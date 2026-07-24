from __future__ import annotations

from fastapi import APIRouter

from app.api.v1 import (
    agent_os,
    agents,
    attachments,
    business_objects,
    capabilities,
    chat,
    execution_plans,
    memories,
    models,
    observations,
    prompts,
    quota,
    runs,
    runtime_events,
    sessions,
    skills,
    teams,
    ui_metadata,
    workflow_runs,
    workflows,
    workflow_schedules,   # MỚI
    workflow_webhooks,
)

api_router = APIRouter(prefix="/api/v1")

api_router.include_router(agent_os.router)
api_router.include_router(teams.router)
api_router.include_router(agents.router)
api_router.include_router(prompts.router)
api_router.include_router(skills.router)
api_router.include_router(capabilities.router)
api_router.include_router(models.router)
api_router.include_router(chat.router)
api_router.include_router(sessions.router)
api_router.include_router(runs.router)
api_router.include_router(memories.router)
api_router.include_router(workflows.router)
api_router.include_router(workflow_runs.router)
api_router.include_router(attachments.router)
# --- AgentX Runtime v2 (all feature-flagged, additive) ---
api_router.include_router(ui_metadata.router)
api_router.include_router(business_objects.router)
api_router.include_router(observations.router)
api_router.include_router(runtime_events.router)
api_router.include_router(execution_plans.router)
api_router.include_router(workflow_schedules.router)
api_router.include_router(workflow_webhooks.router)
api_router.include_router(quota.router)  # MỚI - Quota Management (flagged FEATURE_QUOTA_MANAGEMENT)