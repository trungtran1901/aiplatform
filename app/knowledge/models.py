"""
Typed shapes for the Knowledge Skill integration.

KnowledgeSkillConfig is the authoritative schema for
`Skill.config` when `Skill.skill_type == SkillType.knowledge` - it is
what makes a Knowledge Skill "entirely configurable from REST APIs",
per docs/Knowledge.md. Every field below is read directly from the
database; nothing about a specific Knowledge Platform instance,
collection, or embedding model is ever hardcoded in this codebase.
"""
from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class KnowledgeSkillConfig(BaseModel):
    """Validated shape of a KNOWLEDGE Skill's `config` JSONB column.

    A Knowledge Skill's `knowledgeBaseUrl` is deliberately per-Skill
    (not a single global setting) because multiple Knowledge Platform
    instances may exist side by side (prod / test / department-specific)
    - each Knowledge Skill names exactly one instance to query.
    """

    knowledgeBaseUrl: str = Field(..., min_length=1, description="Base URL of the Knowledge Platform instance")
    searchApi: str = Field(default="/api/v1/search", description="Path appended to knowledgeBaseUrl for search")
    sourceApi: str = Field(
        default="/api/v1/chunks/{chunk_id}/source",
        description="Path template appended to knowledgeBaseUrl to fetch the source document "
        "location for one retrieved chunk. '{chunk_id}' is substituted at call time.",
    )
    collectionId: str = Field(..., min_length=1)
    agentId: str | None = Field(default=None, description="Knowledge-Platform-native agent scoping id, if used")
    embeddingModelCode: str | None = Field(default=None)
    topK: int = Field(default=10, ge=1, le=100)
    timeout: float = Field(default=30.0, gt=0, le=300)
    stream: bool = Field(default=False, description="Reserved for future streaming search support")

    @field_validator("knowledgeBaseUrl")
    @classmethod
    def _no_trailing_slash(cls, value: str) -> str:
        return value.rstrip("/")

    @field_validator("searchApi", "sourceApi")
    @classmethod
    def _leading_slash(cls, value: str) -> str:
        return value if value.startswith("/") else f"/{value}"

    @property
    def search_url(self) -> str:
        return f"{self.knowledgeBaseUrl}{self.searchApi}"

    def source_url(self, chunk_id: str) -> str:
        return f"{self.knowledgeBaseUrl}{self.sourceApi.format(chunk_id=chunk_id)}"


class KnowledgeChunk(BaseModel):
    """One retrieved chunk, normalized from whatever shape the Knowledge
    Platform returns. Only `content` is required - everything else is
    best-effort metadata used purely for formatting the LLM context,
    never for any decision-making in this codebase. `chunk_id` (when
    present in the search response) is what a later
    GET /chunks/{chunk_id}/source call needs to resolve the original
    document location - it is surfaced in the rendered context so the
    Agent can pass it back via the get_document_source tool when a user
    explicitly asks to see the source document."""

    content: str
    chunk_id: str | None = None
    document_title: str | None = None
    page: int | str | None = None
    score: float | None = None
    metadata: dict = Field(default_factory=dict)


class KnowledgeChunkSource(BaseModel):
    """Shape of GET {knowledgeBaseUrl}/chunks/{chunk_id}/source."""

    document_id: str | None = None
    page: int | str | None = None
    bbox: dict | None = None
    source_url: str


class KnowledgeSearchResult(BaseModel):
    chunks: list[KnowledgeChunk] = Field(default_factory=list)
    raw_token_usage: dict | None = None

    @property
    def chunk_count(self) -> int:
        return len(self.chunks)