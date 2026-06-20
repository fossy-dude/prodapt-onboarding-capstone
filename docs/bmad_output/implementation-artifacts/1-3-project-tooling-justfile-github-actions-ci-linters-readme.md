# Story 1.3: Project Tooling — justfile, GitHub Actions CI, Linters & README

Status: ready-for-dev

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As a **developer**,
I want a cross-platform task runner, automated CI pipeline, and configured linters so that all contributors run identical commands regardless of OS and every PR is validated before merge,
so that code quality is enforced automatically and onboarding requires no tribal knowledge.

## Acceptance Criteria

1. **Given** the project root exists with both `cdr-pipeline/` and `service_webapp/` codebases, **When** the tooling is configured, **Then** the `justfile` defines these commands: `just deps`, `just up`, `just migrate`, `just seed`, `just seed-milvus`, `just test`, `just lint` (ARCH-18).
2. ruff is configured in `pyproject.toml` with lint + format rules for both Python codebases; pyrefly is configured for static type checking (ARCH-20).
3. ESLint + TypeScript strict mode are configured in `frontend/`; Vitest is configured for unit tests (ARCH-20).
4. A GitHub Actions workflow runs `uv tox` on every PR executing: lint, typecheck, test — all three must pass before merge (ARCH-19).
5. `README.md` at project root contains: Prerequisites section, MVP Setup (6 steps: clone → deps → up → migrate → seed → open — per architecture §1.15.1), Target State Setup section stub, architecture diagram reference (ARCH-30).
6. `.env.example` is committed with all required environment variable keys; `.env` is gitignored (ARCH-17).
7. Running `just lint` and `just tox` succeeds locally against the current state of both Python codebases and the frontend (a green baseline), and the GitHub Actions workflow runs the same `uv tox` gate.

## Tasks / Subtasks

