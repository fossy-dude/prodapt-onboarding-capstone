"""CDR payload schema for service_webapp (Story 2.8).

Mirrors ``cdr-pipeline/src/models/cdr.py`` byte-for-byte.
DUPLICATION NOTE: Two-codebase rule (architecture §1.5.1) forbids a shared package;
kept in sync by contract — any change to the cdr-pipeline model must propagate here
manually until a future shared module consolidates them.

Matches the ``billing_cdr_events`` table columns from V1__baseline_schema.sql.
"""

from __future__ import annotations

from datetime import datetime  # noqa: TC003  # pydantic resolves field types at runtime
from typing import Annotated, Literal
from uuid import UUID  # noqa: TC003  # pydantic resolves field types at runtime

from pydantic import BaseModel, ConfigDict, Field, model_validator

CdrType = Literal["voice", "sms", "data"]
CallDirection = Literal["MO", "MT"]
CallStatus = Literal["answered", "no_answer", "busy", "failed"]
SmsStatus = Literal["delivered", "failed", "pending"]
NetworkType = Literal["2G", "3G", "4G", "5G"]


class CdrBase(BaseModel):
    """Core fields common to every CDR event."""

    model_config = ConfigDict(extra="forbid")

    cdr_id: UUID
    session_id: UUID
    subscriber_id: UUID
    telecom_circle: str = Field(..., max_length=50)
    cell_tower_id: str | None = Field(default=None, max_length=100)
    roaming: bool = False
    cost_paise: int = Field(..., ge=0, le=10**12)
    start_time: datetime
    end_time: datetime | None = None


class VoiceCdr(CdrBase):
    """Voice call CDR."""

    cdr_type: Literal["voice"] = "voice"
    from_number: str = Field(..., pattern=r"^\+?[1-9]\d{6,14}$", max_length=15)
    to_number: str = Field(..., pattern=r"^\+?[1-9]\d{6,14}$", max_length=15)
    call_direction: CallDirection
    duration_seconds: int = Field(..., ge=0, le=86400 * 30)
    call_status: CallStatus


class SmsCdr(CdrBase):
    """SMS CDR."""

    cdr_type: Literal["sms"] = "sms"
    message_direction: CallDirection
    sms_status: SmsStatus


class DataCdr(CdrBase):
    """Mobile-data CDR."""

    cdr_type: Literal["data"] = "data"
    network_type: NetworkType
    downloaded_mb: float | None = Field(default=None, ge=0)
    uploaded_mb: float | None = Field(default=None, ge=0)
    volume_mb: float | None = Field(default=None, ge=0)
    apn: str | None = Field(default=None, max_length=100)
    imei: str | None = Field(default=None, max_length=20)
    operator_id: str | None = Field(default=None, max_length=50)

    @model_validator(mode="after")
    def _volume_consistency(self) -> DataCdr:
        """Ensure volume_mb equals downloaded_mb + uploaded_mb when all are present."""
        if self.volume_mb is not None and self.downloaded_mb is not None and self.uploaded_mb is not None:
            expected_volume = self.downloaded_mb + self.uploaded_mb
            if abs(self.volume_mb - expected_volume) > 0.001:
                raise ValueError(
                    f"volume_mb ({self.volume_mb}) must equal downloaded_mb ({self.downloaded_mb}) + "
                    f"uploaded_mb ({self.uploaded_mb})"
                )
        return self


CdrEvent = Annotated[VoiceCdr | SmsCdr | DataCdr, Field(discriminator="cdr_type")]

__all__ = ["CdrEvent", "CdrType", "DataCdr", "SmsCdr", "VoiceCdr"]
