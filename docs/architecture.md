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

## Level 2 — Storage (next)

Planned: `POST /upload` stores a file in **Cloud Storage**; document metadata and
Gemini results are persisted in **Firestore** so `/ask` can reference real documents.
