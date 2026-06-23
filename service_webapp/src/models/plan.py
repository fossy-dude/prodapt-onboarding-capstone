"""Pydantic response models for plan details and the plan catalogue (Story 3.4).

Schema variances vs the epic model (documented in the story Dev Notes):

* ``plans_plans`` stores ``data_limit_mb``; the API exposes ``data_gb =
  round(data_limit_mb / 1024, 2)``. ``None`` means unlimited.
* There is **no** ``plan_type`` / ``category`` column in V1 — ``plan_type`` is
  optional and defaults to ``None`` (the catalogue filters by validity, not type).
* There is **no** roaming flag in ``plans_plans`` — ``roaming_enabled`` defaults
  to ``False`` (roaming is observed via usage only).
"""

from __future__ import annotations

from datetime import datetime  # noqa: TC003 — pydantic resolves field types at runtime
from uuid import UUID  # noqa: TC003 — pydantic resolves field types at runtime

from pydantic import BaseModel, ConfigDict, Field


class PlanQuotas(BaseModel):
    """Bundled plan quotas (None means unlimited)."""

    model_config = ConfigDict(extra="forbid")

    data_gb: float | None = Field(default=None, description="round(data_limit_mb / 1024, 2); None = unlimited")
    voice_minutes: int | None = Field(default=None, description="None = unlimited")
    sms_count: int | None = Field(default=None, description="None = unlimited")


class ActivePlanResponse(BaseModel):
    """Response body for GET /api/v1/subscriber/plan (FR-11)."""

    model_config = ConfigDict(extra="forbid")

    plan_id: UUID
    plan_name: str
    validity_expiry: datetime | None = Field(
        default=None,
        description="plans_subscriptions.end_date (frontend formats to DD MMM YYYY IST).",
    )
    validity_days: int
    days_remaining: int | None = Field(default=None, description="Countdown to expiry; negative when expired.")
    quotas: PlanQuotas
    roaming_enabled: bool = False


class PlanCatalogueItem(BaseModel):
    """One row of GET /api/v1/plans (FR-12)."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    name: str
    data_gb: float | None = Field(default=None, description="round(data_limit_mb / 1024, 2); None = unlimited")
    voice_minutes: int | None = Field(default=None, description="None = unlimited")
    sms_count: int | None = Field(default=None, description="None = unlimited")
    validity_days: int
    price_paise: int
    plan_type: str | None = Field(default=None, description="V1 has no plan_type column; derived or None.")


__all__ = ["ActivePlanResponse", "PlanCatalogueItem", "PlanQuotas"]
