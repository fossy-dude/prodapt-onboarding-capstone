---
title: AI-Powered Prepaid Billing System
status: final
created: 2026-06-18
updated: 2026-06-18
---

# 1. PRD: AI-Powered Prepaid Billing System

## 1.1. Document Purpose

This PRD defines the requirements for an AI-powered prepaid billing platform serving an Indian telecom operator. It is structured for product, engineering, UX, and architecture stakeholders who will deliver the MVP. Requirements are grouped by user type; functional requirements (FRs) are numbered globally for stable downstream reference. Items deferred post-MVP are tagged `[NON-GOAL for MVP]`. The companion architecture document (to be authored separately) will address Target State vs MVP infrastructure design decisions, model selection, streaming platform choice, and production migration path.

---

## 1.2. Vision

Indian prepaid telecom operators run high-volume billing platforms processing millions of Call Detail Records (CDRs) daily, yet the billing lifecycle remains largely rule-based and siloed. Charging, fraud detection, subscriber notifications, and customer support operate independently — creating revenue leakage, slow fraud response, high churn, and a poor subscriber self-care experience.

This platform embeds AI and Generative AI across the entire prepaid billing lifecycle. Subscribers self-serve through an intelligent chatbot backed by a multi-agent system. Operations and marketing teams access real-time AI-driven forecasts and LLM-powered subscriber segmentation. A fraud management team receives automated, AI-escalated alerts. All of this sits on a real-time CDR ingestion pipeline with deterministic balance management and an agentic fraud detection layer — designed for 100,000 CDR events per second at the target state.

The outcome: maximise ARPU, minimise churn, and reduce operational cost through intelligent decisioning embedded at every step of the billing lifecycle — without sacrificing the sub-200ms latency the charging layer demands.

---

## 1.3. Target Users

### 1.3.1. Jobs To Be Done

**Subscriber (end customer)**

- Check my balance and usage without calling support or visiting a store
- Recharge my prepaid plan quickly and without double-charging
- Understand why my balance changed after a call or data session
- Get a plan recommendation that actually fits my usage pattern
- Raise and track a billing dispute without waiting on hold
- Activate my SIM and verify my identity digitally (no paper CAF)

**Operations & Marketing Team**

- See how many subscribers are on each plan in real time
- Forecast subscriber growth and plan demand to design targeted offers proactively
- Identify subscriber segments for upselling without a data science team running custom queries
- Track order fulfilment health across the activation pipeline

**Fraud Management Team**

- See flagged CDR events in real time without manually polling logs
- Get AI-escalated fraud case analysis, not raw rule-based alerts alone
- Act on SIM swap and suspicious recharge signals before account takeover completes

**Platform / Engineering**

- Ingest CDRs at scale with deterministic, idempotent balance deductions
- Propagate distributed trace IDs across the full CDR → balance → fraud → notification pipeline
- Meet TRAI and PCI-DSS compliance requirements for data localisation, PII encryption, and payment tokenisation

### 1.3.2. Non-Users (v1)

- Postpaid subscribers — prepaid only
- Enterprise / corporate accounts
- Third-party MVNO operators (platform is single-operator)
- International roaming-only users (Indian operator, Indian subscribers only)

### 1.3.3. Key User Journeys

- **UJ-1. Priya activates her SIM after online sign-up.**
  Priya, a new subscriber, submits an online sign-up form and receives a `Subscriber Registration ID`. She logs in with the Registration ID, submits her TRAI Customer Acquisition Form digitally, and tracks her order fulfilment status through the UI as it progresses from `Created → KYC → Activated`. On activation, her MSISDN is bound to her account and she can log in with MSISDN + OTP.

- **UJ-2. Rohan checks his balance and recharges via the subscriber portal.**
  Rohan, an active prepaid subscriber, logs in with MSISDN + OTP. He sees his real-time INR wallet balance, current plan details, and data/voice/SMS consumption. He browses the plan catalogue, selects a monthly plan, pays via simulated UPI, receives an in-app confirmation and SMS notification, and downloads a PDF receipt. His balance updates immediately.

- **UJ-3. Anjali queries her chatbot about a sudden balance drop.**
  Anjali opens the self-care chatbot. She asks why her balance dropped by ₹30 after a short call. The Support Agent queries the Rating Agent, which returns the charge breakdown (rate per minute × duration + applicable taxes). The Support Agent explains the breakdown in plain language. Anjali disputes the charge; the chatbot auto-creates a support ticket with pre-filled details and surfaces the ticket ID. At session end, the Conclusion Agent logs the interaction and triggers the Notification Agent, which sends Anjali a summary SMS with her ticket ID.

- **UJ-4. A fraud analyst reviews a real-time SIM swap alert.**
  A CDR event arrives that triggers the rule-based pre-screening layer for SIM swap signals. The Fraud Detection Agent performs deeper LLM-powered analysis and confirms elevated risk. The fraud analyst sees the case appear in the Fraud Case Queue with agent-generated analysis. The analyst reviews and escalates or clears the case. A notification is sent to the fraud supervisor.

- **UJ-5. A marketing manager designs a targeted upsell campaign.**
  The marketing manager filters the subscriber base by KPI criteria (e.g. high data users approaching plan expiry) using the Target Base Builder. The system samples up to 100 subscribers and sends their pre-aggregated feature vectors to an LLM for per-customer segment labelling. A Rule Induction Agent generalises the labels into interpretable rules, which are saved to the database. The full filtered base is then classified deterministically. The manager reviews per-segment upsell strategy recommendations generated by an LLM and logs the campaign outcome for future feedback loop refinement.

---

## 1.4. Glossary

