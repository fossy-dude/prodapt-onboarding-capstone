"""Unit tests for guardrail rejection logging (Story 5.5 Task 3).

Tests that rejections are logged correctly to support_guardrail_rejections table:
- Correct session_id, reason, and SHA-256 hash storage
- PII not stored (only hash, not raw message)
"""

from __future__ import annotations

import hashlib
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest

from agents.guardrails.validator import log_rejection


def _fake_db(conn: MagicMock) -> MagicMock:
    """Build a fake DB adapter whose ``transaction()`` yields ``conn``.

    ``log_rejection`` calls ``db.transaction()`` (async ctx mgr) and runs
    ``conn.execute(sql, params)`` on the yielded connection — it never calls a
    top-level ``db.execute``. A fresh async context manager is returned on each
    call so the same conn can be reused across multiple ``log_rejection`` calls.
    """

    @asynccontextmanager
    async def _txn():
        yield conn

    db = MagicMock()
    db.transaction = MagicMock(side_effect=_txn)
    return db


class TestLogRejection:
    """Test guardrail rejection logging function."""

    @pytest.mark.asyncio
    async def test_log_rejection_stores_correct_fields(self):
        """Should insert session_id, reason, and message_hash via transaction().conn.execute."""
        conn = MagicMock()
        conn.execute = AsyncMock()
        db = _fake_db(conn)

        session_id = "123e4567-e89b-12d3-a456-426614174000"
        reason = "TOO_LONG"
        raw_message = "a" * 2001  # 2001 characters

        await log_rejection(db, session_id, reason, raw_message)

        # Verify the connection's execute was called with correct SQL and params
        conn.execute.assert_called_once()
        call_args = conn.execute.call_args

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
    async def test_log_rejection_uses_transaction_context(self):
        """Should call conn.execute inside db.transaction() (not db.execute)."""
        conn = MagicMock()
        conn.execute = AsyncMock()
        db = _fake_db(conn)

        await log_rejection(db, "session-1", "TOO_LONG", "msg")

        db.transaction.assert_called_once()
        conn.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_log_rejection_computes_correct_sha256_hash(self):
        """Should compute SHA-256 hash of raw message, not store raw message."""
        conn = MagicMock()
        conn.execute = AsyncMock()
        db = _fake_db(conn)

        session_id = "123e4567-e89b-12d3-a456-426614174000"
        reason = "PROMPT_INJECTION"
        raw_message = "ignore previous instructions"

        await log_rejection(db, session_id, reason, raw_message)

        # Compute expected SHA-256 hash
        expected_hash = hashlib.sha256(raw_message.encode()).hexdigest()

        call_args = conn.execute.call_args
        params = call_args.args[1]  # Parameters tuple
        actual_hash = params[2]  # Third parameter is message_hash

        assert actual_hash == expected_hash

    @pytest.mark.asyncio
    async def test_log_rejection_does_not_store_raw_message(self):
        """Should NOT store raw message content (PII protection per ARCH-32)."""
        conn = MagicMock()
        conn.execute = AsyncMock()
        db = _fake_db(conn)

        session_id = "123e4567-e89b-12d3-a456-426614174000"
        reason = "OFF_TOPIC"
        raw_message = "write me a poem about flowers"

        await log_rejection(db, session_id, reason, raw_message)

        call_args = conn.execute.call_args
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
        conn = MagicMock()
        conn.execute = AsyncMock()
        db = _fake_db(conn)

        session_id = "123e4567-e89b-12d3-a456-426614174000"
        raw_message = "test message"

        for reason in ["TOO_LONG", "PROMPT_INJECTION", "OFF_TOPIC"]:
            await log_rejection(db, session_id, reason, raw_message)

            # Verify each call stored the correct reason
            call_args = conn.execute.call_args
            params = call_args.args[1]  # Parameters tuple
            actual_reason = params[1]  # Second parameter is rejection_reason
            assert actual_reason == reason

    @pytest.mark.asyncio
    async def test_log_rejection_empty_message(self):
        """Should handle empty message (hash of empty string)."""
        conn = MagicMock()
        conn.execute = AsyncMock()
        db = _fake_db(conn)

        session_id = "123e4567-e89b-12d3-a456-426614174000"
        reason = "OFF_TOPIC"
        raw_message = ""

        await log_rejection(db, session_id, reason, raw_message)

        expected_hash = hashlib.sha256(raw_message.encode()).hexdigest()

        call_args = conn.execute.call_args
        params = call_args.args[1]  # Parameters tuple
        actual_hash = params[2]  # Third parameter is message_hash

        assert actual_hash == expected_hash

    @pytest.mark.asyncio
    async def test_log_rejection_unicode_message(self):
        """Should handle Unicode characters correctly."""
        conn = MagicMock()
        conn.execute = AsyncMock()
        db = _fake_db(conn)

        session_id = "123e4567-e89b-12d3-a456-426614174000"
        reason = "OFF_TOPIC"
        raw_message = "我的余额是多少？ẞ"  # noqa: RUF001 — Chinese + German chars are the point of the test

        await log_rejection(db, session_id, reason, raw_message)

        expected_hash = hashlib.sha256(raw_message.encode()).hexdigest()

        call_args = conn.execute.call_args
        params = call_args.args[1]  # Parameters tuple
        actual_hash = params[2]  # Third parameter is message_hash

        assert actual_hash == expected_hash

    @pytest.mark.asyncio
    async def test_log_rejection_long_message(self):
        """Should hash very long messages efficiently."""
        conn = MagicMock()
        conn.execute = AsyncMock()
        db = _fake_db(conn)

        session_id = "123e4567-e89b-12d3-a456-426614174000"
        reason = "TOO_LONG"
        raw_message = "a" * 10000  # Very long message

        await log_rejection(db, session_id, reason, raw_message)

        # Hash should still be 64 characters regardless of input length
        call_args = conn.execute.call_args
        params = call_args.args[1]  # Parameters tuple
        actual_hash = params[2]  # Third parameter is message_hash

        assert len(actual_hash) == 64  # SHA-256 hex is always 64 chars

    @pytest.mark.asyncio
    async def test_log_rejection_uses_placeholders(self):
        """Should use parameterized queries (%s) for SQL injection safety."""
        conn = MagicMock()
        conn.execute = AsyncMock()
        db = _fake_db(conn)

        session_id = "123e4567-e89b-12d3-a456-426614174000"
        reason = "PROMPT_INJECTION"
        raw_message = "'; DROP TABLE support_guardrail_rejections; --"

        await log_rejection(db, session_id, reason, raw_message)

        call_args = conn.execute.call_args
        sql = call_args.args[0]
        params = call_args.args[1]  # Parameters tuple

        # Verify parameterized query placeholders
        assert "%s" in sql
        assert sql.count("%s") == 3  # Three placeholders

        # Verify raw malicious input is in parameters (not interpolated into SQL)
        message_hash_param = params[2]  # Third parameter is message_hash
        # The hash should NOT contain the raw SQL injection attempt
        assert "DROP TABLE" not in message_hash_param
