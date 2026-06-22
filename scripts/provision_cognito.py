#!/usr/bin/env python3
"""Provision the SBOAI MiniStack Cognito User Pool (idempotent).

This script plays the role CloudFormation/Terraform would in the Target State:
it creates the AWS Cognito resources the app needs, but against the **MiniStack**
(LocalStack-compatible) container exposed at ``http://localhost:4566``. It is wired
into ``just deps`` so the pool exists as soon as the dependency stack is up, and it
is safe to re-run by hand at any time — every step is lookup-first and tolerates
"already exists".

Scope (per architecture §1.8.1, §1.14.3; decisions 2026-06-20)
--------------------------------------------------------------
* **User Pool** ``sboai-subscribers`` — passwordless (no password policy), email +
  ``phone_number`` standard attributes, ``AllowAdminCreateUserOnly`` (registration
  creates users server-side, Story 1.6).
* **6 role groups** — ``subscriber, ops, fraud, dev, admin, marketing``. Roles reach
  the JWT as the ``cognito:groups`` claim (NOT a ``role`` claim / custom attribute);
  Story 1.8's auth layer must read ``cognito:groups``.
* **App Client** ``sboai-webapp`` — ``ALLOW_CUSTOM_AUTH`` + ``ALLOW_REFRESH_TOKEN_AUTH``,
  access/ID token TTL 30 min, refresh 30 days, token revocation enabled (FR-66).
* **Seeded test users** — one per non-subscriber role, written into its group.

Deliberately OUT of scope (land in Story 1.8 / Notification-Portal epic)
-----------------------------------------------------------------------
* The Custom-Auth challenge Lambdas (``DefineAuthChallenge`` /
  ``CreateAuthChallenge`` / ``VerifyAuthChallenge``) that actually issue + verify a
  login OTP.
* The Redpanda (``notification.events``) producer that surfaces the OTP on the
  Notification Portal — **no SNS** in MVP; OTP rides Kafka (architecture §1.8.1).

Run
---
    uvx --with boto3 python scripts/provision_cognito.py \\
        --endpoint-url http://localhost:4566 --region ap-south-1

Credentials default to the LocalStack dummy pair ``test``/``test``; override via the
standard ``AWS_ACCESS_KEY_ID`` / ``AWS_SECRET_ACCESS_KEY`` env vars.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

import boto3
from botocore.config import Config as BotoConfig
from botocore.exceptions import ClientError

# ── Repository-relative defaults ───────────────────────────────────────────────
# scripts/provision_cognito.py  ->  parents[1] == repo root.
REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ENV_FILE = REPO_ROOT / "service_webapp" / ".env"
DEFAULT_README = REPO_ROOT / "README.md"

# ── Resource naming (kept in sync with service_webapp/src/core/config.py) ──────
DEFAULT_POOL_NAME = "sboai-subscribers"
DEFAULT_CLIENT_NAME = "sboai-webapp"

# Roles surface as Cognito groups and reach the JWT as `cognito:groups`.
# Order also doubles as the Cognito group precedence (lower = higher).
ROLES: list[str] = ["subscriber", "ops", "fraud", "dev", "admin", "marketing"]

# One demo user per non-subscriber role. Subscriber users are created at registration
# (Story 1.6), so we do not seed one here. Username == role keeps the demo simple.
SEED_USERS: list[str] = ["dev", "admin", "marketing", "ops", "fraud"]

# Markers delimiting the README section this script owns (idempotent rewrite).
README_BEGIN = "<!-- BEGIN COGNITO PROVISIONING -->"
README_END = "<!-- END COGNITO PROVISIONING -->"


# ── boto3 client ───────────────────────────────────────────────────────────────
def build_client(endpoint_url: str, region: str, access_key: str, secret_key: str):
    """Build a ``cognito-idp`` client pointed at MiniStack/LocalStack.

    A standard retry policy smooths over the brief window where the ministack
    container is still booting right after ``just deps`` starts it.
    """
    return boto3.client(
        "cognito-idp",
        endpoint_url=endpoint_url,
        region_name=region,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        config=BotoConfig(
            region_name=region,
            retries={"max_attempts": 6, "mode": "standard"},
            connect_timeout=5,
            read_timeout=20,
        ),
    )


def wait_for_cognito(client, timeout_s: int = 60) -> None:
    """Poll Cognito until it answers, so re-runs don't race container startup."""
    deadline = time.monotonic() + timeout_s
    last_err: Exception | None = None
    while time.monotonic() < deadline:
        try:
            client.list_user_pools(MaxResults=1)
            return
        except ClientError as exc:
            # ExpiredTokenException etc. mean Cognito IS up but rejected us — proceed.
            if exc.response.get("Error", {}).get("Code") == "ExpiredTokenException":
                return
            last_err = exc
            time.sleep(2)
        except Exception as exc:  # connection refused while container boots
            last_err = exc
            time.sleep(2)
    raise RuntimeError(
        f"Cognito did not become ready within {timeout_s}s: {last_err!r}"
    )