- **CDR (Call Detail Record)** — A structured event record produced after a subscriber voice, data, or SMS session is rated and charged by the upstream telecom operator. CDR is the entry point of this system's real-time pipeline. All pre-CDR charging and rating steps are out of scope.
- **MSISDN** — Mobile Station International Subscriber Directory Number; the subscriber's phone number, used as the primary post-activation identifier.
- **Subscriber Registration ID** — A unique identifier issued on sign-up form submission, used for pre-activation login before an MSISDN is assigned.
- **Wallet Balance** — The subscriber's current prepaid monetary balance in INR, from which charges are deducted on each CDR receipt.
- **Plan** — A prepaid tariff product with defined data, voice, and SMS bundles, validity period, and pricing. Plans are either `unlimited` (capped data/voice allowances) or `talktime balance` type (per-second/per-MB deduction from wallet).
- **Talktime Balance Plan** — A plan type where usage charges are deducted directly from the subscriber's INR wallet at a per-unit rate rather than from a fixed bundle quota.
- **CAF (Customer Acquisition Form)** — TRAI-mandated KYC form required for SIM activation; submitted digitally in this system.
- **KYC** — Know Your Customer; the identity verification state of a subscriber account. States: `verified | pending | rejected`.
- **Order Fulfilment** — The end-to-end lifecycle of a subscriber's SIM activation: `Created → KYC → Activated`.
- **CDR Ingestion Pipeline** — The real-time streaming infrastructure that receives CDR events and triggers balance deduction, fraud screening, and notifications.
- **Balance Deduction Engine** — The deterministic, idempotent component that deducts charges from a subscriber's Wallet Balance upon CDR receipt.
- **Fraud Detection Agent** — The LLM-powered agent that performs deeper risk analysis on CDR events flagged by the rule-based pre-screening layer.
- **Support Agent** — The primary conversational AI agent in the self-care chatbot, orchestrating child agents (Rating Agent, Balance Management Agent) to resolve subscriber queries.
- **Rating Agent** — A sub-agent that explains the charge breakdown for a given CDR event, accessible via the Support Agent.
- **Balance Management Agent** — A sub-agent that handles wallet-related queries, accessible via the Support Agent.
- **Conclusion Agent** — A sub-agent that stores interaction learnings, captures user feedback, and triggers the Notification Agent with a conversation summary at session end.
- **Notification Agent** — An agent that uses the A2A protocol to decide if, when, and how to send subscriber notifications based on session context.
- **A2A (Agent-to-Agent) Protocol** — The communication protocol used between agents in the multi-agent orchestration framework.
- **RAG (Retrieval-Augmented Generation)** — The mechanism by which the chatbot retrieves relevant FAQ and plan/billing content from a knowledge base before generating responses.
- **ARPU** — Average Revenue Per User; the primary business metric this platform is designed to maximise.
- **USSD** — Unstructured Supplementary Service Data; a GSM protocol allowing text-based menu interactions from a subscriber's handset. This system receives REST API callbacks from the telecom operator's USSD gateway.
- **Notification Portal** — A real-time dashboard that surfaces all simulated SMS and push notifications sent to subscribers, used for development and demonstration purposes.
- **CDR Simulator** — A standalone developer tool that generates synthetic CDR events and shows end-to-end trace logs across each service.
- **LLM-as-Judge** — An evaluation mechanism where an LLM scores the quality of chatbot responses or plan recommendations against defined rubrics.
- **DeepEval** — An evaluation framework used for offline and sampled online quality assessment of chatbot and ML components.
- **LangFuse** — An observability platform used to trace and evaluate agentic workflow execution.
- **PII** — Personally Identifiable Information; includes MSISDN, name, address, and financial data.
- **PCI-DSS** — Payment Card Industry Data Security Standard; governs secure handling of payment card data.
- **TRAI** — Telecom Regulatory Authority of India; the regulatory body whose mandates govern billing, data localisation, and customer identity verification.
- **Rule Induction Agent** — An LLM-powered agent that generalises per-customer segment labels (produced by LLM labelling) into interpretable KPI-predicate rules, which are persisted to the database for reuse in deterministic classification of the full subscriber pool.
- **Root Cause Analysis Agent** — An LLM-powered agent that assists engineering teams in diagnosing billing discrepancies and failed recharges, using audit logs, CDR data, and a synthetic Standard Operating Procedure knowledge base as grounding.
- **Dead-Letter Queue** — A secondary message queue that captures CDR events that failed to process successfully, preventing data loss and enabling reprocessing after root cause remediation.

---

## 1.5. Features

### 1.5.1. Account & Identity

**Description:** Subscriber account lifecycle from initial sign-up through SIM activation, authentication, profile management, and KYC status visibility. Pre-activation users authenticate with a Subscriber Registration ID; post-activation users authenticate with MSISDN + OTP. The SIM activation order fulfilment flow is simulated on the UI rather than integrated with real provisioning infrastructure. TRAI CAF is submitted digitally and an audit trail is stored; physical document handling is out of scope.

**Functional Requirements:**

#### FR-1: Subscriber Account Registration

A new subscriber can submit an online sign-up form and receive a unique Subscriber Registration ID before SIM activation.

**Consequences (testable):**

- On successful form submission, the system generates and returns a unique `Subscriber Registration ID`.
- The subscriber can log in using the Registration ID prior to SIM activation.
- Duplicate submissions for the same identity are rejected with an informative error.

#### FR-2: SIM Activation Order Fulfilment (Simulated)

A subscriber can track their SIM activation progress through a step-by-step UI journey simulating the order fulfilment lifecycle.

**Consequences (testable):**

- Order fulfilment states displayed: `Created → KYC → Activated`.
- On operator/admin action, status progresses to `Activated (Ready to Use)` for a given MSISDN.
- On activation, the MSISDN is bound to the subscriber account and MSISDN-based login becomes available.

#### FR-3: TRAI CAF Digital Submission

A subscriber can submit the TRAI Customer Acquisition Form digitally as part of the SIM activation flow, with an immutable audit trail.

**Consequences (testable):**

- CAF submission is stored with a timestamp and linked to the subscriber account.
- The audit trail entry is immutable and cannot be modified post-submission.

#### FR-4: Login and Authentication

A subscriber can log in using Subscriber Registration ID (pre-activation) or MSISDN + credentials (post-activation), with step-up OTP enforcement.

**Consequences (testable):**

- Pre-activation: login succeeds with valid Registration ID + OTP sent to the alternate mobile number provided during registration.
- Post-activation: login succeeds with valid MSISDN + OTP sent to the MSISDN.
- Login fails with invalid credentials and returns a non-leaking error message.
- OTP is required for every login session (step-up, not optional).

#### FR-5: Profile Management

An authenticated subscriber can view and edit personal details, saved addresses, and KYC status.

**Consequences (testable):**

- Subscriber can update name, address, and contact details; changes are persisted.
- KYC status (`verified | pending | rejected`) is displayed read-only; updates are system-driven.

#### FR-6: Saved Payment Methods Management

An authenticated subscriber can store and manage payment methods: credit card (tokenised), UPI ID, net banking, and mobile wallet details.

**Consequences (testable):**

- Payment methods are stored; raw card numbers are never persisted (PCI-DSS tokenisation applies).
- Subscriber can add, view, and delete saved payment methods.

#### FR-7: KYC Status Visibility

A subscriber can see their current KYC state (`verified | pending | rejected`) at any time from their profile.

**Consequences (testable):**

- KYC state is always current and reflects the latest verification result.
- A subscriber in `rejected` state sees a reason message and next-step guidance.

---

### 1.5.2. Balance & Usage

**Description:** Real-time visibility into subscriber Wallet Balance, transaction history, usage breakdown by type (voice, data, SMS, roaming), and active plan details. Balance is updated after every CDR deduction — latency between CDR processing and balance display must be imperceptible to the subscriber.

**Functional Requirements:**

#### FR-8: Real-Time Balance Display

An authenticated subscriber can view their current prepaid Wallet Balance in INR, updated after every CDR deduction.

**Consequences (testable):**

- Balance displayed reflects the most recent CDR deduction within the session.
- Balance is denominated in INR with two decimal precision.
- A zero-balance state is displayed distinctively with a prompt to recharge.

