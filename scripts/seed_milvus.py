"""Milvus Lite seeder — populates faq_chunks, plan_vectors, sop_chunks (Story 2.7; AC #4-7).

Run via: scripts/seed_milvus.sh (which sets PYTHONPATH and env vars).

Idempotent: drops and recreates all three collections on every run (AC #7).
Fails loudly if plans_plans is empty — run `just seed` first.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

import psycopg
import yaml
from langchain_openai import AzureOpenAIEmbeddings
from pymilvus import DataType, Function, FunctionType, MilvusClient

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

_BATCH_SIZE = 100
_EMBEDDING_DIM = 1536
_MAX_VARCHAR = 65_535

_COLLECTIONS = ["faq_chunks", "plan_vectors", "sop_chunks"]
_PK: dict[str, str] = {"faq_chunks": "chunk_id", "plan_vectors": "plan_id", "sop_chunks": "chunk_id"}

_EXTRA_FIELDS: dict[str, list[dict]] = {
    "faq_chunks": [
        {"field_name": "category", "datatype": DataType.VARCHAR, "max_length": 256},
        {"field_name": "source_doc", "datatype": DataType.VARCHAR, "max_length": 512},
        {"field_name": "plan_type", "datatype": DataType.VARCHAR, "max_length": 128},
    ],
    "plan_vectors": [
        {"field_name": "plan_type", "datatype": DataType.VARCHAR, "max_length": 128},
        {"field_name": "price", "datatype": DataType.INT64},
        {"field_name": "validity", "datatype": DataType.INT64},
    ],
    "sop_chunks": [
        {"field_name": "rule_id", "datatype": DataType.VARCHAR, "max_length": 512},
        {"field_name": "severity", "datatype": DataType.VARCHAR, "max_length": 64},
        {"field_name": "domain", "datatype": DataType.VARCHAR, "max_length": 256},
    ],
}


# ── Schema helpers ────────────────────────────────────────────────────────────


def _build_schema(name: str) -> object:
    schema = MilvusClient.create_schema(auto_id=False, enable_dynamic_field=False)
    schema.add_field(field_name=_PK[name], datatype=DataType.VARCHAR, is_primary=True, max_length=64)
    schema.add_field(field_name="text", datatype=DataType.VARCHAR, max_length=_MAX_VARCHAR, enable_analyzer=True)
    schema.add_field(field_name="embedding", datatype=DataType.FLOAT_VECTOR, dim=_EMBEDDING_DIM)
    schema.add_field(field_name="sparse_embedding", datatype=DataType.SPARSE_FLOAT_VECTOR)
    for field in _EXTRA_FIELDS[name]:
        schema.add_field(**field)
    bm25 = Function(
        name="bm25",
        input_field_names=["text"],
        output_field_names=["sparse_embedding"],
        function_type=FunctionType.BM25,
    )
    schema.add_function(bm25)
    return schema


def _build_index_params() -> object:
    ip = MilvusClient.prepare_index_params()
    ip.add_index(
        field_name="embedding", index_type="HNSW", metric_type="COSINE", params={"M": 16, "efConstruction": 256}
    )
    ip.add_index(field_name="sparse_embedding", index_type="SPARSE_INVERTED_INDEX", metric_type="BM25")
    return ip


# ── Embedding helper ──────────────────────────────────────────────────────────


def embed_batch(model: AzureOpenAIEmbeddings, texts: list[str]) -> list[list[float]]:
    """Embed texts in batches of _BATCH_SIZE."""
    results: list[list[float]] = []
    for i in range(0, len(texts), _BATCH_SIZE):
        chunk = texts[i : i + _BATCH_SIZE]
        vectors = model.embed_documents(chunk)
        results.extend(vectors)
        logger.info("  Embedded %d/%d", min(i + _BATCH_SIZE, len(texts)), len(texts))
    return results


# ── Collection lifecycle ──────────────────────────────────────────────────────


def drop_and_create(client: MilvusClient, name: str) -> None:
    if client.has_collection(name):
        client.drop_collection(name)
        logger.info("Dropped existing collection %r", name)
    client.create_collection(collection_name=name, schema=_build_schema(name), index_params=_build_index_params())
    logger.info("Created collection %r", name)


# ── Seeder logic ──────────────────────────────────────────────────────────────


def _plan_type_from_code(plan_code: str) -> str:
    """Derive a coarse plan category from plan_code.

    plans_plans has no plan_type column; the 3.1 brief §9.3 prescribes deriving
    it from the code. We take the segment before the first ``_`` uppercased
    (e.g. ``prepaid_x`` -> ``PREPAID``). Empty/None -> ``""``.
    """
    if not plan_code:
        return ""
    return (str(plan_code).split("_", 1)[0]).upper()[:128]


def seed_plan_vectors(client: MilvusClient, model: AzureOpenAIEmbeddings, conn: psycopg.Connection) -> int:
    logger.info("=== Seeding plan_vectors ===")
    rows = conn.execute(
        "SELECT id, plan_name, plan_code, price_paise, validity_days FROM plans_plans WHERE is_active = TRUE"
    ).fetchall()
    if not rows:
        sys.exit("[seed-milvus] ERROR: plans_plans is empty. Run `just seed` first.")
    texts = [f"{r[1]} {r[2]}" for r in rows]
    vectors = embed_batch(model, texts)
    data = [
        {
            "plan_id": str(r[0])[:64],
            "text": texts[i][:_MAX_VARCHAR],
            "embedding": vectors[i],
            "plan_type": _plan_type_from_code(str(r[2] or "")),
            "price": int(r[3]),
            "validity": int(r[4]),
        }
        for i, r in enumerate(rows)
    ]
    client.upsert(collection_name="plan_vectors", data=data)
    client.flush("plan_vectors")  # flush so row_count reflects the upsert
    count = client.get_collection_stats("plan_vectors")["row_count"]
    logger.info("plan_vectors: %d rows", count)
    return count


def seed_faq_chunks(client: MilvusClient, model: AzureOpenAIEmbeddings) -> int:
    logger.info("=== Seeding faq_chunks ===")
    faq_path = Path(__file__).resolve().parents[1] / "service_webapp" / "data" / "faq.yaml"
    with faq_path.open() as f:
        data_yaml = yaml.safe_load(f)
    entries = data_yaml["faqs"]
    texts = [f"{e['question']} {e['answer']}" for e in entries]
    vectors = embed_batch(model, texts)
    data = [
        {
            "chunk_id": str(e["id"])[:64],
            "text": texts[i][:_MAX_VARCHAR],
            "embedding": vectors[i],
            "category": str(e.get("category", ""))[:256],
            "source_doc": str(e.get("source_doc", ""))[:512],
            "plan_type": str(e.get("plan_type", ""))[:128],
        }
        for i, e in enumerate(entries)
    ]
    client.upsert(collection_name="faq_chunks", data=data)
    client.flush("faq_chunks")  # flush so row_count reflects the upsert
    count = client.get_collection_stats("faq_chunks")["row_count"]
    logger.info("faq_chunks: %d rows", count)
    return count


def seed_sop_chunks(client: MilvusClient, model: AzureOpenAIEmbeddings, conn: psycopg.Connection) -> int:
    logger.info("=== Seeding sop_chunks ===")
    rows = conn.execute("SELECT id, chunk_text, source_document, domain FROM sop_knowledge_chunks").fetchall()
    if not rows:
        logger.warning("sop_knowledge_chunks is empty — skipping sop_chunks seeding")
        return 0
    texts = [r[1] for r in rows]
    vectors = embed_batch(model, texts)
    data = [
        {
            "chunk_id": str(r[0])[:64],
            "text": texts[i][:_MAX_VARCHAR],
            "embedding": vectors[i],
            "rule_id": str(r[2] or "")[:512],
            # No severity source column exists in sop_knowledge_chunks yet;
            # severity is reserved and populated when an SOP source provides it.
            "severity": "",
            "domain": str(r[3] or "")[:256],
        }
        for i, r in enumerate(rows)
    ]
    client.upsert(collection_name="sop_chunks", data=data)
    client.flush("sop_chunks")  # flush so row_count reflects the upsert
    count = client.get_collection_stats("sop_chunks")["row_count"]
    logger.info("sop_chunks: %d rows", count)
    return count


# ── Main ──────────────────────────────────────────────────────────────────────


def main() -> None:
    from core.config import settings  # noqa: PLC0415

    milvus_uri = os.environ.get("MILVUS_DB_URI", settings.milvus_db_uri)
    logger.info("Connecting to Milvus Lite at %r", milvus_uri)
    client = MilvusClient(uri=milvus_uri)

    logger.info("Building embedding model (Azure OpenAI %s)", settings.embedding_model)
    model = AzureOpenAIEmbeddings(
        azure_endpoint=settings.azure_openai_endpoint,
        api_key=settings.azure_openai_api_key,
        azure_deployment=settings.embedding_model,
        openai_api_version=settings.azure_openai_api_version,
        dimensions=settings.embedding_dimensions,
    )

    logger.info("Connecting to Postgres")
    conninfo = (
        f"host={settings.db.host} port={settings.db.port} dbname={settings.db.name} "
        f"user={settings.db.user} password={settings.db.password.get_secret_value()}"
    )
    with psycopg.connect(conninfo) as conn:
        logger.info("Dropping and recreating collections (idempotent)")
        for name in _COLLECTIONS:
            drop_and_create(client, name)

        plan_count = seed_plan_vectors(client, model, conn)
        faq_count = seed_faq_chunks(client, model)
        sop_count = seed_sop_chunks(client, model, conn)

    logger.info("=== Seeding complete ===")
    logger.info("plan_vectors=%d  faq_chunks=%d  sop_chunks=%d", plan_count, faq_count, sop_count)
    # "~1000" is the expected plan count, not a hard requirement; the count varies
    # with how many plans are active. We only assert the collection is non-empty.
    logger.info("plan_vectors count vs ~1000 expectation is informational only (saw %d)", plan_count)

    assert plan_count > 0, f"plan_vectors expected >0, got {plan_count}"
    assert faq_count >= 50, f"faq_chunks expected >=50, got {faq_count}"
    assert sop_count > 0, f"sop_chunks expected >0, got {sop_count}"

    client.close()


if __name__ == "__main__":
    main()
