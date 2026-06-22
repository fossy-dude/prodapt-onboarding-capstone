"""CDR payload schema — the shape of every ``cdr.raw`` envelope payload (Story 2.1, AC #3).

Mirrors the ``billing_cdr_events`` table (``service_webapp/db/migrations/V1__baseline_schema.sql``)
as a pydantic v2 discriminated union: core fields common to every CDR plus
voice/sms/data variants selected by ``cdr_type``. Story 2.2 validates incoming
``cdr.raw`` payloads against ``CdrEvent`` before they touch the dedup/insert path.

Type rules enforced here (AC #3): ``cdr_type`` is restricted to ``{voice, sms,
data}``, ``cost_paise`` is an ``int`` (paise, never a float/Decimal), and MSISDN
columns (``from_number``/``to_number``) are ``str`` — matching the DB ``VARCHAR``
columns, never ints (leading zeros / ``+`` prefix matter).
"""

from __future__ import annotations

from datetime import datetime  # noqa: TC003  # pydantic resolves field types at runtime
from typing import Annotated, Literal
from uuid import UUID  # noqa: TC003  # pydantic resolves field types at runtime

from pydantic import BaseModel, ConfigDict, Field

# ── Enums (mirror *_enum CREATE TYPEs in V1__baseline_schema.sql) ───────────────

CdrType = Literal["voice", "sms", "data"]
CallDirection = Literal["MO", "MT"]
CallStatus = Literal["answered", "no_answer", "busy", "failed"]
SmsStatus = Literal["delivered", "failed", "pending"]
NetworkType = Literal["2G", "3G", "4G", "5G"]


class CdrBase(BaseModel):
    """Core fields common to every CDR event (the non-variant ``billing_cdr_events`` columns).

    Variant models extend this and pin ``cdr_type`` to their literal so the
    union can discriminate. ``extra="forbid"`` makes the contract strict: a
    payload carrying an unknown key is rejected here rather than silently
    flowing into Story 2.2's insert.
    """

    model_config = ConfigDict(extra="forbid")

    session_id: UUID
    subscriber_id: UUID
    telecom_circle: str = Field(..., max_length=50)
    cell_tower_id: str | None = Field(default=None, max_length=100)
    roaming: bool = False
    cost_paise: int = Field(..., ge=0, description="Charge in paise (1 INR = 100 paise).")
    start_time: datetime
    end_time: datetime | None = None


class VoiceCdr(CdrBase):
    """Voice call CDR (``billing_cdr_events`` voice-specific columns)."""

    cdr_type: Literal["voice"] = "voice"
    from_number: str = Field(..., max_length=20, description="Calling MSISDN (E.164 string).")
    to_number: str = Field(..., max_length=20, description="Called MSISDN (E.164 string).")
    call_direction: CallDirection
    duration_seconds: int = Field(..., ge=0)
    call_status: CallStatus


class SmsCdr(CdrBase):
    """SMS CDR (``billing_cdr_events`` sms-specific columns)."""

    cdr_type: Literal["sms"] = "sms"
    message_direction: CallDirection
    sms_status: SmsStatus


class DataCdr(CdrBase):
    """Mobile-data CDR (``billing_cdr_events`` data-specific columns)."""

    cdr_type: Literal["data"] = "data"
    network_type: NetworkType
    downloaded_mb: float | None = Field(default=None, ge=0)
    uploaded_mb: float | None = Field(default=None, ge=0)
    volume_mb: float | None = Field(default=None, ge=0)
    apn: str | None = Field(default=None, max_length=100)
    imei: str | None = Field(default=None, max_length=20)
    operator_id: str | None = Field(default=None, max_length=50)


# Discriminated union: pydantic routes by ``cdr_type`` to the right variant.
CdrEvent = Annotated[VoiceCdr | SmsCdr | DataCdr, Field(discriminator="cdr_type")]
"""Validated CDR payload type — validate with ``TypeAdapter(CdrEvent)`` or as a field."""
