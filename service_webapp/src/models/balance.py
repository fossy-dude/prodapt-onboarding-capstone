"""Pydantic response models for balance and usage endpoints (Story 3.2).

Money is always integer paise internally; INR conversion (paise / 100) happens
only at this presentation boundary (architecture §1.11.2, §1.11.3).
"""

from __future__ import annotations

from datetime import datetime  # noqa: TC003 — pydantic resolves field types at runtime
from uuid import UUID  # noqa: TC003 — pydantic resolves field types at runtime

from pydantic import BaseModel, ConfigDict, Field, model_validator


class WalletBalanceResponse(BaseModel):
    """Response body for GET /api/v1/subscriber/balance."""

    model_config = ConfigDict(extra="forbid")

    subscriber_id: UUID
    msisdn: str = Field(..., description="Assigned mobile number (shown to the authenticated owner)")
    msisdn_masked: str = Field(..., description="Last-4 masked MSISDN (e.g. ***1234)")
    balance_paise: int = Field(..., ge=0)
    balance_inr: str = Field(..., description="Formatted INR string (e.g. '₹123.45')")
    last_updated_at: datetime | None = None

    @model_validator(mode="before")
    @classmethod
    def derive_balance_inr(cls, values: dict) -> dict:
        """Derive ``balance_inr`` from ``balance_paise`` when not explicitly provided."""
        if "balance_inr" not in values and "balance_paise" in values:
            paise = values["balance_paise"]
            values["balance_inr"] = f"₹{paise / 100:.2f}"
        return values


class UsageAllowance(BaseModel):
    """Per-type usage + allowance for one dimension."""

    model_config = ConfigDict(extra="forbid")

    used: float = Field(..., ge=0)
    allowance: float | None = Field(default=None, ge=0, description="None means unlimited")
    unlimited: bool = False


class UsagePeriod(BaseModel):
    """Active plan period window."""

    model_config = ConfigDict(extra="forbid")

    start: datetime
    end: datetime | None = None


class UsageResponse(BaseModel):
    """Response body for GET /api/v1/subscriber/usage."""

    model_config = ConfigDict(extra="forbid")

    subscriber_id: UUID
    plan_period: UsagePeriod
    voice_minutes: UsageAllowance
    data_mb: float = Field(..., ge=0, description="Total MB consumed")
    data_gb: float = Field(..., ge=0, description="Total GB consumed (data_mb / 1024)")
    data: UsageAllowance
    sms: UsageAllowance
    roaming_mb: UsageAllowance


__all__ = ["UsageAllowance", "UsagePeriod", "UsageResponse", "WalletBalanceResponse"]
