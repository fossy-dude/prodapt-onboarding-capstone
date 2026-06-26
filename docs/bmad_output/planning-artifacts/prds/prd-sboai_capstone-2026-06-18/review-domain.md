# Domain Review: PRD — AI-Powered Prepaid Billing System
**Reviewer role:** Domain expert in AI systems and telecom billing  
**Review date:** 2026-06-18  
**PRD version reviewed:** prd-sboai_capstone-2026-06-18/prd.md  
**Source documents:** 01_SGQ.md, 02_Feature_List.md, Assumptions.md  
**Verdict:** PASS WITH NOTES

---

## Overall Assessment

The PRD is well-structured, coverage is broad, and the core telecom billing concepts are accurately modelled. Most requirements from the Feature List are correctly translated into numbered FRs with testable consequences. The key architectural constraints (agent placement, async fraud, latency SLA) are accurately reflected. However, there are five specific gaps or misalignments that engineering should resolve before build.

---

## 1. Domain Completeness

### 1.1 Feature List items NOT covered by any FR in the PRD

**GAP-1 (Medium): "Strategy Feedback Loop" — Feature List specifies reuse of Conclusion Agent; PRD explicitly breaks this**

Feature List §2.3 states:
> "Strategy Feedback Loop — Log recommendation outcomes to refine future segmentation/strategy (reuse Conclusion Agent)"

PRD FR-51 explicitly states:
> "The Conclusion Agent (chatbot session agent) is not involved in the upsell feedback loop."

This is an intentional divergence (logged in OQ-7), but it is not flagged as a design decision in the Feature List. The PRD's resolution is technically correct — coupling the upsell marketing workflow to the subscriber chatbot Conclusion Agent would create an architectural dependency across two distinct user journeys. The resolution is sound. However, the Feature List was never updated to reflect this decision. This is a documentation alignment issue, not a PRD defect.

**GAP-2 (Medium): Distributed Tracing — Feature List specifies CDR → rating → balance → notification; PRD drops "rating"**

Feature List §5.6:
> "Trace ID propagation across CDR → rating → balance → notification"

PRD FR-76 specifies:
> "A trace ID is propagated across the full CDR → balance → fraud → notification pipeline"

The PRD correctly omits "rating" (since the system receives post-rated CDRs — rating is upstream and out of scope per A-1/Assumption 1). However, it replaces "rating" with "fraud", which is the correct in-scope step. This is accurate and defensible but should be noted explicitly in the PRD assumptions table (it is not). No FR gap, but traceability of the decision is weak.

**GAP-3 (High): Token Optimisation — Feature List §5.2 lists it as an explicit P2 requirement; PRD has no FR for it**

Feature List §5.2:
> "Token Optimisation — Efficient LLM usage for large-scale CDR analysis and subscriber segmentation"

The PRD handles token control for the upselling flow implicitly (FR-47 caps LLM sample at 100, FR-48 specifies pre-aggregated feature vectors rather than raw CDRs, FR-36 rate-limits subscribers). However, there is no consolidated FR or NFR that defines a token budget, cost monitoring mechanism, or token-efficiency rubric for LLM calls across the platform. The counter-metric in §1.8 ("LLM token cost per upselling session — monitor for cost runaway") acknowledges the concern but does not give engineering a measurable gate.

**Recommendation:** Add an FR (or a measurable NFR) specifying: (a) token budget per LLM operation type, (b) the monitoring/alerting mechanism (LangFuse cost tracking or equivalent), and (c) the response if a budget is breached.

**GAP-4 (Low): Presentation / Next Steps — Feature List §5.7 lists this as a P1 deliverable; PRD §1.7.1 references it only in passing**

Feature List §5.7:
> "Next Steps — Enhancement pipeline post delivery of MVP"

