from __future__ import annotations

from datetime import date
from typing import Any
from unittest.mock import Mock
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command
from pydantic import BaseModel, ValidationError

from agent.capabilities import CapabilityBroker
from agent.context import SlotTracker
from agent.contracts import (
    AgentRequest,
    AgentResponseStatus,
    ConversationMessage,
    ConversationRole,
    TaskPlan,
    TrustedAgentContext,
)
from agent.graph import build_runtime_agent_graph
from agent.hybrid import HybridPlanner, HybridRouter
from agent.planning import BaselinePlanner, PlanVerifier
from agent.providers import FakeModelProvider
from agent.routing import Intent, IntentResult, Route, RuleRouter
from agent.service import AgentService
from agent_tools.contracts import ExecutionContext, ToolResult, ToolResultStatus
from agent_tools.registry import ToolRegistry
from agent_tools.tools import register_default_tools
from banking_core.app.main import app


class FixtureOutput(BaseModel):
    value: str


class StatusOutput(BaseModel):
    status: str


class CapturingGateway:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def execute(
        self, *, tool_name: str, arguments: dict[str, Any], context: ExecutionContext
    ) -> ToolResult[Any]:
        del arguments, context
        self.calls.append(tool_name)
        return ToolResult(
            status=ToolResultStatus.SUCCESS,
            data=FixtureOutput(value="verified-core-result"),
        )


class FailIfRouted:
    def route(self, text: str, *, conversation: list[Any] | None = None) -> IntentResult:
        del text, conversation
        raise AssertionError("a confirmed form must not be sent through the router or LLM")


class ReconciliationGateway:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def execute(
        self, *, tool_name: str, arguments: dict[str, Any], context: ExecutionContext
    ) -> ToolResult[Any]:
        del arguments
        self.calls.append(tool_name)
        if tool_name == "freeze_card" and context.authorization_reference is None:
            return ToolResult(status=ToolResultStatus.WAITING_APPROVAL)
        if tool_name == "freeze_card":
            return ToolResult(
                status=ToolResultStatus.EXECUTION_ERROR,
                error_code="UNKNOWN_OUTCOME",
            )
        if tool_name == "get_card_status":
            return ToolResult(
                status=ToolResultStatus.SUCCESS,
                data=StatusOutput(status="FROZEN"),
            )
        raise AssertionError(tool_name)


class ClarificationGateway:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.arguments: dict[str, dict[str, Any]] = {}
        self.destination_id = uuid4()

    async def execute(
        self, *, tool_name: str, arguments: dict[str, Any], context: ExecutionContext
    ) -> ToolResult[Any]:
        del context
        self.calls.append(tool_name)
        self.arguments[tool_name] = arguments
        if tool_name == "get_accounts":
            class Accounts(BaseModel):
                accounts: list[dict[str, Any]]

            return ToolResult(
                status=ToolResultStatus.SUCCESS,
                data=Accounts(
                    accounts=[
                        {
                            "id": str(uuid4()),
                            "name": "日常账户",
                            "account_number": "DEMO-001",
                            "status": "ACTIVE",
                        }
                    ]
                ),
            )
        if tool_name == "list_beneficiaries":
            class Beneficiaries(BaseModel):
                beneficiaries: list[dict[str, Any]]

            return ToolResult(
                status=ToolResultStatus.SUCCESS,
                data=Beneficiaries(
                    beneficiaries=[
                        {
                            "destination_account_id": str(self.destination_id),
                            "destination_account_number": "DEMO0301000001",
                            "name": "妈妈",
                            "nickname": None,
                        }
                    ]
                ),
            )
        if tool_name == "resolve_beneficiary":
            class Resolution(BaseModel):
                status: str
                matches: list[dict[str, Any]]

            return ToolResult(
                status=ToolResultStatus.SUCCESS,
                data=Resolution(
                    status="RESOLVED",
                    matches=[
                        {
                            "destination_account_id": str(self.destination_id),
                            "destination_account_number": "DEMO0301000001",
                            "name": "妈妈",
                            "nickname": None,
                        }
                    ],
                ),
            )
        raise AssertionError(tool_name)


