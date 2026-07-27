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
- [ ] **L0.7** Local repo scaffolded + first commit  ← you are here
- [ ] **L1** begins: enable Cloud Run + Vertex AI APIs, fix ADC quota project

## Key identifiers

| Thing | Value |
|-------|-------|
| Project ID | `docintel-srg-2026` |
| Project number | `825091457104` |
| Region / zone | `us-central1` / `us-central1-a` |
| Billing account | `013472-F66E24-373390` |

## Layout

```
.
├── services/   # Cloud Run services & functions (code arrives in L1+)
├── infra/      # Terraform / infrastructure-as-code (L5)
├── docs/       # architecture notes
└── scripts/    # helper shell scripts
```
