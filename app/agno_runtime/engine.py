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
    Execute Knowledge Skills assigned to the Agent, fold results into prompt
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
were already determined (by capability_service) to be in scope, and
forward whichever auth headers were already captured (by auth_context)
to the Knowledge Platform via KnowledgeSkillService, exactly the way it
forwards them to MCP Gateway.

MCP-over-SSE note: the MCP session (a live connection to MCP Gateway's
MCP server) must stay open for the entire duration of one agent run,
since Agno calls tools on it lazily as the LLM decides to use them. It
is opened right before `arun()` and closed right after, in `run()` /
`run_stream()` below - never held open across chat turns, keeping the
runtime stateless between requests.

Knowledge Skill note: unlike MCP tools (which the LLM decides whether to
call), Knowledge Skill retrieval happens eagerly, once per run, before
the Agno Agent/Team is even constructed - the retrieved context is
folded directly into the Agent's `instructions` as a "Knowledge Context"
section (see app/knowledge/mapper.py::render_context), not exposed as a
callable tool. This matches the spec's "the Agent should not know how
retrieval is performed" requirement: from the Agent's point of view,
relevant knowledge is simply already part of its instructions.

AgentX v2 additions (all no-ops unless the corresponding Skill/flag is
present - see app/businessobjects/service.py and app/uiaction/service.py):

  - Business Object tools (lookup_business_object / validate_business_object):
    lazy, LLM-invoked tools, selective per-Agent via a Skill whose
    config={"businessObjectLookup": true} - mirrors the Knowledge Skill's
    "build tool or None" shape exactly, added alongside `source_tool` in
    _build_agno_agent().

  - UI Action tool (propose_ui_action): lazy, LLM-invoked tool, selective
    per-Agent via a Skill with skill_type=UI. Each call accumulates into
    a UIActionPlanCollector; collectors are tracked on this engine
    instance (`self._ui_action_collectors`), never on the Agno objects
    themselves, since AgnoRuntimeEngine is already instantiated fresh
    per request (see ChatService.__init__) - this keeps the wiring
    entirely local to this module without needing to attach ad-hoc
    attributes to Agno's own Agent/Team classes. After a run completes,
    `run()`/`run_team()`/`run_root()` expose the aggregated plan via
    `self.last_ui_action_plan`; the streaming counterparts
    (`run_stream()`/`run_team_stream()`/`run_root_stream()`) yield one
    additional `ui_action_plan` event at the end of the stream when any
    actions were proposed.

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

from app.agno_runtime.agent_storage import build_agent_storage, build_team_storage
from app.agno_runtime.explicit_memory import MEMORY_INSTRUCTIONS_SECTION, build_remember_tool
from app.agno_runtime.memory_db import PlatformMemoryDb
from app.agno_runtime.tool_adapter import ToolCatalogBuilder
from app.businessobjects.service import BusinessObjectSkillService
from app.core.exceptions import RuntimeExecutionError
from app.core.logging import get_logger
from app.knowledge.service import KnowledgeSkillService
from app.models.hierarchy import Agent, AgentOS, Team
from app.repositories.hierarchy_repository import AgentOSRepository, AgentRepository, TeamRepository
from app.services.capability_service import CapabilityService
from app.services.model_service import ModelResolutionService
from app.services.prompt_service import PromptCompositionService
from app.uiaction.models import UIActionPlan
from app.uiaction.service import UIActionPlanCollector, UIActionSkillService
from app.workflowskill.service import WorkflowSkillService

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


