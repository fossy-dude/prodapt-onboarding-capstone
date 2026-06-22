"""SOP knowledge base generator for SkyLink telecom (Story 2.6).

Writes sop_rules and sop_knowledge_chunks to Postgres.
These chunks are the source for Story 2.7's Milvus vector seeding.

Run from the service_webapp directory:
    cd service_webapp && PYTHONPATH=src python ../scripts/sop_generator.py

Idempotent: truncates and re-seeds on every run.
"""

from __future__ import annotations

import logging
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import psycopg

sys.path.insert(0, str(Path(__file__).parent.parent / "service_webapp" / "src"))
from core.config import settings  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)


def _conninfo() -> str:
    db = settings.db
    return (
        f"host={db.host} port={db.port} dbname={db.name} "
        f"user={db.user} password={db.password.get_secret_value()}"
    )


# ── SOP Rules ─────────────────────────────────────────────────────────────────

_RULES: list[dict] = [
    {
        "domain": "fraud",
        "rule_name": "HIGH_VELOCITY_CDR",
        "trigger_condition": "subscriber CDR count exceeds 200 events in a single 24-hour window",
        "response_template": "Flag subscriber account for manual fraud review. Temporarily suspend outgoing calls. Escalate to fraud analyst within 2 hours.",
        "priority": 10,
    },
    {
        "domain": "fraud",
        "rule_name": "SIM_SWAP_DETECTION",
        "trigger_condition": "IMEI change detected on subscriber account within 48 hours of last authentication",
        "response_template": "Send OTP verification to registered email. Lock SIM for 30 minutes pending verification. Log SIM-swap event with timestamp.",
        "priority": 10,
    },
    {
        "domain": "fraud",
        "rule_name": "ROAMING_ABUSE",
        "trigger_condition": "subscriber incurs roaming charges across more than 4 circles in 24 hours without an active roaming plan",
        "response_template": "Block further roaming usage. Notify subscriber via SMS. Waive charges if subscriber purchases a roaming add-on within 2 hours.",
        "priority": 9,
    },
    {
        "domain": "fraud",
        "rule_name": "BULK_DIALLER_DETECTION",
        "trigger_condition": "subscriber dials more than 50 unique destination numbers within 1 hour",
        "response_template": "Rate-limit outgoing calls to 10 per minute. Flag for spam/telemarketing review. Send warning SMS to subscriber.",
        "priority": 8,
    },
    {
        "domain": "fraud",
        "rule_name": "IMPOSSIBLE_LOCATION_CHANGE",
        "trigger_condition": "subscriber connects to 5 or more distinct cell towers within a 60-minute window implying physical impossibility",
        "response_template": "Flag as potential device cloning. Trigger secondary authentication. Alert fraud operations team.",
        "priority": 9,
    },
    {
        "domain": "billing",
        "rule_name": "BALANCE_DEPLETION_ALERT",
        "trigger_condition": "subscriber wallet balance falls below 10% of plan price",
        "response_template": "Send low-balance SMS notification. Offer recharge link. If balance reaches zero, suspend data and outgoing calls; allow incoming calls for 48 hours.",
        "priority": 7,
    },
    {
        "domain": "billing",
        "rule_name": "PLAN_EXPIRY_REMINDER",
        "trigger_condition": "plan validity_days has 3 or fewer days remaining",
        "response_template": "Send renewal reminder SMS on day -3 and day -1. Offer auto-renewal at same plan or upsell one tier. Grace period: 24 hours post-expiry for renewal.",
        "priority": 6,
    },
    {
        "domain": "billing",
        "rule_name": "PAYMENT_FAILURE_RETRY",
        "trigger_condition": "subscriber payment fails due to insufficient funds or bank decline",
        "response_template": "Retry payment after 6 hours. After 3 failures, notify subscriber and suspend auto-renewal. Manual recharge remains available.",
        "priority": 7,
    },
    {
        "domain": "billing",
        "rule_name": "OVERCHARGE_DISPUTE",
        "trigger_condition": "subscriber raises a dispute for charges exceeding their plan quota",
        "response_template": "Pull CDR records for disputed period. If discrepancy confirmed, issue credit within 48 hours. Escalate to billing team if dispute exceeds Rs 500.",
        "priority": 8,
    },
    {
        "domain": "billing",
        "rule_name": "ROAMING_CHARGE_CAP",
        "trigger_condition": "roaming charges exceed Rs 2000 in a single billing cycle",
        "response_template": "Send spending-cap alert. Block further roaming. Require subscriber confirmation to extend roaming. Offer roaming plan upgrade.",
        "priority": 9,
    },
    {
        "domain": "activation",
        "rule_name": "NEW_SIM_ACTIVATION",
        "trigger_condition": "new SIM card inserted and MSISDN not yet activated",
        "response_template": "Trigger TRAI CAF verification flow. Collect subscriber name, address, and identity document. Activate within 24 hours of successful KYC.",
        "priority": 8,
    },
    {
        "domain": "activation",
        "rule_name": "KYC_EXPIRY",
        "trigger_condition": "subscriber KYC document expires within 30 days",
        "response_template": "Send re-KYC notification via SMS and email. Provide digital re-verification link. Suspend service 7 days after expiry if re-KYC not completed.",
        "priority": 7,
    },
    {
        "domain": "activation",
        "rule_name": "PORT_IN_REQUEST",
        "trigger_condition": "subscriber submits Mobile Number Portability (MNP) request",
        "response_template": "Acknowledge UPC within 2 hours. Initiate port-out within 7 working days per TRAI guidelines. Retain subscriber offer: match competitor plan or offer 10% discount.",
        "priority": 6,
    },
    {
        "domain": "support",
        "rule_name": "NETWORK_COMPLAINT",
        "trigger_condition": "subscriber reports no signal or degraded service for more than 2 hours",
        "response_template": "Check circle-level cell tower status. If tower outage confirmed, send maintenance notification with ETA. Offer data rollover compensation if outage exceeds 4 hours.",
        "priority": 7,
    },
    {
        "domain": "support",
        "rule_name": "INTERNATIONAL_CALL_BLOCKED",
        "trigger_condition": "subscriber on non-international plan attempts ISD call",
        "response_template": "Inform subscriber of ISD activation requirement. Offer International add-on. Activate ISD within 15 minutes of add-on purchase.",
        "priority": 5,
    },
    {
        "domain": "compliance",
        "rule_name": "TRAI_DND_ENFORCEMENT",
        "trigger_condition": "outgoing bulk SMS detected from subscriber registered on DND",
        "response_template": "Block outgoing bulk SMS. Log TRAI DND violation. Notify subscriber of violation. Repeat violations result in account suspension per TRAI guidelines.",
        "priority": 10,
    },
    {
        "domain": "compliance",
        "rule_name": "DATA_PRIVACY_REQUEST",
        "trigger_condition": "subscriber requests personal data export or deletion under IT Act",
        "response_template": "Acknowledge request within 24 hours. Provide data export or confirm deletion within 30 days. Retain billing records for minimum 2 years per TRAI mandate.",
        "priority": 8,
    },
    {
        "domain": "network",
        "rule_name": "CIRCLE_CONGESTION_THROTTLE",
        "trigger_condition": "active data sessions in a telecom circle exceed 90% of capacity",
        "response_template": "Apply fair-use throttling to SmartValue and TalkMore plan subscribers. Maintain full speed for SuperData and Unlimited subscribers. Alert NOC team.",
        "priority": 7,
    },
    {
        "domain": "network",
        "rule_name": "CDR_DLQ_REPROCESSING",
        "trigger_condition": "CDR event lands in Dead Letter Queue after 3 processing failures",
        "response_template": "Alert billing operations team. Manual inspection of CDR payload within 4 hours. Reprocess after fix or mark as irrecoverable and issue credit note.",
        "priority": 8,
    },
    {
        "domain": "network",
        "rule_name": "ROAMING_PARTNER_FAILURE",
        "trigger_condition": "roaming partner network reports more than 5% call failure rate",
        "response_template": "Disable roaming on failing partner network. Notify affected subscribers. Switch to alternate partner within 1 hour. Escalate to roaming agreements team.",
        "priority": 9,
    },
]


