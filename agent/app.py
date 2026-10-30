"""Standalone single-turn Agent API. Durable task APIs are added in P3."""

from __future__ import annotations

import hmac
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Annotated
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from fastapi import Depends, FastAPI, Header, HTTPException, status
from fastapi.responses import StreamingResponse
from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.postgres import PostgresSaver

from agent.capabilities import CapabilityBroker
from agent.checkpoints import AsyncFromSyncPostgresSaver
from agent.config import AgentSettings, get_agent_settings
from agent.context import SlotTracker
from agent.contracts import (
    AgentRequest,
    AgentResponse,
    TaskDecompositionResponse,
    TrustedAgentContext,
)
from agent.durable import DurableEvent, DurableTask, DurableTaskManager, ResumeRequest
from agent.factory import build_model_provider
from agent.graph import build_runtime_agent_graph
from agent.hybrid import HybridPlanner, HybridRouter
from agent.planning import BaselinePlanner, PlanVerifier
from agent.proactive import (
    ProactiveConfigRequest,
    ProactiveEventEngine,
    ProactiveSubscription,
    ProactiveSuggestion,
)
from agent.routing import RuleRouter
from agent.service import AgentService
from agent_persistence import SqlAlchemyTaskStore
from agent_tools.client import BankingHttpClient, StaticServiceAuthenticator
from agent_tools.gateway import ToolGateway
from agent_tools.registry import ToolRegistry
from agent_tools.tools import register_default_tools

_settings = get_agent_settings()
_banking_client = BankingHttpClient(
    _settings.banking_base_url,
    StaticServiceAuthenticator(_settings.banking_service_token.get_secret_value()),
)
_registry = ToolRegistry()
register_default_tools(_registry, _banking_client)
_model_provider = build_model_provider(_settings)
_gateway = ToolGateway(_registry)
_router = HybridRouter(
    RuleRouter(), _model_provider, routing_mode=_settings.agent_routing_mode
)
_service = AgentService(
    router=_router,
    slots=SlotTracker(),
    planner=HybridPlanner(BaselinePlanner(), _model_provider),
    verifier=PlanVerifier(_registry),
    capabilities=CapabilityBroker(_registry),
    gateway=_gateway,
)
_task_store = SqlAlchemyTaskStore(_settings.agent_database_url)
_runtime_graph = build_runtime_agent_graph(_service, _gateway, MemorySaver())
_task_manager = DurableTaskManager(_service, _gateway, _task_store, _runtime_graph)
_proactive_engine = ProactiveEventEngine(_task_store)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    global _task_manager
    try:
        if _settings.agent_checkpoint_database_url:
            with PostgresSaver.from_conn_string(_settings.agent_checkpoint_database_url) as saver:
                saver.setup()
                graph = build_runtime_agent_graph(
                    _service, _gateway, AsyncFromSyncPostgresSaver(saver)
                )
                _task_manager = DurableTaskManager(_service, _gateway, _task_store, graph)
                yield
        else:
            yield
    finally:
        await _banking_client.close()
        if _model_provider is not None:
            await _model_provider.close()


app = FastAPI(title="FinPilot Agent API", version="0.1.0", lifespan=lifespan)


def get_agent_service() -> AgentService:
    return _service


def get_agent_router() -> HybridRouter:
    return _router


def get_task_manager() -> DurableTaskManager:
    return _task_manager


def get_task_store() -> SqlAlchemyTaskStore:
    return _task_store


def get_proactive_engine() -> ProactiveEventEngine:
    return _proactive_engine


def get_trusted_user_id(
    settings: Annotated[AgentSettings, Depends(get_agent_settings)],
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
) -> UUID:
    expected = settings.agent_api_token.get_secret_value()
    supplied = authorization.removeprefix("Bearer ") if authorization else ""
    if (
        settings.app_env != "development"
        or settings.agent_development_user_id is None
        or not expected
        or not hmac.compare_digest(supplied, expected)
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "AUTHENTICATION_REQUIRED", "message": "valid API token required"},
        )
    return settings.agent_development_user_id


@app.post("/agent/requests", response_model=AgentResponse)
async def create_agent_request(
    request: AgentRequest,
    service: Annotated[AgentService, Depends(get_agent_service)],
    user_id: Annotated[UUID, Depends(get_trusted_user_id)],
    x_trace_id: Annotated[str | None, Header(alias="X-Trace-Id")] = None,
) -> AgentResponse:
    try:
        trace_id = UUID(x_trace_id) if x_trace_id else uuid4()
    except ValueError:
        trace_id = uuid4()
    context = TrustedAgentContext(
        authenticated_user_id=user_id,
        session_id=request.session_id,
        task_id=uuid4(),
        trace_id=trace_id,
    )
    return await service.handle(request, context)


@app.post("/agent/decompose", response_model=TaskDecompositionResponse)
async def decompose_agent_request(
    request: AgentRequest,
    router: Annotated[HybridRouter, Depends(get_agent_router)],
    _: Annotated[UUID, Depends(get_trusted_user_id)],
) -> TaskDecompositionResponse:
    tasks = await router.decompose(request.message, conversation=request.conversation)
    return TaskDecompositionResponse(tasks=tasks)