#### FR-9: Transaction History

An authenticated subscriber can view a full ledger of charges, recharges, and refunds with timestamp and CDR reference.

**Consequences (testable):**

- Each transaction entry shows: type (charge/recharge/refund), amount (INR), timestamp, and CDR reference ID where applicable.
- History is paginated and sorted by most recent first.
- Entries are immutable; no editing of transaction records.

#### FR-10: Usage Breakdown

An authenticated subscriber can view per-type consumption for the current plan period: voice (minutes), data (MB/GB), SMS (count), and roaming.

**Consequences (testable):**

- Usage figures are current as of the most recently processed CDR.
- Each usage type shows consumed vs. total bundle allowance (or "unlimited" for unlimited plans).
- Roaming usage is displayed separately from domestic usage.

#### FR-11: Plan Details View

An authenticated subscriber can view their active plan name, validity expiry date, bundled quotas, and remaining allowances.

**Consequences (testable):**

- Plan details reflect the currently active plan at the time of viewing.
- Validity expiry is shown in human-readable date/time format (IST).
- Remaining allowances are updated after each CDR deduction.

---

### 1.5.3. Recharge & Payments

**Description:** Plan discovery, purchase, and payment processing for the subscriber. Payments are simulated for MVP — no real payment gateway integration. Recharge is idempotent and guarded against double-charging on retry. Refund implementation is limited to a dummy page showing failed transactions; actual refund processing is out of scope for MVP.

**Functional Requirements:**

#### FR-12: Plan Catalogue Browse

An authenticated subscriber can browse all active prepaid plans with data/voice/SMS bundles, validity, and pricing.

**Consequences (testable):**

- Plans are filterable and sortable (e.g. by validity period: daily/weekly/monthly, by price).
- Each plan card displays: name, data allowance, voice allowance, SMS count, validity, and price (INR).
- Only currently active plans are shown; expired or withdrawn plans are hidden.

#### FR-13: Recharge Purchase

An authenticated subscriber can select a plan, pay via a saved or new payment method, and activate the plan on their account.

**Consequences (testable):**

- Plan activates on successful payment and replaces or stacks on the current plan per defined plan rules.
- A recharge confirmation notification (SMS + push) is sent on success.
- Failed payments surface an error with a retry option.

#### FR-14: Multi-Gateway Payment (Simulated)

The system accepts payment method selection across credit card, net banking, UPI, and mobile wallets (India-specific: UPI, IMPS). All payments are simulated for MVP — no real transaction is executed.

**Consequences (testable):**

- Selecting any supported payment method and submitting triggers a simulated success response.
- The simulation does not call any real payment gateway.
- Payment tokenisation logic is implemented for card methods even in simulation (PCI-DSS readiness).

#### FR-15: Invoice / Receipt Generation

A subscriber receives a downloadable PDF receipt for each completed recharge transaction.

**Consequences (testable):**

- PDF receipt is generated on recharge success and accessible from transaction history.
- Receipt includes: subscriber name, MSISDN, plan name, amount paid, payment method type (masked), timestamp, and transaction reference ID.

#### FR-16: Idempotent Recharge Guard

The system prevents double-charging when a recharge is retried due to network failure or client retry.

**Consequences (testable):**

- Duplicate recharge requests with the same idempotency key are detected and return the original successful response without re-processing.
- The subscriber's balance is debited/credited exactly once per intended transaction.

#### FR-17: Refund Workflow (Limited Scope)

A subscriber can view a list of failed recharge transactions. Actual refund processing is not implemented in MVP.

**Consequences (testable):**

- Failed transactions are listed with timestamp, amount attempted, and failure reason.
- No refund initiation or processing capability is available in MVP.

**Out of Scope:** Refund initiation, refund tracking, and refund completion notifications. [NON-GOAL for MVP]

---

### 1.5.4. Notifications

**Description:** Proactive subscriber notifications for balance and plan events, delivered via simulated SMS and push. All notification delivery is simulated — messages are stored to a database and surfaced live on the Notification Portal. No real SMS gateway is integrated in MVP. SMS and push notifications share the same simulated delivery mechanism (notification type used to disambiguate the 2 types).

**Functional Requirements:**

#### FR-18: Low Balance Alert

The system sends a simulated SMS and push notification when a subscriber's Wallet Balance drops below ₹10. The threshold is stored in a database configuration record; changing the record changes the threshold system-wide.

**Consequences (testable):**

- Notification is triggered within one CDR processing cycle after Wallet Balance crosses the ₹10 threshold.
- The threshold value is read from a database configuration record (not hardcoded).
- The notification message includes the current balance and a recharge prompt.

#### FR-19: Balance Depletion Alert

The system sends a simulated SMS and push notification when a subscriber's Wallet Balance reaches zero or near-zero.

**Consequences (testable):**

- Alert fires when balance ≤ ₹0.00.
- Alert is sent only once per depletion event (not repeatedly while balance remains at zero).

#### FR-20: Plan Expiry Reminder

The system sends a simulated SMS and push notification 3 days before a subscriber's active plan expires. The lead-time value is stored in a database configuration record.

**Consequences (testable):**

- Notification is sent exactly 3 days before plan expiry (configurable via database record).
- Notification includes the plan name, expiry date, and a recharge prompt.

#### FR-21: Contextual Top-Up Nudge

The system sends a simulated SMS notification when a subscriber's data allowance drops below 10% remaining.

**Consequences (testable):**

- Nudge fires when remaining data allowance crosses the 10% threshold during CDR processing.
- Message includes current remaining data and a suggested top-up or plan upgrade prompt.

---

### 1.5.5. Self-Care Chatbot

**Description:** A multi-agent conversational self-care interface accessed via the subscriber portal. The Support Agent is the primary conversational agent; it orchestrates child agents (Rating Agent, Balance Management Agent, Conclusion Agent, Notification Agent) via A2A communication to handle balance queries, charge explanations, billing disputes, plan recommendations, and FAQ answers. A RAG knowledge base powers general telecom FAQ and plan/billing queries. The chatbot maintains multi-turn session context. At session end, the Conclusion Agent stores learnings and triggers the Notification Agent to decide if a session-summary notification should be sent. The multi-agent framework uses LangGraph or equivalent for orchestration; specific framework is an architecture decision

**Functional Requirements:**

#### FR-22: Balance Inquiry via Chat

A subscriber can query their current Wallet Balance and remaining quota via the chatbot.

**Consequences (testable):**

- The Support Agent retrieves live balance and quota data and responds in natural language.
- Response is accurate to the most recently processed CDR.

#### FR-23: Plan Query via Chat

A subscriber can ask about their active plan, expiry date, and feature details via the chatbot.

**Consequences (testable):**

- The Support Agent returns accurate active plan details matching the Plan Details View (FR-11).

#### FR-24: Recharge Assistance via Chat

