---
baseline_commit: 3c5d585
---

# Story 5.9: Plan Recommendation Tool & Feedback Loop

Status: ready-for-dev

## Story

As a **subscriber**,
I want the chatbot to recommend the best plan for me based on my usage patterns and accept or dismiss the recommendation,
so that I make informed recharge decisions tailored to my actual behaviour.

## Acceptance Criteria

1. **Given** a subscriber asks for a plan recommendation, **When** the plan recommendation tool is invoked, **Then** it computes the subscriber's 30-day CDR usage profile (data MB, domestic voice seconds, international voice seconds via `roaming=TRUE`), ranks each dimension against the population via a Postgres materialized view, classifies the subscriber into a usage category (DATA_HEAVY / VOICE_HEAVY / VALUE / BALANCED), and uses that category as a Milvus metadata filter before running hybrid search on `plan_vectors`. [Source: epics.md:1718; FR-32]
2. **And** if no usage dimension exceeds the 70th-percentile threshold (ambiguous profile), the tool returns a clarification prompt and the agent asks the subscriber what matters most — more data, more calling minutes, or a lower cost — before proceeding. [Source: FR-32]
3. **And** top 2 plans (post ±20% price filter vs. last recharge) are returned with a natural-language rationale: "Based on your {X}GB data usage this month, the {Plan Name} gives you more data at ₹{Y}." [Source: epics.md:1720]
4. **And** the plans are displayed as Accept/Dismiss cards in the chat UI (via `<PlanRecommendationCard>` component, Story 5.6), each showing a one-line comparison against the subscriber's current active plan (e.g. "50% more data · ₹99 more"). If the subscriber has no active plan, the comparison line is omitted. [Source: epics.md:1722; FR-33; ux-brief-chatbot.md]
5. **Given** a subscriber clicks Accept, **When** the feedback is logged, **Then** `POST /api/v1/recommendations/feedback` records `subscriber_id`, `recommended_plan_id`, `action_taken = ACCEPTED`, `recommendation_type = 'PLAN_RECOMMENDATION'` into `segmentation_recommendation_feedback`. [Source: epics.md:1728; FR-33]
6. **And** if dismissed, `action_taken = DISMISSED` is logged instead. [Source: epics.md:1730]
7. **And** the `segmentation_recommendation_feedback` table (already in V1 baseline) is used — NO new migration for this table. The `mv_usage_population_stats` materialized view requires a new migration (V2 or next version). [Source: V1__baseline_schema.sql:490–502]

## Tasks / Subtasks

- [ ] **Task 1: Enrich plan_vectors with usage_category** (prerequisite for metadata filtering)
  - [ ] In `service_webapp/src/adapters/milvus.py`, add `{"field_name": "usage_category", "datatype": DataType.VARCHAR, "max_length": 16}` to the `plan_vectors` extra fields list.
  - [ ] In `scripts/seed_milvus.py`, add helper:
    ```python
    def _usage_category(data_mb, voice_min, price_paise) -> str:
        data = data_mb or 0
        is_unlimited_voice = voice_min is None
        voice = voice_min if voice_min is not None else 99999
        if data > 20480:
            return "DATA_HEAVY"
        elif is_unlimited_voice or voice > 1000:
            return "VOICE_HEAVY"
        elif price_paise and price_paise < 10000:
            return "VALUE"
        return "BALANCED"
    ```
  - [ ] Extend the `seed_plan_vectors` SQL to also fetch `data_limit_mb, voice_minutes`:
    ```sql
    SELECT id, plan_name, plan_code, price_paise, validity_days, data_limit_mb, voice_minutes
    FROM plans_plans WHERE is_active = TRUE
    ```
  - [ ] Store `usage_category` in every Milvus row. Re-seed required after schema change.

