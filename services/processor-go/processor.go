// Package processor is a Cloud Function (2nd gen) that analyzes uploaded
// documents with Gemini and writes the results to Firestore. It is triggered by
// the Pub/Sub message that Cloud Storage publishes when a file is uploaded.
package processor

import (
	"context"
	"encoding/json"
	"fmt"
	"log"
	"os"
	"strings"
	"time"

	"cloud.google.com/go/firestore"
	"github.com/GoogleCloudPlatform/functions-framework-go/functions"
	"github.com/cloudevents/sdk-go/v2/event"
	"google.golang.org/genai"
)

// Configuration, read once from the environment (with sensible fallbacks).
var (
	projectID = envOr("PROJECT_ID", "docintel-srg-2026")
	location  = envOr("REGION", "us-central1")
	model     = envOr("MODEL", "gemini-2.5-flash")
)

const analysisPrompt = "You are a document analyst. Analyze the attached document and produce: " +
	"a concise 2-3 sentence summary; up to 6 key entities (people, organizations, dates, " +
	"monetary amounts, locations); and a short document-type label (e.g. invoice, resume, " +
	"contract, article, email)."

// envOr returns the environment variable named key, or fallback if it is unset.
func envOr(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}

func init() {
	functions.CloudEvent("ProcessUpload", processUpload)
}

// PubSubMessage is the envelope the Pub/Sub CloudEvent carries.
type PubSubMessage struct {
	Message struct {
		Data []byte `json:"data"` // []byte => auto base64-decoded from the JSON string
	} `json:"message"`
}

// GCSObject is the subset of the Cloud Storage object metadata we need.
type GCSObject struct {
	Bucket      string `json:"bucket"`
	Name        string `json:"name"`
	ContentType string `json:"contentType"`
}

// DocAnalysis is the structured result we force Gemini to return.
type DocAnalysis struct {
	Summary  string   `json:"summary"`
	Entities []string `json:"entities"`
	DocType  string   `json:"docType"`
}

// processUpload is invoked once per Pub/Sub message.
func processUpload(ctx context.Context, e event.Event) error {
	var msg PubSubMessage
	if err := e.DataAs(&msg); err != nil {
		return fmt.Errorf("parsing CloudEvent: %w", err)
	}

	var obj GCSObject
	if err := json.Unmarshal(msg.Message.Data, &obj); err != nil {
		return fmt.Errorf("parsing GCS metadata: %w", err)
	}

	parts := strings.Split(obj.Name, "/")
	if len(parts) < 3 || parts[0] != "uploads" {
		log.Printf("skipping non-upload object: %s", obj.Name)
		return nil
	}
	docID := parts[1]
	gcsURI := fmt.Sprintf("gs://%s/%s", obj.Bucket, obj.Name)
	log.Printf("processing docID=%s uri=%s", docID, gcsURI)

	// Create the Gemini client (Vertex AI backend, authed by the runtime SA).
	client, err := genai.NewClient(ctx, &genai.ClientConfig{
		Backend:  genai.BackendVertexAI,
		Project:  projectID,
		Location: location,
	})
	if err != nil {
		return fmt.Errorf("creating genai client: %w", err)
	}

	// Constrain the model to return JSON matching DocAnalysis.
	config := &genai.GenerateContentConfig{
		ResponseMIMEType: "application/json",
		ResponseSchema: &genai.Schema{
			Type: genai.TypeObject,
			Properties: map[string]*genai.Schema{
				"summary":  {Type: genai.TypeString},
				"entities": {Type: genai.TypeArray, Items: &genai.Schema{Type: genai.TypeString}},
				"docType":  {Type: genai.TypeString},
			},
			Required: []string{"summary", "entities", "docType"},
		},
	}

	// The file (read straight from GCS by Vertex) plus the prompt.
	contents := []*genai.Content{
		genai.NewContentFromParts([]*genai.Part{
			genai.NewPartFromURI(gcsURI, obj.ContentType),
			genai.NewPartFromText(analysisPrompt),
		}, genai.RoleUser),
	}

	resp, err := client.Models.GenerateContent(ctx, model, contents, config)
	if err != nil {
		return fmt.Errorf("gemini generate: %w", err)
	}

	var analysis DocAnalysis
	if err := json.Unmarshal([]byte(resp.Text()), &analysis); err != nil {
		return fmt.Errorf("parsing analysis JSON: %w", err)
	}

	// Write results back to the SAME Firestore doc the API created.
	// Field names match the Python version (snake_case) so the API/UI read them.
	db, err := firestore.NewClient(ctx, projectID)
	if err != nil {
		return fmt.Errorf("creating firestore client: %w", err)
	}
	defer db.Close()

	_, err = db.Collection("documents").Doc(docID).Set(ctx, map[string]any{
		"summary":      analysis.Summary,
		"entities":     analysis.Entities,
		"doc_type":     analysis.DocType,
		"status":       "done",
		"processed_at": time.Now().UTC(),
	}, firestore.MergeAll)
	if err != nil {
		return fmt.Errorf("writing firestore: %w", err)
	}

	log.Printf("done docID=%s type=%s", docID, analysis.DocType)
	return nil
}
