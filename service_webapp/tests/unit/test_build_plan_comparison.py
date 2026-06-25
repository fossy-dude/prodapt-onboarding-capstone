"""Tests for _build_plan_comparison helper (Story 5.9 Task 8)."""

from agents.support.tools import _build_plan_comparison


def test_comparison_with_more_data():
    current = {"plan_name": "Basic", "data_limit_mb": 1024, "voice_minutes": 100, "price_paise": 5000}
    rec = {"data_limit_mb": 2048, "voice_minutes": 100, "price": 6000}
    result = _build_plan_comparison(current, rec)
    assert result is not None
    assert "100% more data" in result
    assert "₹10 more" in result


def test_comparison_with_less_data():
    current = {"plan_name": "Premium", "data_limit_mb": 10240, "voice_minutes": 500, "price_paise": 20000}
    rec = {"data_limit_mb": 5120, "voice_minutes": 500, "price": 15000}
    result = _build_plan_comparison(current, rec)
    assert result is not None
    assert "50% less data" in result
    assert "₹50 less" in result


def test_comparison_with_unlimited_voice():
    current = {"plan_name": "Basic", "data_limit_mb": 1024, "voice_minutes": 100, "price_paise": 5000}
    rec = {"data_limit_mb": 1024, "voice_minutes": 0, "price": 6000}
    result = _build_plan_comparison(current, rec)
    assert result is not None
    assert "unlimited calls" in result


def test_comparison_no_current_plan():
    current = None
    rec = {"data_limit_mb": 1024, "voice_minutes": 100, "price": 5000}
    assert _build_plan_comparison(current, rec) is None


def test_comparison_identical_plans():
    current = {"plan_name": "Same", "data_limit_mb": 1024, "voice_minutes": 100, "price_paise": 5000}
    rec = {"data_limit_mb": 1024, "voice_minutes": 100, "price": 5000}
    result = _build_plan_comparison(current, rec)
    assert result is None


def test_comparison_with_voice_difference():
    current = {
        "plan_name": "Basic",
        "data_limit_mb": 1024,
        "voice_minutes": 100,
        "voice_minutes": 100,
        "price_paise": 5000,
    }
    rec = {"data_limit_mb": 1024, "voice_minutes": 500, "price": 5000}
    result = _build_plan_comparison(current, rec)
    assert result is not None
    assert "400 more min" in result


def test_comparison_subtle_data_difference_filtered():
    current = {"plan_name": "PlanA", "data_limit_mb": 10000, "voice_minutes": 100, "price_paise": 5000}
    rec = {"data_limit_mb": 10500, "voice_minutes": 100, "price": 5000}
    result = _build_plan_comparison(current, rec)
    assert result is None  # 5% difference < 10% threshold


def test_comparison_subtle_voice_difference_filtered():
    current = {"plan_name": "PlanA", "data_limit_mb": 1024, "voice_minutes": 100, "price_paise": 5000}
    rec = {"data_limit_mb": 1024, "voice_minutes": 120, "price": 5000}
    result = _build_plan_comparison(current, rec)
    assert result is None  # 20 min < 50 min threshold