# ── SOP Knowledge Chunks ───────────────────────────────────────────────────────

_CHUNKS: list[dict] = [
    # Fraud domain
    {
        "source_document": "SkyLink Fraud Detection SOP v3.2",
        "domain": "fraud",
        "chunk_index": 0,
        "chunk_text": (
            "SkyLink's fraud detection system monitors CDR velocity in real time. "
            "A subscriber generating more than 200 call or data events within any 24-hour window "
            "is automatically flagged for velocity fraud. The system compares rolling 24-hour counts "
            "against the threshold and triggers an alert to the fraud operations dashboard. "
            "Affected CDRs are marked fraud_flag=TRUE in the billing_cdr_events table for downstream "
            "agent analysis."
        ),
    },
    {
        "source_document": "SkyLink Fraud Detection SOP v3.2",
        "domain": "fraud",
        "chunk_index": 1,
        "chunk_text": (
            "SIM-swap fraud is detected by monitoring IMEI changes on a subscriber's account. "
            "If the IMEI registered in CDR events changes within 48 hours of the last authenticated session, "
            "the system triggers a SIM-swap alert. The subscriber's pre-swap and post-swap CDRs are "
            "segmented by the swap timestamp. Post-swap CDRs from the new IMEI are flagged as suspicious. "
            "The subscriber is required to complete a secondary OTP verification before the new SIM is activated."
        ),
    },
    {
        "source_document": "SkyLink Fraud Detection SOP v3.2",
        "domain": "fraud",
        "chunk_index": 2,
        "chunk_text": (
            "Roaming abuse occurs when a subscriber uses roaming services across multiple telecom circles "
            "without an active roaming plan. SkyLink tracks the telecom_circle field in CDR events. "
            "If a subscriber's CDRs span more than 4 distinct circles in a 24-hour window with roaming=TRUE, "
            "the system applies an abuse flag. This pattern often correlates with SIM resale fraud or "
            "unauthorised commercial use of consumer SIMs."
        ),
    },
    {
        "source_document": "SkyLink Fraud Detection SOP v3.2",
        "domain": "fraud",
        "chunk_index": 3,
        "chunk_text": (
            "Bulk dialling fraud is identified when a subscriber contacts more than 50 unique destination numbers "
            "within a 60-minute window. The to_number column in billing_cdr_events is used to count unique "
            "destinations per subscriber per hour. This pattern is characteristic of telemarketing fraud, "
            "OTP interception rings, and subscription scam operations. Such subscribers are rate-limited "
            "immediately and referred to the compliance team."
        ),
    },
    {
        "source_document": "SkyLink Fraud Detection SOP v3.2",
        "domain": "fraud",
        "chunk_index": 4,
        "chunk_text": (
            "Device cloning is detected through multi-tower location analysis. If a subscriber's CDRs "
            "show connection to 5 or more distinct cell_tower_id values within a 60-minute window, "
            "it indicates physical impossibility — a genuine user cannot be in 5 different locations simultaneously. "
            "This is a strong indicator of cloned SIM cards being used in parallel across different devices. "
            "Fraud operations must be alerted within 15 minutes of detection."
        ),
    },
    {
        "source_document": "SkyLink Fraud Detection SOP v3.2",
        "domain": "fraud",
        "chunk_index": 5,
        "chunk_text": (
            "The fraud risk score is computed by combining multiple signals: CDR velocity (weight 0.35), "
            "SIM-swap history (weight 0.25), roaming pattern anomalies (weight 0.20), "
            "unique destination count (weight 0.12), and cell tower location jumps (weight 0.08). "
            "A composite score above 0.7 triggers automatic account review. Scores above 0.9 trigger "
            "immediate suspension pending investigation."
        ),
    },
    # Billing domain
    {
        "source_document": "SkyLink Billing Operations Manual v5.1",
        "domain": "billing",
        "chunk_index": 0,
        "chunk_text": (
            "SkyLink uses an integer paise model for all monetary values. One rupee equals 100 paise. "
            "All charges (cost_paise), balances (balance_paise), and plan prices (price_paise) are stored "
            "as BIGINT in Postgres. This avoids floating-point rounding errors in high-volume billing. "
            "Voice CDRs are rated at 50 paise per second. Data CDRs at 200 paise per MB. SMS is 100 paise flat."
        ),
    },
    {
        "source_document": "SkyLink Billing Operations Manual v5.1",
        "domain": "billing",
        "chunk_index": 1,
        "chunk_text": (
            "The billing wallet balance (billing_wallet_balances) is a denormalised real-time balance "
            "maintained in Valkey cache and flushed to Postgres every 30 seconds by the balance engine. "
            "When a CDR is rated, the cost_paise is deducted from the subscriber's wallet. "
            "If balance reaches zero, outgoing calls and data are suspended. Incoming calls remain active "
            "for a 48-hour grace period to allow recharge."
        ),
    },
    {
        "source_document": "SkyLink Billing Operations Manual v5.1",
        "domain": "billing",
        "chunk_index": 2,
        "chunk_text": (
            "Plan pricing follows a validity multiplier model. A 28-day base price of Rs 199 (19,900 paise) "
            "scales to Rs 348 for 56 days (1.75×), Rs 478 for 84 days (2.4×), Rs 896 for 180 days (4.5×), "
            "and Rs 1,592 for 365 days (8×). This gives subscribers a discount incentive for longer validity plans. "
            "International plans carry a premium starting at Rs 499 for 28 days."
        ),
    },
    {
        "source_document": "SkyLink Billing Operations Manual v5.1",
        "domain": "billing",
        "chunk_index": 3,
        "chunk_text": (
            "CDR dispute resolution: when a subscriber disputes a charge, billing operations pull the "
            "billing_cdr_events records for the disputed period. The CDR includes session_id, start_time, "
            "end_time, cdr_type, duration_seconds (for voice), volume_mb (for data), and cost_paise. "
            "If the charge is confirmed as erroneous, a credit transaction is inserted into billing_transactions "
            "with transaction_type='credit' and a negative amount_paise."
        ),
    },
    {
        "source_document": "SkyLink Billing Operations Manual v5.1",
        "domain": "billing",
        "chunk_index": 4,
        "chunk_text": (
            "Plan quota types: SuperData plans provide a daily data allowance (e.g. 2GB/day × 28 days = 56GB total). "
            "AllRounder plans provide a fixed monthly data pool (10GB–100GB). "
            "TextMore plans include 1,000–5,000+ SMS with unlimited SMS on high tiers. "
            "TalkMore plans offer 500–2,700+ voice minutes with unlimited calls on premium tiers. "
            "Unlimited plans have NULL for both data_limit_mb and voice_minutes, meaning no hard quota."
        ),
    },
    {
        "source_document": "SkyLink Billing Operations Manual v5.1",
        "domain": "billing",
        "chunk_index": 5,
        "chunk_text": (
            "Roaming charges on non-roaming plans are billed at 3× the standard rate. "
            "Subscribers on International plans have roaming included at standard rates within partner networks. "
            "Roaming CDRs are identified by roaming=TRUE in billing_cdr_events. "
            "The telecom_circle field records the circle where the CDR originated. "
            "Roaming CDRs originating outside the subscriber's home circle are subject to the roaming tariff."
        ),
    },
    # Activation domain
    {
        "source_document": "SkyLink Subscriber Activation Guide v2.4",
        "domain": "activation",
        "chunk_index": 0,
        "chunk_text": (
            "New SIM activation follows TRAI's Customer Acquisition Form (CAF) process. "
            "The subscriber must provide: full name, residential address (address_line1, city, state, pin_code), "
            "a valid identity document (Aadhaar, PAN, or Passport), and a biometric verification. "
            "The MSISDN is assigned in the format 91XXXXXXXXXX where the third digit is 6, 7, 8, or 9 "
            "per Indian mobile number allocation rules."
        ),
    },
    {
        "source_document": "SkyLink Subscriber Activation Guide v2.4",
        "domain": "activation",
        "chunk_index": 1,
        "chunk_text": (
            "KYC verification is mandatory within 30 days of SIM activation. "
            "SkyLink uses a digital KYC flow via the subscriber self-care portal. "
            "Uploaded documents are hashed using SHA-256 for the TRAI audit trail. "
            "The original document is not stored as a queryable column — only the hash is persisted "
            "in accordance with data minimisation principles. Subscribers must re-verify KYC every 5 years."
        ),
    },
    {
        "source_document": "SkyLink Subscriber Activation Guide v2.4",
        "domain": "activation",
        "chunk_index": 2,
        "chunk_text": (
            "Mobile Number Portability (MNP) allows subscribers to move their existing number to SkyLink. "
            "The subscriber obtains a Unique Porting Code (UPC) from their current operator. "
            "SkyLink submits the port-in request to the MNP clearinghouse within 2 hours of UPC receipt. "
            "The port completes within 7 working days. During the porting window, the subscriber retains "
            "full service on their current operator until the port is successful."
        ),
    },
    {
        "source_document": "SkyLink Subscriber Activation Guide v2.4",
        "domain": "activation",
        "chunk_index": 3,
        "chunk_text": (
            "Plan selection at activation: subscribers choose from 7 plan categories — "
            "SuperData (daily data quota, 100MB to 5GB/day), TalkMore (voice-heavy, up to unlimited calls), "
            "AllRounder (balanced combo), TextMore (SMS-heavy, up to unlimited SMS), "
            "Unlimited (no data or voice quota), SmartValue (budget, Rs 49–139), "
            "and International (includes ISD and roaming). Validity options are 28, 56, 84, 180, or 365 days."
        ),
    },
    # Support domain
    {
        "source_document": "SkyLink Customer Support Handbook v4.0",
        "domain": "support",
        "chunk_index": 0,
        "chunk_text": (
            "Subscriber identity verification for support calls: before any account modification, "
            "the support agent must verify the subscriber's MSISDN, registered name, and one of: "
            "date of birth, last recharge amount, or pin_code. For high-risk operations (SIM replacement, "
            "address change), a secondary OTP sent to the registered email is also required."
        ),
    },
    {
        "source_document": "SkyLink Customer Support Handbook v4.0",
        "domain": "support",
        "chunk_index": 1,
        "chunk_text": (
            "Network complaints are triaged by the subscriber's telecom circle. "
            "Support agents check the Network Operations Centre (NOC) dashboard for active outages in the circle. "
            "If a tower is under maintenance, the ETA for restoration is communicated. "
            "If no outage is recorded, the agent escalates to a field engineer for the cell_tower_id "
            "reported in the subscriber's last CDR."
        ),
    },
    {
        "source_document": "SkyLink Customer Support Handbook v4.0",
        "domain": "support",
        "chunk_index": 2,
        "chunk_text": (
            "Data speed complaints: subscribers on SuperData plans may experience speed throttling after "
            "exhausting their daily quota. The daily quota resets at midnight IST. "
            "Support can check the remaining data_limit_mb against consumed volume from billing_cdr_events. "
            "After quota exhaustion, data speed is capped at 64Kbps for SmartValue plans and 512Kbps for others."
        ),
    },
    {
        "source_document": "SkyLink Customer Support Handbook v4.0",
        "domain": "support",
        "chunk_index": 3,
        "chunk_text": (
            "Recharge options: subscribers can recharge via the self-care portal, USSD (*101#), "
            "authorised retail outlets, or net banking. Recharge updates the billing_wallet_balances table "
            "and sends a confirmation SMS with the new balance in rupees (balance_paise / 100). "
            "Recharge amounts must be in whole rupees; partial rupee recharges are not supported."
        ),
    },
    {
        "source_document": "SkyLink Customer Support Handbook v4.0",
        "domain": "support",
        "chunk_index": 4,
        "chunk_text": (
            "International calling activation: subscribers on standard plans must activate ISD calling separately. "
            "The International add-on can be purchased for Rs 99/month (9,900 paise) via the portal. "
            "Once activated, ISD calls are rated at 5 rupees per minute (500 paise/minute) to most destinations. "
            "Premium destinations (satellite phones, certain island nations) are rated at 15 rupees/minute."
        ),
    },
    # Compliance domain
    {
        "source_document": "SkyLink TRAI Compliance Manual v1.8",
        "domain": "compliance",
        "chunk_index": 0,
        "chunk_text": (
            "TRAI's Telecom Commercial Communications Customer Preference Regulations (TCCCPR) prohibit "
            "unsolicited commercial communications. SkyLink maintains a Do-Not-Disturb (DND) registry. "
            "Subscribers on DND must not receive promotional SMS or calls. Violations are logged and "
            "reported to TRAI quarterly. Repeat violations can result in a Rs 2.5 lakh penalty per instance."
        ),
    },
    {
        "source_document": "SkyLink TRAI Compliance Manual v1.8",
        "domain": "compliance",
        "chunk_index": 1,
        "chunk_text": (
            "Data localisation: all subscriber CDR data, billing records, and KYC documents must be stored "
            "on servers located in India per the TRAI data localisation directive. "
            "SkyLink's Postgres database is hosted in the ap-south-1 (Mumbai) region. "
            "CDR exports for analytics must be anonymised before transfer outside the country. "
            "Subscriber MSISDN and name fields must be masked in exported datasets."
        ),
    },
    {
        "source_document": "SkyLink TRAI Compliance Manual v1.8",
        "domain": "compliance",
        "chunk_index": 2,
        "chunk_text": (
            "CDR retention: TRAI mandates that CDR records be retained for a minimum of 2 years. "
            "SkyLink archives billing_cdr_events older than 1 year to cold storage while keeping "
            "the last 12 months in the live Postgres database for billing and fraud queries. "
            "Archived CDRs are available within 48 hours on request from law enforcement with a valid order."
        ),
    },
    # Network domain
    {
        "source_document": "SkyLink Network Operations Manual v6.3",
        "domain": "network",
        "chunk_index": 0,
        "chunk_text": (
            "SkyLink operates across all 22 Indian telecom circles: Andhra Pradesh, Assam, "
            "Bihar & Jharkhand, Chennai, Delhi & NCR, Gujarat, Haryana, Himachal Pradesh, "
            "Jammu & Kashmir, Karnataka, Kerala, Kolkata, Madhya Pradesh & Chhattisgarh, "
            "Maharashtra, Mumbai, North East, Orissa, Punjab, Rajasthan, Tamil Nadu, "
            "Uttar Pradesh, and West Bengal. Each circle has dedicated NOC capacity."
        ),
    },
    {
        "source_document": "SkyLink Network Operations Manual v6.3",
        "domain": "network",
        "chunk_index": 1,
        "chunk_text": (
            "Cell tower IDs follow the format TOWER_XXXXXXX where X is a 7-digit numeric identifier. "
            "Each tower serves a specific geographic cell within a telecom circle. "
            "A subscriber's CDR contains the cell_tower_id of the serving tower at the time of the session. "
            "Tower IDs are used for coverage complaint resolution, handoff analysis, and fraud location checks."
        ),
    },
    {
        "source_document": "SkyLink Network Operations Manual v6.3",
        "domain": "network",
        "chunk_index": 2,
        "chunk_text": (
            "Network type progression: SkyLink's network supports 2G, 3G, 4G, and 5G. "
            "Data CDRs record the network_type at the time of the session. "
            "5G coverage is available in metro circles (Delhi, Mumbai, Kolkata, Chennai, Bangalore). "
            "4G is the primary technology in Tier-2 and Tier-3 circles. "
            "2G and 3G are maintained for backward compatibility and rural coverage."
        ),
    },
    {
        "source_document": "SkyLink Network Operations Manual v6.3",
        "domain": "network",
        "chunk_index": 3,
        "chunk_text": (
            "CDR pipeline: call data records are generated at the network element, formatted as Kafka messages "
            "on the billing.cdr.raw topic, consumed by the CDR ingestion service, deduplicated using session_id, "
            "rated against the subscriber's active plan, and written to billing_cdr_events in Postgres. "
            "Dead-letter CDRs (failed after 3 attempts) are routed to billing.cdr.dlq for manual review."
        ),
    },
    {
        "source_document": "SkyLink Network Operations Manual v6.3",
        "domain": "network",
        "chunk_index": 4,
        "chunk_text": (
            "APN (Access Point Name) determines the data routing path for mobile data sessions. "
            "SkyLink's default APNs: skylink.internet (standard internet), skylink.mms (MMS messaging), "
            "skylink.wap (legacy WAP), skylink.data (enterprise), internet (generic). "
            "APN is recorded in the apn column of billing_cdr_events for data-type CDRs. "
            "IMEI is also recorded to support device compatibility and fraud analysis."
        ),
    },
    {
        "source_document": "SkyLink Network Operations Manual v6.3",
        "domain": "network",
        "chunk_index": 5,
        "chunk_text": (
            "Fair use policy: during peak hours (18:00–22:00 IST), subscribers on SmartValue and TalkMore plans "
            "may be subject to traffic deprioritisation when the circle utilisation exceeds 85%. "
            "SuperData and Unlimited subscribers are always served at full speed. "
            "Data throttling post-quota exhaustion caps speeds at 64Kbps (SmartValue) or 512Kbps (others). "
            "Throttling is applied per subscriber, not per session."
        ),
    },
]


