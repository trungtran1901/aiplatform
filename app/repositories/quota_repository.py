from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select

from app.models.quota import QuotaPolicy, QuotaScopeType, QuotaUsageEvent
from app.repositories.base import BaseRepository


class QuotaPolicyRepository(BaseRepository[QuotaPolicy]):
    model = QuotaPolicy

    async def list_matching(
        self, *, user_id: str, groups: list[str], model_id: uuid.UUID | None
    ) -> list[QuotaPolicy]:
        """Every enabled, non-deleted policy that could apply to this
        caller: exact USER match, any GROUP match, or GLOBAL - for
        either this specific model_id or model_id=NULL (all-models
        policies). QuotaService picks the effective one(s) from this
        candidate set; this method does no scope-priority resolution
        itself, it only narrows down what's eligible."""
        scope_filters = [
            (QuotaPolicy.scope_type == QuotaScopeType.user) & (QuotaPolicy.scope_value == user_id),
            QuotaPolicy.scope_type == QuotaScopeType.global_,
        ]
        if groups:
            scope_filters.append(
                (QuotaPolicy.scope_type == QuotaScopeType.group) & (QuotaPolicy.scope_value.in_(groups))
            )

        from sqlalchemy import or_

        stmt = select(QuotaPolicy).where(
            QuotaPolicy.deleted_at.is_(None),
            QuotaPolicy.enabled.is_(True),
            or_(*scope_filters),
            or_(QuotaPolicy.model_id.is_(None), QuotaPolicy.model_id == model_id) if model_id else QuotaPolicy.model_id.is_(None),
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())


class QuotaUsageEventRepository(BaseRepository[QuotaUsageEvent]):
    model = QuotaUsageEvent

    async def sum_since(
        self, *, user_id: str, since: datetime, model_id: uuid.UUID | None = None
    ) -> dict[str, float]:
        """Aggregates usage for reconciliation / rebuilding a lost Redis
        counter. Not on the hot enforcement path (that reads Redis) -
        this is for reporting and disaster recovery."""
        from sqlalchemy import func

        stmt = select(
            func.coalesce(func.sum(QuotaUsageEvent.input_tokens + QuotaUsageEvent.output_tokens), 0),
            func.coalesce(func.count(QuotaUsageEvent.id), 0),
            func.coalesce(func.sum(QuotaUsageEvent.cost_usd), 0.0),
        ).where(QuotaUsageEvent.user_id == user_id, QuotaUsageEvent.created_at >= since)
        if model_id is not None:
            stmt = stmt.where(QuotaUsageEvent.model_id == model_id)

        result = await self.session.execute(stmt)
        tokens, requests, cost = result.one()
        return {"tokens": float(tokens), "requests": float(requests), "cost_usd": float(cost)}

    async def list_by_user(self, user_id: str, *, offset: int = 0, limit: int = 50):
        return await self.list(offset=offset, limit=limit, user_id=user_id)