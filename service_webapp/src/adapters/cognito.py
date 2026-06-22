"""Cognito identity-provider port + MiniStack/LocalStack and in-memory impls.

The subscriber registration flow (Story 1.6) provisions a **passwordless** Cognito
user (username = Registration ID, no password) and triggers a verification OTP to
the alternate mobile number (AC #7, PRD A-6). Full OTP *delivery* is simulated and
captured for the Notification Portal (the story's MVP stance); the user
provisioning itself is real and routed at the provisioned MiniStack endpoint.

* :class:`CognitoProvider` — the port business logic depends on (injectable).
* :class:`MinistackCognitoProvider` — real ``boto3`` client against
  ``settings.cognito_endpoint_url`` (MiniStack/LocalStack at ``localhost:4566``).
  Self-provisions the user pool + client (create-if-not-exists) so the app "just
  routes to its URL". ``boto3`` is imported lazily so boot, the lint/test toolchain
  and the unit tests (which inject :class:`FakeCognitoProvider`) never require it.
* :class:`FakeCognitoProvider` — deterministic in-memory impl for fast unit tests.
"""

from __future__ import annotations

import asyncio
import logging
import secrets
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from core.errors import CognitoProvisioningError, OtpVerificationError

if TYPE_CHECKING:
    from core.config import Settings

logger = logging.getLogger(__name__)

_OTP_LENGTH = 6


@runtime_checkable
class CognitoProvider(Protocol):
    """Port for provisioning, verifying, and authenticating passwordless subscriber users."""

    async def provision_user(self, username: str, phone_number: str | None) -> str:
        """Create a passwordless user (username = Registration ID); return the username."""
        ...

    async def start_verification(self, phone_number: str | None) -> str:
        """Trigger the Step-3 verification OTP; return the captured code (MVP)."""
        ...

    async def initiate_login(self, identifier: str) -> str:
        """Initiate Cognito Custom Auth Flow (CUSTOM_AUTH); return the session string.

        ``identifier`` is the Registration ID (pre-activation) or MSISDN (post-activation).
        The flow issues an OTP challenge surfaced by the Notification Portal.
        """
        ...

    async def verify_login_otp(self, identifier: str, session: str, otp: str) -> dict:
        """Respond to the CUSTOM_CHALLENGE with ``otp``; return the JWT token dict.

        On success returns ``{access_token, refresh_token, id_token, token_type}``.
        Raises :class:`~core.errors.OtpVerificationError` on wrong/expired OTP.
        """
        ...


class FakeCognitoProvider:
    """Deterministic in-memory Cognito stand-in for fast unit tests.

    Records every provisioned user and returns a fixed OTP so tests can assert the
    Step-3 flow without any AWS dependency. Provisioning failures can be simulated
    by setting :attr:`fail`.
    """

    OTP = "123456"
    SESSION = "fake-session-abc123"
    TOKENS: dict[str, str] = {
        "access_token": "fake.access.token",
        "refresh_token": "fake-refresh-token",
        "id_token": "fake.id.token",
        "token_type": "Bearer",
    }

    def __init__(self) -> None:
        self.provisioned: dict[str, str | None] = {}  # username -> phone_number
        self.verifications: list[str | None] = []  # phone numbers an OTP was sent to
        self.login_initiations: list[str] = []  # identifiers that initiated login
        self.fail = False

    async def provision_user(self, username: str, phone_number: str | None) -> str:
        """Record a provisioned user (deterministic, in-memory)."""
        if self.fail:
            raise CognitoProvisioningError("fake provisioning disabled")
        self.provisioned[username] = phone_number
        return username

    async def start_verification(self, phone_number: str | None) -> str:
        """Return the fixed OTP and record the dispatch target."""
        self.verifications.append(phone_number)
        return self.OTP

    async def initiate_login(self, identifier: str) -> str:
        """Return a fixed session string and record the identifier."""
        if self.fail:
            raise CognitoProvisioningError("fake login initiation disabled")
        self.login_initiations.append(identifier)
        return self.SESSION

    async def verify_login_otp(self, identifier: str, session: str, otp: str) -> dict:
        """Validate the OTP (must equal :attr:`OTP`); return fake tokens on success."""
        if otp != self.OTP:
            raise OtpVerificationError(f"Invalid OTP for {_safe_phone(identifier)}")
        return dict(self.TOKENS)


