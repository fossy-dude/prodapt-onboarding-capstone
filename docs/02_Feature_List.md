---

# AI-Powered Prepaid Billing System — Feature Definitions

---

# 1. User: Subscriber

## 1.1. P0 — Account & Identity

- **Account Registration** — Create subscriber account via online sign-up form; receive `Subscriber Registration ID` pre-SIM activation
- **SIM Activation Flow** — Step-by-step order fulfilment journey on UI;
	- **TRAI CAF Verification** — Customer Acquisition Form digital submission + audit trail
- **Login & Auth** — Login via Registration ID (pre-activation) and MSISDN/credentials (post-activation)
	- **OTP Enforcement** — Step-up mobile OTP based login (using MSISDN)
		- For pre-registration users, OTP will be sent to the alternate mobile number provided during registration
- **Profile Management** — View/edit personal details, saved addresses, KYC status
- **Saved Payment Methods** — Store/manage credit card, UPI ID, net banking, mobile wallet details
- **KYC Status Visibility** — Display KYC state: `verified | pending | rejected`

---

## 1.2. P0 — Balance & Usage

- **Real-Time Balance Display** — Show current prepaid wallet balance (INR), updated after every CDR deduction
- **Transaction History** — Full ledger of charges, recharges, refunds with timestamp and CDR reference
- **Usage Breakdown** — Per-type consumption view: voice (min), data (MB/GB), SMS (count), roaming
- **Plan Details View** — Active plan name, validity expiry, bundled quotas and remaining allowances

---

## 1.3. P0 — Recharge & Payments

- **Plan Catalogue Browse** — View all active prepaid plans (daily/weekly/monthly), with data/voice/SMS bundles and pricing
- **Recharge Purchase** — Select plan → pay via saved/new method → activate on account
- **Multi-Gateway Payment** —
	- Support credit card, net banking, UPI, mobile wallets (India-specific: UPI, IMPS) - Simulated for now
- **Recharge Confirmation Notification** — SMS + push on successful recharge
- **Invoice / Receipt Generation** — Downloadable PDF receipt per recharge transaction
- **Refund Workflow** — Initiate/track refund for failed recharge; notification on refund completion (Dummy page only showing failed transactions. Implementation of refund flow not part of scope)
- **Idempotent Recharge Guard** — Prevent double-charging on retry/network failure

---

## 1.4. P0 — Notifications

- **Low Balance Alert** — SMS + push when balance drops below threshold
- **Balance Depletion Alert** — Notification on zero/near-zero balance
- **Plan Expiry Reminder** — Notify N days before plan expiry
- **Contextual Top-Up Nudge** — Trigger recharge recommendation (e.g., data at <10%) via SMS

---

## 1.5. P1 — Self-Care Chatbot

- **Balance Inquiry** — Query current wallet balance and quota remaining via chat
- **Plan Query** — Ask about active plan, expiry, features
- **Recharge Assistance** — Guided recharge via chat with tool-calling to payment flow
- **Multi-Turn Session Memory** — Maintain context across conversation turns within session
- **RAG FAQ Assistant** — Answer general telecom FAQs + plan/billing queries from knowledge base
- **Input Validation Guardrails** — Reject malformed/suspicious chatbot inputs before processing
- **Customer support tickets** - View previously raised support tickets
- **Subscriber Support Agent**: Multi-agent orchestration with Agent to Agent communication
	- **Rating Agent Integration** — Support agent queries rating agent to explain charge breakdown
	- **Disputed Transaction Workflow** — Subscriber raises billing dispute; Create support ticket (with sensible pre-filled details) for same and share ticket id. Allow user to also get status of support tickets
	- **Balance Management Agent** — Support agent queries balance agent for wallet-related queries
	- **Plan Recommendation Tool** — Hybrid search: plan attributes + semantic retrieval + usage signals
	- **Conclusion Agent** - For storing learnings, user feedback (self-learning). Also Triggering the notification agent with conversation summary
	- **Feedback Loop** — Log plan recommendation outcomes to refine future suggestions
- **Notification Agent** - Uses A2A protocol. Decides if, when and how to send notifications to customer based on the type of query being raised at the end of a session (based on the conversation summary)
- **Rate Limiting / Throttling** — API + USSD + chatbot request rate limits per subscriber

---

## 1.6. P1 — USSD Interface

- **USSD Session Handling** — Receive callbacks: `{msisdn, button_pressed, session_id}`; respond with text menu (numerical bulleted options or final text)
- **Balance Check via USSD** — Menu option to fetch and display balance
- **Plan Info via USSD** — Menu option to view active plan details
- **Recharge via USSD** — Initiate recharge workflow through USSD menu
- **Notification Opt-in/out via USSD** — Manage alert preferences

---

# 2. User: Operations & Marketing Teams

## 2.1. P0 — Inventory & Provisioning

- **Plan Stock Dashboard** — Real-time subscriber counts per plan
- **Order Fulfilment Status View** — Live view of subscriber orders across fulfilment states (created → KYC → activated)
- **Subscriber Growth Forecast** — 3-month projection of activations/churn using time-series ML
- **Plan Popularity Forecast** — Demand forecasting per plan for marketing targeting

---

## 2.2. P2 — Observability

- **CDR Processing Monitor** — Structured CDR log viewer; processing latency, error rate
- **Charging Pipeline Health** — P95 latency tracking for balance deduction (<200ms SLA)
- **Notification Delivery Status** — Delivery success/failure tracking per alert type

