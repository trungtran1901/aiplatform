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

  - QUOTA METRICS: token usage accounting for streamed runs.

    IMPORTANT (agno==1.8.4): unlike some other Agno versions, the
    RunResponseEvent subclasses emitted during a streaming `arun(...,
    stream=True)` call (RunResponseContentEvent, ToolCallStartedEvent,
    ToolCallCompletedEvent, RunResponseCompletedEvent, and their Team
    equivalents) do NOT carry a `metrics` attribute in this version.
    Aggregated token usage only exists on the final `RunResponse` /
    `TeamRunResponse` object itself, reachable as `agno_agent.run_response`
    (or `agno_team.run_response` / `agno_root_team.run_response`) once
    the stream has been fully consumed.

    Earlier drafts of this module read `getattr(event, "metrics", None)`
    inside the per-event loop; on agno 1.8.4 that is always None, which
    is why QuotaService silently recorded 0 tokens for every streamed
    run. The fix: never look for `metrics` on individual stream events.
    Instead, after the `async for event in stream:` loop finishes (i.e.
    the run is fully done), read `metrics` once from the agent/team's
    own `run_response` attribute and emit a single extra
    `agent_completed` event carrying `payload["metrics"]`. This engine
    makes no decision about *what* to do with the metrics beyond
    surfacing them; QuotaService is solely responsible for enforcement/
    recording. ChatService's consumer should treat this as the single
    source of truth for a streamed run's usage and must not also sum
    metrics off of other events (there are none carrying metrics
    anymore, but this note is here so nobody re-adds per-event reading
    without re-checking the installed agno version first).

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


def _metrics_to_dict(metrics: Any) -> dict[str, Any] | None:
    """Normalizes whatever shape Agno's `run_response.metrics` happens to
    be (plain dict, a dataclass-like metrics object, or something
    exposing `.to_dict()` / `.model_dump()`) into a plain dict so
    downstream code (ChatService._extract_token_usage) can read it
    uniformly without needing to know the Agno-internal type. Returns
    None - never raises - for anything it can't confidently convert,
    since token accounting must never crash an otherwise-successful run.
    """
    if metrics is None:
        return None
    if isinstance(metrics, dict):
        return metrics
    to_dict = getattr(metrics, "to_dict", None)
    if callable(to_dict):
        try:
            result = to_dict()
            if isinstance(result, dict):
                return result
        except Exception:  # noqa: BLE001
            pass
    model_dump = getattr(metrics, "model_dump", None)
    if callable(model_dump):
        try:
            result = model_dump()
            if isinstance(result, dict):
                return result
        except Exception:  # noqa: BLE001
            pass
    try:
        return dict(vars(metrics))
    except TypeError:
        return None


