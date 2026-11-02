"""Public contracts for multi-turn, multi-intent task bundles."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from agent.contracts import ClarificationPayload, ConversationMessage, TaskPlan
from agent.routing import Intent


class BundleStatus(StrEnum):
    RUNNING = "RUNNING"
    NEEDS_CLARIFICATION = "NEEDS_CLARIFICATION"
    NEEDS_CONFIRMATION = "NEEDS_CONFIRMATION"
    WAITING_APPROVAL = "WAITING_APPROVAL"
    PARTIALLY_COMPLETED = "PARTIALLY_COMPLETED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class BundleItemStatus(StrEnum):
    PROPOSED = "PROPOSED"
    NEEDS_CLARIFICATION = "NEEDS_CLARIFICATION"
    NEEDS_CONFIRMATION = "NEEDS_CONFIRMATION"
    WAITING_APPROVAL = "WAITING_APPROVAL"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    DEFERRED_UNSUPPORTED = "DEFERRED_UNSUPPORTED"


class ProposedTask(BaseModel):
    model_config = ConfigDict(extra="forbid")
    item_key: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,39}$")]
    intent: Intent
    evidence: Annotated[str, Field(min_length=1, max_length=1_000)]
    proposed_slots: dict[str, JsonValue] = Field(default_factory=dict, max_length=20)
    depends_on: list[str] = Field(default_factory=list, max_length=5)


class TaskDecomposition(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tasks: Annotated[list[ProposedTask], Field(min_length=1, max_length=5)]
    needs_clarification: bool = False
    clarification_question: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def validate_keys(self) -> TaskDecomposition:
        keys = [task.item_key for task in self.tasks]
        if len(keys) != len(set(keys)):
            raise ValueError("task item keys must be unique")
        known = set(keys)
        for task in self.tasks:
            if task.item_key in task.depends_on or not set(task.depends_on).issubset(known):
                raise ValueError("task dependencies must reference other bundle items")
        if self.needs_clarification and not self.clarification_question:
            raise ValueError("clarification question is required")
        return self


class BundleItemConfirmation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    item_id: UUID
    intent: Intent
    fields: dict[str, JsonValue] = Field(min_length=1, max_length=20)


class AgentTurnRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["v2"] = "v2"
    request_id: UUID = Field(default_factory=uuid4)
    session_id: UUID
    bundle_id: UUID | None = None
    reply_to_item_id: UUID | None = None
    message: Annotated[str, Field(min_length=1, max_length=20_000)]
    conversation: list[ConversationMessage] = Field(default_factory=list, max_length=100)
    confirmation: BundleItemConfirmation | None = None
    locale: Literal["zh-CN", "en-US"] = "zh-CN"

    @model_validator(mode="after")
    def validate_continuation(self) -> AgentTurnRequest:
        if self.confirmation is not None and self.bundle_id is None:
            raise ValueError("confirmation requires a bundle")
        if self.reply_to_item_id is not None and self.bundle_id is None:
            raise ValueError("reply target requires a bundle")
        if self.confirmation is not None and self.reply_to_item_id is not None:
            raise ValueError("send a form confirmation or a text reply, not both")
        return self


class AgentTaskItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    item_id: UUID
    item_key: str
    intent: Intent
    evidence: str
    proposed_slots: dict[str, JsonValue] = Field(default_factory=dict)
    status: BundleItemStatus
    depends_on: list[str] = Field(default_factory=list)
    clarification: ClarificationPayload | None = None
    plan: TaskPlan | None = None
    result: JsonValue | None = None
    task_id: UUID | None = None
    error_code: str | None = None


class AgentTaskBundle(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["v2"] = "v2"
    bundle_id: UUID
    session_id: UUID
    original_request: str
    status: BundleStatus
    active_item_id: UUID | None = None
    items: list[AgentTaskItem]
    revision: int = 1


class AgentTurnResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["v2"] = "v2"
    request_id: UUID
    session_id: UUID
    bundle: AgentTaskBundle
    public_message: str


class BundleResumeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    authorization_reference: str = Field(min_length=1, max_length=500)
