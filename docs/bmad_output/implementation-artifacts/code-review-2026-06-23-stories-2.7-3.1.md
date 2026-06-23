# Code Review — Story 3.1 + Story 2.7

- **Date:** 2026-06-23
- **Reviewer model:** claude-fable-5 (GLM-5.2)
- **Scope:** `git diff c733cba..0faf4cb` (HEAD)
  - Story 3.1 (`0ae2528`) — doc-only UX brief (`docs/bmad_output/planning-artifacts/ux-brief-portal.md`)
  - Story 2.7 (`0faf4cb`) — Milvus Lite init + vector seeder
- **Both stories:** status `review`

## Verdict

| Story | ACs | Blockers | Recommendation |
|---|---|---|---|
| **2.7** | #4 FAIL; #2 / #6 / #7 PARTIAL | CRITICAL: seeder cannot run (#1) | **Do not mark done.** Fix #1–#4, re-run `just seed-milvus` end-to-end. |
| **3.1** | #1–#6 all PASS | none (doc) | Approve after #15 (Modal). Rest Low polish. |

Note: the test suite gives false confidence — the seeder logic is entirely untested, so the critical crash shipped uncaught.

---

## Story 2.7 — Milvus Lite Initialisation & Vector Seeding

### AC verdict

| AC | Verdict | Evidence |
|---|---|---|
| 1 | PARTIAL | Connects to embedded path; graceful degradation makes Milvus *optional* (`main.py:81-89` sets adapter=None on error; `/ready` then omits milvus and still 200s). |
| 2 | FAIL | Collections/fields defined in code, but seeder crashes (#1) and `severity` never populated (#2). |
| 3 | PASS | HNSW + BM25 `Function` + `SPARSE_INVERTED_INDEX` + `RRFRanker` wired (`milvus.py:62-91`). |
| 4 | **FAIL** | `seed_plan_vectors` SELECTs a nonexistent column → crashes before any vector written (#1). |
| 5 | PASS | `data/faq.yaml` = 55 entries (≥50). |
| 6 | PARTIAL | `sop_chunks` seeded but `severity` hard-coded empty (#2). |
| 7 | PARTIAL | drop+recreate implemented; not unit-tested; asserts may fail on stale stats (#5, #7). |

### Findings

**[CRITICAL] #1 — Seeder crashes: `plan_type` column does not exist.** `scripts/seed_milvus.py:105`
```sql
SELECT id, plan_name, plan_code, price_paise, validity_days, plan_type FROM plans_plans WHERE is_active = TRUE
```
`plans_plans` has no `plan_type` column (`db/migrations/V1__baseline_schema.sql:107-122`; confirmed no later migration adds it). `just seed-milvus` aborts with `psycopg.errors.UndefinedColumn`. AC #4 unachievable as written. **Fix:** remove `plan_type` from the SELECT and derive it from `plan_code` (the 3.1 brief §9.3 already prescribes this). The 2.7 Completion Note claims the script "asserts plan_vectors == 1000" — it was never run against a real DB.

**[HIGH] #2 — `severity` always empty; source has no severity column.** `scripts/seed_milvus.py:170` `"severity": ""[:64]`. `sop_knowledge_chunks` (`schema:572-581`) has no severity column, so AC #2's `severity` field can never be populated. Either add severity to the migration / 2.6 generator, or document it as intentionally blank. `""[:64]` is a nonsense leftover expression — a placeholder never replaced.

**[HIGH] #3 — pymilvus runtime dep `>=2.4`, code needs `>=2.5`.** `service_webapp/pyproject.toml:17` declares `pymilvus[milvus-lite]>=2.4`; code imports `Function, FunctionType, SPARSE_FLOAT_VECTOR, RRFRanker` (`milvus.py:17,62`) — 2.5+ APIs. A fresh re-resolve could land 2.4.x → ImportError at boot. Tox envs correctly pin `>=2.5` (`:316,350`); main dep does not. Lock currently mitigates; **bump `:17` to `>=2.5`.**

**[HIGH] #4 — Seeder logic has ZERO unit tests (spec Task 8 required).** `tests/unit/test_milvus_adapter.py` covers only `MilvusAdapter` + `faq.yaml` structure + embedding client. `seed_plan_vectors` / `seed_faq_chunks` / `seed_sop_chunks` / `drop_and_create` / `main` are untested. A mocked-psycopg unit test would have caught #1.

**[MEDIUM] #5 — Idempotency (AC #7) not actually tested.** `tests/integration/test_milvus_integration.py:118` imports `_build_schema` and manually recreates — it never calls the seeder's `drop_and_create`. Test name oversells coverage.

**[MEDIUM] #6 — AC #2 metadata fields not verified.** Unit test checks only embedding dim=1536; integration `test_collections_have_correct_fields` (`:51`) asserts only embedding/text/sparse_embedding — not the per-collection scalars (`category/source_doc/plan_type`; `plan_type/price/validity`; `rule_id/severity/domain`). A dropped metadata field would pass.

**[MEDIUM] #7 — `get_collection_stats` read with no `flush()` → stale-count risk.** `seed_milvus.py:124,149,176` call stats immediately after `upsert`. The hard asserts (`==1000`, `>=50`, `>0`) may fail on lagging stats even when upsert succeeded. Add `client.flush([name])` before counting.

**[MEDIUM] #8 — `assert plan_count == 1000` is brittle.** `seed_milvus.py:216`. Spec says "~1,000"; `WHERE is_active=TRUE` excludes inactive rows; any env with !=1000 active plans fails. The empty-`plans_plans` guard (`sys.exit`) already covers the zero case — relax to `> 0` or compare against `SELECT count(*)`.

**[MEDIUM] #9 — Graceful startup hides failure → AC #1 treated as optional.** `main.py:81-89` swallows all Milvus errors → `milvus_adapter=None` → `/ready` omits milvus and still returns 200. A prod misconfig (bad path / missing Azure keys) is invisible while Epic 5/7 depend on a populated store. Consider failing `/ready` when Milvus is configured-but-down.

**[MEDIUM] #10 — Seed path diverges from app path.** `scripts/seed_milvus.sh:22` defaults `MILVUS_DB_URI` to `${PROJECT_ROOT}/data/milvus/sboai.db`; the containerised app reads `/app/data/milvus/sboai.db`. Seeded vectors won't be visible to the app unless the operator aligns paths/mounts. Single-writer constraint (spec Task 4) also unenforced — relies on the operator stopping the app first.

**[LOW] #11 — `make_embedding_client` is dead code.** `adapters/embeddings.py:60` builds the "injectable/mockable" client the spec (Task 5) asked for — but the seeder bypasses it and constructs `AzureOpenAIEmbeddings` directly (`seed_milvus.py:191`). This is why seeder unit tests can't easily mock embeddings (see #4).

**[LOW] #12 — Blocking `MilvusClient(uri=uri)` on the event loop.** `milvus.py:100` runs client construction synchronously in `__init__` during lifespan. One-time/fast for Lite, but inconsistent with the module's documented `to_thread` discipline.

**[LOW] #13 — `hybrid_search` returns `results[0]` only** (`milvus.py:152`). Fine for Epic 5's single-query use; undocumented.

**[LOW] #14 — Integration test shares mutable state with implicit ordering.** `tests/integration/test_milvus_integration.py:18-27` module-scoped `real_adapter` is created→described→mutated→dropped across tests. Fragile under reorder/parallel.

---

## Story 3.1 — UX Brief (doc-only)

### AC verdict

| AC | Verdict | Evidence |
|---|---|---|
| 1–6 | **PASS** | All routes/components/flows/contracts/variances present (`ux-brief-portal.md` §1–§9.3). |

### Findings

**[MEDIUM] #15 — `Modal` wrongly listed as an EXISTING component.** `ux-brief-portal.md` §3.1 "Existing Components (Reuse)" table includes Modal — but `frontend/src/components/ui/index.ts` exports only Badge/Button/Card/Table (no Modal). The 3.1 spec Task 4 explicitly says Modal/Input/Select are NEW. §3.2 then lists Input+Select as new but omits Modal → Modal appears to exist when it doesn't. A 3.5 dev will expect to reuse it. **Fix:** move Modal to §3.2 (Story 3.5).

**[LOW] #16 — Role-claim wording contradicts codebase.** §2.3 body: "The JWT `role` claim determines..."; but `frontend/src/lib/auth.ts:7` + `components/layout/RoleGuard.tsx:5` confirm the role comes from **`cognito:groups`** (no `role` claim). The brief's own §1 note + §2.3 prefix text already say `cognito:groups` — §2.3 body is the outlier. Fix wording.

**[LOW] #17 — `Balance.tsx (reserved for future)` ambiguity.** §9.1 tree lists it, but §2.1 / §4 put the BalanceCard inside `Dashboard.tsx`. A separate `Balance.tsx` is ambiguous vs the spec's authoritative portal map. Clarify or drop.

**[LOW] #18 — Undefined edge cases.** Negative balance (refunds exist), UsageRing `allowed=0` division, receipt-not-found, empty payment-method list, recharge double-submit. A one-line "defer to 3.x impl" each would stop downstream guessing.

---

## Cross-story

**[MEDIUM] #19 — Brief warned; 2.7 ignored it.** The 3.1 brief §9.3 explicitly states "`plan_type`/`category` ... no column exists ... derive from `plan_code` or omit." Story 2.7's seeder — same review batch — SELECTs `plan_type` directly. Same root as #1. The brief is authoritative for 3.x; it should have been heeded by 2.7 too.

---

## Disposition

**Delegated for fix (background agent — 2026-06-23):** #1, #2, #3, #4, #5, #6, #7, #8 (all 2.7 code/test findings in `scripts/seed_milvus.py`, `service_webapp/pyproject.toml`, and a new seeder test file).

**Open for manual follow-up (design decisions / polish, not auto-fixed):**
- #9 (graceful-startup vs `/ready` policy) — product/ops decision.
- #10 (seed path vs container path alignment) — ops/docs decision.
- #11–#14 (low-severity cleanups).
- #15–#18 (3.1 doc edits — Modal categorisation, wording).
- #19 (process note — resolved once #1 is fixed).

**Before marking either story `done`:**
- **2.7:** confirm the delegated fixes land, then run `just seed-milvus` end-to-end once to prove AC #4 / #7.
- **3.1:** apply #15 (Modal) and #16 (cognito:groups wording).