def _extract_final_metrics(agno_obj: Any) -> dict[str, Any] | None:
    """Reads aggregated token-usage metrics off a finished Agno Agent or
    Team run.

    agno==1.8.4 does NOT stamp `.metrics` on individual streaming events
    (RunResponseContentEvent, ToolCallCompletedEvent,
    RunResponseCompletedEvent, or their Team-prefixed equivalents) - only
    the final `RunResponse` / `TeamRunResponse` object carries it, as
    `agno_obj.run_response.metrics`. This helper is the single place that
    reads it, so if a future agno upgrade moves/renames the field, only
    this function needs to change.
    """
    run_response = getattr(agno_obj, "run_response", None)
    if run_response is None:
        return None
    return _metrics_to_dict(getattr(run_response, "metrics", None))


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

    async def _resolve_instructions(self, ctx, message, ui_context=None):
        knowledge_context = await self.knowledge_service.execute_for_agent(ctx.agent.id, message)

        attachment_context = ""
        has_valid_attachment = False
        attachment_ids_raw = getattr(ui_context, "attachments", None) if ui_context else None
        if attachment_ids_raw:
            import uuid as uuid_module
            from app.attachments.service import AttachmentService
            attachment_service = AttachmentService(self.session)
            try:
                attachment_ids = [uuid_module.UUID(a) for a in attachment_ids_raw]
            except (ValueError, TypeError):
                attachment_ids = []
            if attachment_ids:
                attachment_context = await attachment_service.render_for_prompt(attachment_ids)
                has_valid_attachment = "KHÔNG đọc được" not in attachment_context and bool(attachment_context)

        priority_note = ""
        if has_valid_attachment:
            priority_note = (
                "\n\nLƯU Ý QUAN TRỌNG: Người dùng vừa đính kèm file trong tin nhắn này. "
                "Hãy ưu tiên trả lời dựa trên nội dung file đính kèm ở trên, KHÔNG tự động "
                "tìm kiếm hay trộn lẫn với tài liệu khác trong Knowledge Base trừ khi người "
                "dùng yêu cầu rõ ràng."
            )

        parts = [p for p in (attachment_context, knowledge_context, ctx.final_prompt) if p]
        result = "\n\n".join(parts) if parts else ctx.final_prompt
        return result + priority_note

    async def _build_agno_agent(
        self,
        ctx: ResolvedRuntimeContext,
        mcp_tools,
        *,
        message: str,
        session_id: str,
        user_id: str | None = None,
        ui_context: Any = None,          # <-- THÊM
    ) -> AgnoAgent:
        model_entry = await self.model_service.resolve_registry_entry(
            agent_model_id=ctx.agent.model_id,
            agent_os_default_model_id=ctx.agent_os.default_model_id,
        )
        agno_model = self.model_service.build_agno_model(
            model_entry, temperature_override=ctx.agent.temperature
        )

        instructions = await self._resolve_instructions(ctx, message, ui_context)   # <-- SỬA dòng này
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
        ui_context: Any = None,          # <-- THÊM
    ) -> str:
        self._reset_ui_action_collectors()
        mcp_session = self.tool_builder.build(ctx.effective_capabilities)
        try:
            async with mcp_session as session:
                agno_agent = await self._build_agno_agent(
                    ctx, session.tools, message=message, session_id=session_id,
                    user_id=user_id, ui_context=ui_context,   # <-- THÊM
                )
                response = await agno_agent.arun(message, session_id=session_id, user_id=user_id, stream=False)
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
        ui_context: Any = None,          # <-- THÊM
    ) -> AsyncIterator[dict[str, Any]]:
        self._reset_ui_action_collectors()
        mcp_session = self.tool_builder.build(ctx.effective_capabilities)
        agno_agent: AgnoAgent | None = None
        try:
            async with mcp_session as session:
                agno_agent = await self._build_agno_agent(
                    ctx, session.tools, message=message, session_id=session_id,
                    user_id=user_id, ui_context=ui_context,   # <-- THÊM
                )
                stream = await agno_agent.arun(
                    message, session_id=session_id, user_id=user_id,
                    stream=True, stream_intermediate_steps=True,
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

                    # NOTE (agno==1.8.4): stream events never carry
                    # `.metrics` in this version - only the final
                    # `agno_agent.run_response` does. Do NOT read
                    # `event.metrics` here; see `_extract_final_metrics`
                    # and the module docstring's QUOTA METRICS note.

                    yield {"event_type": mapped_type, "payload": payload}
        except Exception as exc:  # noqa: BLE001
            logger.error("agno_run_stream_failed", error=str(exc), agent_code=ctx.agent.code)
            yield {"event_type": "error", "payload": {"error": str(exc)}}
            raise RuntimeExecutionError(f"Agno agent streaming execution failed: {exc}") from exc

        # --- QUOTA FIX (agno 1.8.4 correct source): the stream is fully
        # consumed at this point, so `agno_agent.run_response` now holds
        # the aggregated RunResponse for the whole turn. Read metrics
        # once here and surface them as a single extra event -
        # ChatService._extract_token_usage should treat this as the sole
        # source of truth for a streamed run's usage, not sum metrics
        # across events (no other event carries any). ---
        metrics_dict = _extract_final_metrics(agno_agent)
        if metrics_dict:
            yield {
                "event_type": "agent_completed",
                "payload": {"is_assistant_content": False, "metrics": metrics_dict},
            }

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
        ui_context: Any = None,          # <-- THÊM
    ) -> AgnoTeam:
        member_agents: list[AgnoAgent] = []
        for member_ctx in ctx.member_contexts:
            mcp_session = self.tool_builder.build(member_ctx.effective_capabilities)
            session = await exit_stack.enter_async_context(mcp_session)
            member_agents.append(
                await self._build_agno_agent(
                    member_ctx, session.tools, message=message, session_id=session_id,
                    user_id=user_id, ui_context=ui_context,   # <-- THÊM
                )
            )
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
        ui_context: Any = None,          # <-- THÊM
    ) -> str:
        self._reset_ui_action_collectors()
        async with AsyncExitStack() as exit_stack:
            try:
                agno_team = await self._build_agno_team(
                    ctx, exit_stack, message=message, session_id=session_id,
                    user_id=user_id, ui_context=ui_context,   # <-- THÊM
                )
                response = await agno_team.arun(message, session_id=session_id, user_id=user_id, stream=False)
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
        ui_context: Any = None,          # <-- THÊM
    ) -> AsyncIterator[dict[str, Any]]:
        own_team_id = str(ctx.team.id)
        self._reset_ui_action_collectors()
        agno_team: AgnoTeam | None = None
        async with AsyncExitStack() as exit_stack:
            try:
                agno_team = await self._build_agno_team(
                    ctx, exit_stack, message=message, session_id=session_id,
                    user_id=user_id, ui_context=ui_context,   # <-- THÊM
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

                    # NOTE (agno==1.8.4): same as run_stream() above -
                    # Team stream events never carry `.metrics` either;
                    # read it once from `agno_team.run_response` after
                    # the loop instead (see below).

                    yield {"event_type": mapped_type, "payload": payload}
            except Exception as exc:  # noqa: BLE001
                logger.error("agno_team_run_stream_failed", error=str(exc), team_code=ctx.team.code)
                yield {"event_type": "error", "payload": {"error": str(exc)}}
                raise RuntimeExecutionError(f"Agno team streaming execution failed: {exc}") from exc

        # --- QUOTA FIX (agno 1.8.4 correct source): read aggregated
        # metrics once from the finished Team's own run_response. ---
        metrics_dict = _extract_final_metrics(agno_team)
        if metrics_dict:
            yield {
                "event_type": "agent_completed",
                "payload": {"is_assistant_content": False, "metrics": metrics_dict},
            }

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
        ui_context: Any = None,          # <-- THÊM
    ) -> AgnoTeam:
        member_teams: list[AgnoTeam] = [
            await self._build_agno_team(
                team_ctx, exit_stack, message=message, session_id=session_id,
                user_id=user_id, ui_context=ui_context,   # <-- THÊM
            )
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
        ui_context: Any = None,          # <-- THÊM
    ) -> str:
        self._reset_ui_action_collectors()
        async with AsyncExitStack() as exit_stack:
            try:
                agno_root_team = await self._build_agno_root_team(
                    ctx, exit_stack, message=message, session_id=session_id,
                    mode=mode, user_id=user_id, ui_context=ui_context,   # <-- THÊM
                )
                response = await agno_root_team.arun(message, session_id=session_id, user_id=user_id, stream=False)
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
        ui_context: Any = None,          # <-- THÊM
    ) -> AsyncIterator[dict[str, Any]]:
        own_team_id = f"root-{ctx.agent_os.id}"
        self._reset_ui_action_collectors()
        agno_root_team: AgnoTeam | None = None
        async with AsyncExitStack() as exit_stack:
            try:
                agno_root_team = await self._build_agno_root_team(
                    ctx, exit_stack, message=message, session_id=session_id,
                    mode=mode, user_id=user_id, ui_context=ui_context,   # <-- THÊM
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

                    # NOTE (agno==1.8.4): same as the other two streaming
                    # paths above - no per-event `.metrics`; read it once
                    # from `agno_root_team.run_response` after the loop.

                    yield {"event_type": mapped_type, "payload": payload}
            except Exception as exc:  # noqa: BLE001
                logger.error("agno_root_run_stream_failed", error=str(exc), agent_os_code=ctx.agent_os.code)
                yield {"event_type": "error", "payload": {"error": str(exc)}}
                raise RuntimeExecutionError(f"Agno root team streaming execution failed: {exc}") from exc

        # --- QUOTA FIX (agno 1.8.4 correct source): read aggregated
        # metrics once from the finished Root Team's own run_response. ---
        metrics_dict = _extract_final_metrics(agno_root_team)
        if metrics_dict:
            yield {
                "event_type": "agent_completed",
                "payload": {"is_assistant_content": False, "metrics": metrics_dict},
            }

        self.last_ui_action_plan = self._aggregate_ui_action_plan(run_id=session_id)
        if self.last_ui_action_plan.actions:
            yield {
                "event_type": "ui_action_plan",
                "payload": {
                    "is_assistant_content": False,
                    "ui_action_plan": self.last_ui_action_plan.model_dump(),
                },
            }