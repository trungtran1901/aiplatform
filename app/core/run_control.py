"""
Run cancellation signaling.

A chat turn's streamed execution (app/services/chat_service.py::
handle_chat_stream) may be consumed by a different runtime instance than
the one that later receives a cancel request - this platform is
explicitly designed to be stateless and horizontally scalable (see
docs/Architecture.md), so a cancellation cannot be a plain in-process
flag shared by reference. Instead it is written to Redis as a
short-lived key, and the instance actually running the streamed loop
polls it once per yielded event.

This module only signals intent - it never itself stops anything. The
actual interruption happens in chat_service, which checks
is_cancelled() between events and, on a hit, closes the underlying Agno
stream (releasing its MCP session/tool connections via the same
async-generator cleanup path a normal completion or exception takes) and
marks the run CANCELLED.

Calling request_cancel() for a run_id that isn't currently executing on
any instance (already finished, or never existed) is harmless - the key
is simply never read and expires via TTL.
"""
from __future__ import annotations

from redis.asyncio import Redis

from app.core.config import get_settings

_redis: Redis | None = None


def _get_redis() -> Redis:
    global _redis
    if _redis is None:
        settings = get_settings()
        _redis = Redis.from_url(settings.REDIS_URL, decode_responses=True)
    return _redis


def _key(run_id: str) -> str:
    return f"run:cancel:{run_id}"


async def request_cancel(run_id: str) -> None:
    """Signals that `run_id` should stop as soon as the executing
    instance next checks (typically within one streamed model/tool-call
    chunk). TTL matches REDIS_EVENT_STREAM_TTL_SECONDS so a stale flag
    can never linger past any run's realistic lifetime."""
    settings = get_settings()
    redis = _get_redis()
    await redis.set(_key(run_id), "1", ex=settings.REDIS_EVENT_STREAM_TTL_SECONDS)


async def is_cancelled(run_id: str) -> bool:
    redis = _get_redis()
    return bool(await redis.exists(_key(run_id)))


async def clear_cancel(run_id: str) -> None:
    """Removes the flag once a run has actually stopped - pure
    housekeeping so the key disappears immediately instead of waiting
    out its TTL."""
    redis = _get_redis()
    await redis.delete(_key(run_id))