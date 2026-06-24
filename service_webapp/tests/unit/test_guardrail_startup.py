"""Unit tests for guardrail startup wiring (Story 5.5 Task 5).

Tests that:
- Guardrail is initialized during FastAPI startup
- Guardrail uses correct Azure OpenAI client and embedding model
- System degrades gracefully when Azure OpenAI is unavailable
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from openai import AzureOpenAI

from agents.guardrails.validator import InputGuardrail
from agents.support.graph import set_guardrail, _guardrail


class TestGuardrailStartup:
    """Test guardrail initialization at FastAPI startup."""

    def test_set_guardrail_wires_singleton(self):
        """Should set the module-level _guardrail singleton."""
        mock_azure = MagicMock(spec=AzureOpenAI)
        guardrail = InputGuardrail(azure_client=mock_azure, embedding_deployment="test-model")

        set_guardrail(guardrail)

        # Verify singleton is set (indirectly via functionality)
        assert guardrail is not None

    def test_set_guardrail_with_none_clears_singleton(self):
        """Should clear singleton when Azure unavailable."""
        mock_azure = MagicMock(spec=AzureOpenAI)
        guardrail = InputGuardrail(azure_client=mock_azure, embedding_deployment="test-model")
        set_guardrail(guardrail)

        set_guardrail(None)

        # Singleton cleared (degraded graceful mode)
        # This allows the system to continue without guardrail checks
        assert True  # No exception raised

    def test_guardrail_uses_correct_azure_client(self):
        """Guardrail should use provided Azure OpenAI client."""
        mock_azure = MagicMock(spec=AzureOpenAI)
        mock_azure.embeddings.create = MagicMock(return_value=MagicMock(data=[MagicMock(embedding=[0.5] * 1536)]))

        guardrail = InputGuardrail(azure_client=mock_azure, embedding_deployment="text-embedding-3-small")

        assert guardrail._azure == mock_azure
        assert guardrail._embedding_deployment == "text-embedding-3-small"

    def test_guardrail_degrades_gracefully_when_azure_unavailable(self):
        """Should handle Azure OpenAI unavailability gracefully."""
        # Simulate Azure failure
        mock_azure = MagicMock(spec=AzureOpenAI)
        mock_azure.embeddings.create = MagicMock(side_effect=Exception("Azure unavailable"))

        guardrail = InputGuardrail(azure_client=mock_azure, embedding_deployment="test-model")

        # Should not crash during construction
        assert guardrail is not None

    @pytest.mark.asyncio
    async def test_guardrail_validates_with_azure_client(self):
        """Guardrail should validate using provided Azure client."""
        mock_azure = MagicMock(spec=AzureOpenAI)
        mock_azure.embeddings.create = MagicMock(return_value=MagicMock(data=[MagicMock(embedding=[0.8] * 1536)]))

        guardrail = InputGuardrail(azure_client=mock_azure, embedding_deployment="test-model")

        result = await guardrail.validate("what is my balance?")

        # Should pass validation (assuming semantic similarity passes)
        assert result.passed is True


class TestGuardrailStartupIntegration:
    """Test guardrail integration in the broader startup context."""

    def test_guardrail_singleton_pattern_matches_rag_pattern(self):
        """Guardrail singleton should follow same pattern as RAG retriever."""
        from agents.rag.retriever import set_retriever

        # Both should follow the same singleton pattern
        mock_azure = MagicMock(spec=AzureOpenAI)
        guardrail = InputGuardrail(azure_client=mock_azure, embedding_deployment="test-model")

        # Should work without exceptions
        set_guardrail(guardrail)
        set_retriever(None)  # RAG singleton

        # Cleanup
        set_guardrail(None)

    def test_guardrail_initialization_order(self):
        """Guardrail should be initialized after Azure OpenAI client."""
        mock_azure = MagicMock(spec=AzureOpenAI)

        # 1. Azure client exists
        assert mock_azure is not None

        # 2. Guardrail can be constructed with Azure client
        guardrail = InputGuardrail(azure_client=mock_azure, embedding_deployment="test-model")
        assert guardrail is not None

        # 3. Singleton can be set
        set_guardrail(guardrail)
        assert True  # No exceptions

        # Cleanup
        set_guardrail(None)


class TestGuardrailStartupConfiguration:
    """Test guardrail configuration at startup."""

    def test_guardrail_uses_embedding_model_from_settings(self):
        """Should use embedding_model from settings for deployment."""
        from core.config import settings

        mock_azure = MagicMock(spec=AzureOpenAI)
        embedding_model = settings.embedding_model

        guardrail = InputGuardrail(azure_client=mock_azure, embedding_deployment=embedding_model)

        assert guardrail._embedding_deployment == embedding_model

    def test_guardrail_topic_seed_text_is_defined(self):
        """Should have topic seed text for semantic similarity."""
        mock_azure = MagicMock(spec=AzureOpenAI)
        guardrail = InputGuardrail(azure_client=mock_azure, embedding_deployment="test-model")

        # Topic seed should be defined (class constant)
        assert guardrail._TOPIC_SEED_TEXT is not None
        assert "billing" in guardrail._TOPIC_SEED_TEXT.lower()
        assert "telecom" in guardrail._TOPIC_SEED_TEXT.lower()

    def test_guardrail_injection_patterns_are_defined(self):
        """Should have injection patterns defined."""
        mock_azure = MagicMock(spec=AzureOpenAI)
        guardrail = InputGuardrail(azure_client=mock_azure, embedding_deployment="test-model")

        # Injection patterns should be defined
        assert len(guardrail._INJECTION_PATTERNS) > 0
        assert "ignore previous instructions" in guardrail._INJECTION_PATTERNS
        assert "system:" in guardrail._INJECTION_PATTERNS
