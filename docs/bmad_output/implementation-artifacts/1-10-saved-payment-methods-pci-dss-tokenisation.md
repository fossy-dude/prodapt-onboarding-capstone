# Story 1.10: Saved Payment Methods & PCI-DSS Tokenisation

Status: review

baseline_commit: 01065f31a525e73748217d7ba1a8fe69f580673e

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As an **authenticated subscriber**,
I want to add and manage saved payment methods (credit card, UPI, net banking, mobile wallet) with card numbers tokenised at the point of entry,
so that I can recharge quickly without re-entering payment details and my card data is never stored in plain text.

## Acceptance Criteria

1. **Given** a subscriber navigates to `/subscriber/profile/payment-methods`, **When** they add a credit card, **Then** the card number is tokenised **client-side before it leaves the browser**, and only `{token, display_label (last-4), type}` is sent to the API; the record persists to `recharge_payment_methods` storing the token and last-4 only (FR-6, FR-64, NFR-5).
2. **Raw PAN is never present** in any API request/response payload, server log, database column, or OTEL span attribute (NFR-5, NFR-16).
3. The `recharge_payment_methods` row stores: `id` (UUIDv4), `subscriber_id`, `type` (`CREDIT_CARD | UPI | NET_BANKING | MOBILE_WALLET`), `token`, `display_label`, `is_default`.
4. **Given** a subscriber adds a UPI ID or net banking account or mobile wallet, **When** the record is saved, **Then** no tokenisation is applied (these are not card numbers); the identifier is stored as-is.
5. **Given** a subscriber has multiple saved payment methods, **When** they view `/subscriber/profile/payment-methods`, **Then** all saved methods are listed with a type icon, `display_label` (e.g., `"•••• 4242"`), and a **"Set Default"** action; setting a new default clears the previous default (exactly one default at a time).
6. All endpoints return the standard FastAPI envelope (`{data, meta:{trace_id, timestamp}}`); a subscriber may only read/modify their own payment methods (JWT `sub`-claim match → 403 otherwise).

## Tasks / Subtasks

