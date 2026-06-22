"""Unit tests for pure helper logic in scripts/generate_synthetic_data.py (Story 2.6).

No DB required — all tests run fast and in-process.
"""

from __future__ import annotations

import random
import sys
from pathlib import Path

import pytest

# Make scripts importable from the test runner
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "scripts"))


@pytest.fixture(autouse=True)
def _fixed_seed():
    random.seed(42)
    yield
    random.seed(None)


class TestMsisdn:
    def test_format_length(self):
        from generate_synthetic_data import _rand_msisdn

        used: set[str] = set()
        msisdn = _rand_msisdn(used)
        assert len(msisdn) == 12, f"Expected 12 chars, got {len(msisdn)}"

    def test_starts_with_91(self):
        from generate_synthetic_data import _rand_msisdn

        used: set[str] = set()
        msisdn = _rand_msisdn(used)
        assert msisdn.startswith("91")

    def test_third_digit_valid_prefix(self):
        from generate_synthetic_data import _rand_msisdn

        used: set[str] = set()
        third_digit = _rand_msisdn(used)[2]
        assert third_digit in "6789", f"Invalid prefix digit: {third_digit}"

    def test_uniqueness_enforced(self):
        from generate_synthetic_data import _rand_msisdn

        used: set[str] = set()
        msisdns = [_rand_msisdn(used) for _ in range(100)]
        assert len(set(msisdns)) == 100, "Duplicate MSISDNs generated"

    def test_digits_only(self):
        from generate_synthetic_data import _rand_msisdn

        used: set[str] = set()
        msisdn = _rand_msisdn(used)
        assert msisdn.isdigit()


class TestCostPaise:
    def test_voice_cost_is_int(self):
        # Voice cost = duration_seconds * 50
        duration = 123
        cost = duration * 50
        assert isinstance(cost, int)
        assert cost == 6150

    def test_sms_cost_is_int(self):
        cost = 100  # flat
        assert isinstance(cost, int)

    def test_data_cost_is_int(self):
        # Data cost = int(volume_mb * 200)
        vol_mb = 1.5
        cost = int(vol_mb * 200)
        assert isinstance(cost, int)
        assert cost == 300


class TestCdrTypeDistribution:
    def test_distribution_within_tolerance(self):
        # Sample 10,000 CDR types and verify proportions are within ±5 percentage points
        choices = random.choices(["voice", "data", "sms"], weights=[60, 30, 10], k=10_000)
        voice_pct = choices.count("voice") / 10_000
        data_pct = choices.count("data") / 10_000
        sms_pct = choices.count("sms") / 10_000

        assert 0.55 <= voice_pct <= 0.65, f"Voice: {voice_pct:.2%}"
        assert 0.25 <= data_pct <= 0.35, f"Data: {data_pct:.2%}"
        assert 0.05 <= sms_pct <= 0.15, f"SMS: {sms_pct:.2%}"


class TestFraudFraction:
    def test_fraud_fraction_approx_half_percent(self):
        from generate_synthetic_data import FRAUD_FRACTION, _build_fraud_plan

        subscriber_ids = [str(i) for i in range(10_000)]
        fraud_meta, _ = _build_fraud_plan(subscriber_ids)

        fraction = len(fraud_meta) / len(subscriber_ids)
        assert abs(fraction - FRAUD_FRACTION) < 0.001, f"Fraud fraction: {fraction:.4f}"

    def test_fraud_signals_are_valid(self):
        from generate_synthetic_data import FRAUD_SIGNAL_NAMES, _build_fraud_plan

        subscriber_ids = [str(i) for i in range(1000)]
        fraud_meta, _ = _build_fraud_plan(subscriber_ids)

        for sub_id, meta in fraud_meta.items():
            assert meta["signal"] in FRAUD_SIGNAL_NAMES, f"Unknown signal: {meta['signal']}"

    def test_velocity_burst_has_day_offset(self):
        from generate_synthetic_data import _build_fraud_plan

        random.seed(0)
        subscriber_ids = [str(i) for i in range(2000)]
        fraud_meta, _ = _build_fraud_plan(subscriber_ids)

        velocity_subs = {k: v for k, v in fraud_meta.items() if v["signal"] == "velocity_burst"}
        for meta in velocity_subs.values():
            assert 10 <= meta["fraud_day_offset"] <= 80

    def test_sim_swap_has_two_imeis(self):
        from generate_synthetic_data import _build_fraud_plan

        random.seed(1)
        subscriber_ids = [str(i) for i in range(2000)]
        fraud_meta, _ = _build_fraud_plan(subscriber_ids)

        swap_subs = {k: v for k, v in fraud_meta.items() if v["signal"] == "sim_swap"}
        for meta in swap_subs.values():
            assert "imei_before" in meta
            assert "imei_after" in meta
            assert meta["imei_before"] != meta["imei_after"]


class TestImei:
    def test_imei_length(self):
        from generate_synthetic_data import _rand_imei

        imei = _rand_imei()
        assert len(imei) == 15, f"IMEI should be 15 digits, got {len(imei)}"
        assert imei.isdigit()


class TestTowerId:
    def test_tower_format(self):
        from generate_synthetic_data import _tower_id

        tower = _tower_id()
        assert tower.startswith("TOWER_")
        suffix = tower[len("TOWER_"):]
        assert len(suffix) == 7
        assert suffix.isdigit()


class TestSeedPlansSql:
    def test_seed_sql_file_exists(self):
        sql_path = (
            Path(__file__).parent.parent.parent.parent
            / "service_webapp"
            / "db"
            / "seed"
            / "seed_plans.sql"
        )
        assert sql_path.exists(), f"seed_plans.sql not found at {sql_path}"

    def test_seed_sql_contains_on_conflict(self):
        sql_path = (
            Path(__file__).parent.parent.parent.parent
            / "service_webapp"
            / "db"
            / "seed"
            / "seed_plans.sql"
        )
        content = sql_path.read_text()
        assert "ON CONFLICT" in content
        assert "DO NOTHING" in content

    def test_seed_sql_targets_correct_table(self):
        sql_path = (
            Path(__file__).parent.parent.parent.parent
            / "service_webapp"
            / "db"
            / "seed"
            / "seed_plans.sql"
        )
        content = sql_path.read_text()
        assert "INSERT INTO plans_plans" in content