# ── pagination helpers ─────────────────────────────────────────────────────────
def _list_all(client, op, result_key, **kwargs):
    """Drain a boto3 paginator-style list call into a single list."""
    paginator = client.get_paginator(op)
    out: list[dict] = []
    for page in paginator.paginate(**kwargs):
        out.extend(page.get(result_key, []))
    return out


# ── 1. User Pool ───────────────────────────────────────────────────────────────
def upsert_user_pool(client, pool_name: str) -> str:
    """Return the UserPoolId for ``pool_name``, creating it if absent.

    Passwordless model: no password policy is enforced because the login flow never
    collects a password (Story 1.8 Custom Auth Flow). ``AllowAdminCreateUserOnly``
    disables public self-sign-up — every user is created server-side (Story 1.6).
    """
    # MaxResults is required for list_user_pools (unlike the other list calls).
    for pool in _list_all(client, "list_user_pools", "UserPools", MaxResults=60):
        if pool["Name"] == pool_name:
            print(f"[pool]  reuse existing  {pool_name} -> {pool['Id']}")
            return pool["Id"]

    resp = client.create_user_pool(
        PoolName=pool_name,
        # email + phone_number support the eventual OTP delivery + MSISDN login.
        # Both optional and mutable; alias/username-attribute tuning is deferred to
        # Story 1.8 (it owns the auth flow).
        Schema=[
            {
                "Name": "email",
                "AttributeDataType": "String",
                "Mutable": True,
                "Required": False,
            },
            {
                "Name": "phone_number",
                "AttributeDataType": "String",
                "Mutable": True,
                "Required": False,
            },
        ],
        UsernameConfiguration={"CaseSensitive": False},
        MfaConfiguration="OFF",  # OTP is the only factor; no TOTP/SMS MFA
        AdminCreateUserConfig={"AllowAdminCreateUserOnly": True},
        # LambdaConfig intentionally empty: the Custom-Auth challenge triggers +
        # Redpanda producer land in Story 1.8 / Notification-Portal epic.
    )
    pool_id = resp["UserPool"]["Id"]
    print(f"[pool]  created        {pool_name} -> {pool_id}")
    return pool_id


# ── 2. Role groups ─────────────────────────────────────────────────────────────
def upsert_groups(client, pool_id: str) -> None:
    """Ensure all role groups exist. Membership reaches the JWT as cognito:groups."""
    existing = {
        g["GroupName"]
        for g in _list_all(client, "list_groups", "Groups", UserPoolId=pool_id)
    }
    for precedence, role in enumerate(ROLES, start=1):
        if role in existing:
            print(f"[group] reuse existing  {role}")
            continue
        client.create_group(
            UserPoolId=pool_id,
            GroupName=role,
            Description=f"SBOAI role group: {role}",
            Precedence=precedence,
            # RoleArn omitted — no IAM role mapping in MVP; the group is a JWT claim only.
        )
        print(f"[group] created        {role}")


