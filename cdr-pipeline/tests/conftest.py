"""Shared pytest config for the cdr-pipeline test suite.

Integration and slow tests skip by default; opt in with ``--run-integration`` /
``--run-slow``. The hook is intentionally duplicated from
service_webapp/tests/conftest.py because the two projects run pytest
independently (each has its own rootdir/pythonpath) and share no conftest root.
"""

from __future__ import annotations

import pytest


def pytest_addoption(parser):
    """Register opt-in flags for integration / slow tests (skipped by default)."""
    parser.addoption(
        "--run-integration",
        action="store_true",
        default=False,
        help="run integration tests (skipped by default)",
    )
    parser.addoption(
        "--run-slow",
        action="store_true",
        default=False,
        help="run slow tests (skipped by default)",
    )


def pytest_collection_modifyitems(config, items):
    """Skip slow/integration tests unless an opt-in flag is given.

    Plain ``pytest`` runs unit tests only. Pass ``--run-integration`` and/or
    ``--run-slow`` to opt in. An item runs if ANY of its gate marks has its flag
    set, so tests marked both ``slow`` + ``integration`` (the integration suite)
    run under either flag. Mirrored in service_webapp/tests/conftest.py.
    """
    run_integration = config.getoption("--run-integration")
    run_slow = config.getoption("--run-slow")
    if run_integration and run_slow:
        return  # both buckets opted in — nothing to gate
    skip_gate = pytest.mark.skip(reason="integration/slow test — rerun with --run-integration or --run-slow")
    for item in items:
        has_slow = "slow" in item.keywords
        has_integration = "integration" in item.keywords
        if (has_slow or has_integration) and not ((has_slow and run_slow) or (has_integration and run_integration)):
            item.add_marker(skip_gate)