def build_service() -> tuple[AgentService, CapturingGateway]:
    registry = ToolRegistry()
    register_default_tools(registry, Mock())
    gateway = CapturingGateway()
    service = AgentService(
        router=RuleRouter(),
        slots=SlotTracker(),
        planner=BaselinePlanner(),
        verifier=PlanVerifier(registry),
        capabilities=CapabilityBroker(registry),
        gateway=gateway,
    )
    return service, gateway


@pytest.mark.asyncio
async def test_llm_fallback_handles_general_chat_without_tool_execution() -> None:
    router = HybridRouter(
        RuleRouter(),
        FakeModelProvider(
            {"intent": "GENERAL_CHAT", "confidence": 0.99, "reply": "你好，我能帮你。"}
        ),
    )
    result = await router.route("hello")
    assert result.intent == Intent.GENERAL_CHAT
    assert result.reply == "你好，我能帮你。"


@pytest.mark.asyncio
async def test_llm_candidate_dag_is_still_verified() -> None:
    candidate = TaskPlan.model_validate(
        {
            "goal": "查看银行卡",
            "steps": [
                {
                    "step_id": "list_cards",
                    "purpose": "读取银行卡",
                    "tool_call": {"tool_name": "list_cards", "arguments": {}},
                    "argument_sources": {},
                }
            ],
        }
    )
    planner = HybridPlanner(BaselinePlanner(), FakeModelProvider(candidate))
    intent = IntentResult(
        intent=Intent.LIST_CARDS,
        complexity=2,
        confidence=0.9,
        route=Route.PLANNER,
        reason="llm:fake/test",
    )
    plan = await planner.create(
        intent,
        SlotTracker().extract("请展示卡片", intent),
        request=AgentRequest(session_id=uuid4(), message="请展示卡片"),
        allowed_tools=[],
    )
    registry = ToolRegistry()
    register_default_tools(registry, Mock())
    verified = PlanVerifier(registry).verify(plan, {"cards.list"})
    assert verified.ordered_step_ids == ("list_cards",)


@pytest.mark.asyncio
async def test_online_langgraph_runs_verified_card_tool() -> None:
    service, gateway = build_service()
    graph = build_runtime_agent_graph(service, gateway, MemorySaver())
    session_id, task_id, user_id, trace_id = uuid4(), uuid4(), uuid4(), uuid4()
    request = AgentRequest(session_id=session_id, message="查看我的银行卡")
    state = await graph.ainvoke(
        {
            "task_id": str(task_id),
            "session_id": str(session_id),
            "trace_id": str(trace_id),
            "request_text": request.message,
            "request": request.model_dump(mode="json"),
            "context": {
                "authenticated_user_id": str(user_id),
                "session_id": str(session_id),
                "task_id": str(task_id),
                "trace_id": str(trace_id),
            },
        },
        {"configurable": {"thread_id": str(task_id)}},
    )
    assert state["status"] == "COMPLETED"
    assert state["response"]["status"] == AgentResponseStatus.COMPLETED
    assert gateway.calls == ["list_cards"]


