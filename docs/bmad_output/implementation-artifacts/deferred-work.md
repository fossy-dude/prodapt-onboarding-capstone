# Deferred Work

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

## Deferred from: Story 1.4 — pydantic-settings singleton, health endpoints, OTEL middleware (2026-06-20)

- **`service_webapp` Dockerfile does not exist** — `docker/docker-compose.yaml` `service_webapp` declares `build: context: ../service_webapp` but no `Dockerfile` is present, so `just up` / `podman compose build` cannot build the service. Pre-existing Story 1.2 gap; containerising the app is its own concern (no Story 1.4 task). The app serves on :8000 via the dev path `just backend` (verified live). Add a Dockerfile (system libs for weasyprint etc.) when the service must run under compose.
- **Compose injects `DATABASE_URL` (deprecated), not the `DB__*` vars** the Story 1.4 config singleton requires — `docker-compose.yaml` `service_webapp.environment` must add `DB__HOST=postgres`, `DB__PORT=5432`, `DB__NAME=sboai`, `DB__USER=sboai_app`, `DB__PASSWORD=${POSTGRES_APP_PASSWORD}` (and `VALKEY_URL`/`KAFKA_BROKERS` are already present) or the container fails fast at boot. Land alongside the Dockerfile.
- **`.github/workflows/` CI YAMLs are absent** — Story 1.3 notes reference `ci-pipeline.yml` / `ci-cdr.yml` but they were not committed. Not a Story 1.4 task; re-create so the `uv tox` gate runs on PRs.