# ── 3. App Client ──────────────────────────────────────────────────────────────
def upsert_app_client(client, pool_id: str, client_name: str) -> str:
    """Return the ClientId for ``client_name``, creating or reconciling it.

    Token TTLs encode the §1.8.1 security bound: a 30-minute access token limits how
    long a blacklisted subscriber's token stays valid after account disable (FR-66).
    ``ALLOW_CUSTOM_AUTH`` enables the passwordless OTP flow; refresh is included so
    the SPA can renew without re-challenging.
    """
    auth_flows = ["ALLOW_CUSTOM_AUTH", "ALLOW_REFRESH_TOKEN_AUTH"]
    token_units = {
        "AccessToken": "minutes",
        "IdToken": "minutes",
        "RefreshToken": "days",
    }
    read_write_attrs = ["email", "phone_number"]

    for c in _list_all(
        client, "list_user_pool_clients", "UserPoolClients", UserPoolId=pool_id
    ):
        if c["ClientName"] == client_name:
            client_id = c["ClientId"]
            # Reconcile drift on re-run so manual edits don't silently diverge.
            client.update_user_pool_client(
                UserPoolId=pool_id,
                ClientId=client_id,
                ClientName=client_name,
                ExplicitAuthFlows=auth_flows,
                AccessTokenValidity=30,
                IdTokenValidity=30,
                RefreshTokenValidity=30,
                TokenValidityUnits=token_units,
                EnableTokenRevocation=True,
                PreventUserExistenceErrors="ENABLED",
                ReadAttributes=read_write_attrs,
                WriteAttributes=read_write_attrs,
            )
            print(f"[client] reuse + reconcile {client_name} -> {client_id}")
            return client_id

    resp = client.create_user_pool_client(
        UserPoolId=pool_id,
        ClientName=client_name,
        GenerateSecret=False,  # public SPA client — no secret
        ExplicitAuthFlows=auth_flows,
        AccessTokenValidity=30,
        IdTokenValidity=30,
        RefreshTokenValidity=30,
        TokenValidityUnits=token_units,
        EnableTokenRevocation=True,
        PreventUserExistenceErrors="ENABLED",
        ReadAttributes=read_write_attrs,
        WriteAttributes=read_write_attrs,
    )
    client_id = resp["UserPoolClient"]["ClientId"]
    print(f"[client] created          {client_name} -> {client_id}")
    return client_id


# ── 4. Seeded test users ───────────────────────────────────────────────────────
def _get_sub(client, pool_id: str, username: str) -> str | None:
    """Return the user's `sub` UUID, or None if the user does not exist."""
    try:
        resp = client.admin_get_user(UserPoolId=pool_id, Username=username)
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") == "UserNotFoundException":
            return None
        raise
    for attr in resp.get("UserAttributes", []):
        if attr["Name"] == "sub":
            return attr["Value"]
    return None


def seed_users(client, pool_id: str) -> list[dict]:
    """Ensure one demo user per non-subscriber role exists and is in its group.

    Users are created passwordless (no TemporaryPassword). Cognito leaves them in
    FORCE_CHANGE_PASSWORD status, which the passwordless Custom Auth flow bypasses
    — login itself lands in Story 1.8, so the users only need to exist + hold a role.
    """
    seeded: list[dict] = []
    for idx, role in enumerate(SEED_USERS):
        sub = _get_sub(client, pool_id, role)
        if sub is None:
            client.admin_create_user(
                UserPoolId=pool_id,
                Username=role,
                UserAttributes=[
                    {"Name": "email", "Value": f"{role}@simulator.sboai.local"},
                    {"Name": "phone_number", "Value": f"+9199990{idx:04d}"},
                ],
                MessageAction="SUPPRESS",  # no welcome email/SMS in MVP
            )
            sub = _get_sub(client, pool_id, role)
            print(f"[user]  created   {role} (sub={sub})")
        else:
            print(f"[user]  reuse     {role} (sub={sub})")

        # AddUserToGroup is idempotent on AWS/LocalStack; guard regardless.
        try:
            client.admin_add_user_to_group(
                UserPoolId=pool_id, Username=role, GroupName=role
            )
        except ClientError as exc:
            print(
                f"[user]  WARNING add-to-group {role}: {exc.response['Error']['Code']}"
            )

        seeded.append({"username": role, "role": role, "sub": sub or ""})
    return seeded


# ── 5. Write outputs (.env + README + stdout) ──────────────────────────────────
def write_env(env_file: Path, pool_id: str, client_id: str) -> None:
    """Upsert COGNITO_USER_POOL_ID / COGNITO_CLIENT_ID into the app .env.

    Creates the file (with a header) if the dev hasn't initialised it yet.
    """
    header = "# Populated by scripts/provision_cognito.py (MiniStack Cognito).\n"
    lines = (
        env_file.read_text().splitlines()
        if env_file.exists()
        else [header.rstrip("\n")]
    )

    updates = {"COGNITO_USER_POOL_ID": pool_id, "COGNITO_CLIENT_ID": client_id}
    seen: set[str] = set()
    out: list[str] = []
    for line in lines:
        key = line.split("=", 1)[0].strip()
        if key in updates:
            out.append(f"{key}={updates[key]}")
            seen.add(key)
        else:
            out.append(line)
    for key, value in updates.items():
        if key not in seen:
            out.append(f"{key}={value}")

    env_file.parent.mkdir(parents=True, exist_ok=True)
    env_file.write_text("\n".join(out) + "\n")
    print(f"[env]   wrote {env_file.relative_to(REPO_ROOT)} (pool_id, client_id)")