- [ ] **Task 2: Population stats materialized view** (new migration)
  - [ ] Add migration file (next version after V1, e.g. `V2__usage_population_stats.sql`; verify highest existing version first).
  - [ ] SQL:
    ```sql
    CREATE MATERIALIZED VIEW mv_usage_population_stats AS
    SELECT
      percentile_cont(0.25) WITHIN GROUP (ORDER BY data_mb)  AS data_p25,
      percentile_cont(0.50) WITHIN GROUP (ORDER BY data_mb)  AS data_p50,
      percentile_cont(0.75) WITHIN GROUP (ORDER BY data_mb)  AS data_p75,
      percentile_cont(0.90) WITHIN GROUP (ORDER BY data_mb)  AS data_p90,
      percentile_cont(0.25) WITHIN GROUP (ORDER BY voice_sec) AS voice_p25,
      percentile_cont(0.50) WITHIN GROUP (ORDER BY voice_sec) AS voice_p50,
      percentile_cont(0.75) WITHIN GROUP (ORDER BY voice_sec) AS voice_p75,
      percentile_cont(0.90) WITHIN GROUP (ORDER BY voice_sec) AS voice_p90,
      percentile_cont(0.25) WITHIN GROUP (ORDER BY intl_sec)  AS intl_p25,
      percentile_cont(0.50) WITHIN GROUP (ORDER BY intl_sec)  AS intl_p50,
      percentile_cont(0.75) WITHIN GROUP (ORDER BY intl_sec)  AS intl_p75,
      percentile_cont(0.90) WITHIN GROUP (ORDER BY intl_sec)  AS intl_p90,
      COUNT(*) AS subscriber_count
    FROM (
      SELECT
        subscriber_id,
        COALESCE(SUM(CASE WHEN cdr_type='data' THEN volume_mb ELSE 0 END), 0)                         AS data_mb,
        COALESCE(SUM(CASE WHEN cdr_type='voice' AND NOT roaming THEN duration_seconds ELSE 0 END), 0) AS voice_sec,
        COALESCE(SUM(CASE WHEN cdr_type='voice' AND roaming     THEN duration_seconds ELSE 0 END), 0) AS intl_sec
      FROM billing_cdr_events
      WHERE start_time >= NOW() - INTERVAL '30 days'
      GROUP BY subscriber_id
    ) per_sub;
    ```
  - [ ] Add `REFRESH MATERIALIZED VIEW CONCURRENTLY mv_usage_population_stats;` to a nightly job or seed script.

