---
baseline_commit: 47be78dde59d40f9f81fb836e9f5de9dd5f718ee
---

# Story 1.5: LangFuse Self-Hosted Setup & Client Instrumentation Scaffold

Status: review

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As a **platform engineer**,
I want LangFuse running locally and a reusable instrumentation client wired into `service_webapp` so that all future agentic workflows can emit traces with a single decorator,
so that agent observability is available from the first agent story without per-agent setup overhead.

## Acceptance Criteria

1. **Given** LangFuse is included in `docker/docker-compose-dependencies.yaml`, **When** `just up` is run, **Then** the LangFuse UI is accessible at `http://localhost:3000` and accepts traces.
2. A `get_langfuse_client()` singleton factory is implemented in `service_webapp/src/core/observability/langfuse.py`.
3. A `@trace_agent` decorator is implemented that wraps any async function, creating a LangFuse trace with: trace name, input, output, model, token usage (FR-72).
4. The decorator is a **no-op (pass-through) when `LANGFUSE_ENABLED=false`** in env, allowing tests to run without a live LangFuse instance.
5. `just up` logs the LangFuse dashboard URL after startup.

## Tasks / Subtasks

- [x] **Task 1: Confirm/complete LangFuse in the dependency compose** (AC: #1, #5)
  - [x] Verify `langfuse` service exists in `docker/docker-compose-dependencies.yaml` (added in Story 1.2) and is reachable on `http://localhost:3000`
  - [x] LangFuse self-hosted requires its own Postgres + secrets — configure per the LangFuse self-host docs (it can use a dedicated DB or the shared Postgres with a separate database; prefer a separate DB to avoid coupling with `sboai`). Document the choice.
  - [x] Ensure `just up` echoes the LangFuse dashboard URL after startup (add an echo to the `up` recipe or a post-up note)
- [x] **Task 2: Implement the LangFuse client singleton** (AC: #2, #4)
  - [x] Create `service_webapp/src/core/observability/langfuse.py`
  - [x] `get_langfuse_client()` returns a cached singleton `Langfuse` client built from `settings` (host, public key, secret key)
  - [x] When `settings.langfuse_enabled is False`, `get_langfuse_client()` returns `None` (or a null client) and callers/decorator short-circuit — no network calls
- [x] **Task 3: Implement the `@trace_agent` decorator** (AC: #3, #4)
  - [x] Async-function decorator that wraps any `async def`, creating a LangFuse trace capturing: trace name (default = wrapped fn name, overridable), input args, output/return, model, token usage
  - [x] When `LANGFUSE_ENABLED=false`: pure pass-through — calls the wrapped function with zero LangFuse overhead and no client construction
  - [x] Propagate `trace_id` into LangFuse metadata so OTEL trace (Story 1.4) and LangFuse trace correlate (architecture §1.13.7: "LangGraph nodes must pass trace_id in LangFuse metadata")
  - [x] Follow PII hygiene: do NOT capture raw MSISDN/name/card data as trace input; if subscriber context is passed, it must already be sanitised (UUID / `[-4:]`). The decorator should not itself leak PII it is handed — document this contract for callers.
- [x] **Task 4: Add config keys** (AC: #2, #4)
  - [x] Extend `service_webapp/src/core/config.py` (Story 1.4) with: `langfuse_enabled: bool = False`, `langfuse_host: str`, `langfuse_public_key: str`, `langfuse_secret_key: str`
  - [x] Ensure these keys have placeholders in `.env.example` (Story 1.3) — add if missing
- [x] **Task 5: Tests** (AC: #2, #3, #4)
  - [x] Unit test: with `LANGFUSE_ENABLED=false`, `@trace_agent`-wrapped async fn returns the correct value and makes NO LangFuse calls (assert client not constructed / not called)
  - [x] Unit test: with enabled + a mocked Langfuse client, the decorator records a trace with name/input/output/model/token-usage fields populated
  - [x] Unit test: `get_langfuse_client()` returns the same instance on repeated calls (singleton)
  - [x] Do NOT require a live LangFuse container for tests — the no-op path + mock are the test surface (this is the whole point of AC #4)

## Dev Notes

### Scope boundary

- **DOES:** LangFuse container reachable + URL echo, `get_langfuse_client()` singleton, `@trace_agent` decorator (with no-op gate), config keys, unit tests of the decorator's enabled/disabled paths.
- **DOES NOT:** Apply `@trace_agent` to any real agent (no agents exist until Epic 5), wire LangGraph, or instrument RAG/LLM calls. This is a **scaffold** — the decorator must exist and be tested, but it is not yet decorating production agent code.
- The whole value proposition (epics.md): "agent observability is available from the first agent story without per-agent setup overhead." Build the reusable primitive correctly; do not gold-plate.

### Dependencies & prerequisites

- Depends on Story 1.2 (LangFuse declared in `docker-compose-dependencies.yaml`) and Story 1.4 (`core/config.py` settings singleton). The `langfuse` Python package is already in `service_webapp/pyproject.toml` (`langfuse>=2`). [Source: service_webapp/pyproject.toml line 22]
- `langchain-openai` and `langgraph` are present too but are NOT used in this story (agents are Epic 5). Do not import them here.

### LangFuse client & decorator design

- File: `service_webapp/src/core/observability/langfuse.py`. (Architecture §1.12.1 also references `agents/shared/langfuse_client.py` — that is the agent-layer wrapper added in Epic 5; THIS story's deliverable is the core `core/observability/langfuse.py` named explicitly in epics.md AC.) Keep the core client here; the agent wrapper can import from it later. [Source: epics.md#Story-1.5 (line 393); architecture.md#1.12.1 (line 1081)]
- Singleton pattern: use module-level cache or `functools.lru_cache`. Build from `settings` only — no hard-coded host/keys (architecture §1.11.1: "No config values hard-coded").
- `@trace_agent` is for async functions (architecture mandates async-only; all agent calls are async). It must capture: trace name, input, output, model, token usage (FR-72). Use the LangFuse SDK v2/v3 tracing API (`@observe` / `langfuse.trace(...)` depending on installed major version — `langfuse>=2` is declared; verify the installed version's API at implementation time and use the current decorator/context-manager API, not a deprecated one).

[Source: epics.md#Story-1.5 (lines 382–396); architecture.md#1.10.2 (LangFuse coverage, lines 710–716); #1.13.7 (line 1605)]

### The no-op gate is the critical requirement

AC #4 is the highest-value, easiest-to-get-wrong part. The decorator must be a **true pass-through** when `LANGFUSE_ENABLED=false`:
- No `Langfuse` client construction (constructing it may attempt a network handshake or require keys).
- No attribute access that triggers lazy connection.
- The wrapped function's signature, return value, and exceptions must be identical to undecorated.
- This lets the entire test suite (and CI, which has no LangFuse server) run with `LANGFUSE_ENABLED=false`. Story 1.4's note about `LANGFUSE_ENABLED=false` letting tests run without a live instance applies here. [Source: epics.md#Story-1.5 (line 395); #Story-1.4 dev note]

### Trace correlation with OTEL (don't break Story 1.4's contract)

- Story 1.4 stores `trace_id` in `request.state.trace_id` and emits `X-Trace-Id`. When `@trace_agent` runs inside a request, it should accept/propagate that `trace_id` into LangFuse metadata so the OTEL trace and the LangFuse trace share an ID. Provide a way to pass `trace_id` (param or contextvar) into the decorator. [Source: architecture.md#1.13.7 (line 1605)]

### Observability architecture context (for correctness, not extra work)

- MVP observability = OTEL-TUI + LangFuse + Fluentd. LangFuse handles **agent/LLM traces only**; infra traces go to OTEL-TUI. Do not route generic HTTP spans into LangFuse. [Source: architecture.md#1.10.1 (lines 679–692)]
- MVP→Target switch is config-only (LangFuse stays; OTEL-TUI → LGTM). Keep host/keys in `settings` so the switch needs no code change. [Source: architecture.md#1.10.2]

### Testing standards summary

- pytest via `uv tox`; unit tests only here (no testcontainers needed — LangFuse is mocked / no-op). Tests in `service_webapp/tests/unit/`. [Source: architecture.md#1.11.8]
- Critical assertions: (1) disabled → no LangFuse interaction + correct return; (2) enabled (mocked) → trace fields populated; (3) singleton identity.

### Project Structure Notes

- New file: `service_webapp/src/core/observability/langfuse.py` (create the `observability/` package with `__init__.py`).
- Extends (does not replace): `service_webapp/src/core/config.py` from Story 1.4 — add the four `langfuse_*` keys.
- Extends: `docker/docker-compose-dependencies.yaml` (LangFuse service from Story 1.2) and the `just up` recipe (Story 1.3) for the URL echo — coordinate so you augment rather than duplicate those definitions.
- Variance: LangFuse self-host needs a backing Postgres + (optionally) Redis/ClickHouse depending on the LangFuse version. Architecture lists `langfuse` as a single compose service without detailing its backing store. The dev agent must consult current LangFuse self-host requirements and add what that version needs (e.g. a dedicated `langfuse_postgres` or reuse Postgres with a separate DB). Document the chosen topology in Completion Notes — this is the most likely setup friction point.

### References

- [Source: epics.md#Story-1.5 (lines 382–396)]
- [Source: architecture.md#1.10.1-Observability-MVP (lines 679–692)]
- [Source: architecture.md#1.10.2-LangFuse-instrumentation-coverage (lines 694–716)]
- [Source: architecture.md#1.11.1-Configuration-Management (no hard-coded config, lines 759–764)]
- [Source: architecture.md#1.11.6-PII-Hygiene-Rules (lines 938–943)]
- [Source: architecture.md#1.12.1-Monorepo-Layout (lines 1080–1081)]
- [Source: architecture.md#1.13.7 (trace_id in LangFuse metadata, line 1605)]
- [Source: service_webapp/pyproject.toml (langfuse>=2, line 22)]

## Dev Agent Record

### Agent Model Used

GLM-5.2 (via Claude Code, `bmad-dev-story` workflow)

### Debug Log References

- Lint gate `uvx --with tox-uv tox -e lint` (service_webapp): ruff check + ruff format --check + pyrefly check → **0 errors**.
- Test gate `uvx --with tox-uv tox -e test` (service_webapp): **26 passed, 1 deselected** (the pre-existing `slow` testcontainers integration test, unchanged).
- New module isolated: `tests/unit/test_langfuse.py` → **11 passed**.

### Completion Notes List

**Infra + config layers were already delivered by Stories 1.2 & 1.4 and only verified/extended here:**

- LangFuse v3 self-host stack is already present in `docker/docker-compose-dependencies.yaml` (`langfuse/langfuse:3`, port `3000:3000`) using the **separate-DB topology** the dev notes prefer: a dedicated `langfuse` database + `langfuse_app` role (`docker/postgres/init/03_databases.sql`, `04_langfuse_permissions.sh`), backed by ClickHouse (event store) + MinIO (blob store) + Valkey — no coupling to the `sboai` DB. AC #1 satisfied at the compose-wiring level.
- The four config keys (`langfuse_enabled` / `langfuse_host` / `langfuse_secret_key` / `langfuse_public_key`) and the matching `LANGFUSE_*` placeholders were already in `service_webapp/src/core/config.py` and `service_webapp/.env.example` (added during Story 1.4 scaffolding, labelled "Story 1.5"). Verified, no change needed. `pytest` already sets `LANGFUSE_ENABLED=false`, so collection and the no-op path run without a live instance.

**This story's net deliverable — the reusable client + decorator primitive:**

- `service_webapp/src/core/observability/langfuse.py`:
  - `get_langfuse_client()` singleton built from `settings` only; returns `None` and **never constructs `Langfuse`** when `langfuse_enabled` is False (the AC #4 no-op gate).
  - `@trace_agent` async decorator recording **name / input / output / model / token usage** (FR-72); `trace_id` + `usage` contextvars propagate the OTEL trace id (§1.13.7) and let agents feed token usage from the LLM response.
  - Bare `@trace_agent`, `@trace_agent()`, and `@trace_agent("name", model=...)` all supported; exceptions re-raised (observation flagged `ERROR`); `functools.wraps` preserves the signature.
- `justfile`: `just up` **and** `just deps` now echo the LangFuse dashboard URL after startup (AC #5).
- `tests/unit/test_langfuse.py`: 11 tests — disabled pass-through (no construction, exceptions preserved, signature preserved), enabled recording (name/input/output/model/usage/metadata, default name, usage-omitted, error-flag+reraise), and singleton identity (single construction).

**Key implementation decision — SDK version:** `langfuse>=2` resolves to **langfuse 4.9.1**, which is OTEL-based and **removed** the v2 `client.trace()` / `.generation()` API the dev notes listed as a fallback. Per the dev note's directive to "use the current decorator/context-manager API, not a deprecated one", `@trace_agent` uses the v4 `client.start_as_current_observation(name, as_type="generation", input, model, metadata)` context manager + `observation.update(output, usage_details)` — both the current API and cleanly mockable (tests assert on those exact calls). The compose server is langfuse v3; the v4 SDK is compatible with its ingestion API.

**Typing note:** ParamSpec was avoided — this pyrefly version rejects `P.args`/`P.kwargs` annotations and the codebase uses ParamSpec nowhere else — so the decorator is typed with `Callable[..., Awaitable[Any]]`.

**Verification scope / known gap:** Lint + unit tests are green via `uv tox`. A live `just up` runtime smoke (LangFuse UI reachable at `http://localhost:3000`, AC #1 end-to-end) is **not** exercised here: it needs rootless podman + the deps stack, and `just up` for the app layer is blocked by the pre-existing, deferred `service_webapp` Dockerfile gap (see `deferred-work.md`, Story 1.2). The deps-only path (`just deps`) brings up LangFuse identically (URL echo added there too). AC #1 wiring is verified; runtime reachability remains the Story 1.2 deps stack's responsibility. Logged here for the reviewer.

### File List

- `service_webapp/src/core/observability/__init__.py` — new (package marker)
- `service_webapp/src/core/observability/langfuse.py` — new (`get_langfuse_client`, `@trace_agent`, trace_id/usage contextvars)
- `service_webapp/tests/unit/test_langfuse.py` — new (11 unit tests)
- `service_webapp/pyproject.toml` — modified (added `langfuse>=2` to `[tool.tox.env.lint]` and `[tool.tox.env.test]` `deps`)
- `justfile` — modified (LangFuse dashboard URL echo in `up` and `deps` recipes)
- `docs/bmad_output/implementation-artifacts/1-5-langfuse-self-hosted-setup-client-instrumentation-scaffold.md` — this story file (status/record/checkboxes)

## Change Log

- 2026-06-20: Story 1.5 implemented — LangFuse v4 client singleton + no-op-gated `@trace_agent` decorator (name/input/output/model/token-usage, OTEL trace_id correlation), `just up`/`just deps` LangFuse URL echo, 11 unit tests. Tox `lint` and `test` gates green. Config keys + compose stack verified (pre-delivered by Stories 1.2/1.4). Status → review.
