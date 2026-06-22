# Story 1.9: Profile Management & KYC Status View

Status: ready-for-dev

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As an **authenticated subscriber**,
I want to view and edit my personal details and see my current KYC verification status,
so that my account information stays accurate and I understand what actions are available to me.

## Acceptance Criteria

1. **Given** a subscriber is logged in and navigates to `/subscriber/profile`, **When** the page loads, **Then** their **decrypted** name, email, saved address, and KYC status are displayed.
2. KYC status is rendered via the shared `Badge` component as exactly one of: **Verified** (green), **Pending** (amber), **Rejected** (red, with reason) (FR-7).
3. **Given** a subscriber edits their address or email and submits, **When** `PATCH /api/v1/subscriber/profile` is processed, **Then** the updated PII fields are **re-encrypted at rest** (pgcrypto AES-256) and a `billing_audit_log` row is written with `event_type = 'UPDATE_PROFILE'` (FR-5).
4. The `PATCH` response is HTTP 200 with the updated **decrypted** profile in the standard envelope: `{data: {...}, meta: {trace_id, timestamp}}` (ARCH-12).
5. **Given** a subscriber's KYC status is `'REJECTED'`, **When** they view their profile, **Then** the rejection reason is displayed **and** a link/CTA to re-submit KYC documents is shown.
6. A subscriber can only read/edit **their own** profile — the endpoint authorizes on the JWT `sub` claim (UUID match); a request for another subscriber's record is rejected (403).
7. No raw PII (name, email, address, MSISDN) appears in any log line or OTEL span — only subscriber UUID or `[-4:]` suffixes (NFR-16).

## Tasks / Subtasks

