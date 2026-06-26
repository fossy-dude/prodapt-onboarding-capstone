#!/usr/bin/env python3
"""Generate architecture diagrams for SBO AI using the diagrams library."""

import os

from diagrams import Cluster, Diagram
from diagrams.aws.security import Cognito
from diagrams.azure.aimachinelearning import CognitiveServices
from diagrams.onprem.aggregator import Fluentd
from diagrams.onprem.ci import GithubActions
from diagrams.onprem.client import User
from diagrams.onprem.compute import Server
from diagrams.onprem.database import Postgresql
from diagrams.onprem.inmemory import Redis
from diagrams.onprem.queue import Kafka
from diagrams.programming.framework import Fastapi, React
from diagrams.programming.language import Python


def generate_mvp_architecture():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(script_dir)
    output_path = os.path.join(project_root, "docs", "architecture_mvp")

    graph_attr = {
        "bgcolor": "white",
        "fontsize": "22",
        "rankdir": "TB",
        "splines": "ortho",
        "nodesep": "0.8",
        "ranksep": "1.4",
        "pad": "0.8",
        "compound": "true",
    }
    node_attr = {
        "fontsize": "11",
        "height": "1.4",
        "width": "1.8",
    }

    with Diagram(
        "SBO AI - MVP Architecture",
        filename=output_path,
        outformat="jpg",
        graph_attr=graph_attr,
        node_attr=node_attr,
        show=False,
    ):
        # ── USERS ─────────────────────────────────────────────────────────
        with Cluster("Users"):
            subscriber_user = User("Subscriber Portal")
            ops_user_node = User("Ops Dashboard")
            fraud_user_node = User("Fraud Dashboard")
            sim_user_node = User("Simulator / Dev")

        # ── FRONTEND ──────────────────────────────────────────────────────
        with Cluster("Frontend (React 18 + Vite + TailwindCSS)"):
            fe_sub = React("Subscriber Portal\n(React SPA)")
            fe_ops = React("Ops Dashboard\n(React SPA)")
            fe_fraud = React("Fraud Dashboard\n(React SPA)")
            fe_sim = React("Simulator Portal\n(React SPA)")

        # ── AUTH ──────────────────────────────────────────────────────────
        auth = Cognito("Identity Provider\n(AWS Cognito)")

        # ── APP BACKEND ───────────────────────────────────────────────────
        with Cluster("App Backend (Python 3.14 + FastAPI)"):
            acct_router = Fastapi("Account Router\n(FR-1 to 7)")
            bal_router = Fastapi("Balance Router\n(FR-8 to 11)")
            rchg_router = Fastapi("Recharge Router\n(FR-12 to 17)")
            notif_router = Fastapi("Notifications Router\n(FR-18 to 21)")
            ussd_router = Fastapi("USSD Router\n(FR-37 to 41)")
            ops_router = Fastapi("Ops Router\n(FR-42 to 52)")
            fraud_router = Fastapi("Fraud Router\n(FR-53 to 56)")
            sim_router = Fastapi("Simulator Router\n(FR-68 to 70)")
            copilot = Server("AG-UI Runtime\n(CopilotKit)")
            chatbot_agent = Python("Self-Care Chatbot\n(LangGraph)")
            fraud_agent = Python("Fraud Detection Agent\n(LangGraph)")
            ops_agents = Python("Ops & Marketing Agents\n(LangGraph)")
            milvus_lite = Postgresql("Vector Store\n(Milvus Lite)")
            ml = Python("ML Forecasting\n(scikit-learn)")
            pdf = Server("PDF Receipts\n(WeasyPrint)")

        # ── CDR PIPELINE ──────────────────────────────────────────────────
        with Cluster("CDR Pipeline (Python + aiokafka)"):
            consumer = Server("CDR Consumer\n(batch 500)")
            dedup = Server("Idempotency Guard\n(Valkey TTL 24h)")
            bal_writer = Server("Balance Writer\n(INCRBY async PG flush)")
            screener = Server("Rule-Based Pre-Screener\n(Fraud Flags)")
            dlq_handler = Server("DLQ Handler\n(cdr.dlq)")
            mgmt_api = Server("Management API\n(pause/resume/DLQ)")

        # ── EVENT BUS ─────────────────────────────────────────────────────
        with Cluster("Event Bus (Redpanda - 24 partitions)"):
            t_raw = Kafka("cdr.raw (24p)")
            t_enr = Kafka("cdr.enriched.filtered (24p)")
            t_fraud_f = Kafka("cdr.fraud.flagged (6p)")
            t_fraud_a = Kafka("fraud.alerts (6p)")
            t_notif = Kafka("notification.events (12p)")
            t_dlq = Kafka("cdr.dlq (6p)")

        # ── DATA STORES ───────────────────────────────────────────────────
        postgres = Postgresql("Primary Database\n(PostgreSQL 16)")
        valkey = Redis("Cache & Write Buffer\n(Valkey 512MB)")

        # ── LLM PROVIDER ──────────────────────────────────────────────────
        llm = CognitiveServices("LLM Provider\n(Azure OpenAI\nGPT-4o-mini)")

        # ── OBSERVABILITY ─────────────────────────────────────────────────
        with Cluster("Observability (Docker)"):
            langfuse = Server("Agent Traces\n(LangFuse)")
            otel_tui = Server("Infra Traces & Metrics\n(OTEL-TUI)")
            fluentd_node = Fluentd("Log Routing\n(Fluentd)")

        # ── CI/CD ─────────────────────────────────────────────────────────
        cicd = GithubActions("CI/CD\n(GitHub Actions - uv tox)")

        # ── EDGES ─────────────────────────────────────────────────────────

        # Users → Frontend portals
        subscriber_user >> fe_sub
        ops_user_node >> fe_ops
        fraud_user_node >> fe_fraud
        sim_user_node >> fe_sim

        # Frontend → Auth (login)
        fe_sub >> auth

        # Frontend → Backend routers
        fe_sub >> copilot
        fe_sub >> bal_router
        fe_sub >> rchg_router
        fe_ops >> ops_router
        fe_fraud >> fraud_router
        fe_sim >> sim_router

        # Auth validates all backend requests (representative connections)
        auth >> acct_router
        auth >> ops_router
        auth >> fraud_router

        # CopilotKit → Chatbot agent
        copilot >> chatbot_agent

        # Agents → LLM provider
        chatbot_agent >> llm
        fraud_agent >> llm
        ops_agents >> llm

        # Chatbot → Vector Store (RAG)
        chatbot_agent >> milvus_lite

        # CDR ingest pipeline: Simulator → Event Bus → Consumer → downstream
        sim_router >> t_raw
        t_raw >> consumer
        consumer >> dedup
        dedup >> valkey
        consumer >> bal_writer
        bal_writer >> valkey
        bal_writer >> postgres
        consumer >> screener
        screener >> t_fraud_f
        screener >> t_enr
        consumer >> dlq_handler
        dlq_handler >> t_dlq

        # Event-driven: topics → consumers
        t_fraud_f >> fraud_agent
        t_enr >> notif_router
        t_fraud_a >> fraud_router
        t_notif >> notif_router

        # Agents publish to topics
        fraud_agent >> t_fraud_a
        chatbot_agent >> t_notif

        # App Backend → Data stores
        acct_router >> postgres
        rchg_router >> postgres
        ops_router >> postgres
        bal_router >> valkey
        ussd_router >> valkey
        rchg_router >> valkey

        # Observability: agents → LangFuse traces
        chatbot_agent >> langfuse
        fraud_agent >> langfuse
        ops_agents >> langfuse

        # Observability: infra telemetry → OTEL-TUI (representative edges)
        acct_router >> otel_tui
        consumer >> otel_tui
        fluentd_node >> otel_tui

        # CI/CD → App Backend and CDR Pipeline (representative edges)
        cicd >> acct_router
        cicd >> consumer


if __name__ == "__main__":
    generate_mvp_architecture()
    print("Exported: docs/architecture_mvp.jpg")
