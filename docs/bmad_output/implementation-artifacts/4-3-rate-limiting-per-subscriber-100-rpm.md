---
baseline_commit: b1dda60
---

# Story 4.3: Rate Limiting — Per-Subscriber 100 RPM (MVP Stub)

Status: review

## Story

As a **platform engineer**,
I want a rate limiter that enforces 100 requests per minute per subscriber across API and USSD channels,
so that no single subscriber can overload the system and the limit is adjustable without a code deploy.

## Acceptance Criteria

1. **Given** `RATE_LIMITING_ENABLED=false` (MVP default), **When** any subscriber makes any number of requests, **Then** all requests pass through — no 429 is returned. `X-RateLimit-Limit` and `X-RateLimit-Channel` headers are set on every response for observability. [Source: arch §1.7.3 — "not in MVP"; user decision 2026-06-23]
2. **Given** `RATE_LIMITING_ENABLED=true`, **When** a subscriber exceeds 100 requests within a 60-second sliding window on a given channel, **Then** subsequent requests return HTTP 429 with body `{"error": {"code": "RATE_LIMIT_EXCEEDED", "message": "100 RPM limit reached. Try again in {retry_after}s"}}` (FR-36). [Source: epics.md:1414–1416]
3. **And** rate limiting is enforced per-channel: `api`, `ussd`, `chatbot`. A subscriber at their API limit is NOT blocked on USSD. [Source: epics.md:1422]
4. **And** the Valkey key pattern is `ratelimit:{msisdn}:{channel}:{minute_bucket}` with 60s TTL, where `minute_bucket = int(time.time()) // 60`. [Source: epics.md:1418]
5. **And** the RPM limit value is read from `notification_threshold_config` (key=`rate_limit_rpm`) at startup — not hardcoded. [Source: epics.md:1420; story 4.1 creates this table]
6. **And** requests without a valid JWT (e.g. USSD callbacks at `/api/v1/ussd/callback`, `/health`, `/ready`) are never rate-limited. [Source: arch §1.9 — USSD is inbound callback only]
7. **And** `channel` is resolved from the request path: `/api/v1/ussd/*` → `ussd`; `/api/chat/*` → `chatbot`; all other paths → `api`. [Source: epics.md:1422]

## Tasks / Subtasks