- [ ] **Task 1: Backend — GET profile (decrypt-on-read)** (AC: #1, #6, #7)
  - [ ] Add/extend `GET /api/v1/subscriber/profile` in `service_webapp/src/routers/account.py` (FR-1–7 grouping; `async def`)
  - [ ] Resolve the subscriber from the JWT `sub` claim (Story 1.8's `core/auth.py` guard) — never from a client-supplied id
  - [ ] Read `identity_subscribers` (PII columns) + the subscriber's latest `identity_kyc_records` row (status + rejection reason) via the `DatabaseProtocol` Postgres adapter
  - [ ] Decrypt name/email/address with `pgp_sym_decrypt(...)` using the key from `settings` (no hard-coded key) — decrypt ONLY for the authorized owner
  - [ ] Return the standard envelope; ensure no PII is logged or placed in span attributes (use UUID / `msisdn[-4:]`)
- [ ] **Task 2: Backend — PATCH profile (re-encrypt + audit)** (AC: #3, #4, #6)
  - [ ] `PATCH /api/v1/subscriber/profile` accepts editable fields (address, email; name editability per UX brief)
  - [ ] Re-encrypt updated PII fields with `pgp_sym_encrypt(...)` before write; update `identity_subscribers` (`modified_at` advances via the V2 trigger)
  - [ ] Append a `billing_audit_log` row (`event_type='UPDATE_PROFILE'`, subscriber UUID, timestamp) — INSERT only (append-only table; never UPDATE/DELETE)
  - [ ] Return HTTP 200 with the updated **decrypted** profile in the standard envelope
  - [ ] Authorize on `sub` claim; validate payload (422 on bad input; envelope error shape)
- [ ] **Task 3: Frontend — Profile page** (AC: #1, #2, #5)
  - [ ] `frontend/src/portals/subscriber/Profile.tsx` at route `/subscriber/profile`, role-gated under `/subscriber/*` via Story 1.8's `RoleGuard`
  - [ ] Fetch profile via TanStack Query through `lib/api.ts`; render decrypted name/email/address + KYC `Badge`
  - [ ] KYC status → `Badge` variant: Verified=green, Pending=amber, Rejected=red (reuse `components/ui/Badge.tsx` variant API from Story 1.1 — do NOT build a new badge)
  - [ ] When KYC = REJECTED: show the rejection reason and a "Re-submit KYC documents" link/CTA (route per UX brief, e.g. `/profile/kyc`)
  - [ ] TailwindCSS utility classes only; PascalCase component; `usePascalCase.ts` hook if extracted
- [ ] **Task 4: Frontend — edit form** (AC: #3, #4)
  - [ ] Editable form for address/email; submit → `PATCH` via TanStack Query mutation; invalidate/refetch the profile query on success
  - [ ] Surface validation/envelope errors inline
- [ ] **Task 5: Tests** (AC: #1–#7)
  - [ ] Backend unit (`service_webapp/tests/unit/`): encrypt→decrypt round-trip yields original value; PATCH writes exactly one `UPDATE_PROFILE` audit row; authz — a token whose `sub` ≠ record owner gets 403; assert no PII in captured logs
  - [ ] Frontend (Vitest + RTL): correct `Badge` variant per KYC status; Rejected renders reason + resubmit link; edit submit triggers PATCH and refetch

## Dev Notes

### Scope boundary

- **DOES:** view profile (decrypt-on-read), edit address/email (re-encrypt + audit), KYC status display with Verified/Pending/Rejected badge, rejected-reason + resubmit CTA, owner-only authorization.
- **DOES NOT:** implement KYC **verification logic** — the KYC status in `identity_kyc_records` is seeded/simulated and set elsewhere (this story only *reads* it). Does NOT build the payment-methods sub-page (Story 1.10). Does NOT add DB tables.

### Dependencies & prerequisites

- **Story 1.6** — created the encrypted PII columns and `identity_subscribers` / `identity_kyc_records` rows. The pgcrypto encrypt/decrypt convention (`pgp_sym_encrypt`/`pgp_sym_decrypt`, key from `settings`) is established there; reuse it exactly.
- **Story 1.8** — JWT middleware + `core/auth.py` role guard + `RoleGuard.tsx` + `lib/auth.ts`. This story's endpoints sit behind that guard; the page sits under `/subscriber/*`.
- **Story 1.1** — UX brief defines `/profile`, `/profile/kyc` routes and the three `Badge` variants. **Story 1.4** — config singleton, OTEL middleware, response envelope.

### RESOLVED — no new migration (use the V1 baseline)

All tables already exist in the **full V1 all-domain baseline** (Story 1.2). This story USES `identity_subscribers` and `identity_kyc_records`; it adds **no** core tables and **no** new migration. [Source: 1-2 story "RESOLVED V1 scope decision"; architecture.md#1.12.1]

### Canonical names & data shape

- `identity_subscribers` (master record, **UUIDv4** PK `id`) holds the encrypted PII columns; `identity_kyc_records` (**UUIDv7** PK) holds KYC `status` + rejection reason, FK `subscriber_id`. [Source: architecture.md#1.7.1; 1-2 story UUID split]
- `billing_audit_log` is **append-only** (INSERT only via the app role). Write `UPDATE_PROFILE` events here — never UPDATE/DELETE. [Source: architecture.md#1.7.1 (line 378)]

### PII handling (decrypt-on-read, re-encrypt-on-write)

- Name/email/address are AES-256 column-encrypted at rest via pgcrypto. Decrypt only for the authenticated owner; return decrypted values in the API response but **never** log them or place them in OTEL span attributes — use the subscriber UUID, or `[-4:]` for any MSISDN. [Source: architecture.md#1.8.2 (PII encryption), #1.11.6 (PII hygiene rules)]
- Encryption key comes from `settings` (Story 1.4) — no hard-coded key (architecture §1.11.1).

### API & frontend conventions

- Endpoints in `service_webapp/src/routers/account.py` (FR-1–7), `async def`, standard envelope, HTTP codes per §1.11.3 (200 ok, 403 forbidden, 422 validation). [Source: architecture.md#1.11.3]
- Frontend: `src/portals/subscriber/Profile.tsx`, **TailwindCSS only** (no SCSS modules), PascalCase components / `usePascalCase.ts` hooks; server state via **TanStack Query** (no Redux); API via `lib/api.ts` (Axios + error interceptor). Reuse shared `components/ui/Badge.tsx`. [Source: architecture.md#1.9.3, #1.11.2, #1.12.1; ux-brief-identity.md AC #3]

### Project Structure Notes

- New/extended backend: `service_webapp/src/routers/account.py` (GET + PATCH profile). New frontend: `frontend/src/portals/subscriber/Profile.tsx`.
- Backend dir is **`service_webapp/`** (architecture says `app-backend/`/`service_webapp/` — read as `service_webapp/` per the project decision). [Source: 1-2 story "RESOLVED backend directory decision"]
- Variance: the UX brief places the KYC re-submit behind `/profile/kyc`; confirm the exact resubmit route/affordance against the brief at implementation time.

### Testing standards summary

- pytest via `uv tox`; backend unit tests in `service_webapp/tests/unit/` (testcontainers-Postgres only if an encrypt/decrypt integration check is wanted). Frontend: Vitest + React Testing Library (no Cypress for MVP). [Source: architecture.md#1.11.8]
- Critical assertions: encrypt/decrypt round-trip; one `UPDATE_PROFILE` audit row per edit; owner-only authz (403 on `sub` mismatch); Badge variant per status; rejected-reason + resubmit link.

### References

- [Source: epics.md#Story-1.9 (lines 472–494)]
- [Source: architecture.md#1.7.1-PostgreSQL-Table-Naming (identity tables, append-only audit, lines 357–378)]
- [Source: architecture.md#1.8.2-Security-Controls (PII encryption, lines 616–627)]
- [Source: architecture.md#1.11.3-API-Response-Format (lines 825–847)]
- [Source: architecture.md#1.11.6-PII-Hygiene-Rules (lines 938–943)]
- [Source: architecture.md#1.12.1-Monorepo-Layout (routers/account.py, frontend tree)]
- [Source: ux-brief-identity.md (Story 1.1 — /profile, /profile/kyc routes; Badge variants AC #3)]
- [Source: 1-2-docker-compose-stack-postgres-init-flyway-baseline.md (V1 full baseline; canonical names; UUID split)]
- [Source: 1-6 (encrypted PII columns, pgcrypto convention), 1-8 (RoleGuard, JWT middleware, lib/auth.ts)]

## Dev Agent Record

### Agent Model Used

{{agent_model_name_version}}

### Debug Log References

### Completion Notes List

### File List
