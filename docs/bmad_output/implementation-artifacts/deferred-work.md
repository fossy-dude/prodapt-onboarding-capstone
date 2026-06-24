# Deferred Work

## Deferred from: code review of 1-7-sim-activation-order-tracker-ui (2026-06-22)

- **401 hard redirect, no refresh-token retry** — `api.ts` interceptor redirects to `/login` on the first 401 with no refresh-token retry despite a refresh token being stored. Token-refresh flow is Story 1.8 auth territory; not this story's job to introduce.
- **UUID case-sensitivity in `sub` comparison** — `account.py` does `subscriber_id != sub` on raw strings; canonical UUIDs are lowercase on both sides (Postgres `::text` output + Cognito `sub`), so real risk ≈ 0. Normalising both via `str().lower()` would be defensive but not warranted now.
- **`getOrderStatus(orderId!)` non-null assertion** — the `!` is safe only because `enabled: orderId !== null` guards the queryFn; refactor-fragile but guarded today.
- **`modified_at = NOW()` divergence from app clock** — simulator advance writes DB wall-clock time via `NOW()` rather than an app-level timestamp; dev-only tool, speculative ordering impact on `getActiveOrder`'s `created_at DESC`.
- **Import naming collision `SimActivation as SimActivationSimulator`** — foot-gun alongside the subscriber `SimActivation` default import in `App.tsx`; cosmetic.
- **`test_order_status_msisdn_absent_for_kyc_pending` is a `for` loop, not `pytest.parametrize`** — a failure aborts the loop and masks partial regressions; no parametrized id reported.
- **Checkmark-count test name vs assertion mismatch** — test name says "three checkmarks" but asserts `toHaveLength(2)` for `KYC_VERIFIED`; cosmetic.

## Deferred from: code review of 1-8-login-otp-step-up-jwt-role-based-auth (2026-06-22)

- **D1 — OTEL `trace_id` not asserted in auth tests** — `require_role` and `JWTValidator` run inside the OTEL middleware stack but no unit test asserts `request.state.trace_id` is preserved or that `X-Trace-Id` appears on `401`/`403` responses. Middleware ordering is correct structurally but untested; add an integration assertion in a later observability pass.
- **D2 — `makeToken` helper duplicated in frontend test files** — verbatim copy in both `frontend/src/lib/auth.test.ts` and `frontend/src/components/layout/RoleGuard.test.tsx`; extract to a shared `testUtils.ts` fixture in a later cleanup pass.
- **D3 — `require_role` not wired to any production route** — the guard primitive is built and tested in isolation; wiring it to role-specific endpoints is the responsibility of the stories that introduce those endpoints (subscriber portal, ops dashboard, etc.).
- **D4 — Concurrent race on `_jwks_client` lazy init** — `JWTValidator._client` property initialises `PyJWKClient` lazily without locking; in asyncio (single-threaded GIL) with synchronous init this is safe, but worth revisiting if threading is introduced.

## Deferred from: code review of 1-6-subscriber-registration-trai-caf-pii-encryption (2026-06-20)

- **No retry on `registration_id` uniqueness collision** — `generate_registration_id` uses 4 random bytes (2^32 per day); a collision surfaces as a raw psycopg `UniqueViolation` → 500. Low probability at MVP scale but should be wrapped in a retry loop (max 3 attempts) before production load.

## Deferred from: MiniStack Cognito provisioning script (scripts/provision_cognito.py) (2026-06-20)

- **OTP Custom Auth challenge Lambdas not provisioned** — `scripts/provision_cognito.py` creates the user pool, app client, role groups, and demo users only. The `DefineAuthChallenge` / `CreateAuthChallenge` / `VerifyAuthChallenge` Lambdas that actually issue + verify a passwordless login OTP are intentionally out of scope and land in Story 1.8 (login). Until then, the pool supports custom auth but no OTP can be issued.
- **Redpanda `notification.events` OTP producer not wired** — the login OTP must be published to the Redpanda `notification.events` stream so the Notification Portal can surface it (**no SNS in MVP**). The producer (inside `CreateAuthChallenge` or a bridge) is deferred to Story 1.8 / the Notification-Portal epic. Architecture §1.8.1 + §1.14.3 updated to reflect Redpanda (was "SMS via SNS").
- **Role claim is `cognito:groups`, not `role`** — roles are delivered as Cognito groups; Story 1.8's `core/auth.py` / `require_role` must read `cognito:groups`. Documented in the Story 1.8 dev notes; no `custom:role` attribute or PreTokenGeneration Lambda is provisioned.
- **Seeded demo users are in FORCE_CHANGE_PASSWORD status** — created passwordless via `admin_create_user`; the Custom Auth flow bypasses this, but it is worth noting if any flow inspects user status before Story 1.8 lands.

