"""
Request-scoped storage for the VerifiedIdentity produced by
app.core.identity.verify_bearer_token(), set by RequestContextMiddleware
and read by ChatService / QuotaService.

Kept as its own tiny module (mirroring app.core.auth_context's
ContextVar pattern) rather than merged into PropagatedAuth, since the
two have deliberately different trust levels: PropagatedAuth is raw,
unverified, forward-only data; VerifiedIdentity is cryptographically
verified and is the only thing quota accounting should ever trust as
"the user".
"""
from __future__ import annotations

from contextvars import ContextVar

from app.core.identity import VerifiedIdentity

_identity_ctx: ContextVar[VerifiedIdentity | None] = ContextVar("verified_identity", default=None)


def set_verified_identity(identity: VerifiedIdentity | None) -> None:
    _identity_ctx.set(identity)


def get_verified_identity() -> VerifiedIdentity | None:
    return _identity_ctx.get()


def resolve_effective_user_id(client_supplied_user_id: str | None, *, auth_mode: str) -> tuple[str | None, list[str]]:
    """Single choke point deciding which user_id/groups a request
    actually uses for session ownership + quota accounting.

    - auth_mode == "keycloak_required": ONLY the verified `sub` is
      trusted; a client-supplied user_id is ignored entirely (it cannot
      be used to spoof another user's quota or session history).
    - auth_mode == "trust_client_user_id" (default, backward-compatible):
      verified identity is preferred when present (e.g. Keycloak is on
      but not yet enforced), otherwise falls back to whatever the client
      sent - byte-for-byte the pre-Keycloak behavior.
    """
    identity = get_verified_identity()
    if identity is not None:
        return identity.user_id, identity.groups
    if auth_mode == "keycloak_required":
        return None, []
    return client_supplied_user_id, []