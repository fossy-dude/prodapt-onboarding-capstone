"""Cache port (architecture §1.12.1 dependency-inversion seam)."""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class CacheProtocol(Protocol):
    """Cache port: connectivity check + generic string key/value ops for OTP (Story 1.8)."""

    async def ping(self) -> bool:
        """Return ``True`` if the cache (Valkey) is reachable, ``False`` otherwise.

        Must never raise — a down dependency yields ``False`` so ``/ready`` can
        report it cleanly instead of erroring.
        """
        ...

    async def set_str(self, key: str, value: str, ex: int) -> None:
        """Set a string key with an expiry in seconds."""
        ...

    async def get_str(self, key: str) -> str | None:
        """Return the string value for ``key``, or ``None`` if absent/expired."""
        ...

    async def delete(self, key: str) -> None:
        """Delete ``key`` (no-op if absent)."""
        ...

    async def set_balance(self, msisdn: str, paise: int) -> None:
        """Seed the persistent no-TTL balance counter ``balance:{msisdn}`` to ``paise``.

        No expiry — the cdr-pipeline consumer ``INCRBY``s this counter and flushes it
        back to ``billing_wallet_balances`` (architecture §1.7.3). Seeding it at SIM
        activation (initial credit = the plan's price in paise) is what makes a
        freshly-activated subscriber billable; the Valkey key and the Postgres wallet
        row must start in sync.
        """
        ...

    async def get_balance(self, msisdn: str) -> int | None:
        """GET ``balance:{msisdn}`` and return as integer paise, or ``None`` if key absent.

        Returns ``None`` on a cold cache (key not yet seeded) — callers fall back to
        ``billing_wallet_balances.balance_paise`` in that case (architecture §1.7.3).
        """
        ...

    async def incr_balance(self, msisdn: str, delta_paise: int) -> int:
        """INCRBY ``balance:{msisdn} +delta_paise`` and return new value (Story 3.5).

        Used for crediting wallet after recharge. The cdr-pipeline consumer uses
        INCRBY with negative delta for deductions (Story 2-3). This mirrors the
        deduction writer's INCRBY contract but for credits (positive delta).

        Returns the new balance after increment.
        """
        ...

    async def incr_with_expire(self, key: str, ttl_seconds: int) -> int:
        """INCR ``key`` then set TTL; return new counter value (Story 4.3 rate limiting).

        Used for sliding-window rate limiting: the caller passes the fully-formed
        rate-limit key (``ratelimit:{msisdn}:{channel}:{minute_bucket}``) and the
        method increments it atomically, then sets the TTL so Valkey auto-evicts
        expired windows.

        Returns the new counter value after increment.
        """
        ...
