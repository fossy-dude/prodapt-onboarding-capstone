---
baseline_commit: 89d48fe
---

# Story 6.4: Real-Time Anomaly Feed & Fraud Case Queue UI

Status: ready-for-dev

## Story

As a **fraud analyst**,
I want a live dashboard showing flagged CDR anomalies and a case queue for AI-escalated fraud cases,
so that I can monitor threats in real time and manage investigations efficiently.

## Acceptance Criteria

1. **Given** a fraud analyst logs in with role = `fraud` and navigates to `/fraud/dashboard`, **When** the page loads, **Then** the `AnomalyFeed.tsx` component connects to `ws://localhost:8000/ws/fraud/alerts` and displays a live-updating list: MSISDN[-4:], rule triggered, detected_at, confidence_score. (FR-53, ARCH-21) [Source: epics.md:1876]
2. **And** new alerts appear at the top of the feed without a page reload; feed auto-scrolls to latest. [Source: epics.md:1878]
3. **Given** confirmed_fraud or needs_review cases exist in `fraud_cases`, **When** the analyst views `/fraud/cases`, **Then** `GET /api/v1/fraud/cases` returns a paginated list: case_id, MSISDN[-4:], verdict, confidence_score, status, detected_at. (FR-54) [Source: epics.md:1884]
4. **And** the analyst can update a case status: OPEN → UNDER_REVIEW → RESOLVED with a free-text notes field. [Source: epics.md:1886]
5. **And** `PATCH /api/v1/fraud/cases/{case_id}` accepts: status, analyst_notes, resolved_by. [Source: epics.md:1888]

## Tasks / Subtasks