def write_readme(
    readme: Path,
    region: str,
    endpoint: str,
    pool_name: str,
    pool_id: str,
    client_name: str,
    client_id: str,
    seeded: list[dict],
) -> None:
    """Maintain a clearly-marked README section with provisioned IDs + seeded users.

    Idempotent: rewrites only the block between the markers; appends the block if the
    markers are absent.
    """
    rows = "\n".join(
        f"| `{u['username']}` | {u['role']} | `{u['sub'] or '<pending>'}` |"
        for u in seeded
    )
    block = f"""{README_BEGIN}
### MiniStack Cognito — provisioned resources & seeded test users

Provisioned by `scripts/provision_cognito.py` (run automatically by `just deps`).
Idempotent — re-running refreshes this section.

- **User Pool:** `{pool_name}` — ID: `{pool_id}`
- **App Client:** `{client_name}` — ID: `{client_id}`
- **Endpoint / region:** `{endpoint}` / `{region}` (MiniStack / LocalStack)
- **Auth model:** passwordless Custom Auth Flow (Story 1.8). Roles surface as the
  `cognito:groups` claim — the backend auth layer reads `cognito:groups`, not `role`.
- **No SNS in MVP:** login OTP is published to the Redpanda `notification.events`
  stream and surfaced on the Notification Portal (Story 1.8 / Notification-Portal epic).

Seeded test users (one per non-subscriber role; subscriber users come from registration):

| Username | Role (group) | `sub` |
| --- | --- | --- |
{rows}
{README_END}"""

    text = readme.read_text() if readme.exists() else ""
    if README_BEGIN in text and README_END in text:
        pre = text.split(README_BEGIN, 1)[0]
        post = text.split(README_END, 1)[1]
        text = pre + block + post
    else:
        sep = "\n\n" if text and not text.endswith("\n") else ("\n" if text else "")
        text = text + sep + block + "\n"
    readme.write_text(text)
    print(f"[readme] updated {readme.relative_to(REPO_ROOT)}")


# ── entrypoint ─────────────────────────────────────────────────────────────────
def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--endpoint-url",
        default=os.environ.get("AWS_ENDPOINT_URL", "http://localhost:4566"),
    )
    parser.add_argument(
        "--region", default=os.environ.get("AWS_DEFAULT_REGION", "ap-south-1")
    )
    parser.add_argument(
        "--pool-name",
        default=os.environ.get("COGNITO_USER_POOL_NAME", DEFAULT_POOL_NAME),
    )
    parser.add_argument("--client-name", default=DEFAULT_CLIENT_NAME)
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE)
    parser.add_argument("--readme", type=Path, default=DEFAULT_README)
    parser.add_argument(
        "--no-seed", action="store_true", help="skip seeding demo users"
    )
    args = parser.parse_args()

    access_key = os.environ.get("AWS_ACCESS_KEY_ID", "test")
    secret_key = os.environ.get("AWS_SECRET_ACCESS_KEY", "test")

    print(
        f"→ Cognito provisioning: {args.endpoint_url} ({args.region}), pool={args.pool_name}"
    )
    client = build_client(args.endpoint_url, args.region, access_key, secret_key)
    wait_for_cognito(client)

    pool_id = upsert_user_pool(client, args.pool_name)
    upsert_groups(client, pool_id)
    client_id = upsert_app_client(client, pool_id, args.client_name)
    seeded = [] if args.no_seed else seed_users(client, pool_id)

    write_env(args.env_file, pool_id, client_id)
    write_readme(
        args.readme,
        args.region,
        args.endpoint_url,
        args.pool_name,
        pool_id,
        args.client_name,
        client_id,
        seeded,
    )

    print("\n✓ Cognito provisioning complete")
    print(f"  COGNITO_USER_POOL_ID={pool_id}")
    print(f"  COGNITO_CLIENT_ID={client_id}")
    if seeded:
        print(
            f"  seeded {len(seeded)} demo users: {', '.join(u['username'] for u in seeded)}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