A subscriber can initiate and complete a recharge workflow through the chatbot via tool-calling to the payment flow.

**Consequences (testable):**

- The chatbot guides the subscriber through plan selection and payment initiation using tool calls.
- The chatbot confirms successful recharge and surfaces a receipt reference.

#### FR-25: Multi-Turn Session Memory

The chatbot maintains conversational context across all turns within a single session.

**Consequences (testable):**

- Follow-up questions referencing prior turns in the session are answered correctly without the subscriber re-supplying context.
- Session context is cleared on session end or timeout.

#### FR-26: RAG FAQ Assistant

The chatbot answers general telecom FAQs and plan/billing queries by retrieving from a structured knowledge base.

**Consequences (testable):**

- Queries about general telecom policies, network coverage, and plan FAQs return answers grounded in the knowledge base.
- Out-of-knowledge-base queries are acknowledged gracefully with a suggestion to contact support.

#### FR-27: Input Validation Guardrails

The chatbot rejects malformed, adversarial, or suspicious inputs before processing.

**Consequences (testable):**

- Prompt injection attempts, excessively long inputs, and structured malicious payloads are rejected with a sanitised error message.
- Legitimate edge-case inputs (e.g. mixed-language, typos) are processed without rejection.

#### FR-28: Customer Support Ticket Viewing

An authenticated subscriber can view their previously raised support tickets via the chatbot.

**Consequences (testable):**

- The subscriber can request a list of their open and closed tickets.
- Each ticket entry shows: ticket ID, subject, status, and creation timestamp.

#### FR-29: Rating Agent — Charge Breakdown Explanation

The Support Agent queries the Rating Agent to explain the charge breakdown for a specific CDR event when a subscriber disputes or queries a charge.

**Consequences (testable):**

- The Support Agent surfaces the charge breakdown (rate type, unit rate, duration/volume, total charge) in natural language.
- The Rating Agent is queried via A2A protocol.

#### FR-30: Disputed Transaction Workflow

A subscriber can raise a billing dispute via the chatbot, which auto-creates a support ticket with pre-filled details and provides the ticket ID.

**Consequences (testable):**

- A support ticket is created with pre-populated fields: subscriber MSISDN, disputed CDR reference, charge amount, and dispute reason from the conversation.
- The chatbot surfaces the ticket ID immediately.
- The subscriber can subsequently check the status of existing tickets via the chatbot.

#### FR-31: Balance Management Agent Integration

The Support Agent queries the Balance Management Agent for wallet-related queries, via A2A protocol.

**Consequences (testable):**

- Wallet-related responses are sourced from the Balance Management Agent, not hardcoded in the Support Agent.
- A2A communication between agents is traceable via LangFuse.

#### FR-32: Plan Recommendation Tool

The Support Agent offers a plan recommendation using a hybrid search combining plan attribute matching, semantic retrieval, and subscriber usage signals. The exact implementation of the hybrid search (embedding model, vector index type, attribute matching rules, usage signal source, and score fusion method) is TBD and will be specified in the architecture document.

**Consequences (testable):**

- Recommendations return 1–3 plans most relevant to the subscriber's current usage pattern.
- Recommendation rationale is surfaced to the subscriber in natural language.
- Recommendation outcomes are logged to the feedback loop (FR-33).

**[NOTE FOR ARCHITECTURE]:** Specify embedding model, vector index, attribute matching logic, subscriber usage signals source (CDR aggregates vs. live balance), and score fusion strategy for the hybrid search.

#### FR-33: Recommendation Feedback Loop

When a subscriber explicitly selects a recommended plan, the system logs the acceptance and responds with a message: "One of our agents will reach out to you to finalise your request shortly." Dismissals (no explicit action) are also logged.

**Consequences (testable):**

- Acceptance is triggered by an explicit subscriber action (button/selection), not inferred from recharge behaviour.
- On acceptance, the system responds with the defined handoff message and logs the outcome with status `accepted`.
- On session end without an explicit acceptance action, the recommendation is logged with status `dismissed`.
- Both accepted and dismissed outcomes are persisted to a feedback store accessible for future refinement.

#### FR-34: Conclusion Agent — Session Learning and Notification Trigger

At the end of each chatbot session, the Conclusion Agent stores interaction learnings and user feedback, and triggers the Notification Agent with a conversation summary.

**Consequences (testable):**

- Session learnings (query type, resolution, user sentiment signals) are persisted.
- The Notification Agent receives the conversation summary and independently decides whether and how to send a subscriber notification.

#### FR-35: Notification Agent — A2A Session-End Notification

The Notification Agent, upon receiving a conversation summary from the Conclusion Agent, decides whether, when, and how to send a notification to the subscriber.

**Consequences (testable):**

- Notification decisions are driven by query type and session outcome, not sent for every session indiscriminately.
- Notification is delivered via the simulated notification pipeline (Notification Portal).
- Agent decisions are traceable via LangFuse observability.

#### FR-36: Rate Limiting and Throttling

The system enforces a limit of 100 requests per minute (RPM) per subscriber across API, USSD, and chatbot channels.

**Consequences (testable):**

- Subscribers exceeding 100 RPM on any channel receive an HTTP 429 response (API/chatbot) or a rate-limit text message (USSD).
- The 100 RPM threshold is configurable via a database configuration record.

---

### 1.5.6. USSD Interface

**Description:** The system handles REST API callbacks from the telecom operator's USSD gateway when a subscriber interacts using a USSD shortcode. The system receives `{msisdn, button_pressed, session_id}` and responds with text menus or final messages. The system does not initiate USSD sessions. The telecom operator's USSD gateway handles the subscriber-facing GSM USSD session; this system only handles the REST callback.

**Functional Requirements:**

#### FR-37: USSD Session Callback Handling

The system receives USSD REST API callbacks from the telecom operator and responds with structured text menus.

**Consequences (testable):**

- The system accepts POST callbacks containing `{msisdn, button_pressed, session_id}`.
- Response is a structured text menu with numbered options or a terminal text response.
- Session state is maintained per `session_id` for multi-step USSD flows.

#### FR-38: Balance Check via USSD

A subscriber can check their current Wallet Balance via a USSD menu option.

**Consequences (testable):**

- The balance returned matches the real-time Wallet Balance (FR-8).

#### FR-39: Plan Info via USSD

A subscriber can view their active plan details via a USSD menu option.

**Consequences (testable):**

- Response includes plan name, validity expiry, and remaining data/voice/SMS allowances.

#### FR-40: Recharge Initiation via USSD

A subscriber can initiate a recharge workflow through the USSD menu.

**Consequences (testable):**

- The USSD flow guides the subscriber through plan selection.
- Full payment completion via USSD is not expected; USSD initiates the intent, actual payment may redirect to the web flow or is simulated.

#### FR-41: Notification Opt-in/out via USSD

A subscriber can manage notification alert preferences via a USSD menu option.

**Consequences (testable):**

