"""Action DSL - AgentX Runtime v2 (Phase 4, flagged).

A versioned, serializable vocabulary the LLM (via a UI Skill) can
generate instead of freeform text when it wants the frontend to *do*
something (fill a field, click a button, navigate). This package NEVER
touches a DOM - it only defines and validates the DSL shape; execution
is entirely the frontend SDK's responsibility (see docs note in
app/uiaction/models.py).
"""
from __future__ import annotations
