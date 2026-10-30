from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import SecretStr

from agent.app import (
    app,
    get_agent_router,
    get_agent_service,
    get_task_store,
    get_trusted_user_id,
)
from agent.config import AgentSettings
from agent.contracts import AgentResponse, AgentResponseStatus, TrustedAgentContext
from agent.durable import DurableEvent


class CapturingService:
    def __init__(self) -> None:
        self.context: TrustedAgentContext | None = None

    async def handle(self, request, context: TrustedAgentContext):  # type: ignore[no-untyped-def]
        self.context = context
        return AgentResponse(
            request_id=request.request_id,
            session_id=request.session_id,
            task_id=context.task_id,
            status=AgentResponseStatus.COMPLETED,
            message="verified fixture",
            result={"source": "banking-core-fixture"},
        )


class DecompositionRouter:
    async def decompose(self, text: str, *, conversation=None):  # type: ignore[no-untyped-def]
        del text, conversation
        return ["创建100元晚餐预算", "给妈妈转账20元"]


def test_agent_decomposition_endpoint_uses_llm_router() -> None:
    app.dependency_overrides[get_agent_router] = lambda: DecompositionRouter()
    app.dependency_overrides[get_trusted_user_id] = lambda: uuid4()
    try:
        with TestClient(app) as client:
            response = client.post(
                "/agent/decompose",
                json={
                    "session_id": str(uuid4()),
                    "message": "创建晚餐预算，并给妈妈转账20元",
                },
            )
        assert response.status_code == 200
        assert response.json()["tasks"] == ["创建100元晚餐预算", "给妈妈转账20元"]
    finally:
        app.dependency_overrides.clear()


def test_agent_api_uses_server_identity_and_rejects_extra_identity_field() -> None:
    service = CapturingService()
    trusted_user = uuid4()
    app.dependency_overrides[get_agent_service] = lambda: service
    app.dependency_overrides[get_trusted_user_id] = lambda: trusted_user
    try:
        with TestClient(app) as client:
            session_id = uuid4()
            response = client.post(
                "/agent/requests",
                headers={"X-User-Id": str(uuid4())},
                json={"session_id": str(session_id), "message": "查看我的账户"},
            )
            assert response.status_code == 200
            assert service.context is not None
            assert service.context.authenticated_user_id == trusted_user
            forged = client.post(
                "/agent/requests",
                json={
                    "session_id": str(session_id),
                    "message": "查看我的账户",
                    "authenticated_user_id": str(uuid4()),
                },
            )
            assert forged.status_code == 422
    finally:
        app.dependency_overrides.clear()


class EventStoreFixture:
    def __init__(self, task_id: UUID) -> None:
        self.events = [
            DurableEvent(
                id=uuid4(),
                task_id=task_id,
                sequence=sequence,
                event_type=f"EVENT_{sequence}",
                payload={"sequence": sequence},
                created_at=datetime.now(UTC),
            )
            for sequence in (1, 2)
        ]

    def list_events(
        self, *, task_id: UUID, user_id: UUID, after_sequence: int = 0
    ) -> list[DurableEvent]:
        del task_id, user_id
        return [event for event in self.events if event.sequence > after_sequence]


def test_sse_reconnect_uses_last_event_id() -> None:
    task_id = uuid4()
    app.dependency_overrides[get_task_store] = lambda: EventStoreFixture(task_id)
    app.dependency_overrides[get_trusted_user_id] = lambda: uuid4()
    try:
        with TestClient(app) as client:
            response = client.get(
                f"/agent/tasks/{task_id}/events/stream", headers={"Last-Event-ID": "1"}
            )
            assert response.status_code == 200
            assert "id: 2" in response.text
            assert "id: 1" not in response.text
            assert "event: EVENT_2" in response.text
    finally:
        app.dependency_overrides.clear()


def test_agent_identity_requires_proxy_service_token() -> None:
    user_id = uuid4()
    settings = AgentSettings(
        agent_development_user_id=user_id,
        agent_api_token=SecretStr("agent-test-secret"),
    )
    with pytest.raises(HTTPException) as exc_info:
        get_trusted_user_id(settings, None)
    assert exc_info.value.status_code == 401
    assert get_trusted_user_id(settings, "Bearer agent-test-secret") == user_id
