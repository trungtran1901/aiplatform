"""
Agno Runtime Engine.

This module is the bridge between platform metadata (AgentOS/Team/Agent/
Prompt/Skill/Capability rows in Postgres) and live Agno framework objects.

It implements the runtime flow described in the architecture:

    Resolve AgentOS -> Team -> Agent
        |
    Compose Final Prompt (AgentOS + Team + Agent)
        |
    Resolve Effective Capabilities (intersection)
        |
    Open MCP session scoped to effective capabilities (MCP Tool Adapter)
        |
    Construct Agno Agent (model, prompt, live MCPTools)
        |
    Agent.arun(message) -- Agno's own reasoning/tool-calling loop
        |
    Emit AgentEvents as Agno surfaces RunResponseEvents
        |
    Close MCP session
        |
    Persist Run + Messages + Memories

No business logic about *what* a tool does lives here - this module only
wires metadata into Agno's constructs. It also never makes an
authorization decision; all it does is forward whichever capabilities
were already determined (by capability_service) to be in scope.

MCP-over-SSE note: the MCP session (a live connection to MCP Gateway's
MCP server) must stay open for the entire duration of one agent run,
since Agno calls tools on it lazily as the LLM decides to use them. It
is opened right before `arun()` and closed right after, in `run()` /
`run_stream()` below - never held open across chat turns, keeping the
runtime stateless between requests.

Hierarchical dispatch (AgentOS -> Team -> Agent), added on top of the
flow above:

    resolve_dispatch_context(agent_os_code, team_code=None)
        team_code given   -> resolve_team_context_by_code()
                              -> one ResolvedTeamContext
                              -> _build_agno_team()      (mode=coordinate)
                              -> Team's own leader picks which member
                                 Agent(s) handle the request
        team_code omitted -> resolve_root_context()
                              -> every enabled Team under the AgentOS,
                                 each as its own ResolvedTeamContext
                              -> _build_agno_root_team()  (mode=route by
                                 default; each member IS a fully built
                                 AgnoTeam, i.e. team-of-teams)
                              -> Root Team's own leader picks which
                                 Team - and transitively which
                                 Agent(s) - handle the request

No routing decision is made by platform code in either branch; Agno's
own leader model(s) do the picking. Platform code only ever decides
*what is eligible* (enabled AgentOS/Team/Agent rows, effective
capabilities) - never *which one gets used*.

Prerequisites this assumes elsewhere in the codebase (verify/add if
missing before wiring this up):
  - PromptCompositionService.compose_root_only(agent_os) - AgentOS-level
    routing instructions, analogous to the existing compose_team_only().
  - TeamRepository.list(agent_os_id=..., limit=...) - listing teams
    scoped to one AgentOS, analogous to AgentRepository.list(team_id=...)
    already used in _build_team_context().
"""
from __future__ import annotations

from contextlib import AsyncExitStack
from typing import Any, AsyncIterator, Literal

from sqlalchemy.ext.asyncio import AsyncSession

from agno.agent import Agent as AgnoAgent
from agno.memory.v2.memory import Memory
from agno.team import Team as AgnoTeam

from app.agno_runtime.agent_storage import build_agent_storage
from app.agno_runtime.memory_db import PlatformMemoryDb
from app.agno_runtime.tool_adapter import ToolCatalogBuilder
from app.core.exceptions import RuntimeExecutionError
from app.core.logging import get_logger
from app.models.hierarchy import Agent, AgentOS, Team
from app.repositories.hierarchy_repository import AgentOSRepository, AgentRepository, TeamRepository
from app.services.capability_service import CapabilityService
from app.services.model_service import ModelResolutionService
from app.services.prompt_service import PromptCompositionService

logger = get_logger(__name__)


