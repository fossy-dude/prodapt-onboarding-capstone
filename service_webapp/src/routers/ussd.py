"""USSD session handler and menu router (Story 4.4).

POST /api/v1/ussd/callback — no JWT auth (telecom operator inbound callback).

Session state is stored as a Valkey HASH ``session:{session_id}`` with a
30-minute TTL reset on every response. MSISDN identity comes from the
request body and is validated against ``identity_subscribers``.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from uuid import UUID as _UUID

from fastapi import APIRouter, Request
from fastapi.responses import Response

from db.billing.queries import get_usage_for_period
from db.identity.queries import get_subscriber_by_msisdn
from db.notifications.commands import upsert_preference
from db.notifications.queries import get_preferences
from db.plans.queries import get_active_subscription, get_available_plans
from db.recharge.commands import complete_recharge_transaction, create_recharge_order
from models.ussd import UssdCallbackRequest  # noqa: TC001

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/ussd", tags=["ussd"])

_SESSION_TTL = 1800  # 30 minutes

_ROOT_MENU = "Welcome\n1. Balance\n2. My Plan\n3. Recharge\n4. Notifications\n0. Exit"

_NOTIFICATION_TYPES = [
    "LOW_BALANCE",
    "BALANCE_DEPLETED",
    "PLAN_EXPIRY_REMINDER",
    "DATA_NUDGE",
]

_NOTIFICATION_LABELS = {
    "LOW_BALANCE": "Low Balance",
    "BALANCE_DEPLETED": "Bal Depleted",
    "PLAN_EXPIRY_REMINDER": "Plan Expiry",
    "DATA_NUDGE": "Data Nudge",
}


def _db(request: Request):
    db = getattr(request.app.state, "db_adapter", None)
    if db is None:
        raise RuntimeError("Database adapter is not initialised.")
    return db


def _cache(request: Request):
    cache = getattr(request.app.state, "cache_adapter", None)
    if cache is None:
        raise RuntimeError("Cache adapter is not initialised.")
    return cache


def _plain(text: str) -> Response:
    return Response(content=text, media_type="text/plain")


def _format_notifications_menu(prefs: list) -> str:
    pref_map: dict[str, bool] = {}
    for p in prefs:
        if isinstance(p, dict):
            pref_map[p["notification_type"]] = p["is_enabled"]
        else:
            pref_map[p.notification_type] = p.is_enabled

    lines = ["Notifications (toggle):"]
    for i, ntype in enumerate(_NOTIFICATION_TYPES, start=1):
        status = "ON" if pref_map.get(ntype, True) else "OFF"
        lines.append(f"{i}. {_NOTIFICATION_LABELS[ntype]}: {status}")
    lines.append("0. Back")
    return "\n".join(lines)


async def _get_plan_by_id(conn, plan_id: str) -> dict | None:
    cur = await conn.execute(
        """
        SELECT id, plan_name, price_paise, data_limit_mb, voice_minutes, sms_count
          FROM plans_plans
         WHERE id = %s::uuid AND is_active = TRUE
        """,
        (plan_id,),
    )
    row = await cur.fetchone()
    if row is None:
        return None
    return {
        "id": str(row[0]),
        "plan_name": row[1],
        "price_paise": row[2],
        "data_limit_mb": row[3],
        "voice_minutes": row[4],
        "sms_count": row[5],
    }


async def _get_primary_payment_method(conn, subscriber_id: str) -> dict | None:
    cur = await conn.execute(
        """
        SELECT id, method_type, last_four
          FROM recharge_payment_methods
         WHERE subscriber_id = %s::uuid AND is_active = TRUE
         ORDER BY created_at ASC
         LIMIT 1
        """,
        (subscriber_id,),
    )
    row = await cur.fetchone()
    if row is None:
        return None
    return {"id": str(row[0]), "method_type": row[1], "last_four": row[2]}


@router.post("/callback", status_code=200)
async def ussd_callback(req: UssdCallbackRequest, request: Request) -> Response:
    """Handle USSD callback from telecom operator.

    Returns ``text/plain`` USSD menu string (HTTP 200). No auth — MSISDN
    identity is validated against ``identity_subscribers`` inline.
    """
    db = _db(request)
    cache = _cache(request)

    session_key = f"session:{req.session_id}"

    # Load existing session or start fresh
    session: dict[str, str] = await cache.hgetall(session_key)
    menu_state = session.get("menu_state", "root")

    # Cross-check: if session has an msisdn, it must match the request msisdn
    if "msisdn" in session and session["msisdn"] != req.msisdn:
        await cache.delete(session_key)
        return _plain("Session invalid.\n0. Exit")

    # Look up subscriber by MSISDN
    async with db.transaction() as conn:
        subscriber = await get_subscriber_by_msisdn(conn, req.msisdn)

    if subscriber is None:
        # AC #10: unknown MSISDN — do not create a ghost session
        return _plain("Unknown subscriber.\n0. Exit")

    subscriber_id = subscriber["id"]

    # Store subscriber_id and msisdn in session on first request
    if "subscriber_id" not in session:
        session["subscriber_id"] = subscriber_id
        session["msisdn"] = req.msisdn
    else:
        subscriber_id = session["subscriber_id"]

    text, updated_state = await _dispatch(
        menu_state=menu_state,
        button=req.button_pressed,
        msisdn=req.msisdn,
        subscriber_id=subscriber_id,
        session=session,
        db=db,
        cache=cache,
        session_key=session_key,
    )

    if updated_state is None:
        try:
            await cache.delete(session_key)
        except Exception:
            logger.warning("USSD session delete failed for session_key=%s", session_key)
    else:
        updated_state["subscriber_id"] = subscriber_id
        updated_state["msisdn"] = req.msisdn
        try:
            await cache.hset(session_key, updated_state, ex=_SESSION_TTL)
        except Exception:
            logger.warning("USSD session save failed for session_key=%s", session_key)

    return _plain(text)


async def _dispatch(
    menu_state: str,
    button: str,
    msisdn: str,
    subscriber_id: str,
    session: dict[str, str],
    db,
    cache,
    session_key: str,
) -> tuple[str, dict[str, str] | None]:
    """Route (menu_state, button_pressed) to handler; return (text, new_session_state).

    Returns ``(text, None)`` to signal session termination (delete the key).
    """
    # ------------------------------------------------------------------ root
    if menu_state == "root":
        if button == "":
            return _ROOT_MENU, {"menu_state": "root"}

        if button == "0":
            return "Thank you. Goodbye.", None

        if button == "1":
            return await _handle_balance(msisdn, subscriber_id, db, cache)

        if button == "2":
            return await _handle_plan(subscriber_id, db)

        if button == "3":
            return await _handle_recharge_select(subscriber_id, db)

        if button == "4":
            return await _handle_notifications(subscriber_id, db)

        # Invalid input at root — re-display root menu
        return _ROOT_MENU, {"menu_state": "root"}

    # -------------------------------------------------------------- balance
    if menu_state == "balance":
        if button == "0":
            return _ROOT_MENU, {"menu_state": "root"}
        return await _handle_balance(msisdn, subscriber_id, db, cache)

    # ----------------------------------------------------------------- plan
    if menu_state == "plan":
        if button == "0":
            return _ROOT_MENU, {"menu_state": "root"}
        return await _handle_plan(subscriber_id, db)

    # -------------------------------------------------------- recharge_select
    if menu_state == "recharge_select":
        if button == "0":
            return _ROOT_MENU, {"menu_state": "root"}

        plan_ids_str = session.get("plan_ids", "")
        plan_ids = [p for p in plan_ids_str.split(",") if p]

        try:
            idx = int(button) - 1
        except ValueError:
            return await _handle_recharge_select(subscriber_id, db)

        if 0 <= idx < len(plan_ids):
            selected_plan_id = plan_ids[idx]
            async with db.transaction() as conn:
                plan = await _get_plan_by_id(conn, selected_plan_id)
            if plan is None:
                return await _handle_recharge_select(subscriber_id, db)
            price_inr = plan["price_paise"] / 100
            text = f"{plan['plan_name']} - ₹{price_inr:.2f}\nPress 1 to confirm\n0. Back"
            return text, {
                "menu_state": "recharge_confirm",
                "plan_ids": plan_ids_str,
                "selected_plan_id": selected_plan_id,
            }

        # Out of range — re-show plan list
        return await _handle_recharge_select(subscriber_id, db)

    # ------------------------------------------------------- recharge_confirm
    if menu_state == "recharge_confirm":
        if button == "0":
            return _ROOT_MENU, {"menu_state": "root"}

        if button == "1":
            selected_plan_id = session.get("selected_plan_id", "")
            return await _handle_recharge_confirm(
                subscriber_id=subscriber_id,
                msisdn=msisdn,
                plan_id=selected_plan_id,
                session_key=session_key,
                db=db,
                cache=cache,
            )

        # Invalid — re-show confirm screen using stored plan
        selected_plan_id = session.get("selected_plan_id", "")
        plan_ids_str = session.get("plan_ids", "")
        if selected_plan_id:
            async with db.transaction() as conn:
                plan = await _get_plan_by_id(conn, selected_plan_id)
            if plan:
                price_inr = plan["price_paise"] / 100
                text = f"{plan['plan_name']} - ₹{price_inr:.2f}\nPress 1 to confirm\n0. Back"
                return text, {
                    "menu_state": "recharge_confirm",
                    "plan_ids": plan_ids_str,
                    "selected_plan_id": selected_plan_id,
                }
        return _ROOT_MENU, {"menu_state": "root"}

    # --------------------------------------------------------- notifications
    if menu_state == "notifications":
        if button == "0":
            return _ROOT_MENU, {"menu_state": "root"}

        try:
            idx = int(button) - 1
        except ValueError:
            return await _handle_notifications(subscriber_id, db)

        if 0 <= idx < len(_NOTIFICATION_TYPES):
            ntype = _NOTIFICATION_TYPES[idx]
            async with db.transaction() as conn:
                prefs = await get_preferences(conn, subscriber_id)
                pref_map = {
                    (p["notification_type"] if isinstance(p, dict) else p.notification_type): (
                        p["is_enabled"] if isinstance(p, dict) else p.is_enabled
                    )
                    for p in prefs
                }
                current = pref_map.get(ntype, True)
                await upsert_preference(conn, subscriber_id, ntype, not current)
                updated_prefs = await get_preferences(conn, subscriber_id)
            text = _format_notifications_menu(updated_prefs)
            return text, {"menu_state": "notifications"}

        return await _handle_notifications(subscriber_id, db)

    # Unknown state — fall back to root
    return _ROOT_MENU, {"menu_state": "root"}


async def _handle_balance(
    msisdn: str,
    subscriber_id: str,
    db,
    cache,
) -> tuple[str, dict[str, str]]:
    """Read balance from Valkey; fall back to DB on cold cache."""
    raw = await cache.get_str(f"balance:{msisdn}")
    if raw is not None:
        paise = int(raw)
    else:
        async with db.transaction() as conn:
            cur = await conn.execute(
                "SELECT balance_paise FROM billing_wallet_balances WHERE subscriber_id = %s::uuid",
                (subscriber_id,),
            )
            row = await cur.fetchone()
            paise = row[0] if row else 0
    inr = paise / 100
    text = f"Your balance is ₹{inr:.2f}\n0. Back"
    return text, {"menu_state": "balance"}


async def _handle_plan(
    subscriber_id: str,
    db,
) -> tuple[str, dict[str, str]]:
    """Fetch active subscription and format plan text with remaining usage."""
    async with db.transaction() as conn:
        sub = await get_active_subscription(conn, subscriber_id)
        if sub is None:
            return "No active plan.\n0. Back", {"menu_state": "plan"}

        # Convert start_date to timezone-aware datetime for get_usage_for_period
        start_date = sub["start_date"]
        if isinstance(start_date, datetime):
            start_dt = start_date.replace(tzinfo=timezone.utc) if start_date.tzinfo is None else start_date
        else:
            # date object -> convert to datetime at midnight UTC
            start_dt = datetime(start_date.year, start_date.month, start_date.day, tzinfo=timezone.utc)

        usage = await get_usage_for_period(conn, _UUID(subscriber_id), start_dt, sub["end_date"])

    end_date = sub["end_date"]
    expiry_str = end_date.strftime("%d %b %Y") if end_date else "N/A"

    # Show remaining, not limit
    data_limit = sub["data_limit_mb"] or 0
    data_used = usage["data_mb_used"]
    data_remaining = max(0.0, data_limit - data_used)
    data = f"{data_remaining:.0f}/{data_limit} MB" if data_limit else "Unlimited"

    voice_limit = sub["voice_minutes"] or 0
    voice_used = usage["voice_minutes_used"]
    voice_remaining = max(0.0, voice_limit - voice_used)
    voice = f"{voice_remaining:.0f}/{voice_limit} min" if voice_limit else "Unlimited"

    sms_limit = sub["sms_count"] or 0
    sms_used = usage["sms_count_used"]
    sms_remaining = max(0, sms_limit - sms_used)
    sms = f"{sms_remaining}/{sms_limit}" if sms_limit else "Unlimited"

    text = f"Plan: {sub['plan_name']}\nExpires: {expiry_str}\nData: {data}\nVoice: {voice}\nSMS: {sms}\n0. Back"
    return text, {"menu_state": "plan"}


async def _handle_recharge_select(
    subscriber_id: str,
    db,
) -> tuple[str, dict[str, str]]:
    """Fetch available plans and format selection menu."""
    async with db.transaction() as conn:
        plans = await get_available_plans(conn, limit=5)

    if not plans:
        return "No plans available.\n0. Back", {"menu_state": "root"}

    lines = ["Select plan:"]
    plan_ids = []
    for i, plan in enumerate(plans, start=1):
        price_inr = plan["price_paise"] / 100
        lines.append(f"{i}. {plan['plan_name']} ₹{price_inr:.0f}")
        plan_ids.append(plan["id"])
    lines.append("0. Back")

    return "\n".join(lines), {
        "menu_state": "recharge_select",
        "plan_ids": ",".join(plan_ids),
    }


async def _handle_notifications(
    subscriber_id: str,
    db,
) -> tuple[str, dict[str, str]]:
    """Fetch notification preferences and format toggle menu."""
    async with db.transaction() as conn:
        prefs = await get_preferences(conn, subscriber_id)
    text = _format_notifications_menu(prefs)
    return text, {"menu_state": "notifications"}


async def _handle_recharge_confirm(
    subscriber_id: str,
    msisdn: str,
    plan_id: str,
    session_key: str,
    db,
    cache,
) -> tuple[str, dict[str, str]]:
    """Execute recharge: insert order, credit balance, update subscription."""
    if not plan_id:
        return "Invalid selection.\n0. Back", {"menu_state": "root"}

    async with db.transaction() as conn:
        payment_method = await _get_primary_payment_method(conn, subscriber_id)

    if payment_method is None:
        return "No saved payment method.\n0. Back", {"menu_state": "root"}

    try:
        idempotency_key = f"ussd-{subscriber_id}-{plan_id}-{session_key}"
        async with db.transaction() as conn:
            order = await create_recharge_order(
                conn=conn,
                subscriber_id=uuid.UUID(subscriber_id),
                plan_id=uuid.UUID(plan_id),
                payment_method_id=uuid.UUID(payment_method["id"]),
                idempotency_key=idempotency_key,
            )
            if order is None:
                return "Recharge failed.\n0. Back", {"menu_state": "root"}

            result = await complete_recharge_transaction(
                conn=conn,
                order_id=order["id"],
                subscriber_id=uuid.UUID(subscriber_id),
                amount_paise=order["amount_paise"],
            )
        if result is None or "new_balance_paise" not in result:
            return "Recharge failed.\n0. Back", {"menu_state": "root"}
        new_balance_inr = result["new_balance_paise"] / 100
        await cache.incr_balance(msisdn, order["amount_paise"])
    except Exception:
        logger.exception("USSD recharge failed subscriber_id=%s plan_id=%s", subscriber_id, plan_id)
        return "Recharge failed.\n0. Back", {"menu_state": "root"}

    return f"Recharge successful.\nBalance: ₹{new_balance_inr:.2f}\n0. Back", {"menu_state": "root"}


__all__ = ["router"]
