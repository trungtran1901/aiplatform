"""Workflow Scheduling - AgentX Runtime v2 (flagged).

Runs an existing Workflow on a cron or fixed-interval basis, without
duplicating any execution logic: every fire is just a normal call into
WorkflowExecutionService.run_workflow(), exactly the same entrypoint
POST /workflows/{id}/run uses.

Two pieces:
  service.py  - metadata CRUD + next_run_at computation (pure, testable)
  ticker.py   - the actual polling loop + cross-instance Redis lock,
                started from app.main's lifespan when the flag is on
"""
from __future__ import annotations