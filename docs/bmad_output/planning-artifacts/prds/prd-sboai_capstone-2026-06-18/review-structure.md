# PRD Structural Review
**Document reviewed:** `prd.md` — AI-Powered Prepaid Billing System
**Reviewer role:** Senior Product Manager
**Review date:** 2026-06-18
**Verdict:** PASS WITH NOTES

---

## Executive Summary

This is a well-structured, detailed PRD that covers the prepaid billing lifecycle comprehensively. The FR numbering is globally consistent (FR-1 through FR-77), user journeys are concrete named-persona narratives, the glossary is thorough, and the non-goals section is explicit and well-maintained. The document falls short of a clean PASS on four distinct grounds: (1) two FRs have consequences that are not fully testable, (2) one significant functional gap exists between a User Journey and the FR coverage, (3) a handful of glossary terms used in FRs are absent from the glossary, and (4) the Vision section, while strong, blends the problem statement with architectural decisions in a way that creates forward risk. None of these are blocking defects for MVP planning, but they need resolution before handing off to engineering.

---

## Criterion-by-Criterion Findings

### 1. Vision — Does it stand alone?

**Rating: PASS WITH NOTE**

The Vision (§1.2) is three strong paragraphs covering the problem, the solution concept, and the desired outcome. It is independently readable without the rest of the document.

**Note:** The Vision mentions "100,000 CDR events per second at the target state" — this is a Target State infrastructure figure, not an MVP outcome. The Vision risks being read as a launch commitment. Recommend adding one sentence making clear the 100K/s figure is the Target State ceiling, not the MVP launch threshold. The Constraints section (§1.9) does state this clearly, but the Vision does not.

---

### 2. User Types and Jobs To Be Done

**Rating: PASS**

All four user types are identified with distinct, well-scoped JTBDs: Subscriber, Operations & Marketing Team, Fraud Management Team, and Platform/Engineering. JTBDs are stated in first-person ("I want to…") form, which is correct.

**Minor note:** The Platform/Engineering JTBD reads more like NFR bullets ("Ingest CDRs at scale…") than user-oriented jobs. This is a common pattern for internal platform users and is acceptable, but the distinction from actual NFRs could be drawn more clearly.

---

### 3. User Journeys — Concrete Named-Persona Narratives

**Rating: PASS**

All five User Journeys (UJ-1 through UJ-5) use named personas (Priya, Rohan, Anjali, unnamed fraud analyst, unnamed marketing manager). UJ-3 through UJ-5 name the specific agents involved. Each journey describes a complete end-to-end scenario with a clear start, decision point, and resolution.

**Minor note:** UJ-4 and UJ-5 omit persona names for the fraud analyst and marketing manager. This is a stylistic inconsistency with UJ-1/2/3, not a functional gap. Consider naming them for consistency.

---

### 4. Glossary — Completeness Against FRs

**Rating: PASS WITH NOTES**

The glossary (§1.4) is one of the strongest sections of the PRD — 29 terms defined. However, three terms used in FR bodies are absent:

| Missing Term | Used In | Impact |
|---|---|---|
| **Rule Induction Agent** | FR-49 title and body | An entire agent type is described in §1.5.7 description and has a dedicated FR (FR-49), but is not in the glossary. This is a significant omission since the Rule Induction Agent is distinct from the Fraud Detection Agent and the Support Agent. |
| **Root Cause Analysis Agent** | FR-75 | Defined in §1.5.14 description text but absent from the glossary. |
| **Dead-letter mechanism** | FR-57 | Used without definition; engineers will assume standard meaning, but it should be glossarised for completeness. |

**Additional consistency note:** "Wallet Balance" and "balance" are used interchangeably across several FRs (e.g., FR-8, FR-22, FR-31, FR-38). The glossary defines "Wallet Balance" as the canonical term. FRs using bare "balance" should be updated for consistency.

---

### 5. FR Numbering and Testable Consequences

**Rating: PASS WITH NOTES**

FRs are globally numbered FR-1 through FR-77 with no gaps or duplicates. The vast majority have well-formed testable consequences. Two exceptions:

**FR-66 (Account Takeover Prevention) — FAIL on testability:**
The two consequence bullets are incomplete sentences that appear to have been cut off mid-thought:
- "SIM swap signals detected in the fraud pipeline are propagated to the auth layer by blacklisting the account (at the Gateway level)" — no testable outcome stated. What exactly happens to a blacklisted account? What does the system return on a login attempt?
- "The user is asked to speak with a Telecom Kiosk agent to login. If already logged in, an auth alert is sent and the user is logged out" — this is a consequence, but it is vague. "Auth alert" is undefined. Is this a notification via the Notification Portal? An in-app message? This needs to be specific enough for a QA engineer to write a test case.

