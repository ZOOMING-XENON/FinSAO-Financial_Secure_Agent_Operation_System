"""Standalone single-turn Agent API. Durable task APIs are added in P3."""

from __future__ import annotations

import asyncio
import hmac
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Annotated
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from fastapi import Depends, FastAPI, File, Header, HTTPException, UploadFile, status
from fastapi.responses import StreamingResponse
from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.postgres import PostgresSaver

from agent.beneficiary_ranking import ModelBeneficiaryRanker
from agent.capabilities import CapabilityBroker
from agent.checkpoints import AsyncFromSyncPostgresSaver
from agent.config import AgentSettings, get_agent_settings
from agent.context import SlotTracker
from agent.contracts import (
    AgentRequest,
    AgentResponse,
    AgentResponseStatus,
    TrustedAgentContext,
)
from agent.durable import DurableEvent, DurableTask, DurableTaskManager, ResumeRequest
from agent.expenses import ExpenseRouter
from agent.factory import build_model_provider
from agent.graph import build_runtime_agent_graph
from agent.hybrid import HybridPlanner, HybridRouter
from agent.jev_http import HttpJevAdapter
from agent.multimedia import MultimediaProvider, MultimediaSettings, MultimediaUnavailable
from agent.planning import BaselinePlanner, PlanVerifier
from agent.privacy_broker import PrivacyBroker
from agent.proactive import (
    ProactiveConfigRequest,
    ProactiveEventEngine,
    ProactiveSubscription,
    ProactiveSuggestion,
)
from agent.review import PrivacyPreservingReviewer
from agent.routing import RuleRouter
from agent.service import AgentService
from agent.transfer_reasoning import ModelTransferReasoner
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
_multimedia_vision_api_key = (
    _settings.multimedia_vision_api_key or _settings.deepseek_api_key
)
_multimedia = MultimediaProvider(
    MultimediaSettings(
        enabled=_settings.multimedia_enabled,
        vision_base_url=_settings.multimedia_vision_base_url
        or (_settings.deepseek_base_url if _settings.model_provider == "deepseek" else None),
        vision_api_key=(
            _multimedia_vision_api_key.get_secret_value()
            if _multimedia_vision_api_key is not None
            else None
        ),
        vision_model=_settings.multimedia_vision_model
        or (_settings.deepseek_model if _settings.model_provider == "deepseek" else None),
        speech_base_url=_settings.multimedia_speech_base_url,
        speech_api_key=(
            _settings.multimedia_speech_api_key.get_secret_value()
            if _settings.multimedia_speech_api_key
            else None
        ),
        speech_model=_settings.multimedia_speech_model,
        max_upload_bytes=_settings.multimedia_max_upload_bytes,
        vision_enabled=_settings.multimedia_vision_enabled,
        speech_enabled=_settings.multimedia_speech_enabled,
    )
)
_jev_adapter = (
    HttpJevAdapter(
        api_key=_settings.jev_api_key.get_secret_value(),
        base_url=_settings.jev_base_url,
        model=_settings.jev_model,
        timeout_seconds=_settings.jev_timeout_seconds,
    )
    if _settings.jev_enabled and _settings.jev_api_key is not None
    else None
)
_privacy_broker = PrivacyBroker() if _settings.privacy_broker_enabled else None
_gateway = ToolGateway(_registry)
_service = AgentService(
    router=HybridRouter(
        ExpenseRouter(
            RuleRouter(),
            enabled=_settings.expense_chat_enabled and _settings.expense_tracking_enabled,
            capture_enabled=(
                _settings.expense_capture_enabled
                and _settings.expense_capture_chat_enabled
            ),
        ),
        _model_provider,
        routing_mode=_settings.agent_routing_mode,
        jev_adapter=_jev_adapter,
        jev_enabled=_settings.jev_enabled,
        jev_min_confidence=_settings.jev_intent_min_confidence,
        jev_expense_min_confidence=_settings.jev_expense_intent_min_confidence,
        jev_max_injection=_settings.jev_max_injection,
        jev_min_in_scope=_settings.jev_min_in_scope,
        privacy_broker=_privacy_broker,
    ),
    slots=SlotTracker(),
    planner=HybridPlanner(
        BaselinePlanner(), _model_provider, privacy_broker=_privacy_broker
    ),
    verifier=PlanVerifier(_registry),
    capabilities=CapabilityBroker(_registry),
    gateway=_gateway,
    plan_reviewer=(
        PrivacyPreservingReviewer(_jev_adapter, _privacy_broker)
        if _settings.jev_enabled
        and _settings.jev_pass2_enabled
        and _jev_adapter is not None
        and _privacy_broker is not None
        else _jev_adapter
        if _settings.jev_enabled and _settings.jev_pass2_enabled
        else None
    ),
    plan_review_threshold=_settings.jev_plan_review_min,
    beneficiary_ranker=ModelBeneficiaryRanker(_model_provider),
    transfer_reasoner=ModelTransferReasoner(_model_provider),
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
        if _jev_adapter is not None:
            await _jev_adapter.close()
        await _multimedia.close()


app = FastAPI(title="FinPilot Agent API", version="0.1.0", lifespan=lifespan)


def _validate_upload(
    upload: UploadFile,
    content: bytes,
    allowed: set[str],
    kind: str,
) -> None:
    if upload.content_type not in allowed:
        raise HTTPException(status_code=415, detail={"code": "UNSUPPORTED_MEDIA_TYPE"})
    if not content:
        raise HTTPException(status_code=400, detail={"code": "EMPTY_UPLOAD"})
    if len(content) > _settings.multimedia_max_upload_bytes:
        raise HTTPException(status_code=413, detail={"code": "UPLOAD_TOO_LARGE"})
    if not _valid_signature(content, kind):
        raise HTTPException(status_code=415, detail={"code": "INVALID_MEDIA"})


def _valid_signature(content: bytes, kind: str) -> bool:
    if kind == "image":
        return (
            content.startswith(b"\xff\xd8\xff")
            or content.startswith(b"\x89PNG\r\n\x1a\n")
            or (content.startswith(b"RIFF") and content[8:12] == b"WEBP")
            or (content[4:8] == b"ftyp")
        )
    if kind == "audio":
        return (
            content.startswith(b"\x1aE\xdf\xa3")
            or (content.startswith(b"RIFF") and content[8:12] == b"WAVE")
            or content.startswith(b"ID3")
            or content[:2] in {b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"}
            or content[4:8] == b"ftyp"
            or content.startswith(b"OggS")
        )
    return False


def get_agent_service() -> AgentService:
    return _service


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


@app.post("/agent/receipts/parse")
async def parse_receipt(
    user_id: Annotated[UUID, Depends(get_trusted_user_id)],
    upload: UploadFile = File(...),  # noqa: B008
) -> dict[str, object]:
    del user_id
    content = await upload.read(_settings.multimedia_max_upload_bytes + 1)
    _validate_upload(
        upload,
        content,
        {"image/jpeg", "image/jpg", "image/png", "image/webp", "image/heic"},
        "image",
    )
    try:
        result = await _multimedia.extract_receipt(content, upload.content_type or "image/jpeg")
    except MultimediaUnavailable as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": "MULTIMEDIA_UNAVAILABLE", "message": str(exc)},
        ) from None
    return result.model_dump(mode="json")


@app.post("/agent/audio/transcribe")
async def transcribe_audio(
    user_id: Annotated[UUID, Depends(get_trusted_user_id)],
    upload: UploadFile = File(...),  # noqa: B008
) -> dict[str, object]:
    del user_id
    content = await upload.read(_settings.multimedia_max_upload_bytes + 1)
    _validate_upload(
        upload,
        content,
        {
            "audio/webm",
            "audio/wav",
            "audio/x-wav",
            "audio/mpeg",
            "audio/mp3",
            "audio/mp4",
            "audio/ogg",
            "audio/x-m4a",
        },
        "audio",
    )
    try:
        result = await _multimedia.transcribe(
            content,
            upload.filename or "voice.webm",
            upload.content_type or "audio/webm",
        )
    except MultimediaUnavailable as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": "MULTIMEDIA_UNAVAILABLE", "message": str(exc)},
        ) from None
    return result.model_dump(mode="json")


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
    try:
        return await asyncio.wait_for(
            service.handle(request, context),
            timeout=_settings.request_deadline_seconds,
        )
    except TimeoutError:
        return AgentResponse(
            request_id=request.request_id,
            session_id=request.session_id,
            task_id=context.task_id,
            status=AgentResponseStatus.NEEDS_CLARIFICATION,
            message="Request deadline exceeded; no action was executed.",
        )


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
    try:
        return await asyncio.wait_for(
            manager.create(request, context),
            timeout=_settings.request_deadline_seconds,
        )
    except TimeoutError:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail={"code": "REQUEST_DEADLINE_EXCEEDED"},
        ) from None


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
