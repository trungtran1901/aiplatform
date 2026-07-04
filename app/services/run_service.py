"""Run management and event tracking service."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.run import AgentEvent, AgentRun, EventType, RunStatus
from app.repositories.run_repository import AgentEventRepository, AgentRunRepository

logger = get_logger(__name__)


class RunTrackingService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.run_repo = AgentRunRepository(session)
        self.event_repo = AgentEventRepository(session)

    async def create_run(self, session_id: uuid.UUID, agent_id: uuid.UUID, input_text: str) -> AgentRun:
        run = await self.run_repo.create(
            session_id=session_id,
            agent_id=agent_id,
            status=RunStatus.pending,
            input=input_text,
        )
        await self.emit_event(run.id, EventType.agent_started, {"input": input_text})
        return run

    async def mark_running(self, run: AgentRun) -> AgentRun:
        run.status = RunStatus.running
        run.started_at = datetime.now(timezone.utc)
        await self.session.flush()
        return run

    async def mark_tool_calling(self, run: AgentRun) -> AgentRun:
        run.status = RunStatus.tool_calling
        await self.session.flush()
        return run

    async def mark_completed(self, run: AgentRun, output: str) -> AgentRun:
        run.status = RunStatus.completed
        run.output = output
        run.finished_at = datetime.now(timezone.utc)
        await self.session.flush()
        await self.emit_event(run.id, EventType.agent_completed, {"output_length": len(output)})
        return run

    async def mark_failed(self, run: AgentRun, error_message: str) -> AgentRun:
        run.status = RunStatus.failed
        run.error_message = error_message
        run.finished_at = datetime.now(timezone.utc)
        await self.session.flush()
        await self.emit_event(run.id, EventType.error, {"error": error_message})
        return run

    async def emit_event(self, run_id: uuid.UUID, event_type: EventType, payload: dict) -> AgentEvent:
        event = await self.event_repo.create(run_id=run_id, event_type=event_type, payload=payload)
        logger.info("agent_event_emitted", run_id=str(run_id), event_type=event_type.value)
        return event

    async def list_events(self, run_id: uuid.UUID) -> list[AgentEvent]:
        return await self.event_repo.list_by_run(run_id)