@pytest.mark.asyncio
async def test_online_langgraph_reconciles_unknown_mutation_outcome() -> None:
    registry = ToolRegistry()
    register_default_tools(registry, Mock())
    gateway = ReconciliationGateway()
    service = AgentService(
        router=RuleRouter(),
        slots=SlotTracker(),
        planner=BaselinePlanner(),
        verifier=PlanVerifier(registry),
        capabilities=CapabilityBroker(registry),
        gateway=gateway,
    )
    graph = build_runtime_agent_graph(service, gateway, MemorySaver())
    task_id, session_id, user_id, trace_id, card_id = (
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
    )
    config = {"configurable": {"thread_id": str(task_id)}}
    request = AgentRequest(session_id=session_id, message=f"冻结银行卡 {card_id}")
    waiting = await graph.ainvoke(
        {
            "task_id": str(task_id),
            "session_id": str(session_id),
            "trace_id": str(trace_id),
            "request_text": request.message,
            "request": request.model_dump(mode="json"),
            "context": {
                "authenticated_user_id": str(user_id),
                "session_id": str(session_id),
                "task_id": str(task_id),
                "trace_id": str(trace_id),
            },
        },
        config,
    )
    assert waiting["status"] == "WAITING_APPROVAL"

    completed = await graph.ainvoke(
        Command(resume={"authorization_reference": "grant-fixture"}), config
    )
    assert completed["status"] == "COMPLETED"
    assert completed["response"]["status"] == "COMPLETED"
    assert completed["response"]["result"]["status"] == "FROZEN"
    assert gateway.calls == ["freeze_card", "freeze_card", "get_card_status"]


def test_savings_and_beneficiary_apis_and_tools_are_exposed() -> None:
    paths = TestClient(app).get("/openapi.json").json()["paths"]
    assert "/savings-pots" in paths
    assert "/savings-pots/{pot_id}/contributions" in paths
    assert "post" in paths["/beneficiaries"]
    registry = ToolRegistry()
    register_default_tools(registry, Mock())
    names = {item["name"] for item in registry.list_allowed()}
    assert {"list_savings_pots", "create_savings_pot", "contribute_savings_pot"} <= names
    assert "list_beneficiaries" in names


@pytest.mark.asyncio
async def test_transfer_clarification_returns_account_and_contact_choices() -> None:
    registry = ToolRegistry()
    register_default_tools(registry, Mock())
    gateway = ClarificationGateway()
    service = AgentService(
        router=RuleRouter(),
        slots=SlotTracker(),
        planner=BaselinePlanner(),
        verifier=PlanVerifier(registry),
        capabilities=CapabilityBroker(registry),
        gateway=gateway,
    )
    session_id = uuid4()
    response = await service.handle(
        AgentRequest(session_id=session_id, message="帮我给妈妈转账10000元"),
        _trusted_context(session_id),
    )
    assert response.status == AgentResponseStatus.NEEDS_CLARIFICATION
    assert "匹配到“妈妈”" in response.message
    assert isinstance(response.result, dict)
    clarification = response.result["clarification"]
    assert isinstance(clarification, dict)
    fields = {item["name"]: item for item in clarification["fields"]}
    assert fields["source_account_id"]["options"]
    assert (
        fields["destination_account_id"]["options"][0]["label"]
        == "妈妈 · 尾号 0001"
    )
    assert fields["destination_account_id"]["value"] is not None
    assert clarification["kind"] == "CONFIRM_RESOLVED_BENEFICIARY"
    assert gateway.calls == ["get_accounts", "resolve_beneficiary", "list_beneficiaries"]
    assert gateway.arguments["resolve_beneficiary"] == {"query": "妈妈"}


@pytest.mark.asyncio
async def test_confirmed_transfer_form_bypasses_llm_and_executes_once() -> None:
    registry = ToolRegistry()
    register_default_tools(registry, Mock())
    gateway = CapturingGateway()
    service = AgentService(
        router=FailIfRouted(),
        slots=SlotTracker(),
        planner=BaselinePlanner(),
        verifier=PlanVerifier(registry),
        capabilities=CapabilityBroker(registry),
        gateway=gateway,
    )
    source, destination, session_id = uuid4(), uuid4(), uuid4()
    response = await service.handle(
        AgentRequest(
            session_id=session_id,
            message=f"确认从 {source} 向 {destination} 转账 500.00 元",
            confirmation={
                "intent": "TRANSFER",
                "fields": {
                    "source_account_id": str(source),
                    "destination_account_id": str(destination),
                    "amount": "500.00",
                    "currency": "CNY",
                },
            },
        ),
        _trusted_context(session_id),
    )
    assert response.status == AgentResponseStatus.COMPLETED
    assert gateway.calls == ["create_transfer_draft"]
    assert response.plan is not None
    call = response.plan.steps[0].tool_call
    assert call is not None
    assert call.arguments["amount"] == "500.00"
    assert response.plan.steps[0].argument_sources["amount"].kind.value == "USER_EXPLICIT"