@app.post("/agent/tasks", response_model=DurableTask)
async def create_task(
    request: AgentRequest,
    manager: Annotated[DurableTaskManager, Depends(get_task_manager)],
    user_id: Annotated[UUID, Depends(get_trusted_user_id)],
    x_trace_id: Annotated[str | None, Header(alias="X-Trace-Id")] = None,
) -> DurableTask:
    try:
        trace_id = UUID(x_trace_id) if x_trace_id else uuid4()
    except ValueError:
        trace_id = uuid4()
    context = TrustedAgentContext(
        authenticated_user_id=user_id,
        session_id=request.session_id,
        task_id=uuid4(),
        trace_id=trace_id,
    )
    return await manager.create(request, context)


@app.get("/agent/tasks/{task_id}", response_model=DurableTask)
def get_task(
    task_id: UUID,
    store: Annotated[SqlAlchemyTaskStore, Depends(get_task_store)],
    user_id: Annotated[UUID, Depends(get_trusted_user_id)],
) -> DurableTask:
    task = store.get_task(task_id=task_id, user_id=user_id)
    if task is None:
        raise HTTPException(status_code=404, detail={"code": "TASK_NOT_FOUND"})
    return task


@app.post("/agent/tasks/{task_id}/resume", response_model=DurableTask)
async def resume_task(
    task_id: UUID,
    request: ResumeRequest,
    manager: Annotated[DurableTaskManager, Depends(get_task_manager)],
    user_id: Annotated[UUID, Depends(get_trusted_user_id)],
) -> DurableTask:
    try:
        return await manager.resume(
            task_id=task_id,
            user_id=user_id,
            authorization_reference=request.authorization_reference,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail={"code": "TASK_NOT_FOUND"}) from None


@app.post("/agent/tasks/{task_id}/cancel", response_model=DurableTask)
def cancel_task(
    task_id: UUID,
    manager: Annotated[DurableTaskManager, Depends(get_task_manager)],
    user_id: Annotated[UUID, Depends(get_trusted_user_id)],
) -> DurableTask:
    try:
        return manager.cancel(task_id=task_id, user_id=user_id)
    except KeyError:
        raise HTTPException(status_code=404, detail={"code": "TASK_NOT_FOUND"}) from None


@app.post("/agent/tasks/{task_id}/takeover", response_model=DurableTask)
def takeover_task(
    task_id: UUID,
    manager: Annotated[DurableTaskManager, Depends(get_task_manager)],
    user_id: Annotated[UUID, Depends(get_trusted_user_id)],
) -> DurableTask:
    try:
        return manager.takeover(task_id=task_id, user_id=user_id)
    except KeyError:
        raise HTTPException(status_code=404, detail={"code": "TASK_NOT_FOUND"}) from None


@app.get("/agent/tasks/{task_id}/events", response_model=list[DurableEvent])
def list_task_events(
    task_id: UUID,
    store: Annotated[SqlAlchemyTaskStore, Depends(get_task_store)],
    user_id: Annotated[UUID, Depends(get_trusted_user_id)],
    after: int = 0,
) -> list[DurableEvent]:
    try:
        return store.list_events(task_id=task_id, user_id=user_id, after_sequence=after)
    except KeyError:
        raise HTTPException(status_code=404, detail={"code": "TASK_NOT_FOUND"}) from None


@app.get("/agent/tasks/{task_id}/events/stream")
def stream_task_events(
    task_id: UUID,
    store: Annotated[SqlAlchemyTaskStore, Depends(get_task_store)],
    user_id: Annotated[UUID, Depends(get_trusted_user_id)],
    last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
) -> StreamingResponse:
    after = int(last_event_id) if last_event_id and last_event_id.isdigit() else 0

    async def generate() -> AsyncIterator[str]:
        events = store.list_events(task_id=task_id, user_id=user_id, after_sequence=after)
        for event in events:
            data = json.dumps(event.model_dump(mode="json"), ensure_ascii=False)
            yield f"id: {event.sequence}\nevent: {event.event_type}\ndata: {data}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


@app.put("/agent/proactive/subscriptions/{event_kind}", response_model=ProactiveSubscription)
def configure_proactive_subscription(
    event_kind: str,
    request: ProactiveConfigRequest,
    engine: Annotated[ProactiveEventEngine, Depends(get_proactive_engine)],
    user_id: Annotated[UUID, Depends(get_trusted_user_id)],
) -> ProactiveSubscription:
    return engine.configure(
        user_id=user_id,
        event_kind=event_kind,
        enabled=request.enabled,
        quiet_start=request.quiet_start,
        quiet_end=request.quiet_end,
        minimum_interval_minutes=request.minimum_interval_minutes,
    )


@app.post("/agent/proactive/suggestions/{event_kind}", response_model=ProactiveSuggestion | None)
def emit_proactive_suggestion(
    event_kind: str,
    engine: Annotated[ProactiveEventEngine, Depends(get_proactive_engine)],
    user_id: Annotated[UUID, Depends(get_trusted_user_id)],
) -> ProactiveSuggestion | None:
    return engine.suggest(
        user_id=user_id,
        event_kind=event_kind,
        now=datetime.now(ZoneInfo("Asia/Shanghai")),
    )
