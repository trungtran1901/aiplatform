"""Typed shape for Skill.config when skill_type=WORKFLOW - mirrors
app.knowledge.models.KnowledgeSkillConfig's role for skill_type=KNOWLEDGE:
the authoritative schema for that one skill_type's config JSONB column.
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class WorkflowSkillConfig(BaseModel):
    """One WORKFLOW Skill = exactly one target Workflow, named by its
    human-facing `code` (scoped to the calling Agent's own AgentOS at
    lookup time - see WorkflowSkillService.build_trigger_tools). This is
    deliberately NOT "give the Agent a generic trigger_workflow(code)
    tool" - explicit per-Skill assignment is the permission model, the
    same way MCP capabilities are exposed one-tool-per-capability rather
    than one catch-all "call anything" tool.
    """

    workflowCode: str = Field(..., min_length=1, description="Workflow.code to trigger")
    maxTriggerDepth: int = Field(
        default=1,
        ge=0,
        le=5,
        description="How many nested workflow triggers this specific skill allows before "
        "refusing (a per-skill cap on top of the hard global ceiling in "
        "app.core.workflow_trigger_context). 0 disables nesting entirely for this skill.",
    )