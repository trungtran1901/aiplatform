"""
ContextEngineService.

Assembles the "Context" block folded into an Agent's instructions for a
single chat turn, mirroring exactly how KnowledgeSkillService produces a
"Knowledge Context" block (see app/knowledge/service.py +
app/knowledge/mapper.py::render_context) - same shape, same integration
point, so AgnoRuntimeEngine only needs one more optional concatenation,
never a structural change.

INTEGRATION POINT (not wired in by default - see note at bottom):
    AgnoRuntimeEngine._resolve_instructions() currently does:

        knowledge_context = await self.knowledge_service.execute_for_agent(...)
        if not knowledge_context:
            return ctx.final_prompt
        return f"{knowledge_context}\n\n{ctx.final_prompt}"

    To wire the Context Engine in, add ONE more optional concatenation
    above that, guarded by the same "empty string -> no-op" pattern:

        ui_context = await self.context_engine.build_context_block(request.uiContext)
        parts = [p for p in (ui_context, knowledge_context, ctx.final_prompt) if p]
        return "\n\n".join(parts)

    This is intentionally left as a documented patch rather than an
    in-place edit to engine.py in this delivery, since engine.py is a
    large, sensitive, already-stable file - applying it should be a
    deliberate, reviewed one-line change by the team, not a silent
    side-effect of adding this package.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.logging import get_logger
from app.models.ui_metadata import UIMetadataKind
from app.repositories.ui_metadata_repository import UIMetadataRepository

logger = get_logger(__name__)


class ContextEngineService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.ui_metadata_repo = UIMetadataRepository(session)

    async def build_context_block(self, ui_context: Any | None) -> str:
        """Returns a plain-text "Runtime Context" section, or "" (never
        None) when the feature is disabled or there's nothing to
        assemble - callers can always safely concatenate the result,
        exactly like KnowledgeSkillService.execute_for_agent().

        `ui_context` is expected to be an app.schemas.chat.UIContextFields
        instance (or None) - typed as Any here to avoid a schemas->this
        package import cycle; only attribute access is used, so a plain
        dict with the same keys also works.
        """
        settings = get_settings()
        if not settings.FEATURE_CONTEXT_ENGINE:
            return ""
        if ui_context is None:
            return ""

        def _get(name: str) -> Any:
            if isinstance(ui_context, dict):
                return ui_context.get(name)
            return getattr(ui_context, name, None)

        sections: list[str] = []

        application_id = _get("applicationId")
        page_id = _get("pageId")
        route = _get("route")
        locale = _get("device")
        device = _get("device")
        current_record = _get("currentRecord")
        selected_items = _get("selectedItems")
        variables = _get("variables")
        ui_state = _get("uiState")

        if application_id or page_id or route:
            sections.append(
                "Application: {app} | Page: {page} | Route: {route}".format(
                    app=application_id or "-", page=page_id or "-", route=route or "-"
                )
            )

        if page_id:
            page_meta = await self.ui_metadata_repo.get_latest(page_id, kind=UIMetadataKind.page)
            if page_meta is not None:
                sections.append(f"Page metadata ({page_id}): {page_meta.payload}")

        if current_record:
            sections.append(f"Current record: {current_record}")

        if selected_items:
            sections.append(f"Selected items: {selected_items}")

        if variables:
            sections.append(f"Session variables: {variables}")

        if ui_state:
            sections.append(f"UI state: {ui_state}")

        if not sections:
            return ""

        header = "Runtime Context"
        if locale or device:
            header += f" (locale={locale or '-'}, device={device or '-'})"

        logger.info("context_engine_block_built", application_id=application_id, page_id=page_id)
        return "\n".join([header, "-" * 40, *sections, "-" * 40])
