"""Input guardrail validator for Support Agent (Story 5.5).

Validates incoming chatbot messages against three rejection criteria:
1. Length check: messages exceeding 2,000 characters → TOO_LONG
2. Injection check: prompt injection patterns → PROMPT_INJECTION
3. Semantic check: low cosine similarity vs. telecom/billing topics → OFF_TOPIC

Rejections are logged to the ``support_guardrail_rejections`` table with a SHA-256
hash (never raw message text per ARCH-32 PII requirements).
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from openai import AzureOpenAI

logger = logging.getLogger(__name__)

__all__ = [
    "GuardrailResult",
    "InputGuardrail",
    "log_rejection",
]


@dataclass
class GuardrailResult:
    """Result of input validation.

    Attributes
    ----------
        passed: Whether the message passed all guardrail checks
        rejection_reason: One of 'TOO_LONG', 'PROMPT_INJECTION', 'OFF_TOPIC' (if passed=False)
        response_message: User-facing rejection message (if passed=False)
    """

    passed: bool
    rejection_reason: str | None = None
    response_message: str | None = None


class InputGuardrail:
    """Validates chatbot messages before they reach the LLM.

    Performs three validation checks in order:
    1. Length: reject messages > 2,000 characters
    2. Injection: reject messages containing prompt injection patterns
    3. Semantic: reject messages with low similarity to telecom/billing topics

    The semantic check computes cosine similarity between the message embedding
    and a topic seed embedding for telecom/billing domains. Messages with
    similarity < 0.2 are rejected as off-topic.
    """

    # Topic seed text for semantic similarity (Story 5.5 AC #3)
    _TOPIC_SEED_TEXT = "billing balance plan recharge usage data voice SMS account telecom MVNO subscriber"

    # Injection patterns to detect (Story 5.5 AC #2)
    _INJECTION_PATTERNS = [
        "ignore previous instructions",
        "ignore above",
        "system:",
        "assistant:",
        "disregard",
        "forget your instructions",
        "new instructions:",
        "override",
    ]

    # Rejection thresholds (from Story 5.5)
    _MAX_LENGTH = 2000
    _SIMILARITY_THRESHOLD = 0.2

    # Response messages (from Story 5.5 AC)
    _TOO_LONG_MESSAGE = "Your message is too long. Please keep it under 2,000 characters."
    _PROMPT_INJECTION_MESSAGE = "I can only help with billing and account queries."
    _OFF_TOPIC_MESSAGE = "I'm a billing assistant and can only help with account and plan queries."

    def __init__(self, azure_client: AzureOpenAI, embedding_deployment: str) -> None:
        """Initialize the guardrail with Azure OpenAI client.

        Args:
            azure_client: Azure OpenAI client for embeddings
            embedding_deployment: Name of the embedding model deployment
        """
        self._azure = azure_client
        self._embedding_deployment = embedding_deployment
        self._topic_seed_embedding: list[float] | None = None

    async def _get_topic_seed_embedding(self) -> list[float]:
        """Lazy-compute topic seed embedding on first access.

        Computes embedding of the telecom/billing topic seed text via Azure OpenAI
        and caches it as a class attribute for reuse across all requests.
        """
        if self._topic_seed_embedding is None:
            try:
                response = await asyncio.to_thread(
                    self._azure.embeddings.create,
                    model=self._embedding_deployment,
                    input=self._TOPIC_SEED_TEXT,
                )
                if not response.data:
                    raise RuntimeError("Azure OpenAI returned no embedding for topic seed")
                self._topic_seed_embedding = list(response.data[0].embedding)
                logger.debug("Computed topic seed embedding (cached for future requests)")
            except Exception as exc:
                logger.warning(
                    "Failed to compute topic seed embedding: %s. Defaulting to pass all semantic checks.", exc
                )
                self._topic_seed_embedding = None
        return self._topic_seed_embedding if self._topic_seed_embedding is not None else []

    async def validate(self, message: str) -> GuardrailResult:
        """Validate a message against all guardrail checks.

        Checks are performed in order (length → injection → semantic) and the
        first failing check returns immediately with its rejection reason.

        Args:
            message: The user's message to validate

        Returns
        -------
            GuardrailResult indicating pass/fail and reason if rejected
        """
        # Check 1: Length validation (short-circuits if too long)
        if len(message) > self._MAX_LENGTH:
            return GuardrailResult(
                passed=False,
                rejection_reason="TOO_LONG",
                response_message=self._TOO_LONG_MESSAGE,
            )

        # Check 2: Prompt injection detection (case-insensitive)
        message_lower = message.lower()
        for pattern in self._INJECTION_PATTERNS:
            if pattern.lower() in message_lower:
                return GuardrailResult(
                    passed=False,
                    rejection_reason="PROMPT_INJECTION",
                    response_message=self._PROMPT_INJECTION_MESSAGE,
                )

        # Check 3: Semantic similarity check
        # If Azure is unavailable, degrade gracefully (pass all semantic checks)
        topic_embedding = await self._get_topic_seed_embedding()
        if not topic_embedding:
            logger.debug("Azure unavailable - skipping semantic check (degraded graceful per NFR)")
            return GuardrailResult(passed=True, rejection_reason=None, response_message=None)

        try:
            # Embed the user message
            response = await asyncio.to_thread(
                self._azure.embeddings.create,
                model=self._embedding_deployment,
                input=message,
            )
            if not response.data:
                raise RuntimeError("Azure OpenAI returned no embedding for message")
            message_embedding = list(response.data[0].embedding)

            # Compute cosine similarity
            similarity = self._cosine_similarity(message_embedding, topic_embedding)

            # Reject if below threshold
            if similarity < self._SIMILARITY_THRESHOLD:
                return GuardrailResult(
                    passed=False,
                    rejection_reason="OFF_TOPIC",
                    response_message=self._OFF_TOPIC_MESSAGE,
                )

            return GuardrailResult(passed=True, rejection_reason=None, response_message=None)
        except Exception as exc:
            logger.warning("Semantic check failed: %s. Passing message (degraded graceful per NFR).", exc)
            return GuardrailResult(passed=True, rejection_reason=None, response_message=None)

    def _cosine_similarity(self, a: list[float], b: list[float]) -> float:
        """Compute cosine similarity between two vectors using pure Python.

        Args:
            a: First vector (list of floats)
            b: Second vector (list of floats)

        Returns
        -------
            Cosine similarity in range [-1, 1], or 0.0 if either vector is zero

        Note:
            Pure Python implementation (no numpy) to avoid heavy dependency in
            the hot path. Sufficient for 1536-dim vectors in chat latency context.
        """
        if not a or not b:
            return 0.0

        # Compute dot product
        dot_product = sum(x * y for x, y in zip(a, b))

        # Compute magnitudes
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(y * y for y in b))

        # Avoid division by zero
        if norm_a == 0.0 or norm_b == 0.0:
            return 0.0

        return dot_product / (norm_a * norm_b)


async def log_rejection(
    db,
    session_id: str,
    reason: str,
    raw_message: str,
) -> None:
    """Log a guardrail rejection to the audit table.

    Computes SHA-256 hash of the raw message (NEVER stores the raw message text
    per ARCH-32 PII requirements) and inserts into ``support_guardrail_rejections``.

    Args:
        db: Database connection with execute method
        session_id: UUID string of the chat session
        reason: Rejection reason ('TOO_LONG', 'PROMPT_INJECTION', 'OFF_TOPIC')
        raw_message: The raw user message (for hashing only, not storage)
    """
    message_hash = hashlib.sha256(raw_message.encode()).hexdigest()

    await db.execute(
        "INSERT INTO support_guardrail_rejections (session_id, rejection_reason, message_hash) VALUES (%s, %s, %s)",
        (session_id, reason, message_hash),
    )

    logger.debug("Logged guardrail rejection: session_id=%s reason=%s hash=%s", session_id, reason, message_hash)
