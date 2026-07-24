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

IDENTITY + QUOTA (added):
Every entrypoint below (`handle_chat`, `handle_chat_stream`) first
resolves the EFFECTIVE user_id/groups via
app.core.identity_context.resolve_effective_user_id() - this replaces
raw trust in `request.user_id` with a Keycloak-verified `sub` whenever
a verified identity is present on the request (see
app/core/identity.py, app/core/middleware.py). `request.user_id` is
overwritten in place so every downstream consumer (session ownership,
Agno's own agentic memory scoping, quota) uses exactly the same value -
there is deliberately only one place in this file that decides "who is
this request for".

Quota is enforced (`QuotaService.assert_within_quota`) once per chat
turn, right before a run is created - a caller that is already over
their configured limit never gets an AgentRun row created at all, and
sees a 429 `quota_exceeded` (mapped automatically by app/main.py's
existing AgnoRuntimeError handler - QuotaExceededError is a subclass).
Actual usage is recorded (`QuotaService.record_usage`) once a run
completes successfully, from whatever token metrics Agno's response
exposes - this is best-effort by design (see QuotaService) and never
allowed to fail an otherwise-successful chat turn.

COST CALCULATION (added): `record_usage()` accepts an optional
`cost_usd`, but nothing in this file used to compute one - `cost_usd`
was always sent as `None`, silently making every QuotaMetric.COST_USD
policy inert and leaving `quota_usage_events.cost_usd` permanently NULL.
`_compute_cost_usd()` below resolves the ModelRegistry entry actually
used for the turn and, if it has `cost_per_1k_input_tokens` /
`cost_per_1k_output_tokens` configured, computes
    cost_usd = (input_tokens/1000)*cost_in + (output_tokens/1000)*cost_out
Returns None (not 0.0) when the model has no cost configured at all, so
QuotaService can keep distinguishing "no cost data available" from
"this turn genuinely cost $0" - see app/services/quota_service.py.
Like token extraction, this is best-effort and never raises: a missing/
disabled ModelRegistry entry at this late stage (the run already
succeeded) simply yields cost_usd=None rather than failing the turn.

TOKEN EXTRACTION FIX (agno==1.8.4): `_extract_token_usage()` below used
to read `metrics["input_tokens"]` / `metrics["output_tokens"]` as plain
scalars. On agno 1.8.4, `RunResponse.metrics` is produced by
`Agent.aggregate_metrics_from_messages()`, which returns a dict whose
values are LISTS - one entry per assistant Message that carried metrics
during the run (i.e. one entry per model call / tool-loop iteration),
e.g. `{"input_tokens": [120, 45], "output_tokens": [30, 12], ...}`.
Treating a list as a scalar (`int(metrics["input_tokens"])`) raises
TypeError, which the old code silently swallowed and fell through to
`(0, 0)` - this was the actual root cause of quota always recording
zero tokens, even once app/agno_runtime/engine.py was fixed to read
`run_response.metrics` from the correct place. `_extract_token_usage`
now sums list-shaped values (and still accepts plain scalars, for
forward/backward compatibility with other Agno versions/shapes).
"""
from __future__ import annotations

import uuid
from typing import Any, AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession

from app.agno_runtime.agui_interface import AgnoAguiInterface, _merge_text_chunks
from app.agno_runtime.engine import AgnoRuntimeEngine, ResolvedRuntimeContext, ResolvedTeamContext, ResolvedRootContext
from app.core.config import get_settings
from app.core.exceptions import NotFoundError, RuntimeExecutionError
from app.core.identity_context import resolve_effective_user_id
from app.core.logging import get_logger
from app.core.run_control import clear_cancel, is_cancelled
from app.models.run import EventType
from app.models.session import MessageRole
from app.repositories.model_repository import ModelRegistryRepository
from app.repositories.session_repository import ChatMessageRepository, ChatSessionRepository
from app.schemas.chat import ChatRequest
from app.services.quota_service import QuotaService
from app.services.run_service import RunTrackingService

logger = get_logger(__name__)


def _sum_metric_field(container: Any, *keys: str) -> int:
    """Reads the first matching key out of `container` (dict or object
    with attributes) and returns it as an int, summing across the list
    if the value is list/tuple-shaped.

    agno==1.8.4's `RunResponse.metrics` stores each metric as a LIST of
    per-message values rather than a single aggregated scalar (see
    `Agent.aggregate_metrics_from_messages`), so this must sum rather
    than cast directly. Still accepts a plain scalar for forward/
    backward compatibility with other Agno versions/shapes. Never
    raises - returns 0 for anything it can't confidently interpret,
    since token accounting must never break an otherwise-successful
    chat turn.
    """
    for key in keys:
        if isinstance(container, dict):
            value = container.get(key)
        else:
            value = getattr(container, key, None)

        if value is None:
            continue

        if isinstance(value, (list, tuple)):
            try:
                return int(sum(v for v in value if v is not None))
            except (TypeError, ValueError):
                continue

        try:
            return int(value)
        except (TypeError, ValueError):
            continue

    return 0


def _extract_token_usage(resp_or_event: Any) -> tuple[int, int]:
    """Best-effort extraction of (input_tokens, output_tokens) from an
    Agno RunResponse / stream event's `.metrics`, summed across every
    assistant message counted in this run. Agno's `.metrics` can be a
    plain dict or a small metrics object depending on version/path
    (single-agent vs Team run), and on agno 1.8.4 each field is itself a
    LIST of per-message values rather than a pre-summed scalar (see
    `_sum_metric_field` / module docstring "TOKEN EXTRACTION FIX").
    Returns (0, 0) - never raises - when metrics are absent or in an
    unrecognized shape, since token accounting must never break an
    otherwise-successful chat turn.

    NOTE: `resp_or_event` here is always the normalized `event["payload"]`
    dict produced by AgnoRuntimeEngine's streaming methods
    (run_stream/run_team_stream/run_root_stream). Those methods surface
    Agno's final aggregated `run_response.metrics` (read once, after the
    stream is fully consumed) as `payload["metrics"]` on a single
    trailing `agent_completed` event - see app/agno_runtime/
    engine.py::_extract_final_metrics. No other event in the stream
    carries `metrics` in agno 1.8.4, so this function only needs to find
    a non-None value once per run.

    NOTE: verify the exact field names against the Agno version actually
    pinned in requirements.txt before relying on this for billing-grade
    accuracy - field names (and whether values are scalars or lists)
    have moved between Agno releases.
    """
    metrics = getattr(resp_or_event, "metrics", None)
    if metrics is None and isinstance(resp_or_event, dict):
        metrics = resp_or_event.get("metrics")
    if metrics is None:
        return 0, 0

    input_tokens = _sum_metric_field(metrics, "input_tokens", "prompt_tokens")
    output_tokens = _sum_metric_field(metrics, "output_tokens", "completion_tokens")

    return input_tokens, output_tokens


class ChatService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.session_repo = ChatSessionRepository(session)
        self.message_repo = ChatMessageRepository(session)
        self.run_service = RunTrackingService(session)
        self.engine = AgnoRuntimeEngine(session)
        self.agui_interface = AgnoAguiInterface()
        self.quota_service = QuotaService(session)
        self.model_repo = ModelRegistryRepository(session)

    def _resolve_identity(self, request: ChatRequest) -> list[str]:
        """Overwrites request.user_id in place with the effective
        (Keycloak-verified when available) user id, and returns the
        caller's verified groups (empty list when no verified identity
        is present, e.g. AUTH_MODE=trust_client_user_id and no bearer
        token was sent). Called once at the top of every public
        entrypoint below, before anything else touches request.user_id.
        """
        settings = get_settings()
        effective_user_id, verified_groups = resolve_effective_user_id(
            request.user_id, auth_mode=settings.AUTH_MODE
        )
        request.user_id = effective_user_id
        return verified_groups

    async def _compute_cost_usd(
        self, model_id: uuid.UUID | None, *, input_tokens: int, output_tokens: int
    ) -> float | None:
        """Resolves `model_id`'s ModelRegistry row and computes the cost
        of this turn from its configured per-1k-token prices. Returns
        None (never 0.0) when:
          - model_id is None,
          - the ModelRegistry entry can't be found (e.g. deleted since
            the run started), or
          - neither cost_per_1k_input_tokens nor
            cost_per_1k_output_tokens is configured on it.
        This lets QuotaService keep distinguishing "no pricing data" from
        "this call was free" - see module docstring. Never raises: a
        lookup failure here must not fail an otherwise-successful chat
        turn, so any error is logged and treated as "no cost data".
        """
        if model_id is None:
            return None
        try:
            entry = await self.model_repo.get(model_id)
        except Exception as exc:  # noqa: BLE001
            logger.error("quota_cost_model_lookup_failed", model_id=str(model_id), error=str(exc))
            return None

        if entry is None:
            return None
        if entry.cost_per_1k_input_tokens is None and entry.cost_per_1k_output_tokens is None:
            return None

        cost_in = entry.cost_per_1k_input_tokens or 0.0
        cost_out = entry.cost_per_1k_output_tokens or 0.0
        return (input_tokens / 1000.0) * cost_in + (output_tokens / 1000.0) * cost_out

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
        verified_groups = self._resolve_identity(request)

        ctx = await self.engine.resolve_dispatch_context(request.agentOs, request.team)

        # Three dispatch outcomes: single-Agent (ResolvedRuntimeContext),
        # explicit Team (ResolvedTeamContext), or root-OS routing (ResolvedRootContext).
        if isinstance(ctx, ResolvedRuntimeContext):
            selected_team = ctx.team
            selected_agent = ctx.agent
            model_id_for_quota = selected_agent.model_id or ctx.agent_os.default_model_id

            await self.quota_service.assert_within_quota(
                user_id=request.user_id, groups=verified_groups, model_id=model_id_for_quota
            )

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
            total_input_tokens = 0
            total_output_tokens = 0
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

                    in_tok, out_tok = _extract_token_usage(event["payload"])
                    total_input_tokens += in_tok
                    total_output_tokens += out_tok
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

            cost_usd = await self._compute_cost_usd(
                model_id_for_quota, input_tokens=total_input_tokens, output_tokens=total_output_tokens
            )
            await self.quota_service.record_usage(
                run_id=run.id,
                user_id=request.user_id,
                groups=verified_groups,
                model_id=model_id_for_quota,
                input_tokens=total_input_tokens,
                output_tokens=total_output_tokens,
                cost_usd=cost_usd,
            )

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
            model_id_for_quota = representative_agent.model_id or ctx.agent_os.default_model_id

            await self.quota_service.assert_within_quota(
                user_id=request.user_id, groups=verified_groups, model_id=model_id_for_quota
            )

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

            # run_team() (non-streaming) returns aggregated text only, not
            # per-run metrics - token accounting for Team runs requires the
            # streaming path (run_team_stream) to observe per-event
            # metrics; recorded as 0/0 here rather than guessing, so
            # cost_usd is computed from those same zeros (i.e. None, since
            # 0 tokens against any non-zero price is still a real, if
            # uninteresting, $0.00 - _compute_cost_usd only returns None
            # when the model has no pricing configured at all). This only
            # affects TOKENS/COST_USD-metric policies (REQUESTS-metric
            # policies are unaffected).
            cost_usd = await self._compute_cost_usd(model_id_for_quota, input_tokens=0, output_tokens=0)
            await self.quota_service.record_usage(
                run_id=run.id,
                user_id=request.user_id,
                groups=verified_groups,
                model_id=model_id_for_quota,
                input_tokens=0,
                output_tokens=0,
                cost_usd=cost_usd,
            )

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
            model_id_for_quota = representative_agent.model_id or ctx.agent_os.default_model_id

            await self.quota_service.assert_within_quota(
                user_id=request.user_id, groups=verified_groups, model_id=model_id_for_quota
            )

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
            total_input_tokens = 0
            total_output_tokens = 0
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

                    in_tok, out_tok = _extract_token_usage(event["payload"])
                    total_input_tokens += in_tok
                    total_output_tokens += out_tok
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

            cost_usd = await self._compute_cost_usd(
                model_id_for_quota, input_tokens=total_input_tokens, output_tokens=total_output_tokens
            )
            await self.quota_service.record_usage(
                run_id=run.id,
                user_id=request.user_id,
                groups=verified_groups,
                model_id=model_id_for_quota,
                input_tokens=total_input_tokens,
                output_tokens=total_output_tokens,
                cost_usd=cost_usd,
            )

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
        verified_groups = self._resolve_identity(request)

        ctx = await self.engine.resolve_dispatch_context(request.agentOs, request.team)

        if isinstance(ctx, ResolvedRuntimeContext):
            selected_team = ctx.team
            selected_agent = ctx.agent
            model_id_for_quota = selected_agent.model_id or ctx.agent_os.default_model_id

            await self.quota_service.assert_within_quota(
                user_id=request.user_id, groups=verified_groups, model_id=model_id_for_quota
            )

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
            total_input_tokens = 0
            total_output_tokens = 0
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

                    in_tok, out_tok = _extract_token_usage(event["payload"])
                    total_input_tokens += in_tok
                    total_output_tokens += out_tok

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

            cost_usd = await self._compute_cost_usd(
                model_id_for_quota, input_tokens=total_input_tokens, output_tokens=total_output_tokens
            )
            await self.quota_service.record_usage(
                run_id=run.id,
                user_id=request.user_id,
                groups=verified_groups,
                model_id=model_id_for_quota,
                input_tokens=total_input_tokens,
                output_tokens=total_output_tokens,
                cost_usd=cost_usd,
            )

            yield {
                "event_type": "agent_completed",
                "run_id": run.id,
                "session_id": chat_session.id,
                "data": {"message": final_output},
            }

        elif isinstance(ctx, ResolvedTeamContext):
            representative_agent = ctx.member_contexts[0].agent
            model_id_for_quota = representative_agent.model_id or ctx.agent_os.default_model_id

            await self.quota_service.assert_within_quota(
                user_id=request.user_id, groups=verified_groups, model_id=model_id_for_quota
            )

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
            total_input_tokens = 0
            total_output_tokens = 0
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

                    in_tok, out_tok = _extract_token_usage(event["payload"])
                    total_input_tokens += in_tok
                    total_output_tokens += out_tok

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

            cost_usd = await self._compute_cost_usd(
                model_id_for_quota, input_tokens=total_input_tokens, output_tokens=total_output_tokens
            )
            await self.quota_service.record_usage(
                run_id=run.id,
                user_id=request.user_id,
                groups=verified_groups,
                model_id=model_id_for_quota,
                input_tokens=total_input_tokens,
                output_tokens=total_output_tokens,
                cost_usd=cost_usd,
            )

            yield {
                "event_type": "agent_completed",
                "run_id": run.id,
                "session_id": chat_session.id,
                "data": {"message": final_output},
            }

        elif isinstance(ctx, ResolvedRootContext):
            rep_team_ctx = ctx.team_contexts[0]
            representative_agent = rep_team_ctx.member_contexts[0].agent
            model_id_for_quota = representative_agent.model_id or ctx.agent_os.default_model_id

            await self.quota_service.assert_within_quota(
                user_id=request.user_id, groups=verified_groups, model_id=model_id_for_quota
            )

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
            total_input_tokens = 0
            total_output_tokens = 0
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

                    in_tok, out_tok = _extract_token_usage(event["payload"])
                    total_input_tokens += in_tok
                    total_output_tokens += out_tok

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

            cost_usd = await self._compute_cost_usd(
                model_id_for_quota, input_tokens=total_input_tokens, output_tokens=total_output_tokens
            )
            await self.quota_service.record_usage(
                run_id=run.id,
                user_id=request.user_id,
                groups=verified_groups,
                model_id=model_id_for_quota,
                input_tokens=total_input_tokens,
                output_tokens=total_output_tokens,
                cost_usd=cost_usd,
            )

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