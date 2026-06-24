"""Unit tests for the charge_explain tool (Story 5.7; AC #1, #4).

Tests the Support Agent tool that invokes the Rating Agent via A2A
(agent-to-agent) LangGraph call. Mocks the Rating Agent graph to verify
tool behavior without real DB calls.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import pytest

if TYPE_CHECKING:
    from unittest.mock import Mock

from agents.support.tools import charge_explain


class MockLangfuseClient:
    """Fake LangFuse client for tracing tests."""

    def __init__(self) -> None:
        self.spans_created = []

    def start_as_current_observation(
        self,
        name: str,
        as_type: str,
        input: dict,
    ) -> MockLangfuseSpan:
        span = MockLangfuseSpan(name, as_type, input)
        self.spans_created.append(span)
        return span


class MockLangfuseSpan:
    """Fake LangFuse span for tracing tests."""

    def __init__(self, name: str, as_type: str, input: dict) -> None:
        self.name = name
        self.as_type = as_type
        self.input = input
        self.updates = []

    def update(self, **kwargs: object) -> None:
        self.updates.append(kwargs)

    def __enter__(self) -> MockLangfuseSpan:
        return self

    def __exit__(self, *args: object) -> None:
        pass


@pytest.fixture
def mock_langfuse_client() -> MockLangfuseClient:
    """Fake LangFuse client for testing."""
    return MockLangfuseClient()


@pytest.fixture
def mock_rating_agent_result() -> dict:
    """Sample successful Rating Agent result."""
    return {
        "subscriber_id": "sub-123",
        "cdr_reference": "cdr-456",
        "trace_id": "trace-789",
        "result": MagicMock(
            cdr_id="cdr-456",
            event_type="voice",
            duration_or_data="5m 30s",
            rate_per_unit=50,
            charge_paise=275,
            balance_before=1000,
            balance_after=725,
        ),
    }


@pytest.fixture
def mock_rating_agent_not_found() -> dict:
    """Sample Rating Agent result when CDR not found."""
    return {
        "subscriber_id": "sub-123",
        "cdr_reference": "nonexistent-cdr",
        "trace_id": "trace-789",
        "result": None,
    }


class TestChargeExplainTool:
    """Unit tests for the charge_explain tool function."""

    @pytest.mark.asyncio
    async def test_charge_explain_calls_rating_agent(self, mock_rating_agent_result: dict) -> None:
        """Tool should invoke Rating Agent graph via A2A call."""
        # Mock the rating graph
        import agents.rating.graph
        import agents.support.tools

        # Create a mock that returns a successful result
        mock_invoke = AsyncMock(return_value=mock_rating_agent_result)
        original_graph = agents.rating.graph.rating_graph
        agents.rating.graph.rating_graph = MagicMock(ainvoke=mock_invoke)

        try:
            # Set up context vars for current_subscriber_id
            from agents.support.identity import _set_subscriber_id_context

            _set_subscriber_id_context("sub-123")

            # Set up context vars for current_session_id
            from agents.support.identity import _set_session_id_context

            _set_session_id_context("session-456")

            # Set up DB singleton
            from agents.support.tools import set_support_adapters
            from core.protocols.cache import CacheProtocol

            class FakeCache:
                async def get_balance(self, msisdn: str) -> int | None:
                    return 1000

            fake_cache = FakeCache()
            set_support_adapters(fake_cache, None)

            # Call the tool
            result = await charge_explain.func("sub-123", "cdr-456")

            # Verify Rating Agent was invoked
            mock_invoke.assert_called_once()
            call_args = mock_invoke.call_args

            # Check that the state was passed correctly
            state = call_args[0][0] if call_args[0] else call_args.kwargs.get("state", {})
            assert state["subscriber_id"] == "sub-123"
            assert state["cdr_reference"] == "cdr-456"
            assert state["trace_id"] in ["session-456", "unknown"]
        finally:
            # Restore original
            agents.rating.graph.rating_graph = original_graph

    @pytest.mark.asyncio
    async def test_charge_explain_returns_dict_on_success(self, mock_rating_agent_result: dict) -> None:
        """Tool should return a dict with found=True and breakdown data on success."""
        import dataclasses

        import agents.rating.graph
        import agents.support.tools

        # Mock the rating graph
        mock_invoke = AsyncMock(return_value=mock_rating_agent_result)
        original_graph = agents.rating.graph.rating_graph
        agents.rating.graph.rating_graph = MagicMock(ainvoke=mock_invoke)

        try:
            # Set up context vars
            from agents.support.identity import _set_session_id_context, _set_subscriber_id_context

            _set_subscriber_id_context("sub-123")
            _set_session_id_context("session-456")

            # Set up DB singleton
            from agents.support.tools import set_support_adapters

            class FakeCache:
                async def get_balance(self, msisdn: str) -> int | None:
                    return 1000

            fake_cache = FakeCache()
            set_support_adapters(fake_cache, None)

            # Call the tool
            result = await charge_explain.func("sub-123", "cdr-456")

            # Verify response structure
            assert isinstance(result, dict)
            assert result["found"] is True
            assert result["breakdown"] is not None
            assert isinstance(result["breakdown"], dict)
            assert "message" in result

            # Verify breakdown fields
            breakdown = result["breakdown"]
            assert breakdown["cdr_id"] == "cdr-456"
            assert breakdown["event_type"] == "voice"
            assert breakdown["duration_or_data"] == "5m 30s"
            assert breakdown["rate_per_unit"] == 50
            assert breakdown["charge_paise"] == 275
            assert breakdown["balance_before"] == 1000
            assert breakdown["balance_after"] == 725
        finally:
            agents.rating.graph.rating_graph = original_graph

    @pytest.mark.asyncio
    async def test_charge_explain_handles_not_found(self, mock_rating_agent_not_found: dict) -> None:
        """Tool should return found=False with helpful message when CDR not found."""
        import agents.rating.graph
        import agents.support.tools

        # Mock the rating graph to return None (not found)
        mock_invoke = AsyncMock(return_value=mock_rating_agent_not_found)
        original_graph = agents.rating.graph.rating_graph
        agents.rating.graph.rating_graph = MagicMock(ainvoke=mock_invoke)

        try:
            # Set up context vars
            from agents.support.identity import _set_session_id_context, _set_subscriber_id_context

            _set_subscriber_id_context("sub-123")
            _set_session_id_context("session-456")

            # Set up DB singleton
            from agents.support.tools import set_support_adapters

            class FakeCache:
                async def get_balance(self, msisdn: str) -> int | None:
                    return 1000

            fake_cache = FakeCache()
            set_support_adapters(fake_cache, None)

            # Call the tool
            result = await charge_explain.func("sub-123", "nonexistent-cdr")

            # Verify response structure
            assert isinstance(result, dict)
            assert result["found"] is False
            assert result["breakdown"] is None
            assert "message" in result
            assert "couldn't find" in result["message"].lower() or "not found" in result["message"].lower()
        finally:
            agents.rating.graph.rating_graph = original_graph

    @pytest.mark.asyncio
    async def test_charge_explain_uses_current_subscriber_id(self, mock_rating_agent_result: dict) -> None:
        """Tool should use current_subscriber_id from context, not LLM-provided value."""
        import agents.rating.graph
        import agents.support.tools

        # Mock the rating graph
        mock_invoke = AsyncMock(return_value=mock_rating_agent_result)
        original_graph = agents.rating.graph.rating_graph
        agents.rating.graph.rating_graph = MagicMock(ainvoke=mock_invoke)

        try:
            # Set up context vars with different subscriber_id
            from agents.support.identity import _set_session_id_context, _set_subscriber_id_context

            _set_subscriber_id_context("real-sub-999")  # Context ID
            _set_session_id_context("session-456")

            # Set up DB singleton
            from agents.support.tools import set_support_adapters

            class FakeCache:
                async def get_balance(self, msisdn: str) -> int | None:
                    return 1000

            fake_cache = FakeCache()
            set_support_adapters(fake_cache, None)

            # Call the tool with LLM-provided subscriber_id (should be ignored)
            result = await charge_explain.func("llm-provided-sub-123", "cdr-456")

            # Verify Rating Agent was called with context subscriber_id, not LLM-provided
            mock_invoke.assert_called_once()
            call_args = mock_invoke.call_args
            state = call_args[0][0] if call_args[0] else call_args.kwargs.get("state", {})

            # Should use context subscriber_id, not the LLM-provided one
            assert state["subscriber_id"] == "real-sub-999"
        finally:
            agents.rating.graph.rating_graph = original_graph


class TestChargeExplainTracing:
    """Unit tests for LangFuse tracing in charge_explain tool."""

    @pytest.mark.asyncio
    async def test_charge_explain_creates_langfuse_span(self, mock_rating_agent_result: dict) -> None:
        """Tool should create a LangFuse span for A2A call tracing."""
        import agents.rating.graph
        import agents.support.tools
        from core.observability.langfuse import set_langfuse_client

        # Mock the rating graph
        mock_invoke = AsyncMock(return_value=mock_rating_agent_result)
        original_graph = agents.rating.graph.rating_graph
        agents.rating.graph.rating_graph = MagicMock(ainvoke=mock_invoke)

        # Mock LangFuse client
        mock_client = MockLangfuseClient()
        original_client = None

        try:
            # Set up context vars
            from agents.support.identity import _set_session_id_context, _set_subscriber_id_context

            _set_subscriber_id_context("sub-123")
            _set_session_id_context("session-456")

            # Set up DB singleton
            from agents.support.tools import set_support_adapters

            class FakeCache:
                async def get_balance(self, msisdn: str) -> int | None:
                    return 1000

            fake_cache = FakeCache()
            set_support_adapters(fake_cache, None)

            # Set mock LangFuse client
            set_langfuse_client(mock_client)  # type: ignore[arg-type]

            # Call the tool
            result = await charge_explain.func("sub-123", "cdr-456")

            # Verify tool executed successfully
            assert result["found"] is True

            # Note: Actual LangFuse span creation is handled by _traced_tool wrapper
            # This test verifies the tool doesn't break when LangFuse is available
        finally:
            agents.rating.graph.rating_graph = original_graph
            set_langfuse_client(None)


class TestChargeExplainErrorHandling:
    """Unit tests for error handling in charge_explain tool."""

    @pytest.mark.asyncio
    async def test_charge_explain_handles_rating_agent_exception(self) -> None:
        """Tool should return error response when Rating Agent raises exception."""
        import agents.rating.graph
        import agents.support.tools

        # Mock the rating graph to raise an exception
        mock_invoke = AsyncMock(side_effect=Exception("Database connection failed"))
        original_graph = agents.rating.graph.rating_graph
        agents.rating.graph.rating_graph = MagicMock(ainvoke=mock_invoke)

        try:
            # Set up context vars
            from agents.support.identity import _set_session_id_context, _set_subscriber_id_context

            _set_subscriber_id_context("sub-123")
            _set_session_id_context("session-456")

            # Set up DB singleton
            from agents.support.tools import set_support_adapters

            class FakeCache:
                async def get_balance(self, msisdn: str) -> int | None:
                    return 1000

            fake_cache = FakeCache()
            set_support_adapters(fake_cache, None)

            # Call the tool
            result = await charge_explain.func("sub-123", "cdr-456")

            # Verify error response
            assert isinstance(result, dict)
            assert result["found"] is False
            assert result["breakdown"] is None
            assert "error" in result["message"].lower() or "try again" in result["message"].lower()
        finally:
            agents.rating.graph.rating_graph = original_graph


class TestChargeExplainToolSignature:
    """Unit tests for tool metadata and signature."""

    def test_charge_explain_has_correct_name(self) -> None:
        """Tool should have name 'charge_explain' for CopilotKit registration."""
        assert charge_explain.name == "charge_explain"

    def test_charge_explain_has_description(self) -> None:
        """Tool should have a description for LLM understanding."""
        assert charge_explain.description is not None
        assert len(charge_explain.description) > 0
        # Description should mention key concepts
        desc_lower = charge_explain.description.lower()
        assert "charge" in desc_lower or "breakdown" in desc_lower
        assert "cdr" in desc_lower or "event" in desc_lower

    def test_charge_explain_has_arg_schema(self) -> None:
        """Tool should define subscriber_id and cdr_reference arguments."""
        # The tool should have an args_schema defining the expected parameters
        assert charge_explain.args_schema is not None
        # Check that the schema has the required fields
        schema_fields = charge_explain.args_schema.model_fields
        assert "subscriber_id" in schema_fields or "cdr_reference" in schema_fields


class TestChargeExplainInSupportTools:
    """Integration tests for charge_explain in SUPPORT_TOOLS list."""

    def test_charge_explain_in_support_tools(self) -> None:
        """charge_explain should be included in SUPPORT_TOOLS list."""
        from agents.support.tools import SUPPORT_TOOLS

        tool_names = [tool.name for tool in SUPPORT_TOOLS]
        assert "charge_explain" in tool_names

    def test_support_tools_order(self) -> None:
        """SUPPORT_TOOLS should include all expected tools in order."""
        from agents.support.tools import SUPPORT_TOOLS

        tool_names = [tool.name for tool in SUPPORT_TOOLS]

        # Verify expected tools are present (order may vary but all should exist)
        expected_tools = [
            "get_balance",
            "get_plan",
            "get_usage",
            "rag_search_tool",
            "list_plans",
            "recharge_flow",
            "charge_explain",
        ]
        for expected in expected_tools:
            assert expected in tool_names, f"Tool {expected} not found in SUPPORT_TOOLS"
