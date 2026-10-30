"""Versioned model-facing contracts separated from trusted execution state."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator, model_validator

from agent.privacy import SensitiveDataGuard
from agent.routing import REQUIRED_SLOTS_BY_INTENT, Intent


class StrictContract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ConversationRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    TOOL = "tool"


class TrustLabel(StrEnum):
    USER_INPUT = "USER_INPUT"
    SYSTEM_POLICY = "SYSTEM_POLICY"
    TOOL_VERIFIED = "TOOL_VERIFIED"
    EXTERNAL_UNTRUSTED = "EXTERNAL_UNTRUSTED"


class ConversationMessage(StrictContract):
    role: ConversationRole
    content: Annotated[str, Field(min_length=1, max_length=20_000)]
    trust: TrustLabel = TrustLabel.USER_INPUT

    @model_validator(mode="after")
    def validate_trust_source(self) -> ConversationMessage:
        if self.role == ConversationRole.USER and self.trust == TrustLabel.SYSTEM_POLICY:
            raise ValueError("user messages cannot be marked as system policy")
        return self

    @field_validator("content")
    @classmethod
    def reject_authentication_secrets(cls, value: str) -> str:
        return SensitiveDataGuard.ensure_safe(value)


class ClarificationConfirmation(StrictContract):
    """User-confirmed form values; this is data, never a new model prompt."""

    intent: Intent
    fields: dict[str, JsonValue] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def validate_fields(self) -> ClarificationConfirmation:
        required = set(REQUIRED_SLOTS_BY_INTENT.get(self.intent, ()))
        if not required:
            raise ValueError("intent does not accept a clarification confirmation")
        optional = {"include_balance"} if self.intent == Intent.TRANSFER else set()
        present = set(self.fields)
        forbidden = {
            "user_id",
            "authenticated_user_id",
            "authorization_ref",
            "authorization_reference",
            "mfa_code",
            "risk_tier",
            "approved",
            "idempotency_key",
        }
        if forbidden.intersection(present):
            raise ValueError("trusted fields are forbidden in confirmation data")
        if unexpected := present - required - optional:
            raise ValueError(f"unexpected confirmation fields: {sorted(unexpected)}")
        missing = {
            name
            for name in required
            if name not in self.fields or self.fields[name] in (None, "", [])
        }
        if missing:
            raise ValueError(f"missing confirmation fields: {sorted(missing)}")
        for value in self.fields.values():
            if isinstance(value, str):
                SensitiveDataGuard.ensure_safe(value)
        return self


class AgentRequest(StrictContract):
    schema_version: Literal["v1"] = "v1"
    request_id: UUID = Field(default_factory=uuid4)
    session_id: UUID
    message: Annotated[str, Field(min_length=1, max_length=20_000)]
    conversation: list[ConversationMessage] = Field(default_factory=list, max_length=100)
    confirmation: ClarificationConfirmation | None = None
    locale: Literal["zh-CN", "en-US"] = "zh-CN"

    @field_validator("message")
    @classmethod
    def reject_authentication_secrets(cls, value: str) -> str:
        return SensitiveDataGuard.ensure_safe(value)


class TrustedAgentContext:
    """Server-only context. Never deserialize this object from AgentRequest/model output."""

    __slots__ = (
        "authenticated_user_id",
        "authorization_reference",
        "session_id",
        "task_id",
        "trace_id",
    )

    def __init__(
        self,
        *,
        authenticated_user_id: UUID,
        session_id: UUID,
        task_id: UUID,
        trace_id: UUID,
        authorization_reference: str | None = None,
    ) -> None:
        self.authenticated_user_id = authenticated_user_id
        self.session_id = session_id
        self.task_id = task_id
        self.trace_id = trace_id
        self.authorization_reference = authorization_reference


class ToolCall(StrictContract):
    tool_name: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")]
    arguments: dict[str, JsonValue] = Field(default_factory=dict)

    @field_validator("arguments")
    @classmethod
    def reject_trusted_fields(cls, value: dict[str, JsonValue]) -> dict[str, JsonValue]:
        forbidden = {
            "user_id",
            "authenticated_user_id",
            "risk_tier",
            "approved",
            "mfa_code",
            "authorization_ref",
            "authorization_reference",
        }
        present = forbidden.intersection(value)
        if present:
            raise ValueError(
                f"trusted fields are forbidden in model tool arguments: {sorted(present)}"
            )
        return value


class ArgumentSourceKind(StrEnum):
    USER_EXPLICIT = "USER_EXPLICIT"
    TOOL_VERIFIED = "TOOL_VERIFIED"
    SYSTEM_CONSTANT = "SYSTEM_CONSTANT"
    MODEL_INFERRED = "MODEL_INFERRED"


class ArgumentSource(StrictContract):
    kind: ArgumentSourceKind
    reference: Annotated[str, Field(min_length=1, max_length=200)]


class PlanStep(StrictContract):
    step_id: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")]
    purpose: Annotated[str, Field(min_length=1, max_length=500)]
    depends_on: list[str] = Field(default_factory=list, max_length=20)
    tool_call: ToolCall | None = None
    argument_sources: dict[str, ArgumentSource] = Field(default_factory=dict)
    requires_user_input: bool = False


class TaskPlan(StrictContract):
    schema_version: Literal["v1"] = "v1"
    plan_id: UUID = Field(default_factory=uuid4)
    goal: Annotated[str, Field(min_length=1, max_length=1_000)]
    steps: Annotated[list[PlanStep], Field(min_length=1, max_length=50)]

    @model_validator(mode="after")
    def validate_unique_step_ids(self) -> TaskPlan:
        ids = [step.step_id for step in self.steps]
        if len(ids) != len(set(ids)):
            raise ValueError("step_id values must be unique")
        return self


class AgentResponseStatus(StrEnum):
    COMPLETED = "COMPLETED"
    NEEDS_CLARIFICATION = "NEEDS_CLARIFICATION"
    WAITING_APPROVAL = "WAITING_APPROVAL"
    FAILED = "FAILED"


class ClarificationOption(StrictContract):
    value: str
    label: str


class ClarificationField(StrictContract):
    name: str
    label: str
    input_type: Literal["text", "date", "month", "amount", "select", "combobox"] = "text"
    required: bool = True
    value: JsonValue | None = None
    inferred: bool = False
    options: list[ClarificationOption] = Field(default_factory=list)


class ClarificationPayload(StrictContract):
    kind: Literal["MISSING_FIELDS", "CONFIRM_INFERRED", "CONFIRM_RESOLVED_BENEFICIARY"]
    intent: str
    fields: list[ClarificationField]


class AgentError(StrictContract):
    code: str
    message: str
    retryable: bool = False


class AgentResponse(StrictContract):
    schema_version: Literal["v1"] = "v1"
    request_id: UUID
    session_id: UUID
    task_id: UUID
    status: AgentResponseStatus
    message: str
    plan: TaskPlan | None = None
    result: JsonValue | None = None
    error: AgentError | None = None


class AgentEventType(StrEnum):
    REQUEST_ACCEPTED = "REQUEST_ACCEPTED"
    PLAN_CREATED = "PLAN_CREATED"
    TOOL_STARTED = "TOOL_STARTED"
    TOOL_FINISHED = "TOOL_FINISHED"
    WAITING_APPROVAL = "WAITING_APPROVAL"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class AgentEvent(StrictContract):
    schema_version: Literal["v1"] = "v1"
    event_id: UUID = Field(default_factory=uuid4)
    task_id: UUID
    sequence: Annotated[int, Field(ge=0)]
    event_type: AgentEventType
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    public_message: str | None = None
    data: dict[str, JsonValue] = Field(default_factory=dict)
