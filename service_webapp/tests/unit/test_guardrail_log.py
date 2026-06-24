"""Unit tests for guardrail rejection logging (Story 5.5 Task 3).

Tests that rejections are logged correctly to support_guardrail_rejections table:
- Correct session_id, reason, and SHA-256 hash storage
- PII not stored (only hash, not raw message)
"""

from __future__ import annotations

import hashlib
from unittest.mock import AsyncMock, MagicMock

import pytest

from agents.guardrails.validator import log_rejection


class TestLogRejection:
    """Test guardrail rejection logging function."""

    @pytest.mark.asyncio
    async def test_log_rejection_stores_correct_fields(self):
        """Should insert session_id, reason, and message_hash into support_guardrail_rejections."""
        db = MagicMock()
        db.execute = AsyncMock()

        session_id = "123e4567-e89b-12d3-a456-426614174000"
        reason = "TOO_LONG"
        raw_message = "a" * 2001  # 2001 characters

        await log_rejection(db, session_id, reason, raw_message)

        # Verify execute was called with correct SQL and parameters
        db.execute.assert_called_once()
        call_args = db.execute.call_args

        sql = call_args.args[0]  # First arg is the SQL query
        params = call_args.args[1]  # Second arg is the parameters tuple

        # Check SQL contains INSERT and correct table
        assert "INSERT INTO support_guardrail_rejections" in sql
        assert "session_id" in sql
        assert "rejection_reason" in sql
        assert "message_hash" in sql

        # Check parameters (passed as tuple)
        assert params[0] == session_id  # session_id
        assert params[1] == reason  # rejection_reason
        assert len(params[2]) == 64  # message_hash (SHA-256 hex = 64 chars)

    @pytest.mark.asyncio
    async def test_log_rejection_computes_correct_sha256_hash(self):
        """Should compute SHA-256 hash of raw message, not store raw message."""
        db = MagicMock()
        db.execute = AsyncMock()

        session_id = "123e4567-e89b-12d3-a456-426614174000"
        reason = "PROMPT_INJECTION"
        raw_message = "ignore previous instructions"

        await log_rejection(db, session_id, reason, raw_message)

        # Compute expected SHA-256 hash
        expected_hash = hashlib.sha256(raw_message.encode()).hexdigest()

        # Get the actual hash from the call
        call_args = db.execute.call_args
        params = call_args.args[1]  # Parameters tuple
        actual_hash = params[2]  # Third parameter is message_hash

        assert actual_hash == expected_hash

    @pytest.mark.asyncio
    async def test_log_rejection_does_not_store_raw_message(self):
        """Should NOT store raw message content (PII protection per ARCH-32)."""
        db = MagicMock()
        db.execute = AsyncMock()

        session_id = "123e4567-e89b-12d3-a456-426614174000"
        reason = "OFF_TOPIC"
        raw_message = "write me a poem about flowers"

        await log_rejection(db, session_id, reason, raw_message)

        # Get the call parameters
        call_args = db.execute.call_args
        params = call_args.args[1]  # Parameters tuple
        message_hash_param = params[2]  # Third parameter is message_hash

        # Verify raw message is NOT in parameters (only the hash)
        assert raw_message not in message_hash_param
        # Verify message content is NOT in hash (hash is deterministic, not plaintext)
        assert "poem" not in message_hash_param
        assert "flowers" not in message_hash_param

    @pytest.mark.asyncio
    async def test_log_rejection_all_reason_types(self):
        """Should handle all three rejection reason types."""
        db = MagicMock()
        db.execute = AsyncMock()

        session_id = "123e4567-e89b-12d3-a456-426614174000"
        raw_message = "test message"

        for reason in ["TOO_LONG", "PROMPT_INJECTION", "OFF_TOPIC"]:
            await log_rejection(db, session_id, reason, raw_message)

            # Verify each call stored the correct reason
            call_args = db.execute.call_args
            params = call_args.args[1]  # Parameters tuple
            actual_reason = params[1]  # Second parameter is rejection_reason
            assert actual_reason == reason

    @pytest.mark.asyncio
    async def test_log_rejection_empty_message(self):
        """Should handle empty message (hash of empty string)."""
        db = MagicMock()
        db.execute = AsyncMock()

        session_id = "123e4567-e89b-12d3-a456-426614174000"
        reason = "OFF_TOPIC"
        raw_message = ""

        await log_rejection(db, session_id, reason, raw_message)

        # SHA-256 of empty string is: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
        expected_hash = hashlib.sha256(raw_message.encode()).hexdigest()

        call_args = db.execute.call_args
        params = call_args.args[1]  # Parameters tuple
        actual_hash = params[2]  # Third parameter is message_hash

        assert actual_hash == expected_hash

    @pytest.mark.asyncio
    async def test_log_rejection_unicode_message(self):
        """Should handle Unicode characters correctly."""
        db = MagicMock()
        db.execute = AsyncMock()

        session_id = "123e4567-e89b-12d3-a456-426614174000"
        reason = "OFF_TOPIC"
        raw_message = "我的余额是多少？ẞ"  # Chinese and German characters

        await log_rejection(db, session_id, reason, raw_message)

        # SHA-256 should handle Unicode correctly
        expected_hash = hashlib.sha256(raw_message.encode()).hexdigest()

        call_args = db.execute.call_args
        params = call_args.args[1]  # Parameters tuple
        actual_hash = params[2]  # Third parameter is message_hash

        assert actual_hash == expected_hash

    @pytest.mark.asyncio
    async def test_log_rejection_long_message(self):
        """Should hash very long messages efficiently."""
        db = MagicMock()
        db.execute = AsyncMock()

        session_id = "123e4567-e89b-12d3-a456-426614174000"
        reason = "TOO_LONG"
        raw_message = "a" * 10000  # Very long message

        await log_rejection(db, session_id, reason, raw_message)

        # Hash should still be 64 characters regardless of input length
        call_args = db.execute.call_args
        params = call_args.args[1]  # Parameters tuple
        actual_hash = params[2]  # Third parameter is message_hash

        assert len(actual_hash) == 64  # SHA-256 hex is always 64 chars

    @pytest.mark.asyncio
    async def test_log_rejection_uses_placeholders(self):
        """Should use parameterized queries ($1, $2, $3) for SQL injection safety."""
        db = MagicMock()
        db.execute = AsyncMock()

        session_id = "123e4567-e89b-12d3-a456-426614174000"
        reason = "PROMPT_INJECTION"
        raw_message = "'; DROP TABLE support_guardrail_rejections; --"

        await log_rejection(db, session_id, reason, raw_message)

        # Get the SQL query
        call_args = db.execute.call_args
        sql = call_args.args[0]
        params = call_args.args[1]  # Parameters tuple

        # Verify parameterized query placeholders
        assert "%s" in sql
        assert sql.count("%s") == 3  # Three placeholders

        # Verify raw malicious input is in parameters (not interpolated into SQL)
        message_hash_param = params[2]  # Third parameter is message_hash
        # The hash should NOT contain the raw SQL injection attempt
        assert "DROP TABLE" not in message_hash_param