PRD §1.7.1 mentions it as "Next Steps presentation section" in architecture deliverables. This is a capstone demo deliverable, not an engineering FR. No gap in system behaviour, but the PRD should note whether the content of the Next Steps section is itself a defined deliverable with acceptance criteria. As written, it is vague.

**GAP-5 (Low): Architecture Diagram specifics — Feature List §5.3 specifies JPEG/PDF format for the architecture diagram**

Feature List §5.3:
> "Architecture Diagram — JPEG/PDF; label CDR flow, rating, balance, AI/ML, APIs, datastores"

This is a deliverable format requirement. The PRD §1.7.1 lists "architecture diagram + design document" without specifying the format or labelling requirements. Low risk — address in the architecture document, not the PRD.

### 1.2 Architectural constraints from Assumptions.md

All key architectural constraints from the Assumptions document are accurately reflected in the PRD:

| Assumption | PRD Location | Accuracy |
|---|---|---|
| CDR as pipeline entry; pre-CDR out of scope | A-1, FR-57, §1.6 | Accurate |
| Both plan types (unlimited + talktime balance) | A-2, FR-58, Glossary | Accurate |
| USSD inbound-only, receives {msisdn, button_pressed, session_id} | A-3, FR-37 | Accurate |
| Agents NOT in synchronous balance deduction path | A-4, A-10, §1.9, FR-61 | Accurate — explicitly stated twice |
| Rule-based first, then agent escalation for fraud | Assumptions §4.2.1, FR-60, FR-61 | Accurate |
| Multi-agent framework (LangGraph etc.) is architecture decision | A-5, §4.5 | Accurate — PRD is framework-agnostic |
| Pre-activation OTP to alternate mobile | A-6, FR-4 | Accurate |
| SIM activation is UI simulation only | A-7, FR-2 | Accurate |
| RAG covers both general FAQ + plan/billing | A-8, FR-26 | Accurate |
| SMS + push share simulated pipeline | A-9, §4.4 | Accurate |
| SIM swap rule parameters are implementation decisions | A-12, FR-55 | Accurate |
| Indian operator, Indian customers only | Assumption 9, §1.3.2, §1.9 | Accurate |

**Finding:** All architectural constraints are correctly preserved. The latency/agent placement decision (assumptions §4.2.1, point 4b) is especially well handled — it appears in the PRD constraints (§1.9), in a dedicated assumption (A-4, A-10), and is referenced directly in FR-61. This is the highest-risk architectural constraint and it is thoroughly documented.

### 1.3 Fraud Detection Flow — Two-stage design accuracy

The fraud detection flow is correctly modelled as a two-stage pipeline:

- **Stage 1 (synchronous, deterministic):** FR-60 specifies rule-based pre-screening executes synchronously in the CDR pipeline. Rules include: high voice-call rate, roaming abuse, SIM swap signals, suspicious recharge patterns. Events passing all rules proceed without agent escalation. Events triggering a rule are flagged and queued for agent analysis.

- **Stage 2 (asynchronous, LLM-powered):** FR-61 specifies the Fraud Detection Agent receives flagged CDR events, the triggered rule(s), and relevant subscriber history. It produces a risk verdict (`confirmed | false positive | needs review`). The section description for §1.5.10 explicitly states: "Agent analysis runs asynchronously to the balance deduction to avoid adding latency to the <200ms deduction SLA."

- **Async from balance deduction:** A-4 and A-10 both state the agent escalation runs asynchronously. FR-61 is consistent with this. The PRD does not specify the exact mechanism for async handoff (e.g., queue, event bus), which is appropriate — this belongs in the architecture document.

**Finding:** Two-stage design is accurately described. The async separation from the balance deduction path is clearly stated. No gaps.

**Minor note (MEDIUM):** The PRD description for §1.5.8 says "Fraud detection pipeline is synchronous with the CDR processing flow — rule-based screening first, agent escalation second." This is slightly ambiguous — it could be read as the entire pipeline (including agent escalation) being synchronous with CDR processing. The intent is that rule-based screening is synchronous but agent escalation is async. The section body (FR-61) and the constraint table (§1.9) clarify this, but the section description should be made unambiguous. Suggested fix: "Rule-based screening is synchronous with the CDR processing flow; agent escalation runs asynchronously to protect the balance deduction SLA."

