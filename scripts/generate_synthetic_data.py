"""Synthetic data generator: 300K subscribers + 5M CDRs for SkyLink telecom.

Run from the service_webapp directory:
    cd service_webapp && PYTHONPATH=src python ../scripts/generate_synthetic_data.py

Env overrides:
    SEED              (int, default 42)  — random seed for determinism
    SUBSCRIBER_COUNT  (int, default 300000)
    CDR_COUNT         (int, default 5000000)
    RECHARGE_ORDER_COUNT (int, default 2000)
    RECHARGE_PLAN_COUNT  (int, default 8)
    SUBSCRIBER_BATCH  (int, default 50000)
    CDR_BATCH         (int, default 100000)
    FRAUD_REPORT_PATH (str, default scripts/fraud_report.json)

Plans seed SQL: service_webapp/db/seed/seed_plans.sql — executed at the start
(NOT a Flyway migration; idempotent via ON CONFLICT DO NOTHING).

Writes scripts/fraud_report.json (list of fraud subscribers with description).
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import random
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd
import psycopg
from faker import Faker

sys.path.insert(0, str(Path(__file__).parent.parent / "service_webapp" / "src"))
from core.config import settings

# ── Configuration ─────────────────────────────────────────────────────────────

SEED = int(os.getenv("SEED", "42"))
SUBSCRIBER_COUNT = int(os.getenv("SUBSCRIBER_COUNT", "300000"))
CDR_COUNT = int(os.getenv("CDR_COUNT", "5000000"))
RECHARGE_ORDER_COUNT = int(os.getenv("RECHARGE_ORDER_COUNT", "2000"))
RECHARGE_PLAN_COUNT = int(os.getenv("RECHARGE_PLAN_COUNT", "8"))
SUBSCRIBER_BATCH = int(os.getenv("SUBSCRIBER_BATCH", "50000"))
CDR_BATCH = int(os.getenv("CDR_BATCH", "100000"))
FRAUD_FRACTION = 0.005
CDR_WINDOW_DAYS = 90
FRAUD_REPORT_PATH = Path(
    os.getenv(
        "FRAUD_REPORT_PATH", Path(__file__).parent.parent / "temp" / "fraud_report.json"
    )
)
SEED_PLANS_SQL = (
    Path(__file__).parent.parent / "service_webapp" / "db" / "seed" / "seed_plans.sql"
)

# ── Seeding ───────────────────────────────────────────────────────────────────

random.seed(SEED)
fake = Faker("en_IN")
Faker.seed(SEED)

# ── Logging ───────────────────────────────────────────────────────────────────

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

# ── Reference data ────────────────────────────────────────────────────────────

INDIAN_CIRCLES = [
    "Andhra Pradesh",
    "Assam",
    "Bihar & Jharkhand",
    "Chennai",
    "Delhi & NCR",
    "Gujarat",
    "Haryana",
    "Himachal Pradesh",
    "Jammu & Kashmir",
    "Karnataka",
    "Kerala",
    "Kolkata",
    "Madhya Pradesh & Chhattisgarh",
    "Maharashtra",
    "Mumbai",
    "North East",
    "Orissa",
    "Punjab",
    "Rajasthan",
    "Tamil Nadu",
    "Uttar Pradesh",
    "West Bengal",
]

APNS = ["skylink.internet", "skylink.data", "skylink.mms", "skylink.wap", "internet"]
OPERATORS = [
    "SkyLink-MH",
    "SkyLink-DL",
    "SkyLink-KA",
    "SkyLink-TN",
    "SkyLink-GJ",
    "SkyLink-UP",
]

# ── Helpers ───────────────────────────────────────────────────────────────────


def _conninfo() -> str:
    db = settings.db
    return (
        f"host={db.host} port={db.port} dbname={db.name} "
        f"user={db.user} password={db.password.get_secret_value()}"
    )


def _admin_conninfo() -> str:
    """Return a connection string using elevated credentials for truncation.

    billing_cdr_events/billing_transactions/billing_audit_log have DELETE revoked from
    sboai_app (V5 migration). Seed resets require a superuser connection. Falls back to
    the regular app user if SEED_ADMIN_USER is not set (useful in test environments where
    V5 hasn't run).
    """
    db = settings.db
    user = os.getenv("SEED_ADMIN_USER", db.user)
    password = os.getenv("SEED_ADMIN_PASSWORD", db.password.get_secret_value())
    return f"host={db.host} port={db.port} dbname={db.name} user={user} password={password}"


def _rand_msisdn(used: set[str]) -> str:
    while True:
        prefix = random.choice(["6", "7", "8", "9"])
        number = str(random.randint(10**8, 10**9 - 1))
        msisdn = f"91{prefix}{number}"
        if msisdn not in used:
            used.add(msisdn)
            return msisdn


def _rand_imei() -> str:
    return str(random.randint(10**14, 10**15 - 1))


def _rand_phone() -> str:
    prefix = random.choice(["6", "7", "8", "9"])
    return f"91{prefix}{random.randint(10**8, 10**9 - 1)}"


def _tower_id() -> str:
    return f"TOWER_{random.randint(1000000, 9999999)}"


# ── DB helpers ────────────────────────────────────────────────────────────────


def _seed_plans(conn: psycopg.Connection) -> None:
    """Execute seed_plans.sql (idempotent — ON CONFLICT DO NOTHING)."""
    sql = SEED_PLANS_SQL.read_text()
    with conn.cursor() as cur:
        cur.execute(sql)
    conn.commit()
    log.info("Plans seed SQL executed")


def _load_plans(conn: psycopg.Connection) -> pd.DataFrame:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id::text, price_paise, validity_days "
            "FROM plans_plans WHERE is_active = TRUE"
        )
        rows = cur.fetchall()
    return pd.DataFrame(rows, columns=["id", "price_paise", "validity_days"])


def _truncate_generated() -> None:
    # Append-only tables (billing_cdr_events, billing_transactions, billing_audit_log)
    # have DELETE revoked from sboai_app (V5 grants), so the reset runs over the admin
    # connection.
    #
    # identity_subscribers is referenced by 19 dependent tables (plans_subscriptions,
    # billing_wallet_balances, billing_cdr_events, billing_transactions, support_tickets,
    # notifications_*, fraud_*, segmentation_*, recharge_*, identity_registrations, ...)
    # via RESTRICT foreign keys — none use ON DELETE CASCADE. Because the script
    # regenerates subscriber UUIDs every run, every dependent row would otherwise be
    # orphaned and block the parent delete (ForeignKeyViolation on
    # plans_subscriptions_subscriber_id_fkey). TRUNCATE ... CASCADE atomically clears
    # identity_subscribers AND all of its dependents in one shot, giving a clean slate.
    # UUID PKs have no sequences, so RESTART IDENTITY is unnecessary. plans_plans is NOT
    # a dependent (the FK points the other way) and is preserved.
    with psycopg.connect(_admin_conninfo(), autocommit=False) as admin_conn:
        with admin_conn.cursor() as cur:
            cur.execute("TRUNCATE identity_subscribers CASCADE")
        admin_conn.commit()
    log.info("Truncated identity_subscribers and all dependent tables (CASCADE)")


# ── Subscriber generation ─────────────────────────────────────────────────────

SUB_COPY_SQL = (
    "COPY identity_subscribers "
    "(id, msisdn, subscriber_name, email, status, plan_id, "
    "address_line1, address_line2, city, state, pin_code, "
    "created_at, modified_at) "
    "FROM STDIN"
)


def generate_subscribers(conn: psycopg.Connection, plans_df: pd.DataFrame) -> pd.DataFrame:
    """Insert subscribers; return DataFrame with identity and activation metadata."""
    log.info("Generating %d subscribers ...", SUBSCRIBER_COUNT)
    now = datetime.now(UTC)
    plan_ids = plans_df["id"].tolist()

    msisdn_set: set[str] = set()
    all_rows: list[tuple] = []
    sub_meta: list[dict] = []

    def _flush_batch(batch: list[tuple]) -> None:
        with conn.cursor() as cur:
            with cur.copy(SUB_COPY_SQL) as copy:
                for row in batch:
                    copy.write_row(row)
        conn.commit()

    pending: list[tuple] = []
    for i in range(SUBSCRIBER_COUNT):
        sub_id = str(uuid.uuid4())
        msisdn = _rand_msisdn(msisdn_set)
        name = fake.name()
        email = fake.email()
        plan_id = random.choice(plan_ids)
        activated_at = now - timedelta(seconds=random.randint(0, 365 * 24 * 3600))

        # Indian address fields
        addr1 = fake.street_address()[:200]
        addr2 = ""
        city = fake.city()[:100]
        state = fake.state()[:100]
        pin = fake.postcode()[:10]

        row = (
            sub_id,
            msisdn,
            name,
            email,
            "active",
            plan_id,
            addr1,
            addr2,
            city,
            state,
            pin,
            activated_at,
            now,
        )
        pending.append(row)
        sub_meta.append({"id": sub_id, "msisdn": msisdn, "plan_id": plan_id, "created_at": activated_at})

        if len(pending) == SUBSCRIBER_BATCH or i == SUBSCRIBER_COUNT - 1:
            _flush_batch(pending)
            log.info("  subscribers: %d / %d", i + 1, SUBSCRIBER_COUNT)
            pending = []

    all_rows = sub_meta  # keep for wallet + CDR generation
    return pd.DataFrame(all_rows, columns=["id", "msisdn", "plan_id", "created_at"])


# ── Wallet balance generation ─────────────────────────────────────────────────

WALLET_COPY_SQL = (
    "COPY billing_wallet_balances "
    "(id, subscriber_id, msisdn, balance_paise, created_at, modified_at) "
    "FROM STDIN"
)


def generate_wallets(
    conn: psycopg.Connection, subs_df: pd.DataFrame, plans_df: pd.DataFrame
) -> None:
    """Generate wallet balance rows for all synthetic subscribers."""
    log.info("Generating wallet balances ...")
    price_map = plans_df.set_index("id")["price_paise"].to_dict()
    now = datetime.now(UTC)

    pending: list[tuple] = []

    def _flush(batch: list[tuple]) -> None:
        with conn.cursor() as cur:
            with cur.copy(WALLET_COPY_SQL) as copy:
                for row in batch:
                    copy.write_row(row)
        conn.commit()

    for _, row in subs_df.iterrows():
        balance = price_map.get(row["plan_id"], 9900)
        pending.append(
            (str(uuid.uuid4()), row["id"], row["msisdn"], int(balance), now, now)
        )
        if len(pending) == SUBSCRIBER_BATCH:
            _flush(pending)
            pending = []
    if pending:
        _flush(pending)
    log.info("  wallets done")


# ── Plan subscription generation ──────────────────────────────────────────────


def generate_plan_subscriptions(conn: psycopg.Connection) -> int:
    """Ensure every plan-bearing subscriber has an active plans_subscriptions row.

    Uses each subscriber's assigned ``identity_subscribers.plan_id``; the subscription
    window starts after the subscriber activation timestamp and remains active at seed
    time, so plan history never predates activation. Idempotent — skips subscribers
    that already have an active subscription. Returns the number of rows inserted.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            WITH subscription_windows AS (
                SELECT
                    s.id AS subscriber_id,
                    s.plan_id,
                    GREATEST(
                        s.created_at,
                        NOW() - (random() * GREATEST(p.validity_days - 1, 0)) * INTERVAL '1 day'
                    ) AS start_date,
                    p.validity_days
                  FROM identity_subscribers s
                  JOIN plans_plans p ON p.id = s.plan_id
                 WHERE s.plan_id IS NOT NULL
                   AND NOT EXISTS (
                       SELECT 1 FROM plans_subscriptions ps
                        WHERE ps.subscriber_id = s.id AND ps.status = 'active'
                   )
            )
            INSERT INTO plans_subscriptions
                (id, subscriber_id, plan_id, start_date, end_date, status, created_at, modified_at)
            SELECT gen_random_uuid(), subscriber_id, plan_id,
                   start_date,
                   start_date + validity_days * INTERVAL '1 day',
                   'active', start_date, NOW()
              FROM subscription_windows
            """
        )
        inserted = cur.rowcount
    conn.commit()
    log.info("  active plan_subscriptions ensured for %d subscribers", inserted)
    return inserted


# ── Recharge order generation ─────────────────────────────────────────────────

RECHARGE_COPY_SQL = (
    "COPY recharge_orders "
    "(subscriber_id, plan_id, amount_paise, idempotency_key, status, completed_at, created_at, modified_at) "
    "FROM STDIN"
)


def generate_recharge_orders(
    conn: psycopg.Connection,
    subs_df: pd.DataFrame,
    plans_df: pd.DataFrame,
) -> int:
    """Generate completed recharge orders for forecastable plan-demand history.

    Orders are restricted to the last 90 days and each order timestamp is after the
    chosen subscriber's activation timestamp. A small set of plans receives orders over
    many distinct days so the Holt-Winters forecaster has enough non-empty history.
    """
    if RECHARGE_ORDER_COUNT <= 0:
        log.info("Skipping recharge order generation (RECHARGE_ORDER_COUNT=0)")
        return 0

    log.info(
        "Generating %d completed recharge orders across up to %d plans ...",
        RECHARGE_ORDER_COUNT,
        RECHARGE_PLAN_COUNT,
    )
    now = datetime.now(UTC)
    window_start = now - timedelta(days=CDR_WINDOW_DAYS)
    plans_by_id = plans_df.set_index("id")
    plan_ids = plans_df["id"].tolist()
    established_plan_ids = subs_df.loc[subs_df["created_at"] <= window_start, "plan_id"].drop_duplicates().tolist()
    candidate_plan_ids = established_plan_ids or plan_ids
    forecast_plan_ids = random.sample(candidate_plan_ids, min(RECHARGE_PLAN_COUNT, len(candidate_plan_ids)))
    orders_per_plan = max(1, RECHARGE_ORDER_COUNT // len(forecast_plan_ids))
    remainder = RECHARGE_ORDER_COUNT % len(forecast_plan_ids)
    inserted = 0
    pending: list[tuple] = []

    def _flush(batch: list[tuple]) -> None:
        with conn.cursor() as cur:
            with cur.copy(RECHARGE_COPY_SQL) as copy:
                for row in batch:
                    copy.write_row(row)
        conn.commit()

    for plan_idx, plan_id in enumerate(forecast_plan_ids):
        plan_subs = subs_df[subs_df["plan_id"] == plan_id]
        if plan_subs.empty:
            continue
        established_subs = plan_subs[plan_subs["created_at"] <= window_start]
        if not established_subs.empty:
            plan_subs = established_subs.sample(n=min(50, len(established_subs)), random_state=SEED + plan_idx)

        plan = plans_by_id.loc[plan_id]
        amount_paise = int(plan["price_paise"])
        target_count = orders_per_plan + (1 if plan_idx < remainder else 0)
        active_days = random.sample(range(CDR_WINDOW_DAYS), min(45, CDR_WINDOW_DAYS))

        for order_idx in range(target_count):
            day_offset = active_days[order_idx % len(active_days)]
            completed_at = window_start + timedelta(
                days=day_offset,
                seconds=random.randint(8 * 3600, 23 * 3600),
            )
            eligible = plan_subs[plan_subs["created_at"] <= completed_at]
            if eligible.empty:
                continue

            sub = eligible.sample(n=1, random_state=SEED + inserted).iloc[0]
            created_at = completed_at - timedelta(minutes=random.randint(1, 20))
            idempotency_key = f"synthetic-recharge-{plan_idx}-{order_idx}-{sub['id']}"
            pending.append(
                (
                    sub["id"],
                    plan_id,
                    amount_paise,
                    idempotency_key[:100],
                    "completed",
                    completed_at,
                    created_at,
                    completed_at,
                )
            )
            inserted += 1

            if len(pending) == SUBSCRIBER_BATCH:
                _flush(pending)
                pending = []

    if pending:
        _flush(pending)

    log.info("  recharge_orders completed: %d", inserted)
    return inserted


# ── CDR generation ────────────────────────────────────────────────────────────

CDR_COPY_SQL = (
    "COPY billing_cdr_events "
    "(session_id, subscriber_id, cdr_type, telecom_circle, cell_tower_id, roaming, "
    "cost_paise, status, fraud_flag, start_time, end_time, "
    "from_number, to_number, call_direction, duration_seconds, call_status, "
    "message_direction, sms_status, "
    "network_type, downloaded_mb, uploaded_mb, volume_mb, apn, imei, operator_id) "
    "FROM STDIN"
)

FRAUD_SIGNAL_NAMES = [
    "velocity_burst",
    "sim_swap",
    "roaming_abuse",
    "unique_destinations",
    "multi_tower",
]


def _build_fraud_plan(subscriber_ids: list[str]) -> tuple[dict, dict]:
    """Return (fraud_meta, fraud_signal_map).

    fraud_meta: {sub_id: {signal: str, fraud_day: datetime|None, swap_point: datetime|None, ...}}
    fraud_signal_map: {sub_id: signal_name}
    """
    n_fraud = max(1, int(len(subscriber_ids) * FRAUD_FRACTION))
    fraud_subs = random.sample(subscriber_ids, n_fraud)

    signal_cycle = FRAUD_SIGNAL_NAMES * (n_fraud // len(FRAUD_SIGNAL_NAMES) + 1)
    random.shuffle(signal_cycle)

    fraud_meta: dict = {}
    for idx, sub_id in enumerate(fraud_subs):
        signal = signal_cycle[idx]
        meta: dict = {"signal": signal}
        if signal == "velocity_burst":
            # concentrated burst day (days 10..80 to avoid boundary edge)
            meta["fraud_day_offset"] = random.randint(10, 80)
        elif signal == "sim_swap":
            # IMEI changes at day 45
            meta["swap_day_offset"] = random.randint(30, 60)
            meta["imei_before"] = _rand_imei()
            meta["imei_after"] = _rand_imei()
        elif signal == "roaming_abuse":
            # heavy roaming, random circle set
            meta["roaming_circles"] = random.sample(
                INDIAN_CIRCLES, random.randint(5, 10)
            )
        # unique_destinations and multi_tower: patterns applied inline per CDR row
        fraud_meta[sub_id] = meta

    fraud_signal_map = {sub_id: meta["signal"] for sub_id, meta in fraud_meta.items()}
    return fraud_meta, fraud_signal_map


def _cdr_row(
    sub_id: str,
    start: datetime,
    fraud_flag: bool,
    cdr_type: str,
    fraud_meta: dict | None,
    unique_dest_pool: list[str] | None,
    multi_tower_seq: list[str] | None,
    tower_idx_ref: list[int] | None,
) -> tuple:
    """Build a single CDR row (no id — DB assigns uuid_generate_v7())."""
    session_id = str(uuid.uuid4())
    circle = random.choice(INDIAN_CIRCLES)
    tower = _tower_id()
    roaming = False

    from_num: str | None = None
    to_num: str | None = None
    call_dir: str | None = None
    duration: int | None = None
    call_status: str | None = None
    msg_dir: str | None = None
    sms_status: str | None = None
    net_type: str | None = None
    dl_mb: float | None = None
    ul_mb: float | None = None
    vol_mb: float | None = None
    apn: str | None = None
    imei: str | None = None
    op_id: str | None = None
    end_time: datetime | None = None
    cost: int = 0

    signal = fraud_meta.get("signal") if fraud_meta else None

    # ── Apply fraud signal modifiers ──────────────────────────────────────────
    if signal == "roaming_abuse" and fraud_flag:
        circles = fraud_meta.get("roaming_circles", INDIAN_CIRCLES)
        circle = random.choice(circles)
        roaming = True
    elif (
        signal == "multi_tower"
        and multi_tower_seq is not None
        and tower_idx_ref is not None
    ):
        # Rapidly cycle through 5 distinct towers
        tower = multi_tower_seq[tower_idx_ref[0] % len(multi_tower_seq)]
        tower_idx_ref[0] += 1

    # ── Type-specific columns ─────────────────────────────────────────────────
    if cdr_type == "voice":
        duration = random.randint(10, 3600)
        end_time = start + timedelta(seconds=duration)
        from_num = _rand_phone()
        # Fraud: unique destinations = many different to_number values
        if signal == "unique_destinations" and unique_dest_pool and fraud_flag:
            to_num = unique_dest_pool[random.randint(0, len(unique_dest_pool) - 1)]
        else:
            to_num = _rand_phone()
        call_dir = random.choice(["MO", "MT"])
        call_status = random.choices(
            ["answered", "no_answer", "busy", "failed"],
            weights=[70, 15, 10, 5],
        )[0]
        cost = duration * 50  # 50 paise/second

    elif cdr_type == "data":
        dl = round(random.uniform(0.1, 500.0), 3)
        ul = round(random.uniform(0.05, dl * 0.3), 3)
        vol = round(dl + ul, 3)
        dl_mb, ul_mb, vol_mb = dl, ul, vol
        session_mins = random.randint(1, 120)
        end_time = start + timedelta(minutes=session_mins)
        net_type = random.choices(["2G", "3G", "4G", "5G"], weights=[5, 15, 50, 30])[0]
        apn = random.choice(APNS)
        imei = _rand_imei()
        op_id = random.choice(OPERATORS)
        cost = int(vol * 200)  # 200 paise/MB

    else:  # sms
        end_time = start + timedelta(seconds=random.randint(1, 5))
        msg_dir = random.choice(["MO", "MT"])
        sms_status = random.choices(
            ["delivered", "failed", "pending"],
            weights=[90, 6, 4],
        )[0]
        cost = 100  # 100 paise flat

    # SIM-swap: apply IMEI based on side of swap_day_offset
    if signal == "sim_swap" and fraud_meta:
        swap_off = fraud_meta.get("swap_day_offset", 45)
        base = datetime.now(UTC) - timedelta(days=CDR_WINDOW_DAYS)
        swap_point = base + timedelta(days=swap_off)
        chosen_imei = (
            fraud_meta["imei_after"]
            if start > swap_point
            else fraud_meta["imei_before"]
        )
        if cdr_type == "data":
            imei = chosen_imei

    return (
        session_id,
        sub_id,
        cdr_type,
        circle,
        tower,
        roaming,
        cost,
        "pending",
        fraud_flag,
        start,
        end_time,
        from_num,
        to_num,
        call_dir,
        duration,
        call_status,
        msg_dir,
        sms_status,
        net_type,
        dl_mb,
        ul_mb,
        vol_mb,
        apn,
        imei,
        op_id,
    )


def generate_cdrs(
    conn: psycopg.Connection,
    sub_ids: list[str],
    fraud_meta: dict,
    activation_by_subscriber: dict[str, datetime],
) -> dict[str, int]:
    """Generate 5M CDRs in two passes. Returns fraud_flag counts by subscriber."""
    now = datetime.now(UTC)
    base_time = now - timedelta(days=CDR_WINDOW_DAYS)

    fraud_sub_set = set(fraud_meta.keys())
    n_velocity = sum(1 for m in fraud_meta.values() if m["signal"] == "velocity_burst")
    velocity_burst_per = 220

    # Pass-1 normal CDR count (reserve budget for velocity bursts)
    velocity_total = n_velocity * velocity_burst_per
    pass1_count = CDR_COUNT - velocity_total
    log.info(
        "CDR generation: pass-1=%d, velocity burst=%d, total=%d",
        pass1_count,
        velocity_total,
        CDR_COUNT,
    )

    # Pre-build unique-dest pools and multi-tower sequences for relevant fraud subs
    unique_dest_pools: dict[str, list[str]] = {}
    multi_tower_seqs: dict[str, list[str]] = {}
    for sub_id, meta in fraud_meta.items():
        if meta["signal"] == "unique_destinations":
            unique_dest_pools[sub_id] = [_rand_phone() for _ in range(200)]
        elif meta["signal"] == "multi_tower":
            multi_tower_seqs[sub_id] = [_tower_id() for _ in range(5)]

    tower_idx_tracking: dict[str, list[int]] = {
        sub_id: [0] for sub_id in multi_tower_seqs
    }

    fraud_flagged_counts: dict[str, int] = {}

    def _random_cdr_start(sub_id: str) -> datetime:
        earliest = max(base_time, activation_by_subscriber.get(sub_id, base_time))
        span_seconds = max(0, int((now - earliest).total_seconds()))
        return earliest + timedelta(seconds=random.randint(0, span_seconds))

    def _flush_cdr_batch(batch: list[tuple]) -> None:
        with conn.cursor() as cur:
            with cur.copy(CDR_COPY_SQL) as copy:
                for row in batch:
                    copy.write_row(row)
        conn.commit()

    # ── Pass 1: normal CDRs ───────────────────────────────────────────────────
    pending: list[tuple] = []
    for i in range(pass1_count):
        sub_id = sub_ids[i % len(sub_ids)]
        start = _random_cdr_start(sub_id)
        cdr_type = random.choices(["voice", "data", "sms"], weights=[60, 30, 10])[0]

        is_fraud_sub = sub_id in fraud_sub_set
        meta = fraud_meta.get(sub_id)
        fraud_flag = False

        if is_fraud_sub and meta:
            signal = meta["signal"]
            if signal == "sim_swap":
                swap_off = meta.get("swap_day_offset", 45)
                swap_point = base_time + timedelta(days=swap_off)
                fraud_flag = start > swap_point
            elif signal == "roaming_abuse":
                fraud_flag = True
            elif signal == "unique_destinations":
                fraud_flag = cdr_type == "voice"
            elif signal == "multi_tower":
                fraud_flag = True

        row = _cdr_row(
            sub_id,
            start,
            fraud_flag,
            cdr_type,
            meta if is_fraud_sub else None,
            unique_dest_pools.get(sub_id),
            multi_tower_seqs.get(sub_id),
            tower_idx_tracking.get(sub_id),
        )
        pending.append(row)
        if fraud_flag:
            fraud_flagged_counts[sub_id] = fraud_flagged_counts.get(sub_id, 0) + 1

        if len(pending) == CDR_BATCH:
            _flush_cdr_batch(pending)
            log.info("  CDRs pass-1: %d / %d", i + 1, pass1_count)
            pending = []

    if pending:
        _flush_cdr_batch(pending)

    # ── Pass 2: velocity burst CDRs ───────────────────────────────────────────
    velocity_subs = [
        s for s, m in fraud_meta.items() if m["signal"] == "velocity_burst"
    ]
    log.info("CDR pass-2: velocity bursts for %d subscribers", len(velocity_subs))
    pending = []
    for sub_id in velocity_subs:
        meta = fraud_meta[sub_id]
        day_off = meta.get("fraud_day_offset", 20)
        burst_base = max(base_time + timedelta(days=day_off), activation_by_subscriber.get(sub_id, base_time))
        burst_window_seconds = max(0, min(86400, int((now - burst_base).total_seconds())))
        for j in range(velocity_burst_per):
            # All burst CDRs within the same 24h window
            start = burst_base + timedelta(seconds=random.randint(0, burst_window_seconds))
            cdr_type = random.choices(["voice", "data", "sms"], weights=[70, 20, 10])[0]
            row = _cdr_row(sub_id, start, True, cdr_type, meta, None, None, None)
            pending.append(row)
            fraud_flagged_counts[sub_id] = fraud_flagged_counts.get(sub_id, 0) + 1
            if len(pending) == CDR_BATCH:
                _flush_cdr_batch(pending)
                log.info("  CDRs pass-2 flush")
                pending = []

    if pending:
        _flush_cdr_batch(pending)

    return fraud_flagged_counts


# ── Fraud report ──────────────────────────────────────────────────────────────

_SIGNAL_DESC: dict[str, str] = {
    "velocity_burst": "Generated >200 calls/data sessions in a single day (CDR velocity fraud).",
    "sim_swap": "IMEI changed mid-history — classic SIM-swap signal; post-swap CDRs flagged.",
    "roaming_abuse": "Roaming usage across 5+ telecom circles without an active roaming plan.",
    "unique_destinations": "Called >50 unique destination numbers within a 24-hour window (bulk dialler).",
    "multi_tower": "Connected to 5 distinct cell towers within 1 hour (impossible physical movement).",
}


def write_fraud_report(
    fraud_meta: dict,
    subs_df: pd.DataFrame,
    fraud_flagged_counts: dict[str, int],
) -> None:
    """Write a JSON report describing generated fraud subscribers."""
    msisdn_map = subs_df.set_index("id")["msisdn"].to_dict()
    report = []
    for sub_id, meta in fraud_meta.items():
        signal = meta["signal"]
        flagged = fraud_flagged_counts.get(sub_id, 0)
        report.append(
            {
                "subscriber_id": sub_id,
                "msisdn": msisdn_map.get(sub_id, "unknown"),
                "fraud_types": [signal],
                "flagged_cdr_count": flagged,
                "description": _SIGNAL_DESC.get(signal, signal),
            }
        )

    FRAUD_REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(FRAUD_REPORT_PATH, "w") as f:
        json.dump(report, f, indent=2, default=str)
    log.info(
        "Fraud report written to %s (%d subscribers)", FRAUD_REPORT_PATH, len(report)
    )


# ── Main ──────────────────────────────────────────────────────────────────────


def _has_subscribers(conn: psycopg.Connection) -> bool:
    with conn.cursor() as cur:
        cur.execute("SELECT EXISTS (SELECT 1 FROM identity_subscribers LIMIT 1)")
        return cur.fetchone()[0]


def main() -> None:
    """Run the synthetic data generation workflow."""
    parser = argparse.ArgumentParser(
        description="Synthetic data generator for SkyLink."
    )
    parser.add_argument(
        "--skip-truncate-if-pre-seeded",
        action="store_true",
        help="Skip all seeding steps if subscriber data already exists",
    )
    args = parser.parse_args()

    log.info("Connecting to Postgres ...")
    with psycopg.connect(_conninfo(), autocommit=False) as conn:
        if args.skip_truncate_if_pre_seeded and _has_subscribers(conn):
            log.info("Subscriber data already exists — skipping seed (--skip-truncate)")
            return

        log.info("Seeding plans from %s ...", SEED_PLANS_SQL)
        _seed_plans(conn)

        log.info("Truncating generated tables ...")
        _truncate_generated()

        log.info("Loading plans ...")
        plans_df = _load_plans(conn)
        if plans_df.empty:
            log.error(
                "No active plans found — check service_webapp/db/seed/seed_plans.sql"
            )
            sys.exit(1)
        log.info("  loaded %d plans", len(plans_df))

        subs_df = generate_subscribers(conn, plans_df)
        generate_wallets(conn, subs_df, plans_df)
        generate_plan_subscriptions(conn)
        recharge_count = generate_recharge_orders(conn, subs_df, plans_df)

        sub_ids = subs_df["id"].tolist()
        activation_by_subscriber = subs_df.set_index("id")["created_at"].to_dict()
        fraud_meta, _ = _build_fraud_plan(sub_ids)

        fraud_flagged_counts = generate_cdrs(conn, sub_ids, fraud_meta, activation_by_subscriber)

    write_fraud_report(fraud_meta, subs_df, fraud_flagged_counts)

    total_flagged = len(fraud_meta)
    log.info(
        "Seed complete — plans=%d subscribers=%d recharge_orders=%d cdrs=%d fraud_flagged_subscribers=%d",
        len(plans_df),
        len(subs_df),
        recharge_count,
        CDR_COUNT,
        total_flagged,
    )


if __name__ == "__main__":
    main()
