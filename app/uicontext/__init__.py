"""
Context Engine - AgentX Runtime v2 (Phase 2, feature-flagged).

Single source of truth assembled BEFORE an LLM invocation, folding
together whatever of the following are present for a given chat turn:

    - Extended Chat Context (app.schemas.chat.UIContextFields)
    - UI Metadata Registry lookups (app.uimeta / app.repositories.ui_metadata_repository)
    - Session variables / conversation memory (already resolved elsewhere)

This package NEVER calls the LLM itself and NEVER decides routing - it
only produces a plain text "Context" block, folded into the Agent's
instructions the exact same way Knowledge Skill context is folded in
(see AgnoRuntimeEngine._resolve_instructions in app/agno_runtime/engine.py).

Disabled by default (settings.FEATURE_CONTEXT_ENGINE=False): when off,
ContextEngineService.build_context_block() returns "" unconditionally,
so folding it in is always safe and behavior-neutral even if a caller
wires it in before the flag is turned on anywhere.
"""
from __future__ import annotations
