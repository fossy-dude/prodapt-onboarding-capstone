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

1. **Given** a subscriber asks for a plan recommendation or the agent determines one is useful, **When** the plan recommendation tool is invoked, **Then** it performs hybrid search on `plan_vectors` using the subscriber's 30-day CDR usage profile as the query embedding, filtered by price range tolerance ±20% of last recharge. [Source: epics.md:1718; FR-32]
2. **And** top 2 plans are returned with a natural-language rationale: "Based on your {X}GB data usage this month, the {Plan Name} gives you more data at ₹{Y}." [Source: epics.md:1720]
3. **And** the plans are displayed as Accept/Dismiss cards in the chat UI (via `<PlanRecommendationCard>` component, Story 5.6). [Source: epics.md:1722; FR-33; ux-brief-chatbot.md]
4. **Given** a subscriber clicks Accept, **When** the feedback is logged, **Then** `POST /api/v1/recommendations/feedback` records: `subscriber_id`, `plan_id`, `action = ACCEPTED`, `session_id`, `timestamp` into `segmentation_recommendation_feedback`. [Source: epics.md:1728; FR-33]
5. **And** if dismissed, `action = DISMISSED` is logged instead. [Source: epics.md:1730]
6. **And** the `segmentation_recommendation_feedback` table (already in V1 baseline) is used — NO new migration required. [Source: V1__baseline_schema.sql:490–502]

## Tasks / Subtasks

