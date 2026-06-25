# Plan: Real Passwordless OTP Login Flow (Backend-Driven)

> **Status:** Proposed (Epic 3 / re-opens Story 1.8).
> Addresses the defect surfaced while documenting the Notification Portal URL and
> staff login: the passwordless OTP login flow is non-functional against the live
> stack today.

## Context

The question "which URL shows all notifications, and where do non-subscriber staff
(dev/marketing/ops) log in?" surfaced a real defect: **the passwordless OTP login
flow is non-functional against the live stack.**

Root cause (verified by trace):
- `MinistackCognitoProvider.initiate_login` (`service_webapp/src/adapters/cognito.py:228-252`)
  calls Cognito `CUSTOM_AUTH`, which requires the `DefineAuthChallenge`/`CreateAuthChallenge`/
  `VerifyAuthChallenge` Lambdas to issue a challenge. Those Lambdas were **never provisioned** —
  the pool is created with empty `LambdaConfig` (`scripts/provision_cognito.py:170-172`). Cognito
  returns an empty session → `CognitoProvisioningError`. **No login OTP is ever minted or
  published.**
- The only working OTP path is `FakeCognitoProvider` (hardcoded `OTP = "123456"`,
  `cognito.py:73`), which is test-only — never wired in dev (`main.py:182-183`).
- This is explicitly listed as deferred
  (`docs/bmad_output/implementation-artifacts/deferred-work.md:24-29`); Story 1.8 was marked
  "done" only because it was validated against the fake provider.

The README's dev-login instructions are therefore both circular (the Notification Portal needs a
`dev` JWT) AND unbacked by any implementation. The user chose to **build the real flow** with the
OTP published to Redpanda `notification.events`, and chose **Path A (deterministic local
password)** for token minting.

**Outcome:** a real, end-to-end working login — OTP minted server-side, stored in Valkey,
published to `notification.events` so it renders on the Notification Portal, then verified and
exchanged for a real Cognito RS256 JWT (validated unchanged by the existing `JWTValidator`).

## Key decisions (locked)

1. **Backend-driven, no Lambdas.** OTP mint/store/verify happens server-side; tokens come from
   Cognito via **`admin_initiate_auth(ADMIN_NO_SRP_AUTH)`** after a per-user local password is set
   at provisioning (Path A). The existing `JWTValidator` (`core/auth.py:51-94`,
   `verify_aud: False`, RS256/JWKS) accepts these tokens with **zero changes**.
2. **OTP delivery = Redpanda `notification.events`** (no SNS in MVP), matching the existing
   Notification Portal contract so it renders with no UI change.
3. **Bootstrap (first dev login):** relax the Notification Portal WebSocket to accept anonymous
   connections when `NOTIFICATION_PORTAL_OPEN_IN_DEV=true` (default off; MSISDNs already masked
   to `[-4:]` server-side by `to_notification_broadcast`, so no PII leak). Documented `rpk`
   fallback for operators who keep the socket authed.
4. **Drop the `session` field end-to-end** — it was a Cognito Custom Auth artifact; dead weight now.
5. **MSISDN normalization** lives in the backend (frontend sends national numbers, per the
   `Login.tsx:135` placeholder `9876543210`) — add an E.164 helper.

## Implementation