- [ ] **Task 1: Author the cross-platform justfile** (AC: #1)
  - [ ] Replace the existing stub `justfile` (currently only has a no-op `format` recipe) at the project root
  - [ ] `set windows-shell := ["powershell.exe", "-NoLogo", "-Command"]` for Windows compatibility
  - [ ] Define the required recipes (see Dev Notes "justfile reference") including `deps`, `up`, `down`, `logs`, `migrate`, `seed`, `seed-milvus`, `test`, `test-cdr`, `lint`, `format`, `tox`, plus backend/frontend/cdr dev runners
  - [ ] `seed`/`seed-milvus` may point at scripts that do not yet exist (Epic 2) — recipe definitions are required now; the scripts they call land later. Add a clear echo/guard so an early invocation fails gracefully, not cryptically.
- [ ] **Task 2: Configure Python linting/typing/testing in both codebases** (AC: #2, #7)
  - [ ] `service_webapp/pyproject.toml` — align ruff + pyrefly + tox config to the reference (`docs/Ref-Linting-config-pyproject.toml`); see "Lint config reconciliation" in Dev Notes
  - [ ] Create `cdr-pipeline/pyproject.toml` with the same ruff/pyrefly/tox config and the `dev`/`test` extras
  - [ ] Ensure tox env names are consistent across both codebases and match what CI invokes
  - [ ] Verify `uv tox -e lint` and `uv tox -e <test-env>` run green in `service_webapp/` (it has a real `main.py`) and in `cdr-pipeline/` (may be a stub `src/` + a placeholder test)
- [ ] **Task 3: Configure frontend ESLint + TS strict + Vitest** (AC: #3, #7)
  - [ ] `frontend/` already has `eslint.config.js`, `tsconfig.json`, `vite.config.ts`, `vitest.config.ts`. Verify TypeScript `strict: true` is enabled in `tsconfig.json`
  - [ ] Ensure `npm run lint` and `npm run test` scripts exist in `frontend/package.json` and run green
  - [ ] Do NOT restructure `frontend/src` here (that is Story 1.7); only ensure the lint/type/test toolchain is configured and green
- [ ] **Task 4: Author GitHub Actions CI workflow** (AC: #4)
  - [ ] `.github/workflows/ci-pipeline.yml` — on every PR, run `uv tox` (all envs: lint, typecheck, test) for `service_webapp/`; all must pass to merge
  - [ ] `.github/workflows/ci-cdr.yml` — CDR-pipeline-specific `uv tox` run for `cdr-pipeline/`
  - [ ] Include a frontend job (or step) running `npm ci && npm run lint && npm run test` in `frontend/`
  - [ ] Use `astral-sh/setup-uv` (or equivalent) to install `uv`; set up Node 20 for the frontend job
- [ ] **Task 5: Author root README.md** (AC: #5)
  - [ ] Replace the current stub (`# prodapt-onboarding-capstone`)
  - [ ] Follow the exact section structure in architecture §1.15.1: Prerequisites, MVP Setup (2.1–2.6), Target State stub (section 3), Development Workflow (section 4), Troubleshooting (section 5)
  - [ ] Reference the architecture diagram (`docs/architecture_diagrams.md`) and `architecture.md`
  - [ ] Use `service_webapp` (not `app-backend`/`service_backend`) for backend command examples — reconcile the architecture's `service_backend` naming to the actual `service_webapp` dir
- [ ] **Task 6: Author `.env.example` and confirm `.gitignore`** (AC: #6)
  - [ ] `.env.example` at project root with ALL required keys (see "Environment variable keys" in Dev Notes), placeholder values only
  - [ ] Confirm `.env` is gitignored (the repo `.gitignore` exists — verify it covers `.env`)
- [ ] **Task 7: Green-baseline verification** (AC: #7)
  - [ ] Run `just lint` and `just tox` locally; capture output in Debug Log References
  - [ ] Confirm the GitHub Actions workflow YAML is valid and invokes the same `uv tox` gate

## Dev Notes

### Scope boundary

- **DOES:** justfile, ruff/pyrefly config for both Python codebases, frontend lint/type/test toolchain config, GitHub Actions CI, README, `.env.example`.
- **DOES NOT:** Implement app code, write Podman Compose (Story 1.2), implement health endpoints (Story 1.4), or restructure `frontend/src` (Story 1.7). The synthetic-data and Milvus seed *scripts* are Epic 2 — only their `just` recipes are defined here.

### RESOLVED directory & naming decisions

- Backend dir is `service_webapp/` (NOT `app-backend/`). `cdr-pipeline/` is created in this story (at least `pyproject.toml` + a stub `src/` + tox config) so CI has something to run. [user decision 2026-06-19]
- Architecture's README snippet says `service_backend` and `app-backend` interchangeably — both mean the actual `service_webapp/` dir. Normalise to `service_webapp` in the README and justfile.

### justfile reference (cross-platform — adapt from architecture §1.12.2)

```just
set windows-shell := ["powershell.exe", "-NoLogo", "-Command"]

deps:         podman compose -f docker/docker-compose-dependencies.yaml up -d
up:           podman compose -f docker/docker-compose.yaml up -d
down:         podman compose -f docker/docker-compose.yaml down
logs:         podman compose -f docker/docker-compose.yaml logs -f
restart svc:  podman compose -f docker/docker-compose.yaml restart {{svc}}

backend:      cd service_webapp && uvicorn src.main:app --reload --port 8000
frontend:     cd frontend && npm run dev
cdr:          cd cdr-pipeline && python -m src.main

migrate:      flyway -url=jdbc:postgresql://localhost:5432/sboai -locations=filesystem:service_webapp/db/migrations migrate
seed:         cd service_webapp && python scripts/generate_synthetic_data.py
seed-milvus:  cd service_webapp && bash scripts/seed_milvus.sh

test:         cd service_webapp && uv tox -e test
test-cdr:     cd cdr-pipeline && uv tox -e test
test-fe:      cd frontend && npm run test
tox:          cd service_webapp && uv tox && cd ../cdr-pipeline && uv tox

lint:         cd service_webapp && uv tox -e lint && cd ../cdr-pipeline && uv tox -e lint
format:       cd service_webapp && ruff format src/ && cd ../cdr-pipeline && ruff format src/
lint-fe:      cd frontend && npm run lint
```

Notes:
- Flyway `-url` points at the `sboai` database (architecture §1.15.1 line 1779 shows `sboai`). The architecture §1.12.2 snippet uses port 5432 and DB `sboai` — keep that.
- `seed-milvus` in architecture §1.12.2 mistakenly does `python scripts/seed_milvus.sh` (running a shell script with python). Correct it to `bash scripts/seed_milvus.sh` (or call the Python ingestor directly). Flag this fix in Completion Notes.

[Source: architecture.md#1.12.2 (lines 1260–1288)]

### Lint config reconciliation (IMPORTANT — two configs disagree)

There are **two reference lint configs** in this repo and they differ. Resolve before configuring:

| Setting          | `docs/Ref-Linting-config-pyproject.toml` (the named reference) | `service_webapp/pyproject.toml` (current)        |
| ---------------- | -------------------------------------------------------------- | ------------------------------------------------ |
| `line-length`    | 120                                                            | 100                                              |
| `target-version` | py311                                                          | py311                                            |
| ruff `select`    | large set incl. `D` (pydocstyle numpy), `PL`, `PT`, `PYI`, ... | minimal: `E,W,F,I,B,C4,UP,SIM,RUF`               |
| pydocstyle       | numpy convention                                               | none                                             |
| tox `env_list`   | `["lint", "pytest_fast"]`, `uv-venv-lock-runner`               | `lint, typecheck, test`, `uv-venv-runner`        |
| tox lint cmds    | `ruff check .` + `ruff format --check .` + `pyrefly check`     | `ruff check src/ tests/` + `ruff format --check` |

**Decision needed at implementation time:** `docs/Ref-Linting-config-pyproject.toml` is the architecture-designated reference (architecture §1.11.7 line 948 says "Refer to docs/Ref-Linting-config-pyproject.toml"). **Adopt the Ref config as canonical** (line-length 120, full select set incl. pydocstyle numpy, pyrefly) for BOTH `service_webapp/` and `cdr-pipeline/`, and bring the existing `service_webapp/pyproject.toml` into line with it. Keep the existing dependency list in `service_webapp/pyproject.toml` (it is correct and complete) — only the `[tool.ruff]`/`[tool.pyrefly]`/`[tool.tox]`/`[tool.pytest]` sections change.

> ⚠️ If adopting the full `D`/`PL` rule set causes a large number of failures on `service_webapp/main.py` (currently a trivial stub), it is acceptable to keep the Ref config's existing `ignore` list (it already disables most noisy rules) and add narrow per-file ignores rather than weakening the rule set. The goal of AC #7 is a *green* baseline — achieve it via the Ref config + its ignore list, not by deleting rules.

[Source: architecture.md#1.11.7 (lines 944–970); docs/Ref-Linting-config-pyproject.toml; service_webapp/pyproject.toml]

### Toolchain versions

- Python: the Ref config and `service_webapp/pyproject.toml` both target **py311** (`requires-python = ">=3.11"`). The architecture stack table says "Python 3.14" aspirationally and `service_webapp/.python-version` says `3.13`. **Use `requires-python = ">=3.11"` and ruff `target-version = "py311"`** to match the working reference config; do not chase 3.14. Note the discrepancy in Completion Notes. [Source: Ref-Linting-config-pyproject.toml; service_webapp/.python-version]
- `uv tox` requires the `tox-uv` plugin (`uv-venv-lock-runner`). Ensure both codebases declare it (test extra). [Source: architecture.md#1.3.1, #1.11.7]
- Node 20+ and npm for the frontend (architecture §1.15.1 Prerequisites). [Source: architecture.md#1.15.1, line 1760]

### GitHub Actions specifics

- Workflow files: `.github/workflows/ci-pipeline.yml` (service_webapp), `.github/workflows/ci-cdr.yml` (cdr-pipeline). [Source: architecture.md#1.12.1 (lines 996–998), #1.11.7 (line 970)]
- Triggers: `on: pull_request` (every PR). All `uv tox` envs must pass before merge.
- Use working-directory per job to scope `uv tox` to the right codebase.

### Environment variable keys for `.env.example`

At minimum (gather the full set from architecture §1.11.1 Settings example + §1.12.4 Postgres init):
```dotenv
# Postgres (consumed by docker/postgres/init + Flyway + app)
POSTGRES_SUPERUSER_PASSWORD=change_me_superuser
POSTGRES_APP_PASSWORD=change_me_app
POSTGRES_READONLY_PASSWORD=change_me_readonly
POSTGRES_FLYWAY_PASSWORD=change_me_flyway
# App config (pydantic-settings — Story 1.4)
DB__HOST=localhost
DB__PORT=5432
DB__NAME=sboai
DB__USER=sboai_app
DB__PASSWORD=change_me_app
REDIS_URL=redis://localhost:6379
KAFKA_BROKERS=localhost:9092
AZURE_OPENAI_API_KEY=
LANGFUSE_ENABLED=false
LANGFUSE_HOST=http://localhost:3000
LANGFUSE_SECRET_KEY=
LANGFUSE_PUBLIC_KEY=
```
Cross-reference Story 1.4 (pydantic-settings) and Story 1.5 (LangFuse) so every key those stories read has a placeholder here. Keep it superset-complete; missing keys cause fail-fast crashes at boot. [Source: architecture.md#1.11.1 (lines 730–764); #1.12.4]

### Testing standards summary

- AC #7 (green baseline) is the test: `just lint` and `just tox` must exit 0 locally; the CI YAML must invoke the same gate.
- For `cdr-pipeline/` (new, mostly empty), a single placeholder `tests/test_smoke.py` asserting `True` is acceptable to make the test env pass — do not over-build; Epic 2 fills in real tests.
- Frontend: `npm run test` (Vitest) must exit 0; a single trivial test is acceptable if no components exist yet.
- [Source: architecture.md#1.11.8]

### Project Structure Notes

- Existing stub files to REPLACE: root `justfile` (no-op `format` recipe) and root `README.md` (`# prodapt-onboarding-capstone`).
- Existing frontend tooling files to VERIFY/KEEP: `frontend/eslint.config.js`, `frontend/tsconfig.json`, `frontend/vite.config.ts`, `frontend/vitest.config.ts`. Note `frontend/` currently has BOTH `vite.config.js` and `vite.config.ts` — resolve the duplicate (keep `.ts`, remove `.js`) and note it.
- Existing `service_webapp/pyproject.toml` deps are correct — preserve them; only retune the tooling config sections.
- `cdr-pipeline/` is created fresh in this story.

### References

- [Source: epics.md#Story-1.3 (lines 343–358)]
- [Source: architecture.md#1.11.7-Linting-Formatting-Code-Quality (lines 944–970)]
- [Source: architecture.md#1.12.1-Monorepo-Layout (CI workflow paths, lines 994–998)]
- [Source: architecture.md#1.12.2 (justfile reference, lines 1260–1288)]
- [Source: architecture.md#1.15.1-README-Structure (lines 1745–1841)]
- [Source: docs/Ref-Linting-config-pyproject.toml]
- [Source: service_webapp/pyproject.toml; frontend/{eslint.config.js,tsconfig.json,vite.config.ts,vitest.config.ts}]

## Dev Agent Record

### Agent Model Used

{{agent_model_name_version}}

### Debug Log References

### Completion Notes List

### File List