class MinistackCognitoProvider:
    """Real Cognito client against the provisioned MiniStack/LocalStack endpoint.

    ``boto3`` is imported lazily (first use) so importing this module — which the
    default app wiring does — never requires ``boto3``. The user pool + client are
    created idempotently on first use and cached for the process lifetime.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client: Any = None  # boto3 cognito-idp client (dynamically typed)
        self._user_pool_id: str | None = None
        self._client_id: str | None = None
        self._pool_lock = asyncio.Lock()

    def _boto_client(self) -> Any:
        if self._client is None:
            import boto3  # noqa: PLC0415 — lazy: keeps boot + unit tests boto3-free

            self._client = boto3.client(
                "cognito-idp",
                region_name=self._settings.cognito_region,
                endpoint_url=self._settings.cognito_endpoint_url,
                aws_access_key_id=self._settings.aws_access_key_id,
                aws_secret_access_key=self._settings.aws_secret_access_key,
            )
        return self._client

    def _ensure_pool_sync(self) -> tuple[str, str]:
        """Create-or-fetch the user pool id + client id (idempotent). Returns (pool_id, client_id)."""
        client = self._boto_client()
        pool_name = self._settings.cognito_user_pool_name

        # User pool — honour a pre-provisioned id (scripts/provision_cognito.py), else
        # find by name, else create.
        pool_id = self._settings.cognito_user_pool_id or self._find_user_pool(client, pool_name)
        if not pool_id:
            created = client.create_user_pool(PoolName=pool_name, AutoVerifiedAttributes=["phone_number"])
            pool_id = created["UserPool"]["Id"]

        # Client — find existing, else create.
        client_id = self._settings.cognito_client_id or self._find_user_pool_client(client, pool_id)
        if not client_id:
            created_client = client.create_user_pool_client(
                ClientName=f"{pool_name}-client",
                UserPoolId=pool_id,
                ExplicitAuthFlows=["CUSTOM_AUTH_FLOW_ONLY"],
            )
            client_id = created_client["UserPoolClient"]["ClientId"]
        return pool_id, client_id

    async def _ensure_pool(self) -> tuple[str, str]:
        if self._user_pool_id is None or self._client_id is None:
            async with self._pool_lock:
                if self._user_pool_id is None or self._client_id is None:
                    self._user_pool_id, self._client_id = await asyncio.to_thread(self._ensure_pool_sync)
        return self._user_pool_id, self._client_id

    async def provision_user(self, username: str, phone_number: str | None) -> str:
        """Admin-create the passwordless user (MessageAction=SUPPRESS — no welcome email)."""
        try:
            pool_id, _ = await self._ensure_pool()
            attributes = [{"Name": "phone_number", "Value": phone_number or ""}]
            await asyncio.to_thread(
                self._provision_user_sync,
                pool_id,
                username,
                attributes,
            )
            return username
        except CognitoProvisioningError:
            raise
        except Exception as exc:  # boto3 ClientError + any MiniStack transport error
            logger.exception("Cognito user provisioning failed for username=%s", username)
            raise CognitoProvisioningError(f"Cognito provisioning failed: {exc}") from exc

    def _provision_user_sync(self, pool_id: str, username: str, attributes: list[dict[str, str]]) -> Any:
        client = self._boto_client()
        try:
            client.admin_create_user(
                UserPoolId=pool_id,
                Username=username,
                UserAttributes=attributes,
                MessageAction="SUPPRESS",
            )
        except Exception as exc:
            # UsernameExistsException is acceptable for idempotent retries — anything else propagates.
            error_code = ""
            try:
                error_code = exc.response["Error"]["Code"]  # type: ignore[attr-defined]
            except (AttributeError, KeyError, TypeError):
                pass
            if error_code == "UsernameExistsException":
                return
            raise

    async def start_verification(self, phone_number: str | None) -> str:
        """Generate + capture the verification OTP (delivery simulated per Story 1.6).

        A real Custom Auth OTP would be delivered by Cognito trigger Lambdas; for MVP
        the code is minted server-side and returned so the Notification Portal / tests
        can surface it. Never logs the raw alternate mobile — only the masked suffix.
        """
        code = "".join(secrets.choice("0123456789") for _ in range(_OTP_LENGTH))
        logger.info("Cognito verification OTP dispatched to alternate mobile %s", _safe_phone(phone_number))
        return code

    async def initiate_login(self, identifier: str) -> str:
        """Initiate Cognito Custom Auth Flow for ``identifier``; return the session string.

        MiniStack (LocalStack) routes the ``CUSTOM_AUTH`` initiate call; the
        DefineAuthChallenge / CreateAuthChallenge Lambdas must be provisioned for the
        challenge to be issued. The session string is returned to the client so it can
        respond with the OTP in the verify step.
        """
        try:
            _, client_id = await self._ensure_pool()
            resp = await asyncio.to_thread(
                self._boto_client().initiate_auth,
                AuthFlow="CUSTOM_AUTH",
                AuthParameters={"USERNAME": identifier},
                ClientId=client_id,
            )
            session: str = resp.get("Session", "")
            logger.info("Cognito Custom Auth initiated for identifier=%s", _safe_phone(identifier))
            return session
        except Exception as exc:
            logger.exception("Cognito login initiation failed for identifier=%s", _safe_phone(identifier))
            raise CognitoProvisioningError(f"Login initiation failed: {exc}") from exc

    async def verify_login_otp(self, identifier: str, session: str, otp: str) -> dict:
        """Respond to the Custom Auth challenge with ``otp``; return JWT tokens on success.

        On success returns ``{access_token, refresh_token, id_token, token_type}``.
        Raises :class:`~core.errors.OtpVerificationError` on wrong/expired OTP.
        """
        try:
            _, client_id = await self._ensure_pool()
            resp = await asyncio.to_thread(
                self._boto_client().respond_to_auth_challenge,
                ClientId=client_id,
                ChallengeName="CUSTOM_CHALLENGE",
                Session=session,
                ChallengeResponses={"USERNAME": identifier, "ANSWER": otp},
            )
        except Exception as exc:
            err_code = ""
            try:
                err_code = exc.response["Error"]["Code"]  # type: ignore[attr-defined]
            except (AttributeError, KeyError, TypeError):
                pass
            if err_code in ("NotAuthorizedException", "CodeMismatchException"):
                raise OtpVerificationError("OTP verification failed.") from exc
            logger.exception("Cognito OTP verify failed for identifier=%s", _safe_phone(identifier))
            raise CognitoProvisioningError(f"OTP verification error: {exc}") from exc

        auth_result = resp.get("AuthenticationResult", {})
        if not auth_result:
            raise OtpVerificationError("OTP challenge not completed — check Cognito Lambda triggers.")
        return {
            "access_token": auth_result.get("AccessToken", ""),
            "refresh_token": auth_result.get("RefreshToken", ""),
            "id_token": auth_result.get("IdToken", ""),
            "token_type": auth_result.get("TokenType", "Bearer"),
        }

    # ── helpers ───────────────────────────────────────────────────────────────
    @staticmethod
    def _find_user_pool(client: Any, pool_name: str) -> str | None:
        resp = client.list_user_pools(MaxResults=60)
        for pool in resp.get("UserPools", []):
            if pool.get("Name") == pool_name:
                return pool["Id"]
        return None

    @staticmethod
    def _find_user_pool_client(client: Any, pool_id: str) -> str | None:
        resp = client.list_user_pool_clients(UserPoolId=pool_id, MaxResults=60)
        clients = resp.get("UserPoolClients", [])
        return clients[0]["ClientId"] if clients else None


def _safe_phone(phone_number: str | None) -> str:
    """Never log a raw alternate mobile — mask to the last 4 digits (§1.11.6)."""
    if not phone_number:
        return "<none>"
    digits = "".join(c for c in phone_number if c.isdigit())
    return f"***{digits[-4:]}" if len(digits) >= 4 else "***"


__all__ = [
    "CognitoProvider",
    "FakeCognitoProvider",
    "MinistackCognitoProvider",
    "_safe_phone",
]
