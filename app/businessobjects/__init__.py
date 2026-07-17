"""Business Object Skill - AgentX v2.

Gives an Agent (only if it has a Skill with config={"businessObjectLookup": true})
two tools: lookup_business_object (read the schema/rules) and
validate_business_object (server-side rule check before calling any MCP
capability that would actually persist the data). Mirrors
app.knowledge.service.KnowledgeSkillService's build-tool-or-None shape.
"""
from __future__ import annotations