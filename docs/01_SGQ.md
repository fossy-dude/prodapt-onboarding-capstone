# 1. Current State

- Telecom operators run large-scale prepaid billing platforms processing millions of CDRs, managing subscriber balances, and supporting diverse payment methods across a massive subscriber base.
- Existing systems handle real-time rating, plan management, and basic subscriber notifications through established but largely siloed charging and balance workflows. Revenue leakage, reactive fraud response, high churn, higher costs and poor subscriber experience occur due to absence of AI-driven decisioning across the billing lifecycle.
- The operator seeks to embed AI/GenAI across the billing lifecycle — enabling intelligent fraud detection, subscriber growth forecasting, personalised plan recommendations, and an NLP-driven self-care experience.

# 2. Future State

- *Outcome* — Maximise ARPU and minimise churn by embedding AI/GenAI across charging, subscriber intelligence, fraud detection, and self-care within a unified prepaid billing platform.
- *Behaviour* — Operations teams act on real-time anomaly dashboards; subscribers self-serve their support queries via an AI chatbot; marketing leverages demand forecasts to design targeted offers proactively.
- *Insight* — A multi-agent system ingesting CDRs to drive real-time balance and fraud management, time-series churn/growth forecasting, LLM-powered self-care, and hybrid plan recommendation with continuous eval feedback loops for customers

# 3. Gap

- *No AI layer on CDR pipeline* — Rated CDRs today are rule based and cannot adapt quickly; anomaly detection, fraud signals, and segmentation must be retrofitted onto a streaming ingestion architecture capable of 100K events/sec.
- *Absent agentic orchestration* — Charging, fraud, notifications, and support are isolated; closing the gap requires addressing data silos & a reliable multi-agent framework (e.g., LangGraph) enabling multi-agent communication, orchestration, and coordinated decisioning.
- *Missing evaluation & feedback infrastructure* — Plan recommendations and chatbot responses have no quality gate; DeepEval integration, LLM-as-judge, and a usage-driven feedback loop are net-new capabilities with no current-state baseline.
