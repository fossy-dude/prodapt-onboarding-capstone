# Deferred Work

## Deferred from: code review of 1-2-docker-compose-stack-postgres-init-flyway-baseline (2026-06-20)

- **otel-tui may not render in detached mode** — TUI app with `tty: true` may exit when run headless; low priority, likely acceptable for dev workflow
- **billing_audit_log append-only not enforced at DB level** — V5__grants.sql is the planned vehicle; REVOKE UPDATE/DELETE on `billing_audit_log` for `sboai_app` must be added in the grants migration
- **Redpanda topic initialization (partition counts per ARCH-10)** — 6 topics with explicit partitions required; no init container. Epic 2 scope when cdr-pipeline is implemented
- **OTEL metrics + logs pipelines have no persistent exporter** — Intentional dev-mode design; stdout/debug exporters acceptable for local dev
- **Unpinned image tags on redpanda, localstack, otel-collector, otel-tui** — Breaking changes possible across `podman pull`; pin to specific digests for reproducibility when stabilising the stack
- **Flyway failed-migration recovery not documented** — If V1/V2 fail mid-run, `flyway repair` + retry is required; add to runbook / README