### 1.4 Multi-agent chatbot architecture

The multi-agent architecture is correctly described across several FRs:

| Agent | PRD Location | Protocol | Accuracy |
|---|---|---|---|
| Support Agent (primary orchestrator) | FR-22 through FR-35, Glossary | Orchestrates child agents | Accurate |
| Rating Agent | FR-29, Glossary | A2A from Support Agent | Accurate |
| Balance Management Agent | FR-31, Glossary | A2A from Support Agent | Accurate |
| Conclusion Agent | FR-34, Glossary | Triggered at session end | Accurate |
| Notification Agent | FR-35, Glossary | A2A from Conclusion Agent | Accurate |

**Finding:** The architecture matches the Feature List §1.5 and the Assumptions §4.2.1(b). All five agents are present, their roles are correctly separated, and the A2A protocol is consistently referenced for inter-agent communication. The Notification Agent's autonomy ("decides whether, when, and how") is preserved in FR-35.

**Minor note:** The PRD notes that the framework is LangGraph "or equivalent" (§1.5.5 description). This is correct — the PRD should not mandate the framework. The architecture document will resolve this. No defect.

---

## 2. AI/ML Requirements

### 2.1 Evaluation requirements (LangFuse, DeepEval, LLM-as-Judge)

**LangFuse (FR-72):** Requirements are sufficient for engineering to implement. The FR specifies every agent invocation, A2A call, and tool call must be captured as a LangFuse trace, queryable by session ID, agent type, and time range. This gives engineering a clear integration target.

**LLM-as-Judge (FR-73):** Requirements are mostly sufficient. The FR specifies offline evaluation on a configurable sample, quality score + pass/fail per rubric, and persistent storage of results. 

**Gap (MEDIUM):** The rubric itself is not defined. "Per defined rubric" is referenced three times (FR-73, Success Metrics §1.8) but the rubric criteria (e.g., relevance, factual accuracy, tone, groundedness) are not specified anywhere in the PRD. Engineering cannot implement an LLM-as-Judge without knowing what the judge is scoring. This should be added either as FR consequences or as a referenced specification.

**DeepEval (FR-74):** Requirements are mostly sufficient. Offline + sampled online evals are specified. Metrics listed: response faithfulness, relevance, hallucination rate for chatbot; accuracy metrics for churn and recharge conversion predictions.

**Gap (MEDIUM):** Target thresholds for DeepEval metrics are missing for the chatbot faithfulness and relevance metrics. The Success Metrics table (§1.8) defines chatbot hallucination rate target (< 5%) and LLM-as-Judge pass rate (≥ 80%), but does not define a minimum threshold for faithfulness or relevance scores from DeepEval. This creates an ambiguous quality gate.

**Gap (LOW):** FR-74 mentions "recharge conversion and churn prediction accuracy" as metrics but neither a churn prediction model nor a recharge conversion model is defined as an explicit feature in the PRD. The subscriber growth forecast (FR-44) uses time-series ML for activations/churn, but this is a forecasting model, not a churn prediction model for individual subscribers. The distinction should be clarified, or the DeepEval metric should be scoped to the time-series forecast model (with MAPE already defined in §1.8).

### 2.2 Upsell segmentation flow

The full five-step flow is correctly represented:

1. **Target Base Builder (FR-46):** Dynamic KPI filter from materialised view — accurate, avoids hardcoding.
2. **Pool Preview & Stats (FR-47):** Sample + statistics, LLM sample cap at 100 — accurate.
3. **LLM Per-Customer Labelling (FR-48):** Pre-aggregated feature vectors, not raw CDRs — accurate and token-optimised.
4. **Rule Induction Agent (FR-49):** Human-readable KPI predicates, persisted to DB — accurate.
5. **Segment Classification at Scale (FR-50):** Deterministic, no LLM re-invocation — accurate.
6. **Upsell Strategy Recommendations (FR-51):** LLM generates textual strategy per segment — accurate.

