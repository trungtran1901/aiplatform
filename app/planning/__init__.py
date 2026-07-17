"""Planning Engine - AgentX Runtime v2 (Phase 8, flagged).

IMPORTANT SCOPE NOTE: Agno's own Agent/Team `arun()` already performs
intent understanding and tool/skill selection internally via the LLM's
native reasoning loop (see app/agno_runtime/engine.py) - re-implementing
that here would duplicate Agno's own job, which the project's
"Development Principles" (reuse, never replace) explicitly forbid.

What THIS Planning Engine legitimately adds, without duplicating Agno,
is a layer *above* a single Agent/Team run: deciding whether a request
should be handled by exactly one Agent/Team call (today's behavior,
unchanged) or as an ordered SEQUENCE of Agent/Team calls (a novel,
ad-hoc, non-persisted alternative to creating a full Workflow row for a
one-off multi-step request). It is currently a deterministic/heuristic
planner (explicit step list in the request, or a single-step fallback
identical to current behavior) rather than an LLM-driven planner -
wiring in real LLM-based planning is a documented future extension
point in PlanningEngineService, not implemented here, since it requires
your own product decisions about prompt/model choice for the planner
itself.
"""
from __future__ import annotations
