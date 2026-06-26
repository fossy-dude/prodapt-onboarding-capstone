#!/usr/bin/env python3
"""Generate architecture diagrams for SBO AI using the diagrams library."""

import os

from diagrams import Cluster, Diagram
from diagrams.aws.analytics import ManagedStreamingForKafka
from diagrams.aws.database import Elasticache, RDS
from diagrams.aws.network import APIGateway, CloudFront
from diagrams.aws.security import Cognito
from diagrams.aws.storage import S3
from diagrams.azure.aimachinelearning import CognitiveServices
from diagrams.oci.database import DBService
from diagrams.oci.governance import Logging
from diagrams.onprem.aggregator import Fluentd
from diagrams.onprem.ci import GithubActions
from diagrams.onprem.client import User
from diagrams.onprem.compute import Server
from diagrams.onprem.database import Postgresql
from diagrams.onprem.inmemory import Redis
from diagrams.onprem.monitoring import Grafana
from diagrams.onprem.queue import Kafka
from diagrams.programming.framework import Fastapi, React
from diagrams.programming.language import Python, Rust

TOP_PADDING = "\n" * 2


def generate_mvp_architecture():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(script_dir)
    output_path = os.path.join(project_root, "docs", "architecture_mvp")

    graph_attr = {
        "bgcolor": "white",
        "fontsize": "22",
        "rankdir": "TB",
        "splines": "ortho",
        "nodesep": "1.0",
        "ranksep": "1.6",
        "pad": "0.8",
        "compound": "true",
    }
    node_attr = {
        "fontsize": "11",
        "fontname": "Helvetica-Bold",
        "height": "1.8",
        "width": "2.2",
        "margin": "0.15,0.45",
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
            subscriber_user = User(f"{TOP_PADDING * 2}Subscriber")
            ops_user_node = User(f"{TOP_PADDING * 2}Ops Manager")
            fraud_user_node = User(f"{TOP_PADDING * 2}Fraud Analyst")
            sim_user_node = User(f"{TOP_PADDING * 2}Simulator / Dev")

        # ── FRONTEND ──────────────────────────────────────────────────────
        # Single React SPA with role-based routing; CopilotKit embedded for chatbot UI
        with Cluster("Frontend (React 18 + Vite + TailwindCSS + CopilotKit)"):
            fe_sub = React(f"{TOP_PADDING}Subscriber Portal")
            fe_ops = React(f"{TOP_PADDING}Ops Dashboard")
            fe_fraud = React(f"{TOP_PADDING}Fraud Dashboard")
            fe_sim = React(f"{TOP_PADDING}Simulator Portal")

        # ── AUTH ──────────────────────────────────────────────────────────
        auth = Cognito(f"{TOP_PADDING}AWS Cognito\n(Identity Provider)")

        # ── APP BACKEND ───────────────────────────────────────────────────
        # FastAPI monorepo; LangGraph agents run in-process; Milvus Lite embedded
        with Cluster("App Backend (Python 3.14 + FastAPI)"):
            fastapi_svc = Fastapi(f"{TOP_PADDING}FastAPI Service")
            chatbot_agent = Python(f"{TOP_PADDING}Self-Care Chatbot\n(LangGraph)")
            fraud_agent = Python(f"{TOP_PADDING}Fraud Detection Agent\n(LangGraph)")
            ops_agents = Python(f"{TOP_PADDING}Ops & Marketing Agents\n(LangGraph)")
            milvus_lite = DBService(
                f"{TOP_PADDING}Milvus Lite\n(Vector Store, embedded)"
            )

        # ── CDR PIPELINE ──────────────────────────────────────────────────
        with Cluster("CDR Pipeline (Python + aiokafka)"):
            cdr_consumer = Server(
                f"{TOP_PADDING}CDR Consumer Service\n(batch 500, idempotent)"
            )

        # ── EVENT BUS ─────────────────────────────────────────────────────
        # Redpanda is Kafka-wire-compatible; topics grouped by logical domain
        with Cluster("Event Bus (Redpanda, Podman)"):
            t_cdr = Kafka(
                f"{TOP_PADDING}CDR Topics\n(cdr.raw, cdr.enriched.filtered, cdr.dlq)"
            )
            t_fraud = Kafka(
                f"{TOP_PADDING}Fraud Topics\n(cdr.fraud.flagged, fraud.alerts)"
            )
            t_notif = Kafka(f"{TOP_PADDING}Notification Topic\n(notification.events)")

        # ── DATA STORES ───────────────────────────────────────────────────
        postgres = Postgresql(f"{TOP_PADDING}PostgreSQL 16\n(Primary Database)")
        valkey = Redis(f"{TOP_PADDING}Valkey\n(Cache & Write Buffer, Podman)")

        # ── LLM PROVIDER ──────────────────────────────────────────────────
        llm = CognitiveServices(
            f"{TOP_PADDING}Azure OpenAI\n(GPT-5.4*, text-embedding-3-small)"
        )

        # ── OBSERVABILITY ─────────────────────────────────────────────────
        with Cluster("Observability (Podman)"):
            langfuse = Logging(f"{TOP_PADDING}LangFuse\n(Agent Traces)")
            otel_tui = Logging(f"{TOP_PADDING}OTEL-TUI\n(Infra Traces & Metrics)")
            fluentd_node = Fluentd(f"{TOP_PADDING}Fluentd\n(Log Routing)")

        # ── CI/CD ─────────────────────────────────────────────────────────
        cicd = GithubActions(
            f"{TOP_PADDING}GitHub Actions\n(CI/CD - uv tox, Podman build)"
        )

        # ── EDGES ─────────────────────────────────────────────────────────

        # Users → Frontend portals
        subscriber_user >> fe_sub
        ops_user_node >> fe_ops
        fraud_user_node >> fe_fraud
        sim_user_node >> fe_sim

        # Frontend → Auth (JWT login / OTP)
        fe_sub >> auth

        # Frontend → App Backend (REST + AG-UI event stream)
        [fe_sub, fe_ops, fe_fraud, fe_sim] >> fastapi_svc

        # Auth validates all backend requests
        auth >> fastapi_svc

        # FastAPI routes to LangGraph agents
        fastapi_svc >> chatbot_agent
        fastapi_svc >> fraud_agent
        fastapi_svc >> ops_agents

        # Agents → LLM (inference + embeddings)
        chatbot_agent >> llm
        fraud_agent >> llm
        ops_agents >> llm

        # Chatbot RAG: queries vector store
        chatbot_agent >> milvus_lite

        # App Backend → Data stores
        fastapi_svc >> postgres
        fastapi_svc >> valkey

        # Simulator Portal publishes CDRs → cdr.raw
        fastapi_svc >> t_cdr

        # CDR Consumer: consumes cdr.raw, produces cdr.enriched.filtered + cdr.dlq
        t_cdr >> cdr_consumer
        cdr_consumer >> t_cdr

        # CDR Consumer: flags suspicious CDRs → fraud topics
        cdr_consumer >> t_fraud

        # CDR Consumer → Data stores (balance writes + dedup)
        cdr_consumer >> postgres
        cdr_consumer >> valkey

        # Fraud Agent: consumes cdr.fraud.flagged, publishes fraud.alerts
        t_fraud >> fraud_agent
        fraud_agent >> t_fraud

        # Chatbot Agent: publishes notification events
        chatbot_agent >> t_notif

        # App Backend consumes notification events (delivery)
        t_notif >> fastapi_svc

        # Agents → LangFuse (agent + tool call traces)
        chatbot_agent >> langfuse
        fraud_agent >> langfuse
        ops_agents >> langfuse

        # Services → OTEL-TUI (infra traces, metrics)
        fastapi_svc >> otel_tui
        cdr_consumer >> otel_tui
        fluentd_node >> otel_tui

        # CI/CD → services
        cicd >> fastapi_svc
        cicd >> cdr_consumer


def generate_target_architecture():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(script_dir)
    output_path = os.path.join(project_root, "docs", "architecture_target")

    graph_attr = {
        "bgcolor": "white",
        "fontsize": "22",
        "rankdir": "TB",
        "splines": "ortho",
        "nodesep": "1.0",
        "ranksep": "1.6",
        "pad": "0.8",
        "compound": "true",
    }
    node_attr = {
        "fontsize": "11",
        "fontname": "Helvetica-Bold",
        "height": "1.8",
        "width": "2.2",
        "margin": "0.15,0.45",
    }

    with Diagram(
        "SBO AI - Target Architecture",
        filename=output_path,
        outformat="jpg",
        graph_attr=graph_attr,
        node_attr=node_attr,
        show=False,
    ):
        # ── USERS ─────────────────────────────────────────────────────────
        with Cluster("Users"):
            subscriber_user = User(f"{TOP_PADDING * 2}Subscriber")
            ops_user_node = User(f"{TOP_PADDING * 2}Ops Manager")
            fraud_user_node = User(f"{TOP_PADDING * 2}Fraud Analyst")

        # ── CDN ───────────────────────────────────────────────────────────
        cdn = CloudFront(f"{TOP_PADDING}AWS CloudFront\n(CDN)")

        # ── FRONTEND ──────────────────────────────────────────────────────
        with Cluster("Frontend (React 18 + Vite + TailwindCSS, S3 Origin)"):
            fe_sub = React(f"{TOP_PADDING}Subscriber Portal")
            fe_ops = React(f"{TOP_PADDING}Ops Dashboard")
            fe_fraud = React(f"{TOP_PADDING}Fraud Dashboard")

        # ── AUTH + API GATEWAY ────────────────────────────────────────────
        api_gw = APIGateway(f"{TOP_PADDING}API Gateway\n(Rate Limit, JWT Validation)")

        # ── AWS EKS CLUSTER ───────────────────────────────────────────────
        with Cluster("AWS EKS"):
            keycloak = Server(f"{TOP_PADDING}Keycloak\n(Enterprise IdP, RBAC)")

            with Cluster("App Backend (Python 3.14 + FastAPI)"):
                fastapi_svc = Fastapi(f"{TOP_PADDING}FastAPI Service")

            with Cluster("CDR Pipeline (Rust / tokio + rdkafka)"):
                cdr_pipeline = Rust(
                    f"{TOP_PADDING}CDR Pipeline\n(100K eps, sub-200ms P95)"
                )
                cdr_simulator = Rust(f"{TOP_PADDING}CDR Simulator\n(feature-flagged)")

            langfuse = Logging(f"{TOP_PADDING}LangFuse\n(Self-hosted, Enterprise)")
        # Agents
        with Cluster("AgentCore Runtime)"):
            chatbot_agent = Python(f"{TOP_PADDING}Self-Care Chatbot\n(LangGraph)")
            fraud_agent = Python(f"{TOP_PADDING}Fraud Detection Agent\n(LangGraph)")
            ops_agents = Python(f"{TOP_PADDING}Ops & Marketing Agents\n(LangGraph)")
        # ── EVENT BUS (MSK) ───────────────────────────────────────────────
        with Cluster("Amazon MSK (Multi-partitions)"):
            t_cdr = ManagedStreamingForKafka(
                f"{TOP_PADDING}CDR Topics\n(cdr.raw, cdr.enriched, cdr.dlq)"
            )
            t_fraud = ManagedStreamingForKafka(
                f"{TOP_PADDING}Fraud Topics\n(fraud.flagged, fraud.alerts)"
            )
            t_notif = ManagedStreamingForKafka(
                f"{TOP_PADDING}Notification Topic\n(notification.events)"
            )

        # ── DATA STORES ───────────────────────────────────────────────────
        with Cluster("Data stores"):
            milvus = DBService(f"{TOP_PADDING}Milvus Distributed\n(Vector Store)")
            rds = RDS(f"{TOP_PADDING}Amazon RDS PostgreSQL\n(Multi-AZ, Read-replicas)")
            valkey = Elasticache(f"{TOP_PADDING}ElastiCache Valkey\n(Write Buffer)")

        # ── LLM PROVIDER ──────────────────────────────────────────────────
        with Cluster("Inference Services (Across clouds)"):
            llm = CognitiveServices(
                f"{TOP_PADDING}Azure OpenAI\n(GPT-4o-mini, text-embedding-3-small)"
            )
            ml_forecast = CognitiveServices(
                f"{TOP_PADDING}ML Forecasting\n(TimesFM / Chronos)"
            )

        # ── OBSERVABILITY (LGTM) ──────────────────────────────────────────
        with Cluster("Observability - LGTM (Managed Grafana)"):
            grafana = Grafana(f"{TOP_PADDING}Grafana\n(Dashboards & Alerts)")
            loki = Logging(f"{TOP_PADDING}Loki\n(Logs)")
            tempo = Logging(f"{TOP_PADDING}Tempo\n(Traces)")
            mimir = Logging(f"{TOP_PADDING}Mimir\n(Metrics)")
            fluentd_node = Fluentd(f"{TOP_PADDING}Fluentd DaemonSet\n(Log Routing)")

        # ── AUDIT ARCHIVE ─────────────────────────────────────────────────
        s3_archive = S3(f"{TOP_PADDING}S3 + Glacier\n(Audit Archive, 6yr TRAI)")

        # ── CI/CD ─────────────────────────────────────────────────────────
        cicd = GithubActions(
            f"{TOP_PADDING}GitHub Actions\n(CI/CD - uv tox, EKS deploy)"
        )

        # ── EDGES ─────────────────────────────────────────────────────────

        # Users → CDN
        [subscriber_user, ops_user_node, fraud_user_node] >> cdn

        # CDN → Frontend (static assets from S3)
        cdn >> [fe_sub, fe_ops, fe_fraud]

        # Frontend → API Gateway
        [fe_sub, fe_ops, fe_fraud] >> api_gw

        # Keycloak JWT validation via API Gateway
        keycloak >> api_gw

        # API Gateway → FastAPI
        api_gw >> fastapi_svc

        # FastAPI → Agents
        fastapi_svc >> chatbot_agent
        fastapi_svc >> fraud_agent
        fastapi_svc >> ops_agents

        # Agents → LLM (inference + embeddings)
        chatbot_agent >> llm
        fraud_agent >> llm
        ops_agents >> llm

        # Chatbot RAG → Milvus Distributed
        chatbot_agent >> milvus

        # FastAPI → Data stores
        fastapi_svc >> rds
        fastapi_svc >> valkey

        # CDR Simulator → MSK
        cdr_simulator >> t_cdr

        # CDR Pipeline: consumes cdr.raw, produces cdr.enriched + cdr.dlq
        t_cdr >> cdr_pipeline
        cdr_pipeline >> t_cdr

        # CDR Pipeline: flags suspicious CDRs → fraud topics
        cdr_pipeline >> t_fraud

        # CDR Pipeline → Data stores (OLTP write layer: Valkey buffer → RDS)
        cdr_pipeline >> valkey
        valkey >> rds

        # Fraud Agent: consumes cdr.fraud.flagged, publishes fraud.alerts
        t_fraud >> fraud_agent
        fraud_agent >> t_fraud

        # Chatbot Agent: publishes notification events
        chatbot_agent >> t_notif
        t_notif >> fastapi_svc

        # Agents → LangFuse (agent + tool call traces)
        chatbot_agent >> langfuse
        fraud_agent >> langfuse
        ops_agents >> langfuse

        # Services → LGTM (infra metrics, traces)
        fastapi_svc >> grafana
        cdr_pipeline >> grafana
        langfuse >> tempo

        # Fluentd DaemonSet → Loki (pod log routing)
        fluentd_node >> loki

        # ML Forecasting reads historical data from RDS
        rds >> ml_forecast

        # Audit archive: RDS → S3 + Glacier
        rds >> s3_archive

        # CI/CD → EKS services
        cicd >> fastapi_svc
        cicd >> cdr_pipeline


if __name__ == "__main__":
    generate_mvp_architecture()
    print("Exported: docs/architecture_mvp.jpg")
    generate_target_architecture()
    print("Exported: docs/architecture_target.jpg")
