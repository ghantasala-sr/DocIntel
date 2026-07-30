// Command main runs the processor locally via the Functions Framework.
// It is NOT used in deployment — Cloud Functions generates its own main.
// (Excluded from the deploy upload via .gcloudignore.)
package main

import (
	"log"
	"os"

	"github.com/GoogleCloudPlatform/functions-framework-go/funcframework"

	// Blank import: we import this package ONLY for its side effect — its init()
	// runs and registers "ProcessUpload". We use no names from it, so `_` avoids
	// the "imported and not used" compile error.
	_ "github.com/ghantasala-sr/docintel/processor-go"
)

func main() {
	port := os.Getenv("PORT")
	if port == "" {
		port = "8080"
	}
	// Starts an HTTP server that turns the registered CloudEvent function into an
	// endpoint — exactly what Cloud Functions does for us in production.
	if err := funcframework.Start(port); err != nil {
		log.Fatalf("funcframework.Start: %v", err)
	}
}
