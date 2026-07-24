"""Import every ORM model here so Alembic's autogenerate and
Base.metadata.create_all() see the complete schema."""
from app.db.base import Base  # noqa: F401
from app.models.business_object import BusinessObjectDefinition  # noqa: F401
from app.models.capability import AgentCapability, AgentOSCapability, TeamCapability  # noqa: F401
from app.models.execution_plan_run import (  # noqa: F401
    ExecutionPlanRun,
    ExecutionPlanRunStatus,
    ExecutionPlanStepRun,
    ExecutionStepStatus,
)
from app.models.hierarchy import Agent, AgentOS, Team  # noqa: F401
from app.models.memory import AgentMemory, MemoryType  # noqa: F401
from app.models.model_registry import ModelRegistry  # noqa: F401
from app.models.observation import ObservationType, RuntimeObservation  # noqa: F401
from app.models.prompt import Prompt, PromptStatus  # noqa: F401
from app.models.run import AgentEvent, AgentRun, EventType, RunStatus  # noqa: F401
from app.models.runtime_event import RuntimeEvent  # noqa: F401
from app.models.session import ChatMessage, ChatSession, MessageRole  # noqa: F401
from app.models.skill import AgentSkill, Skill, SkillCapability  # noqa: F401
from app.models.ui_metadata import UIMetadataEntry, UIMetadataKind  # noqa: F401
from app.models.workflow import Workflow, WorkflowStep, WorkflowStepType  # noqa: F401
from app.models.workflow_run import (  # noqa: F401
    WorkflowEvent,
    WorkflowEventType,
    WorkflowRun,
    WorkflowRunStatus,
    WorkflowRunStep,
    WorkflowStepStatus,
)
from app.models.workflow_schedule import ScheduleType, WorkflowSchedule  # noqa: F401
from app.models.workflow_webhook import WorkflowWebhook  # noqa: F401
__all__ = [
    "Base",
    "AgentOS",
    "Team",
    "Agent",
    "Prompt",
    "PromptStatus",
    "Skill",
    "SkillCapability",
    "AgentSkill",
    "AgentOSCapability",
    "TeamCapability",
    "AgentCapability",
    "ModelRegistry",
    "ChatSession",
    "ChatMessage",
    "MessageRole",
    "AgentRun",
    "RunStatus",
    "AgentEvent",
    "EventType",
    "AgentMemory",
    "MemoryType",
    "Workflow",
    "WorkflowStep",
    "WorkflowStepType",
    "WorkflowRun",
    "WorkflowRunStatus",
    "WorkflowRunStep",
    "WorkflowStepStatus",
    "WorkflowEvent",
    "WorkflowEventType",
    "UIMetadataEntry",
    "UIMetadataKind",
    "BusinessObjectDefinition",
    "RuntimeObservation",
    "ObservationType",
    "RuntimeEvent",
    "ExecutionPlanRun",
    "ExecutionPlanRunStatus",
    "ExecutionPlanStepRun",
    "ExecutionStepStatus",
    "WorkflowSchedule", "ScheduleType", "WorkflowWebhook"
]
