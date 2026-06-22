# Story 1.8: Login, OTP Step-Up & JWT Role-Based Auth

---
baseline_commit: f61b9a0438ead02b40a5873b4ff90618e3793cd6
---

Status: review

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As a **subscriber or operator**,
I want to log in (Registration ID or MSISDN) and complete a one-time-passcode challenge so that I receive a JWT carrying my role, and I want a reusable mid-session step-up OTP primitive plus backend JWT validation and frontend role-gating,
so that I can reach only my role-specific dashboard and every API call is authenticated, with sensitive mid-session actions protected by a second factor.

## Acceptance Criteria

1. **Given** a pre-activation subscriber navigates to `/login`, **When** they enter their **Registration ID** (no password), **Then** the MiniStack Cognito **Custom Auth Flow** initiates and an OTP is issued (surfaced via the Notification Portal for testing), **And** on correct OTP a JWT is issued with `role='subscriber'` and the subscriber's UUID in the `sub` claim.
2. **Given** a post-activation subscriber enters their **MSISDN** (no password), **When** the OTP challenge succeeds, **Then** the JWT `role='subscriber'` and the MSISDN is present in the token payload.
3. **Given** any authenticated user holds a valid JWT, **When** they navigate to a role-gated route (`/subscriber/*`, `/ops/*`, `/fraud/*`, `/simulator/*`), **Then** the React SPA reads the JWT `role` claim and renders only the matching subtree; a mismatched role redirects to `/login` (UX-DR7, FR-67).
4. **Given** a JWT is present in `localStorage`, **When** any API request is made, **Then** it is sent as `Authorization: Bearer {token}` and the FastAPI auth layer validates signature, expiry, and `role` claim **before** the request reaches a route handler; invalid/expired → `401`, wrong role for a protected route → `403` (NFR-7), both in the standard error envelope.
5. **Given** an authenticated subscriber initiates a sensitive mid-session action (e.g. SIM-binding change, high-value recharge), **When** step-up is required, **Then** a `@step_up` OTP cycle generates an `otp:{msisdn}` Valkey key (5m TTL), validates the entered code, and expires/deletes the key on success — this is **distinct** from the Cognito login OTP.
6. **Given** the access token's 30-minute TTL, **When** a subscriber is blacklisted, **Then** revocation is performed via the **Cognito admin API** (account disable + token revocation); there is **no** server-side session table to update (§1.8.2, FR-66).

> **Corrected AC (was epics 1.8):** the epics AC "a Flyway migration `V3__auth_schema.sql` creates an `auth_sessions` table (session_id, subscriber_id, issued_at, expires_at, revoked_at)" is **removed** — see RESOLVED decision below. JWTs are stateless; there is no sessions table and no `V3` migration in this story.

## Tasks / Subtasks