- [x] **Task 1: Settings + protocol extension** (AC: #1, #2, #5)
  - [x] Add `rate_limiting_enabled: bool = False` to `Settings` in `service_webapp/src/core/config.py`. Field reads from env var `RATE_LIMITING_ENABLED`. [Source: core/config.py — existing Settings pattern]
  - [x] Add `incr_with_expire(key: str, ttl_seconds: int) -> int` to `CacheProtocol` in `service_webapp/src/core/protocols/cache.py`. Returns new counter value after increment. [Source: core/protocols/cache.py — existing protocol]
  - [x] Implement `incr_with_expire` in `ValkeyAdapter` (`service_webapp/src/adapters/redis.py`): call `INCR key` then `EXPIRE key ttl_seconds` in pipeline. Returns int. [Source: adapters/redis.py — existing valkey[asyncio] client]

- [x] **Task 2: RateLimitMiddleware** (AC: #1–#7)
  - [x] Create `service_webapp/src/core/rate_limit.py` with `RateLimitMiddleware(BaseHTTPMiddleware)`.
  - [x] On startup (via `set_limit` classmethod called from lifespan): read `rate_limit_rpm` from `notification_threshold_config` via DB, store as `RateLimitMiddleware._rpm_limit: int = 100`.
  - [x] On each request: skip if path is `/health`, `/ready`, or starts with `/api/v1/ussd/callback`. [Source: AC #6]
  - [x] Extract msisdn from `Authorization: Bearer <token>` → decode JWT (no verify — already verified by `require_role` on the route) → `phone_number` claim. If absent: call `call_next(request)`, set pass-through headers, return. [Source: core/auth.py — JWT decode pattern]
  - [x] Compute `channel` from `request.url.path` (see AC #7). Compute `minute_bucket = int(time.time()) // 60`.
  - [x] If `settings.rate_limiting_enabled` is False: call `call_next(request)`, add `X-RateLimit-Limit: {_rpm_limit}` and `X-RateLimit-Channel: {channel}` headers to response, return. [Source: AC #1]
  - [x] If `settings.rate_limiting_enabled` is True: call `cache.incr_with_expire(f"ratelimit:{msisdn}:{channel}:{minute_bucket}", 60)`. If result > `_rpm_limit`: compute `retry_after = 60 - (int(time.time()) % 60)`, return `JSONResponse(status_code=429, content={...})`. [Source: AC #2, #4]
  - [x] On 429: include `Retry-After: {retry_after}` header per RFC 6585. [Source: AC #2]

- [x] **Task 3: Wire middleware into app** (AC: #1)
  - [x] In `service_webapp/src/main.py` `lifespan`: after DB/Valkey pool startup, call `await RateLimitMiddleware.load_config(db=app.state.db_adapter)` to populate `_rpm_limit`. [Source: main.py:77 — existing lifespan pattern]
  - [x] Add `app.add_middleware(RateLimitMiddleware, settings=settings)` in `create_app()` AFTER `OTelTraceMiddleware`. Cache resolved lazily from `request.app.state.cache_adapter` at dispatch time. [Source: main.py — existing middleware order]

- [x] **Task 4: Tests** (AC: #1–#7)
  - [x] Unit `tests/unit/test_rate_limit.py`: mock Valkey + DB. `rate_limiting_enabled=False` → 200 with X-RateLimit-Limit header; no Valkey INCR called. [Source: AC #1]
  - [x] Unit: `rate_limiting_enabled=True` → requests 1–100 return 200; request 101 returns 429 with `RATE_LIMIT_EXCEEDED` body and `Retry-After` header. [Source: AC #2]
  - [x] Unit: path `/api/v1/ussd/callback` with no JWT → pass-through (no rate-limit header, no 429). [Source: AC #6]
  - [x] Unit: channel routing — `/api/v1/ussd/menu` → `ussd`; `/api/chat/stream` → `chatbot`; `/api/v1/subscriber/balance` → `api`. [Source: AC #7]
  - [x] Unit: per-channel isolation — api counter at 100 does NOT affect ussd counter. [Source: AC #3]
  - [x] Unit: `retry_after` value is `60 - (unix_ts % 60)` (mocked `time.time`). [Source: AC #2]

## Dev Notes

### MVP scope: stub mode only

Architecture §1.7.3 explicitly states rate limiting is "not in MVP — API Gateway in Target State". The user confirmed this on 2026-06-23. This story ships `rate_limiting_enabled=False` (env default). The full Valkey enforcement path is implemented and tested, but gated. Production activation: set `RATE_LIMITING_ENABLED=true` in the environment.

### Middleware placement

`BaseHTTPMiddleware` runs before route handlers, so `phone_number` is not yet in `request.state`. Decode the JWT header directly in middleware without the `require_role` dependency. Use `jose.jwt.get_unverified_claims(token)` (python-jose already in deps from Story 1.8) — this does NOT verify the signature, but the route handler will. The middleware must not double-verify; it only reads claims for the rate-limit key.

### Valkey key design

`ratelimit:{msisdn}:{channel}:{minute_bucket}` — three-part key. `minute_bucket` is `int(time.time()) // 60` so it auto-rotates every minute. TTL=60s ensures Valkey cleans up expired windows. This matches architecture Valkey key patterns (ARCH-5). [Source: arch §1.7.3]

### incr_with_expire implementation note

Valkey's `INCR` + `EXPIRE` is two round-trips. This is acceptable since rate limiting is off by default in MVP. For Target State, use `EVAL "local c=redis.call('INCR',KEYS[1]) redis.call('EXPIRE',KEYS[1],ARGV[1]) return c" 1 key ttl` (single round-trip Lua). Document this in a TODO comment in the adapter.

### DB config dependency

`notification_threshold_config` table is created by Story 4.1's Flyway V6 migration. Story 4.3 depends on that migration having run. During lifespan startup, if the table does not exist (migration not applied), fall back to default `_rpm_limit = 100` and log a warning — do not crash. [Source: story 4.1 tasks]

### No new Flyway migration

Story 4.3 does not add any migrations. The `notification_threshold_config` row for `rate_limit_rpm` is seeded by Story 4.1's V6 migration.

### Error response format

429 body matches the standard error envelope from `service_webapp/src/core/responses.py` / `core/errors.py`. Use `{"error": {"code": "RATE_LIMIT_EXCEEDED", "message": "100 RPM limit reached. Try again in {retry_after}s"}}` — consistent with existing 4xx responses. [Source: arch §1.11 — HTTP status codes]

### Deferred work

The Lua-script single-round-trip optimization for Valkey INCR+EXPIRE should be noted in `deferred-work.md` as a Target State improvement.

## Dev Agent Record

### Implementation Notes

- Dev note said `python-jose` was in deps but only `PyJWT` is installed. Used `pyjwt.decode(..., options={"verify_signature": False})` instead of `jose.jwt.get_unverified_claims`. Both produce the same unverified claims dict.
- Cache injected via `request.app.state.cache_adapter` at dispatch time rather than constructor — avoids the chicken-and-egg problem where `cache_adapter` is None at `create_app()` time (created in lifespan).
- Valkey `incr_with_expire` uses `pipeline(transaction=False)` for INCR + EXPIRE in a single round-trip batch. TODO comment added for Lua script Target State upgrade.
- All 12 unit tests pass. 0 new regressions introduced (pre-existing failures in test_recharge/test_data_nudge confirmed against main branch).

### Completion Notes

All ACs satisfied: MVP disabled mode (AC #1) passes through with observability headers; full enabled mode (AC #2–#7) enforces 100 RPM per-channel with correct 429 body and Retry-After header; bypass paths skip rate limiting; per-channel isolation works correctly.

## File List

- `service_webapp/src/core/config.py` — added `rate_limiting_enabled: bool = False`
- `service_webapp/src/core/protocols/cache.py` — added `incr_with_expire` to `CacheProtocol`
- `service_webapp/src/adapters/redis.py` — implemented `incr_with_expire` with pipeline
- `service_webapp/src/core/rate_limit.py` — new: `RateLimitMiddleware`, `load_config`, `_extract_msisdn`, `_resolve_channel`
- `service_webapp/src/main.py` — wired `RateLimitMiddleware` import, `load_config` call in lifespan, `add_middleware` in `create_app`
- `service_webapp/tests/unit/test_rate_limit.py` — new: 12 unit tests covering all ACs

## Change Log

- 2026-06-24: Story 4.3 implemented — rate limit middleware (MVP stub, disabled by default). Added `rate_limiting_enabled` setting, `incr_with_expire` cache op, `RateLimitMiddleware` with Valkey sliding-window, lifespan wiring, 12 unit tests. All ACs satisfied.