# Maps Agno's native RunEvent values onto the platform's own EventType
# vocabulary (see app.models.run.EventType), so observability consumers
# only need to know one event taxonomy regardless of Agno's internal
# naming. These events fire generically at the agent/model layer
# regardless of whether the underlying tool is a plain Function or one
# sourced from an MCP server, so this mapping is unaffected by the MCP
# transport details below.
_AGNO_EVENT_MAP: dict[str, str] = {
    "RunStarted": "agent_started",
    "ReasoningStarted": "reasoning_started",
    "ToolCallStarted": "tool_selected",
    "ToolCallCompleted": "tool_call_completed",
    "RunResponseContent": "agent_response",
    "RunCompleted": "agent_completed",
    "MemoryUpdateStarted": "memory_update_started",
    "MemoryUpdateCompleted": "memory_update_completed",
    "RunError": "error",
}

# agno.team.Team emits its own distinctly-named event class
# (TeamRunEvent: "TeamRunStarted", "TeamToolCallStarted", ...) rather
# than reusing Agent's RunEvent names - mapped separately here onto the
# exact same platform EventType vocabulary as _AGNO_EVENT_MAP above, so
# observability consumers never need to know whether a given chat turn
# or workflow step was executed by a single Agent or a Team.
_AGNO_TEAM_EVENT_MAP: dict[str, str] = {
    "TeamRunStarted": "agent_started",
    "TeamReasoningStarted": "reasoning_started",
    "TeamToolCallStarted": "tool_selected",
    "TeamToolCallCompleted": "tool_call_completed",
    "TeamRunResponseContent": "agent_response",
    "TeamRunCompleted": "agent_completed",
    "TeamMemoryUpdateStarted": "memory_update_started",
    "TeamMemoryUpdateCompleted": "memory_update_completed",
    "TeamRunError": "error",
}
_ASSISTANT_CONTENT_TEAM_EVENT_NAMES = frozenset({"TeamRunResponseContent"})

# Only these event types carry assistant-facing answer text in their
# `content` field. Several other Agno events also set `content` (e.g.
# ToolCallCompletedEvent.content holds a tool execution log/result, not
# anything meant to be shown to the user as the assistant's reply) - if
# those were collected into the final message too, the response would
# get tool-call logs and/or duplicated text spliced into it. We collect
# ONLY the incremental delta event here; RunResponseCompletedEvent's
# content is the same text reassembled by Agno and is deliberately NOT
# also collected, to avoid doubling the final message.
_ASSISTANT_CONTENT_EVENT_NAMES = frozenset({"RunResponseContent"})