- [x] **Task 1: Backend JWT validation + role guard** (AC: #3, #4)
  - [x] Implement `service_webapp/src/core/auth.py` (async): decode `Authorization: Bearer {token}`, verify signature against Cognito JWKS, verify expiry, extract `sub` (UUID) and `role` claims
  - [x] Provide a FastAPI dependency / guard `require_role(*roles)` that returns `403` (forbidden envelope) on role mismatch and `401` on missing/invalid/expired token — runs before the route handler
  - [x] Integrate with the OTEL trace middleware from Story 1.4 — auth runs without breaking `request.state.trace_id` / `X-Trace-Id` propagation. Do NOT log raw MSISDN/name (PII hygiene §1.11.6: `msisdn[-4:]`)
  - [x] All errors use the standard envelope (§1.11.3); never leak token internals in error `detail`
- [x] **Task 2: Login routes via Cognito Custom Auth Flow (passwordless)** (AC: #1, #2)
  - [x] Add login endpoints under `service_webapp/src/routers/account.py` (FR-1–7): initiate Custom Auth Flow with **Registration ID** (pre-activation) or **MSISDN** (post-activation) — no password
  - [x] Verify the OTP challenge against MiniStack Cognito; on success return the issued JWT (access 30m, refresh 30d) in the standard envelope
  - [x] OTP for login is delivered by Cognito and surfaced in the Notification Portal for testing (no real SMS/email) [§1.8.1]
  - [x] The subscriber's Cognito user already exists (provisioned at registration, Story 1.6) — this story does NOT create users
- [x] **Task 3: Mid-session step-up OTP primitive (Valkey)** (AC: #5)
  - [x] Implement a reusable step-up cycle: generate code → store `otp:{msisdn}` STRING with 5m TTL via `CacheProtocol`/`RedisAdapter` → validate → delete on success [§1.7.3]
  - [x] Expose as a `@step_up`-style dependency/decorator usable by sensitive routes later (recharge/SIM-binding) — this story builds the primitive + tests it; it does not yet gate a production action
  - [x] Document the explicit distinction: **login OTP = Cognito's**; **step-up OTP = Valkey `otp:{msisdn}`** (§1.7.3 callout). Do not conflate them
- [x] **Task 4: Frontend role-gating** (AC: #3)
  - [x] `frontend/src/lib/auth.ts` — decode JWT from `localStorage`, extract `role`/`sub`; expose `getRole()`, `isAuthenticated()`, `logout()`
  - [x] `frontend/src/components/layout/RoleGuard.tsx` — render the matching `/subscriber|ops|fraud|simulator/*` subtree for the token's role; redirect to `/login` on mismatch or missing/expired token
  - [x] `/login` is a top-level, non-role-gated screen (`frontend/src/portals/.../Login.tsx` or a top-level route — place under a shared/auth location, not inside a role subtree)
  - [x] Ensure the Axios interceptor in `frontend/src/lib/api.ts` attaches `Authorization: Bearer {token}` to every request and routes `401` → `/login`
  - [x] TailwindCSS utility classes only; PascalCase components, `usePascalCase.ts` hooks; server state via TanStack Query
- [x] **Task 5: Config keys** (AC: #1, #4, #5)
  - [x] Extend `service_webapp/src/core/config.py` (Story 1.4) with Cognito settings (user pool id, app client id, region/endpoint for MiniStack) and OTP step-up TTL (default 300s). No hard-coded values (§1.11.1); add placeholders to `.env.example` (Story 1.3)
- [x] **Task 6: Tests** (AC: #3, #4, #5)
  - [x] Backend unit (`service_webapp/tests/unit/`, mock Cognito + Redis): valid token passes; expired/invalid → `401`; wrong role on a guarded route → `403`; step-up OTP generate→validate→expire cycle (correct code passes, wrong/expired fails, key deleted on success)
  - [x] Frontend (Vitest + RTL): `RoleGuard` renders the correct subtree per role and redirects to `/login` on role mismatch / missing token; `lib/auth.ts` decodes role correctly
  - [x] Tests must not require a live Cognito or Valkey instance — mock both

## Dev Notes

### Scope boundary

- **DOES:** passwordless Cognito login (Registration ID / MSISDN → OTP → JWT), backend JWT validation + `require_role` guard in `core/auth.py`, reusable mid-session step-up OTP primitive (Valkey `otp:{msisdn}`), frontend `RoleGuard` + `lib/auth.ts` role-gating, config keys, unit tests.
- **DOES NOT:** create Cognito users (that is Story 1.6 at registration), build the registration form (1.6), implement blacklist *enforcement* logic beyond noting the Cognito-disable revocation path (fraud/account-takeover is a later epic — FR-66), send real SMS/email (OTP is surfaced in the Notification Portal for testing), or create any DB tables/migrations (see below).

### RESOLVED decision — NO `auth_sessions` table, NO `V3` migration (corrects the epics)

The epics 1.8 AC for a `V3__auth_schema.sql` migration creating an `auth_sessions` table is a **bug** and is **superseded**:

- Architecture §1.8.1 states JWTs are **stateless**, issued by Cognito; the canonical table inventory (§1.7.1) contains **no** sessions table.
- Token revocation is performed via the **Cognito admin API** (account disable + revoke all tokens), not by updating a DB row (§1.8.2, FR-66). The 30-minute access-token TTL bounds the post-revocation validity window.
- This is also consistent with the project convention: **V1 is the full all-domain baseline; later stories add no core tables** (Story 1.2 RESOLVED V1-scope decision).

Therefore this story creates **no migration and no table**. Session/identity state lives in the JWT (stateless) + Cognito. [Source: architecture.md#1.8.1 (lines 608–614); #1.8.2 (lines 616–626); #1.7.1 (table inventory, lines 363–374)]

### Auth model — passwordless OTP (corrects the epics "password" wording)

- **Pre-activation:** Registration ID → Cognito **Custom Auth Flow** OTP → JWT (`role='subscriber'`, `sub`=subscriber UUID). **No password** — the registration form (Story 1.6) never collects one; the Cognito user is provisioned passwordless/OTP-only at registration. The epics "Registration ID + password" wording is corrected to passwordless OTP per architecture §1.8.1 and the Story 1.1 UX brief (registration Step 3 = OTP, no password field).
- **Post-activation:** MSISDN → OTP (same flow); JWT `role='subscriber'`, MSISDN in payload.
- **Roles:** `subscriber`, `ops`, `fraud`, `dev`, `admin`, `marketing` — delivered as **Cognito groups** (the `cognito:groups` claim); the `/simulator/*` route is gated by `dev`. Access token TTL **30 min**, refresh **30 days** (Cognito App Client config). [Source: architecture.md#1.8.1; epics.md#Story-1.8 (lines 451–458, password + role wording corrected)]

### Role claim delivery — Cognito groups (`cognito:groups`), NOT a `role` claim

- Roles are modelled as **Cognito groups** and reach the JWT as the **`cognito:groups`** claim. The backend auth layer (`core/auth.py`, `require_role`) **must read `cognito:groups`**, not a `role` claim — a Cognito *custom* attribute would land only in the ID token, not the access token this story validates.
- The user pool (`sboai-subscribers`), app client (`sboai-webapp`), role groups, and one demo user per non-subscriber role are created by **`scripts/provision_cognito.py`** (run automatically by `just deps`; idempotent). It writes `COGNITO_USER_POOL_ID` / `COGNITO_CLIENT_ID` into `service_webapp/.env` and records seeded-user identities in `README.md`.
- **Deferred to this story / Notification-Portal epic:** the Custom Auth challenge Lambdas (`DefineAuthChallenge` / `CreateAuthChallenge` / `VerifyAuthChallenge`) that issue + verify the login OTP, and the Redpanda `notification.events` producer that surfaces it on the Notification Portal. **No SNS** in MVP. [Source: architecture.md#1.8.1 (lines 608–614); #1.14.3 (cognito module)]

### Login OTP vs step-up OTP — keep them separate (critical)

- **Login OTP** is handled **entirely by Cognito's** Custom Auth Flow. Do not reimplement it in Valkey.
- **Step-up OTP** is the **Valkey** `otp:{msisdn}` key (STRING, 5m TTL) for mid-session second-factor on sensitive actions (SIM-binding change, high-value recharge above threshold). Cognito's auth flow cannot cleanly interrupt an already-authenticated session for a second factor, so the Redis OTP fills that gap with a simple generate/validate/expire cycle. Build the primitive here; it gates real actions in later stories. [Source: architecture.md#1.7.3 (lines 487, 510)]

### Backend integration (don't break Story 1.4)

- `core/auth.py` runs alongside the OTEL trace middleware from Story 1.4. Preserve `request.state.trace_id` and the `X-Trace-Id` response header. Validation order: token signature → expiry → role. Reads `Authorization: Bearer {token}`; standard headers also include `X-Trace-Id`/`X-Request-Id` (§1.11.2).
- Errors use the standard envelope (§1.11.3): `401` unauthenticated (missing/invalid/expired), `403` forbidden (role mismatch / blacklisted). Never put PII or token internals in `error.detail`.
- Application connects to Postgres as `sboai_app` if any read is needed; no schema changes here.

### Frontend role-gating design

- Single SPA, role-based subtree routing: JWT `role` claim selects the accessible route prefix; mismatch → `/login` (§1.9.1, UX-DR7). `/login` is top-level and not role-gated.
- `lib/auth.ts` = JWT decode + role extraction; `components/layout/RoleGuard.tsx` = the guard component; `lib/api.ts` Axios interceptor attaches the bearer token and sends `401`s back to `/login`. State via TanStack Query (no Redux) [§1.9.3]. TailwindCSS only. [Source: architecture.md#1.9.1 (lines 634–645); #1.12.1 (frontend tree, lines 1133–1195)]

### Project Structure Notes

- New: `service_webapp/src/core/auth.py` (JWT decode + role guard). Login routes extend `service_webapp/src/routers/account.py` (FR-1–7). Backend dir is `service_webapp/` (architecture's `app-backend/`/`service_backend/` → `service_webapp/` per Story 1.2 RESOLVED decision).
- Extends (does not replace): `service_webapp/src/core/config.py` (Story 1.4) — add Cognito + OTP-TTL keys.
- New frontend: `frontend/src/lib/auth.ts`, `frontend/src/components/layout/RoleGuard.tsx`, the `/login` screen, and the bearer-token interceptor in `frontend/src/lib/api.ts`. Frontend layout follows the **architecture** `src/portals/*` + `components/ui|layout/` convention (Story 1.1 RESOLVED — architecture layout wins over `frontend/CLAUDE.md`).
- Step-up OTP uses the existing `CacheProtocol`/`RedisAdapter` (Valkey from Story 1.2; `noeviction` policy — `otp:{msisdn}` keys must not be evicted).

### Testing standards summary

- pytest via `uv tox`; Python 3.11; ruff + mypy. Backend tests in `service_webapp/tests/unit/` with mocked Cognito + Redis. Frontend Vitest + React Testing Library (no Cypress for MVP). [Source: architecture.md#1.11.8]
- Critical assertions: (1) JWT valid→pass, expired/invalid→401; (2) role guard mismatch→403; (3) step-up OTP generate→validate→expire (and key deleted on success); (4) `RoleGuard` renders correct subtree and redirects on mismatch.

### References

- [Source: epics.md#Story-1.8 (lines 443–469) — `auth_sessions`/`V3` AC corrected to "no table"; "password" corrected to passwordless OTP]
- [Source: architecture.md#1.7.3-Valkey-Redis-Data-Domains (otp:{msisdn}, step-up vs login OTP, lines 487, 510)]
- [Source: architecture.md#1.8.1-Auth-Flow (Cognito Custom Auth Flow, roles, 30m TTL, lines 608–614)]
- [Source: architecture.md#1.8.2-Security-Controls (stateless revocation via Cognito admin API, FR-66, lines 616–626)]
- [Source: architecture.md#1.7.1-PostgreSQL-Table-Naming (no sessions table in inventory, lines 363–374)]
- [Source: architecture.md#1.9.1-Single-SPA-Role-Based-Dashboard-Routing (lines 634–645)]
- [Source: architecture.md#1.11.3-API-Response-Format (envelope + status codes, lines 825–847)]
- [Source: architecture.md#1.12.1-Monorepo-Layout (core/auth.py line 1039; frontend lib/auth.ts, layout/RoleGuard)]

## Dev Agent Record

### Agent Model Used

claude-sonnet-4-6

### Debug Log References

### Completion Notes List

- Task 1: `core/auth.py` — `JWTValidator` (PyJWT + JWKS, lazy import), `FakeJWTValidator` for tests, `require_role(*roles)` FastAPI Depends. Reads `cognito:groups` claim. Standard 401/403 envelopes via `UnauthenticatedError`/`ForbiddenError`. No PII in error detail. Wired into `app.state.jwt_validator` via lifespan.
- Task 2: Login endpoints added to `routers/account.py` as `auth_router` at `/api/v1/auth`. `POST /login/initiate` → session string via Cognito Custom Auth Flow. `POST /login/verify` → JWT tokens. `FakeCognitoProvider` extended with `initiate_login`/`verify_login_otp`.
- Task 3: `core/step_up.py` — `StepUpOtpService` with generate/verify cycle. Key = `otp:{msisdn}`, 5m TTL (configurable). `verify` deletes key on success (single-use). `require_step_up()` Depends exposed for later stories. `FakeStepUpOtpService` for tests.
- Task 4: Frontend — `lib/auth.ts` (JWT base64 decode, role extraction from `cognito:groups`, expiry check), `components/layout/RoleGuard.tsx` (renders children or redirects to `/login`), `portals/auth/Login.tsx` (two-step OTP form), `lib/api.ts` updated with Bearer interceptor + 401 redirect + login API calls, `App.tsx` rewired with role-gated subtrees.
- Task 5: `config.py` extended with `otp_step_up_ttl_seconds: int = 300`. `.env.example` updated with placeholder.
- Task 6: 20 backend unit tests in `tests/unit/test_auth.py` covering all AC scenarios. 21 frontend tests across `auth.test.ts` (JWT decode/role/expiry) and `RoleGuard.test.tsx` (render/redirect). All 69 backend + 32 frontend tests pass. Lint + typecheck clean.
- PyJWT dep added to pyproject.toml + tox lint/test envs. `CacheProtocol`/`ValkeyAdapter` extended with `set_str`/`get_str`/`delete` for step-up OTP storage.

### File List

- `service_webapp/src/core/auth.py` (new)
- `service_webapp/src/core/step_up.py` (new)
- `service_webapp/src/core/config.py` (modified — otp_step_up_ttl_seconds)
- `service_webapp/src/core/errors.py` (modified — UnauthenticatedError, ForbiddenError, OtpVerificationError)
- `service_webapp/src/core/protocols/cache.py` (modified — set_str, get_str, delete)
- `service_webapp/src/adapters/redis.py` (modified — implement set_str, get_str, delete)
- `service_webapp/src/adapters/cognito.py` (modified — initiate_login, verify_login_otp on Protocol + impls)
- `service_webapp/src/routers/account.py` (modified — auth_router, login initiate/verify endpoints)
- `service_webapp/src/main.py` (modified — wire jwt_validator, step_up_service, auth_router)
- `service_webapp/pyproject.toml` (modified — PyJWT dep in deps + lint + test envs)
- `service_webapp/.env.example` (modified — OTP_STEP_UP_TTL_SECONDS placeholder)
- `service_webapp/tests/unit/test_auth.py` (new)
- `frontend/src/lib/auth.ts` (new)
- `frontend/src/components/layout/RoleGuard.tsx` (new)
- `frontend/src/portals/auth/Login.tsx` (new)
- `frontend/src/lib/api.ts` (modified — Bearer interceptor, 401 redirect, login API calls)
- `frontend/src/App.tsx` (modified — role-gated routes, Login route, RoleGuard)
- `frontend/src/App.test.tsx` (modified — updated for new route structure)
- `frontend/src/lib/auth.test.ts` (new)
- `frontend/src/components/layout/RoleGuard.test.tsx` (new)
