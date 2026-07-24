"""
Chat orchestration service.

Implements the runtime flow end to end:

    1. Resolve AgentOS -> Team -> Agent + compose prompt + resolve capabilities
    2. Get-or-create ChatSession
    3. Create AgentRun (status=pending)
    4. Persist the inbound user ChatMessage
    5. Execute via AgnoRuntimeEngine
    6. Persist AgentEvents as they occur (sourced from Agno's own RunEvent
       stream - tool_call_started/completed, reasoning, etc. - which fire
       identically whether the underlying tool is a plain Function or one
       sourced live from MCP Gateway's MCP-over-SSE server)
    7. Persist the assistant ChatMessage + mark Run completed/failed

Note: POST /api/v1/chat (non-streaming) internally drives the engine's
streaming path and just aggregates the result, so that tool-call events
are always captured into agent_events regardless of which endpoint the
caller used - only the HTTP response shape differs between the two
endpoints, not the underlying execution or observability.

CANCELLATION: POST /api/v1/chat/stream is the one execution path where a
user can realistically stop an in-flight run mid-way, the same way a
"stop generating" button works in a chat UI - see
app/core/run_control.py and POST /api/v1/runs/{id}/cancel. Each branch
below checks `is_cancelled(run.id)` once per streamed Agno event; on a
hit it closes the underlying stream (releasing its MCP session via the
same async-generator cleanup path a normal completion takes), marks the
run CANCELLED with whatever partial content had already been produced,
and stops - no further events are yielded for that run.
"""
from __future__ import annotations

from typing import Any, AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession

from app.agno_runtime.agui_interface import AgnoAguiInterface, _merge_text_chunks
from app.agno_runtime.engine import AgnoRuntimeEngine, ResolvedRuntimeContext, ResolvedTeamContext, ResolvedRootContext
from app.core.exceptions import NotFoundError, RuntimeExecutionError
from app.core.logging import get_logger
from app.core.run_control import clear_cancel, is_cancelled
from app.models.run import EventType
from app.models.session import MessageRole
from app.repositories.session_repository import ChatMessageRepository, ChatSessionRepository
from app.schemas.chat import ChatRequest
from app.services.run_service import RunTrackingService

logger = get_logger(__name__)


