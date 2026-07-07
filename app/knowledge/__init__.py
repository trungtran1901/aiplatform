"""
Knowledge Skill integration.

Treats an external Knowledge Platform microservice as just another
pluggable Skill Executor (skill_type=KNOWLEDGE on app.models.skill.Skill),
exactly the way MCP capabilities are just another Skill Executor
(skill_type=MCP). Agno Runtime never embeds retrieval logic into Agent
itself and never knows or cares how the Knowledge Platform implements
search internally - it only knows how to call it, per Skill
configuration, and fold the results into the Agent's prompt context.

    Agent -> Skill Engine -> KnowledgeSkillExecutor -> Knowledge Platform

Modules:
    models.py     - typed config/response shapes (KnowledgeSkillConfig,
                     KnowledgeChunk, KnowledgeSearchResult)
    exceptions.py  - KnowledgeServiceError hierarchy
    client.py      - raw async HTTP client (auth-forwarding only, no
                     retrieval logic of its own)
    mapper.py      - converts a KnowledgeSearchResult into LLM-ready
                     prompt context text
    executor.py    - KnowledgeSkillExecutor: one Skill row in, one
                     context string out
    service.py     - KnowledgeSkillService: orchestrates executor
                     construction + invocation for a Skill id, used by
                     both the runtime engine and the
                     POST /skills/{id}/test endpoint

Nothing in this package modifies or assumes anything about the Knowledge
Platform's own internals - it is treated as an opaque HTTP service whose
contract is entirely captured in KnowledgeSkillConfig.
"""
from __future__ import annotations
