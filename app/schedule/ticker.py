"""
WorkflowScheduleTicker.

The actual polling loop. Runs as a background asyncio task (started
from app/main.py's lifespan when FEATURE_WORKFLOW_SCHEDULING is on) -
NOT a separate process by default, to keep local/dev setup simple, but
written so it is safe to run on N replicas simultaneously:

Every tick:
  1. Query workflow_schedules for anything due (next_run_at <= now).
  2. For each due schedule, attempt to acquire a short-lived Redis lock
     keyed by schedule id (same cross-instance coordination pattern as
     app/core/run_control.py's cancellation flag). Only the instance
     that wins the lock actually triggers the run; others skip it this
     tick (the losing instances will simply see next_run_at already
     advanced on their next poll).
  3. Call WorkflowExecutionService.run_workflow() - the exact same
     entrypoint POST /workflows/{id}/run uses. No execution logic is
     duplicated here.
  4. Advance next_run_at via WorkflowScheduleService.record_fired(),
     regardless of success/failure, so a persistently-failing schedule
     doesn't spin on the same timestamp forever.

A single schedule failing to trigger never stops the ticker loop or
affects any other schedule - each is caught and logged independently.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from redis.asyncio import Redis

from app.core.config import get_settings
from app.core.logging import get_logger
from app.db.session import session_scope
from app.schedule.service import WorkflowScheduleService
from app.schemas.workflow_run import WorkflowRunRequest
from app.services.workflow_execution_service import WorkflowExecutionService

logger = get_logger(__name__)

_running = False


def _lock_key(schedule_id) -> str:
    return f"workflow_schedule:lock:{schedule_id}"


async def _try_acquire_lock(redis: Redis, schedule_id, ttl_seconds: int) -> bool:
    return bool(await redis.set(_lock_key(schedule_id), "1", nx=True, ex=ttl_seconds))


async def _fire_one(redis: Redis, schedule) -> None:
    settings = get_settings()
    if not await _try_acquire_lock(redis, schedule.id, settings.WORKFLOW_SCHEDULER_LOCK_TTL_SECONDS):
        return  # another instance already won this tick

    async with session_scope() as session:
        schedule_service = WorkflowScheduleService(session)
        # Re-fetch inside this session/transaction - the `schedule`
        # object passed in came from a different, already-closed session.
        fresh = await schedule_service.get(schedule.id)
        if not fresh.enabled:
            return

        exec_service = WorkflowExecutionService(session)
        try:
            result = await exec_service.run_workflow(
                fresh.workflow_id,
                WorkflowRunRequest(input=fresh.input_template, user_id=fresh.user_id),
            )
            await schedule_service.record_fired(
                fresh, status=result["status"], workflow_run_id=result["workflowRunId"]
            )
            logger.info("workflow_schedule_fired", schedule_id=str(fresh.id), status=result["status"])
        except Exception as exc:  # noqa: BLE001
            await schedule_service.record_fired(fresh, status="FAILED", workflow_run_id=None, error=str(exc))
            logger.error("workflow_schedule_fire_failed", schedule_id=str(fresh.id), error=str(exc))


async def run_ticker_loop() -> None:
    """Entrypoint started as a background task. Runs until cancelled."""
    global _running
    settings = get_settings()
    redis = Redis.from_url(settings.REDIS_URL, decode_responses=True)
    _running = True
    logger.info("workflow_schedule_ticker_started", tick_seconds=settings.WORKFLOW_SCHEDULER_TICK_SECONDS)

    try:
        while _running:
            try:
                async with session_scope() as session:
                    schedule_repo_service = WorkflowScheduleService(session)
                    due = await schedule_repo_service.schedule_repo.list_due(as_of=datetime.now(timezone.utc))

                for schedule in due:
                    try:
                        await _fire_one(redis, schedule)
                    except Exception as exc:  # noqa: BLE001
                        logger.error("workflow_schedule_tick_error", schedule_id=str(schedule.id), error=str(exc))
            except Exception as exc:  # noqa: BLE001
                logger.error("workflow_schedule_ticker_tick_failed", error=str(exc))

            await asyncio.sleep(settings.WORKFLOW_SCHEDULER_TICK_SECONDS)
    finally:
        await redis.close()
        logger.info("workflow_schedule_ticker_stopped")


def stop_ticker() -> None:
    global _running
    _running = False