## Deferred from: code review of 1-2-docker-compose-stack-postgres-init-flyway-baseline (2026-06-20)

- **otel-tui may not render in detached mode** — TUI app with `tty: true` may exit when run headless; low priority, likely acceptable for dev workflow
- **billing_audit_log append-only not enforced at DB level** — V5__grants.sql is the planned vehicle; REVOKE UPDATE/DELETE on `billing_audit_log` for `sboai_app` must be added in the grants migration
- **Redpanda topic initialization (partition counts per ARCH-10)** — 6 topics with explicit partitions required; no init container. Epic 2 scope when cdr-pipeline is implemented
- **OTEL metrics + logs pipelines have no persistent exporter** — Intentional dev-mode design; stdout/debug exporters acceptable for local dev
- **Unpinned image tags on redpanda, localstack, otel-collector, otel-tui** — Breaking changes possible across `podman pull`; pin to specific digests for reproducibility when stabilising the stack
- **Flyway failed-migration recovery not documented** — If V1/V2 fail mid-run, `flyway repair` + retry is required; add to runbook / README

## Deferred from: code review of story-1.4 (2026-06-20)

- **`close()` absent from `DatabaseProtocol`/`CacheProtocol`** — lifespan depends on `.close()` at shutdown but it is not part of either Protocol interface; a future adapter that implements only the Protocol will type-check cleanly but raise AttributeError at shutdown. Add `close()` to both protocols when the adapter suite grows in later stories.
- **No HTTP status code on OTEL span** — `OtelTraceMiddleware` records `http.method` and `http.url.path` but omits the response status code, making every span look identical regardless of outcome. Add `http.status_code` attribute after `call_next()` in a later observability pass.
- **No timing assertion for the 200 ms `/ready` and `/health` response-time SLO (AC-2, NFR-19)** — live smoke test verified < 200 ms; hard to unit-test timing reliably. Add a performance test (e.g. locust/k6) in a dedicated NFR story.
- **Postgres adapter cannot self-recover after network loss via `ping()` alone** — once the pool is in a degraded state (successful `open()` followed by connection loss), repeated `ping()` calls correctly return `False` but never re-open the pool. Recovery requires `close()` + adapter reconstruction; wire up a lifespan health-check loop or connection-pool reconnect config in a later story.
- **`kafka_brokers: str` is a comma-separated list disguised as a plain string** — every consumer must split on `,` manually. Refactor to `list[str]` with a `@field_validator` when the CDR pipeline consumer (Epic 2) actually uses it.

## Deferred from: code review of 1-5-langfuse-self-hosted-setup-client-instrumentation-scaffold (2026-06-20)

- **AC #1: no healthcheck on langfuse compose service** — langfuse service in `docker-compose-dependencies.yaml` has no `healthcheck` block; other infra services (postgres, clickhouse, minio, valkey) all have healthchecks. Pre-existing Story 1.2 gap; add when stabilising the deps stack.
- **Post-fork stale singleton** — module-level `_langfuse_client` inherited by forked workers (Gunicorn, `multiprocessing`); background threads and file descriptors do not survive `fork()`. Register `os.register_at_fork(after_in_child=_reset_langfuse_client_for_tests)` or equivalent if multi-worker deployments are needed.
- **`@trace_agent` on instance methods leaks `self` into trace input** — `_capture_input` records `args[0]` verbatim; on methods this is `self`, potentially exposing credentials or subscriber data. Document as unsupported and add a guard or `self`/`cls` stripping when agents are wired in Epic 5.
- **ContextVar tokens discarded by callers** — `set_trace_id`/`set_trace_usage` return `contextvars.Token` objects that are never used for `var.reset(token)`; asyncio task-isolation mitigates in production (each request task copies the context). Revisit if non-asyncio or threaded callers are introduced.

## Deferred from: Story 1.4 — pydantic-settings singleton, health endpoints, OTEL middleware (2026-06-20)

