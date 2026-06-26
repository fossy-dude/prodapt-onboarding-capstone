"""PDF receipt renderer for recharge orders (Story 3.6).

Renders an HTML template (Jinja2-style simple string substitution) via WeasyPrint.
WeasyPrint is declared in pyproject.toml but excluded from the tox test env;
unit tests stub ``render_receipt_pdf`` directly.
"""

from __future__ import annotations

import pathlib
import re
from typing import TYPE_CHECKING

_TEMPLATE_PATH = pathlib.Path(__file__).parent / "template.html"

_METHOD_TYPE_LABELS: dict[str, str] = {
    "CREDIT_CARD": "Credit Card",
    "DEBIT_CARD": "Debit Card",
    "UPI": "UPI",
    "NET_BANKING": "Net Banking",
    "MOBILE_WALLET": "Mobile Wallet",
    "card": "Card",
    "upi": "UPI",
    "netbanking": "Net Banking",
    "wallet": "Mobile Wallet",
}


def _render_template(template: str, ctx: dict) -> str:
    """Naive {{ key }} substitution — no external dep required for rendering."""
    result = template
    for key, value in ctx.items():
        result = result.replace("{{ " + key + " }}", str(value) if value is not None else "")
        result = result.replace("{{" + key + "}}", str(value) if value is not None else "")
    result = re.sub(r"\{%[^%]*?%\}", "", result)

    # Validate that all template keys were replaced - check for unreplaced placeholders
    unreplaced_keys = re.findall(r"\{\{([^}]+)\}\}", result)
    if unreplaced_keys:
        raise ValueError(f"Template keys were not replaced: {unreplaced_keys}")

    return result


def render_receipt_pdf(
    *,
    transaction_id: str,
    subscriber_name: str,
    msisdn_last4: str,
    transaction_date: str,
    plan_name: str,
    amount_inr: str,
    method_type: str | None,
    last_four: str | None,
    receipt_number: str | None,
) -> bytes:
    """Render receipt HTML via WeasyPrint and return PDF bytes.

    ``subscriber_name`` must already be decrypted (PII boundary).
    ``msisdn_last4`` must already be masked (last 4 digits only).
    No card numbers / full PAN appear in the output.
    """
    try:
        # type: ignore[misc] — WeasyPrint excluded from tox test env
        from weasyprint import HTML  # noqa: PLC0415
    except ImportError as exc:
        raise ImportError("WeasyPrint is required for PDF rendering but is not installed") from exc

    method_label = _METHOD_TYPE_LABELS.get(method_type or "", method_type or "Unknown")
    ctx = {
        "transaction_id": transaction_id,
        "subscriber_name": subscriber_name,
        "msisdn_last4": msisdn_last4,
        "transaction_date": transaction_date,
        "plan_name": plan_name,
        "amount_inr": amount_inr,
        "method_type_display": method_label,
        "last_four": last_four or "",
        "receipt_number": receipt_number or "",
    }
    html_source = _render_template(_TEMPLATE_PATH.read_text(encoding="utf-8"), ctx)
    return HTML(string=html_source).write_pdf()


__all__ = ["render_receipt_pdf"]
