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

## Level 4 — Web UI + ops (done)

- **Web UI**: `services/api/static/index.html` served by the API at `/` (health moved to
  `/health`). Same-origin (no CORS); upload + auto-refreshing results table showing the
  `processing → done` flip live. Alternative not taken: static hosting on GCS/Firebase
  (would need CORS on the API).
- **Least-privilege SAs** (retired shared `roles/editor`):
  - `docintel-api-sa` → `storage.objectCreator` (bucket), `datastore.user`, `aiplatform.user`
  - `docintel-processor-sa` → `datastore.user`, `aiplatform.user`, `eventarc.eventReceiver`,
    plus `run.invoker` on its own service (needed for the Eventarc trigger to invoke it).
    Notably needs **no** storage role — Vertex's agent reads the file.
- **Cloud Scheduler**: job `docintel-stats-daily` (cron `0 9 * * *`, ET) calls
  `POST /tasks/stats` via **OIDC** as `docintel-scheduler-sa` (granted `run.invoker` on the
  API). Gotcha: the Cloud Scheduler **service agent** needed
  `roles/iam.serviceAccountTokenCreator` on the scheduler SA to mint the OIDC token.
- **Cloud Monitoring**: uptime check on `/health` (5-min, multi-region) + email
  notification channel + alert policy "DocIntel API down".
  - **Gotcha**: originally used `/healthz`, which Google's Front End reserves and
    intercepts before the container — the route existed in the app but was unreachable
    externally (404), so the check failed and the alert fired. Renamed to `/health`.
- **Identity count so far** (a running theme): user/ADC, API SA, processor SA, scheduler SA,
  Cloud Storage service agent, Vertex AI service agent, Cloud Scheduler service agent.

## Level 5 — Production polish (done)

- **Go rewrite (done)**: the processor is reimplemented in Go (`services/processor-go`)
  and deployed to the *same* Cloud Function (`docintel-processor`, runtime `go126`,
  same Pub/Sub trigger + `docintel-processor-sa`), replacing the Python one. The Python
  version stays in `services/processor/` as the "before". Writes the same snake_case
  Firestore fields so the API/UI are unaffected — a clean, drop-in language swap.
  - Why Go: ~10x smaller container, faster cold starts, compile-time type safety.
  - Local testing: `cmd/main.go` runs it via the Functions Framework; excluded from the
    deploy upload via `.gcloudignore` (an extra `package main` would break the build).
- **Cloud Build CI/CD (done)**: `cloudbuild.yaml` (docker build → push to Artifact
  Registry → `gcloud run deploy` the API, image tagged by `$SHORT_SHA`) + a GitHub
  trigger `docintel-api-deploy` on push to `main`. Runs as a dedicated least-privilege
  `docintel-cicd-sa` (run.developer, artifactregistry.writer, logging.logWriter, +
  serviceAccountUser on `docintel-api-sa`). Org policy *required* a user-managed build
  SA — good default. This is Continuous **Deployment** (no approval gate). Next step to
  strengthen it: add a `go test` / `pytest` stage before deploy.
- **Terraform (done, `infra/`)**: `main.tf` + `variables.tf`. Created a **dead-letter
  topic** `document-uploads-dlq` from code, and **imported** the existing
  `document-uploads` topic so Terraform manages it too (`plan` → no changes = code
  matches reality). Demonstrated the full loop: write → init → plan → apply → import.
  Local state (`terraform.tfstate`, gitignored); production would use a remote GCS
  backend. Caution: this state now owns the live topic, so `terraform destroy` would
  delete it.
  - Not yet codified (future work): bucket, notification, SAs + all IAM, scheduler,
    monitoring — the same patterns extended to the rest of the stack.

## Identities in the system (a running theme)

user/ADC · `docintel-api-sa` · `docintel-processor-sa` · `docintel-scheduler-sa` ·
`docintel-cicd-sa` · Cloud Storage service agent · Vertex AI service agent ·
Cloud Scheduler service agent · Pub/Sub service agent. Each has only the permissions
it needs — the least-privilege story end to end.