class ChatService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.session_repo = ChatSessionRepository(session)
        self.message_repo = ChatMessageRepository(session)
        self.run_service = RunTrackingService(session)
        self.engine = AgnoRuntimeEngine(session)
        self.agui_interface = AgnoAguiInterface()

    async def _get_or_create_session(self, request: ChatRequest, agent_os_id, team_id, agent_id):
        if request.session_id:
            # Ownership check applies only when the session already
            # exists: a session can only be CONTINUED by the same
            # user_id it was created with (including the anonymous
            # case, user_id=None continuing user_id=None). This prevents
            # user A from resuming user B's conversation just by sending
            # B's session_id - Agno Runtime performs no authorization
            # itself, but resource ownership at the data layer is not the
            # same thing as authorization/RBAC (which remains entirely
            # MCP Gateway's responsibility for tool access).
            existing = await self.session_repo.get(request.session_id)
            if existing is not None:
                if existing.user_id != request.user_id:
                    raise NotFoundError(
                        f"ChatSession {request.session_id} not found for this user_id"
                    )
                return existing

            # Client-generated session_id that doesn't exist yet (e.g. a
            # frontend that mints its own conversation ID up front, before
            # the first message is sent) - create it with exactly that ID
            # rather than rejecting it or silently swapping in a
            # server-generated one, so the caller's own ID remains the
            # canonical reference for this conversation going forward.
            return await self.session_repo.create(
                id=request.session_id,
                agent_os_id=agent_os_id,
                team_id=team_id,
                agent_id=agent_id,
                user_id=request.user_id,
                title=request.message[:80],
            )

        return await self.session_repo.create(
            agent_os_id=agent_os_id,
            team_id=team_id,
            agent_id=agent_id,
            user_id=request.user_id,
            title=request.message[:80],
        )

    async def handle_chat(self, request: ChatRequest) -> dict[str, Any]:
        """Non-streaming chat turn. Used by POST /api/v1/chat.

        Internally drives engine.run_stream() to completion so that
        tool-call events are captured into agent_events the same way as
        the streaming endpoint - only the final aggregated text is
        returned to the caller here.
        """
        ctx = await self.engine.resolve_dispatch_context(request.agentOs, request.team)

        # Three dispatch outcomes: single-Agent (ResolvedRuntimeContext),
        # explicit Team (ResolvedTeamContext), or root-OS routing (ResolvedRootContext).
        if isinstance(ctx, ResolvedRuntimeContext):
            selected_team = ctx.team
            selected_agent = ctx.agent
            chat_session = await self._get_or_create_session(
                request, ctx.agent_os.id, selected_team.id, selected_agent.id
            )

            run = await self.run_service.create_run(chat_session.id, selected_agent.id, request.message)

            await self.message_repo.create(
                session_id=chat_session.id,
                run_id=run.id,
                role=MessageRole.user,
                content=request.message,
            )

            await self.run_service.mark_running(run)

            full_content_parts: list[str] = []
            try:
                async for event in self.engine.run_stream(
                    ctx,
                    request.message,
                    session_id=str(chat_session.id),
                    user_id=request.user_id,
                    ui_context=request.uiContext,
                ):
                    await self.run_service.emit_event(run.id, _safe_event_type(event["event_type"]), event["payload"])

                    content_piece = event["payload"].get("content")
                    if content_piece and event["payload"].get("is_assistant_content"):
                        full_content_parts.append(str(content_piece))
            except RuntimeExecutionError as exc:
                await self.run_service.mark_failed(run, str(exc))
                raise

            output = self._merge_content_parts(full_content_parts)

            await self.message_repo.create(
                session_id=chat_session.id,
                run_id=run.id,
                role=MessageRole.assistant,
                content=output,
            )

            await self.run_service.mark_completed(run, output)

            return {
                "session_id": chat_session.id,
                "run_id": run.id,
                "agent_os": ctx.agent_os.code,
                "team": selected_team.code,
                "agent": selected_agent.code,
                "message": output,
                "status": "completed",
            }

        if isinstance(ctx, ResolvedTeamContext):
            # Pick a representative agent for session/run creation (DB requires an agent_id).
            representative_agent = ctx.member_contexts[0].agent
            chat_session = await self._get_or_create_session(
                request, ctx.agent_os.id, ctx.team.id, representative_agent.id
            )

            run = await self.run_service.create_run(chat_session.id, representative_agent.id, request.message)

            await self.message_repo.create(
                session_id=chat_session.id,
                run_id=run.id,
                role=MessageRole.user,
                content=request.message,
            )

            await self.run_service.mark_running(run)

            # Call the non-streaming route to get final output
            output = await self.engine.run_team(
                ctx, request.message, session_id=str(chat_session.id), user_id=request.user_id, ui_context=request.uiContext,
            )

            await self.message_repo.create(
                session_id=chat_session.id,
                run_id=run.id,
                role=MessageRole.assistant,
                content=output,
            )
            await self.run_service.mark_completed(run, output)

            return {
                "session_id": chat_session.id,
                "run_id": run.id,
                "agent_os": ctx.agent_os.code,
                "team": ctx.team.code,
                "agent": representative_agent.code,
                "message": output,
                "status": "completed",
            }

        if isinstance(ctx, ResolvedRootContext):
            # Representative team/agent for DB records
            rep_team_ctx = ctx.team_contexts[0]
            representative_agent = rep_team_ctx.member_contexts[0].agent
            chat_session = await self._get_or_create_session(
                request, ctx.agent_os.id, rep_team_ctx.team.id, representative_agent.id
            )

            run = await self.run_service.create_run(chat_session.id, representative_agent.id, request.message)

            await self.message_repo.create(
                session_id=chat_session.id,
                run_id=run.id,
                role=MessageRole.user,
                content=request.message,
            )

            await self.run_service.mark_running(run)

            full_content_parts: list[str] = []
            try:
                async for event in self.engine.run_root_stream(
                    ctx,
                    request.message,
                    session_id=str(chat_session.id),
                    user_id=request.user_id,
                ):
                    # stream events through to run events storage
                    await self.run_service.emit_event(run.id, _safe_event_type(event["event_type"]), event["payload"])

                    content_piece = event["payload"].get("content")
                    if content_piece and event["payload"].get("is_assistant_content"):
                        full_content_parts.append(str(content_piece))
            except RuntimeExecutionError as exc:
                await self.run_service.mark_failed(run, str(exc))
                raise

            output = self._merge_content_parts(full_content_parts)

            await self.message_repo.create(
                session_id=chat_session.id,
                run_id=run.id,
                role=MessageRole.assistant,
                content=output,
            )

            await self.run_service.mark_completed(run, output)

            return {
                "session_id": chat_session.id,
                "run_id": run.id,
                "agent_os": ctx.agent_os.code,
                "team": rep_team_ctx.team.code,
                "agent": representative_agent.code,
                "message": output,
                "status": "completed",
            }

        # Fallback
        raise RuntimeExecutionError("Unable to resolve runtime context for chat request")

    async def _handle_cancellation(
        self,
        run,
        stream,
        chat_session_id,
        full_content_parts: list[str],
    ) -> dict[str, Any]:
        """Shared cancellation-noticed path for every branch below:
        closes the underlying Agno stream (triggering its normal
        async-generator cleanup - the same `finally`/`async with` exit
        that a completed or errored run takes, so the MCP session is
        released the same way either way), persists whatever partial
        assistant content had already streamed in as the ChatMessage,
        marks the run CANCELLED, and clears the Redis signal now that
        it's been acted on."""
        await stream.aclose()

        partial_output = self._merge_content_parts(full_content_parts)
        if partial_output:
            await self.message_repo.create(
                session_id=chat_session_id,
                run_id=run.id,
                role=MessageRole.assistant,
                content=partial_output,
            )
        await self.run_service.mark_cancelled(run, partial_output)
        await self.session.commit()
        await clear_cancel(str(run.id))

        logger.info("agent_run_cancelled", run_id=str(run.id))

        return {
            "event_type": "run_cancelled",
            "run_id": run.id,
            "session_id": chat_session_id,
            "data": {"message": "Run cancelled by user", "partial_message": partial_output},
        }

    async def handle_chat_stream(self, request: ChatRequest) -> AsyncIterator[dict[str, Any]]:
        """Streaming chat turn. Used by POST /api/v1/chat/stream (SSE)."""
        ctx = await self.engine.resolve_dispatch_context(request.agentOs, request.team)

        if isinstance(ctx, ResolvedRuntimeContext):
            selected_team = ctx.team
            selected_agent = ctx.agent
            chat_session = await self._get_or_create_session(
                request, ctx.agent_os.id, selected_team.id, selected_agent.id
            )
            run = await self.run_service.create_run(chat_session.id, selected_agent.id, request.message)

            await self.message_repo.create(
                session_id=chat_session.id,
                run_id=run.id,
                role=MessageRole.user,
                content=request.message,
            )
            await self.session.commit()

            await self.run_service.mark_running(run)
            await self.session.commit()

            yield {
                "event_type": "agent_started",
                "run_id": run.id,
                "session_id": chat_session.id,
                "data": {"agent": selected_agent.code, "team": selected_team.code},
            }

            full_content_parts: list[str] = []
            stream = self.engine.run_stream(
                ctx,
                request.message,
                session_id=str(chat_session.id),
                user_id=request.user_id,
                ui_context=request.uiContext,
            )
            try:
                async for event in stream:
                    if await is_cancelled(str(run.id)):
                        yield await self._handle_cancellation(run, stream, chat_session.id, full_content_parts)
                        return

                    event_type = _safe_event_type(event["event_type"])
                    await self.run_service.emit_event(run.id, event_type, event["payload"])
                    await self.session.commit()

                    content_piece = event["payload"].get("content")
                    if content_piece and event["payload"].get("is_assistant_content"):
                        full_content_parts.append(str(content_piece))

                    agui_event = self.agui_interface.build_event(
                        event_name=event["event_type"],
                        payload=event["payload"],
                        content=content_piece,
                        is_assistant_content=bool(event["payload"].get("is_assistant_content")),
                    )
                    payload = dict(event["payload"])
                    payload["agui"] = agui_event
                    payload["ui_status"] = agui_event["status"]

                    yield {
                        "event_type": event["event_type"],
                        "run_id": run.id,
                        "session_id": chat_session.id,
                        "data": payload,
                    }
            except RuntimeExecutionError as exc:
                await self.run_service.mark_failed(run, str(exc))
                await self.session.commit()
                yield {
                    "event_type": "error",
                    "run_id": run.id,
                    "session_id": chat_session.id,
                    "data": {"error": str(exc)},
                }
                return

            final_output = self._merge_content_parts(full_content_parts)
            await self.message_repo.create(
                session_id=chat_session.id,
                run_id=run.id,
                role=MessageRole.assistant,
                content=final_output,
            )
            await self.run_service.mark_completed(run, final_output)
            await self.session.commit()

            yield {
                "event_type": "agent_completed",
                "run_id": run.id,
                "session_id": chat_session.id,
                "data": {"message": final_output},
            }

        elif isinstance(ctx, ResolvedTeamContext):
            representative_agent = ctx.member_contexts[0].agent
            chat_session = await self._get_or_create_session(
                request, ctx.agent_os.id, ctx.team.id, representative_agent.id
            )
            run = await self.run_service.create_run(chat_session.id, representative_agent.id, request.message)

            await self.message_repo.create(
                session_id=chat_session.id,
                run_id=run.id,
                role=MessageRole.user,
                content=request.message,
            )
            await self.session.commit()

            await self.run_service.mark_running(run)
            await self.session.commit()

            yield {
                "event_type": "agent_started",
                "run_id": run.id,
                "session_id": chat_session.id,
                "data": {"agent": representative_agent.code, "team": ctx.team.code},
            }

            full_content_parts: list[str] = []
            stream = self.engine.run_team_stream(
                ctx,
                request.message,
                session_id=str(chat_session.id),
                user_id=request.user_id,
                ui_context=request.uiContext,
            )
            try:
                async for event in stream:
                    if await is_cancelled(str(run.id)):
                        yield await self._handle_cancellation(run, stream, chat_session.id, full_content_parts)
                        return

                    event_type = _safe_event_type(event["event_type"])
                    await self.run_service.emit_event(run.id, event_type, event["payload"])
                    await self.session.commit()

                    content_piece = event["payload"].get("content")
                    if content_piece and event["payload"].get("is_assistant_content"):
                        full_content_parts.append(str(content_piece))

                    agui_event = self.agui_interface.build_event(
                        event_name=event["event_type"],
                        payload=event["payload"],
                        content=content_piece,
                        is_assistant_content=bool(event["payload"].get("is_assistant_content")),
                    )
                    payload = dict(event["payload"])
                    payload["agui"] = agui_event
                    payload["ui_status"] = agui_event["status"]

                    yield {
                        "event_type": event["event_type"],
                        "run_id": run.id,
                        "session_id": chat_session.id,
                        "data": payload,
                    }
            except RuntimeExecutionError as exc:
                await self.run_service.mark_failed(run, str(exc))
                await self.session.commit()
                yield {
                    "event_type": "error",
                    "run_id": run.id,
                    "session_id": chat_session.id,
                    "data": {"error": str(exc)},
                }
                return

            final_output = self._merge_content_parts(full_content_parts)
            await self.message_repo.create(
                session_id=chat_session.id,
                run_id=run.id,
                role=MessageRole.assistant,
                content=final_output,
            )
            await self.run_service.mark_completed(run, final_output)
            await self.session.commit()

            yield {
                "event_type": "agent_completed",
                "run_id": run.id,
                "session_id": chat_session.id,
                "data": {"message": final_output},
            }

        elif isinstance(ctx, ResolvedRootContext):
            rep_team_ctx = ctx.team_contexts[0]
            representative_agent = rep_team_ctx.member_contexts[0].agent
            chat_session = await self._get_or_create_session(
                request, ctx.agent_os.id, rep_team_ctx.team.id, representative_agent.id
            )
            run = await self.run_service.create_run(chat_session.id, representative_agent.id, request.message)

            await self.message_repo.create(
                session_id=chat_session.id,
                run_id=run.id,
                role=MessageRole.user,
                content=request.message,
            )
            await self.session.commit()

            await self.run_service.mark_running(run)
            await self.session.commit()

            yield {
                "event_type": "agent_started",
                "run_id": run.id,
                "session_id": chat_session.id,
                "data": {"agent": representative_agent.code, "team": rep_team_ctx.team.code},
            }

            full_content_parts: list[str] = []
            stream = self.engine.run_root_stream(
                ctx,
                request.message,
                session_id=str(chat_session.id),
                user_id=request.user_id,
                ui_context=request.uiContext,
            )
            try:
                async for event in stream:
                    if await is_cancelled(str(run.id)):
                        yield await self._handle_cancellation(run, stream, chat_session.id, full_content_parts)
                        return

                    event_type = _safe_event_type(event["event_type"])
                    await self.run_service.emit_event(run.id, event_type, event["payload"])
                    await self.session.commit()

                    content_piece = event["payload"].get("content")
                    if content_piece and event["payload"].get("is_assistant_content"):
                        full_content_parts.append(str(content_piece))

                    agui_event = self.agui_interface.build_event(
                        event_name=event["event_type"],
                        payload=event["payload"],
                        content=content_piece,
                        is_assistant_content=bool(event["payload"].get("is_assistant_content")),
                    )
                    payload = dict(event["payload"])
                    payload["agui"] = agui_event
                    payload["ui_status"] = agui_event["status"]

                    yield {
                        "event_type": event["event_type"],
                        "run_id": run.id,
                        "session_id": chat_session.id,
                        "data": payload,
                    }
            except RuntimeExecutionError as exc:
                await self.run_service.mark_failed(run, str(exc))
                await self.session.commit()
                yield {
                    "event_type": "error",
                    "run_id": run.id,
                    "session_id": chat_session.id,
                    "data": {"error": str(exc)},
                }
                return

            final_output = self._merge_content_parts(full_content_parts)
            await self.message_repo.create(
                session_id=chat_session.id,
                run_id=run.id,
                role=MessageRole.assistant,
                content=final_output,
            )
            await self.run_service.mark_completed(run, final_output)
            await self.session.commit()

            yield {
                "event_type": "agent_completed",
                "run_id": run.id,
                "session_id": chat_session.id,
                "data": {"message": final_output},
            }


    def _merge_content_parts(self, content_parts: list[str]) -> str:
        merged = ""
        for part in content_parts:
            merged = _merge_text_chunks(merged, part)
        return merged


def _safe_event_type(event_name: str) -> EventType:
    """Maps an arbitrary event name string onto the EventType enum,
    defaulting to a sensible fallback rather than raising, since event
    taxonomies evolve across Agno versions and we never want
    observability logging to break the actual chat turn."""
    try:
        return EventType(event_name)
    except ValueError:
        if "tool" in event_name:
            return EventType.tool_call_started
        if "error" in event_name.lower():
            return EventType.error
        return EventType.agent_response