from __future__ import annotations

from typing import Any
from unittest.mock import Mock
from uuid import uuid4

import pytest
from pydantic import BaseModel

from agent.capabilities import CapabilityBroker
from agent.context import SlotTracker
from agent.contracts import AgentRequest, AgentResponseStatus, TrustedAgentContext
from agent.expenses import ExpenseRouter
from agent.planning import BaselinePlanner, PlanVerifier
from agent.routing import Intent, Route, RuleRouter
from agent.service import AgentService
from agent_tools.contracts import ExecutionContext, ToolResult, ToolResultStatus
from agent_tools.registry import ToolRegistry
from agent_tools.tools import register_default_tools


class FixtureOutput(BaseModel):
    items: list[dict[str, Any]] = []
    total: str | None = None
    transaction_count: int = 0
    totals_by_currency: dict[str, str] = {}
    by_category: dict[str, dict[str, str]] = {}
    by_merchant: dict[str, dict[str, str]] = {}
    limit: int = 50
    offset: int = 0


class FakeGateway:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def execute(
        self, *, tool_name: str, arguments: dict[str, Any], context: ExecutionContext
    ) -> ToolResult[Any]:
        del context
        self.calls.append((tool_name, arguments))
        return ToolResult(status=ToolResultStatus.SUCCESS, data=FixtureOutput())


def service(enabled: bool = True) -> tuple[AgentService, FakeGateway]:
    registry = ToolRegistry()
    register_default_tools(registry, Mock())
    gateway = FakeGateway()
    return (
        AgentService(
            router=ExpenseRouter(RuleRouter(), enabled=enabled),
            slots=SlotTracker(),
            planner=BaselinePlanner(),
            verifier=PlanVerifier(registry),
            capabilities=CapabilityBroker(registry),
            gateway=gateway,
        ),
        gateway,
    )


def context() -> TrustedAgentContext:
    return TrustedAgentContext(
        authenticated_user_id=uuid4(),
        session_id=uuid4(),
        task_id=uuid4(),
        trace_id=uuid4(),
    )


def test_expense_router_is_feature_gated() -> None:
    enabled = ExpenseRouter(RuleRouter(), enabled=True)
    disabled = ExpenseRouter(RuleRouter(), enabled=False)
    assert enabled.route("show my dining expenses this month").intent == Intent.TRACK_EXPENSES
    assert disabled.route("show my dining expenses this month").route == Route.SAFE_FALLBACK


def test_expense_slots_are_deterministic() -> None:
    routed = ExpenseRouter(RuleRouter(), enabled=True).route(
        "show my dining expenses this month sorted by largest"
    )
    slots = SlotTracker().extract(
        "show my dining expenses this month sorted by largest", routed
    )
    assert routed.intent == Intent.TRACK_EXPENSES
    assert slots.facts["category"].value == "DINING"
    assert slots.facts["sort_by"].value == "amount"
    assert slots.facts["sort_direction"].value == "desc"
    assert slots.missing == []


@pytest.mark.asyncio
async def test_expense_list_plan_calls_get_expenses() -> None:
    agent, gateway = service()
    response = await agent.handle(
        AgentRequest(
            session_id=uuid4(),
            message="show my dining expenses this month sorted by largest",
        ),
        context(),
    )
    assert response.status == AgentResponseStatus.COMPLETED
    assert gateway.calls[0][0] == "get_expenses"
    assert gateway.calls[0][1]["category"] == "DINING"
    assert gateway.calls[0][1]["sort_by"] == "amount"


@pytest.mark.asyncio
async def test_expense_summary_plan_calls_summarize_expenses() -> None:
    agent, gateway = service()
    response = await agent.handle(
        AgentRequest(session_id=uuid4(), message="total spending this month"),
        context(),
    )
    assert response.status == AgentResponseStatus.COMPLETED
    assert gateway.calls[0][0] == "summarize_expenses"


@pytest.mark.asyncio
async def test_disabled_expense_chat_clarifies_without_tool_calls() -> None:
    agent, gateway = service(enabled=False)
    response = await agent.handle(
        AgentRequest(session_id=uuid4(), message="show my expenses this month"),
        context(),
    )
    assert response.status == AgentResponseStatus.NEEDS_CLARIFICATION
    assert gateway.calls == []

def test_expense_tool_mutation_metadata() -> None:
    registry = ToolRegistry()
    register_default_tools(registry, Mock())
    expected = {
        "get_expenses": False,
        "summarize_expenses": False,
        "categorize_transaction": True,
        "create_transfer_draft": True,
        "compare_wealth_products": False,
        "assess_risk_profile": True,
        "create_budget": True,
    }
    for name, mutates in expected.items():
        tool = registry.get(name)
        assert tool is not None
        assert tool.mutates_data is mutates
        assert tool.metadata()["mutates_data"] is mutates

def test_expense_core_routes_are_registered() -> None:
    from banking_core.app.main import app

    paths = app.openapi()["paths"]
    assert "/transactions" in paths
    assert "/analytics/expenses/summary" in paths
    assert "/recipients/recent" in paths
    assert "/internal/expense-labeling/transactions/{transaction_id}/label" in paths
    assert "sort_by" in str(paths["/transactions"]["get"]["parameters"])

@pytest.mark.asyncio
async def test_expense_tools_use_core_routes() -> None:
    import httpx

    from agent_tools.analytics_tools import GetExpensesTool, SummarizeExpensesTool
    from agent_tools.client import BankingHttpClient, StaticServiceAuthenticator
    from agent_tools.contracts import ExecutionContext

    seen: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        if request.url.path == "/transactions":
            return httpx.Response(
                200,
                json={"items": [], "limit": 50, "offset": 0},
            )
        return httpx.Response(
            200,
            json={
                "total": "0.00",
                "transaction_count": 0,
                "totals_by_currency": {},
                "by_category": {},
                "by_merchant": {},
            },
        )

    client = BankingHttpClient(
        "http://banking",
        StaticServiceAuthenticator("test"),
        transport=httpx.MockTransport(handler),
    )
    ctx = ExecutionContext(uuid4(), uuid4(), uuid4(), uuid4())
    await GetExpensesTool(client).execute(
        GetExpensesTool.input_model(category="DINING"), ctx
    )
    await SummarizeExpensesTool(client).execute(
        SummarizeExpensesTool.input_model(category="DINING"), ctx
    )
    await client.close()
    assert seen == ["/transactions", "/analytics/expenses/summary"]

def test_merchant_normalization_and_like_escaping() -> None:
    from shared.expense_taxonomy import escape_like, normalize_merchant

    assert normalize_merchant("  Café   SHOP  ") == "café shop"
    assert escape_like("50%_off") == "50\\%\\_off"