def _dedupe_self_concatenated(text: str) -> str:
    """Some Agno completion events (observed on TeamRunCompleted in
    coordinate mode after a leader relays a single delegated member's
    answer) surface `content` as the exact same final answer
    concatenated with itself, no separator - e.g.
    "X sinh ngay 1992-08-11.X sinh ngay 1992-08-11." instead of the
    string once. This detects that precise self-concatenation pattern
    (the string is exactly two identical halves) and collapses it to a
    single copy.

    Deliberately narrow: it only fires when the two halves are
    byte-for-byte identical, so it can never truncate a legitimately
    repetitive answer that merely happens to repeat a word or phrase -
    only an answer that is the *entire* text duplicated verbatim.
    """
    if not text:
        return text
    length = len(text)
    if length % 2 != 0:
        return text
    half = length // 2
    first_half, second_half = text[:half], text[half:]
    if first_half and first_half == second_half:
        return first_half
    return text


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
        self.knowledge_service = KnowledgeSkillService(session)
        # --- AgentX v2 ---
        self.business_object_service = BusinessObjectSkillService(session)
        self.ui_action_service = UIActionSkillService(session)
        self.workflow_skill_service = WorkflowSkillService(session)
        self._ui_action_collectors: list[UIActionPlanCollector] = []
        self.last_ui_action_plan: UIActionPlan | None = None

    def _reset_ui_action_collectors(self) -> None:
        self._ui_action_collectors = []
        self.last_ui_action_plan = None

    def _aggregate_ui_action_plan(self, *, run_id: str | None = None) -> UIActionPlan:
        actions = []
        for collector in self._ui_action_collectors:
            actions.extend(collector.actions)
        actions.sort(key=lambda a: a.executionOrder)
        return UIActionPlan(runId=run_id, actions=actions)

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

    async def _resolve_instructions(self, ctx: ResolvedRuntimeContext, message: str) -> str:
        """Folds any Knowledge Skill(s) assigned to this Agent into its
        final prompt, per docs/Knowledge.md: Knowledge is executed as
        just another Skill, not embedded into Agent. The Agent never
        sees how retrieval happened - only the resulting "Knowledge
        Context" section prepended to its instructions. A Knowledge
        Skill failure never aborts the run (see
        KnowledgeSkillService.execute_for_agent) - it degrades to simply
        contributing no context.
        """
        knowledge_context = await self.knowledge_service.execute_for_agent(ctx.agent.id, message)
        if not knowledge_context:
            return ctx.final_prompt
        return f"{knowledge_context}\n\n{ctx.final_prompt}"

    async def _build_agno_agent(
        self,
        ctx: ResolvedRuntimeContext,
        mcp_tools,
        *,
        message: str,
        session_id: str,
        user_id: str | None = None,
    ) -> AgnoAgent:
        model_entry = await self.model_service.resolve_registry_entry(
            agent_model_id=ctx.agent.model_id,
            agent_os_default_model_id=ctx.agent_os.default_model_id,
        )
        agno_model = self.model_service.build_agno_model(
            model_entry, temperature_override=ctx.agent.temperature
        )

        instructions = await self._resolve_instructions(ctx, message)
        source_tool = await self.knowledge_service.build_source_lookup_tool(ctx.agent.id)

        # --- AgentX v2: Business Object tools (lazy, selective per-Agent
        # via Skill config={"businessObjectLookup": true} - see
        # app/businessobjects/service.py) ---
        bo_lookup_tool = await self.business_object_service.build_lookup_tool(ctx.agent.id)
        bo_validate_tool = await self.business_object_service.build_validate_tool(ctx.agent.id)

        # --- AgentX v2: UI Action tool (lazy, selective per-Agent via a
        # Skill with skill_type=UI - see app/uiaction/service.py). The
        # collector is tracked on THIS engine instance, never on the
        # Agno object, so no ad-hoc attribute is ever set on Agno's own
        # classes - see class docstring for rationale. ---
        ui_action_collector = UIActionPlanCollector()
        ui_action_tool = await self.ui_action_service.build_action_tool(ctx.agent.id, ui_action_collector)
        if ui_action_tool is not None:
            self._ui_action_collectors.append(ui_action_collector)

        # --- AgentX v2: Workflow trigger tools (SkillType.WORKFLOW,
        # previously reserved/unimplemented - see
        # app/workflowskill/service.py). One tool per WORKFLOW Skill
        # assigned to this Agent, each scoped to exactly the Workflow
        # named in that Skill's config - never a generic "trigger any
        # workflow" tool. ---
        workflow_trigger_tools = await self.workflow_skill_service.build_trigger_tools(
            ctx.agent.id, agent_os_id=ctx.agent_os.id, session_id=session_id, user_id=user_id
        )

        tools: list[Any] = []
        if mcp_tools is not None:
            tools.append(mcp_tools)
        if source_tool is not None:
            tools.append(source_tool)
        if bo_lookup_tool is not None:
            tools.append(bo_lookup_tool)
        if bo_validate_tool is not None:
            tools.append(bo_validate_tool)
        if ui_action_tool is not None:
            tools.append(ui_action_tool)
        tools.extend(workflow_trigger_tools)

        # Agentic memory (LLM self-extracts facts/preferences after each
        # run, ChatGPT-memory style) is only meaningful when we know
        # *whose* memory it is - chat requests without a user_id skip it
        # entirely rather than writing anonymous, unattributable memories.
        memory = None
        enable_user_memories = False
        remember_tool = None
        if user_id:
            memory = Memory(model=agno_model, db=PlatformMemoryDb(ctx.agent.id))
            enable_user_memories = True
            # --- AgentX v2: deterministic "remember" path, complementing
            # (not replacing) Agno's own automatic extraction above - see
            # app/agno_runtime/explicit_memory.py for the rationale. Only
            # built when user_id is present, same guard as the automatic
            # path, since remembering is meaningless without knowing
            # whose memory it is. ---
            remember_tool = build_remember_tool(self.session, ctx.agent.id, user_id)
            instructions = f"{instructions}\n\n{MEMORY_INSTRUCTIONS_SECTION}"

        if remember_tool is not None:
            tools.append(remember_tool)

        return AgnoAgent(
            model=agno_model,
            name=ctx.agent.name,
            agent_id=str(ctx.agent.id),
            instructions=instructions,
            tools=tools,
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
        tools/list, never cached across runs. Any Knowledge Skills
        assigned to this Agent are executed once, eagerly, before the
        Agno Agent is even constructed (see _resolve_instructions).

        AgentX v2: after this call, `self.last_ui_action_plan` holds the
        UIActionPlan aggregated from any propose_ui_action tool calls
        made during this run (empty plan if none) - callers that want to
        forward it to the frontend can read it right after awaiting run().
        """
        self._reset_ui_action_collectors()
        mcp_session = self.tool_builder.build(ctx.effective_capabilities)
        try:
            async with mcp_session as session:
                agno_agent = await self._build_agno_agent(
                    ctx, session.tools, message=message, session_id=session_id, user_id=user_id
                )
                response = await agno_agent.arun(
                    message,
                    session_id=session_id,
                    user_id=user_id,
                    stream=False,
                )
        except Exception as exc:  # noqa: BLE001
            logger.error("agno_run_failed", error=str(exc), agent_code=ctx.agent.code)
            raise RuntimeExecutionError(f"Agno agent execution failed: {exc}") from exc

        self.last_ui_action_plan = self._aggregate_ui_action_plan(run_id=session_id)

        content = getattr(response, "content", None)
        if content is None:
            content = str(response)
        return _dedupe_self_concatenated(content)

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
        for the duration of the streamed run.

        AgentX v2: if any propose_ui_action tool calls were made during
        this run, one additional event is yielded after the stream
        completes: {"event_type": "ui_action_plan", "payload": {
        "is_assistant_content": False, "ui_action_plan": <UIActionPlan
        dict>}} - existing consumers that don't recognize this event_type
        can safely ignore it (is_assistant_content=False means it's never
        folded into assistant text)."""
        self._reset_ui_action_collectors()
        mcp_session = self.tool_builder.build(ctx.effective_capabilities)
        try:
            async with mcp_session as session:
                agno_agent = await self._build_agno_agent(
                    ctx, session.tools, message=message, session_id=session_id, user_id=user_id
                )
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
                        payload["content"] = _dedupe_self_concatenated(content)
                    payload.update(_build_stream_payload(event_name, payload))
                    tool_calls = getattr(event, "tools", None)
                    if tool_calls:
                        payload["tools"] = tool_calls

                    yield {"event_type": mapped_type, "payload": payload}
        except Exception as exc:  # noqa: BLE001
            logger.error("agno_run_stream_failed", error=str(exc), agent_code=ctx.agent.code)
            yield {"event_type": "error", "payload": {"error": str(exc)}}
            raise RuntimeExecutionError(f"Agno agent streaming execution failed: {exc}") from exc

        self.last_ui_action_plan = self._aggregate_ui_action_plan(run_id=session_id)
        if self.last_ui_action_plan.actions:
            yield {
                "event_type": "ui_action_plan",
                "payload": {
                    "is_assistant_content": False,
                    "ui_action_plan": self.last_ui_action_plan.model_dump(),
                },
            }

    async def _build_agno_team(
        self,
        ctx: ResolvedTeamContext,
        exit_stack: AsyncExitStack,
        *,
        message: str,
        session_id: str,
        user_id: str | None = None,
    ) -> AgnoTeam:
        """Builds a live agno.team.Team with every enabled member fully
        constructed (model, prompt, tools, memory, Knowledge context) -
        reusing _build_agno_agent for each member, so a Team run resolves
        prompts/capabilities/memory/knowledge identically to how each
        member would resolve them in a standalone chat turn. Each
        member's MCP session is opened via `exit_stack`, which the
        caller (run_team / run_team_stream) closes once the whole Team
        run completes - all member sessions stay open for the team run's
        full duration, since agno.team.Team may delegate to any member
        at any point during its own reasoning loop.

        AgentX v2: each member's Business Object / UI Action tools are
        wired in transparently via _build_agno_agent - no team-specific
        code needed here, since _ui_action_collectors is tracked on this
        engine instance and accumulates across every member built during
        this call.
        """
        member_agents: list[AgnoAgent] = []
        for member_ctx in ctx.member_contexts:
            mcp_session = self.tool_builder.build(member_ctx.effective_capabilities)
            session = await exit_stack.enter_async_context(mcp_session)
            member_agents.append(
                await self._build_agno_agent(
                    member_ctx, session.tools, message=message, session_id=session_id, user_id=user_id
                )
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
            storage=build_team_storage(),
            add_history_to_messages=True,
            num_history_runs=10,
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

        AgentX v2: `self.last_ui_action_plan` is populated exactly like
        in run(), aggregated across every member that proposed actions.
        """
        self._reset_ui_action_collectors()
        async with AsyncExitStack() as exit_stack:
            try:
                agno_team = await self._build_agno_team(
                    ctx, exit_stack, message=message, session_id=session_id, user_id=user_id
                )
                response = await agno_team.arun(
                    message,
                    session_id=session_id,
                    user_id=user_id,
                    stream=False,
                )
            except Exception as exc:  # noqa: BLE001
                logger.error("agno_team_run_failed", error=str(exc), team_code=ctx.team.code)
                raise RuntimeExecutionError(f"Agno team execution failed: {exc}") from exc

        self.last_ui_action_plan = self._aggregate_ui_action_plan(run_id=session_id)

        content = getattr(response, "content", None)
        if content is None:
            content = str(response)
        return _dedupe_self_concatenated(content)

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
        MCP lifecycle as run_team()  above.

        AgentX v2: same trailing `ui_action_plan` event as run_stream(),
        aggregated across every member."""
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
        self._reset_ui_action_collectors()
        async with AsyncExitStack() as exit_stack:
            try:
                agno_team = await self._build_agno_team(
                    ctx, exit_stack, message=message, session_id=session_id, user_id=user_id
                )
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
                        payload["content"] = _dedupe_self_concatenated(content)
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

        self.last_ui_action_plan = self._aggregate_ui_action_plan(run_id=session_id)
        if self.last_ui_action_plan.actions:
            yield {
                "event_type": "ui_action_plan",
                "payload": {
                    "is_assistant_content": False,
                    "ui_action_plan": self.last_ui_action_plan.model_dump(),
                },
            }

    async def _build_agno_root_team(
        self,
        ctx: ResolvedRootContext,
        exit_stack: AsyncExitStack,
        *,
        message: str,
        session_id: str,
        mode: Literal["route", "coordinate", "collaborate"] = "route",
        user_id: str | None = None,
    ) -> AgnoTeam:
        """Builds the "Root Team" for an AgentOS: a Team whose members
        are other, fully-constructed Teams (Agno's team-of-teams
        pattern), so the Root Team's own leader model - not platform
        code - decides which child Team handles a given request.

        Every child Team is built eagerly via _build_agno_team (reusing
        the exact same per-member MCP session / model / memory / Knowledge
        wiring as an explicit team_code call would use), so behavior is
        identical whether a Team is reached through auto-routing or by
        name. This means every enabled Agent's MCP session (and any
        Knowledge Skill it has assigned) under this AgentOS gets
        exercised for the run - no LLM calls happen for child Teams the
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
            await self._build_agno_team(team_ctx, exit_stack, message=message, session_id=session_id, user_id=user_id)
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
            storage=build_team_storage(),
            add_history_to_messages=True,
            num_history_runs=10,
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
        routing. Same single-AsyncExitStack lifecycle as run_team().

        AgentX v2: `self.last_ui_action_plan` aggregated across every
        member of every child Team, same as run_team()."""
        self._reset_ui_action_collectors()
        async with AsyncExitStack() as exit_stack:
            try:
                agno_root_team = await self._build_agno_root_team(
                    ctx, exit_stack, message=message, session_id=session_id, mode=mode, user_id=user_id
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

        self.last_ui_action_plan = self._aggregate_ui_action_plan(run_id=session_id)

        content = getattr(response, "content", None)
        if content is None:
            content = str(response)
        return _dedupe_self_concatenated(content)

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

        AgentX v2: same trailing `ui_action_plan` event as
        run_team_stream(), aggregated across every member of every child
        Team."""
        own_team_id = f"root-{ctx.agent_os.id}"
        self._reset_ui_action_collectors()
        async with AsyncExitStack() as exit_stack:
            try:
                agno_root_team = await self._build_agno_root_team(
                    ctx, exit_stack, message=message, session_id=session_id, mode=mode, user_id=user_id
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
                        payload["content"] = _dedupe_self_concatenated(content)
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

        self.last_ui_action_plan = self._aggregate_ui_action_plan(run_id=session_id)
        if self.last_ui_action_plan.actions:
            yield {
                "event_type": "ui_action_plan",
                "payload": {
                    "is_assistant_content": False,
                    "ui_action_plan": self.last_ui_action_plan.model_dump(),
                },
            }