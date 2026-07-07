"""
Maps between the Knowledge Platform's wire format and this runtime's own
typed/prompt representations.

Deliberately tolerant of shape variation in the raw response (the
Knowledge Platform is an independent, unmodified microservice - this
runtime adapts to it, not the other way around) - unrecognized or
missing fields degrade gracefully rather than raising. Nested envelopes
(e.g. `{"data": {"results": [...]}}` or `{"result": {"chunks": [...]}}`)
are unwrapped recursively rather than only one level deep, since a
schema mismatch here silently yields zero chunks with no error - the
single most common cause of "the request went out but the Skill wasn't
actually used".
"""
from __future__ import annotations

from typing import Any

from app.knowledge.models import KnowledgeChunk, KnowledgeSearchResult

# Candidate key names tried in order for each normalized field, since
# different Knowledge Platform deployments/versions may name fields
# slightly differently (e.g. "content" vs "text" vs "chunk").
_CONTENT_KEYS = ("content", "text", "chunk", "chunk_text", "passage", "body", "answer")
_ID_KEYS = ("id", "chunk_id", "chunkId", "_id")
_TITLE_KEYS = ("document_title", "documentTitle", "title", "document_name", "source", "filename", "file_name")
_PAGE_KEYS = ("page", "page_number", "pageNumber")
_SCORE_KEYS = ("score", "similarity", "relevance_score")

# Candidate keys that wrap the actual list of retrieved items. Checked
# recursively - if a value under one of these keys is itself a dict, we
# look inside it for another one of these keys, so both
# {"data": {"results": [...]}} and {"data": {"items": [...]}} resolve
# correctly, not just one specific level of nesting.
_LIST_KEYS = ("results", "chunks", "documents", "items", "hits", "matches", "data")


def _first_present(item: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        if key in item and item[key] is not None:
            return item[key]
    return None


def _find_item_list(node: Any, *, depth: int = 0) -> list[Any]:
    """Recursively searches for the first list of retrieval items inside
    `node`, following any of `_LIST_KEYS` regardless of nesting depth.
    Bounded to a shallow depth since Knowledge Platform envelopes are
    never more than a couple of levels deep in practice - this is a
    safety net against schema drift, not a general-purpose JSON walker.
    """
    if depth > 4:
        return []
    if isinstance(node, list):
        return node
    if not isinstance(node, dict):
        return []
    for key in _LIST_KEYS:
        if key in node and node[key] is not None:
            found = _find_item_list(node[key], depth=depth + 1)
            if found:
                return found
    return []


def parse_search_response(raw: dict[str, Any]) -> KnowledgeSearchResult:
    """Normalizes a raw Knowledge Platform JSON body into a
    KnowledgeSearchResult. Accepts `{"results": [...]}`, `{"chunks":
    [...]}`, `{"data": {"results": [...]}}`, `{"data": {"items":
    [...]}}`, `{"result": {"chunks": [...]}}`, or a bare top-level
    list - any reasonable envelope shape, so a Knowledge Platform naming
    its wrapper key slightly differently doesn't silently produce zero
    chunks.
    """
    items = _find_item_list(raw)

    chunks: list[KnowledgeChunk] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        content = _first_present(item, _CONTENT_KEYS)
        if not content:
            continue
        chunks.append(
            KnowledgeChunk(
                content=str(content),
                chunk_id=_first_present(item, _ID_KEYS),
                document_title=_first_present(item, _TITLE_KEYS),
                page=_first_present(item, _PAGE_KEYS),
                score=_first_present(item, _SCORE_KEYS),
                metadata={k: v for k, v in item.items() if k not in _CONTENT_KEYS},
            )
        )

    usage = raw.get("usage") if isinstance(raw, dict) else None
    return KnowledgeSearchResult(chunks=chunks, raw_token_usage=usage)


def render_context(result: KnowledgeSearchResult) -> str:
    """Renders a KnowledgeSearchResult into the structured, LLM-ready
    context block described in docs/Knowledge.md, injected before the
    user prompt. Returns an empty string (never None) when there are no
    chunks, so callers can always safely concatenate it. Each chunk's
    `chunk_id` (when known) is included as "Ma doan" so the Agent can
    later pass it to the get_document_source tool if the user asks to
    see the original document."""
    if not result.chunks:
        return ""

    sections = ["Knowledge Context", "-" * 40]
    has_chunk_id = False
    for chunk in result.chunks:
        if chunk.document_title:
            sections.append(f"Document: {chunk.document_title}")
        if chunk.page is not None:
            sections.append(f"Page: {chunk.page}")
        sections.append(chunk.content.strip())
        if chunk.chunk_id:
            sections.append(f"Ma doan (chunk_id): {chunk.chunk_id}")
            has_chunk_id = True
        sections.append("-" * 40)

    if has_chunk_id:
        sections.append(
            "Neu nguoi dung yeu cau xem/tai tai lieu goc cua mot doan, hay goi tool "
            "get_document_source voi chunk_id tuong ung o tren de lay duong dan chinh xac - "
            "khong tu bia duong dan tai lieu."
        )

    return "\n".join(sections)