- [x] **Task 1: Client-side tokenisation utility** (AC: #1, #2)
  - [x] Create `frontend/src/lib/tokenize.ts` — `tokenizeCard(pan: string) => { token: string; last4: string }`. Generate an opaque token (UUID v4) and extract the last 4 digits. The raw PAN exists only in component state during entry and is **never** placed in any object that is sent over the network.
  - [x] The PAN input field value is consumed by `tokenizeCard` and then discarded; the form submits `{ type, token, display_label }` only.
  - [x] **Simulated tokenisation** — there is no real PCI gateway in MVP. This mimics a tokenisation provider returning an opaque reference (architecture §1.8.2: "raw PAN → UUID token at point of entry; raw PAN never written to DB").
- [x] **Task 2: Payment methods UI** (AC: #1, #4, #5)
  - [x] Create `frontend/src/portals/subscriber/PaymentMethods.tsx` at route `/subscriber/profile/payment-methods` (role-gated under `/subscriber/*` via the RoleGuard from Story 1.8).
  - [x] Add form supports all four `type` values. For `CREDIT_CARD`, run `tokenizeCard` and build `display_label = "•••• " + last4`. For `UPI`/`NET_BANKING`/`MOBILE_WALLET`, take the identifier as-is and derive a sensible `display_label` (e.g. masked UPI handle / bank name).
  - [x] List view: type icon + `display_label` + "Set Default" action. Reuse `components/ui/` (`Button`, `Card`, `Table`). TailwindCSS utility classes only; PascalCase component; server state via TanStack Query against `lib/api.ts`.
- [x] **Task 3: Backend payment-method endpoints** (AC: #1, #3, #4, #6)
  - [x] Add CRUD routes to `service_webapp/src/routers/account.py` (profile-adjacent, FR-6): `POST` (add), `GET` (list), `PATCH .../{id}/default` (set default), `DELETE .../{id}`. (Placed in `account.py` rather than a recharge router because these are profile-management operations, not recharge transactions.)
  - [x] Persist to `recharge_payment_methods` via the `DatabaseProtocol` adapter. PK `id` defaults to `gen_random_uuid()` (UUIDv4); `subscriber_id` FK from the JWT `sub` claim.
  - [x] **Set-default semantics**: setting `is_default = true` on one row clears `is_default` on all other rows for that `subscriber_id` (single transaction).
  - [x] **Defensive PAN guard**: reject (HTTP 422) any payload whose `token` field matches a raw-PAN pattern (13–19 contiguous digits / passes Luhn) — tokenisation is client-side, so a PAN reaching the server is a client bug and must never be stored or logged.
  - [x] Authorisation: every operation scoped to `subscriber_id == jwt.sub`; cross-subscriber access → 403.
- [x] **Task 4: PII/PAN hygiene** (AC: #2)
  - [x] Ensure no router/service logs the request body for these endpoints; never emit `token`-input or any card field to OTEL span attributes (§1.11.6).
  - [x] Confirm the table has no PAN column — only `token`, `display_label` (last-4) exist (already true in the V1 baseline schema).
- [x] **Task 5: Tests** (AC: #1, #2, #3, #5, #6)
  - [x] Frontend (Vitest + RTL): adding a card sends a request whose body contains **no PAN** (assert the serialized payload has no 13–19 digit sequence and no full card number); `display_label` renders as `"•••• 4242"`; "Set Default" calls the default endpoint.
  - [x] Backend (`service_webapp/tests/unit/`): add stores `token` + `display_label` only; set-default flips the previous default to false; raw-PAN-shaped `token` payload → 422; cross-subscriber access → 403.

## Dev Notes

### Scope boundary — what this story does and does NOT do

- **DOES:** Add / list / set-default / delete saved payment methods; client-side card tokenisation; the four `type` variants; authorised CRUD with the standard envelope; PAN-hygiene guards and tests.
- **DOES NOT:** Process payments or run a recharge (that is Epic 3 — `recharge_orders`/`recharge_receipts`). These are **saved methods only**. No real payment gateway integration; tokenisation is simulated.

### RESOLVED decisions (use these EXACTLY)

| Concern | **Use this** | Do NOT use (epics shorthand) |
|---|---|---|
| Table | `recharge_payment_methods` | ~~`payment_methods`~~ |
| PK column | `id` (UUIDv4, `gen_random_uuid()`) | ~~`payment_method_id`~~ |
| FK | `subscriber_id` | — |
| Migration | **none** — table already in V1 baseline | ~~`V4__payment_schema.sql`~~ |

- **No new Flyway migration.** Per Story 1.2, `V1__baseline_schema.sql` is the **full all-domain baseline** — `recharge_payment_methods` already exists. The epics' `V4__payment_schema.sql` is superseded; this story *uses* the existing table (add grants/views only if needed). [Source: 1-2-...-flyway-baseline.md "RESOLVED V1 scope decision"; architecture.md §1.12.1]
- **UUIDv4 PK** because `recharge_payment_methods` is a saved-config/reference record, not a high-insert transaction stream — consistent with epics 1.10 (`payment_method_id (UUIDv4)`) and the §1.7.1 UUID split (v7 only for transactional tables). [Source: architecture.md §1.7.1; 1-2 UUID table]

### Client-side tokenisation is the critical requirement

- The PAN must be tokenised **in the browser, before any network call** — only `{type, token, display_label}` ever crosses the wire. The server, DB, logs, and OTEL spans never see a PAN. This is the literal reading of epics 1.10 ("tokenised client-side before leaving the browser") and NFR-5/NFR-16. [Source: epics.md#Story-1.10; architecture.md §1.8.2, §1.11.6]
- This is **simulated** tokenisation (no PCI gateway in MVP): generate a UUID token + keep last-4. Architecture §1.8.2: "Simulated tokenisation: raw PAN → UUID token at point of entry; raw PAN never written to DB."
- Add the **defensive server-side guard** anyway: reject any `token` that looks like a raw PAN (13–19 digits / Luhn-valid). Client-side tokenisation is the design, but the server must fail closed if a PAN ever arrives — never persist or log it.
- Non-card methods (UPI / net banking / mobile wallet) are identifiers, not card numbers: stored as-is, **not** tokenised (AC #4). Still treat them as sensitive — do not log them.

### API & authorisation

- Routes live in `service_webapp/src/routers/account.py` (FR-6 is account/profile management). Standard envelope §1.11.3; status codes 201 (add), 200 (list/set-default), 403 (cross-subscriber), 422 (validation / PAN guard), 404 (unknown id). [Source: architecture.md §1.11.3, §1.12.1]
- Every operation is scoped to the authenticated subscriber via the JWT `sub` claim (decoded by the Story 1.8 middleware in `core/auth.py`). No subscriber may see or mutate another's methods.

### Frontend conventions

- `frontend/src/portals/subscriber/PaymentMethods.tsx`; TailwindCSS utility classes only (no per-component CSS); PascalCase component, `usePascalCase.ts` hooks if extracted. Server state via TanStack Query; HTTP via `lib/api.ts` (Axios + interceptor that attaches the JWT). Route is role-gated under `/subscriber/*` by the RoleGuard from Story 1.8. Reuse the shared `components/ui/` primitives (`Button`, `Card`, `Table`) defined in the Story 1.1 UX brief. [Source: architecture.md §1.9.1, §1.9.3, §1.11.2, §1.12.1; ux-brief-identity.md]

### Dependencies & prerequisites

- **Story 1.8** — JWT middleware + `RoleGuard` + `lib/auth.ts` (auth context, role gating, `sub` claim).
- **Story 1.6** — the subscriber record exists (`identity_subscribers`).
- **Story 1.2** — `recharge_payment_methods` present in the V1 baseline; Postgres + extensions.
- **Story 1.4** — settings singleton, OTEL middleware, response-envelope helper.
- **Story 1.1** — UX brief (`/profile/payment-methods` route, shared UI components).

### Project Structure Notes

- New: `frontend/src/lib/tokenize.ts`, `frontend/src/portals/subscriber/PaymentMethods.tsx`.
- Extends (does not replace): `service_webapp/src/routers/account.py` (add payment-method routes alongside Story 1.6/1.9 account routes — coordinate so you augment rather than duplicate).
- No migration file. If a read grant for `recharge_payment_methods` is missing for `sboai_app`, fold it into the grants migration rather than creating a per-story schema migration.

### Testing standards summary

- Backend: pytest via `uv tox`; unit tests in `service_webapp/tests/unit/` (Postgres via testcontainers if integration coverage is wanted). Python 3.11; ruff + mypy gates. [Source: architecture.md §1.11.7, §1.11.8]
- Frontend: Vitest + React Testing Library (no Cypress for MVP). Critical assertion: the add-card request body contains **no PAN**. [Source: architecture.md §1.11.8]

### References

- [Source: epics.md#Story-1.10 (lines 496–517)]
- [Source: architecture.md#1.7.1-PostgreSQL-Table-Naming (recharge_payment_methods; UUIDv4 split)]
- [Source: architecture.md#1.8.2-Security-Controls (simulated card tokenisation, line 623)]
- [Source: architecture.md#1.11.3-API-Response-Format (envelope, lines 825–847)]
- [Source: architecture.md#1.11.6-PII-Hygiene-Rules (PAN never in logs/spans, lines 938–943)]
- [Source: architecture.md#1.12.1-Monorepo-Layout (frontend tree, routers)]
- [Source: 1-2-docker-compose-stack-postgres-init-flyway-baseline.md — V1 full baseline; no per-story payment migration]
- [Source: docs/bmad_output/planning-artifacts/ux-brief-identity.md — /profile/payment-methods route]

## Dev Agent Record

### Agent Model Used

{{agent_model_name_version}}

### Debug Log References

### Completion Notes List
- ✅ **Task 1 complete**: Client-side tokenisation utility implemented following red-green-refactor cycle. Created `frontend/src/lib/tokenize.ts` with `tokenizeCard()` function that generates UUID v4 tokens and extracts last-4 digits. Comprehensive test suite (16 tests) covering security requirements (no PAN exposure), token generation, last-4 extraction, input validation, and output format consistency. All tests pass, TypeScript strict mode and ESLint validation successful.
- ✅ **Task 2 complete**: Payment methods UI implemented at `frontend/src/portals/subscriber/PaymentMethods.tsx` with route `/subscriber/profile/payment-methods`. Supports all 4 payment types (CREDIT_CARD, UPI, NET_BANKING, MOBILE_WALLET). Integrated client-side tokenisation for cards, TanStack Query for server state, TailwindCSS styling, and emoji icons. Comprehensive test suite (11 tests) including critical security tests asserting no PAN in API payloads. All tests pass, TypeScript and ESLint validation successful.
- ✅ **Task 3 complete**: Backend payment-method endpoints implemented in `service_webapp/src/routers/account.py` with `/api/v1/account/payment-methods` router. CRUD operations include POST (add), GET (list), PATCH /{id}/default (set default), DELETE /{id}. Defensive PAN guard rejects raw PAN patterns (13-19 digits or Luhn-valid) with HTTP 422. Set-default semantics ensure exactly one default per subscriber via single transaction. JWT-scoped access control enforces subscriber_id == jwt.sub with 403 for cross-subscriber access. Comprehensive test suite (17 tests) covers security, authorisation, and functionality.
- ✅ **Task 4 complete**: PII/PAN hygiene implemented. No request body logging for payment endpoints. No PAN column in table (only token + display_label). Defensive PAN guard prevents raw PAN storage.
- ✅ **Task 5 complete**: Comprehensive test coverage. Frontend: 11 tests with critical security assertions for no PAN in API payloads. Backend: 17 tests covering CRUD operations, PAN guard, authorisation, and edge cases. All tests pass with proper validation of security requirements.

### File List
- frontend/src/lib/tokenize.ts (new)
- frontend/src/lib/tokenize.test.ts (new)
- frontend/src/types/payment-method.ts (new)
- frontend/src/portals/subscriber/PaymentMethods.tsx (new)
- frontend/src/portals/subscriber/PaymentMethods.test.tsx (new)
- frontend/src/lib/api.ts (modified)
- frontend/src/App.tsx (modified)
- service_webapp/src/routers/account.py (modified)
- service_webapp/src/main.py (modified)
- service_webapp/tests/api/test_payment_methods.py (new)