def _build_stream_payload(event_name: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize stream payloads so only assistant text deltas surface as content.

    Agno can emit completion events that carry the same final answer text as a
    non-assistant event (for example TeamRunCompleted). Those payloads should
    not be forwarded to the UI as if they were new assistant content, because
    that causes duplicated or repeated output when routing through a root team.
    """
    normalized_payload = dict(payload)
    is_assistant_content = event_name in _ASSISTANT_CONTENT_EVENT_NAMES or event_name in _ASSISTANT_CONTENT_TEAM_EVENT_NAMES
    normalized_payload["is_assistant_content"] = is_assistant_content

    if not is_assistant_content:
        normalized_payload.pop("content", None)

    return normalized_payload


class ResolvedRuntimeContext:
    """Everything needed to execute one chat turn, fully resolved from
    metadata, EXCEPT the live MCP tool connection - that is opened
    separately around the actual run (see run() / run_stream() below),
    since it is a stateful SSE session, not inert metadata."""

    __slots__ = ("agent_os", "team", "agent", "final_prompt", "effective_capabilities")

    def __init__(
        self,
        agent_os: AgentOS,
        team: Team,
        agent: Agent,
        final_prompt: str,
        effective_capabilities: list[str],
    ) -> None:
        self.agent_os = agent_os
        self.team = team
        self.agent = agent
        self.final_prompt = final_prompt
        self.effective_capabilities = effective_capabilities


class ResolvedTeamContext:
    """Everything needed to execute one Team run, fully resolved from
    metadata. Distinct from ResolvedRuntimeContext (single-Agent) since a
    Team run involves multiple member Agents, each with their own
    resolved prompt/capabilities, plus the Team's own composed
    instructions.
    """

    __slots__ = ("agent_os", "team", "team_prompt", "member_contexts")

    def __init__(
        self,
        agent_os: AgentOS,
        team: Team,
        team_prompt: str,
        member_contexts: list[ResolvedRuntimeContext],
    ) -> None:
        self.agent_os = agent_os
        self.team = team
        self.team_prompt = team_prompt
        self.member_contexts = member_contexts


class ResolvedRootContext:
    """Everything needed to let Agno itself pick which Team handles a
    request, fully resolved from metadata. Used when a caller specifies
    only an AgentOS (no team_code) - every enabled Team under that
    AgentOS is resolved into its own ResolvedTeamContext (member agents,
    prompts, capabilities and all), and wrapped into a single "Root
    Team" whose members are Teams rather than Agents (Agno's
    team-of-teams pattern). The Root Team's own leader model decides
    which child Team(s) to delegate to at run time - no routing
    decision is made by platform code.
    """

    __slots__ = ("agent_os", "root_prompt", "team_contexts")

    def __init__(
        self,
        agent_os: AgentOS,
        root_prompt: str,
        team_contexts: list[ResolvedTeamContext],
    ) -> None:
        self.agent_os = agent_os
        self.root_prompt = root_prompt
        self.team_contexts = team_contexts


class AgnoRuntimeEngine:
    """Resolves metadata into runtime context and executes Agno agents."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.agent_os_repo = AgentOSRepository(session)
        self.team_repo = TeamRepository(session)
        self.agent_repo = AgentRepository(session)
        self.capability_service = CapabilityService(session)
        self.prompt_service = PromptCompositionService(session)
        self.model_service = ModelResolutionService(session)
        self.tool_builder = ToolCatalogBuilder()

    async def resolve_context(
        self,
        agent_os_code: str,
        team_code: str,
        agent_code: str | None,
    ) -> ResolvedRuntimeContext:
        agent_os = await self.agent_os_repo.get_by_code(agent_os_code)
        if agent_os is None or not agent_os.enabled:
            raise RuntimeExecutionError(f"AgentOS '{agent_os_code}' not found or disabled")

        team = await self.team_repo.get_by_code(agent_os.id, team_code)
        if team is None or not team.enabled:
            raise RuntimeExecutionError(f"Team '{team_code}' not found or disabled under AgentOS '{agent_os_code}'")

        agent: Agent | None
        if agent_code:
            agent = await self.agent_repo.get_by_code(team.id, agent_code)
        else:
            agent = await self.agent_repo.get_first_enabled_in_team(team.id)

        if agent is None or not agent.enabled:
            raise RuntimeExecutionError(
                f"Agent '{agent_code or '<first-enabled>'}' not found or disabled under team '{team_code}'"
            )

        return await self._build_resolved_context(agent_os, team, agent)

    async def resolve_context_by_id(self, agent_id) -> ResolvedRuntimeContext:
        """Resolves an Agent (and its parent Team/AgentOS) directly by
        id rather than by human-facing code. Used by the Workflow engine
        (app/agno_runtime/workflow_engine.py), where each WorkflowStep
        already stores a stable agent_id - codes are only meaningful at
        the chat API boundary, not in stored workflow metadata.
        """
        agent = await self.agent_repo.get(agent_id)
        if agent is None or not agent.enabled:
            raise RuntimeExecutionError(f"Agent {agent_id} not found or disabled")

        team = await self.team_repo.get(agent.team_id)
        if team is None or not team.enabled:
            raise RuntimeExecutionError(f"Team {agent.team_id} not found or disabled")

        agent_os = await self.agent_os_repo.get(team.agent_os_id)
        if agent_os is None or not agent_os.enabled:
            raise RuntimeExecutionError(f"AgentOS {team.agent_os_id} not found or disabled")

        return await self._build_resolved_context(agent_os, team, agent)

    async def _build_resolved_context(
        self, agent_os: AgentOS, team: Team, agent: Agent
    ) -> ResolvedRuntimeContext:
        final_prompt = await self.prompt_service.compose(agent_os, team, agent)
        capability_result = await self.capability_service.resolve(agent_os.id, team.id, agent.id)

        return ResolvedRuntimeContext(
            agent_os=agent_os,
            team=team,
            agent=agent,
            final_prompt=final_prompt,
            effective_capabilities=capability_result.effective_capabilities,
        )

    async def resolve_team_context_by_id(self, team_id) -> ResolvedTeamContext:
        """Resolves a Team (and every enabled Agent member within it) for
        a full Team execution - used by the Workflow engine for
        step_type=TEAM steps, and by the chat entrypoint when a caller
        explicitly names a team_code (see resolve_dispatch_context).
        Reuses resolve_context_by_id for each member agent so prompt
        composition and capability intersection are computed identically
        to how a single-agent chat turn would resolve them - no
        duplicated logic.
        """
        team = await self.team_repo.get(team_id)
        if team is None or not team.enabled:
            raise RuntimeExecutionError(f"Team {team_id} not found or disabled")

        agent_os = await self.agent_os_repo.get(team.agent_os_id)
        if agent_os is None or not agent_os.enabled:
            raise RuntimeExecutionError(f"AgentOS {team.agent_os_id} not found or disabled")

        return await self._build_team_context(agent_os, team)

    async def resolve_team_context_by_code(self, agent_os_code: str, team_code: str) -> ResolvedTeamContext:
        """Same as resolve_team_context_by_id, but looked up by the
        human-facing codes used at the chat/AG-UI API boundary. This is
        the path taken when a caller explicitly names both agent_os_code
        and team_code: the Team itself still auto-coordinates whichever
        of its member Agents the leader model picks - platform code only
        resolves *which Team*, never which Agent within it.
        """
        agent_os = await self.agent_os_repo.get_by_code(agent_os_code)
        if agent_os is None or not agent_os.enabled:
            raise RuntimeExecutionError(f"AgentOS '{agent_os_code}' not found or disabled")

        team = await self.team_repo.get_by_code(agent_os.id, team_code)
        if team is None or not team.enabled:
            raise RuntimeExecutionError(f"Team '{team_code}' not found or disabled under AgentOS '{agent_os_code}'")

        return await self._build_team_context(agent_os, team)

    async def _build_team_context(self, agent_os: AgentOS, team: Team) -> ResolvedTeamContext:
        """Shared resolution body for a single Team, factored out of
        resolve_team_context_by_id/_by_code so resolve_root_context can
        reuse it once per enabled Team under an AgentOS without
        duplicating the member-listing/prompt-composition logic."""
        members, _total = await self.agent_repo.list(team_id=team.id, limit=200)
        enabled_members = [m for m in members if m.enabled]
        if not enabled_members:
            raise RuntimeExecutionError(f"Team {team.id} has no enabled member agents")

        member_contexts = [
            await self._build_resolved_context(agent_os, team, member) for member in enabled_members
        ]

        team_prompt = await self.prompt_service.compose_team_only(agent_os, team)

        return ResolvedTeamContext(
            agent_os=agent_os,
            team=team,
            team_prompt=team_prompt,
            member_contexts=member_contexts,
        )

    async def resolve_root_context(self, agent_os_code: str) -> ResolvedRootContext:
        """Resolves every enabled Team under an AgentOS into its own
        ResolvedTeamContext, for the case where a caller names only an
        agent_os_code (no team_code): Agno's own Root Team leader - not
        platform code - decides which child Team(s) handle the request.
        See resolve_dispatch_context for the entrypoint that chooses
        between this and resolve_team_context_by_code.
        """
        agent_os = await self.agent_os_repo.get_by_code(agent_os_code)
        if agent_os is None or not agent_os.enabled:
            raise RuntimeExecutionError(f"AgentOS '{agent_os_code}' not found or disabled")

        teams, _total = await self.team_repo.list(agent_os_id=agent_os.id, limit=200)
        enabled_teams = [t for t in teams if t.enabled]
        if not enabled_teams:
            raise RuntimeExecutionError(f"AgentOS '{agent_os_code}' has no enabled teams")

        team_contexts = [await self._build_team_context(agent_os, team) for team in enabled_teams]

        # AgentOS has no team_code in this branch, so there is no
        # team-level prompt to fold in - the Root Team's own
        # instructions are composed from AgentOS-level prompt material
        # only, via the same PromptCompositionService used everywhere
        # else, so routing instructions stay centrally editable rather
        # than hardcoded here.
        root_prompt = await self.prompt_service.compose_root_only(agent_os)

        return ResolvedRootContext(
            agent_os=agent_os,
            root_prompt=root_prompt,
            team_contexts=team_contexts,
        )

    async def resolve_dispatch_context(
        self, agent_os_code: str, team_code: str | None = None
    ) -> ResolvedTeamContext | ResolvedRootContext:
        """Single entrypoint for the chat/AG-UI boundary, implementing
        the dispatch rule: team_code given -> resolve that Team directly
        (it auto-coordinates its own Agents); team_code omitted ->
        resolve every Team under the AgentOS and let the Root Team's
        leader model decide which one(s) to use. Callers (e.g. the AG-UI
        route / team_factory) branch on isinstance() of the return value
        to call _build_agno_team vs _build_agno_root_team."""
        if team_code:
            return await self.resolve_team_context_by_code(agent_os_code, team_code)
        return await self.resolve_root_context(agent_os_code)

    async def _build_agno_agent(
        self, ctx: ResolvedRuntimeContext, mcp_tools, *, user_id: str | None = None
    ) -> AgnoAgent:
        model_entry = await self.model_service.resolve_registry_entry(
            agent_model_id=ctx.agent.model_id,
            agent_os_default_model_id=ctx.agent_os.default_model_id,
        )
        agno_model = self.model_service.build_agno_model(
            model_entry, temperature_override=ctx.agent.temperature
        )

        # Agentic memory (LLM self-extracts facts/preferences after each
        # run, ChatGPT-memory style) is only meaningful when we know
        # *whose* memory it is - chat requests without a user_id skip it
        # entirely rather than writing anonymous, unattributable memories.
        memory = None
        enable_user_memories = False
        if user_id:
            memory = Memory(model=agno_model, db=PlatformMemoryDb(ctx.agent.id))
            enable_user_memories = True
        return AgnoAgent(
            model=agno_model,
            name=ctx.agent.name,
            agent_id=str(ctx.agent.id),
            instructions=ctx.final_prompt,
            tools=[mcp_tools] if mcp_tools is not None else [],
            memory=memory,
            enable_user_memories=enable_user_memories,
            storage=build_agent_storage(),
            add_history_to_messages=True,
            num_history_runs=10,
            show_tool_calls=True,
            markdown=True,
            add_datetime_to_instructions=True,
        )

    async def run(
        self,
        ctx: ResolvedRuntimeContext,
        message: str,
        *,
        session_id: str,
        user_id: str | None = None,
    ) -> str:
        """Non-streaming execution. Returns the final text response.

        Opens an MCP session scoped to ctx.effective_capabilities for the
        duration of this single run, then closes it - the tool catalog is
        always rebuilt fresh from current metadata + the Gateway's live
        tools/list, never cached across runs.
        """
        mcp_session = self.tool_builder.build(ctx.effective_capabilities)
        try:
            async with mcp_session as session:
                agno_agent = await self._build_agno_agent(ctx, session.tools, user_id=user_id)
                response = await agno_agent.arun(
                    message,
                    session_id=session_id,
                    user_id=user_id,
                    stream=False,
                )
        except Exception as exc:  # noqa: BLE001
            logger.error("agno_run_failed", error=str(exc), agent_code=ctx.agent.code)
            raise RuntimeExecutionError(f"Agno agent execution failed: {exc}") from exc

        content = getattr(response, "content", None)
        if content is None:
            content = str(response)
        return content

    async def run_stream(
        self,
        ctx: ResolvedRuntimeContext,
        message: str,
        *,
        session_id: str,
        user_id: str | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Streaming execution. Yields normalized event dicts as Agno
        surfaces RunResponseEvents, mapped onto the platform's EventType
        vocabulary. Same MCP session lifecycle as run() above, held open
        for the duration of the streamed run."""
        mcp_session = self.tool_builder.build(ctx.effective_capabilities)
        try:
            async with mcp_session as session:
                agno_agent = await self._build_agno_agent(ctx, session.tools, user_id=user_id)
                stream = await agno_agent.arun(
                    message,
                    session_id=session_id,
                    user_id=user_id,
                    stream=True,
                    stream_intermediate_steps=True,
                )
                async for event in stream:
                    event_name = getattr(event, "event", None) or type(event).__name__
                    mapped_type = _AGNO_EVENT_MAP.get(event_name, "agent_response")
                    payload: dict[str, Any] = {"agno_event": event_name}

                    content = getattr(event, "content", None)
                    if content:
                        payload["content"] = content
                    payload.update(_build_stream_payload(event_name, payload))
                    tool_calls = getattr(event, "tools", None)
                    if tool_calls:
                        payload["tools"] = tool_calls

                    yield {"event_type": mapped_type, "payload": payload}
        except Exception as exc:  # noqa: BLE001
            logger.error("agno_run_stream_failed", error=str(exc), agent_code=ctx.agent.code)
            yield {"event_type": "error", "payload": {"error": str(exc)}}
            raise RuntimeExecutionError(f"Agno agent streaming execution failed: {exc}") from exc

    async def _build_agno_team(
        self,
        ctx: ResolvedTeamContext,
        exit_stack: AsyncExitStack,
        *,
        user_id: str | None = None,
    ) -> AgnoTeam:
        """Builds a live agno.team.Team with every enabled member fully
        constructed (model, prompt, tools, memory) - reusing
        _build_agno_agent for each member, so a Team run resolves
        prompts/capabilities/memory identically to how each member would
        resolve them in a standalone chat turn. Each member's MCP
        session is opened via `exit_stack`, which the caller (run_team /
        run_team_stream) closes once the whole Team run completes - all
        member sessions stay open for the team run's full duration, since
        agno.team.Team may delegate to any member at any point during
        its own reasoning loop.
        """
        member_agents: list[AgnoAgent] = []
        for member_ctx in ctx.member_contexts:
            mcp_session = self.tool_builder.build(member_ctx.effective_capabilities)
            session = await exit_stack.enter_async_context(mcp_session)
            member_agents.append(
                await self._build_agno_agent(member_ctx, session.tools, user_id=user_id)
            )

        # The Team coordinator's own model: Teams have no model_id of
        # their own in the existing schema (intentionally not modified
        # per "DO NOT rewrite existing AgentOS architecture") - falls
        # back to the AgentOS default model, same as any Agent that
        # doesn't set its own model_id.
        model_entry = await self.model_service.resolve_registry_entry(
            agent_model_id=None,
            agent_os_default_model_id=ctx.agent_os.default_model_id,
        )
        team_model = self.model_service.build_agno_model(model_entry)

        return AgnoTeam(
            members=member_agents,
            mode="coordinate",
            model=team_model,
            name=ctx.team.name,
            team_id=str(ctx.team.id),
            instructions=ctx.team_prompt,
            show_tool_calls=True,
            markdown=True,
            add_datetime_to_instructions=True,
        )

    async def run_team(
        self,
        ctx: ResolvedTeamContext,
        message: str,
        *,
        session_id: str,
        user_id: str | None = None,
    ) -> str:
        """Non-streaming Team execution. Returns the final text response.

        Opens one MCP session per enabled member agent (all held open
        for the duration of this single run via an AsyncExitStack, since
        agno.team.Team's coordinator may delegate to any member at any
        point), then closes all of them together.
        """
        async with AsyncExitStack() as exit_stack:
            try:
                agno_team = await self._build_agno_team(ctx, exit_stack, user_id=user_id)
                response = await agno_team.arun(
                    message,
                    session_id=session_id,
                    user_id=user_id,
                    stream=False,
                )
            except Exception as exc:  # noqa: BLE001
                logger.error("agno_team_run_failed", error=str(exc), team_code=ctx.team.code)
                raise RuntimeExecutionError(f"Agno team execution failed: {exc}") from exc

        content = getattr(response, "content", None)
        if content is None:
            content = str(response)
        return content

    async def run_team_stream(
        self,
        ctx: ResolvedTeamContext,
        message: str,
        *,
        session_id: str,
        user_id: str | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Streaming Team execution. Yields normalized event dicts as
        Agno surfaces TeamRunResponseEvents, mapped onto the platform's
        EventType vocabulary via _AGNO_TEAM_EVENT_MAP. Same multi-session
        MCP lifecycle as run_team()  above."""
        # Agno's `atransfer_task_to_member` tool (used internally for
        # delegation) forwards a member's own stream events verbatim
        # instead of wrapping them as intermediate events. When a member
        # is itself an agno.team.Team (team-of-teams, see
        # _build_agno_root_team), that leaked event carries the exact
        # same event name ("TeamRunResponseContent") as this team's own
        # final content event - the only thing that tells them apart is
        # `team_id`, which on a leaked event is the *member* team's id,
        # not this team's. Without this check, both the member's own
        # answer and this team's relayed/synthesized answer get
        # collected as assistant content and concatenated, producing a
        # duplicated final message.
        own_team_id = str(ctx.team.id)
        async with AsyncExitStack() as exit_stack:
            try:
                agno_team = await self._build_agno_team(ctx, exit_stack, user_id=user_id)
                stream = await agno_team.arun(
                    message,
                    session_id=session_id,
                    user_id=user_id,
                    stream=True,
                    stream_intermediate_steps=True,
                )
                async for event in stream:
                    event_name = getattr(event, "event", None) or type(event).__name__
                    mapped_type = _AGNO_TEAM_EVENT_MAP.get(event_name, "agent_response")
                    payload: dict[str, Any] = {"agno_event": event_name}

                    content = getattr(event, "content", None)
                    if content:
                        payload["content"] = content
                        payload["is_assistant_content"] = (
                            event_name in _ASSISTANT_CONTENT_TEAM_EVENT_NAMES
                            and getattr(event, "team_id", None) == own_team_id
                        )
                    tool_calls = getattr(event, "tools", None)
                    if tool_calls:
                        payload["tools"] = tool_calls

                    yield {"event_type": mapped_type, "payload": payload}
            except Exception as exc:  # noqa: BLE001
                logger.error("agno_team_run_stream_failed", error=str(exc), team_code=ctx.team.code)
                yield {"event_type": "error", "payload": {"error": str(exc)}}
                raise RuntimeExecutionError(f"Agno team streaming execution failed: {exc}") from exc

    async def _build_agno_root_team(
        self,
        ctx: ResolvedRootContext,
        exit_stack: AsyncExitStack,
        *,
        mode: Literal["route", "coordinate", "collaborate"] = "route",
        user_id: str | None = None,
    ) -> AgnoTeam:
        """Builds the "Root Team" for an AgentOS: a Team whose members
        are other, fully-constructed Teams (Agno's team-of-teams
        pattern), so the Root Team's own leader model - not platform
        code - decides which child Team handles a given request.

        Every child Team is built eagerly via _build_agno_team (reusing
        the exact same per-member MCP session / model / memory wiring as
        an explicit team_code call would use), so behavior is identical
        whether a Team is reached through auto-routing or by name. This
        means every enabled Agent's MCP session under this AgentOS gets
        opened for the run - no LLM calls happen for child Teams the
        Root Team's leader doesn't end up delegating to, but the session
        setup cost is paid regardless. If that becomes a bottleneck for
        AgentOS instances with many Teams, the fix is lazy per-member
        construction (Agno supports passing a callable for `members`,
        evaluated at run start) rather than restructuring this method.

        mode defaults to TeamMode.route (pick exactly one child Team and
        hand off fully) since that matches "os quyết định team nào" as a
        single dispatch decision; pass TeamMode.coordinate instead if an
        AgentOS's Teams are meant to be combinable within one answer.
        """
        member_teams: list[AgnoTeam] = [
            await self._build_agno_team(team_ctx, exit_stack, user_id=user_id)
            for team_ctx in ctx.team_contexts
        ]

        model_entry = await self.model_service.resolve_registry_entry(
            agent_model_id=None,
            agent_os_default_model_id=ctx.agent_os.default_model_id,
        )
        root_model = self.model_service.build_agno_model(model_entry)

        return AgnoTeam(
            members=member_teams,
            mode=mode,
            model=root_model,
            name=f"{ctx.agent_os.name} Router",
            team_id=f"root-{ctx.agent_os.id}",
            instructions=ctx.root_prompt,
            show_tool_calls=True,
            markdown=True,
            add_datetime_to_instructions=True,
        )

    async def run_root(
        self,
        ctx: ResolvedRootContext,
        message: str,
        *,
        session_id: str,
        mode: Literal["route", "coordinate", "collaborate"] = "route",
        user_id: str | None = None,
    ) -> str:
        """Non-streaming execution for the "only agent_os_code given"
        case: builds the Root Team (all child Teams, all their member
        Agents, all MCP sessions) and lets Agno's own leader model decide
        routing. Same single-AsyncExitStack lifecycle as run_team()."""
        async with AsyncExitStack() as exit_stack:
            try:
                agno_root_team = await self._build_agno_root_team(
                    ctx, exit_stack, mode=mode, user_id=user_id
                )
                response = await agno_root_team.arun(
                    message,
                    session_id=session_id,
                    user_id=user_id,
                    stream=False,
                )
            except Exception as exc:  # noqa: BLE001
                logger.error("agno_root_run_failed", error=str(exc), agent_os_code=ctx.agent_os.code)
                raise RuntimeExecutionError(f"Agno root team execution failed: {exc}") from exc

        content = getattr(response, "content", None)
        if content is None:
            content = str(response)
        return content

    async def run_root_stream(
        self,
        ctx: ResolvedRootContext,
        message: str,
        *,
        session_id: str,
        mode: Literal["route", "coordinate", "collaborate"] = "route",
        user_id: str | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Streaming counterpart of run_root(). Reuses
        _AGNO_TEAM_EVENT_MAP since the Root Team is still an
        agno.team.Team under the hood (its members merely happen to be
        Teams rather than Agents) - observability consumers see the same
        EventType vocabulary regardless of how many routing layers were
        involved.

        IMPORTANT: the Root Team's members are themselves full
        agno.team.Team objects (team-of-teams). Agno's delegation tool
        (`atransfer_task_to_member`) forwards a delegated-to member's own
        stream events verbatim rather than wrapping them as intermediate
        events - so when that member is a Team, its own final content
        event is emitted with the *same* event name
        ("TeamRunResponseContent") as this Root Team's own final/relayed
        content event (mode="route" -> respond_directly=True ->
        show_result relays the child Team's answer as this team's own
        content). The only field that distinguishes "the child team's
        own answer, leaked through the tool call" from "this Root Team's
        own final answer" is `team_id`. Without filtering on it, both
        get collected as assistant content and concatenated in
        ChatService, producing a duplicated final message - this is
        exactly the bug where selecting only agent_os (no team) yields a
        doubled-up answer while selecting a team explicitly does not
        (there, the member is a plain Agent, whose native event name
        "RunResponseContent" doesn't collide with "TeamRunResponseContent"
        in the first place).
        """
        own_team_id = f"root-{ctx.agent_os.id}"
        async with AsyncExitStack() as exit_stack:
            try:
                agno_root_team = await self._build_agno_root_team(
                    ctx, exit_stack, mode=mode, user_id=user_id
                )
                stream = await agno_root_team.arun(
                    message,
                    session_id=session_id,
                    user_id=user_id,
                    stream=True,
                    stream_intermediate_steps=True,
                )
                async for event in stream:
                    event_name = getattr(event, "event", None) or type(event).__name__
                    mapped_type = _AGNO_TEAM_EVENT_MAP.get(event_name, "agent_response")
                    payload: dict[str, Any] = {"agno_event": event_name}

                    content = getattr(event, "content", None)
                    if content:
                        payload["content"] = content
                        payload["is_assistant_content"] = (
                            event_name in _ASSISTANT_CONTENT_TEAM_EVENT_NAMES
                            and getattr(event, "team_id", None) == own_team_id
                        )
                    tool_calls = getattr(event, "tools", None)
                    if tool_calls:
                        payload["tools"] = tool_calls

                    yield {"event_type": mapped_type, "payload": payload}
            except Exception as exc:  # noqa: BLE001
                logger.error("agno_root_run_stream_failed", error=str(exc), agent_os_code=ctx.agent_os.code)
                yield {"event_type": "error", "payload": {"error": str(exc)}}
                raise RuntimeExecutionError(f"Agno root team streaming execution failed: {exc}") from exc