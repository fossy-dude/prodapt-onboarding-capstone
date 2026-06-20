# Story 1.6: Subscriber Registration, TRAI CAF & PII Encryption

Status: ready-for-dev

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As a **new subscriber**,
I want to submit an online sign-up form with my personal details and TRAI Customer Acquisition Form (CAF) fields and receive a unique Registration ID,
so that I can begin the SIM activation process and my identity is on record (encrypted, auditable) before my SIM is active.

## Acceptance Criteria

1. **Given** a visitor navigates to `/register`, **When** they complete the multi-step form (Step 1 personal details → Step 2 TRAI CAF fields → Step 3 submission), **Then** an `identity_subscribers` master record is created in Postgres with `status = 'REGISTRATION_COMPLETE'` and a linked `identity_registrations` record is created.
2. A unique, human-readable **Registration ID** in the format `REG-{YYYYMMDD}-{8 hex chars}` (e.g. `REG-20260619-a3f9c1d2`) is generated, persisted on the registration record, and displayed to the subscriber in Step 3.
3. PII fields (name, address, MSISDN if provided) are **encrypted at rest** using pgcrypto AES-256 (`pgp_sym_encrypt`); the plaintext never lands in an unencrypted column (FR-63, NFR-6).
4. The TRAI CAF submission is recorded in `billing_audit_log` as an immutable row with `event_type = 'TRAI_CAF_SUBMITTED'`, a timestamp, and a SHA-256 hash of the submitted CAF data (FR-3, FR-65).
5. The registration API response uses the standard envelope: `{ "data": { "registration_id": "...", "status": "REGISTRATION_COMPLETE" }, "meta": { "trace_id": "...", "timestamp": "..." } }` (ARCH-12, §1.11.3).
6. On successful registration, an initial **`ops_order_fulfilment`** row is created with state `'CREATED'` and linked to the subscriber, so the SIM activation tracker (Story 1.7) has an order to read.
7. A **MiniStack Cognito user** is provisioned (username = Registration ID, **no password**) so the subscriber can later log in via the Registration ID + OTP Custom Auth Flow (Story 1.8); Step 3 sends a verification OTP to the **alternate mobile number** captured in Step 1 (PRD A-6).
8. **Given** a registration form is submitted with a duplicate MSISDN, **When** the API receives the request, **Then** it returns HTTP **409** with error `code = "DUPLICATE_MSISDN"` in the standard error envelope.
9. Raw MSISDN / name / address never appear in application logs or OTEL span attributes — only `msisdn[-4:]` suffix or the subscriber UUID is used (§1.11.6).

## Tasks / Subtasks

