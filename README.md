# DocIntel — Serverless AI Document Intelligence on GCP

A learning + showcase project: upload a document → an AI model (Gemini via Vertex AI)
extracts a summary, key entities, and answers questions → results are stored and
queryable via an API and a small web UI. Built **level by level** to demonstrate real
cloud architecture, not a single script.

## Target architecture

```
Web UI → Cloud Run API (Python/FastAPI) → Cloud Storage (upload)
             ↓ event
          Pub/Sub → Cloud Function → Vertex AI (Gemini) → Firestore (results)
Foundation: Cloud Build CI/CD · Terraform IaC · Cloud Monitoring
```

## Roadmap

| Level | Focus | Key services |
|-------|-------|--------------|
| L0 | Foundations | Project, billing, budget, APIs, repo |
| L1 | API + AI | Cloud Run, Vertex AI (Gemini), Artifact Registry |
| L2 | Storage | Cloud Storage, Firestore |
| L3 | Async | Pub/Sub, Cloud Functions |
| L4 | Frontend + ops | Web UI, Cloud Scheduler, Monitoring |
| L5 | Production polish | Go rewrite, Cloud Build CI/CD, Terraform |

## Progress log

- [x] **L0.1** gcloud verified, active config understood
- [x] **L0.2** Dedicated project created (`docintel-srg-2026`)
- [x] **L0.3** gcloud default project set
- [x] **L0.4** Billing account linked
- [x] **L0.5** Billing Budget API enabled
- [x] **L0.6** $10/month budget with 50/90/100% alerts
- [x] **L0.7** Local repo scaffolded + first commit + pushed to GitHub
- [x] **L1.1** Enabled Cloud Run + Vertex AI + Artifact Registry + Cloud Build APIs
- [x] **L1.2** Fixed ADC quota project so local code can call Vertex AI
- [x] **L1.3** FastAPI `/ask` endpoint calling Gemini (tested locally)
- [x] **L1.4** Containerized (Dockerfile) + deployed to Cloud Run — **live**
- [x] **L2.1** Enabled Cloud Storage + Firestore APIs
- [x] **L2.2** Created bucket `docintel-srg-2026-uploads` (uniform access, private)
- [x] **L2.3** Created Firestore (Native mode, `us-central1`)
- [x] **L2.4** `/upload` endpoint: GCS store + Gemini structured analysis + Firestore persist; `/documents` list & get
- [x] **L2.5** Granted Vertex AI service agent read on bucket; redeployed — **live**
- [x] **L3.1** Enabled Pub/Sub + Cloud Functions + Eventarc APIs
- [x] **L3.2** Created Pub/Sub topic `document-uploads`
- [x] **L3.3** Granted Cloud Storage service agent publish rights on the topic
- [x] **L3.4** Wired bucket → topic notification (OBJECT_FINALIZE); observed a live message
- [x] **L3.5** Wrote the processor Cloud Function (`services/processor`)
- [x] **L3.6** Deployed the function (gen2, Pub/Sub-triggered) — **ACTIVE**
- [x] **L3.7** Made `/upload` async (store + `status: processing`, returns instantly)
- [x] **L3.8** Verified async flow end-to-end (upload → queue → function → Firestore `done`)
- [x] **L4.1** Web UI served by the API (upload + live status + results browser)
- [x] **L4.2** Least-privilege service accounts for API & function (retired `roles/editor`)
- [x] **L4.3** Cloud Scheduler daily stats job (OIDC-authenticated) + `/tasks/stats`, `/stats`
- [x] **L4.4** Cloud Monitoring: uptime check on `/healthz` + email alert policy
- [ ] **L5** begins: Go rewrite + Cloud Build CI/CD + Terraform  ← you are here

## Key identifiers

| Thing | Value |
|-------|-------|
| Project ID | `docintel-srg-2026` |
| Project number | `825091457104` |
| Region / zone | `us-central1` / `us-central1-a` |
| Billing account | `013472-F66E24-373390` |
| Live API URL | https://docintel-api-825091457104.us-central1.run.app |

## Layout

```
.
├── services/   # Cloud Run services & functions (code arrives in L1+)
├── infra/      # Terraform / infrastructure-as-code (L5)
├── docs/       # architecture notes
└── scripts/    # helper shell scripts
```
