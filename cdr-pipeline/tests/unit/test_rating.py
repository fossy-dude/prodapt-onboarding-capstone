"""Unit tests for plan-based rating (Story 2.3, Task 7)."""

from __future__ import annotations

import pytest

from consumer.rating import PlanTariff, rate_cdr
from models.cdr import DataCdr, SmsCdr, VoiceCdr


def test_voice_per_second_charge() -> None:
    """Voice per-second charge: cost = per_second * duration (Task 7)."""
    cdr = VoiceCdr(
        cdr_id="0192a4d0-0001-7000-8000-000000000001",
        session_id="0192a4d0-abcd-7000-8000-000000000001",
        subscriber_id="0192a4d0-1234-7000-8000-000000000abc",
        telecom_circle="KA",
        cost_paise=0,  # ignored by rate_cdr
        start_time="2026-01-01T12:00:00Z",
        from_number="+919876543210",
        to_number="+919876543211",
        call_direction="MO",
        duration_seconds=120,
        call_status="answered",
    )

    tariff = PlanTariff(voice_paise_per_second=1, voice_unlimited=False)  # 1 paise/sec
    assert rate_cdr(cdr, tariff) == 120  # 120 seconds * 1 paise/sec


def test_voice_unlimited_bundle_zero_charge() -> None:
    """Unlimited voice bundle → zero charge, still logged (Task 7)."""
    cdr = VoiceCdr(
        cdr_id="0192a4d0-0001-7000-8000-000000000002",
        session_id="0192a4d0-abcd-7000-8000-000000000001",
        subscriber_id="0192a4d0-1234-7000-8000-000000000abc",
        telecom_circle="KA",
        cost_paise=0,
        start_time="2026-01-01T12:00:00Z",
        from_number="+919876543210",
        to_number="+919876543211",
        call_direction="MO",
        duration_seconds=300,  # 5 minutes
        call_status="answered",
    )

    tariff = PlanTariff(voice_paise_per_second=1, voice_unlimited=True)
    assert rate_cdr(cdr, tariff) == 0  # unlimited → zero charge


def test_sms_flat_charge() -> None:
    """SMS flat per-message charge."""
    cdr = SmsCdr(
        cdr_id="0192a4d0-0001-7000-8000-000000000003",
        session_id="0192a4d0-abcd-7000-8000-000000000001",
        subscriber_id="0192a4d0-1234-7000-8000-000000000abc",
        telecom_circle="KA",
        cost_paise=0,
        start_time="2026-01-01T12:00:00Z",
        message_direction="MT",
        sms_status="delivered",
    )

    tariff = PlanTariff(sms_paise_per_message=25, sms_unlimited=False)
    assert rate_cdr(cdr, tariff) == 25


def test_sms_unlimited_zero_charge() -> None:
    """Unlimited SMS → zero charge."""
    cdr = SmsCdr(
        cdr_id="0192a4d0-0001-7000-8000-000000000004",
        session_id="0192a4d0-abcd-7000-8000-000000000001",
        subscriber_id="0192a4d0-1234-7000-8000-000000000abc",
        telecom_circle="KA",
        cost_paise=0,
        start_time="2026-01-01T12:00:00Z",
        message_direction="MT",
        sms_status="delivered",
    )

    tariff = PlanTariff(sms_paise_per_message=25, sms_unlimited=True)
    assert rate_cdr(cdr, tariff) == 0


def test_data_per_mb_charge() -> None:
    """Data per-MB charge: cost = per_mb * volume_mb (rounded)."""
    cdr = DataCdr(
        cdr_id="0192a4d0-0001-7000-8000-000000000005",
        session_id="0192a4d0-abcd-7000-8000-000000000001",
        subscriber_id="0192a4d0-1234-7000-8000-000000000abc",
        telecom_circle="KA",
        cost_paise=0,
        start_time="2026-01-01T12:00:00Z",
        network_type="4G",
        volume_mb=10.5,
        downloaded_mb=5.0,
        uploaded_mb=5.5,
    )

    tariff = PlanTariff(data_paise_per_mb=2, data_unlimited=False)
    assert rate_cdr(cdr, tariff) == 21  # 10.5 MB * 2 paise/MB = 21


def test_data_unlimited_zero_charge() -> None:
    """Unlimited data → zero charge."""
    cdr = DataCdr(
        cdr_id="0192a4d0-0001-7000-8000-000000000006",
        session_id="0192a4d0-abcd-7000-8000-000000000001",
        subscriber_id="0192a4d0-1234-7000-8000-000000000abc",
        telecom_circle="KA",
        cost_paise=0,
        start_time="2026-01-01T12:00:00Z",
        network_type="4G",
        volume_mb=100.0,
    )

    tariff = PlanTariff(data_paise_per_mb=2, data_unlimited=True)
    assert rate_cdr(cdr, tariff) == 0


def test_data_missing_volume_zero_charge() -> None:
    """Data CDR with missing volume_mb → zero charge (safe default)."""
    cdr = DataCdr(
        cdr_id="0192a4d0-0001-7000-8000-000000000007",
        session_id="0192a4d0-abcd-7000-8000-000000000001",
        subscriber_id="0192a4d0-1234-7000-8000-000000000abc",
        telecom_circle="KA",
        cost_paise=0,
        start_time="2026-01-01T12:00:00Z",
        network_type="4G",
        volume_mb=None,
    )

    tariff = PlanTariff(data_paise_per_mb=2, data_unlimited=False)
    assert rate_cdr(cdr, tariff) == 0  # None volume → 0 charge
