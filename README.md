# SBOAI Capstone

**AI-Powered Prepaid Billing System** — subscriber self-care portal, CDR billing pipeline, fraud detection, ops/marketing dashboards, and a multi-agent self-care chatbot.

> **Status:** MVP in progress (Epic 1 — Core Infrastructure, Tooling & Subscriber Identity).
> The MVP runs entirely on local Podman Compose. The Target State (AWS/EKS) section
> below is a stub and is filled in by later epics.

This README is the single authoritative onboarding document. It follows the setup
sequence defined in `docs/bmad_output/planning-artifacts/architecture.md` §1.15.1.
For the system design, see [`architecture.md`](docs/bmad_output/planning-artifacts/architecture.md)
and the diagrams in [`docs/architecture_diagrams.md`](docs/architecture_diagrams.md).

---

## 1. Prerequisites

Install these once on your machine:

- **Podman** — One of:
  - **Podman Desktop** (bundles `podman` and `podman-compose` together; easiest for Mac/Windows), OR
  - **Podman Engine** + manually install the `podman-compose` plugin (for Linux; more control)
- **just** — cross-platform task runner ([install](https://github.com/casey/just))
- **uv** — Python package/environment manager ([install](https://docs.astral.sh/uv/))
- **Node.js 20+** and **npm** — for the React/Vite frontend
- **Flyway CLI** — for manual database migrations (the compose stack also runs a Flyway sidecar automatically)

Target State only (later epics):

- **Terraform ≥ 1.7**, **AWS CLI v2**, **kubectl**, **helm**

---

## 2. MVP Setup — Local Podman Compose

Each phase depends on the previous; do not reorder.

### 2.1 Clone and configure environment

```bash
git clone <repo-url> sboai_capstone
cd sboai_capstone
cp .env.example docker/.env
# Edit docker/.env: set every password and API key (placeholders are NOT secrets).
# The justfile passes --env-file docker/.env to podman compose, so the compose
# stack reads its env vars from there. (.env.example itself stays at the repo root.)
```

### 2.2 Start infrastructure containers

```bash
just deps
# Starts: Postgres (init scripts: extensions + roles/users), Redpanda, Valkey,
#         LangFuse, MiniStack, OTEL-TUI, Fluentd.
# Postgres init scripts under docker/postgres/init/ run automatically on first start.
# Wait for the Postgres healthcheck to pass before continuing.
# After the stack is up, `just deps` also provisions MiniStack Cognito (user pool,
# role groups, app client, demo test users) — re-runnable via `just provision-cognito`.
# Pool/client IDs are written to service_webapp/.env; seeded users are listed in the
# "MiniStack Cognito" section maintained at the end of this README.
```

### 2.3 Run database migrations

```bash
just migrate
# Flyway applies service_webapp/db/migrations/V1.. in order against the `sboai` database.
# Requires Postgres to be healthy (step 2.2). The compose Flyway sidecar also applies
# these automatically on `just up`, so this manual step is optional but explicit.
```

> **MVP note:** only `V1__baseline_schema.sql` and `V2__modified_at_trigger.sql` exist
> today (Story 1.2). V3–V5 land in later stories; `just migrate` is a no-op for the
> not-yet-authored migrations.

### 2.4 Generate and seed synthetic data

```bash
just seed          # 1K plans -> 300K subscribers -> 5M CDRs (in that order) — Epic 2
just seed-milvus   # ingest FAQ, plan and SOP documents into Milvus Lite — Epic 2
```

> **MVP note:** the synthetic-data and Milvus-seed scripts land in Epic 2. The recipes
> are wired now (they fail gracefully with a clear message until the scripts exist).

### 2.5 Start application services

```bash
just up
# Starts: cdr-pipeline, service_webapp (Milvus Lite embedded), frontend.
```

### 2.6 Verify

```bash
curl http://localhost:8000/health    # service_webapp (Story 1.4)
curl http://localhost:8001/health    # cdr-pipeline management API (Epic 2)
open http://localhost:5173           # React frontend
```

> **MVP note:** `/health` is implemented in Story 1.4 and the cdr management API in
> Epic 2 (story 2-5). Until then these endpoints are not yet live.

---

## 3. Target State Setup — AWS

> **Stub.** Provisioned by later epics. Outline (from architecture §1.15.1):

1. Bootstrap Terraform state backend (S3 bucket `sboai-terraform-state-ap-south-1` + DynamoDB lock table).
2. `terraform apply` in `infrastructure/terraform/environments/{dev,prod}` (VPC, EKS, RDS, MSK, ElastiCache Valkey, Cognito, S3, CloudFront, API Gateway, Secrets Manager).
3. `aws eks update-kubeconfig --region ap-south-1 --name sboai-eks`.
4. Migrate RDS (`just migrate-prod`).
5. Seed RDS + Milvus Distributed (`just seed-prod`, `just seed-milvus-prod`).
6. `helm upgrade --install` the services to EKS.
7. Deploy frontend to S3 + CloudFront.

---

## 4. Development Workflow

```bash
just test       # run service_webapp tests
just test-cdr   # run cdr-pipeline tests
just test-fe    # run frontend tests (Vitest)
just lint       # ruff lint + format check + pyrefly on both Python codebases
just lint-fe    # ESLint on the frontend
just tox        # full quality gate (lint + typecheck + test) for both Python codebases
just format     # auto-format both Python codebases (ruff format)
```

### Project layout (MVP)

```
sboai_capstone/
├── service_webapp/   # FastAPI backend (auth, agents, recharge, dashboards). src/ layout.
├── cdr-pipeline/     # CDR ingestion + balance engine + fraud pre-screener. src/ layout.
├── frontend/         # React 18 + Vite + TypeScript + Tailwind (Vitest).
├── docker/           # Podman Compose stacks + Postgres init + OTEL/Fluentd config.
├── docs/             # architecture, diagrams, feature list, schemas.
├── justfile          # cross-platform task runner (run `just --list`).
└── .env.example      # all required environment keys (copy to docker/.env).
```

The quality gate is **tox run through `uv`** (`uvx --with tox-uv tox`). It is invoked
identically by `just` locally and by the GitHub Actions workflows on every PR
(`ci-pipeline.yml`, `ci-cdr.yml`). Make those checks **required** in GitHub branch
protection so no PR merges with a red gate.

---

## 5. Troubleshooting

```text
# Postgres init scripts didn't run: wipe the postgres_data volume and restart deps.
just down && podman volume rm sboai_capstone_postgres_data && just deps

# Milvus Lite data lost: re-seed it.
just seed-milvus

# Redpanda topic missing: topics are auto-created on consumer start — run `just deps`.

# `uv tox` not found: `uv tox` is not a real `uv` subcommand. The project uses
# `uvx --with tox-uv tox` (exposed via `just tox` / `just lint`). No global install needed.

# A `just seed*` recipe prints an "Epic 2" message: expected — the scripts don't exist yet.
```

<!-- BEGIN COGNITO PROVISIONING -->
### MiniStack Cognito — provisioned resources & seeded test users

Provisioned by `scripts/provision_cognito.py` (run automatically by `just deps`).
Idempotent — re-running refreshes this section.

- **User Pool:** `sboai-subscribers` — ID: `ap-south-1_RqEFMnEjO`
- **App Client:** `sboai-webapp` — ID: `RnxOQc5rB5ITY8abDvwVbvhXen`
- **Endpoint / region:** `http://localhost:4566` / `ap-south-1` (MiniStack / LocalStack)
- **Auth model:** passwordless Custom Auth Flow (Story 1.8). Roles surface as the
  `cognito:groups` claim — the backend auth layer reads `cognito:groups`, not `role`.
- **No SNS in MVP:** login OTP is published to the Redpanda `notification.events`
  stream and surfaced on the Notification Portal (Story 1.8 / Notification-Portal epic).

Seeded test users (one per non-subscriber role; subscriber users come from registration):

| Username | Role (group) | `sub` |
| --- | --- | --- |
| `dev` | dev | `f3541185-7e81-4bd4-bd0f-8b0c7d2eab15` |
| `admin` | admin | `ac2345c2-8fc6-4662-81ea-98c4bc89391e` |
| `marketing` | marketing | `71bfa6a1-affd-49fd-be9c-a7b312146d90` |
| `ops` | ops | `257bb97c-dcef-4ee1-8872-0ba610314656` |
| `fraud` | fraud | `ce1a12bd-1d8b-4124-a09f-9a6e23626036` |
<!-- END COGNITO PROVISIONING -->