- [ ] **Task 1: Usage profile query** (AC: #1)
  - [ ] Add `get_subscriber_usage_profile(db, subscriber_id: str, days: int = 30) -> dict` to `service_webapp/src/db/billing/queries.py`.
  - [ ] SQL: aggregate from `billing_cdr_events` for last 30 days:
    ```sql
    SELECT
      COALESCE(SUM(CASE WHEN cdr_type='data' THEN volume_mb ELSE 0 END), 0) AS total_data_mb,
      COALESCE(SUM(CASE WHEN cdr_type='voice' THEN duration_seconds ELSE 0 END), 0) AS total_voice_seconds,
      COALESCE(SUM(CASE WHEN cdr_type='sms' THEN 1 ELSE 0 END), 0) AS total_sms_count,
      COALESCE(SUM(charge_paise), 0) AS total_spend_paise
    FROM billing_cdr_events
    WHERE subscriber_id = %(subscriber_id)s
      AND start_time >= NOW() - INTERVAL '30 days'
    ```
  - [ ] Returns: `{"total_data_mb": float, "total_voice_seconds": int, "total_sms_count": int, "total_spend_paise": int}`.

- [ ] **Task 2: Last recharge amount query** (AC: #1)
  - [ ] Add `get_last_recharge_amount(db, subscriber_id: str) -> int | None` to `service_webapp/src/db/billing/queries.py`.
  - [ ] SQL: `SELECT amount_paise FROM recharge_orders WHERE subscriber_id = %s AND status = 'COMPLETED' ORDER BY created_at DESC LIMIT 1`.
  - [ ] Returns: `amount_paise` or `None` if no prior recharge. If `None`, skip price filter (no tolerance constraint). [Source: V1__baseline_schema.sql recharge_orders]

- [ ] **Task 3: `recommend_plan` tool** (AC: #1, #2)
  - [ ] In `service_webapp/src/agents/support/graph.py`, add `@tool` function `recommend_plan(subscriber_id: str) -> list[dict]`.
  - [ ] Steps:
    1. Call `get_subscriber_usage_profile(db, subscriber_id)` → usage profile dict.
    2. Build query text: `f"data {profile['total_data_mb']:.0f}MB voice {profile['total_voice_seconds']//60}min SMS {profile['total_sms_count']}"`. Embed via `settings.embedding_model`.
    3. Call `rag_search(query=query_text, top_k=5)` on `plan_vectors` collection (Story 5.3 retriever — pass `collection="plan_vectors"` or use a separate retriever method).
    4. Call `get_last_recharge_amount(db, subscriber_id)` → apply ±20% price filter: discard plans outside `[last_amount * 0.8, last_amount * 1.2]` range. If no prior recharge → no filter.
    5. Return top 2 plans with rationale string.
  - [ ] Rationale format: `f"Based on your {profile['total_data_mb']/1024:.1f}GB data usage this month, the {plan_name} gives you more data at ₹{price_inr}."` [Source: epics.md:1720]
  - [ ] Return: `[{"plan_id": str, "name": str, "price_paise": int, "price_inr": str, "rationale": str, "recharge_url": f"/subscriber/recharge?plan={plan_id}"}]`

- [ ] **Task 4: Feedback endpoint** (AC: #4, #5)
  - [ ] In `service_webapp/src/routers/support.py` (created in Story 5.8), add:
    - `POST /api/v1/recommendations/feedback`: auth required (role=subscriber). Body: `FeedbackRequest(subscriber_id: UUID, plan_id: UUID, action: Literal["ACCEPTED", "DISMISSED"], session_id: str)`. INSERT into `segmentation_recommendation_feedback`. Returns 201. [Source: epics.md:1728; FR-33]
  - [ ] Add to `service_webapp/src/db/support/commands.py`:
    - `log_recommendation_feedback(db, subscriber_id, plan_id, action, session_id) -> None`. INSERT into `segmentation_recommendation_feedback(subscriber_id, plan_id, action, session_id, created_at)`.
  - [ ] Check V1 migration for `segmentation_recommendation_feedback` exact column names (V1__baseline_schema.sql:490–502). [Source: V1__baseline_schema.sql:490–502]

- [ ] **Task 5: Frontend Accept/Dismiss handling** (AC: #3, #4, #5)
  - [ ] Update `frontend/src/portals/subscriber/components/PlanRecommendationCard.tsx` (Story 5.6) to accept `onAccept` and `onDismiss` callbacks.
  - [ ] On Accept: call `POST /api/v1/recommendations/feedback` with action=ACCEPTED; then navigate to `recharge_url`.
  - [ ] On Dismiss: call `POST /api/v1/recommendations/feedback` with action=DISMISSED; hide card.
  - [ ] Register `recommend_plan` action renderer:
    ```tsx
    useCopilotAction({
      name: "recommend_plan",
      render: ({ result }) => (
        <div>
          {result.map(plan => (
            <PlanRecommendationCard
              key={plan.plan_id}
              {...plan}
              onAccept={() => logFeedback(plan.plan_id, "ACCEPTED")}
              onDismiss={() => logFeedback(plan.plan_id, "DISMISSED")}
            />
          ))}
        </div>
      )
    });
    ```

- [ ] **Task 6: Tests** (AC: #1–#6)
  - [ ] `service_webapp/tests/unit/test_usage_profile.py`: mock DB. Returns aggregated counts for 3 CDR types; zero CDRs → all zeros.
  - [ ] `service_webapp/tests/unit/test_recommend_plan_tool.py`: mock DB + Milvus retriever. Verify price filter applied (plan outside ±20% excluded); rationale string contains data usage; returns max 2 plans.
  - [ ] `service_webapp/tests/unit/test_feedback_endpoint.py`: mock DB. POST feedback with ACCEPTED → 201; DISMISSED → 201; invalid action → 422.
  - [ ] Integration (`@pytest.mark.slow`): real Postgres (V1) + Milvus Lite. Verify `segmentation_recommendation_feedback` INSERT works with UUIDv7 PK.

## Dev Notes

### segmentation_recommendation_feedback in V1 — NO new migration

V1__baseline_schema.sql:490–502 creates `segmentation_recommendation_feedback`. The epics AC does NOT mention a migration for this story (unlike Story 5.8 which incorrectly mentioned one for support_tickets). Story 5.9 needs NO migration. [Source: V1__baseline_schema.sql:490–502]

### plan_vectors Milvus collection

`plan_vectors` was seeded in Story 2.7. The collection stores plan attribute embeddings (text-embedding-3-small, 1536 dims). The retriever from Story 5.3 supports searching by collection name — use `collection="plan_vectors"` in the search call, or add a `search_plans(query_embedding, top_k) -> list[RagChunk]` method to `HybridRetriever`. Verify field names in the plan_vectors collection from Story 2.7. [Source: 2-7-milvus-lite-initialisation-vector-seeding.md; architecture.md §1.6.1 Plan Recommendation]

### Usage profile as embedding query text

The plan recommendation uses a text description of the subscriber's usage as the embedding query — NOT the raw usage vector directly. This text-to-embedding approach is intentional: it leverages the same `text-embedding-3-small` model used for plan descriptions, so similar usage descriptions match similar plan descriptions in embedding space. [Source: architecture.md §1.6.1 Plan Recommendation]

### Price tolerance filter

The ±20% filter is applied AFTER vector search (post-retrieval filter). Fetch top_k=10 from Milvus, then Python-side filter by price, then return top 2. This avoids the complexity of Milvus metadata filtering for MVP. [Source: epics.md:1718]

### recharge_orders — canonical table name

Canonical = `recharge_orders` per architecture §1.7.1 (UUIDv7, transactional). [Source: V1__baseline_schema.sql; architecture.md §1.7.1]

### uuid7 import (from memory)

If Python-side UUIDv7 generation is needed for `segmentation_recommendation_feedback`, use `from uuid_extensions import uuid7`. The DB generates it via `uuid_generate_v7()` automatically for the INSERT — Python does not need to generate the PK. [Source: memory: uuid7-import-and-pydantic-typecheck-gotchas]

### Project Structure Notes

- Modified: `service_webapp/src/agents/support/graph.py` (add recommend_plan tool)
- Modified: `service_webapp/src/db/billing/queries.py` (add get_subscriber_usage_profile, get_last_recharge_amount)
- Modified: `service_webapp/src/routers/support.py` (add POST /recommendations/feedback)
- Modified: `service_webapp/src/db/support/commands.py` (add log_recommendation_feedback)
- Modified: `frontend/src/portals/subscriber/components/PlanRecommendationCard.tsx` (add callbacks)
- No migration (segmentation_recommendation_feedback in V1).

### References

- [Source: epics.md §1.8.9 — Story 5.9 acceptance criteria]
- [Source: architecture.md §1.6.1 — Plan Recommendation (hybrid search + usage signals)]
- [Source: architecture.md:FR-32 — Plan recommendation tool]
- [Source: architecture.md:FR-33 — Recommendation feedback loop]
- [Source: V1__baseline_schema.sql:490–502 — segmentation_recommendation_feedback]
- [Source: 2-7-milvus-lite-initialisation-vector-seeding.md — plan_vectors collection]
- [Source: memory: uuid7-import-and-pydantic-typecheck-gotchas — uuid_extensions import]
- [Source: ux-brief-chatbot.md — Accept/Dismiss card UI pattern]

## Dev Agent Record

### Agent Model Used

claude-sonnet-4-6

### Debug Log References

### Completion Notes List

### File List