def test_confirmation_rejects_missing_or_trusted_fields() -> None:
    source = str(uuid4())
    destination = str(uuid4())
    with pytest.raises(ValidationError, match="missing confirmation fields"):
        AgentRequest(
            session_id=uuid4(),
            message="确认转账",
            confirmation={
                "intent": "TRANSFER",
                "fields": {"source_account_id": source},
            },
        )
    with pytest.raises(ValidationError, match="trusted fields are forbidden"):
        AgentRequest(
            session_id=uuid4(),
            message="确认转账",
            confirmation={
                "intent": "TRANSFER",
                "fields": {
                    "source_account_id": source,
                    "destination_account_id": destination,
                    "amount": "500.00",
                    "currency": "CNY",
                    "user_id": str(uuid4()),
                },
            },
        )


@pytest.mark.asyncio
async def test_followup_uses_active_clarification_context_and_requires_confirmation() -> None:
    registry = ToolRegistry()
    register_default_tools(registry, Mock())
    gateway = CapturingGateway()
    service = AgentService(
        router=HybridRouter(
            RuleRouter(),
            FakeModelProvider(
                {"intent": "CREATE_SAVINGS_POT", "confidence": 0.99, "reply": None}
            ),
        ),
        slots=SlotTracker(),
        planner=BaselinePlanner(),
        verifier=PlanVerifier(registry),
        capabilities=CapabilityBroker(registry),
        gateway=gateway,
    )
    session_id = uuid4()
    followup = await service.handle(
        AgentRequest(
            session_id=session_id,
            message="妈妈，时间是2026.10.31",
            conversation=[
                ConversationMessage(
                    role=ConversationRole.USER,
                    content="下周我妈妈过生日，希望能预留1000块",
                ),
                ConversationMessage(
                    role=ConversationRole.ASSISTANT,
                    content="[CLARIFICATION] 请补充目标名称和日期。",
                ),
            ],
        ),
        _trusted_context(session_id),
    )
    assert followup.status == AgentResponseStatus.NEEDS_CLARIFICATION
    assert isinstance(followup.result, dict)
    clarification = followup.result["clarification"]
    assert isinstance(clarification, dict)
    fields = {item["name"]: item for item in clarification["fields"]}
    assert fields["name"]["value"] == "妈妈生日"
    assert fields["name"]["inferred"] is True
    assert fields["target_amount"]["value"] == "1000.00"
    assert fields["target_date"]["value"] == "2026-10-31"
    assert gateway.calls == []

    confirmed = await service.handle(
        AgentRequest(
            session_id=session_id,
            message="创建一个妈妈生日储蓄罐，目标金额1000元，目标日期2026-10-31",
        ),
        _trusted_context(session_id),
    )
    assert confirmed.status == AgentResponseStatus.COMPLETED
    assert gateway.calls == ["create_savings_pot"]


def test_agent_contract_rejects_secrets_before_llm_boundary() -> None:
    session_id = uuid4()
    for message in (
        "我的验证码是 246810",
        "银行卡号 6222 0200 0000 0000",
        "password: super-secret",
        "CVV=123",
    ):
        with pytest.raises(ValueError, match="请勿在聊天中输入"):
            AgentRequest(session_id=session_id, message=message)


