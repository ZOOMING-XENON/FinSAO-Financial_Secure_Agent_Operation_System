from __future__ import annotations

from typing import Any
from unittest.mock import Mock
from uuid import uuid4

import pytest
from pydantic import BaseModel

from agent.capabilities import CapabilityBroker
from agent.context import SlotTracker
from agent.contracts import AgentRequest, AgentResponseStatus, TrustedAgentContext
from agent.planning import BaselinePlanner, PlanVerifier
from agent.providers import FakeModelProvider
from agent.routing import Intent, IntentResult, Route, RuleRouter
from agent.service import AgentService
from agent.transfer_reasoning import ModelTransferReasoner
from agent_tools.contracts import ExecutionContext, ToolResult, ToolResultStatus
from agent_tools.registry import ToolRegistry
from agent_tools.tools import register_default_tools


class Accounts(BaseModel):
    accounts: list[dict[str, Any]]


class Beneficiaries(BaseModel):
    beneficiaries: list[dict[str, Any]]


class ReferenceGateway:
    def __init__(self) -> None:
        self.checking_id = uuid4()
        self.mom_id = uuid4()
        self.dad_id = uuid4()

    async def execute(
        self, *, tool_name: str, arguments: dict[str, Any], context: ExecutionContext
    ) -> ToolResult[Any]:
        del arguments, context
        if tool_name == "get_accounts":
            return ToolResult(
                status=ToolResultStatus.SUCCESS,
                data=Accounts(accounts=[{
                    "id": str(self.checking_id), "name": "Checking",
                    "account_number": "0001", "currency": "CNY", "status": "ACTIVE",
                }]),
            )
        if tool_name == "list_beneficiaries":
            return ToolResult(
                status=ToolResultStatus.SUCCESS,
                data=Beneficiaries(beneficiaries=[
                    {"destination_account_id": str(self.dad_id),
                     "destination_account_number": "0002", "name": "爸爸", "nickname": "爸爸"},
                    {"destination_account_id": str(self.mom_id),
                     "destination_account_number": "0003", "name": "妈妈", "nickname": "妈妈"},
                ]),
            )
        raise AssertionError(tool_name)


def make_service(gateway: ReferenceGateway) -> AgentService:
    registry = ToolRegistry()
    register_default_tools(registry, Mock())
    return AgentService(
        router=RuleRouter(),
        slots=SlotTracker(),
        planner=BaselinePlanner(),
        verifier=PlanVerifier(registry),
        capabilities=CapabilityBroker(registry),
        gateway=gateway,
        transfer_reasoner=ModelTransferReasoner(FakeModelProvider({
            "multiple_actions": False,
            "requires_clarification": False,
            "total": None,
            "share_count": None,
            "recipient_paid": None,
            "percentage": 10,
            "balance_ref": "task_1",
            "explanation": "Use the verified balance from the previous query.",
        })),
    )


@pytest.mark.asyncio
async def test_percentage_uses_verified_balance_and_prefills_transfer_form() -> None:
    gateway = ReferenceGateway()
    service = make_service(gateway)
    session_id = uuid4()
    context = TrustedAgentContext(
        authenticated_user_id=uuid4(), session_id=session_id, task_id=uuid4(),
        trace_id=uuid4(), expected_intent=Intent.TRANSFER,
        expected_slots={"percentage": 10, "recipient": "妈妈", "amount": "10%"},
        verified_balances=[{
            "ref": "task_1", "account_id": str(gateway.checking_id),
            "balance": "1440.00", "currency": "CNY",
        }],
    )
    response = await service.handle(
        AgentRequest(session_id=session_id, message="将其10%转账给我的妈妈"), context
    )
    assert response.status == AgentResponseStatus.NEEDS_CLARIFICATION
    assert isinstance(response.result, dict)
    fields = {
        field["name"]: field
        for field in response.result["clarification"]["fields"]
    }
    assert fields["amount"]["value"] == "144.00"
    assert fields["source_account_id"]["value"] == str(gateway.checking_id)
    assert fields["destination_account_id"]["value"] == str(gateway.mom_id)
    assert fields["destination_account_id"]["inferred"] is True
    assert fields["currency"]["value"] == "CNY"
    assert fields["amount"]["inferred"] is True


@pytest.mark.asyncio
async def test_percentage_without_verified_balance_does_not_offer_ten_percent_as_money() -> None:
    gateway = ReferenceGateway()
    service = make_service(gateway)
    session_id = uuid4()
    context = TrustedAgentContext(
        authenticated_user_id=uuid4(), session_id=session_id, task_id=uuid4(),
        trace_id=uuid4(), expected_intent=Intent.TRANSFER,
        expected_slots={"amount": "10%", "recipient": "妈妈"},
    )
    response = await service.handle(
        AgentRequest(session_id=session_id, message="将其10%转账给我的妈妈"), context
    )
    assert response.status == AgentResponseStatus.NEEDS_CLARIFICATION
    assert response.result is None


def test_percent_string_is_not_a_money_slot_and_currency_defaults_to_cny() -> None:
    intent = IntentResult(
        intent=Intent.TRANSFER, complexity=3, confidence=1, route=Route.PLANNER,
        reason="test",
        required_slots=[
            "source_account_id", "destination_account_id", "amount", "currency"
        ],
        proposed_slots={"amount": "10%", "recipient": "妈妈"},
    )
    slots = SlotTracker().extract("将其10%转账给我的妈妈", intent)
    assert "amount" not in slots.facts
    assert slots.facts["currency"].value == "CNY"
    assert slots.facts["beneficiary_query"].value == "妈妈"
