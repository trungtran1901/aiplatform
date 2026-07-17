"""
UIActionSkillService.

Lets an Agent whose Skill has skill_type=UI propose a structured
UIActionPlan instead of (or alongside) free text - mirroring how
app.knowledge.service.KnowledgeSkillService builds a callable tool
(get_document_source) that the Agent can invoke on demand. Here, the
tool is `propose_ui_action`: the Agent calls it once per action it
wants the frontend to take, and this service accumulates them into a
UIActionPlan for the run.

Entirely inert unless FEATURE_UI_SKILLS is enabled - build_action_tool()
returns None when the flag is off, exactly like KnowledgeSkillService
returns None when an Agent has no Knowledge skills, so callers can
always safely omit the tool.

INTEGRATION POINT (documented, not auto-applied - same rationale as
app/uicontext/service.py): in
AgnoRuntimeEngine._build_agno_agent(), alongside the existing
`source_tool = await self.knowledge_service.build_source_lookup_tool(...)`
line, add:

    ui_action_tool = await self.ui_action_service.build_action_tool(ctx.agent.id, collector)
    if ui_action_tool is not None:
        tools.append(ui_action_tool)

where `collector` is a UIActionPlanCollector the caller reads from after
`arun()` completes to get the accumulated UIActionPlan.
"""
from __future__ import annotations

import uuid
from typing import Callable

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.logging import get_logger
from app.models.skill import SkillType
from app.repositories.skill_repository import SkillRepository
from app.uiaction.models import ActionType, UIAction, UIActionPlan

logger = get_logger(__name__)


class UIActionPlanCollector:
    """Accumulates UIActions emitted during one run. One instance per
    chat turn, created by the caller and passed into build_action_tool()
    so the tool closure can append to it."""

    def __init__(self) -> None:
        self.actions: list[UIAction] = []

    def to_plan(self, run_id: str | None = None) -> UIActionPlan:
        return UIActionPlan(runId=run_id, actions=list(self.actions))


class UIActionSkillService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.skill_repo = SkillRepository(session)

    async def build_action_tool(self, agent_id: uuid.UUID, collector: UIActionPlanCollector) -> Callable | None:
        settings = get_settings()
        if not settings.FEATURE_UI_SKILLS:
            return None

        skills = await self.skill_repo.list_skills_for_agent(agent_id)
        ui_skills = [s for s in skills if s.skill_type == SkillType.ui]
        if not ui_skills:
            return None

        async def propose_ui_action(
            actionType: str,
            target: str,
            value: str | None = None,
            reason: str | None = None,
            businessMeaning: str | None = None,
            confidence: float = 1.0,
        ) -> str:
            """Propose a structured UI action (fill a field, click a
            button, navigate, open/close a dialog, etc.) for the
            frontend to execute. Call this instead of describing the UI
            change in prose. `actionType` must be one of the supported
            UIAction types (FILL_FORM, SET_VALUE, SELECT_VALUE,
            CLICK_BUTTON, NAVIGATE, OPEN_DIALOG, CLOSE_DIALOG,
            UPLOAD_FILE, DOWNLOAD_FILE, FOCUS_COMPONENT,
            HIGHLIGHT_COMPONENT, EXPAND_TREE, COLLAPSE_TREE,
            REFRESH_GRID, VALIDATE_FORM). `target` must be a UI Metadata
            Registry component/field/page code, never a CSS selector.
            """
            try:
                normalized_type = ActionType(actionType.upper())
            except ValueError:
                return f"Unknown actionType '{actionType}' - not added to the plan."

            action = UIAction(
                actionType=normalized_type,
                target=target,
                value=value,
                reason=reason,
                businessMeaning=businessMeaning,
                confidence=confidence,
                executionOrder=len(collector.actions),
            )
            collector.actions.append(action)
            logger.info("ui_action_proposed", action_type=normalized_type.value, target=target)
            return f"Action '{normalized_type.value}' on '{target}' added to the UI action plan."

        return propose_ui_action