### 1. New module: `service_webapp/src/services/login_otp.py`
`LoginOtpService` encapsulates mint/store/verify/publish, keeping `cognito.py` FastAPI-free.
- Reuse `step_up.py:55` OTP mint: `secrets.choice("0123456789")` × 6.
- Store under Valkey key `login_otp:{identifier}` (distinct prefix from step-up's `otp:{msisdn}`),
  TTL = `settings.otp_login_ttl_seconds`, via `CacheProtocol.set_str(..., ex=ttl)`.
- `verify()` uses `hmac.compare_digest` and deletes the key on success (single-use), mirroring
  `step_up.py:60-77`.
- **Publish** to `notification.events` using the exact payload shape the portal already parses
  (mirror `_publish_activation_notification`, `routers/simulator.py:349-384`):
  `notification_type="LOGIN_OTP"`, `channel="SMS"`,
  `message_preview=f"Your SBOAI login code is {code}. Valid for 5 minutes."`,
  `msisdn=<identifier>`, wrapped via `EventEnvelope.new(event_type="notification.events", ...)`
  (`models/envelope.py`) with a `traceparent` header. The OTP appears in the portal row because
  `message_preview` is rendered directly.
- **Best-effort publish** (mirror `simulator.py:361-366`): if `producer is None`, log and continue
  — OTP still lives in Valkey, so login still works.

### 2. `service_webapp/src/adapters/cognito.py`
- Rewrite `initiate_login` to take `(identifier, trace_id, otp_service)` → call
  `otp_service.issue(...)`, return a (now-synthetic/ignored) marker.
- Rewrite `verify_login_otp` to take `(identifier, otp, otp_service)` → `otp_service.verify(...)`,
  then resolve the Cognito username and mint tokens via `admin_initiate_auth(ADMIN_NO_SRP_AUTH)`.
- Add `_resolve_username_sync(pool_id, identifier)`: try `admin_get_user(Username=identifier)`
  (covers Registration IDs + seeded users like `dev`); else `list_users(Filter='phone_number=...')`
  for MSISDN login.
- Add E.164 normalization (national → `+91...`) — call it here for the MSISDN path.
- `provision_user` (subscriber registration path, `cognito.py:179-195`): after `admin_create_user`,
  also `admin_set_user_password(..., Permanent=True)` with the deterministic seed so the same
  login flow works for subscribers.
- Update the `CognitoProvider` Protocol (`cognito.py:37-62`) signatures accordingly.
- Extend `FakeCognitoProvider` (`cognito.py:65-118`): keep returning fixed OTP/tokens, but record
  the would-be publish event into a new `self.published_login_otps` list so tests can assert it.

### 3. `scripts/provision_cognito.py`
- After `admin_create_user` for each demo user (`provision_cognito.py:284-292`), call
  `admin_set_user_password(pool_id, username, password=<seed>, Permanent=True)` to clear
  `FORCE_CHANGE_PASSWORD` and enable `admin_initiate_auth`. Idempotent (re-run safe).
- Update the "Deliberately OUT of scope" docstring (`provision_cognito.py:23-34`): the Custom Auth
  Lambdas are now permanently out of scope (backend-driven flow replaces them).

### 4. `service_webapp/src/core/config.py`
Add three optional fields (follow the existing optional-field pattern, `config.py:62-117`):
- `otp_login_ttl_seconds: int = 300`
- `notification_portal_open_in_dev: bool = False`
- `cognito_local_admin_password_seed: str = "sboai-local-{username}-pw"`

### 5. `service_webapp/src/main.py`
- Wire `app.state.login_otp_service = LoginOtpService(cache=app.state.cache_adapter, producer=...,
  ttl_seconds=settings.otp_login_ttl_seconds)` in `lifespan`. **Move the `kafka_producer` creation
  block above this wiring** so the producer is available (producer has no cache dependency).
- The existing `notification.events` consumer/broadcaster (`main.py:289-419`) needs **no change** —
  a `LOGIN_OTP` event flows through unchanged.

### 6. `service_webapp/src/routers/account.py` (`/login/initiate`, `/login/verify`, lines 156-224)
- Resolve `login_otp_service` from `app.state` and thread it into the provider calls.
- Drop `session` from `LoginVerifyRequest` (and the initiate response) — or keep as a tolerated
  no-op field to minimize frontend churn. **Recommend dropping it** (see frontend step).
- Trace id from `request.state.trace_id` threads into `issue(...)`.

### 7. `service_webapp/src/routers/simulator.py:486-513` (`notifications_ws`)
Insert, before the existing token check, a dev branch:
```python
if settings.notification_portal_open_in_dev:
    await notification_connection_manager.connect(ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        notification_connection_manager.disconnect(ws)
    return
# ...existing token + dev-group check...
```

### 8. Frontend
- `frontend/src/portals/auth/Login.tsx` + `frontend/src/lib/api.ts:120-147`: drop the `session`
  field (initiate returns nothing useful; verify sends `{identifier, otp}` only).
- `frontend/src/hooks/useNotificationsWebSocket.ts:48-52`: drop the early-return when
  `getToken()` is null — let the server decide (it accepts when the flag is on, closes 4001 when
  off; the existing reconnect loop tolerates that). No new env flag needed.

## Tests (unit only — integration skipped by default; `just test`)

- **New `tests/unit/test_login_otp_service.py`**: `issue()` mints 6-digit code, stores under
  `login_otp:{identifier}` with TTL, publishes a `notification.events` envelope matching the WS
  contract (`notification_type="LOGIN_OTP"`, code in `message_preview`); `verify()` accepts right
  code + deletes key (single-use), rejects wrong/absent via constant-time compare; producer-absent
  path does not raise.
- **Extend `tests/unit/test_auth.py`** (lines 28-39, 229-330): `_make_app` gains a `login_otp`
  param; assert initiate publishes the OTP event; keep correct/wrong-OTP and phone_number-in-token
  assertions. **This is the biggest churn** — the existing 6-8 login tests assume a `session` flow
  and must be rewritten to omit `session`.
- **New `tests/unit/test_notifications_ws_open_in_dev.py`**: WS connects without a token when the
  flag is on; closes 4001 when off (existing ASGI client pattern).

## Docs

- **README.md (lines 131-148):** replace the circular instructions with the real flow — Continue
  generates an OTP that appears on `/simulator/notifications` (open in dev via the flag) or via
  `podman exec redpanda rpk topic consume notification.events -n 5`; remove the "login as dev
  first" circular step.
- **`docs/bmad_output/implementation-artifacts/deferred-work.md:24-29`:** move the two items under a
  "RESOLVED" header pointing to `LoginOtpService`.
- **`docs/bmad_output/implementation-artifacts/1-8-login-otp-step-up-jwt-role-based-auth.md`:**
  append a "Real-flow implementation" addendum (backend-driven decision, bootstrap flag, `rpk`
  fallback) — documents closing the gap that left 1.8 "done" only against the fake provider.
- Also update the README Cognito section: the seeded-user table is fine; add a note that local
  login now works via real OTPs.

## Risks / out of scope

- **Ministack-only design.** `admin_set_user_password` + `admin_initiate_auth` need
  `cognito-idp:Admin*` perms on real AWS; prod subscribers wouldn't get a deterministic password.
  The prod path (real SNS OTP delivery) is a separate story — explicitly out of MVP.
- **`session` removal breaks** every login test in `test_auth.py:233-330` — plan for a focused
  rewrite.
- **E.164 normalization rules** (national 10-digit → `+91...`) must handle the seeded users'
  `phone_number` format (`+9199990NNNN`, `provision_cognito.py:289`) — confirm both directions.
- Refresh-token rotation / 401-retry (`deferred-work.md:5`) stays deferred — orthogonal.

## Verification

```bash
just deps                                                              # pool + demo users + Redpanda
uvx --with boto3 python scripts/provision_cognito.py                   # (re)seed admin passwords — idempotent
# set NOTIFICATION_PORTAL_OPEN_IN_DEV=true in service_webapp/.env
just backend && just frontend                                           # :8000 + :5173
# Open /simulator/notifications in one tab; /login in another.
# Enter "dev" -> LOGIN_OTP row appears with code -> enter code -> JWT stored -> redirect to /simulator.
# Confirm real Cognito RS256 JWT (issuer = MiniStack pool URL, not "fake.access.token").
podman exec valkey valkey-cli GET "login_otp:dev"                      # nil after verify (single-use)
just test                                                              # unit suite green
```

## Sequencing

1. Config (3 fields) → 2. `services/login_otp.py` + its tests → 3. `adapters/cognito.py` rewrite +
   `FakeCognitoProvider` + E.164 helper → 4. `routers/account.py` thread service, drop `session` →
   5. `provision_cognito.py` admin password → 6. `main.py` wiring (reorder producer) →
   7. `routers/simulator.py` dev WS branch → 8. frontend drop `session` + WS early-return →
   9. rewrite affected `test_auth.py` tests → 10. docs (README, deferred-work, Story 1.8 addendum,
   provisioning docstring).

## Direct answer to the original questions

- **URL to see all notifications (incl. SMS OTPs):** `http://localhost:5173/simulator/notifications`
  (Notification Portal, `/ws/notifications`). Requires `dev` role; with the new
  `NOTIFICATION_PORTAL_OPEN_IN_DEV=true` flag it is reachable for the first login too.
- **Where everyone logs in:** everyone uses `http://localhost:5173/login`. Staff test users
  (`dev`, `admin`, `marketing`, `ops`, `fraud`) log in by their **username**; subscribers log in
  by Registration ID (pre-activation) or MSISDN (post-activation). Role determines the redirect
  (`dev`→`/simulator`, `ops`/`admin`/`marketing`→`/ops`, `fraud`→`/fraud`, `subscriber`→`/subscriber`).
- **The OTP for any login** surfaces on the Notification Portal (or via `rpk` on the raw topic).
