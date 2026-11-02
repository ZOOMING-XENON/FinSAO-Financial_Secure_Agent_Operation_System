"""Durable task contracts, repository protocol and recovery orchestration."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Protocol
from uuid import UUID, uuid4

from langgraph.types import Command
from pydantic import BaseModel, ConfigDict, Field, JsonValue

from agent.contracts import AgentRequest, AgentResponse, AgentResponseStatus, TrustedAgentContext
from agent.service import AgentService, Gateway
from agent_tools.contracts import ExecutionContext, ToolResultStatus


class TaskStatus(StrEnum):
    RUNNING = "RUNNING"
    NEEDS_CLARIFICATION = "NEEDS_CLARIFICATION"
    WAITING_APPROVAL = "WAITING_APPROVAL"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    HUMAN_TAKEOVER = "HUMAN_TAKEOVER"


class DurableTask(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: UUID
    session_id: UUID
    user_id: UUID
    trace_id: UUID
    status: TaskStatus
    request_message: str
    public_message: str | None = None
    plan: dict[str, JsonValue] | None = None
    result: JsonValue | None = None
    error_code: str | None = None
    recovery_action: str | None = None
    version: int
    created_at: datetime
    updated_at: datetime


class DurableEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: UUID
    task_id: UUID
    sequence: int = Field(ge=1)
    event_type: str
    payload: dict[str, JsonValue]
    created_at: datetime


class TaskStore(Protocol):
    def create_from_response(
        self, *, request: AgentRequest, context: TrustedAgentContext, response: AgentResponse
    ) -> DurableTask: ...

    def get_task(self, *, task_id: UUID, user_id: UUID) -> DurableTask | None: ...
    def claim_waiting(self, *, task_id: UUID, user_id: UUID) -> DurableTask | None: ...
    def transition(
        self,
        *,
        task_id: UUID,
        user_id: UUID,
        status: TaskStatus,
        result: JsonValue | None = None,
        error_code: str | None = None,
        recovery_action: str | None = None,
        public_message: str | None = None,
    ) -> DurableTask: ...

    def append_event(
        self, *, task_id: UUID, event_type: str, payload: dict[str, JsonValue]
    ) -> DurableEvent: ...

    def list_events(
        self, *, task_id: UUID, user_id: UUID, after_sequence: int = 0
    ) -> list[DurableEvent]: ...


class ResumeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    authorization_reference: str = Field(min_length=1, max_length=500)


class DurableTaskManager:
    def __init__(
        self,
        service: AgentService,
        gateway: Gateway,
        store: TaskStore,
        graph: Any | None = None,
    ) -> None:
        self._service = service
        self._gateway = gateway
        self._store = store
        self._graph = graph

    async def create(self, request: AgentRequest, context: TrustedAgentContext) -> DurableTask:
        if self._graph is None:
            response = await self._service.handle(request, context)
        else:
            state = await self._graph.ainvoke(
                {
                    "task_id": str(context.task_id),
                    "session_id": str(context.session_id),
                    "trace_id": str(context.trace_id),
                    "request_text": request.message,
                    "request": request.model_dump(mode="json"),
                    "context": {
                        "authenticated_user_id": str(context.authenticated_user_id),
                        "session_id": str(context.session_id),
                        "task_id": str(context.task_id),
                        "trace_id": str(context.trace_id),
                        "expected_intent": (
                            context.expected_intent.value if context.expected_intent else None
                        ),
                        "expected_slots": context.expected_slots,
                    },
                },
                {"configurable": {"thread_id": str(context.task_id)}},
            )
            response = AgentResponse.model_validate(state["response"])
        task = self._store.create_from_response(request=request, context=context, response=response)
        self._store.append_event(
            task_id=task.id,
            event_type="TASK_CREATED",
            payload={"status": task.status.value},
        )
        return task

    async def resume(
        self, *, task_id: UUID, user_id: UUID, authorization_reference: str
    ) -> DurableTask:
        task = self._store.claim_waiting(task_id=task_id, user_id=user_id)
        if task is None:
            existing = self._store.get_task(task_id=task_id, user_id=user_id)
            if existing is None:
                raise KeyError(task_id)
            return existing
        if self._graph is not None:
            state = await self._graph.ainvoke(
                Command(resume={"authorization_reference": authorization_reference}),
                {"configurable": {"thread_id": str(task_id)}},
            )
            response = AgentResponse.model_validate(state["response"])
            target_status = response_status_to_task(response.status)
            return self._store.transition(
                task_id=task.id,
                user_id=user_id,
                status=target_status,
                result=response.result,
                error_code=response.error.code if response.error else None,
                public_message=response.message,
            )
        draft_id = self._draft_id(task)
        context = ExecutionContext(
            authenticated_user_id=user_id,
            session_id=task.session_id,
            task_id=task.id,
            trace_id=task.trace_id,
            authorization_reference=authorization_reference,
        )
        result = await self._gateway.execute(
            tool_name="commit_transfer", arguments={"draft_id": draft_id}, context=context
        )
        if result.status == ToolResultStatus.SUCCESS:
            payload = result.data.model_dump(mode="json") if result.data else None
            updated = self._store.transition(
                task_id=task.id,
                user_id=user_id,
                status=TaskStatus.COMPLETED,
                result=payload,
            )
            self._store.append_event(
                task_id=task.id, event_type="TASK_COMPLETED", payload={"status": "COMPLETED"}
            )
            return updated
        if result.error_code == "UNKNOWN_OUTCOME":
            reconciled = await self._gateway.execute(
                tool_name="get_transfer_status",
                arguments={"transfer_id": draft_id},
                context=context,
            )
            if reconciled.status == ToolResultStatus.SUCCESS and reconciled.data is not None:
                payload = reconciled.data.model_dump(mode="json")
                if str(payload.get("status")) == "COMPLETED":
                    return self._store.transition(
                        task_id=task.id,
                        user_id=user_id,
                        status=TaskStatus.COMPLETED,
                        result=payload,
                    )
            return self._store.transition(
                task_id=task.id,
                user_id=user_id,
                status=TaskStatus.FAILED,
                error_code="UNKNOWN_OUTCOME",
                recovery_action="RECONCILE_STATUS",
            )
        return self._store.transition(
            task_id=task.id,
            user_id=user_id,
            status=TaskStatus.FAILED,
            error_code=result.error_code or "COMMIT_FAILED",
            recovery_action="REVIEW_OR_RETRY",
        )

    def cancel(self, *, task_id: UUID, user_id: UUID) -> DurableTask:
        return self._store.transition(task_id=task_id, user_id=user_id, status=TaskStatus.CANCELLED)

    def takeover(self, *, task_id: UUID, user_id: UUID) -> DurableTask:
        return self._store.transition(
            task_id=task_id, user_id=user_id, status=TaskStatus.HUMAN_TAKEOVER
        )

    @staticmethod
    def _draft_id(task: DurableTask) -> str:
        if not isinstance(task.result, dict) or not task.result.get("id"):
            raise ValueError("task has no persisted draft id")
        return str(task.result["id"])


def response_status_to_task(status: AgentResponseStatus) -> TaskStatus:
    return {
        AgentResponseStatus.COMPLETED: TaskStatus.COMPLETED,
        AgentResponseStatus.WAITING_APPROVAL: TaskStatus.WAITING_APPROVAL,
        AgentResponseStatus.FAILED: TaskStatus.FAILED,
        AgentResponseStatus.NEEDS_CLARIFICATION: TaskStatus.NEEDS_CLARIFICATION,
    }[status]


def utcnow() -> datetime:
    return datetime.now(UTC)


def new_event_id() -> UUID:
    return uuid4()
