from __future__ import annotations

import pytest

from agent.hybrid import HybridRouter
from agent.jev_http import JevObservation
from agent.privacy_broker import PrivacyBroker
from agent.routing import Intent, Route, RuleRouter


class FakeJev:
    def __init__(self, observation: JevObservation | None = None) -> None:
        self.observation = observation
        self.calls: list[str] = []

    @property
    def available(self) -> bool:
        return True

    async def classify(self, text: str) -> JevObservation:
        self.calls.append(text)
        assert self.observation is not None
        return self.observation


def observation(**overrides: object) -> JevObservation:
    values: dict[str, object] = {
        "intent": Intent.TRACK_EXPENSES,
        "confidence": 0.95,
        "probabilities": {"TRACK_EXPENSES": 0.95},
        "injection_probability": 0.01,
        "in_scope_probability": 0.99,
        "order_consistent": True,
        "model": "jev-test",
        "latency_ms": 1,
    }
    values.update(overrides)
    return JevObservation.model_validate(values)


@pytest.mark.asyncio
async def test_jev_replaces_llm_fallback_on_safe_fallback() -> None:
    adapter = FakeJev(observation())
    router = HybridRouter(
        RuleRouter(), None, routing_mode="hybrid", jev_enabled=True, jev_adapter=adapter
    )
    result = await router.route("hello there")
    assert result.intent == Intent.TRACK_EXPENSES
    assert result.route == Route.PLANNER
    assert adapter.calls == ["hello there"]


@pytest.mark.asyncio
async def test_jev_does_not_override_deterministic_transfer_route() -> None:
    adapter = FakeJev(observation())
    router = HybridRouter(
        RuleRouter(), None, routing_mode="hybrid", jev_enabled=True, jev_adapter=adapter
    )
    result = await router.route("给小王转账 800 元")
    assert result.intent == Intent.TRANSFER
    assert result.route == Route.PLANNER
    assert adapter.calls == []


@pytest.mark.asyncio
async def test_jev_low_confidence_or_injection_falls_back() -> None:
    for item in (
        observation(confidence=0.2),
        observation(injection_probability=0.9),
        observation(order_consistent=False),
    ):
        router = HybridRouter(
            RuleRouter(),
            None,
            routing_mode="hybrid",
            jev_enabled=True,
            jev_adapter=FakeJev(item),
        )
        assert (await router.route("hello there")).route == Route.SAFE_FALLBACK


@pytest.mark.asyncio
async def test_jev_and_llm_receive_tokenized_text_when_broker_enabled() -> None:
    adapter = FakeJev(observation())
    router = HybridRouter(
        RuleRouter(),
        None,
        routing_mode="hybrid",
        jev_enabled=True,
        jev_adapter=adapter,
        privacy_broker=PrivacyBroker(names=("Alice",)),
    )
    await router.route("pay Alice")
    assert adapter.calls == ["pay [PERSON_1]"]

class FakeReviewer:
    def __init__(self, score: float) -> None:
        self.score = score
        self.calls: list[str] = []

    async def review_plan(self, text: str, plan: object) -> float:
        self.calls.append(text)
        return self.score


@pytest.mark.asyncio
async def test_plan_reviewer_veto_blocks_execution() -> None:
    from unittest.mock import Mock
    from uuid import uuid4

    from pydantic import BaseModel

    from agent.capabilities import CapabilityBroker
    from agent.context import SlotTracker
    from agent.contracts import AgentRequest, AgentResponseStatus, TrustedAgentContext
    from agent.planning import BaselinePlanner, PlanVerifier
    from agent.service import AgentService
    from agent_tools.contracts import ExecutionContext, ToolResult, ToolResultStatus
    from agent_tools.registry import ToolRegistry
    from agent_tools.tools import register_default_tools

    class Output(BaseModel):
        value: str

    class Gateway:
        def __init__(self) -> None:
            self.calls: list[str] = []

        async def execute(
            self,
            *,
            tool_name: str,
            arguments: dict[str, object],
            context: ExecutionContext,
        ) -> ToolResult[Output]:
            del arguments, context
            self.calls.append(tool_name)
            return ToolResult(status=ToolResultStatus.SUCCESS, data=Output(value="ok"))

    registry = ToolRegistry()
    register_default_tools(registry, Mock())
    gateway = Gateway()
    reviewer = FakeReviewer(0.0)
    service = AgentService(
        router=RuleRouter(),
        slots=SlotTracker(),
        planner=BaselinePlanner(),
        verifier=PlanVerifier(registry),
        capabilities=CapabilityBroker(registry),
        gateway=gateway,
        plan_reviewer=reviewer,
    )
    response = await service.handle(
        AgentRequest(session_id=uuid4(), message="查看我的账户"),
        TrustedAgentContext(
            authenticated_user_id=uuid4(),
            session_id=uuid4(),
            task_id=uuid4(),
            trace_id=uuid4(),
        ),
    )
    assert response.status == AgentResponseStatus.NEEDS_CLARIFICATION
    assert gateway.calls == []
    assert reviewer.calls

@pytest.mark.asyncio
async def test_jev_selected_intent_reaches_llm_planner() -> None:
    from uuid import uuid4

    from agent.contracts import AgentRequest, TaskPlan
    from agent.hybrid import BaselinePlanner, HybridPlanner
    from agent.providers import FakeModelProvider
    from agent.routing import IntentResult

    candidate = TaskPlan(
        goal="list accounts",
        steps=[
            {
                "step_id": "list_accounts",
                "purpose": "list",
                "tool_call": {"tool_name": "get_accounts", "arguments": {}},
                "argument_sources": {},
            }
        ],
    )
    provider = FakeModelProvider(candidate)
    planner = HybridPlanner(BaselinePlanner(), provider)
    intent = IntentResult(
        intent=Intent.LIST_ACCOUNTS,
        complexity=3,
        confidence=0.95,
        route=Route.PLANNER,
        reason="jev:jev-test",
    )
    request = AgentRequest(session_id=uuid4(), message="show my accounts")
    plan = await planner.create(
        intent,
        __import__("agent.context", fromlist=["SlotTracker"]).SlotTracker().extract(
            request.message, intent
        ),
        request=request,
        allowed_tools=[],
    )
    assert plan.goal == "list accounts"
