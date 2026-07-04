"""
PlatformMemoryDb - bridges Agno's agentic memory (agno.memory.v2) to the
platform's own `agent_memories` table, instead of letting Agno create
and own a separate memory table.

WHY THIS EXISTS: agno.memory.v2.Memory requires a `db: MemoryDb` to do
anything - without one, enable_user_memories=True silently no-ops (see
Memory.acreate_user_memories: "MemoryDb not provided" -> returns early).
Agno ships agno.memory.v2.db.postgres.PostgresMemoryDb, but using it
verbatim would mean Agno creates and owns a second, separate memories
table with its own schema - splitting "where memory lives" across two
tables and breaking the platform's own GET /api/v1/memories /
DELETE /api/v1/memories/{id} APIs, which are documented as authoritative
(see docs/Architecture.md, section 8 "Memory"). Implementing the
MemoryDb interface ourselves keeps agent_memories as the single source
of truth: Agno's MemoryManager (an LLM that decides what's worth
remembering, then calls this class's methods as tool-calls) writes
directly into the same rows the platform APIs read.

The MemoryDb interface (agno.memory.v2.db.base.MemoryDb) is synchronous
by design - Agno calls it from inside a sync tool-call path even during
an async run. We therefore use a dedicated *sync* SQLAlchemy engine
(DATABASE_URL_SYNC, the same connection string Alembic migrations use)
rather than trying to bridge into the request's async session, which
would require unsafe cross-loop calls. This sync engine is intentionally
separate and short-lived per call - no long-held connections, no shared
state with the async ORM session used elsewhere in a request.
"""
from __future__ import annotations

import json
import uuid as uuid_module
from datetime import datetime, timezone

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from agno.memory.v2.db.base import MemoryDb
from agno.memory.v2.db.schema import MemoryRow

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_engine_singleton: Engine | None = None


def _get_sync_engine() -> Engine:
    global _engine_singleton
    if _engine_singleton is None:
        settings = get_settings()
        _engine_singleton = create_engine(settings.DATABASE_URL_SYNC, pool_pre_ping=True)
    return _engine_singleton


class PlatformMemoryDb(MemoryDb):
    """Implements agno.memory.v2.db.base.MemoryDb against agent_memories.

    Scoped to one (agent_id) at construction time, since every Agno
    Memory instance in this platform is built per-agent (see
    app/agno_runtime/engine.py) - capability/prompt/model resolution is
    already agent-scoped, and memory follows the same boundary: an
    agent's memories are never visible to a different agent.
    """

    def __init__(self, agent_id: uuid_module.UUID, *, engine: Engine | None = None) -> None:
        self.agent_id = agent_id
        self.engine = engine or _get_sync_engine()

    # --- lifecycle no-ops: agent_memories already exists via Alembic ---
    def create(self) -> None:
        pass

    def table_exists(self) -> bool:
        return True

    def drop_table(self) -> None:  # pragma: no cover - never called in normal operation
        raise NotImplementedError("agent_memories is managed by Alembic migrations, not by Agno")

    def clear(self) -> bool:
        with self.engine.begin() as conn:
            conn.execute(
                text("DELETE FROM agent_memories WHERE agent_id = :agent_id AND source_memory_id IS NOT NULL"),
                {"agent_id": str(self.agent_id)},
            )
        return True

    # --- core read/write contract used by Memory / MemoryManager ---
    def memory_exists(self, memory: MemoryRow) -> bool:
        with self.engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT 1 FROM agent_memories WHERE agent_id = :agent_id AND source_memory_id = :source_id LIMIT 1"
                ),
                {"agent_id": str(self.agent_id), "source_id": memory.id},
            ).first()
        return row is not None

    def read_memories(
        self, user_id: str | None = None, limit: int | None = None, sort: str | None = None
    ) -> list[MemoryRow]:
        order = "DESC" if sort == "desc" else "ASC"
        query = (
            "SELECT source_memory_id, user_id, content, created_at "
            "FROM agent_memories "
            "WHERE agent_id = :agent_id AND source_memory_id IS NOT NULL"
        )
        params: dict = {"agent_id": str(self.agent_id)}
        if user_id is not None:
            query += " AND user_id = :user_id"
            params["user_id"] = user_id
        query += f" ORDER BY created_at {order}"
        if limit is not None:
            query += " LIMIT :limit"
            params["limit"] = limit

        with self.engine.connect() as conn:
            rows = conn.execute(text(query), params).fetchall()

        results: list[MemoryRow] = []
        for source_memory_id, row_user_id, content, created_at in rows:
            try:
                memory_dict = json.loads(content)
            except (TypeError, ValueError):
                # Tolerate rows whose content is plain text rather than
                # the structured UserMemory JSON dict (e.g. memories
                # created via the platform API directly, see
                # MemoryService.record) by wrapping them minimally.
                memory_dict = {"memory": content}
            memory_dict["memory_id"] = source_memory_id
            results.append(
                MemoryRow(id=source_memory_id, user_id=row_user_id, memory=memory_dict, last_updated=created_at)
            )
        return results

    def upsert_memory(self, memory: MemoryRow, create_and_retry: bool = True) -> None:
        now = datetime.now(timezone.utc)
        content = json.dumps(memory.memory)
        with self.engine.begin() as conn:
            existing = conn.execute(
                text(
                    "SELECT id FROM agent_memories WHERE agent_id = :agent_id AND source_memory_id = :source_id"
                ),
                {"agent_id": str(self.agent_id), "source_id": memory.id},
            ).first()

            if existing is not None:
                conn.execute(
                    text(
                        "UPDATE agent_memories SET content = :content, updated_at = :now "
                        "WHERE agent_id = :agent_id AND source_memory_id = :source_id"
                    ),
                    {
                        "content": content,
                        "now": now,
                        "agent_id": str(self.agent_id),
                        "source_id": memory.id,
                    },
                )
            else:
                conn.execute(
                    text(
                        "INSERT INTO agent_memories "
                        "(id, agent_id, user_id, memory_type, content, source_memory_id, created_at, updated_at) "
                        "VALUES (:id, :agent_id, :user_id, 'fact', :content, :source_id, :now, :now)"
                    ),
                    {
                        "id": str(uuid_module.uuid4()),
                        "agent_id": str(self.agent_id),
                        "user_id": memory.user_id,
                        "content": content,
                        "source_id": memory.id,
                        "now": now,
                    },
                )
        logger.info("platform_memory_db_upsert", agent_id=str(self.agent_id), source_memory_id=memory.id)

    def delete_memory(self, memory_id: str) -> None:
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    "DELETE FROM agent_memories WHERE agent_id = :agent_id AND source_memory_id = :source_id"
                ),
                {"agent_id": str(self.agent_id), "source_id": memory_id},
            )
        logger.info("platform_memory_db_delete", agent_id=str(self.agent_id), source_memory_id=memory_id)