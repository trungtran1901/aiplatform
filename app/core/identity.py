"""
Verified identity from Keycloak (JWT/JWKS).

CRITICAL DISTINCTION from app.core.auth_context.PropagatedAuth:
PropagatedAuth forwards the raw Authorization header VERBATIM to MCP
Gateway and never inspects it - that contract is unchanged by this
module.

This module is the ONE place in the codebase that actually decodes and
cryptographically verifies a JWT. It exists solely to answer "who is
the caller, really" for quota accounting (app/services/quota_service.py)
- NOT for authorization/RBAC, which per docs/Architecture.md remains
entirely MCP Gateway's job. A verified `sub` is a much stronger key for
per-user quota than a client-supplied `user_id` string, which anyone
could set to any value to dodge their quota.

Fails OPEN to "no verified identity" (never raises) when:
  - FEATURE_KEYCLOAK_AUTH is off (default - zero behavior change),
  - no/malformed Authorization header,
  - JWKS fetch fails or signature/issuer/audience validation fails.
Callers (RequestContextMiddleware) decide what to do with `None` -
currently: fall back to the client-supplied user_id (AUTH_MODE=
trust_client_user_id), which is the ONLY safe default for existing
deployments that haven't turned Keycloak on yet. Once
AUTH_MODE=keycloak_required, callers should treat None as "anonymous"
for quota purposes (never silently trust a client-asserted user_id).
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

import httpx
from jose import jwt
from jose.exceptions import JWTError

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class VerifiedIdentity:
    user_id: str  # JWT "sub" claim - stable, unforgeable, the ONLY safe quota key
    username: str | None = None
    email: str | None = None
    groups: list[str] = field(default_factory=list)
    realm: str | None = None


class _JWKSCache:
    """Caches Keycloak's JWKS (public signing keys) with a short TTL, so
    verifying every request doesn't hit the Keycloak realm's
    certs endpoint every time. A single process-wide cache is safe here
    since JWKS is public, non-request-scoped data."""

    def __init__(self) -> None:
        self._jwks: dict | None = None
        self._fetched_at: float = 0.0

    async def get(self, jwks_url: str, *, ttl_seconds: int = 300) -> dict:
        now = time.monotonic()
        if self._jwks is not None and (now - self._fetched_at) < ttl_seconds:
            return self._jwks
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(jwks_url)
            response.raise_for_status()
            self._jwks = response.json()
            self._fetched_at = now
        return self._jwks


_jwks_cache = _JWKSCache()


def _extract_groups(claims: dict) -> list[str]:
    """Keycloak can surface group/role membership under different claim
    names depending on realm/client mapper configuration - checked in
    order of preference. `groups` (from a "Group Membership" mapper) is
    preferred since it reflects actual Keycloak groups (which is what
    LDAP User Federation syncs into); `realm_access.roles` is a
    reasonable fallback for realms that model quota scope as roles
    instead."""
    if isinstance(claims.get("groups"), list):
        return [str(g).lstrip("/") for g in claims["groups"]]
    realm_access = claims.get("realm_access")
    if isinstance(realm_access, dict) and isinstance(realm_access.get("roles"), list):
        return [str(r) for r in realm_access["roles"]]
    return []


async def verify_bearer_token(authorization: str | None) -> VerifiedIdentity | None:
    """Verifies a raw `Authorization: Bearer <token>` header value
    against Keycloak's JWKS. Returns None (never raises) on any failure
    - see module docstring for the fail-open rationale."""
    settings = get_settings()
    if not settings.FEATURE_KEYCLOAK_AUTH:
        return None
    if not authorization or not authorization.lower().startswith("bearer "):
        return None
    token = authorization.split(" ", 1)[1].strip()
    if not token:
        return None

    try:
        jwks = await _jwks_cache.get(settings.KEYCLOAK_JWKS_URL)
        unverified_header = jwt.get_unverified_header(token)
        key = next((k for k in jwks.get("keys", []) if k.get("kid") == unverified_header.get("kid")), None)
        if key is None:
            # Key rotated since last cache fetch - force one refetch.
            _jwks_cache._jwks = None
            jwks = await _jwks_cache.get(settings.KEYCLOAK_JWKS_URL)
            key = next((k for k in jwks.get("keys", []) if k.get("kid") == unverified_header.get("kid")), None)
        if key is None:
            logger.warning("keycloak_jwt_unknown_kid", kid=unverified_header.get("kid"))
            return None

        claims = jwt.decode(
            token,
            key,
            algorithms=[unverified_header.get("alg", "RS256")],
            audience=settings.KEYCLOAK_AUDIENCE or None,
            issuer=settings.KEYCLOAK_ISSUER_URL or None,
            options={"verify_aud": bool(settings.KEYCLOAK_AUDIENCE)},
        )
    except (JWTError, httpx.HTTPError, ValueError) as exc:
        logger.warning("keycloak_jwt_verification_failed", error=str(exc))
        return None
    except Exception as exc:  # noqa: BLE001 - never let identity parsing crash a request
        logger.error("keycloak_jwt_unexpected_error", error=str(exc))
        return None

    sub = claims.get("sub")
    if not sub:
        return None

    return VerifiedIdentity(
        user_id=str(sub),
        username=claims.get("preferred_username"),
        email=claims.get("email"),
        groups=_extract_groups(claims),
        realm=settings.KEYCLOAK_REALM,
    )