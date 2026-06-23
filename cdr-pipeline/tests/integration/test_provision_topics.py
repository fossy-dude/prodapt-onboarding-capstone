"""Integration test: ``provision_topics`` creates the 6 topics idempotently (AC #1/#2/#6).

Uses testcontainers Redpanda (architecture §1.11.8 — do NOT mock the broker).
Marked ``slow`` + ``integration``: it needs a container runtime (Docker/Podman
socket) and is therefore skipped by the default ``just test-cdr`` gate
(``-m "not slow"``). Run explicitly with rootless Podman:

    DOCKER_HOST=unix:///run/user/$(id -u)/podman/podman.sock \
        cd cdr-pipeline && uvx --with tox-uv tox -e test -- -m slow

The provisioning logic lives in ``scripts/provision_topics.py`` (not on the src
path), so it is loaded by file path here — testing the real entry point rather
than a re-implementation.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from aiokafka.admin import AIOKafkaAdminClient
from testcontainers.kafka import RedpandaContainer

pytestmark = [pytest.mark.slow, pytest.mark.integration]

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "provision_topics.py"


def _load_provision_topics() -> object:
    """Import ``scripts/provision_topics.py`` by path (it is not on ``sys.path``)."""
    spec = importlib.util.spec_from_file_location("provision_topics", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def redpanda() -> RedpandaContainer:
    """Fresh, isolated Redpanda container for the duration of the module.

    Pinned to the same image the compose stack uses
    (``docker.io/redpandadata/redpanda:v24.2.1``) so it matches the version under
    test and is already cached locally — avoiding an unauthenticated Docker Hub
    pull that can hit the rate limit (429) in CI/dev.
    """
    with RedpandaContainer(image="docker.io/redpandadata/redpanda:v24.2.1") as container:
        yield container


async def test_first_run_creates_all_topics_with_correct_partitions(redpanda: RedpandaContainer) -> None:
    """AC #1/#6: a single provision run creates the 6 topics at their fixed partition counts."""
    mod = _load_provision_topics()
    brokers = redpanda.get_bootstrap_server()

    results = await mod.provision_topics(bootstrap_servers=brokers)  # type: ignore[attr-defined]
    expected = {name for name, _, _ in mod.TOPIC_SPEC}  # type: ignore[attr-defined]
    assert set(results) == expected
    assert all(status == "created" for status in results.values())

    # Verify against the actual broker metadata (AC #1: exact partition counts).
    spec_map = {name: partitions for name, partitions, _ in mod.TOPIC_SPEC}  # type: ignore[attr-defined]
    admin = AIOKafkaAdminClient(bootstrap_servers=brokers)
    await admin.start()
    try:
        meta = await admin.describe_topics(list(spec_map))
        for info in meta:
            assert info["topic"] in spec_map
            assert len(info["partitions"]) == spec_map[info["topic"]], info["topic"]
    finally:
        await admin.close()


async def test_second_run_is_an_idempotent_noop(redpanda: RedpandaContainer) -> None:
    """AC #2: re-running reports every topic as ``exists`` and leaves partitions untouched."""
    mod = _load_provision_topics()
    brokers = redpanda.get_bootstrap_server()

    # First run establishes the topics (no-op if the previous test already did).
    await mod.provision_topics(bootstrap_servers=brokers)  # type: ignore[attr-defined]
    # Second run must be a clean no-op: every topic reports "exists".
    results = await mod.provision_topics(bootstrap_servers=brokers)  # type: ignore[attr-defined]
    assert all(status == "exists" for status in results.values()), results