- **`service_webapp` Dockerfile does not exist** — `docker/docker-compose.yaml` `service_webapp` declares `build: context: ../service_webapp` but no `Dockerfile` is present, so `just up` / `podman compose build` cannot build the service. Pre-existing Story 1.2 gap; containerising the app is its own concern (no Story 1.4 task). The app serves on :8000 via the dev path `just backend` (verified live). Add a Dockerfile (system libs for weasyprint etc.) when the service must run under compose.
- **Compose injects `DATABASE_URL` (deprecated), not the `DB__*` vars** the Story 1.4 config singleton requires — `docker-compose.yaml` `service_webapp.environment` must add `DB__HOST=postgres`, `DB__PORT=5432`, `DB__NAME=sboai`, `DB__USER=sboai_app`, `DB__PASSWORD=${POSTGRES_APP_PASSWORD}` (and `VALKEY_URL`/`KAFKA_BROKERS` are already present) or the container fails fast at boot. Land alongside the Dockerfile.
- **`.github/workflows/` CI YAMLs are absent** — Story 1.3 notes reference `ci-pipeline.yml` / `ci-cdr.yml` but they were not committed. Not a Story 1.4 task; re-create so the `uv tox` gate runs on PRs.

## Deferred from: code review of 1-9-profile-management-kyc-status-view (2026-06-22)

- **`_FakeConn` always returns same `select_row` regardless of query** — `test_profile_endpoint.py:2509`. Test design pattern where the fake routes all SELECTs to the same row; not a production bug; each test sets the row it expects, so tests pass as intended. Extracting separate `select_row_for_update_reread` to make the fake more rigorous is a cleanup item.
- **`update_profile` SET clause relies on dict insertion order** — `account.py:1766-1770`. Uses `dict.keys()`/`dict.values()` to build the parameterised SQL; Python 3.7+ guarantees insertion order so this is correct today, but fragile under refactors. Refactor to an explicit `[(col, val), ...]` list if the handler grows.

## Deferred from: code review of Story 2.1 (2026-06-22)

- **Provisioning swallows only TopicAlreadyExistsError — other errors propagate** — the script only catches the expected concurrent-exists error; auth failures, network errors, and other non-retryable errors intentionally propagate to avoid silently masking real issues. This is a design decision, not a defect.
- **Missing clearer error messaging for Kafka connection failures** — `AIOKafkaAdminClient` raises a meaningful connection error deep in the library. The enhancement would be pre-flight validation or a clearer error wrapper, but not required for MVP.
- **main() doesn't expose --brokers CLI flag** — the `provision_topics()` function accepts `bootstrap_servers` but the CLI entry point has no argparse. Operators must edit `.env` to point at a different cluster. Minor UX gap; defer as enhancement.

## Deferred from: Story 2.2 — CDR ingestion consumer, dedup & DLQ (2026-06-22)

- **`billing_cdr_events.id` still has `DEFAULT uuid_generate_v7()`** — `service_webapp/db/migrations/V1__baseline_schema.sql:172`. Per the Story 2.2 decision, `cdr_id` is now a **mandatory, app-supplied** UUIDv7 (the dedup key and the future PK). The DB column should therefore NOT autogenerate an id (an app-supplied id + a DB default would diverge). V1 baseline is immutable/Flyway-applied, so this needs a new migration (`ALTER COLUMN id DROP DEFAULT`) landed alongside the CDR-insert path (not in 2.2 — 2.2 forwards to `cdr.enriched.filtered` and never inserts into `billing_cdr_events`). Until then, the schema and the event contract are slightly out of sync: the app always supplies the id, so the default is never exercised.
- **Consumer parallelism is fixed at 1 task per process** — `batch_processor.py` runs a single `AIOKafkaConsumer`/`getmany` loop (documented). A configurable `consumer_concurrency` N (capped at 24, spawning N consumer tasks sharing the group within one process) is deferred — it adds rebalance/coordination complexity for no single-process MVP benefit; scale-out is via more process instances (Kafka rebalances partitions). Wire in only if intra-process fan-out is shown to be needed.
- **`getmany` poll timeout is a hard-coded constant (`POLL_TIMEOUT_MS = 1000`)** — not surfaced as a setting. Fine for MVP; promote to `settings` if tuning is needed per-environment.
- **DLQ `raw_payload_b64` must be base64-decoded by Story 2.5's inspector** — the DLQ contract (`cdr_id`, `error_reason`, `original_topic`, `failed_at`, `raw_payload_b64`) is settled here; Story 2.5's `GET /api/v1/admin/dlq` must base64-decode for replay and mask any PII in the decoded raw payload before returning it to operators.
- **In-process `dedup_stats` counter is per-process, not aggregated** — exposed via `consumer.dedup.dedup_stats` for Story 2.5/observability, but with >1 consumer process the counts are local. Aggregate via the metrics/observability pipeline (Story 7.8) if a cluster-wide dedup count is needed.

## Deferred from: code review of 2-2-cdr-ingestion-consumer-dedup-dlq (2026-06-22)

