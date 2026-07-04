"""
Storage factories for Agno Agent and Team persistence.

Provides two thin wrappers around Agno's PostgresStorage:
  - build_agent_storage()  — mode="agent" for single AgnoAgent instances
  - build_team_storage()   — mode="team"  for AgnoTeam instances

Both share a single SQLAlchemy sync Engine singleton (same pool as
PlatformMemoryDb) so multiple storage objects per request don't each
spin up their own connection pool.

WHY BOTH ARE NEEDED:
  Agno dispatches to Teams first (AgnoTeam), then the Team delegates to
  member Agents. Conversation history is tracked at the Team level via
  `AgnoTeam.memory.runs` — member agents use `team_session_id` rather
  than their own session_id when part of a Team. So enabling
  `add_history_to_messages=True` on the Team (not just on Agents) is
  what makes the coordinator model aware of previous turns. Without a
  Team-level storage the Team's Memory.runs is lost after each request
  exactly like the Agent case was before this fix.

TABLES:
  agno_agent_sessions — created by migration 0005_agno_agent_sessions
  agno_team_sessions  — created by migration 0006_agno_team_sessions
"""
from __future__ import annotations

from sqlalchemy.engine import Engine, create_engine

from agno.storage.postgres import PostgresStorage

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_engine_singleton: Engine | None = None

AGNO_SESSIONS_TABLE = "agno_agent_sessions"
AGNO_TEAM_SESSIONS_TABLE = "agno_team_sessions"


def _get_sync_engine() -> Engine:
    """Return (or lazily create) the shared sync SQLAlchemy engine.

    Reuses the same singleton as PlatformMemoryDb so both share one
    connection pool instead of each owning their own.
    """
    global _engine_singleton
    if _engine_singleton is None:
        settings = get_settings()
        _engine_singleton = create_engine(settings.DATABASE_URL_SYNC, pool_pre_ping=True)
        logger.info("platform_agent_storage_engine_created")
    return _engine_singleton


def build_agent_storage() -> PostgresStorage:
    """Build a PostgresStorage (mode=agent) backed by the shared sync engine.

    Used by AgnoAgent in _build_agno_agent(). Persists Memory.runs for
    single-agent chat turns so add_history_to_messages works across requests.
    """
    return PostgresStorage(
        table_name=AGNO_SESSIONS_TABLE,
        schema=None,           # public schema — same as all platform tables
        db_engine=_get_sync_engine(),
        mode="agent",
    )


def build_team_storage() -> PostgresStorage:
    """Build a PostgresStorage (mode=team) backed by the shared sync engine.

    Used by AgnoTeam in _build_agno_team() / _build_agno_root_team().
    In Team mode, conversation history is tracked at the *Team* level:
    member agents receive team_session_id and the Team coordinator is
    what gets add_history_to_messages. Without Team-level storage the
    coordinator's Memory.runs is wiped between requests just as the
    Agent case was before storage was wired in.
    """
    return PostgresStorage(
        table_name=AGNO_TEAM_SESSIONS_TABLE,
        schema=None,
        db_engine=_get_sync_engine(),
        mode="team",
    )
