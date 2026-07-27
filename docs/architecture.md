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

## Level 1 — API + AI (next)

Planned: a Python/FastAPI service on **Cloud Run** exposing `/ask`, which calls
**Vertex AI (Gemini)**. First we enable `run`, `aiplatform`, `artifactregistry`,
`cloudbuild` APIs and fix the ADC quota project.
