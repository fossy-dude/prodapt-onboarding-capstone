"""Tests for _usage_category helper from seed_milvus.py (Story 5.9 Task 8)."""

import sys
from pathlib import Path

import pytest

# Add project root to path so we can import from scripts
project_root = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(project_root))

try:
    from scripts.seed_milvus import _usage_category
except ImportError:
    pytest.skip("seed_milvus.py not found or not importable", allow_module_level=True)


def test_usage_category_data_heavy():
    assert _usage_category(25000, 0, 15000) == "DATA_HEAVY"


def test_usage_category_data_heavy_at_boundary():
    assert _usage_category(20481, 0, 15000) == "DATA_HEAVY"


def test_usage_category_voice_heavy_unlimited():
    assert _usage_category(100, None, 15000) == "VOICE_HEAVY"


def test_usage_category_voice_heavy_large_minutes():
    assert _usage_category(100, 1001, 15000) == "VOICE_HEAVY"


def test_usage_category_value():
    assert _usage_category(5000, 100, 9000) == "VALUE"


def test_usage_category_balanced_default():
    assert _usage_category(5000, 100, 15000) == "BALANCED"


def test_usage_category_with_none_values():
    # None voice means unlimited, which maps to VOICE_HEAVY
    assert _usage_category(0, None, None) == "VOICE_HEAVY"