- [ ] **Task 1: Fraud db queries/commands (extend the 6.3 fraud layer)** (AC: #3, #5)
  - [ ] In `service_webapp/src/db/fraud/queries.py` (created in 6.3), add:
    - `list_fraud_cases(conn, *, limit: int, cursor: UUID | None, status_filter: str | None, type_filter: str | None) -> tuple[list[dict], UUID | None]` — keyset pagination on `id DESC` (mirror `db/billing/queries.py` cursor pattern: fetch `limit+1`, predicate `id < cursor`, derive `has_next` + next cursor). Filterable by `status` and by `fraud_type`/`rule_triggered` (the `?type=` query for 6.5). Columns projected: `id AS case_id, msisdn, verdict, risk_score AS confidence_score, status, created_at AS detected_at, fraud_type, triggered_by AS rule_triggered`.
    - `get_fraud_case(conn, case_id: UUID) -> dict | None`.
  - [ ] In `service_webapp/src/db/fraud/commands.py`, add:
    - `update_fraud_case(conn, case_id: UUID, *, status: str, analyst_notes: str | None, resolved_by: str | None) -> None` — `UPDATE fraud_cases SET status=%s, analyst_notes=%s, resolved_by=%s, resolved_at=CASE WHEN %s='RESOLVED' THEN NOW() ELSE resolved_at END WHERE id=%s`.
  - [ ] Column mappings (from 6.3): `confidence_score`↔`risk_score`, `rule_triggered`↔`triggered_by`, `detected_at`↔`created_at`, `case_id`↔`id`. Use real column names in SQL. [Source: V1__baseline_schema.sql:424-440; 6-3 dev notes]

- [ ] **Task 2: Fraud REST router** (AC: #3, #5)
  - [ ] Create `service_webapp/src/routers/fraud.py`.
  - [ ] Role gate: `jwt_payload: dict = require_role("fraud")` on every route (roles live in `cognito:groups`; `"fraud"` works directly, no registry change). [Source: core/auth.py require_role; architecture.md#1.8.1]
  - [ ] `GET /api/v1/fraud/cases` — query params `limit` (default 20, clamp `max(1, min(limit, 100))`), `cursor` (UUIDv7 optional), `status` (optional), `type` (optional). Response via `success_envelope({data: [...], meta: {next_cursor, trace_id, timestamp}})`. MSISDN masked to `[-4:]` in the response projection (PII hygiene ARCH-32/NFR-16).
  - [ ] `PATCH /api/v1/fraud/cases/{case_id}` — body `{status: Literal["OPEN","UNDER_REVIEW","RESOLVED"], analyst_notes: str | None, resolved_by: str | None}`. Validate status ∈ the allowed set + transition legality (OPEN→UNDER_REVIEW→RESOLVED; reject illegal jumps with 422/409). `resolved_by` defaults to the analyst's identity from the JWT (`cognito:groups`/`sub`) if not supplied. Response 200 with the updated case.
  - [ ] Wire router in `service_webapp/src/main.py` `create_app` (include the API router). Confirm `/api/v1` prefix is already the app mount.

- [ ] **Task 3: WebSocket anomaly feed `/ws/fraud/alerts`** (AC: #1, #2)
  - [ ] In `service_webapp/src/routers/fraud.py` (or a dedicated `ws` section), add a non-prefixed ws route mirroring `routers/simulator.py`:
    ```python
    @ws_router.websocket("/ws/fraud/alerts")
    async def fraud_alerts_ws(ws: WebSocket):
        token = ws.query_params.get("token")
        if not token:
            await ws.close(code=4001); return
        payload = ws.app.state.jwt_validator.decode(token)
        if "fraud" not in (payload.get("cognito:groups") or []):
            await ws.close(code=4003); return
        await fraud_connection_manager.connect(ws)
        try:
            while True:
                await ws.receive_text()
        except WebSocketDisconnect:
            fraud_connection_manager.disconnect(ws)
    ```
    JWT via `?token=` query param (WS cannot carry headers), close codes 4001 (missing/bad token) / 4003 (wrong role). [Source: routers/simulator.py; architecture digest §10]
  - [ ] New `fraud_connection_manager = ConnectionManager()` instance (one per stream — copy the existing `ConnectionManager` accept/register/broadcast/disconnect).
  - [ ] Lifespan consumer: add a background `AIOKafkaConsumer("fraud.alerts", group_id="fraud-dashboard-broadcaster", auto_offset_reset="latest", value_deserializer=lambda v: json.loads(v.decode()))` task in `main.py` that calls `fraud_connection_manager.broadcast(alert_payload)` per message (mirror the simulator-trace/notification-portal broadcasters). The alert payload (published by 6.3) already carries `msisdn[-4:], verdict, rule_triggered, confidence_score, detected_at`.

- [ ] **Task 4: Frontend types + API funcs** (AC: #1, #3)
  - [ ] Create `frontend/src/types/fraud.ts`:
    ```ts
    export type FraudVerdict = "confirmed_fraud" | "false_positive" | "needs_review";
    export type CaseStatus = "OPEN" | "UNDER_REVIEW" | "RESOLVED";
    export interface FraudAlert { case_id: string; msisdn_last4: string; rule_triggered: string; verdict: FraudVerdict; confidence_score: number; detected_at: string; }
    export interface FraudCase { case_id: string; msisdn_last4: string; verdict: FraudVerdict; confidence_score: number; status: CaseStatus; detected_at: string; rule_triggered?: string; analyst_notes?: string | null; }
    ```
  - [ ] Add fraud API funcs in `frontend/src/lib/api.ts` (shared axios instance, `Authorization: Bearer ${getToken()}` already injected):
    - `fetchFraudCases(params: {limit, cursor?, status?, type?}) -> Promise<{data: FraudCase[], next_cursor: string|null}>`
    - `patchFraudCase(case_id, {status, analyst_notes, resolved_by}) -> Promise<FraudCase>`

- [ ] **Task 5: `useFraudAlertsWebSocket` hook** (AC: #1, #2)
  - [ ] Create `frontend/src/hooks/useFraudAlertsWebSocket.ts` — copy `useNotificationsWebSocket.ts` verbatim pattern: `WS_BASE_URL = import.meta.env.VITE_WS_BASE_URL ?? "ws://localhost:8000"`, connect to `${WS_BASE_URL}/ws/fraud/alerts?token=${getToken()}`, `useRef<WebSocket>`, 3s auto-reconnect on `onclose`, return `{alerts: FraudAlert[], status, clearAlerts}`. [Source: frontend/src/hooks/useNotificationsWebSocket.ts]

- [ ] **Task 6: `AnomalyFeed.tsx` + `CaseQueue.tsx`** (AC: #1, #2, #3, #4)
  - [ ] Create `frontend/src/portals/fraud/AnomalyFeed.tsx`:
    - Uses `useFraudAlertsWebSocket()`.
    - Renders a list; newest alert prepended to top (`[newAlert, ...alerts]`); auto-scroll to top on new alert.
    - Row: MSISDN[-4:], rule_triggered, verdict badge, confidence_score, detected_at (relative time).
    - Story 6.5 adds the red "SIM SWAP" / amber "RECHARGE ANOMALY" badges — leave a clear extension point (a `badgeFor(rule_triggered, verdict)` helper).
  - [ ] Create `frontend/src/portals/fraud/CaseQueue.tsx`:
    - React Query (`@tanstack/react-query`): `FRAUD_CASES_QUERY_KEY = ["fraud","cases"]` + `useQuery` with the filter params; `useMutation` for PATCH that invalidates `FRAUD_CASES_QUERY_KEY`.
    - Keyset-paginated table: case_id, MSISDN[-4:], verdict, confidence_score, status, detected_at. "Load more" via `next_cursor`.
    - Row action: status dropdown (OPEN/UNDER_REVIEW/RESOLVED) + notes textarea → PATCH on save.
  - [ ] Charts (optional, if any summary viz): use Recharts wrappers from `frontend/src/components/charts/` (mirror `UsageRing.tsx`). CaseQueue is primarily a table.

- [ ] **Task 7: Route wiring — replace the `/fraud/*` placeholder** (AC: #1, #3)
  - [ ] `frontend/src/App.tsx` already has `<Route path="/fraud/*" element={<RoleGuard allowedRoles={["fraud"]}><PortalPlaceholder/></RoleGuard>}/>`. Replace `PortalPlaceholder` with a `FraudLayout` that nests `/fraud/dashboard` → AnomalyFeed and `/fraud/cases` → CaseQueue. [Source: frontend/src/App.tsx; architecture.md#1.12.1]
  - [ ] `PortalRole` in `frontend/src/lib/auth.ts` already includes `"fraud"` — no change. `RoleGuard` reads `cognito:groups` first entry.

- [ ] **Task 8: Tests** (AC: #1–#5)
  - [ ] `service_webapp/tests/api/test_fraud_cases.py` (mocked DB): GET paginated (limit clamp, cursor, has_next), GET with status/type filter, GET masks msisdn to [-4:], PATCH valid transition → 200, PATCH illegal transition → 422/409, PATCH missing role → 403, GET missing role → 403.
  - [ ] `service_webapp/tests/api/test_fraud_ws.py` (`@pytest.mark.slow`): `/ws/fraud/alerts` — no token → 4001; valid token + `fraud` group → accepted; valid token + wrong group → 4003; broadcast reaches the connected client.
  - [ ] `frontend/src/portals/fraud/__tests__/AnomalyFeed.test.tsx` + `CaseQueue.test.tsx` (vitest): new alert prepended to top; PATCH invalidates query; status dropdown restricts to legal transitions.
  - [ ] Integration (`@pytest.mark.slow`): real Postgres (V1+V11+V12) seeded with fraud_cases rows; GET returns correct projection; PATCH persists status/analyst_notes/resolved_by.

## Dev Notes

### Reuse the simulator WS + ConnectionManager — do NOT reinvent

`routers/simulator.py` already implements the exact pattern: JWT via `?token=`, decode against `app.state.jwt_validator`, role from `cognito:groups`, close codes 4001/4003, a `ConnectionManager` (accept/register/broadcast/disconnect), and a lifespan Kafka consumer driving `broadcast`. Copy it for `/ws/fraud/alerts` with role `"fraud"` and a NEW `fraud_connection_manager` instance (one manager per stream — do not share with simulator/notifications). [Source: routers/simulator.py; architecture digest §10; ARCH-21]

### Keyset pagination — copy the billing queries pattern

`db/billing/queries.py` has the canonical keyset pattern: cursor on UUIDv7 `id DESC`, predicate `id < cursor`, fetch `limit+1` to compute `has_next` + next cursor, `max(1, min(limit, 100))` clamp. Use it for `list_fraud_cases`. Do not use OFFSET (large tables, unstable). [Source: db/billing/queries.py; architecture.md CQRS]

### Column mappings — risk_score / triggered_by / created_at are the real columns

`fraud_cases` has NO `confidence_score`, `rule_triggered`, or `detected_at` column. The AC names map to existing columns:
- `confidence_score` ↔ `risk_score NUMERIC(5,4)`
- `rule_triggered` ↔ `triggered_by VARCHAR(50)`
- `detected_at` ↔ `created_at`
- `case_id` ↔ `id`
`verdict`, `msisdn`, `analyst_notes`, `resolved_by` are the V12 columns (added in 6.3). Project with aliases in SELECT so the API payload uses AC names while SQL uses real names. [Source: V1__baseline_schema.sql:424-440; 6-3 migration; code-review-2026-06-23 lesson #1]

### Role gating — cognito:groups, "fraud" works directly

`require_role("fraud")` decodes the Bearer token via Cognito JWKS RS256 and checks `cognito:groups` (NOT a `role` claim). The `"fraud"` group must exist in the token (provisioned in Cognito). Errors: `UnauthenticatedError`→401, `ForbiddenError`→403. `require_role` is built but each router wires its own dependency (deferred-work). [Source: core/auth.py; deferred-work auth notes; architecture.md#1.8.1]

### MSISDN masking — server-side, always

The API response projects `msisdn[-4:]` (e.g. `"…1234"`). Never send full MSISDN to the frontend (PII hygiene ARCH-32/NFR-16). The WebSocket alert payload published by 6.3 must also mask msisdn. [Source: architecture.md#1.2.3 ARCH-32; epics.md#1.2.2 NFR-16]

### API envelope — success/error shape

Use `success_envelope(data, meta={trace_id, timestamp})` and the shared error envelope (HTTP 403 forbidden, 401 unauthenticated, 422 validation). [Source: core/responses.py; ARCH-12]

### Frontend layout — portals/, not feature-sliced

The as-built layout is `frontend/src/portals/{subscriber,simulator,...}` (the CLAUDE.md feature-sliced layout is NOT on disk). Fraud components go in `frontend/src/portals/fraud/`. Hooks are flat in `frontend/src/hooks/` (e.g. `useFraudAlertsWebSocket.ts`). Shared UI in `components/ui/`, charts in `components/charts/`. All imports relative. [Source: codebase conventions; architecture.md#1.12.1; UX-DR8 naming]

### React Query conventions

`@tanstack/react-query` is the server-state layer (no Redux). Pattern: export a `FRAUD_CASES_QUERY_KEY` tuple + thin `useQuery`/`useMutation` wrapper; mutations invalidate the cases key. `queryClient` config: `retry:false`, `refetchOnWindowFocus:false`. [Source: frontend/src/lib/queryClient.ts; ARCH-22; architecture.md#1.9.3]

### 6.5 extension points

This story ships the feed + queue WITHOUT the colored badges and the `?type=SIM_SWAP` dedicated filter UX (that is 6.5), but must leave: (a) a `badgeFor(rule_triggered, verdict)` helper in AnomalyFeed (returns null in 6.4), and (b) the `type` query param already supported end-to-end (GET + filter state in CaseQueue). [Source: epics.md 6.5 AC; architecture.md#1.9.2]

### Project Structure Notes

- New router: `service_webapp/src/routers/fraud.py` (GET/PATCH cases + `/ws/fraud/alerts`)
- Extended db layer: `service_webapp/src/db/fraud/{queries.py,commands.py}` (list/get/update — layer created in 6.3)
- Modified: `service_webapp/src/main.py` (fraud router include + fraud.alerts broadcaster consumer + fraud_connection_manager)
- New frontend: `frontend/src/types/fraud.ts`, `frontend/src/portals/fraud/{AnomalyFeed.tsx,CaseQueue.tsx,FraudLayout.tsx}`, `frontend/src/hooks/useFraudAlertsWebSocket.ts`, fraud funcs in `frontend/src/lib/api.ts`
- Modified: `frontend/src/App.tsx` (replace `/fraud/*` placeholder)
- New tests: `tests/api/test_fraud_cases.py`, `tests/api/test_fraud_ws.py`, frontend vitest specs
- No new migration (depends on V12 from 6.3). No agent changes. No cdr-pipeline changes.

### References

- [Source: epics.md:1862-1888 — Story 6.4 acceptance criteria]
- [Source: epics.md#1.2.3 ARCH-21 — WebSocket real-time UI; ARCH-12 — API envelope; ARCH-32 — PII]
- [Source: epics.md#1.2.2 FR-53, FR-54 — anomaly feed, case queue]
- [Source: architecture.md#1.9.2 — fraud anomaly feed WS; §1.12.1 routers/fraud.py, portals/fraud/]
- [Source: V1__baseline_schema.sql:424-440 — fraud_cases columns; 6-3 V12 migration — verdict/msisdn/analyst_notes/resolved_by]
- [Source: service_webapp/src/routers/simulator.py — WS + ConnectionManager + lifespan broadcaster pattern]
- [Source: service_webapp/src/db/billing/queries.py — keyset pagination; core/auth.py require_role; core/responses.py envelope]
- [Source: frontend/src/hooks/useNotificationsWebSocket.ts — ws hook pattern; lib/api.ts — axios client; lib/queryClient.ts — React Query]
- [Source: deferred-work.md — require_role built but unwired; auth uses cognito:groups]

## Dev Agent Record

### Agent Model Used

### Debug Log References

### Completion Notes List

### File List

### Change Log
