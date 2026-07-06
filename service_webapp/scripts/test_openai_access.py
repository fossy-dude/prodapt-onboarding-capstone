"""Standalone script to verify Azure OpenAI access via structured output.

Run with: uv run scripts/test_openai_access.py
"""

from __future__ import annotations

from openai import AzureOpenAI
from pydantic import BaseModel, Field

from core.config import settings


class ComplaintExtraction(BaseModel):
    """Structured fields extracted from a subscriber complaint message."""

    category: str = Field(description="One-word category of the complaint, e.g. billing, network, data")
    sentiment: str = Field(description="Overall sentiment: positive, neutral, or negative")
    summary: str = Field(description="One-sentence summary of the complaint")
    requires_escalation: bool = Field(description="Whether this complaint needs escalation to a human agent")


def main() -> None:
    client = AzureOpenAI(
        api_version=settings.azure_openai_api_version,
        azure_endpoint=settings.azure_openai_endpoint,
        api_key=settings.azure_openai_api_key,
    )

    response = client.chat.completions.parse(
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a telecom support assistant. Extract structured details from the subscriber's message."
                ),
            },
            {
                "role": "user",
                "content": (
                    "I've been charged twice for my data pack this month and my internet "
                    "has been down for three days. This is unacceptable, I want a refund now."
                ),
            },
        ],
        model=settings.chat_deployment_mini,
        response_format=ComplaintExtraction,
    )

    result = response.choices[0].message.parsed
    print(result.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
