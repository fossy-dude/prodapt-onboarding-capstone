# 1. User Journeys

## 1.1. Subscriber

The end customer. Purchases a SIM, recharges, interacts with the bot, and manages their account independently.

- **Onboard + Activate SIM** — Completes a sign-up form to receive a Registration ID, submits a TRAI CAF digitally with an immutable audit trail, and tracks SIM status through states: Created → KYC → Activated.
- **Log In** — Pre-activation uses Registration ID + OTP; post-activation uses MSISDN + credentials, with step-up OTP as needed.
- **View Balance + Usage** — Sees live wallet balance in INR updated on each CDR, per-type usage (voice/data/SMS/roaming), and active plan details including validity, quotas, and remaining allowances.
- **Recharge** — Browses the plan catalogue, selects a plan, pays via saved or new method (card/UPI/netbanking/wallet through a simulated gateway), with retry protection against double-charges and a PDF receipt on completion.
- **Audit Self** — Accesses a full ledger of charges, recharges, refunds with CDR references, and views failed recharges (no real refunds in MVP).
- **Self-Help Chatbot** — Queries balance, quota, plan details, and expiry. Can recharge in-chat via tool call, request a "why was I charged X?" breakdown from the Rating Agent, raise disputes that auto-generate a ticket with an ID, view past tickets, and receive plan recommendations to accept or dismiss.
- **USSD Self-Serve (No Internet)** — Checks balance, views plan info, initiates a recharge, and toggles notification preferences.
- **Other:**
	- Manages profile (name, address, KYC status) and payment methods (tokenised card, UPI, netbanking, wallet).
	- Receives proactive alerts for low balance (<₹10), zero balance, plan expiry (3 days prior), and low data (<10%).
	- Chatbot maintains context across turns, answers FAQs via RAG, and rejects adversarial or malformed input.

---

## 1.2. Operations (Ops)

Keeps the network and billing pipeline healthy by monitoring stock, fulfilment, and system health.

- **Monitor Plan Stock** — Views live subscriber counts per active plan.
- **Track Order Fulfilment** — Monitors all orders across states (Created/KYC/Activated) and identifies stalled activations.
- **Watch Pipeline Health** — Tracks CDR processing health, charging latency, and notification delivery.
- **Other:**
	- Reads 3-month subscriber growth and churn forecasts powered by ML.

---

## 1.3. Marketing

Identifies upsell opportunities and builds targeted promotional strategies.

- **Target Base Builder** — Composes KPI filters on a materialised view to generate a candidate pool, with a sample table and pool-level statistics.
- **Segment Labelling** — An LLM tags up to 100 sampled subscribers with descriptive labels; the Rule Induction Agent generates reusable KPI-predicate rules, which are then applied deterministically to the full base with per-segment stats.
- **Upsell Strategy** — The LLM produces a textual upsell playbook for each segment.
- **Other:**
	- Generates 30–90 day demand forecasts per plan to guide spend decisions.

---

## 1.4. Fraud Team (Analyst + Supervisor)

Detects abuse and locks compromised accounts.

- **Anomaly Feed** — Monitors a live feed of rule-pre-screened flagged CDRs.
- **Case Queue** — Works confirmed and escalated risk cases in a supervisor queue; the Fraud Detection Agent deep-analyses flagged CDRs and notifies the supervisor on confirmation.
- **Takeover + Abuse Detection** — Receives SIM swap alerts and alerts for abnormal recharge frequency or amount.
- **Other:**
	- On a confirmed SIM swap, auto-protection triggers: account blacklisting, Cognito disable, and JWT revocation.

---

## 1.5. Engineering (Developer / Admin / Platform)

Builds, tests, and debugs the platform.

- **Pipeline Simulation** — Generates synthetic CDRs and observes end-to-end traces in real time; simulates SIM activation and pushes orders through to Activated state.
- **Notification Observability** — Uses the Notification Portal to view a live feed of all simulated SMS, push, and OTP events.
- **Synthetic Data Generation** — Runs scripts to generate ≥1K plans, 300K subscribers, and 5M CDRs.
- **Other:**
	- Every service exposes `/health` and `/ready` endpoints.
	- LangFuse traces all agent workflows; LLM-as-Judge validates recommendation and chatbot quality; DeepEval measures chatbot metrics and prediction accuracy.
	- The RCA Agent diagnoses billing discrepancies and failed recharges.

---

## 1.6. (Background) System (Automated / Infra / Agents)

Fully automated — operates without human intervention.

- **Real-Time Billing** — Ingests CDRs from upstream with dead-letter handling for failures, deducts charges from the wallet deterministically and idempotently at P95 ≤200ms, and maintains an immutable audit log with 6-year retention.
- **Security + Compliance** — Encrypts all PII at rest and in transit, tokenises card data (no raw PAN stored), enforces TRAI compliance, and applies JWT auth with role separation across 4 dashboards.
- **Other:**
	- Rate-limits at 100 RPM per subscriber across API/USSD/chatbot (DB-configurable).
	- Handles USSD via REST callbacks with structured text menus.
	- Multi-agent A2A communication: Support ↔ Balance Management; Conclusion Agent → Notification Agent at session end.
	- Propagates Trace IDs across CDR → Balance → Fraud → Notification.