"""Workflow Skill - implements SkillType.WORKFLOW (reserved in
app.models.skill since it was added, never previously wired to an
executor).

Lets an Agent trigger a specific, pre-configured Workflow as a tool
call - one tool per WORKFLOW Skill assigned to the Agent, each tool
named/scoped to exactly the Workflow named in that Skill's
config.workflowCode. Mirrors the "build tool(s) or empty list" shape
KnowledgeSkillService / BusinessObjectSkillService already use.
"""
from __future__ import annotations