**Finding:** The flow is complete and correctly ordered. The token-optimisation rationale (pre-aggregated summaries, not raw CDRs) is explicitly stated in FR-48. The deterministic classification step (FR-50) correctly avoids LLM re-invocation at scale. The non-goal of catalogue-plan mapping is correctly tagged.

**Minor gap (LOW):** The PRD does not specify what constitutes a "pre-aggregated feature vector" for LLM input. Engineering will need to define the feature schema (e.g., total data usage in GB, average ARPU, days since last recharge, plan type). This is a data engineering design decision, but a minimum field list should be specified either in the PRD or in a referenced data contract. Without it, the LLM labelling output quality is unpredictable.

### 2.3 Plan recommendation hybrid search

FR-32 states:
> "The Support Agent offers a plan recommendation using a hybrid search combining plan attribute matching, semantic retrieval, and subscriber usage signals."

The three components — plan attributes, semantic retrieval, usage signals — are all present and match the Feature List §1.5.

**Gap (HIGH):** The hybrid search mechanism is underspecified for engineering implementation. Specifically:
- **Semantic retrieval:** What is the embedding model? What is the vector index? What text is embedded (plan descriptions? FAQ content?)? What is the similarity metric?
- **Plan attribute matching:** What are the matching rules? (e.g., filter by price ≤ current plan price, data allowance ≥ current usage)?
- **Usage signals:** How are usage signals sourced? From CDR aggregates? From the same materialised KPI view used for upselling? What time window?
- **Hybrid fusion:** How are the two signals combined? (Reciprocal rank fusion? Weighted scoring?)

The FR consequence only specifies "1–3 plans returned with natural language rationale logged to feedback loop." This is outcome-oriented but not implementation-sufficient. A tech note or companion architecture decision record is needed before engineering begins the recommendation engine.

---

## 3. Telecom/Regulatory Requirements

### 3.1 TRAI compliance

**CAF (FR-3, FR-65):** Digital CAF submission with immutable audit trail is specified. FR-3 requires the audit trail to be immutable and linked to the subscriber account. FR-65 requires the CAF audit trail to be "maintained per TRAI requirements." 

**Gap (LOW):** The specific TRAI CAF fields are not specified. For a production system, the CAF requires: subscriber name, address, ID proof type and number, photograph acknowledgement, service type, and activation date. The PRD does not enumerate these, which means the data model may be incomplete. For an MVP/capstone context this may be acceptable, but should be flagged.

**Data Localisation (FR-65, §1.9):** "All subscriber data is stored in infrastructure physically located within India borders" — correctly specified.

**Retention (FR-59, A-5/OQ-5):** "Billing records retained for a minimum of 6 years per TRAI mandate" — correctly specified and the decision is logged in OQ-5.

**Finding:** TRAI compliance coverage is adequate for MVP. The 6-year retention period is correctly specified. Data localisation constraint is in both the FR and the constraints section (§1.9). The CAF field-level specification is a gap but is low risk for MVP.

**Gap (MEDIUM): DND (Do Not Disturb) Registry compliance missing**

TRAI mandates that SMS/push notifications respect the National Customer Preference Register (NCPR/DND). Subscribers registered on the DND list must not receive unsolicited commercial communications. This requirement is absent from the PRD. The notification opt-in/out via USSD (FR-41) and the Notification Agent (FR-35) do not reference DND compliance. For a real-world telecom system this would be a regulatory blocking issue.

**For MVP context:** Since notifications are simulated and there is no real SMS gateway, DND compliance cannot be enforced technically in MVP. However, the PRD should acknowledge this gap and tag it as a post-MVP compliance requirement. Currently, the PRD is silent on DND.