---

## 2.3. P2 — Upselling Strategy Design (LLM Segmentation)

- **Target Base Builder** — Define a candidate pool by filtering on pre-defined KPIs (KPI set TBD); supports composable filter criteria
- **Pool Preview & Stats** — Show a sample customer table plus pool-level statistics (total count, KPI distributions); cap the LLM-discovery sample at <100 customers for MVP token control
- **LLM Per-Customer Labelling** — Assign a descriptive segment label to each of the (≤100) sampled customers from pre-aggregated feature vectors (token-optimised: summarised CDR features, not raw CDRs)
- **Rule Induction Agent** — Generalise the per-customer labels into common, interpretable segment rules (KPI predicates) per label; persist rules to DB for reuse
- **Segment Classification at Scale** — Apply saved rules to classify the larger filtered base deterministically; show per-segment statistics (counts, KPI averages, distribution across segments)
- **Upsell Strategy Recommendations** — Agent generates a textual upsell strategy per segment: when to reach out and what the segment is interested in (no catalogue-plan mapping for MVP)
- **Strategy Feedback Loop** — Log recommendation outcomes to refine future segmentation/strategy (reuse Conclusion Agent)

---

# 3. User: Fraud Management Team

## 3.1. P1 — Fraud & Anomaly Dashboard

- **Real-Time Anomaly Feed** — Live view of flagged CDR events: high voice-call rates, roaming abuse, SIM swap signals
- **Fraud Case Queue** — Alerts routed to fraud supervisor after agent analysis; per-case status tracking
- **SIM Swap Fraud Alerts** — Dedicated detection + alert for account takeover patterns
- **Suspicious Recharge Pattern Alerts** — Flag abnormal recharge frequency/amounts

---

# 4. System / Platform (Cross-Cutting)

## 4.1. P0 — Data Pipeline

- **CDR Ingestion** — Real-time streaming pipeline; CDR as system input (post-rating/charging, per assumption)
- **Balance Deduction Engine** — Deterministic, idempotent deduction from subscriber wallet on CDR receipt
- **Audit Log Trail** — Immutable log of all billing/auth/admin actions for regulatory audit

## 4.2. P0 — Fraud Detection Agent

- **Rule-Based Pre-Screening** — Fast deterministic filter on CDR events for anomaly signals
- **Agent Escalation on Risk** — Route flagged CDR to LLM agent for deeper analysis
- **Notification Tool Call** — Agent triggers alert to fraud supervisor on confirmed risk
- **Future Hook: ML Classifier** — Architecture supports plugging in ML-based scoring alongside rules

## 4.3. P0 — Security & Compliance

- **PII Encryption** — Encrypt MSISDN, name, address, financial data at rest and in transit
- **Payment Data PCI-DSS** — Tokenise card data; no raw card storage
- **TRAI Compliance** — Adhere to India telecom regulations for billing and data handling
- **Account Takeover Prevention** — Auth hardening; SIM swap detection integrated with login flow

# 5. Development Requirements

## 5.1. P0 — Data Pipeline

- **Synthetic Dataset** — Generate: 1,000+ plans, 300K subscribers, 5M CDRs with all required schema fields

## 5.2. P2 — Evaluation, Observability & Quality

- **Observability** - LangFuse integration for observability & evaluation of agentic workflows. Can use DeepEval and other mechanism for Evals
- **LLM-as-Judge** — Validate plan recommendation relevance and chatbot response quality
- **DeepEval Integration** — Chatbot quality metrics; recharge conversion and churn prediction accuracy. Offline and Online evals (sampled) for live production use-cases
- **Root Cause Analysis Agent** — Collaborative agent analysis of billing discrepancies and failed recharges
- **Token Optimisation** — Efficient LLM usage for large-scale CDR analysis and subscriber segmentation

## 5.3. P1 — Deliverables

- **Target State Architecture** — Full-scale production design meeting all functional + NFRs
- **MVP Architecture** — PoC scoped for limited infra; clear production migration path
- **Architecture Diagram** — JPEG/PDF; label CDR flow, rating, balance, AI/ML, APIs, datastores
- **Design** — Document articulating the system design decisions and trade-offs made (e.g., choice of real-time streaming platform, message broker for CDR ingestion, caching strategy for balance lookup, AI model selection for forecasting, synchronous vs. asynchronous charging).

## 5.4. Simulator Tool

- Simulate CDR generation - show end to end logs on screen for the trace across each service
- Notification portal -
	- watch all the notifications sent to users live (SMS) including OTP msgs
- Activation of SIM cards: Simulate order flow and progress status to `Activated (Ready to Use)` on click for a given MSISDN

## 5.5. Security and Governance

- **Data Localisation** — Subscriber data stored within India borders (TRAI mandate)
- **Consent Management** — Capture + store explicit consent for data usage, marketing comms #future_not_mvp
- **Session Timeout + Revocation** — Force-expire sessions; revoke tokens on fraud identification #future_not_mvp

## 5.6. Ops

- **Health Check Endpoints** — `/health` + `/ready` per microservice
- **Distributed Tracing** —
	- Trace ID propagation across CDR → rating → balance → notification
	- JWT based auth and session management for users in the 4 dashboards

## 5.7. Presentation

- **Next Steps** - Enhancement pipeline post delivery of MVP

