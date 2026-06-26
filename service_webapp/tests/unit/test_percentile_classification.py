"""Tests for percentile rank and classification helpers (Story 5.9 Task 8)."""

from agents.support.tools import _DOMINANT_THRESHOLD, _PREF_MAP, _percentile_rank


def test_percentile_rank_below_p25():
    assert _percentile_rank(50, 100, 200, 300, 400) == 12.5


def test_percentile_rank_at_p25():
    assert _percentile_rank(100, 100, 200, 300, 400) == 25.0


def test_percentile_rank_between_p25_and_p50():
    result = _percentile_rank(150, 100, 200, 300, 400)
    assert 25.0 < result < 50.0


def test_percentile_rank_at_p50():
    assert _percentile_rank(200, 100, 200, 300, 400) == 50.0


def test_percentile_rank_at_p75():
    assert _percentile_rank(300, 100, 200, 300, 400) == 75.0


def test_percentile_rank_at_p90():
    assert _percentile_rank(400, 100, 200, 300, 400) == 90.0


def test_percentile_rank_above_p90():
    assert _percentile_rank(500, 100, 200, 300, 400) == 91.0


def test_percentile_rank_with_zero_baseline():
    assert _percentile_rank(100, 0, 0, 0, 0) == 0.0


def test_pref_map_data():
    assert _PREF_MAP.get("data") == "DATA_HEAVY"


def test_pref_map_voice():
    assert _PREF_MAP.get("voice") == "VOICE_HEAVY"


def test_pref_map_value():
    assert _PREF_MAP.get("value") == "VALUE"


def test_pref_map_balanced():
    assert _PREF_MAP.get("balanced") == "BALANCED"


def test_dominant_threshold_value():
    assert _DOMINANT_THRESHOLD == 70.0