- [ ] **Task 1: Backend registration endpoint** (AC: #1, #5, #8) — `service_webapp/src/routers/account.py`
  - [ ] Add `POST /api/v1/subscriber/register` (async) in `routers/account.py` (FR-1–7 domain router); register the router in `main.py` if not already wired
  - [ ] Define pydantic request/response models (Step 1 personal details incl. `alternate_mobile`, Step 2 TRAI CAF fields); validate with pydantic (422 on validation error)
  - [ ] Persist via `DatabaseProtocol` (Psycopg3 async adapter) inside a single transaction: insert `identity_subscribers`, `identity_registrations`, the CAF audit row, and the initial `ops_order_fulfilment` row — all-or-nothing
  - [ ] Return the standard success envelope (Story 1.4 helper) with `{registration_id, status}`
- [ ] **Task 2: Registration ID generation** (AC: #2)
  - [ ] Implement `generate_registration_id()` → `REG-{YYYYMMDD}-{8 hex chars}` (8 hex = 4 random bytes, lowercase); persist on `identity_registrations`
  - [ ] Ensure uniqueness (unique constraint already in V1 baseline if defined; otherwise retry-on-collision)
- [ ] **Task 3: PII column encryption** (AC: #3, #9)
  - [ ] Encrypt name, address, MSISDN with `pgp_sym_encrypt(value, :pii_key)` on write; decrypt with `pgp_sym_decrypt` on read paths only
  - [ ] Source the symmetric key from `settings.pii_encryption_key` (pydantic-settings; no hard-coded key) and add the placeholder to `.env.example` (Story 1.3) if missing
  - [ ] Audit all log/span sites in this flow — never emit raw MSISDN/name/address; use `msisdn[-4:]` or subscriber UUID
- [ ] **Task 4: TRAI CAF audit row** (AC: #4)
  - [ ] Insert an append-only `billing_audit_log` row: `event_type='TRAI_CAF_SUBMITTED'`, `created_at` timestamp, `detail` containing a **SHA-256 hash** of the canonicalised CAF payload (hash, not raw CAF data)
  - [ ] Use the `sboai_app` role (INSERT-only on the audit table — never UPDATE/DELETE)
- [ ] **Task 5: Duplicate MSISDN handling** (AC: #8)
  - [ ] Pre-check or catch the unique-constraint violation on MSISDN → raise a domain error mapped to HTTP 409 `DUPLICATE_MSISDN` via the error envelope (Story 1.4 error handler)
- [ ] **Task 6: Initial order + Cognito provisioning** (AC: #6, #7)
  - [ ] Create the `ops_order_fulfilment` row (state `'CREATED'`, FK to subscriber) within the registration transaction
  - [ ] Provision a MiniStack Cognito user (username = Registration ID, **no password**); on failure, surface a clear error and roll back consistently (decide and document compensation if Cognito write succeeds but DB commit fails — prefer Cognito-after-commit ordering)
  - [ ] Trigger the Step-3 verification OTP to the alternate mobile number via Cognito Custom Auth (delivery is simulated/captured in the Notification Portal for local testing)
- [ ] **Task 7: Frontend multi-step registration form** (AC: #1, #2, #8) — `frontend/src/portals/subscriber/Register.tsx`
  - [ ] Build the 3-step form (TailwindCSS only, PascalCase): Step 1 personal details + alternate mobile; Step 2 TRAI CAF fields; Step 3 Registration ID display + OTP entry
  - [ ] Submit via `lib/api.ts` (Axios); manage server state with TanStack Query; surface the 409 `DUPLICATE_MSISDN` as an inline Step 1/2 error
  - [ ] Use shared UI components (`Button`, `Card`, `Badge`) from `components/ui/` (per UX brief)
- [ ] **Task 8: Tests** (AC: #1–#9)
  - [ ] Backend unit tests (`service_webapp/tests/unit/`): registration ID format; envelope shape; duplicate MSISDN → 409; CAF audit row written with hash (not raw); no-PII-in-logs assertion
  - [ ] Backend integration test (testcontainers Postgres): full transaction creates subscriber + registration + audit + order; encrypted columns round-trip via `pgp_sym_decrypt`
  - [ ] Frontend tests (Vitest + RTL): step navigation, validation, duplicate-MSISDN inline error

## Dev Notes

### Scope boundary — what this story does and does NOT do

- **DOES:** `/register` multi-step form, `POST /api/v1/subscriber/register`, PII encryption at rest, Registration ID generation, TRAI CAF audit row, initial `ops_order_fulfilment` order, passwordless Cognito user provisioning + Step-3 OTP, duplicate-MSISDN 409.
- **DOES NOT:** Create any DB tables/migrations (V1 baseline already has them — see below); implement login (Story 1.8); render the order tracker (Story 1.7); implement profile edit/KYC view (Story 1.9); payment methods (Story 1.10); drive KYC/order state transitions (simulated/seeded, Epic 2).

### RESOLVED — NO new Flyway migration (epics AC superseded)

Epics 1.6 AC says *"a Flyway migration (`V2__subscriber_schema.sql`) creates: subscribers table, subscriber_orders table, audit_log table."* This is **superseded.** Per Story 1.2, **V1 is the full all-domain baseline** — every table already exists. This story **uses** existing tables (and adds a view/grant only if strictly needed). Do **not** author a new migration to create core tables. [Source: 1-2-docker-compose-stack-postgres-init-flyway-baseline.md — "Cross-story note: 1.6/1.8/1.10 will use already-created tables"; architecture.md#1.12.1]

### RESOLVED — canonical table names (architecture §1.7.1 wins over epics shorthand)

| Epics shorthand | **Use this (canonical)** | UUID PK strategy |
|---|---|---|
| `subscribers` | `identity_subscribers` (master record) | **UUIDv4** `gen_random_uuid()` |
| (registration) | `identity_registrations` | **UUIDv7** `uuid_generate_v7()` |
| (CAF) | `identity_caf_submissions` | per V1 baseline |
| `audit_log` | `billing_audit_log` (append-only) | UUIDv7 |
| `subscriber_orders` | `ops_order_fulfilment` | **UUIDv7** `uuid_generate_v7()` |

> ⚠️ Epics 1.6 says *"a subscriber record … with a UUIDv7 primary key."* **Superseded:** `identity_subscribers` is the master/reference record, so it uses **UUIDv4** per Story 1.2's resolved v7/v4 split (§1.7.1 overrides §1.11.2's blanket `gen_random_uuid()` rule — but in this case both agree the master record is v4). The high-insert child rows (`identity_registrations`, `ops_order_fulfilment`) are UUIDv7. PK column is `id`; foreign keys are `{referenced_singular}_id` (e.g. `subscriber_id`). [Source: architecture.md#1.7.1 (UUID strategy, lines ~380–428); 1-2-…-flyway-baseline.md "UUIDv7 vs UUIDv4" table]

### PII encryption (pgcrypto AES-256)

- Encrypt name, address, MSISDN with `pgp_sym_encrypt(plaintext, :pii_key)`; decrypt only on authorised read paths (`pgp_sym_decrypt`). pgcrypto is installed in V1 init (`01_extensions.sql`). [Source: architecture.md#1.8.2 (PII encryption at rest — pgcrypto AES-256)]
- Symmetric key comes from `settings.pii_encryption_key` (pydantic-settings, Story 1.4) — **never hard-code** (§1.11.1). Add a placeholder to `.env.example`.
- **PII hygiene is non-negotiable (§1.11.6):** never log raw MSISDN/name/address; never put PII in OTEL span attributes. Use `msisdn[-4:]` or the subscriber UUID. Fluentd redaction is a safety net, not the primary guard. [Source: architecture.md#1.11.6 (lines 938–943)]

### TRAI CAF audit (FR-3, FR-65)

- `billing_audit_log` is **append-only** (INSERT only via `sboai_app`; no UPDATE/DELETE — enforced by grants). Store a **SHA-256 hash** of the canonicalised CAF payload in the audit row, not the raw CAF data. This gives tamper-evidence without duplicating PII into the audit stream. [Source: architecture.md#1.7.1 (audit log append-only, line 378)]

### Auth model — passwordless (resolved)

- Pre-activation login (Story 1.8) is **Registration ID + OTP** via Cognito Custom Auth Flow — **passwordless**. Therefore this story provisions the Cognito user with **no password** and the form collects **no password field**. Step 3's OTP (to the alternate mobile per PRD A-6) verifies the registration. [Source: architecture.md#1.8.1 (Cognito Custom Auth Flow, OTP); ux-brief-identity.md (Step 3 = Registration ID + OTP); user decision 2026-06-19]

### API envelope & region

- Success/error envelopes per §1.11.3 (reuse Story 1.4's envelope + error handler). HTTP codes: 201 on create, 409 conflict, 422 validation. [Source: architecture.md#1.11.3 (lines 825–847)]
- NFR-3 India-region storage is a **deployment constraint** (`ap-south-1`), not a local code change for MVP — note only. [Source: architecture.md#1.8.2 (TRAI data localisation)]

### Dependencies & prerequisites

- **Story 1.2** — schema baseline + pgcrypto/pg_uuidv7 extensions + roles. **Story 1.3** — `.env.example`, `just`. **Story 1.4** — `core/config.py` settings singleton, envelope + error handler, trace middleware. **Story 1.1** — UX brief (`docs/bmad_output/planning-artifacts/ux-brief-identity.md`) is the design source for the form. [Source: 1-1-…-ux-brief…md; 1-4-…-pydantic-settings…md]
- Backend is **`service_webapp/`** (architecture says `app-backend/`/`service_backend/` — read as `service_webapp/`). [Source: 1-2-…-flyway-baseline.md "RESOLVED backend directory decision"]

### Cross-story outputs (other stories depend on this)

- **Story 1.7** reads the `ops_order_fulfilment` order created here (state `CREATED`). **Story 1.9** reads/edits the `identity_subscribers` PII + KYC status. **Story 1.8** logs in the Cognito user provisioned here.

### Project Structure Notes

- Backend: `service_webapp/src/routers/account.py` (endpoint), `core/config.py` (add `pii_encryption_key`), `adapters/postgres.py` (via `DatabaseProtocol`). Helpers for Registration ID / hashing can live in a small `service_webapp/src/services/` or `account` module — follow existing layout from Story 1.4. [Source: architecture.md#1.12.1 (routers/account.py = FR-1–7, line 1051; core/auth.py, config.py)]
- Frontend: `frontend/src/portals/subscriber/Register.tsx`, shared `components/ui/`, `lib/api.ts`, TanStack Query (`lib/queryClient.ts`). TailwindCSS only; PascalCase components, `usePascalCase.ts` hooks. The architecture `src/portals/*` layout wins over `frontend/CLAUDE.md` (FSD/SCSS). [Source: ux-brief-identity.md "RESOLVED conventions conflict"; architecture.md#1.12.1]

### Testing standards summary

- Python 3.11; `ruff` + `mypy` + `uv tox`. Backend unit tests in `service_webapp/tests/unit/`; Postgres integration via testcontainers where a live DB is needed. Frontend: Vitest + React Testing Library (no Cypress for MVP). [Source: architecture.md#1.11.7, #1.11.8]
- Critical assertions: Registration ID regex; envelope shape; 409 `DUPLICATE_MSISDN`; CAF audit row stores a **hash** (assert no raw CAF/PII in the row); encrypted columns are non-plaintext and round-trip; **no raw PII in logs/spans**.

### References

- [Source: epics.md#Story-1.6 (lines ~400–420)]
- [Source: architecture.md#1.7.1-PostgreSQL-Table-Naming (tables + UUID strategy, lines ~357–428)]
- [Source: architecture.md#1.8.1-Auth-Flow (Cognito Custom Auth, OTP); #1.8.2-Security-Controls (PII encryption, card tokenisation, data localisation, lines 616–627)]
- [Source: architecture.md#1.11.3-API-Response-Format (lines 825–847)]
- [Source: architecture.md#1.11.6-PII-Hygiene-Rules (lines 938–943)]
- [Source: architecture.md#1.12.1-Monorepo-Layout (routers/account.py line 1051; frontend portals tree)]
- [Source: 1-2-docker-compose-stack-postgres-init-flyway-baseline.md (V1 full baseline; canonical names; UUID split)]
- [Source: 1-1-ux-brief-subscriber-registration-identity-flows.md (form steps, route map, conventions)]
- [Source: prds/prd-sboai_capstone-2026-06-18/prd.md#A-6 (alternate mobile for pre-activation OTP)]

## Dev Agent Record

### Agent Model Used

{{agent_model_name_version}}

### Debug Log References

### Completion Notes List

### File List
