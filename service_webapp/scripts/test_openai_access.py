"""Standalone script to verify Azure OpenAI access via structured output.

Run with: uv run scripts/test_openai_access.py
"""

from __future__ import annotations

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import AzureChatOpenAI
from pydantic import BaseModel, Field

from core.config import settings


class ComplaintExtraction(BaseModel):
    """Structured fields extracted from a subscriber complaint message."""

    category: str = Field(description="One-word category of the complaint, e.g. billing, network, data")
    sentiment: str = Field(description="Overall sentiment: positive, neutral, or negative")
    summary: str = Field(description="One-sentence summary of the complaint")
    requires_escalation: bool = Field(description="Whether this complaint needs escalation to a human agent")


def main() -> None:
    config = dict(
        azure_endpoint=settings.azure_openai_endpoint,
        api_key=settings.azure_openai_api_key,
        api_version=settings.azure_openai_api_version,
        azure_deployment=settings.chat_deployment,
    )
    print(config)
    llm = AzureChatOpenAI(
        **config,
        temperature=0,
    )
    structured_llm = llm.with_structured_output(ComplaintExtraction)

    messages = [
        SystemMessage(
            content=("You are a telecom support assistant. Extract structured details from the subscriber's message.")
        ),
        HumanMessage(
            content=(
                "I've been charged twice for my data pack this month and my internet "
                "has been down for three days. This is unacceptable, I want a refund now."
            )
        ),
    ]

    result = structured_llm.invoke(messages)
    print(result.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
