# DocIntel — Architecture Notes

Living document. We add a section per level as we build it, capturing **what** we
deployed and **why** we made each decision (great interview material later).

## Design principles

- **Serverless-first** — scale to zero, pay per use, no servers to patch.
- **Event-driven** — uploads trigger processing asynchronously (decoupled, resilient).
- **One project boundary** — isolated IAM, billing, and cleanup.
- **Enable-as-you-go** — turn on each API only when a level needs it (small attack surface).

## Level 0 — Foundations (done)

- Dedicated project `docintel-srg-2026`, linked to billing.
- $10/month budget with 50/90/100% email alerts (an *alert*, not a hard cap).
- Concept learned: **quota project** — the project API calls are attributed to.
  gcloud CLI creds now use DocIntel; **ADC** (used by app code / client libraries)
  still needs its quota project set — deferred to the start of L1 where it matters.

## Level 1 — API + AI (done)

- Python/FastAPI service on **Cloud Run**: `GET /` health check + `POST /ask` → Gemini.
- Model: `gemini-2.5-flash` via **Vertex AI** (`vertexai=True`, authed by ADC locally,
  by the service account in the cloud).
- Packaged with a **Dockerfile**; deployed via `gcloud run deploy --source` →
  Cloud Build builds the image → Artifact Registry stores it → Cloud Run runs it.
- Live URL: https://docintel-api-825091457104.us-central1.run.app
- Gotcha learned: `--source` deploy needs a **`.gcloudignore`** to make the upload
  deterministic — without it, gcloud's git fallback dropped the Dockerfile and it
  fell back to Buildpacks (build failed on missing entrypoint).
- Security debt (fix in L4/L5): Cloud Run runs as the default compute SA with broad
  `roles/editor`. Should become a dedicated SA with only `roles/aiplatform.user`
  (least privilege). Endpoint is currently public (`--allow-unauthenticated`).

## Level 2 — Storage (done)

- **Cloud Storage** bucket `docintel-srg-2026-uploads` (regional `us-central1`,
  uniform bucket-level access, private) holds the raw uploaded files (objects).
- **Firestore** (Native, `us-central1`) collection `documents` holds one record per
  file: filename, content_type, size, `gcs_uri`, uploaded_at, and Gemini's analysis.
- **`POST /upload`**: store blob → Gemini reads it via `Part.from_uri(gs://...)` and
  returns **schema-constrained JSON** (`response_schema=DocAnalysis`) → persist to
  Firestore. Plus `GET /documents` (list) and `GET /documents/{id}`.
- **Pattern learned**: big blobs → object storage; small structured data → database;
  the DB record just points at the blob via `gs://`.
- **Third identity learned**: passing a `gs://` URI to Gemini makes the **Vertex AI
  service agent** (`service-<num>@gcp-sa-aiplatform`) fetch the object — it needed an
  explicit `roles/storage.objectViewer` grant on the bucket (private-by-default at work).

### Scaling note (e.g. SEC EDGAR filings)
This synchronous loop is the toy core. Production for large filings needs: async
ingest (Pub/Sub on GCS finalize — L3), parsing (Document AI / XBRL), chunking + RAG
(Vertex Vector Search), bulk LLM (Vertex Batch Prediction), and BigQuery analytics.
Key rule: parse exact numbers from XBRL deterministically; use the LLM for narrative.

## Level 3 — Async processing (done)

- **`/upload` is now async**: it stores the object + a Firestore record with
  `status: "processing"` and returns immediately (no AI in the request path).
- **Event flow**: object lands in the bucket → GCS **notification** publishes an
  OBJECT_FINALIZE message to the **Pub/Sub** topic `document-uploads` → the
  **Cloud Function** `docintel-processor` (gen2, `services/processor`) consumes it,
  runs Gemini, and `merge`s `summary`/`entities`/`doc_type`/`status: "done"` into the
  same record.
- **Identities wired**: Cloud Storage service agent granted `roles/pubsub.publisher`
  on the topic; the function runs as the compute SA (Editor); Vertex service-agent
  bucket-read grant from L2 still applies.
- **Decoupling proven**: measured upload→done at ~9s, fully out-of-band — the caller
  never waits on the model. This is what unblocks large/slow documents.
- **Debt (L4/L5)**: trigger has `RETRY_POLICY_DO_NOT_RETRY` — production wants retries
  + a dead-letter topic; still on the broad compute SA (want least privilege).

## Level 4 — Web UI + ops (next)

Planned: a simple web front-end (upload + browse results), **Cloud Scheduler** for
periodic ingest (the EDGAR "pull on a schedule" step), and **Cloud Monitoring**
dashboards/alerts. Likely tighten IAM to a dedicated least-privilege service account.