@pytest.mark.asyncio
async def test_budget_clarification_supports_custom_category_and_month_picker() -> None:
    service, gateway = build_service()
    session_id = uuid4()
    clarification_response = await service.handle(
        AgentRequest(session_id=session_id, message="创建1000元预算"),
        _trusted_context(session_id),
    )
    assert clarification_response.status == AgentResponseStatus.NEEDS_CLARIFICATION
    assert isinstance(clarification_response.result, dict)
    clarification = clarification_response.result["clarification"]
    assert isinstance(clarification, dict)
    fields = {item["name"]: item for item in clarification["fields"]}
    assert fields["category"]["input_type"] == "combobox"
    assert fields["category"]["options"]
    assert fields["month_date"]["input_type"] == "month"
    assert gateway.calls == []

    confirmed = await service.handle(
        AgentRequest(
            session_id=session_id,
            message="创建预算：类别 Demo Travel Fund，月份 2026-10-01，限额 1000 元",
        ),
        _trusted_context(session_id),
    )
    assert confirmed.status == AgentResponseStatus.COMPLETED
    assert confirmed.plan is not None
    call = confirmed.plan.steps[0].tool_call
    assert call is not None
    assert call.tool_name == "create_budget"
    assert call.arguments == {
        "category": "Demo Travel Fund",
        "month": "2026-10-01",
        "limit_amount": "1000.00",
        "currency": "CNY",
    }
    assert gateway.calls == ["create_budget"]


@pytest.mark.asyncio
async def test_llm_only_routing_proposes_budget_fields_without_tool_execution() -> None:
    registry = ToolRegistry()
    register_default_tools(registry, Mock())
    gateway = CapturingGateway()
    provider = FakeModelProvider(
        {
            "intent": "CREATE_BUDGET",
            "confidence": 0.98,
            "reply": None,
            "proposed_slots": {
                "category": "妈妈生日",
                "month_date": "2026-11-01",
                "limit_amount": "1000.00",
                "currency": "CNY",
            },
        }
    )
    service = AgentService(
        router=HybridRouter(
            RuleRouter(),
            provider,
            routing_mode="llm_only",
            today=lambda: date(2026, 10, 27),
        ),
        slots=SlotTracker(),
        planner=HybridPlanner(BaselinePlanner(), provider),
        verifier=PlanVerifier(registry),
        capabilities=CapabilityBroker(registry),
        gateway=gateway,
    )
    session_id = uuid4()
    response = await service.handle(
        AgentRequest(
            session_id=session_id,
            message="我下个月想预留一些预算给妈妈过生日，大概1000元",
        ),
        _trusted_context(session_id),
    )
    assert response.status == AgentResponseStatus.NEEDS_CLARIFICATION
    assert response.plan is None
    assert gateway.calls == []
    assert isinstance(response.result, dict)
    clarification = response.result["clarification"]
    assert isinstance(clarification, dict)
    assert clarification["intent"] == "CREATE_BUDGET"
    fields = {item["name"]: item for item in clarification["fields"]}
    assert fields["category"]["value"] == "妈妈生日"
    assert fields["category"]["inferred"] is True
    assert fields["month_date"]["value"] == "2026-11-01"
    assert fields["month_date"]["inferred"] is True
    assert fields["limit_amount"]["value"] == "1000.00"
    assert fields["limit_amount"]["inferred"] is False


@pytest.mark.asyncio
async def test_llm_only_mode_fails_closed_instead_of_using_business_rules() -> None:
    result = await HybridRouter(
        RuleRouter(), None, routing_mode="llm_only"
    ).route("查看我的银行卡")
    assert result.intent == Intent.UNKNOWN
    assert result.route == Route.SAFE_FALLBACK
    assert result.confidence == 0


def _trusted_context(session_id: UUID) -> TrustedAgentContext:
    return TrustedAgentContext(
        authenticated_user_id=uuid4(),
        session_id=session_id,
        task_id=uuid4(),
        trace_id=uuid4(),
    )