- **Poison-pill / no per-record exception isolation** — `batch_processor.process_batch` (lines 144-148) calls `_handle_record` per record then `commit()`s once. `_process` catches only `ValidationError` (envelope parse + CDR schema) and routes to DLQ; any other exception (`is_duplicate` failing because the cache is down, a DLQ or enriched publish failure, or the balance hook crashing) propagates, so `commit()` is skipped and the whole batch is re-delivered on restart — re-failing on the same record and blocking the partition. The dedup guard only absorbs records that already passed the dedup check, so it cannot break this loop. The at-least-once + crash-restart design accepts this for MVP (fail loud, operator restarts); robust per-record isolation (wrap `_handle_record` in try/except, route unexpected errors to DLQ, continue the batch) is future hardening before production load.
- **Valkey socket timeout potentially too aggressive** — `adapters/redis.py:18` pins `_SOCKET_TIMEOUT_SECONDS = 2`. Fine for the hot-path dedup check under MVP load; revisit/tune (and surface as a setting) when batch=500 dedup throughput is measured under production load.
- **No consumer connection-failure recovery / supervisor** — `main.py` has no reconnect/retry around the broker; a dropped Kafka connection crashes the process. Recovery is the operator's restart policy (k8s/systemd). Wire a supervised reconnect loop only if self-healing without restart is required.
- **DLQ publish failure loses the record** — `dlq/handler.to_dlq` and the per-record DLQ routes in `batch_processor._process` publish-and-wait with no retry/backoff; if the DLQ publish itself fails the original record is lost (and per the poison-pill item above, also blocks the batch). A retry/backoff or secondary spool is out of scope for this story.

## Deferred from: code review of 2-3-balance-deduction-engine-valkey-write-buffer-postgres-flush (2026-06-23)

- **AC#1 topic mismatch (doc only)** — AC#1 says deductions arrive from `cdr.enriched.filtered`, but the code (correctly) consumes `cdr.raw` via the Story 2.2 `BatchProcessor` seam the spec directs. Fix the AC text, not the code. [main.py:88-91]
- **`CacheProtocol.incr` has no caller** — the Story 2.2 in-process dedup metric it was added for is not wired anywhere in this diff; dead Protocol method. [redis.py:66-68]
- **No OTEL exporter dependency** — `balance.deduction` spans are emitted (`balance_writer.py:183`) but `opentelemetry-sdk` has no exporter, so spans go to a no-op processor and P95 is unverifiable in prod. Wire an exporter (Story 1.5 infra) before treating P95 telemetry as live.
- **Flusher inner loop busy-polls at 10 Hz** — `asyncio.sleep(0.1)` inside `_flusher_loop`; works under MVP load, minor CPU. Replace with an `asyncio.Event` signalled by `deduct` when the dirty threshold is approached.
- **Unlimited-bundle `cost=0` still performs an `INCRBY 0` round-trip** — every free/unlimited CDR still hits Valkey on the hot path. Chose consistency (key always exists) over micro-optimisation; revisit only if free-call volume dominates measured P95.
- **`_management_lifespan` dead `finally: pass`** — never closes `JWTValidator` (JWKS HTTP client leak). Story 2.5 management-API scope. [main.py:56-64]

## Deferred from: code review of 5-3-rag-pipeline-milvus-hybrid-search (2026-06-24)

- `_dispatch_notification_events` commits the Kafka offset outside `db.transaction()` — non-atomic with the DB insert; duplicate inserts / lost notifications on broker hiccup. Story 4.x, not 5.3. [service_webapp/src/main.py]
- `data_nudge_consumer` startup is gated on `notification_dispatcher` being present — conflates two unrelated consumers; DATA_NUDGE never starts if the dispatcher is absent. Story 4.x, not 5.3. [service_webapp/src/main.py]
- Commit scope hygiene: the Story 5.3 commit bundles unrelated Stories 4.1/4.2/4.3/5.2 changes (rate limit, routers, scheduler, consumers) into `main.py`/`pyproject.toml`. Consider splitting before merge.
- `RagChunk` is a plain dataclass, not JSON-serializable — Story 5.4's LangGraph tool result will need `dataclasses.asdict()` or the LLM cannot consume the tool output. [service_webapp/src/agents/rag/retriever.py:90-104]
- `rag_search` is not yet wrapped as a LangGraph `@tool`/`ToolNode` — correctly deferred to Story 5.4 per AC #6; confirm 5.4 owns registration.
- Two `MilvusClient` instances open the same Milvus Lite file (adapter + retriever) — works today; retriever could reuse `app.state.milvus_adapter`. Design note.
- Singleton `_retriever` has no lock — `set_retriever` is called once at startup and concurrent reads were verified safe. Theoretical only.
- Falsy PK `or ""` chain in `_record_hit` — real Milvus PKs are UUID/strings, never falsy. Low-value defensive.
