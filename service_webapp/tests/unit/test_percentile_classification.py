"""Tests for recommend_plan's preference/filter helpers (Story 5.9 Task 8)."""

from agents.support.tools import (
    _UNLIMITED_SENTINEL,
    _build_plan_filter,
    _current_baseline,
    _normalize_direction,
    _normalize_limit,
    _preference_summary,
)


def test_normalize_direction_more():
    assert _normalize_direction("more") == "more"


def test_normalize_direction_less_case_and_whitespace():
    assert _normalize_direction(" LESS ") == "less"


def test_normalize_direction_none():
    assert _normalize_direction(None) is None


def test_normalize_direction_invalid_value_drops_to_none():
    assert _normalize_direction("balanced") is None


def test_normalize_limit_passes_through_int():
    assert _normalize_limit(5000) == 5000


def test_normalize_limit_maps_none_to_sentinel():
    assert _normalize_limit(None) == _UNLIMITED_SENTINEL


def test_current_baseline_prefers_current_plan():
    profile = {"total_data_mb": 100, "total_voice_seconds": 60, "total_sms_count": 5}
    current_plan = {"data_limit_mb": 30720, "voice_minutes": 500, "sms_count": 100}
    baseline = _current_baseline(profile, current_plan)
    assert baseline == {"data_limit_mb": 30720, "voice_minutes": 500, "sms_count": 100}


def test_current_baseline_falls_back_to_usage_without_a_plan():
    profile = {"total_data_mb": 5000, "total_voice_seconds": 6000, "total_sms_count": 100}
    baseline = _current_baseline(profile, None)
    assert baseline == {"data_limit_mb": 5000, "voice_minutes": 100, "sms_count": 100}


def test_current_baseline_maps_unlimited_plan_fields_to_sentinel():
    profile = {"total_data_mb": 0, "total_voice_seconds": 0, "total_sms_count": 0}
    current_plan = {"data_limit_mb": 30720, "voice_minutes": None, "sms_count": None}
    baseline = _current_baseline(profile, current_plan)
    assert baseline["voice_minutes"] == _UNLIMITED_SENTINEL
    assert baseline["sms_count"] == _UNLIMITED_SENTINEL


def test_build_plan_filter_more_data():
    baseline = {"data_limit_mb": 5000, "voice_minutes": 100, "sms_count": 50}
    directions = {"data": "more", "voice": None, "sms": None}
    assert _build_plan_filter(baseline, directions) == "data_limit_mb > 5000"


def test_build_plan_filter_combines_multiple_axes():
    baseline = {"data_limit_mb": 5000, "voice_minutes": 100, "sms_count": 50}
    directions = {"data": "more", "voice": "less", "sms": None}
    assert _build_plan_filter(baseline, directions) == "data_limit_mb > 5000 and voice_minutes < 100"


def test_build_plan_filter_no_directions_returns_none():
    baseline = {"data_limit_mb": 5000, "voice_minutes": 100, "sms_count": 50}
    directions = {"data": None, "voice": None, "sms": None}
    assert _build_plan_filter(baseline, directions) is None


def test_build_plan_filter_skips_more_when_already_unlimited():
    baseline = {"data_limit_mb": 5000, "voice_minutes": _UNLIMITED_SENTINEL, "sms_count": 50}
    directions = {"data": None, "voice": "more", "sms": None}
    assert _build_plan_filter(baseline, directions) is None


def test_preference_summary_lists_only_stated_axes():
    directions = {"data": "more", "voice": None, "sms": "less"}
    assert _preference_summary(directions) == "more data, less SMS"
