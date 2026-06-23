"""Unit tests for the Milvus Lite seeder (scripts/seed_milvus.py) — Story 2.7 code-review fixes.

Covers code-review findings #1, #2, #4, #5, #6: the seeder is fully mocked — no
network, no real Milvus, no real Postgres. The seeder lives under ``scripts/``
(outside ``service_webapp/src``), so it is loaded via importlib from its file path.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest

if TYPE_CHECKING:
    from types import ModuleType

# ── Load the seeder module from scripts/seed_milvus.py ─────────────────────────
_SEEDER_PATH = Path(__file__).resolve().parents[3] / "scripts" / "seed_milvus.py"


def _load_seeder_module() -> ModuleType:
    """Import scripts/seed_milvus.py via importlib (it is outside service_webapp/src)."""
    spec = importlib.util.spec_from_file_location("seed_milvus", _SEEDER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def seeder() -> ModuleType:
    return _load_seeder_module()


@pytest.fixture
def fake_embedding_model() -> MagicMock:
    """Return a fake AzureOpenAIEmbeddings yielding one 1536-dim vector per input text."""
    model = MagicMock()

    def _embed(texts: list[str]) -> list[list[float]]:
        return [[0.01] * 1536 for _ in texts]

    model.embed_documents.side_effect = _embed
    return model


# ── seed_plan_vectors (finding #1) ────────────────────────────────────────────


def test_seed_plan_vectors_upserts_correct_rows_and_omits_plan_type_from_sql(
    seeder: ModuleType, fake_embedding_model: MagicMock
) -> None:
    client = MagicMock()
    client.get_collection_stats.return_value = {"row_count": 2}
    # Fake DB rows: (id, plan_name, plan_code, price_paise, validity_days) — 5 wide,
    # matching the corrected SELECT that no longer asks for a nonexistent plan_type.
    fake_rows = [
        ("11111111-1111-1111-1111-111111111111", "Prepaid Basic", "prepaid_basic", 29900, 28),
        ("22222222-2222-2222-2222-222222222222", "Postpaid Pro", "postpaid_pro", 49900, 30),
    ]
    cursor = MagicMock()
    cursor.fetchall.return_value = fake_rows
    conn = MagicMock()
    conn.execute.return_value = cursor

    count = seeder.seed_plan_vectors(client, fake_embedding_model, conn)

    assert count == 2
    client.upsert.assert_called_once()
    kwargs = client.upsert.call_args.kwargs
    assert kwargs["collection_name"] == "plan_vectors"
    rows = kwargs["data"]
    assert len(rows) == 2

    expected_keys = {"plan_id", "text", "embedding", "plan_type", "price", "validity"}
    for row in rows:
        assert set(row.keys()) == expected_keys
        assert len(row["embedding"]) == 1536

    # plan_type must be derived from plan_code (not None), via the helper.
    assert rows[0]["plan_type"] == "PREPAID"
    assert rows[1]["plan_type"] == "POSTPAID"
    assert rows[0]["price"] == 29900
    assert rows[0]["validity"] == 28

    # The SQL the fake cursor received must NOT mention plan_type.
    sql_arg = conn.execute.call_args.args[0]
    assert "plan_type" not in sql_arg


def test_plan_type_from_code_helper(seeder: ModuleType) -> None:
    assert seeder._plan_type_from_code("prepaid_basic") == "PREPAID"
    assert seeder._plan_type_from_code("postpaid") == "POSTPAID"
    assert seeder._plan_type_from_code("") == ""
    assert seeder._plan_type_from_code(None) == ""  # type: ignore[arg-type]
    long_code = "x" * 200
    assert len(seeder._plan_type_from_code(long_code)) == 128


# ── seed_faq_chunks ───────────────────────────────────────────────────────────


def test_seed_faq_chunks_upserts_correct_row_keys(seeder: ModuleType, fake_embedding_model: MagicMock) -> None:
    client = MagicMock()
    client.get_collection_stats.return_value = {"row_count": 2}
    fake_faqs = {
        "faqs": [
            {"id": "f1", "question": "q1", "answer": "a1", "category": "billing", "source_doc": "doc1"},
            {"id": "f2", "question": "q2", "answer": "a2", "category": "plans", "source_doc": "doc2"},
        ]
    }
    fake_yaml_dump = """
faqs:
  - id: f1
    question: q1
    answer: a1
    category: billing
    source_doc: doc1
  - id: f2
    question: q2
    answer: a2
    category: plans
    source_doc: doc2
