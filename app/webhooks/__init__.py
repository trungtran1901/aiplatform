"""Workflow Webhooks - AgentX Runtime v2 (flagged).

Lets an external HTTP caller trigger a Workflow run via a stable,
opaque URL - see app/models/workflow_webhook.py for the auth-model
rationale (HMAC signature + optional IP allowlist, NOT RBAC).
"""
from __future__ import annotations