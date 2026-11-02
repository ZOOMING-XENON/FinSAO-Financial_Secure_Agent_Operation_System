from __future__ import annotations

from datetime import datetime
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest

from agent.context import SlotState, SlotTracker
from agent.contracts import AgentRequest, TrustedAgentContext
from agent.routing import Intent, IntentResult, Route
from agent.service import AgentService
from agent_tools.analytics_tools import BudgetListOutput
from agent_tools.contracts import ToolResult, ToolResultStatus


@pytest.mark.asyncio
async def test_budget_category_resolves_to_current_month_verified_id() -> None:
    budget_id = uuid4()
    month = datetime.now(ZoneInfo("Asia/Shanghai")).date().replace(day=1)

    class Gateway:
        async def execute(self, *, tool_name: str, arguments: dict, context: object) -> ToolResult:
            assert tool_name == "list_budgets"
            assert arguments == {}
            return ToolResult(
                status=ToolResultStatus.SUCCESS,
                data=BudgetListOutput.model_validate({"items": [
                    {"id": str(budget_id), "category": "DINING", "month": month.isoformat(),
                     "limit_amount": "500.00", "currency": "CNY"}
                ]}),
            )

    service = AgentService.__new__(AgentService)
    service._gateway = Gateway()  # type: ignore[assignment]
    session_id = uuid4()
    context = TrustedAgentContext(
        authenticated_user_id=uuid4(), session_id=session_id,
        task_id=uuid4(), trace_id=uuid4(),
    )
    slots = SlotState(missing=["resource_id"])
    await service._resolve_budget_reference(
        AgentRequest(session_id=session_id, message="这个月餐饮还剩多少预算"), context, slots
    )
    assert slots.facts["resource_id"].value == str(budget_id)
    assert slots.missing == []


def test_model_proposed_recent_expense_count_is_preserved() -> None:
    intent = IntentResult(
        intent=Intent.TRACK_EXPENSES, complexity=2, confidence=1,
        route=Route.PLANNER, reason="test", required_slots=[],
        proposed_slots={"limit": 3},
    )
    slots = SlotTracker().extract("列出最近三笔餐饮消费", intent)
    assert slots.facts["category"].value == "DINING"
    assert slots.facts["limit"].value == 3