### 3.2 CDR schema completeness

FR-57 specifies:
> "Each CDR event carries: subscriber MSISDN, event type (voice/data/SMS/roaming), duration/volume, timestamp, and CDR reference ID."

FR-71 (Synthetic Dataset) specifies:
> "All CDRs include required schema fields: subscriber MSISDN, event type, duration/volume, timestamp, rate, charge, CDR reference ID."

**Finding:** The CDR schema in FR-71 is more complete than FR-57 (adds `rate` and `charge` fields). For consistency, FR-57 should match FR-71's field list — the ingestion pipeline should carry `rate` and `charge` fields since the fraud detection rules and the Rating Agent's charge breakdown explanation (FR-29) depend on these values.

**Gap (MEDIUM):** Several standard CDR fields present in real telecom systems are absent from both FRs:
- **Call duration vs. charged duration** (may differ due to billing increment rules)
- **Cell tower / Location Area Code (LAC)** — required for SIM swap detection (FR-55 specifies geographic distance threshold as a rule parameter, but the CDR schema does not include location data)
- **Roaming partner ID / PLMN code** — needed for roaming abuse detection (FR-60)
- **Service node ID** — for tracing in distributed systems
- **Termination cause code** — for dropped call detection

The most critical missing field for in-scope features is **location data (LAC/Cell-ID or equivalent)**. FR-55 explicitly describes SIM swap detection using "MSISDN used from two geographically distant locations within a short time window" — but if the CDR schema has no location field, this rule cannot be evaluated. This is a functional gap, not just a schema completeness issue.

**Recommendation:** Add at minimum a `cell_id` or `location_area_code` field to the CDR schema in FR-57 and FR-71.

---

## 4. Gaps and Conflicts

### 4.1 PRD vs. source assumptions — contradictions

**No contradictions found.** All assumptions from Assumptions.md are faithfully reflected in the PRD assumptions index (§1.10) and in the relevant FRs. The most sensitive assumption — agents out of the synchronous balance deduction path (Assumptions §4.2.1) — is handled consistently across A-4, A-10, §1.9, and FR-61. No conflicting statements were found between the PRD and the source assumptions.

### 4.2 Internal PRD contradictions

**Contradiction-1 (MEDIUM): §1.5.8 section description vs. FR-61 on synchronous/asynchronous boundary**

As noted in section 1.3 above, the §1.5.8 description says "Fraud detection pipeline is synchronous with the CDR processing flow" while FR-61 and A-4/A-10 clarify that agent escalation is asynchronous. The section description is misleading and should be corrected.

**Contradiction-2 (LOW): FR-57 CDR schema vs. FR-71 CDR schema**

FR-57 omits `rate` and `charge` fields that FR-71 includes. Ingestion pipeline spec (FR-57) and dataset spec (FR-71) should have an identical field list.

### 4.3 Missing requirement: Churn prediction model

Feature List §1.7 (Ops dashboard) and §1 (SGQ Future State) reference subscriber segmentation and churn forecasting. The PRD captures the time-series subscriber growth forecast (FR-44, FR-45). However, the FR-74 DeepEval metric references "churn prediction accuracy" as if a per-subscriber churn propensity model exists. No such model is defined as a feature. Either:
- FR-74 should remove the churn prediction accuracy metric reference, or
- A per-subscriber churn prediction model should be added as a feature (even if P2 or NON-GOAL for MVP)

This is currently an internal inconsistency that will confuse engineering.

### 4.4 Missing requirement: Plan recommendation feedback loop persistence schema

FR-33 specifies that recommendation outcomes (accepted/dismissed) are persisted to "a feedback store." FR-51 specifies that upsell strategy outcomes are logged to "a dedicated upsell feedback store." These are two distinct feedback stores. Neither store's schema, retention policy, or access mechanism is defined. For ML/eval engineers building the feedback loop and for the DeepEval integration (FR-74), at minimum the feedback store schema (what fields are stored) should be specified.