**Recommendation:** Rewrite FR-66 consequences in concrete, observable form: e.g., "When a SIM swap signal is confirmed by the Fraud Detection Agent, the subscriber's account is flagged as `suspended_fraud_review`; subsequent login attempts return HTTP 403 with a message directing the subscriber to a telecom kiosk; if the subscriber is currently logged in, their session token is invalidated and a push notification is sent to the Notification Portal."

**FR-44 (Subscriber Growth Forecast) — borderline:**
The consequence "Forecast refreshes on a configurable schedule (e.g. daily)" uses "e.g." which implies the schedule is not defined. This should be either a fixed default with a configurable override, or explicitly deferred as an implementation decision. As written, it is ambiguous to engineering.

---

### 6. Non-Functional Requirements (NFRs)

**Rating: PASS WITH NOTE**

NFRs are distributed across several sections rather than consolidated:
- **Latency:** Balance deduction P95 ≤ 200ms — covered in Constraints (§1.9) and FR-58.
- **Scale:** 100K CDR/sec Target State — covered in §1.9 and FR-57 description.
- **Security:** PII encryption, PCI-DSS, TRAI — covered in §1.5.11 (FRs 63–67).
- **Availability/Reliability:** Health check endpoints (FR-77) are present but there is no availability SLA stated (e.g., 99.9% uptime for the balance deduction path).
- **Compliance:** TRAI, PCI-DSS, data localisation — covered adequately.

