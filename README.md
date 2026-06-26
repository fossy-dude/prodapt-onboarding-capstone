# 1. SBOAI Capstone

**AI-Powered Prepaid Billing System** — subscriber self-care portal, CDR billing pipeline, fraud detection, ops/marketing dashboards, and a multi-agent self-care chatbot.

This README is focussed on setup and getting started. For other information, refer to:

- [User Roles & User Journeys](docs/user_journeys.md)
- Architecture diagrams: ([Target State](docs/architecture_target.jpg), [MVP](docs/architecture_mvp.jpg))
- [Detailed system design & data flow](docs/bmad_output/planning-artifacts/architecture.md)

> *Note: The below steps are for setting up a MVP scoped only (Refer to [Decisions](docs/DECISIONS.md) for viewing the differences and rationale for the same). Target State instructions to be created*

---

## 1.1. Prerequisites

Install these once on your machine:

- **Podman** & **Podman-compose** (For container-based setups)
- **just** — cross-platform task runner ([install](https://github.com/casey/just))

(Optional) For contributors:
  - **uv** — Python package/environment manager ([install](https://docs.astral.sh/uv/))
  - **Node.js 20+** and **npm** — for the React/Vite frontend

---

## 1.2. MVP Setup — Local Podman Compose

Each phase depends on the previous; do not reorder.

### 1.2.1. Clone and Configure Environment

```bash
git clone <repo-url> sboai_capstone
cd sboai_capstone

# Copy and define configurations
cp docker/.env.example docker/.env
cp frontend/.env.example frontned/.env
cp service_webapp/.env.example service_webapp/.env
cp cdr-pipeline/.env.example cdr-pipeline/.env

# Edit each of the dotenv files - set every password and API key (placeholders are NOT secrets).
# stack reads its env vars from there
```

### 1.2.2. Start Infrastructure Containers & Application Services

Option 1) Start everything in 1 shot

```bash
just up
# Starts: cdr-pipeline, service_webapp (Milvus Lite embedded), frontend.

```

Option 2) Spin up just the dependencies (to run in dev mode)

```bash
just deps
# Starts all dependent services via podman-compose: Postgres (init scripts: extensions + roles/users), Redpanda, Valkey,
#         LangFuse, MiniStack, OTEL-TUI, Fluentd.
# Postgres init scripts under docker/postgres/init/ run automatically on first start.
# Postgres migrations are run
# Provisions MiniStack Cognito (user pool, role groups, app client, demo test users)
# Vector storage, Postgres are seeded

# Now start the respective service in dev mode
just run-dev-frontend #Start frontned
just run-dev-backend #Backend
just run-dev-cdr #CDR Pipeline
```

### 1.2.3. Access the Application

```bash
# Frontend URL
open http://localhost:5173           # React frontend

# Health check endpoints
curl http://localhost:8000/health    # service_webapp (Story 1.4)
curl http://localhost:8001/health    # cdr-pipeline management API (Epic 2)
```

#### Default Login URLs and User Access

**All users login at the same URL:**

- **Login:** `http://localhost:5173/login`
- **Registration:** `http://localhost:5173/register` (for new subscribers)

**After login, users are redirected based on their role:**

| Role                    | Portal URL      | Description                                                              |
| ----------------------- | --------------- | ------------------------------------------------------------------------ |
| **Subscriber**          | `/subscriber/*` | Self-care portal (dashboard, recharge, plans, profile, chatbot)          |
| **Dev**                 | `/simulator/*`  | Dev tools (Notification Portal, SIM activation simulator, CDR simulator) |
| **Ops/Admin/Marketing** | `/ops/*`        | Operations dashboards                                                    |
| **Fraud**               | `/fraud/*`      | Fraud investigation tools                                                |

**Test Users for Non-Subscriber Roles:**

Login using these **usernames** (passwordless OTP — OTP appears on the Notification Portal):

| Username    | Role            | Phone Number (for reference) |
| ----------- | --------------- | ---------------------------- |
| `dev`       | dev             | +91999900000                 |
| `admin`     | admin → ops     | +91999900001                 |
| `marketing` | marketing → ops | +91999900002                 |
| `ops`       | ops             | +91999900003                 |
| `fraud`     | fraud           | +91999900004                 |

**To login as a test user — first bootstrap:**

> [!tldr] This process helps solve the chicken-and-egg problem in `dev` environments (without SMS service): To view OTP securely, you need to login first. To login, you need to see the OTP

Break the cycle with the dev-open flag:

1. Add `NOTIFICATION_PORTAL_OPEN_IN_DEV=true` to `service_webapp/.env` and restart the backend (`just backend`).
2. Open `http://localhost:5173/simulator/notifications` — it now accepts anonymous connections.
3. In a new tab, go to `http://localhost:5173/login` and enter the username (e.g. `dev`).
4. Click "Continue" — the OTP appears as a `LOGIN_OTP` row on the Notification Portal tab.
5. Copy the 6-digit code and enter it in the login form.
6. After your first login you can turn the flag off (the Notification Portal will then require the `dev` JWT).

**Alternative — read OTP from Redpanda directly (no flag needed):**

```bash
podman exec redpanda rpk topic consume notification.events -n 5
```

**Subscriber Login:**

- **Pre-activation:** Enter Registration ID (format: `REG-YYYYMMDD-xxxxxxxx`)
- **Post-activation:** Enter MSISDN (mobile number, national format e.g. `9876543210`)
- OTP appears on the Notification Portal or via `rpk` as above

**Notification Portal — View All SMS OTPs and Notifications:**

- URL: `http://localhost:5173/simulator/notifications`
	- Normally requires: `dev` role JWT
	- With `NOTIFICATION_PORTAL_OPEN_IN_DEV=true`: accessible without a token (dev bootstrap only)
	- Shows: all `LOGIN_OTP`, `SIM_ACTIVATION`, and other notification events in real-time

---

## 1.3. Development Workflow

```bash
just test       # run tests for service_webapp, frontend and cdr-pipeline (sequentially)
just lint       # ruff lint + format check + pyrefly on both Python codebases + ESLint for frontend
just tox        # full quality gate (lint + typecheck + test) for both Python codebases
just format     # auto-format both Python codebases (ruff format) & frontend (prettier)
```

### 1.3.1. Project Layout (MVP)

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

## 1.4. Troubleshooting

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