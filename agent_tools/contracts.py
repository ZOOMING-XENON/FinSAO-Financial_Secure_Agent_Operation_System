from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Generic, TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict

InputT = TypeVar("InputT", bound=BaseModel)
OutputT = TypeVar("OutputT", bound=BaseModel)


@dataclass(frozen=True, slots=True)
class ExecutionContext:
    authenticated_user_id: UUID
    session_id: UUID
    task_id: UUID
    trace_id: UUID
    authorization_reference: str | None = None


class ToolResultStatus(StrEnum):
    SUCCESS = "SUCCESS"
    WAITING_APPROVAL = "WAITING_APPROVAL"
    MFA_REQUIRED = "MFA_REQUIRED"
    DENIED = "DENIED"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    EXECUTION_ERROR = "EXECUTION_ERROR"


class ToolResult(BaseModel, Generic[OutputT]):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    status: ToolResultStatus
    data: OutputT | None = None
    error_code: str | None = None
    message: str | None = None


class BaseBankingTool(ABC, Generic[InputT, OutputT]):
    name: str
    description: str
    action: str
    risk_policy: str
    mutates_data: bool = False
    input_model: type[InputT]
    output_model: type[OutputT]

    @abstractmethod
    async def execute(self, input_data: InputT, context: ExecutionContext) -> OutputT: ...

    def metadata(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "action": self.action,
            "risk_policy": self.risk_policy,
            "mutates_data": self.mutates_data,
            "input_schema": self.input_model.model_json_schema(),
            "output_schema": self.output_model.model_json_schema(),
        }
