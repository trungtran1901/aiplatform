"""
QuotaService.

Two responsibilities, split by latency requirement (same rationale as
app/core/run_control.py splitting cancellation signaling from actual
interruption):

  1. ENFORCEMENT (assert_within_quota) - must be fast, called on every
     chat turn before execution starts. Reads/writes a Redis counter
     only; never touches Postgres on this path.

  2. RECORDING (record_usage) - called once after a run completes.
     Writes the durable QuotaUsageEvent audit row AND increments the
     same Redis counter enforcement reads, so the two stay consistent.

Resolution order (most specific wins): USER policy > GROUP policy
(highest `priority` among matching groups) > GLOBAL policy > unlimited
(no policy configured at all -> quota is simply not enforced for that
scope/metric/period combination, matching the "safe by default, opt-in
per scope" philosophy every other feature flag in this codebase uses).

Never used to make a real authorization decision (see
docs/Architecture.md#1) - a quota-exceeded response is a metering
outcome ("you've used what was allocated to you"), not an RBAC
decision. It is safe for this to live in Agno Runtime the same way
run_control.py's cancellation logic does.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.exceptions import QuotaExceededError
from app.core.logging import get_logger
from app.models.quota import QuotaMetric, QuotaPeriod, QuotaPolicy, QuotaScopeType, QuotaUsageEvent
from app.repositories.quota_repository import QuotaPolicyRepository, QuotaUsageEventRepository

logger = get_logger(__name__)

_redis: Redis | None = None


def _get_redis() -> Redis:
    global _redis
    if _redis is None:
        settings = get_settings()
        _redis = Redis.from_url(settings.REDIS_URL, decode_responses=True)
    return _redis


def _period_bucket(period: QuotaPeriod, *, window_seconds: int | None, now: datetime) -> tuple[str, int]:
    """Returns (bucket_label, ttl_seconds) for the current period.
    bucket_label is embedded in the Redis key so counters naturally
    reset when a new period begins - no cron/cleanup job needed, the
    key simply expires."""
    if period == QuotaPeriod.daily:
        label = now.strftime("%Y-%m-%d")
        # TTL to end of day + small buffer.
        end_of_day = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        ttl = max(int((end_of_day - now).total_seconds()) + 60, 60)
        return label, ttl
    if period == QuotaPeriod.monthly:
        label = now.strftime("%Y-%m")
        if now.month == 12:
            next_month = now.replace(year=now.year + 1, month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        else:
            next_month = now.replace(month=now.month + 1, day=1, hour=0, minute=0, second=0, microsecond=0)
        ttl = max(int((next_month - now).total_seconds()) + 60, 60)
        return label, ttl
    # FIXED_WINDOW: bucket = floor(epoch / window_seconds)
    window = window_seconds or 3600
    bucket_index = int(now.timestamp() // window)
    return str(bucket_index), window + 60


def _policy_key(scope_type: QuotaScopeType, scope_value: str, model_id: uuid.UUID | None,
                 metric: QuotaMetric, period: QuotaPeriod, bucket: str) -> str:
    model_part = str(model_id) if model_id else "any"
    return f"quota:usage:{scope_type.value}:{scope_value}:{model_part}:{metric.value}:{period.value}:{bucket}"


class QuotaService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.policy_repo = QuotaPolicyRepository(session)
        self.usage_repo = QuotaUsageEventRepository(session)
        self.redis = _get_redis()

    async def _select_effective_policies(
        self, *, user_id: str, groups: list[str], model_id: uuid.UUID | None
    ) -> list[QuotaPolicy]:
        """Returns the effective set of policies to enforce: at most one
        per (metric, period) - USER beats GROUP beats GLOBAL; among
        multiple matching GROUP policies for the same (metric, period),
        the highest `priority` wins (ties broken by the smallest
        limit_value, i.e. the stricter policy, to fail safe)."""
        candidates = await self.policy_repo.list_matching(user_id=user_id, groups=groups, model_id=model_id)
        if not candidates:
            return []

        scope_rank = {QuotaScopeType.user: 0, QuotaScopeType.group: 1, QuotaScopeType.global_: 2}
        best: dict[tuple[QuotaMetric, QuotaPeriod], QuotaPolicy] = {}
        for policy in candidates:
            key = (policy.metric, policy.period)
            current = best.get(key)
            if current is None:
                best[key] = policy
                continue
            current_rank = scope_rank[current.scope_type]
            new_rank = scope_rank[policy.scope_type]
            if new_rank < current_rank:
                best[key] = policy
            elif new_rank == current_rank:
                if policy.priority > current.priority:
                    best[key] = policy
                elif policy.priority == current.priority and policy.limit_value < current.limit_value:
                    best[key] = policy  # tie-break: stricter wins
        return list(best.values())

    async def assert_within_quota(
        self, *, user_id: str | None, groups: list[str], model_id: uuid.UUID | None
    ) -> None:
        """Raises QuotaExceededError if any effective policy for this
        caller+model is already at/over its limit. No-op (never raises)
        when: feature flag is off, user_id is None (anonymous/
        unauthenticated callers are not quota-tracked - there is nothing
        stable to key them by), or no policy matches this scope at all.
        """
        settings = get_settings()
        if not settings.FEATURE_QUOTA_MANAGEMENT or not user_id:
            return

        policies = await self._select_effective_policies(user_id=user_id, groups=groups, model_id=model_id)
        if not policies:
            return

        now = datetime.now(timezone.utc)
        for policy in policies:
            bucket, _ttl = _period_bucket(policy.period, window_seconds=policy.window_seconds, now=now)
            key = _policy_key(policy.scope_type, policy.scope_value, policy.model_id, policy.metric, policy.period, bucket)
            current_raw = await self.redis.get(key)
            current = float(current_raw) if current_raw is not None else 0.0

            if current >= policy.limit_value:
                logger.warning(
                    "quota_exceeded",
                    user_id=user_id,
                    scope_type=policy.scope_type.value,
                    scope_value=policy.scope_value,
                    metric=policy.metric.value,
                    period=policy.period.value,
                    used=current,
                    limit=policy.limit_value,
                )
                raise QuotaExceededError(
                    f"Quota exceeded for {policy.metric.value} ({policy.period.value}): "
                    f"{current}/{policy.limit_value} used.",
                    details={
                        "scope_type": policy.scope_type.value,
                        "scope_value": policy.scope_value,
                        "metric": policy.metric.value,
                        "period": policy.period.value,
                        "used": current,
                        "limit": policy.limit_value,
                    },
                )

    async def record_usage(
        self,
        *,
        run_id: uuid.UUID | None,
        user_id: str | None,
        groups: list[str],
        model_id: uuid.UUID | None,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cost_usd: float | None = None,
    ) -> None:
        """Records actual usage after a run completes: writes the
        durable QuotaUsageEvent (always, if quota feature is on and
        user_id is known) and increments every matching policy's Redis
        counter so subsequent assert_within_quota() calls see it.

        Best-effort by design (mirrors ObservationEngineService.record):
        a failure here must never fail the chat turn that already
        completed successfully - errors are logged, not raised.
        """
        settings = get_settings()
        print("record_usage", user_id, str(run_id), input_tokens, output_tokens, cost_usd, settings.FEATURE_QUOTA_MANAGEMENT)
        if not settings.FEATURE_QUOTA_MANAGEMENT or not user_id:
            return

        try:
            await self.usage_repo.create(
                run_id=run_id,
                user_id=user_id,
                groups=groups,
                model_id=model_id,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost_usd=cost_usd,
            )
        except Exception as exc:  # noqa: BLE001
            print("quota_usage_event_write_failed", user_id, str(run_id), str(exc))
            logger.error("quota_usage_event_write_failed", user_id=user_id, run_id=str(run_id), error=str(exc))

        try:
            policies = await self._select_effective_policies(user_id=user_id, groups=groups, model_id=model_id)
            if not policies:
                return
            now = datetime.now(timezone.utc)
            total_tokens = input_tokens + output_tokens
            metric_values = {
                QuotaMetric.requests: 1,
                QuotaMetric.tokens: total_tokens,
                QuotaMetric.cost_usd: cost_usd or 0.0,
            }
            for policy in policies:
                delta = metric_values.get(policy.metric)
                if not delta:
                    continue
                bucket, ttl = _period_bucket(policy.period, window_seconds=policy.window_seconds, now=now)
                key = _policy_key(
                    policy.scope_type, policy.scope_value, policy.model_id, policy.metric, policy.period, bucket
                )
                await self.redis.incrbyfloat(key, delta)
                await self.redis.expire(key, ttl)
        except Exception as exc:  # noqa: BLE001
            logger.error("quota_counter_increment_failed", user_id=user_id, run_id=str(run_id), error=str(exc))

    async def get_usage_snapshot(self, *, user_id: str, since_days: int = 30) -> dict:
        """Reporting helper for GET /quota/usage - aggregates from the
        durable Postgres audit trail (not Redis, which only holds
        current-period counters), so callers can see historical usage
        beyond just "how much is left in the current window"."""
        since = datetime.now(timezone.utc) - timedelta(days=since_days)
        return await self.usage_repo.sum_since(user_id=user_id, since=since)