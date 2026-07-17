from __future__ import annotations

from pydantic import BaseModel, Field

from app.schemas.common import TimestampedSchema


class BusinessObjectFieldSpec(BaseModel):
    name: str
    type: str = Field(..., description="e.g. 'string', 'number', 'date', 'enum', 'reference'")
    required: bool = False
    description: str | None = None
    enumValues: list[str] | None = None
    referenceObjectCode: str | None = Field(default=None, description="For type='reference'")


class BusinessObjectRelationship(BaseModel):
    name: str
    targetObjectCode: str
    cardinality: str = Field(default="many-to-one", description="'one-to-one'|'one-to-many'|'many-to-one'|'many-to-many'")


class BusinessObjectPayload(BaseModel):
    fields: list[BusinessObjectFieldSpec] = Field(default_factory=list)
    relationships: list[BusinessObjectRelationship] = Field(default_factory=list)
    validation: list[dict] = Field(default_factory=list)
    businessMeaning: str | None = None


class BusinessObjectBase(BaseModel):
    code: str = Field(..., min_length=1, max_length=128, pattern=r"^[a-z0-9][a-z0-9\-_.]*$")
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    payload: BusinessObjectPayload
    enabled: bool = True


class BusinessObjectCreate(BusinessObjectBase):
    pass


class BusinessObjectUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    payload: BusinessObjectPayload | None = None
    enabled: bool | None = None


class BusinessObjectRead(TimestampedSchema, BusinessObjectBase):
    version: int
