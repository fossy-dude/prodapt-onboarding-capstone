"""Pydantic models for API request/response envelopes.

Models are organized by domain:
- balance.py: WalletBalanceResponse, UsageResponse (Story 3.2)
- transaction.py: TransactionItem (Story 3.3)
- plan.py: PlanCatalogueItem, ActivePlanData (Story 3.4)
- recharge.py: RechargeRequest, RechargeResponse (Story 3.5)
- cdr.py: CDR-related models (Story 2.x)
- envelope.py: EventEnvelope (Story 2.x)
- notifications.py: Notification preference models (Story 4.2)
"""

from __future__ import annotations

# Re-export all models for convenience
from models.balance import UsageAllowance, UsagePeriod, UsageResponse, WalletBalanceResponse
from models.envelope import EventEnvelope
from models.failed_recharge import FailedRechargeItem
from models.notifications import (
    NotificationPreferencesResponse,
    NotificationTypeLiteral,
    PatchNotificationPreferenceRequest,
)
from models.plan import ActivePlanResponse, PlanCatalogueItem, PlanQuotas
from models.recharge import RechargeRequest, RechargeResponse
from models.transaction import TransactionItem

__all__ = [
    "ActivePlanResponse",
    "EventEnvelope",
    "FailedRechargeItem",
    "NotificationPreferencesResponse",
    "NotificationTypeLiteral",
    "PatchNotificationPreferenceRequest",
    "PlanCatalogueItem",
    "PlanQuotas",
    "RechargeRequest",
    "RechargeResponse",
    "TransactionItem",
    "UsageAllowance",
    "UsagePeriod",
    "UsageResponse",
    "WalletBalanceResponse",
]
