from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from app.models.quota import QuotaMetric, QuotaPeriod, QuotaScopeType
from app.schemas.common import TimestampedSchema


class QuotaPolicyBase(BaseModel):
    scope_type: QuotaScopeType
    scope_value: str = Field(
        default="",
        description="'' for GLOBAL. A Keycloak group name for GROUP (matches the JWT 'groups' claim, "
        "which is populated automatically for LDAP-federated groups once LDAP User Federation is "
        "configured in Keycloak). The verified 'sub' claim for USER.",
    )
    model_id: UUID | None = Field(default=None, description="Omit to apply across every model")
    metric: QuotaMetric
    period: QuotaPeriod
    window_seconds: int | None = Field(default=None, ge=10, description="Required when period=FIXED_WINDOW")
    limit_value: int = Field(..., ge=0, description="Tokens count / request count / cost in cents, depending on metric")
    priority: int = Field(default=0, description="Tie-breaker among multiple matching GROUP policies - higher wins")
    enabled: bool = True

    @model_validator(mode="after")
    def _validate_scope_value(self) -> "QuotaPolicyBase":
        if self.scope_type in (QuotaScopeType.user, QuotaScopeType.group) and not self.scope_value:
            raise ValueError("scope_value is required when scope_type is USER or GROUP")
        if self.period == QuotaPeriod.fixed_window and not self.window_seconds:
            raise ValueError("window_seconds is required when period=FIXED_WINDOW")
        return self


class QuotaPolicyCreate(QuotaPolicyBase):
    pass


class QuotaPolicyUpdate(BaseModel):
    limit_value: int | None = Field(default=None, ge=0)
    priority: int | None = None
    enabled: bool | None = None
    window_seconds: int | None = Field(default=None, ge=10)


class QuotaPolicyRead(TimestampedSchema, QuotaPolicyBase):
    pass


class QuotaUsageRead(BaseModel):
    user_id: str
    since_days: int
    tokens: float
    requests: float
    cost_usd: float