- The subscriber can opt in or out of specific notification types (low balance, plan expiry, top-up nudge).
- Preference changes take effect for the next notification cycle.

---

### 1.5.7. Operations & Marketing Dashboard

**Description:** A web dashboard for operations and marketing team members providing real-time plan stock visibility, order fulfilment status, subscriber growth and plan demand forecasts (via time-series ML), and LLM-powered subscriber segmentation for upsell strategy design. Dashboards are distinct, role-separated UIs; JWT-based auth differentiates user roles across all 4 dashboards.

**Functional Requirements:**

#### FR-42: Plan Stock Dashboard

An operations team member can view real-time subscriber counts per active plan.

**Consequences (testable):**

- Subscriber count per plan is accurate as of the most recent account state.
- Data is displayed in a sortable table or visual chart.

#### FR-43: Order Fulfilment Status View

An operations team member can view a live view of subscriber orders across all fulfilment states.

**Consequences (testable):**

- Orders are grouped by state: `Created | KYC | Activated`.
- Count per state is visible at a glance; individual order drill-down is available.

#### FR-44: Subscriber Growth Forecast

The system provides a 3-month projection of subscriber activations and churn using a time-series ML model.

**Consequences (testable):**

- Forecast is visualised as a time-series chart with confidence intervals.
- Forecast refreshes on a configurable schedule (e.g. daily).
- Model inputs: historical activation and churn data from the subscriber dataset.

#### FR-45: Plan Popularity Forecast

The system provides demand forecasting per plan for marketing targeting.

**Consequences (testable):**

- Forecast shows projected subscriber uptake per plan over the next 30–90 days.
- Marketing team members can use forecast data to design targeted offers.

#### FR-46: Target Base Builder (Upsell Segmentation)

A marketing team member can define a subscriber candidate pool by applying composable filter criteria on KPIs sourced from the columns of a materialised database view. The available KPIs are data-driven — derived from the view schema — and are not hardcoded in the UI. Metadata records can help inform what the columns mean and how they should be labelled to the user.

**Consequences (testable):**

- Available filter dimensions are dynamically sourced from the columns of the designated materialised subscriber KPI view.
- Filter criteria support AND/OR composition across the available KPI columns.
- Filtered pool count is shown before proceeding to LLM labelling.

#### FR-47: Pool Preview and Statistics

The system shows a sample subscriber table and pool-level statistics for the filtered candidate pool.

**Consequences (testable):**

- Sample shows up to the first N subscribers from the filtered pool (configurable, default 10).
- Pool statistics include: total count, KPI distributions (min, max, mean) across selected KPIs.
- The LLM-discovery sample is capped at 100 subscribers for MVP token control.

#### FR-48: LLM Per-Customer Segment Labelling

The system sends pre-aggregated feature vectors for up to 100 sampled subscribers to an LLM for descriptive segment label assignment.

**Consequences (testable):**

- Inputs are pre-aggregated CDR feature summaries, not raw CDRs (token-optimised).
- Each sampled subscriber receives exactly one segment label.
- LLM usage for this operation is tracked via LangFuse.

#### FR-49: Rule Induction Agent

A Rule Induction Agent generalises per-customer LLM labels into interpretable KPI-predicate segment rules, which are persisted to the database for reuse.

**Consequences (testable):**

- Generated rules are human-readable KPI predicates (e.g. "data usage > 5GB AND balance < ₹50").
- Rules are stored and retrievable for applying to future subscriber pools.

#### FR-50: Segment Classification at Scale

The system applies saved segment rules to classify the full filtered subscriber base deterministically, with per-segment statistics.

**Consequences (testable):**

- Classification applies saved rules without invoking the LLM again (deterministic).
- Output shows: count per segment, KPI averages per segment, and distribution across segments.

#### FR-51: Upsell Strategy Recommendations

An LLM agent generates a textual upsell strategy per identified subscriber segment.

**Consequences (testable):**

- Strategy output covers: optimal outreach timing and what the segment is likely interested in.
- No catalogue-plan mapping is generated in MVP — strategy is descriptive only. [NON-GOAL for MVP]
- Strategy recommendation outcomes are logged to a dedicated upsell feedback store for future refinement. The Conclusion Agent (chatbot session agent) is not involved in the upsell feedback loop.

#### FR-52: Ops Dashboard Observability

An operations team member can monitor CDR processing health, charging pipeline latency, and notification delivery status.

**Consequences (testable):**

- CDR Processing Monitor shows: processing latency (P95, P99), error rate, and event count per time window.
- Charging Pipeline Health shows P95 balance deduction latency vs. the 200ms SLA, with a breach indicator.
- Notification Delivery Status shows success/failure counts per notification type.

---

### 1.5.8. Fraud Management Dashboard

**Description:** A real-time fraud operations dashboard for the fraud management team. The Fraud Detection Agent performs LLM-powered analysis on CDR events that pass the rule-based pre-screening layer and routes confirmed risk cases to the fraud supervisor queue. Fraud detection pipeline is synchronous with the CDR processing flow — rule-based screening first, agent escalation second. ML classifier integration is an architecture hook for future releases.

**Functional Requirements:**

#### FR-53: Real-Time Anomaly Feed

A fraud analyst can view a live feed of CDR events flagged by the rule-based pre-screening layer.

**Consequences (testable):**

- Feed updates in near-real-time as CDR events are screened.
- Each entry shows: subscriber MSISDN, CDR reference, flag type, timestamp, and rule triggered.
- Flag types include: high voice-call rate, roaming abuse, SIM swap signal, suspicious recharge pattern.

#### FR-54: Fraud Case Queue

Confirmed risk cases escalated by the Fraud Detection Agent appear in a case queue for fraud supervisors.

**Consequences (testable):**

- Each case entry shows: subscriber MSISDN, case ID, agent analysis summary, risk level, and status.
- Case status transitions: `Open → Under Review → Resolved`.
- The fraud supervisor can update case status and add notes.

#### FR-55: SIM Swap Fraud Alerts

The system detects SIM swap account takeover patterns and surfaces dedicated alerts.

**Consequences (testable):**

- SIM swap signals are detected in the rule-based pre-screening layer and escalated to the Fraud Detection Agent.
- Confirmed SIM swap cases appear in the Fraud Case Queue with the flag type `SIM Swap`.
- SIM swap detection uses a defined rule set (e.g. MSISDN used from two geographically distant locations within a short time window); the exact rule parameters are an implementation decision.

#### FR-56: Suspicious Recharge Pattern Alerts

The system flags abnormal recharge frequency or amounts and surfaces alerts.

**Consequences (testable):**

- Events triggering a suspicious recharge flag appear in the Real-Time Anomaly Feed (FR-53).
- Confirmed suspicious recharge cases are escalated to the Fraud Case Queue.

---

### 1.5.9. CDR Ingestion & Balance Management Pipeline