"""
    expected_keys = {"chunk_id", "text", "embedding", "category", "source_doc", "plan_type"}

    with patch.object(seeder.yaml, "safe_load", return_value=fake_faqs):
        count = seeder.seed_faq_chunks(client, fake_embedding_model)

    assert count == 2
    client.upsert.assert_called_once()
    rows = client.upsert.call_args.kwargs["data"]
    assert len(rows) == 2
    for row in rows:
        assert set(row.keys()) == expected_keys
        assert len(row["embedding"]) == 1536

    # yaml.safe_load is the real mechanism; the fake_yaml_dump above documents the shape.
    _ = fake_yaml_dump


# ── seed_sop_chunks (finding #2) ──────────────────────────────────────────────


def test_seed_sop_chunks_row_keys_and_empty_severity(seeder: ModuleType, fake_embedding_model: MagicMock) -> None:
    client = MagicMock()
    client.get_collection_stats.return_value = {"row_count": 2}
    # Fake DB rows: (id, chunk_text, source_document, domain) — no severity column.
    fake_rows = [
        ("sop-1", "rule text one", "SOP_DOC_A", "billing"),
        ("sop-2", "rule text two", "SOP_DOC_B", "fraud"),
    ]
    cursor = MagicMock()
    cursor.fetchall.return_value = fake_rows
    conn = MagicMock()
    conn.execute.return_value = cursor

    count = seeder.seed_sop_chunks(client, fake_embedding_model, conn)

    assert count == 2
    client.upsert.assert_called_once()
    kwargs = client.upsert.call_args.kwargs
    assert kwargs["collection_name"] == "sop_chunks"
    rows = kwargs["data"]
    assert len(rows) == 2

    expected_keys = {"chunk_id", "text", "embedding", "rule_id", "severity", "domain"}
    for row in rows:
        assert set(row.keys()) == expected_keys
        assert len(row["embedding"]) == 1536
        # severity has no source column yet — must be the empty string, not None.
        assert row["severity"] == ""
    assert rows[0]["rule_id"] == "SOP_DOC_A"
    assert rows[1]["domain"] == "fraud"

    # The SQL must not ask for severity.
    sql_arg = conn.execute.call_args.args[0]
    assert "severity" not in sql_arg


def test_seed_sop_chunks_returns_zero_when_empty(seeder: ModuleType, fake_embedding_model: MagicMock) -> None:
    client = MagicMock()
    cursor = MagicMock()
    cursor.fetchall.return_value = []
    conn = MagicMock()
    conn.execute.return_value = cursor

    count = seeder.seed_sop_chunks(client, fake_embedding_model, conn)
    assert count == 0
    client.upsert.assert_not_called()


# ── drop_and_create idempotency (finding #5) ──────────────────────────────────


def test_drop_and_create_drops_when_present(seeder: ModuleType) -> None:
    client = MagicMock()
    client.has_collection.return_value = True

    with (
        patch.object(seeder, "_build_schema", return_value=MagicMock()),
        patch.object(seeder, "_build_index_params", return_value=MagicMock()),
    ):
        seeder.drop_and_create(client, "plan_vectors")

    client.has_collection.assert_called_once_with("plan_vectors")
    client.drop_collection.assert_called_once_with("plan_vectors")
    client.create_collection.assert_called_once()


def test_drop_and_create_does_not_drop_when_absent(seeder: ModuleType) -> None:
    client = MagicMock()
    client.has_collection.return_value = False

    with (
        patch.object(seeder, "_build_schema", return_value=MagicMock()),
        patch.object(seeder, "_build_index_params", return_value=MagicMock()),
    ):
        seeder.drop_and_create(client, "faq_chunks")

    client.has_collection.assert_called_once_with("faq_chunks")
    client.drop_collection.assert_not_called()
    client.create_collection.assert_called_once()


# ── _build_schema metadata fields (finding #6) ────────────────────────────────


def test_build_schema_adds_expected_metadata_fields(seeder: ModuleType) -> None:
    """All per-collection metadata scalars are added to the schema (pk/text/embedding/sparse too)."""
    with patch.object(seeder, "MilvusClient") as mock_cls:
        schema_mock = MagicMock()
        mock_cls.create_schema.return_value = schema_mock

        for collection, expected_extras in [
            ("faq_chunks", {"category", "source_doc", "plan_type"}),
            ("plan_vectors", {"plan_type", "price", "validity"}),
            ("sop_chunks", {"rule_id", "severity", "domain"}),
        ]:
            schema_mock.add_field.reset_mock()
            seeder._build_schema(collection)
            field_names = {call.kwargs["field_name"] for call in schema_mock.add_field.call_args_list}
            # Standard fields every collection has.
            assert "text" in field_names
            assert "embedding" in field_names
            assert "sparse_embedding" in field_names
            # Per-collection PK + metadata scalars.
            assert seeder._PK[collection] in field_names
            assert expected_extras <= field_names


def test_build_schema_embedding_dim_is_1536(seeder: ModuleType) -> None:
    with patch.object(seeder, "MilvusClient") as mock_cls:
        schema_mock = MagicMock()
        mock_cls.create_schema.return_value = schema_mock
        seeder._build_schema("plan_vectors")

    embedding_call = next(c for c in schema_mock.add_field.call_args_list if c.kwargs.get("field_name") == "embedding")
    assert embedding_call.kwargs["dim"] == 1536
