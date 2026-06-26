"""Pydantic model for refund-eligible (failed) recharge items (Story 3.7)."""

from __future__ import annotations

from datetime import datetime  # noqa: TC003 — pydantic resolves field types at runtime
from uuid import UUID  # noqa: TC003 — pydantic resolves field types at runtime

from pydantic import BaseModel, ConfigDict, Field


class FailedRechargeItem(BaseModel):
    """One failed recharge order row (GET /transactions?type=FAILED)."""

    model_config = ConfigDict(extra="forbid")

    transaction_id: UUID = Field(..., description="recharge_orders.id")
    plan_attempted: str = Field(..., description="Plan name that was being purchased")
    amount_paise: int = Field(..., description="Amount attempted in paise")
    failure_reason: str | None = Field(None, description="Why the recharge failed (may be null)")
    created_at: datetime = Field(..., description="When the failed order was created")


__all__ = ["FailedRechargeItem"]