**Description:** The real-time data pipeline that ingests CDR events (the system's primary input), applies deterministic balance deductions, and triggers downstream fraud screening and notifications. CDR is the entry point; all upstream charging and rating steps are out of scope. The pipeline must support a Target State throughput of 100,000 CDR events per second. The MVP pipeline targets functional correctness; Target State scaling is addressed in the architecture document.

**Functional Requirements:**

#### FR-57: CDR Ingestion

The system ingests CDR events from the telecom operator's upstream pipeline in real time.

**Consequences (testable):**

- CDR events are consumed from the designated streaming input (message broker/queue).
- Each CDR event carries: subscriber MSISDN, event type (voice/data/SMS/roaming), duration/volume, timestamp, and CDR reference ID.
- Failed ingestion events are captured in a dead-letter mechanism for reprocessing.

#### FR-58: Balance Deduction Engine

The system deducts the appropriate charge from the subscriber's Wallet Balance on each CDR receipt, deterministically and idempotently.

**Consequences (testable):**

- Each CDR event results in exactly one balance deduction (idempotency enforced via CDR reference ID).
- Deduction logic is deterministic: same CDR input always produces the same deduction.
- Balance deduction P95 latency is ≤ 200ms from CDR receipt.
- Deduction for Talktime Balance Plans is per-unit rate × usage volume.
- Deduction for unlimited-bundle plans decrements the bundle allowance counter; charges apply only when bundle is exhausted.

#### FR-59: Audit Log Trail

Every billing, authentication, and administrative action is recorded in an immutable audit log.

**Consequences (testable):**

- Audit entries cannot be modified or deleted after creation.
- Each entry contains: action type, actor (subscriber MSISDN or system component), timestamp, and relevant reference ID.
- Billing records are retained for a minimum of 6 years per TRAI mandate.
- Audit log is queryable by MSISDN and time range.

---

### 1.5.10. Fraud Detection Agent

**Description:** A two-stage fraud detection system embedded in the CDR processing pipeline. Stage 1 is a fast, deterministic rule-based pre-screening filter. Stage 2 routes flagged events to an LLM-powered Fraud Detection Agent for deeper analysis. The agent uses a notification tool to alert the fraud supervisor. An ML classifier hook is included in the architecture for future integration but is not built for MVP. Agent analysis runs asynchronously to the balance deduction to avoid adding latency to the <200ms deduction SLA.

**Functional Requirements:**

#### FR-60: Rule-Based Pre-Screening

Every ingested CDR event is evaluated against a rule set for anomaly signals before being passed to the Fraud Detection Agent.

**Consequences (testable):**

- Pre-screening executes synchronously in the CDR processing pipeline before agent escalation.
- Rules cover at minimum: high voice-call rate, roaming abuse, SIM swap signals, suspicious recharge patterns.
- Events passing all rules are processed without agent escalation.
- Events triggering a rule are flagged and queued for agent analysis.

#### FR-61: Agent Escalation on Risk

Flagged CDR events are routed to the Fraud Detection Agent for LLM-powered deeper risk analysis.

**Consequences (testable):**

- The agent receives the CDR event, the triggered rule(s), and relevant subscriber history.
- The agent produces a risk verdict: `confirmed | false positive | needs review`.
- Agent analysis is logged and traceable via LangFuse.

#### FR-62: Fraud Supervisor Notification

The Fraud Detection Agent triggers a notification to the fraud supervisor when risk is confirmed.

**Consequences (testable):**

- A notification is sent via the simulated notification pipeline on `confirmed` risk verdict.
- The notification includes: subscriber MSISDN, CDR reference, agent analysis summary, and risk type.
- The case is simultaneously added to the Fraud Case Queue (FR-54).

---

### 1.5.11. Security & Compliance

**Description:** Platform-wide security and compliance requirements meeting TRAI mandates, PCI-DSS, and standard auth hardening. Consent management and session token revocation are deferred post-MVP.

**Functional Requirements:**

#### FR-63: PII Encryption

All Personally Identifiable Information is encrypted at rest and in transit.

**Consequences (testable):**

- MSISDN, name, address, and financial data are encrypted at rest using AES-256 or equivalent.
- All API communication uses TLS 1.2+.
- Unencrypted PII is never written to logs or audit trails.

#### FR-64: Payment Data Tokenisation (PCI-DSS)

Card payment data is tokenised; raw card numbers are never stored or transmitted through the system.

**Consequences (testable):**

- Card tokenisation occurs at the point of entry; the raw PAN is never persisted.
- Stored token references can retrieve masked card display (e.g. `**** **** **** 4242`) but never the raw PAN.

#### FR-65: TRAI Compliance

The system adheres to TRAI regulations for billing, data handling, and subscriber data localisation.

**Consequences (testable):**

- All subscriber data is stored in infrastructure physically located within India borders.
- CAF audit trail is maintained per TRAI requirements.
- Billing records are retained for the TRAI-mandated retention period.

#### FR-66: Account Takeover Prevention

The system implements authentication hardening and integrates SIM swap detection with the login flow. On confirmed SIM swap risk, the account is blacklisted via a dedicated blacklist table, the account is disabled at the API gateway, and any active JWTs are revoked through the API gateway.

**Consequences (testable):**

- When the Fraud Detection Agent emits a confirmed SIM swap verdict for a subscriber, the system writes a blacklist record (MSISDN, reason, timestamp) to the blacklist table.
- The API gateway disables the subscriber account: subsequent API requests return HTTP 403.
- Active JWTs for the subscriber are revoked; requests using a revoked token return HTTP 401.
- A subscriber attempting login after blacklisting receives the message: "Your account has been restricted. Please visit a Telecom Kiosk to restore access."
- If the subscriber is already in an active session when blacklisted, they receive an in-session alert notification and are logged out within one session-check cycle.

#### FR-67: JWT-Based Auth and Session Management

All four dashboards (Subscriber, Operations, Fraud, Simulator) use JWT-based auth with role separation.

**Consequences (testable):**

- Each dashboard enforces role-appropriate access; cross-dashboard privilege escalation is blocked.
- JWTs carry expiry claims; expired tokens are rejected.

---

### 1.5.12. Simulator & Developer Tools

**Description:** A standalone developer/demo tool dashboard providing CDR event simulation with end-to-end trace logs, a live Notification Portal, and SIM activation simulation. This is distinct from the operational dashboards and intended for development, testing, and capstone demonstration purposes. The Simulator dashboard is accessible to authenticated developer/admin users only and is not subscriber-facing.

**Functional Requirements:**

#### FR-68: CDR Simulator

A developer/admin can generate synthetic CDR events and observe end-to-end trace logs across each service in real time.

**Consequences (testable):**

- The simulator UI allows specifying CDR parameters: subscriber MSISDN, event type (voice/data/SMS/roaming), duration/volume.
- On event dispatch, the full trace is shown on-screen: CDR received → balance deducted → fraud screened → notification triggered.
- Trace includes timestamps per stage and the component that handled each step.

#### FR-69: Notification Portal

All simulated notifications sent to subscribers (SMS, push, OTP) are surfaced on a live Notification Portal for observation.

**Consequences (testable):**

- Notifications appear in the portal in real time as they are dispatched by the pipeline.
- Each entry shows: recipient MSISDN, notification type, message content, and timestamp.
- OTP messages are included in the portal feed for testing auth flows.

#### FR-70: SIM Activation Simulator

An operator/admin can simulate the SIM card activation flow and progress a subscriber's order to `Activated (Ready to Use)` status.

**Consequences (testable):**

- Clicking "Activate" for a given MSISDN progresses the order status to `Activated`.
- The subscriber account is updated to reflect MSISDN-based login availability post-activation.

---

### 1.5.13. Synthetic Dataset

**Description:** A generated dataset required for MVP development, testing, and demonstration. All ML model training, chatbot testing, and UI demonstration will use this dataset.

**Functional Requirements:**

#### FR-71: Synthetic Dataset Generation

The system includes scripts to generate a synthetic dataset of sufficient scale for development and demonstration.

**Consequences (testable):**

- Generated dataset contains: ≥ 1,000 plans, 300,000 subscribers, and 5,000,000 CDRs.
- All CDRs include required schema fields: subscriber MSISDN, event type, duration/volume, timestamp, rate, charge, CDR reference ID.
- Dataset contains realistic distributions of event types, plan types, and usage patterns.
- Both plan types are represented: unlimited bundle plans and Talktime Balance Plans.

---

### 1.5.14. Evaluation, Observability & Quality

**Description:** Evaluation and observability infrastructure for AI/ML components. LangFuse provides agentic workflow tracing. DeepEval and LLM-as-Judge provide offline and sampled online quality scores for chatbot responses and plan recommendations.

**Functional Requirements:**

#### FR-72: LangFuse Agentic Observability

All multi-agent workflows are instrumented with LangFuse for end-to-end trace visibility.

**Consequences (testable):**

- Every agent invocation, A2A call, and tool call is captured as a LangFuse trace.
- Traces are queryable by session ID, agent type, and time range.

#### FR-73: LLM-as-Judge Evaluation

An LLM-as-Judge mechanism validates plan recommendation relevance and chatbot response quality.

**Consequences (testable):**

- Judge evaluations run offline on a configurable sample of production interactions.
- Each evaluation produces a quality score and a pass/fail verdict per defined rubric.
- Evaluation results are stored and accessible for reporting.

#### FR-74: DeepEval Integration

DeepEval is integrated for chatbot quality metrics and prediction accuracy evaluation.

**Consequences (testable):**

- Offline evals run on the synthetic dataset prior to deployment.
- Sampled online evals run on live production interactions (configurable sample rate).
- Metrics captured include: response faithfulness, relevance, hallucination rate for chatbot; accuracy metrics for churn and recharge conversion predictions.

#### FR-75: Root Cause Analysis Agent

An LLM-powered Root Cause Analysis Agent assists engineering teams in diagnosing billing discrepancies and failed recharges. The agent uses a Standard Operating Procedure (SOP) knowledge base — synthetically generated — as its primary grounding source alongside audit logs and CDR data. The same predefined SOP rules used to build the SOP knowledge base must also be used to generate synthetic CDR records with embedded internal notes, enabling the agent's diagnoses to be validated against known scenarios.

**Consequences (testable):**

- The agent accepts a case description (subscriber MSISDN, transaction reference, observed vs. expected outcome) and returns a structured root cause analysis.
- Analysis is grounded in the SOP knowledge base, audit log, and CDR data for the relevant subscriber and time window.
- For each predefined SOP rule scenario, a corresponding synthetic CDR record with internal notes exists in the dataset; the agent's diagnosis for that CDR matches the expected SOP-defined root cause.
- The SOP knowledge base is versioned and queryable independently of the agent.

#### FR-76: Distributed Trace ID Propagation

A trace ID is propagated across the full CDR → balance → fraud → notification pipeline for end-to-end observability.

**Consequences (testable):**

- Every CDR event is assigned a trace ID at ingestion.
- The trace ID is carried through to balance deduction, fraud screening, agent escalation, and notification dispatch.
- The trace ID is included in CDR Simulator trace output (FR-68).

#### FR-77: Health Check Endpoints

Every microservice exposes `/health` and `/ready` endpoints.

**Consequences (testable):**

- `/health` returns HTTP 200 when the service is running.
- `/ready` returns HTTP 200 only when the service is ready to serve traffic (dependencies healthy).
- Both endpoints respond within 200ms under normal operating conditions.

---

## 1.6. Non-Goals (Explicit)

- **Pre-CDR charging and rating** — Upstream charging and rating systems are out of scope. CDR is the system's entry point.
- **Postpaid billing** — The platform is prepaid-only.
- **Real payment gateway integration** — All payment flows are simulated in MVP. No real Razorpay, Stripe, UPI gateway, or bank integration.
- **Actual SMS/push delivery** — All notifications are simulated and delivered to the Notification Portal. No real SMS gateway (e.g. Twilio, MSG91) in MVP.
- **Refund processing** — Only a dummy view of failed transactions is in scope. No actual refund workflow.
- **USSD session initiation** — The system only responds to operator USSD callbacks; it does not initiate USSD sessions.
- **ML fraud classifier** — The fraud detection ML classifier is an architecture hook only; it is not built for MVP.
- **Consent Management** — Explicit consent capture and storage for data usage and marketing comms is deferred. [NON-GOAL for MVP]
- **Session Timeout and Token Revocation** — Force-expiry of sessions and token revocation on fraud identification are deferred. [NON-GOAL for MVP]
- **Catalogue-plan mapping in upsell strategy** — Upsell strategy recommendations describe segments and outreach timing; they do not map to specific plan catalogue entries in MVP.
- **International subscribers or multi-operator support** — Indian operator, Indian subscribers only.
- **Physical CAF / paper KYC** — Digital submission only; physical document handling is out of scope.
- **Target State infrastructure build** — The MVP architecture is a PoC. Target State infrastructure capable of 100K CDR events/sec is addressed in the architecture document, not built for MVP.

---

## 1.7. MVP Scope

### 1.7.1. In Scope

- All P0 features: account & identity, balance & usage, recharge & payments (simulated), notifications (simulated), CDR ingestion pipeline, balance deduction engine, fraud detection agent (rules + LLM escalation), security & compliance (PII encryption, PCI-DSS tokenisation, TRAI compliance, JWT auth), ops dashboard (plan stock, order fulfilment, subscriber growth forecast, plan popularity forecast), synthetic dataset generation
- All P1 features: self-care chatbot (full multi-agent stack), USSD interface (callback handling only), fraud management dashboard
- P2 features: ops dashboard observability (CDR monitor, pipeline health, notification delivery); LLM segmentation upselling strategy; LangFuse observability; LLM-as-Judge; DeepEval integration; Root Cause Analysis Agent
- Simulator & developer tools: CDR simulator, Notification Portal, SIM activation simulator
- Architecture deliverables: Target State architecture diagram + design document; MVP architecture diagram + design document; Next Steps presentation section
- Items marked `#future_not_mvp` are explicitly excluded (Consent Management, Session Timeout/Revocation)

### 1.7.2. Out of Scope for MVP

- Real payment gateway integration [deferred to production]
- Real SMS/push notification delivery [deferred to production]
- Refund workflow implementation [excluded — dummy view only]
- ML fraud classifier [architecture hook only]
- Consent management [#future_not_mvp]
- Session timeout and token revocation [#future_not_mvp]
- Target State infrastructure provisioning (100K events/sec scale) [architecture document only]
- Catalogue-plan mapping in upsell recommendations [MVP descriptive only]

---

## 1.8. Success Metrics

| Metric                                     | Definition                                                                | Target                      |
| ------------------------------------------ | ------------------------------------------------------------------------- | --------------------------- |
| Chatbot containment rate                   | % of subscriber queries resolved by chatbot without human escalation      | ≥ 70% at launch             |
| Chatbot response quality (LLM-as-Judge)    | % of sampled responses rated as relevant and accurate                     | ≥ 80% pass rate             |
| Chatbot hallucination rate (DeepEval)      | % of responses that introduce factually incorrect information             | < 5%                        |
| Balance deduction latency (P95)            | Time from CDR receipt to balance update                                   | < 200ms                     |
| Fraud detection escalation accuracy        | % of agent-escalated cases confirmed as true positive by fraud supervisor | ≥ 75%                       |
| Plan recommendation conversion rate        | % of chatbot plan recommendations accepted by subscribers                 | Baseline measurement in MVP |
| Subscriber growth forecast accuracy (MAPE) | Mean Absolute Percentage Error on 3-month activation/churn forecast       | < 15% MAPE                  |
| Upsell strategy feedback loop coverage     | % of upsell campaign outcomes logged for feedback                         | 100% of campaigns run       |
| CDR simulator trace completeness           | % of simulated CDR events showing full end-to-end trace                   | 100%                        |

**Counter-metrics (watch for degradation):**

- Session length inflation — chatbot sessions should not grow longer over time (signals confusion, not engagement)
- False positive fraud escalation rate — track cost of agent analysis on non-fraud events
- LLM token cost per upselling session — monitor for segmentation cost runaway with large pools

---

## 1.9. Constraints

- **Latency** — Balance deduction P95 ≤ 200ms; agents must not be in the synchronous balance deduction path.
- **Scale (Target State)** — CDR ingestion pipeline must be architecturally capable of 100,000 events/second; MVP is a PoC and need not meet this at launch.
- **Regulatory** — TRAI compliance, data localisation within India borders, PCI-DSS for payment data, CAF audit trail.
- **LLM cost control** — LLM-discovery sample capped at 100 subscribers per upselling session; token-optimised CDR feature summaries (not raw CDRs) as LLM inputs.
- **Geography** — Indian telecom operator; all subscriber data stays within India.
- **Model agnosticism** — PRD does not mandate specific LLM providers or model versions; those decisions belong in the architecture document.
- **Platform** — Payments are simulated; SMS is simulated; USSD is inbound-only (callback handler, not initiator).
- **Prepaid only** — No postpaid, no corporate accounts.

---

## 1.10. Assumptions Index

| #    | Assumption                                                                                                                                              | Tagged in            |
| ---- | ------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------- |
| A-1  | CDR is the pipeline entry point; pre-CDR charging and rating are out of scope (per discussion with Vijay)                                               | §1, FR-57            |
| A-2  | Plans include both unlimited-bundle and Talktime Balance types; prepaid only                                                                            | §3 (Glossary), FR-58 |
| A-3  | USSD handling is inbound-only: receive `{msisdn, button_pressed, session_id}` callbacks; the telecom operator's gateway manages the GSM session         | §4.6, FR-37          |
| A-4  | Agents are NOT in the synchronous balance deduction path due to latency constraints; fraud agent escalation runs asynchronously after balance deduction | §4.10, FR-61         |
| A-5  | Multi-agent framework (e.g. LangGraph) is an architecture decision; PRD is framework-agnostic                                                           | §4.5                 |
| A-6  | Pre-activation OTP is sent to the alternate mobile number provided during registration                                                                  | FR-4                 |
| A-7  | SIM activation order fulfilment is simulated on the UI; no real provisioning system integration                                                         | FR-2                 |
| A-8  | RAG knowledge base covers both general telecom FAQs and plan/billing queries                                                                            | FR-26                |
| A-9  | SMS and push notifications share the same simulated delivery pipeline (Notification Portal)                                                             | §4.4                 |
| A-10 | Fraud agent analysis is asynchronous to the balance deduction to protect the <200ms SLA                                                                 | FR-61                |
| A-11 | USSD recharge initiation via USSD menu triggers the intent; full payment completion may redirect to the web flow or is simulated                        | FR-40                |
| A-12 | SIM swap detection rule parameters (e.g. geographic distance threshold, time window) are implementation decisions                                       | FR-55                |
| A-13 | Account takeover additional auth challenge mechanism is an implementation decision                                                                      | FR-66                |
| A-14 | Simulator dashboard is accessible to authenticated developer/admin users only; not subscriber-facing                                                    | §4.12                |
| A-15 | TRAI CAF is submitted digitally; physical document handling is out of scope                                                                             | FR-3                 |

---

## 1.11. Resolved Decisions

All open questions have been resolved. Decisions are reflected in their respective FRs above and logged in `.decision-log.md`.

| #    | Question                                       | Resolution                                                                                                            | Applied to |
| ---- | ---------------------------------------------- | --------------------------------------------------------------------------------------------------------------------- | ---------- |
| OQ-1 | Low Balance Alert threshold                    | ₹10, global default sourced from a database configuration record                                                      | FR-18      |
| OQ-2 | Plan expiry reminder lead time                 | 3 days, sourced from a database configuration record                                                                  | FR-20      |
| OQ-3 | KPI set for Target Base Builder                | Dynamically sourced from columns of a materialised subscriber KPI database view; exact columns are TBD                | FR-46      |
| OQ-4 | How plan recommendation outcomes are captured  | Explicit subscriber action; on acceptance, system responds with handoff message; dismissal is inferred at session end | FR-33      |
| OQ-5 | TRAI audit log retention period                | 6 years minimum                                                                                                       | FR-59      |
| OQ-6 | Rate limit threshold                           | 100 RPM per subscriber per channel (API, USSD, chatbot); configurable via database record                             | FR-36      |
| OQ-7 | Upsell feedback loop — Conclusion Agent reuse? | Upsell feedback loop does not use the Conclusion Agent; outcomes logged to a dedicated upsell feedback store          | FR-51      |