# ── DB operations ─────────────────────────────────────────────────────────────

RULES_COPY_SQL = (
    "COPY sop_rules "
    "(id, rule_name, domain, trigger_condition, response_template, priority, is_active, created_at, modified_at) "
    "FROM STDIN"
)

CHUNKS_COPY_SQL = (
    "COPY sop_knowledge_chunks "
    "(id, source_document, chunk_text, chunk_index, domain, created_at, modified_at) "
    "FROM STDIN"
)


def seed_sop(conn: psycopg.Connection) -> tuple[int, int]:
    now = datetime.now(timezone.utc)

    with conn.cursor() as cur:
        cur.execute("DELETE FROM sop_knowledge_chunks")
        cur.execute("DELETE FROM sop_rules")
    conn.commit()

    with conn.cursor() as cur:
        with cur.copy(RULES_COPY_SQL) as copy:
            for r in _RULES:
                copy.write_row((
                    str(uuid.uuid4()),
                    r["rule_name"],
                    r["domain"],
                    r["trigger_condition"],
                    r["response_template"],
                    r["priority"],
                    True,
                    now,
                    now,
                ))
    conn.commit()

    with conn.cursor() as cur:
        with cur.copy(CHUNKS_COPY_SQL) as copy:
            for c in _CHUNKS:
                copy.write_row((
                    str(uuid.uuid4()),
                    c["source_document"],
                    c["chunk_text"],
                    c["chunk_index"],
                    c["domain"],
                    now,
                    now,
                ))
    conn.commit()

    return len(_RULES), len(_CHUNKS)


def main() -> None:
    log.info("Connecting to Postgres ...")
    with psycopg.connect(_conninfo(), autocommit=False) as conn:
        n_rules, n_chunks = seed_sop(conn)
    log.info("SOP seed complete — rules=%d knowledge_chunks=%d", n_rules, n_chunks)


if __name__ == "__main__":
    main()