**Gap:** No NFR captures chatbot response latency. UJ-3 (Anjali's chat session) implicitly expects a responsive chatbot, but there is no stated target for P95 chatbot response time. If the LLM call takes 10 seconds, a subscriber-facing SLA is violated. Recommend adding an NFR or consequence to FR-22/FR-23/FR-29: "Chatbot responses are delivered within X seconds at P95."

**Gap:** No concurrent user / load NFR for the subscriber portal or operations dashboard. The CDR pipeline has a throughput target, but the web-facing tiers have no stated concurrent session target. At minimum a rough order-of-magnitude target (e.g., "supports 10,000 concurrent subscriber sessions") should be added for MVP architecture sizing.

---

### 7. MVP Scope — In/Out of Scope

**Rating: PASS**

§1.7 is well-structured with explicit in-scope (P0/P1/P2 priority buckets) and out-of-scope lists. All out-of-scope items from the Non-Goals section (§1.6) appear in the out-of-scope list. The P0/P1/P2 priority framing is useful for sequencing.

**Minor note:** The in-scope list in §1.7.1 is written as a long prose sentence, which is hard to audit. A bullet-point format matching the out-of-scope list would make cross-checking Non-Goals against MVP scope easier.

---

### 8. Success Metrics — Measurable Targets

**Rating: PASS**

The success metrics table (§1.8) is one of the strongest sections of the PRD. Nine primary metrics, each with a definition and a quantified target or explicit "Baseline measurement" placeholder. Counter-metrics are a good addition.

**Minor note:** "Plan recommendation conversion rate — Baseline measurement in MVP" is the only metric without a target. This is acceptable for a first-release baseline, but the PRD should state explicitly who owns defining the target post-baseline (operations team? ML team?) so it does not get lost.

---

### 9. Assumptions — Indexed and Tagged Inline

**Rating: PASS**

§1.10 lists 15 indexed assumptions (A-1 through A-15), each tagged to specific FRs or sections. Inline tagging of cross-references is present. This is well-executed.

**Minor note:** A-4 and A-10 are semantically duplicate ("Agents are NOT in the synchronous balance deduction path" / "Fraud agent analysis is asynchronous to the balance deduction"). Both reference FR-61. Consider merging into a single assumption to avoid inconsistency drift if one is updated and the other is not.

---

### 10. Non-Goals — Explicit

**Rating: PASS**

§1.6 has 12 explicit non-goals with clear rationale. The `[NON-GOAL for MVP]` inline tag and the `#future_not_mvp` tag are used consistently in FRs.

---

### 11. FR Actor-Capability-Condition Form

**Rating: PASS WITH NOTE**

The majority of FRs follow the pattern "An [actor] can [capability] under [condition]" or "The system [does X] when [condition]". This is the correct form.

**Exceptions:**
- **FR-59 (Audit Log Trail):** "Every billing, authentication, and administrative action is recorded…" — this is a system property, not an actor-capability statement. Acceptable for a platform-level NFR-adjacent FR, but inconsistent with the rest.
- **FR-71 (Synthetic Dataset Generation):** "The system includes scripts to generate…" — this describes a deliverable (scripts), not a system capability. The FR should be rewritten as a system capability: "The system can generate a synthetic dataset…" or acknowledged as a developer tool deliverable.
- **FR-77 (Health Check Endpoints):** "Every microservice exposes `/health` and `/ready` endpoints." — this is a delivery requirement, not an actor-capability FR. Consider moving to NFRs or Constraints.

---

### 12. Testable Consequences — Vague, Prescriptive, or Untestable FRs

**Rating: PASS WITH NOTES**

Beyond FR-66 (discussed above), these FRs have quality issues:

**FR-27 (Input Validation Guardrails):** The first consequence ("Prompt injection attempts, excessively long inputs, and structured malicious payloads are rejected") is testable. The second consequence ("Legitimate edge-case inputs (e.g. mixed-language, typos) are processed without rejection") is not independently testable without a defined test set. This is acceptable for MVP, but a test corpus should be attached to this FR before QA.

**FR-51 (Upsell Strategy Recommendations):** "Strategy output covers: optimal outreach timing and what the segment is likely interested in." This is vague — "optimal outreach timing" is not a measurable output. How will QA verify this? Recommend specifying the minimum fields in the strategy output (e.g., "strategy output includes: recommended channel, timing window, and value proposition text per segment").

**FR-75 (Root Cause Analysis Agent):** "returns a structured root cause analysis" — "structured" is implementation-prescriptive without specifying the schema. Consequence should either specify the output format minimally (e.g., "returns a root cause category, affected component, and recommended remediation step") or explicitly defer schema definition to the architecture document.

---

### 13. Implementation-Prescriptive FRs

**Rating: PASS WITH NOTE**

The PRD largely avoids implementation prescription. Two minor cases:

- **FR-31 (Balance Management Agent Integration):** "A2A communication between agents is traceable via LangFuse" — this names LangFuse as an implementation detail within an FR consequence. LangFuse traceability is already captured in FR-72. The consequence in FR-31 is redundant and couples the FR to a specific tool. Remove it from FR-31 and rely on FR-72.
- **FR-46 (Target Base Builder):** "sourced from the columns of a materialised database view" — "materialised database view" is an implementation detail. The FR should say "dynamically sourced from a configured data schema" or similar, and leave the materialised view decision to the architecture document.

---

### 14. FR Coverage Gaps Against User Journeys

**Rating: PASS WITH ONE GAP**

Mapping UJs to FRs:

| UJ | Key Actions | Covered by FRs |
|---|---|---|
| UJ-1 | Sign-up, Registration ID, CAF, order tracking, MSISDN binding | FR-1, FR-2, FR-3, FR-4 — FULL COVERAGE |
| UJ-2 | Login, balance view, plan details, plan browse, UPI payment, SMS notification, PDF receipt | FR-4, FR-8, FR-11, FR-12, FR-13, FR-14, FR-15, FR-18 — FULL COVERAGE |
| UJ-3 | Chat query, Rating Agent, charge breakdown, dispute, ticket creation, session-end notification | FR-22, FR-29, FR-30, FR-34, FR-35 — FULL COVERAGE |
| UJ-4 | CDR arrives, rule-based screening, Agent escalation, case queue, analyst review, supervisor notification | FR-53, FR-54, FR-55, FR-60, FR-61, FR-62 — FULL COVERAGE |
| UJ-5 | Filter base, Target Base Builder, LLM labelling, Rule Induction, classification, strategy recommendations | FR-46, FR-47, FR-48, FR-49, FR-50, FR-51 — FULL COVERAGE |

**Gap identified — UJ-4 (Fraud Analyst Flow):**
UJ-4 states: "The analyst reviews and **escalates or clears** the case." FR-54 (Fraud Case Queue) defines case status transitions as `Open → Under Review → Resolved` and says "The fraud supervisor can update case status and add notes." However, no FR explicitly covers the analyst's action of **clearing a false positive** — i.e., marking an agent-escalated case as a false positive and removing it from the active queue. FR-61 states the agent produces a verdict of `confirmed | false positive | needs review`, but no FR specifies what happens in the UI when the fraud analyst concurs with or overrides a `false positive` verdict. This is a small but real gap: the false positive path through the Fraud Case Queue UI has no FR.

**Recommendation:** Add an FR or extend FR-54 consequences to cover: "A fraud analyst can mark a case as `false positive`; the case is removed from the active queue, the analyst's override is logged with a timestamp and analyst ID, and the event is recorded for future fraud model calibration."

---

### 15. Glossary Term Consistency

**Rating: PASS WITH NOTE**

Terms are used consistently throughout. One inconsistency noted:

- **"Wallet Balance" vs. "balance":** The glossary defines "Wallet Balance" as the canonical term. FRs 8, 19, 22, 31, 38 use the bare term "balance" without the "Wallet" qualifier. This is minor but should be standardised.
- **"plan expiry" vs. "plan expiry date" vs. "validity expiry":** FR-11 uses "validity expiry date"; FR-20 uses "plan expires"; the success metrics table uses "Plan Expiry Reminder". These describe the same concept. The glossary entry for "Plan" references "validity period" — recommend standardising to "validity expiry date" across all FRs.

---

### 16. UJ References in FRs

**Rating: PARTIAL**

The PRD does not use a formal "realizes UJ-X" inline tag convention in FR bodies. Given the size of this PRD (77 FRs across 14 feature groups), adding `realizes UJ-X` inline annotations would significantly improve traceability — particularly for engineering teams implementing UJ-3 (chatbot flow) and UJ-5 (upsell flow), which span many FRs across different sections.

**Recommendation:** Add `[Realizes: UJ-X]` notation to the FRs that are primary drivers of each UJ. At minimum:
- UJ-3: FR-29, FR-30, FR-34, FR-35
- UJ-4: FR-61, FR-62
- UJ-5: FR-48, FR-49, FR-50, FR-51

This is not a blocking issue but will prevent UJ coverage from drifting as FRs are revised during implementation.

---

## Summary of Findings by Severity

### Critical (Blocking for engineering handoff)

1. **FR-66 consequences are not testable** — incomplete sentence fragments, undefined "auth alert", no observable system behavior specified. A QA engineer cannot write a test case for this FR as written.

### High (Should be resolved before sprint planning)

2. **FR gap: false positive path in Fraud Case Queue** — UJ-4 describes an analyst clearing a case; no FR covers the false positive marking and audit of analyst overrides.
3. **Three glossary terms missing** — Rule Induction Agent, Root Cause Analysis Agent, dead-letter mechanism. The Rule Induction Agent omission is highest-risk since it is a named agent with its own FR (FR-49) and no glossary entry.

### Medium (Resolve in next PRD revision)

4. **No chatbot response latency NFR** — subscriber-facing latency for LLM-powered chatbot responses is unspecified, creating architecture sizing ambiguity.
5. **No concurrent session/load NFR** for web-facing tiers — the CDR pipeline has throughput targets; the web tier does not.
6. **FR-51 consequence is vague** — "optimal outreach timing" is not measurable or testable.
7. **FR-75 consequence is vague** — "structured root cause analysis" has no defined output schema.
8. **A-4 and A-10 are duplicate assumptions** — merge to avoid drift.

### Low (Polish before v1.0 release)

9. **"Wallet Balance" vs. "balance" inconsistency** across ~5 FRs.
10. **FR-31 names LangFuse** as an implementation tool within a functional consequence — should be removed; FR-72 covers LangFuse already.
11. **FR-46 names "materialised database view"** — implementation-prescriptive; should be architecture-deferred.
12. **No `realizes UJ-X` inline annotation** on FRs — reduces downstream traceability.
13. **UJ-4 and UJ-5 personas unnamed** — minor stylistic inconsistency.
14. **Vision references 100K CDR/sec** without qualifying it as Target State — may be read as an MVP launch commitment.

---

## Recommended Actions Before Engineering Handoff

| Priority | Action | Affected Section |
|---|---|---|
| P0 | Rewrite FR-66 consequences with observable, testable outcomes | §1.5.11 |
| P0 | Add FR or extend FR-54 for false positive analyst override path | §1.5.8 |
| P1 | Add Rule Induction Agent and Root Cause Analysis Agent to Glossary | §1.4 |
| P1 | Add chatbot P95 response latency NFR | §1.9 or FR-22 |
| P1 | Add concurrent session target for web-facing tiers | §1.9 |
| P2 | Tighten FR-51 and FR-75 consequences | §1.5.7, §1.5.14 |
| P2 | Merge A-4 and A-10 | §1.10 |
| P3 | Standardise "Wallet Balance" vs. "balance" | Multiple FRs |
| P3 | Remove LangFuse reference from FR-31 | §1.5.5 |
| P3 | Add `realizes UJ-X` annotations to key FRs | Multiple FRs |