---

## 5. Summary of All Findings

| ID | Severity | Area | Finding |
|---|---|---|---|
| F-1 | HIGH | Hybrid Plan Recommendation | Hybrid search mechanism is underspecified — embedding model, vector index, attribute matching rules, usage signal source, and fusion method are all undefined |
| F-2 | MEDIUM | CDR Schema | Location data (LAC/Cell-ID) missing from CDR schema; required for SIM swap geographic detection rule (FR-55) |
| F-3 | MEDIUM | Evaluation | LLM-as-Judge rubric criteria not defined; "per defined rubric" referenced without specification |
| F-4 | MEDIUM | Fraud Detection | §1.5.8 section description ambiguously says pipeline is "synchronous" when agent escalation is async — contradicts FR-61 and A-4 |
| F-5 | MEDIUM | TRAI Regulatory | DND (Do Not Disturb) registry compliance absent from notification requirements; should be tagged as post-MVP |
| F-6 | MEDIUM | Evaluation | DeepEval "churn prediction accuracy" metric references a model that does not exist as a defined feature |
| F-7 | MEDIUM | Token Optimisation | No consolidated FR/NFR for token budgets, cost monitoring, or breach response despite Feature List listing this as an explicit P2 requirement |
| F-8 | MEDIUM | CDR Schema | FR-57 (ingestion) and FR-71 (dataset) have mismatched CDR field lists; `rate` and `charge` missing from FR-57 |
| F-9 | LOW | Upsell Segmentation | Pre-aggregated feature vector schema not specified; LLM label quality depends on feature set |
| F-10 | LOW | Evaluation | DeepEval faithfulness/relevance minimum threshold not defined |
| F-11 | LOW | Feature Coverage | Strategy Feedback Loop decision (OQ-7) exists only in PRD; Feature List §2.3 still says "reuse Conclusion Agent" — documentation misalignment |
| F-12 | LOW | TRAI | CAF field-level schema not specified; acceptable for MVP but should be acknowledged |
| F-13 | LOW | Feedback Stores | Two feedback stores (plan recommendation, upsell strategy) referenced without schema or retention policy |
| F-14 | LOW | Feature Coverage | Distributed tracing chain in Feature List (CDR→rating→balance→notification) not updated to reflect correct in-scope chain (CDR→balance→fraud→notification) |

---

## 6. Recommended Actions Before Engineering Kickoff

**Must fix (blocks implementation):**
1. Add a minimum CDR schema field for location data (cell_id or LAC) to FR-57 and FR-71 to enable SIM swap geographic detection.
2. Define the hybrid plan recommendation mechanism in a referenced technical note or ADR: embedding model type, vector index, attribute matching rules, usage signal source, and fusion method.
3. Define the LLM-as-Judge rubric criteria (even as a stub: faithfulness, relevance, groundedness) or reference a separate evaluation spec document.

**Should fix (risk of scope confusion):**
4. Correct §1.5.8 section description: rule-based screening is synchronous; agent escalation is asynchronous.
5. Align FR-57 CDR schema with FR-71 (add `rate` and `charge`).
6. Add DND compliance acknowledgement to notification FRs (FR-18 through FR-21, FR-35) with a [NON-GOAL for MVP] tag and a post-MVP note.
7. Resolve DeepEval churn prediction metric — either remove it or define the churn model as a feature.
8. Add a token budget NFR or FR covering monitoring, alerting, and breach response.

**Nice to have:**
9. Specify minimum fields for feedback stores (plan recommendation + upsell strategy).
10. Update Feature List §2.3 to reflect OQ-7 resolution (or add a footnote in the PRD pointing to the Feature List discrepancy).
11. Specify pre-aggregated feature vector minimum field list for LLM segmentation input.

---

*End of review.*
