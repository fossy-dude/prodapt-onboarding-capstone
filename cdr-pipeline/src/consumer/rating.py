"""Plan-based rating for CDR events (Story 2.3, AC #7, Task 2, Task 7).

Provides the canonical plan-based rater that the simulator (Story 2.8) and
the balance engine can reference. The hot path simply honours the incoming
``cost_paise`` from the CDR (the producer pre-rates), but this module
documents/implements HOW that cost is computed so all services agree.

Voice per-second rate is derived from the plan price (documented simplifying
assumption — plans_plans lacks explicit per-unit rate columns). Unlimited
bundles (NULL cap) → zero charge. SMS/data use a simple default (deferred
complexity, documented in Completion Notes per Dev Notes).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from models.cdr import CdrEvent


@dataclass(frozen=True, slots=True)
class PlanTariff:
    """Per-unit paise rates for a plan, derived from a plans_plans row."""

    voice_paise_per_second: int = 0
    sms_paise_per_message: int = 0
    data_paise_per_mb: int = 0

    # Unlimited flags (NULL cap in plans_plans)
    voice_unlimited: bool = False
    sms_unlimited: bool = False
    data_unlimited: bool = False


def rate_cdr(cdr: CdrEvent, tariff: PlanTariff) -> int:
    """Compute the charge in paise for a CDR against a plan tariff.

    Voice: 0 if unlimited, else ``voice_paise_per_second * duration_seconds``.
    SMS: 0 if unlimited, else ``sms_paise_per_message`` (one message per CDR).
    Data: 0 if unlimited, else round(``data_paise_per_mb * volume_mb``).

    Returns ``int`` >= 0 (paise). Used by the simulator to pre-rate CDRs and
    available for the balance engine's optional plan-based recomputation mode.

    Parameters
    ----------
    cdr : CdrEvent
        Validated CDR payload (voice, sms, or data variant).
    tariff : PlanTariff
        Plan tariff with per-unit rates and unlimited flags.

    Returns
    -------
    int
        Charge in paise (>= 0).
    """
    if cdr.cdr_type == "voice":
        if tariff.voice_unlimited:
            return 0
        return tariff.voice_paise_per_second * cdr.duration_seconds

    if cdr.cdr_type == "sms":
        return 0 if tariff.sms_unlimited else tariff.sms_paise_per_message

    # cdr_type == "data"
    if tariff.data_unlimited:
        return 0
    volume_mb = cdr.volume_mb or 0
    return round(tariff.data_paise_per_mb * volume_mb)


__all__ = ["PlanTariff", "rate_cdr"]