- [ ] **Task 3: DB query functions** (AC: #1)
  - [ ] Add to `service_webapp/src/db/billing/queries.py`:
    - `get_subscriber_usage_profile(db, subscriber_id: str, days: int = 30) -> dict`
      ```sql
      SELECT
        COALESCE(SUM(CASE WHEN cdr_type='data' THEN volume_mb ELSE 0 END), 0)                         AS total_data_mb,
        COALESCE(SUM(CASE WHEN cdr_type='voice' AND NOT roaming THEN duration_seconds ELSE 0 END), 0) AS total_voice_seconds,
        COALESCE(SUM(CASE WHEN cdr_type='voice' AND roaming     THEN duration_seconds ELSE 0 END), 0) AS total_intl_seconds,
        COALESCE(SUM(CASE WHEN cdr_type='sms'   THEN 1 ELSE 0 END), 0)                               AS total_sms_count,
        COALESCE(SUM(charge_paise), 0)                                                                AS total_spend_paise
      FROM billing_cdr_events
      WHERE subscriber_id = %(subscriber_id)s
        AND start_time >= NOW() - INTERVAL %(days)s * INTERVAL '1 day'
      ```
      Returns: `{"total_data_mb": float, "total_voice_seconds": int, "total_intl_seconds": int, "total_sms_count": int, "total_spend_paise": int}`
    - `get_last_recharge_amount(db, subscriber_id: str) -> int | None`
      ```sql
      SELECT amount_paise FROM recharge_orders
      WHERE subscriber_id = %(subscriber_id)s AND status = 'COMPLETED'
      ORDER BY created_at DESC LIMIT 1
      ```
      Returns `amount_paise` or `None`. If `None`, skip price filter.
    - `get_current_plan_details(db, subscriber_id: str) -> dict | None`
      ```sql
      SELECT p.plan_name, p.data_limit_mb, p.voice_minutes, p.price_paise
      FROM recharge_orders r
      JOIN plans_plans p ON r.plan_id = p.id
      WHERE r.subscriber_id = %(subscriber_id)s AND r.status = 'COMPLETED'
      ORDER BY r.created_at DESC LIMIT 1
      ```
      Returns `{"plan_name": str, "data_limit_mb": int | None, "voice_minutes": int | None, "price_paise": int}` or `None`.
    - `get_population_usage_stats(db) -> dict`
      ```sql
      SELECT * FROM mv_usage_population_stats
      ```
      Returns single-row dict with all p25/p50/p75/p90 fields. Returns empty dict if view has no rows (empty CDR table).

- [ ] **Task 4: Extend HybridRetriever** (AC: #1)
  - [ ] In the retriever class created in Story 5.3, add:
    ```python
    async def search_plans(
        self, query_text: str, top_k: int = 10, filter_expr: str | None = None
    ) -> list[RagChunk]:
    ```
    - Embeds `query_text` via `self._embed(query_text)`
    - Calls `self._client.search(collection_name="plan_vectors", data=[embedding], limit=top_k, filter=filter_expr, output_fields=["plan_id", "text", "price", "validity", "usage_category", "data_limit_mb", "voice_minutes"])` for dense search
    - Note: `data_limit_mb` and `voice_minutes` must be added to `plan_vectors` output fields in `service_webapp/src/adapters/milvus.py` and stored during seeding (Task 1 SQL already fetches them)
    - Returns `list[RagChunk]` with `collection="plan_vectors"` and `metadata={"price": ..., "plan_id": ..., "usage_category": ...}`
    - If `filter_expr` is `None`, runs unfiltered (fallback for VALUE preference since VALUE is a cost signal handled by price filter, not metadata filter)

- [ ] **Task 5: `recommend_plan` tool** (AC: #1, #2, #3)
  - [ ] In `service_webapp/src/agents/support/graph.py`, add:
    ```python
    @tool
    async def recommend_plan(subscriber_id: str, preference: str | None = None) -> dict:
        """Recommend plans. preference: 'data' | 'voice' | 'value' | None."""
    ```
  - [ ] Steps:
    1. `profile = await get_subscriber_usage_profile(db, subscriber_id)`
    2. If `preference` given, map to category:
       ```python
       _PREF_MAP = {"data": "DATA_HEAVY", "voice": "VOICE_HEAVY", "value": "VALUE", "balanced": "BALANCED"}
       category = _PREF_MAP.get(preference, "BALANCED")
       ```
    3. Else: `pop_stats = await get_population_usage_stats(db)` and compute percentile ranks using `_percentile_rank(value, p25, p50, p75, p90)` (pure Python interpolation — see dev notes). Classify:
       ```python
       DOMINANT = 70.0
       data_pct  = _percentile_rank(profile["total_data_mb"],   pop_stats["data_p25"],  ..., pop_stats["data_p90"])
       voice_pct = _percentile_rank(profile["total_voice_seconds"], pop_stats["voice_p25"], ..., pop_stats["voice_p90"])
       intl_pct  = _percentile_rank(profile["total_intl_seconds"],  pop_stats["intl_p25"],  ..., pop_stats["intl_p90"])
       scores = {"DATA_HEAVY": data_pct, "VOICE_HEAVY": max(voice_pct, intl_pct)}
       dominant = {cat: pct for cat, pct in scores.items() if pct >= DOMINANT}
       if not dominant:
           return {"needs_clarification": True, "question": "What matters most to you — more data, more calling minutes, or a lower cost?"}
       category = max(dominant, key=dominant.get)
       ```
    4. Build query text: `f"data {profile['total_data_mb']:.0f}MB voice {profile['total_voice_seconds']//60}min intl {profile['total_intl_seconds']//60}min"`
    5. `filter_expr = f"usage_category == '{category}'"` (omit for VALUE — use unfiltered search)
    6. `chunks = await retriever.search_plans(query_text, top_k=10, filter_expr=filter_expr)`
    7. Apply ±20% price filter: `last = await get_last_recharge_amount(db, subscriber_id)` → discard chunks outside `[last * 0.8, last * 1.2]` if `last` is not None
    8. Fetch current plan: `current_plan = await get_current_plan_details(db, subscriber_id)`
    9. Build comparison string via `_build_plan_comparison(current_plan, chunk_metadata)` (see dev notes).
    10. Build rationale and return top 2:
       ```python
       return {"plans": [
           {
               "plan_id": c.metadata["plan_id"],
               "name": c.text.split()[0],
               "price_paise": c.metadata["price"],
               "price_inr": f"₹{c.metadata['price'] // 100}",
               "rationale": f"Based on your {profile['total_data_mb']/1024:.1f}GB data usage this month, {c.text} gives you more data at ₹{c.metadata['price'] // 100}.",
               "recharge_url": f"/subscriber/recharge?plan={c.metadata['plan_id']}",
               "comparison": _build_plan_comparison(current_plan, c.metadata),
           }
           for c in chunks[:2]
       ]}
       ```

- [ ] **Task 6: Feedback endpoint** (AC: #5, #6, #7)
  - [ ] In `service_webapp/src/routers/support.py` (created in Story 5.8), add:
    ```python
    class FeedbackRequest(BaseModel):
        subscriber_id: UUID
        plan_id: UUID
        action: Literal["ACCEPTED", "DISMISSED"]

    @router.post("/api/v1/recommendations/feedback", status_code=201)
    async def post_recommendation_feedback(body: FeedbackRequest, request: Request, jwt_payload: dict = require_role("subscriber")):
    ```
    No `session_id` field — not in the actual schema.
  - [ ] Add to `service_webapp/src/db/support/commands.py`:
    ```python
    async def log_recommendation_feedback(
        conn: AsyncConnection,
        subscriber_id: UUID,
        plan_id: UUID,
        action: str,
    ) -> None:
        await conn.execute(
            """INSERT INTO segmentation_recommendation_feedback
               (subscriber_id, recommended_plan_id, action_taken, recommendation_type)
               VALUES (%(subscriber_id)s, %(plan_id)s, %(action)s, 'PLAN_RECOMMENDATION')""",
            {"subscriber_id": subscriber_id, "plan_id": plan_id, "action": action},
        )
    ```
    Correct column names from V1 schema: `recommended_plan_id`, `action_taken`, `recommendation_type` (NOT NULL).

- [ ] **Task 7: Frontend Accept/Dismiss handling** (AC: #4, #5, #6)
  - [ ] Update `frontend/src/portals/subscriber/components/PlanRecommendationCard.tsx` to accept `onAccept: () => void`, `onDismiss: () => void`, and `comparison?: string` props.
  - [ ] Render `comparison` as a muted one-line badge below the plan name when present (e.g. "50% more data · ₹99 more"). Omit the element entirely when `comparison` is `null` or `undefined`.
  - [ ] On Accept: call `POST /api/v1/recommendations/feedback` with `action="ACCEPTED"`; then navigate to `recharge_url`.
  - [ ] On Dismiss: call `POST /api/v1/recommendations/feedback` with `action="DISMISSED"`; hide card.
  - [ ] Register `recommend_plan` CopilotKit action renderer. When result contains `needs_clarification: true`, render the question as a prompt card instead of plan cards:
    ```tsx
    useCopilotAction({
      name: "recommend_plan",
      render: ({ result }) => {
        if (result?.needs_clarification) {
          return <p>{result.question}</p>;
        }
        return (
          <div>
            {result?.plans?.map(plan => (
              <PlanRecommendationCard
                key={plan.plan_id}
                {...plan}
                onAccept={() => logFeedback(plan.plan_id, "ACCEPTED")}
                onDismiss={() => logFeedback(plan.plan_id, "DISMISSED")}
              />
            ))}
          </div>
        );
      }
    });
    ```

- [ ] **Task 8: Tests** (AC: #1–#7)
  - [ ] `service_webapp/tests/unit/test_usage_category.py`: test `_usage_category()` — >20GB → DATA_HEAVY; NULL voice_minutes → VOICE_HEAVY; <₹100 → VALUE; else BALANCED.
  - [ ] `service_webapp/tests/unit/test_percentile_classification.py`: test `_percentile_rank()` and `_classify_category()` — dominant data → DATA_HEAVY; dominant intl → VOICE_HEAVY; all below 70 → AMBIGUOUS; tie → highest wins.
  - [ ] `service_webapp/tests/unit/test_recommend_plan_tool.py`: mock DB + retriever. Verify: filter_expr passed as `"usage_category == 'DATA_HEAVY'"` for data-heavy subscriber; preference="voice" bypasses percentile calc; AMBIGUOUS returns `{"needs_clarification": True, ...}`; ±20% price filter excludes out-of-range plans; max 2 plans returned; `comparison` field present when current plan exists; `comparison` is `None` when subscriber has no prior recharge.
  - [ ] `service_webapp/tests/unit/test_build_plan_comparison.py`: test `_build_plan_comparison()` — 50% more data correctly computed; price increase/decrease sign; unlimited voice (NULL) vs finite; no current plan → returns `None`; identical plans → returns `None` (no meaningful diff).
  - [ ] `service_webapp/tests/unit/test_feedback_endpoint.py`: mock DB. POST with ACCEPTED → 201; DISMISSED → 201; invalid action → 422. Verify INSERT uses `recommended_plan_id`, `action_taken`, `recommendation_type`.
  - [ ] Integration (`@pytest.mark.slow`): real Postgres (V1 + V2 migration) + Milvus Lite. Verify `mv_usage_population_stats` refresh works; `segmentation_recommendation_feedback` INSERT succeeds with UUIDv7 PK auto-generated by DB.

## Dev Notes

### Percentile rank function (pure Python)

```python
def _percentile_rank(value: float, p25: float, p50: float, p75: float, p90: float) -> float:
    if p25 == 0 and p50 == 0:
        return 0.0
    if value <= p25:
        return 25.0 * (value / p25) if p25 > 0 else 0.0
    if value <= p50:
        return 25.0 + 25.0 * ((value - p25) / (p50 - p25)) if p50 > p25 else 25.0
    if value <= p75:
        return 50.0 + 25.0 * ((value - p50) / (p75 - p50)) if p75 > p50 else 50.0
    if value <= p90:
        return 75.0 + 15.0 * ((value - p75) / (p90 - p75)) if p90 > p75 else 75.0
    return 91.0
```

### AMBIGUOUS path — no interrupt() required

The tool returns `{"needs_clarification": True, "question": "..."}`. The LLM agent reads the `question` field and surfaces it to the user in natural language. On the next conversational turn the agent calls `recommend_plan(subscriber_id=..., preference="data"|"voice"|"value")`. Valkey-backed context memory (Story 5.4 pattern) carries session state across turns. No LangGraph checkpoint or `interrupt()` needed.

### usage_category thresholds

Thresholds (>20 GB → DATA_HEAVY, >1000 min or unlimited → VOICE_HEAVY, <₹100 → VALUE) reflect typical Indian prepaid plan ranges. May need tuning against the actual synthetic data distribution after seeding. The `_usage_category()` function in `seed_milvus.py` is the single source of truth — update it there and re-seed.

### segmentation_recommendation_feedback — correct column names

V1__baseline_schema.sql:490–502 actual columns:
- `recommended_plan_id` (UUID FK to plans_plans) — NOT `plan_id`
- `action_taken` (VARCHAR(20)) — NOT `action`
- `recommendation_type` (VARCHAR(50) NOT NULL) — hardcode `'PLAN_RECOMMENDATION'`
- `feedback_at` (TIMESTAMPTZ DEFAULT NOW())
- NO `session_id` column

### International call tracking

`billing_cdr_events` has `roaming` (BOOL NOT NULL DEFAULT FALSE). International voice = `cdr_type='voice' AND roaming=TRUE`. No separate CDR type for international.

### Milvus metadata filter syntax

Milvus filter expression for string equality: `"usage_category == 'DATA_HEAVY'"`. Pass as the `filter` kwarg to `client.search()`. Empty string or `None` disables filtering.

### Plan comparison string — `_build_plan_comparison`

```python
def _build_plan_comparison(current: dict | None, rec_metadata: dict) -> str | None:
    if not current:
        return None

    parts = []

    cur_data = current.get("data_limit_mb") or 0
    rec_data = rec_metadata.get("data_limit_mb") or 0
    if cur_data > 0 and rec_data > 0:
        diff_pct = (rec_data - cur_data) / cur_data * 100
        if abs(diff_pct) >= 10:
            label = "more" if diff_pct > 0 else "less"
            parts.append(f"{abs(diff_pct):.0f}% {label} data")
    elif rec_data > 0 and cur_data == 0:
        parts.append(f"{rec_data / 1024:.1f}GB data")

    cur_voice = current.get("voice_minutes")
    rec_voice = rec_metadata.get("voice_minutes")
    if cur_voice is not None and rec_voice is not None:
        diff = rec_voice - cur_voice
        if abs(diff) >= 50:
            label = "more" if diff > 0 else "fewer"
            parts.append(f"{abs(diff)} {label} min")
    elif rec_voice is None and cur_voice is not None:
        parts.append("unlimited calls")

    price_diff_paise = rec_metadata.get("price", 0) - current.get("price_paise", 0)
    if price_diff_paise != 0:
        label = "more" if price_diff_paise > 0 else "less"
        parts.append(f"₹{abs(price_diff_paise) // 100} {label}")

    return " · ".join(parts) if parts else None
```

Rules:
- Data diff only shown when ≥10% change — avoids noise for trivially similar plans.
- Voice diff only shown when ≥50 min change.
- NULL `voice_minutes` in `plans_plans` means unlimited — if recommended is unlimited and current is finite, show "unlimited calls".
- `rec_metadata` comes from the Milvus `output_fields`; it needs `data_limit_mb` and `voice_minutes` — add these to the `output_fields` list in `search_plans()`.
- Returns `None` when there are no meaningful differences — frontend omits the badge.

### VALUE category — filter vs. price-sort

VALUE preference is a cost signal, not a data/voice pattern. Do NOT filter by `usage_category == 'VALUE'` in Milvus — it would exclude perfectly good data or voice plans that happen to be cheap. Instead, for VALUE preference: run unfiltered search, then sort results ascending by `price` before applying the ±20% range (or skip the ±20% filter and just return the two cheapest results).

### recharge_orders — canonical table name

Canonical = `recharge_orders` per architecture §1.7.1. [Source: V1__baseline_schema.sql; architecture.md §1.7.1]

### uuid7 import

DB generates PK via `uuid_generate_v7()` automatically — Python does not need to generate it. [Source: memory: uuid7-import-and-pydantic-typecheck-gotchas]

### Project Structure Notes

- Modified: `service_webapp/src/adapters/milvus.py` (add usage_category, data_limit_mb, voice_minutes fields to plan_vectors schema)
- Modified: `scripts/seed_milvus.py` (add _usage_category, extend SQL to include data_limit_mb + voice_minutes, store all new fields)
- New migration: `service_webapp/db/migrations/V2__usage_population_stats.sql` (verify version)
- Modified: `service_webapp/src/db/billing/queries.py` (add get_subscriber_usage_profile with intl, get_last_recharge_amount, get_population_usage_stats)
- Modified: Story 5.3 retriever file (add search_plans with filter_expr param)
- Modified: `service_webapp/src/agents/support/graph.py` (add recommend_plan tool)
- Modified: `service_webapp/src/routers/support.py` (add POST /recommendations/feedback)
- Modified: `service_webapp/src/db/support/commands.py` (add log_recommendation_feedback)
- Modified: `frontend/src/portals/subscriber/components/PlanRecommendationCard.tsx` (add callbacks)

### References

- [Source: epics.md §1.8.9 — Story 5.9 acceptance criteria]
- [Source: architecture.md §1.6.1 — Plan Recommendation (hybrid search + usage signals)]
- [Source: architecture.md:FR-32 — Plan recommendation tool]
- [Source: architecture.md:FR-33 — Recommendation feedback loop]
- [Source: V1__baseline_schema.sql:490–502 — segmentation_recommendation_feedback exact columns]
- [Source: 2-7-milvus-lite-initialisation-vector-seeding.md — plan_vectors collection fields]
- [Source: scripts/seed_milvus.py — _plan_type_from_code pattern, seed_plan_vectors SQL]
- [Source: service_webapp/src/adapters/milvus.py — plan_vectors schema definition]
- [Source: memory: uuid7-import-and-pydantic-typecheck-gotchas — uuid_extensions import]
- [Source: ux-brief-chatbot.md — Accept/Dismiss card UI pattern]

## Dev Agent Record

### Agent Model Used

claude-sonnet-4-6

### Debug Log References

### Completion Notes List

### File List
