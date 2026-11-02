from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from agent.bundle_contracts import (
    AgentTurnRequest,
    BundleItemConfirmation,
    BundleItemStatus,
    BundleStatus,
    TaskDecomposition,
)
from agent.contracts import AgentRequest, ConversationRole, TaskPlan, TrustedAgentContext
from agent.durable import DurableTask, TaskStatus
from agent.orchestrator import ConversationOrchestrator
from agent.providers import FakeModelProvider
from agent.routing import Intent
from agent.task_decomposition import TaskDecomposer
from agent_persistence.bundle_store import MemoryBundleStore


class BundleTaskManager:
    async def create(self, request: AgentRequest, context: TrustedAgentContext) -> DurableTask:
        if request.confirmation is not None:
            return _task(
                context,
                TaskStatus.WAITING_APPROVAL,
                result={"id": str(uuid4()), "amount": "105.00"},
                plan={
                    "goal": "向 Friend 转账 105.00 CNY",
                    "steps": [
                        {
                            "step_id": "draft",
                            "purpose": "创建转账草稿",
                            "tool_call": {
                                "tool_name": "create_transfer_draft",
                                "arguments": {"amount": "105.00"},
                            },
                            "argument_sources": {},
                        }
                    ],
                },
            )
        if "余额" in request.message:
            return _task(
                context,
                TaskStatus.COMPLETED,
                result={"balance": "29998.00", "currency": "CNY"},
            )
        return _task(
            context,
            TaskStatus.NEEDS_CLARIFICATION,
            result={
                "clarification": {
                    "kind": "CONFIRM_INFERRED",
                    "intent": "TRANSFER",
                    "fields": [
                        {
                            "name": "amount",
                            "label": "金额",
                            "input_type": "amount",
                            "required": True,
                            "value": "105.00",
                            "inferred": True,
                            "options": [],
                        }
                    ],
                }
            },
        )

    async def resume(
        self, *, task_id: UUID, user_id: UUID, authorization_reference: str
    ) -> DurableTask:
        del user_id, authorization_reference
        context = TrustedAgentContext(
            authenticated_user_id=uuid4(),
            session_id=uuid4(),
            task_id=task_id,
            trace_id=uuid4(),
        )
        return _task(
            context,
            TaskStatus.COMPLETED,
            result={"status": "COMPLETED", "amount": "105.00"},
        )


def _task(
    context: TrustedAgentContext,
    status: TaskStatus,
    *,
    result: object,
    plan: dict[str, object] | None = None,
) -> DurableTask:
    now = datetime.now(UTC)
    validated_plan = TaskPlan.model_validate(plan).model_dump(mode="json") if plan else None
    return DurableTask(
        id=context.task_id,
        session_id=context.session_id,
        user_id=context.authenticated_user_id,
        trace_id=context.trace_id,
        status=status,
        request_message="fixture",
        public_message="fixture response",
        plan=validated_plan,
        result=result,  # type: ignore[arg-type]
        error_code=None,
        recovery_action=None,
        version=1,
        created_at=now,
        updated_at=now,
    )


@pytest.mark.asyncio
async def test_bundle_continues_after_query_confirmation_and_approval() -> None:
    decomposition = TaskDecomposition.model_validate(
        {
            "tasks": [
                {
                    "item_key": "balance_savings",
                    "intent": "GET_BALANCE",
                    "evidence": "查询我saving账户的余额",
                },
                {
                    "item_key": "transfer_friend",
                    "intent": "TRANSFER",
                    "evidence": "昨晚吃海底捞一共210，要和Friend进行aa，帮我给他转账",
                },
            ]
        }
    )
    store = MemoryBundleStore()
    orchestrator = ConversationOrchestrator(
        decomposer=TaskDecomposer(FakeModelProvider(decomposition)),
        task_manager=BundleTaskManager(),  # type: ignore[arg-type]
        store=store,
    )
    user_id, session_id = uuid4(), uuid4()
    context = TrustedAgentContext(
        authenticated_user_id=user_id,
        session_id=session_id,
        task_id=uuid4(),
        trace_id=uuid4(),
    )
    first = await orchestrator.handle_turn(
        AgentTurnRequest(
            session_id=session_id,
            message=(
                "请帮我查询我saving账户的余额，并且昨晚吃海底捞一共210，"
                "要和Friend进行aa，帮我给他转账"
            ),
        ),
        context,
    )
    assert first.bundle.items[0].status == BundleItemStatus.COMPLETED
    assert first.bundle.items[1].status == BundleItemStatus.NEEDS_CONFIRMATION
    assert first.bundle.status == BundleStatus.NEEDS_CONFIRMATION

    transfer = first.bundle.items[1]
    second = await orchestrator.handle_turn(
        AgentTurnRequest(
            session_id=session_id,
            bundle_id=first.bundle.bundle_id,
            message="确认转账信息",
            confirmation=BundleItemConfirmation(
                item_id=transfer.item_id,
                intent=Intent.TRANSFER,
                fields={
                    "source_account_id": str(uuid4()),
                    "destination_account_id": str(uuid4()),
                    "amount": "105.00",
                    "currency": "CNY",
                },
            ),
        ),
        context,
    )
    assert second.bundle.status == BundleStatus.WAITING_APPROVAL
    waiting = second.bundle.items[1]
    assert waiting.status == BundleItemStatus.WAITING_APPROVAL

    final = await orchestrator.resume_item(
        bundle_id=second.bundle.bundle_id,
        item_id=waiting.item_id,
        authorization_reference="fixture-grant",
        request_id=uuid4(),
        context=context,
        locale="zh-CN",
    )
    assert final.bundle.status == BundleStatus.COMPLETED
    assert all(item.status == BundleItemStatus.COMPLETED for item in final.bundle.items)


@pytest.mark.asyncio
async def test_savings_item_is_deferred_while_transfer_continues() -> None:
    decomposition = TaskDecomposition.model_validate(
        {
            "tasks": [
                {
                    "item_key": "reserve_party",
                    "intent": "CREATE_SAVINGS_POT",
                    "evidence": "帮我预留100给下周的生日party",
                },
                {
                    "item_key": "transfer_mom",
                    "intent": "TRANSFER",
                    "evidence": "给妈妈转账100",
                },
            ]
        }
    )
    store = MemoryBundleStore()
    orchestrator = ConversationOrchestrator(
        decomposer=TaskDecomposer(FakeModelProvider(decomposition)),
        task_manager=BundleTaskManager(),  # type: ignore[arg-type]
        store=store,
    )
    user_id, session_id = uuid4(), uuid4()
    context = TrustedAgentContext(
        authenticated_user_id=user_id,
        session_id=session_id,
        task_id=uuid4(),
        trace_id=uuid4(),
    )
    response = await orchestrator.handle_turn(
        AgentTurnRequest(
            session_id=session_id,
            message="帮我预留100给下周的生日party，并且给妈妈转账100",
        ),
        context,
    )
    assert response.bundle.items[0].status == BundleItemStatus.DEFERRED_UNSUPPORTED
    assert response.bundle.items[1].status == BundleItemStatus.NEEDS_CONFIRMATION


def test_session_memory_is_capped_at_twenty_messages() -> None:
    store = MemoryBundleStore()
    user_id, session_id = uuid4(), uuid4()
    for index in range(25):
        store.append_message(
            user_id=user_id,
            session_id=session_id,
            role=ConversationRole.USER,
            content=f"message-{index}",
        )
    messages = store.recent_messages(user_id=user_id, session_id=session_id)
    assert len(messages) == 20
    assert messages[0].content == "message-5"


@pytest.mark.asyncio
async def test_new_message_does_not_continue_pending_bundle() -> None:
    class Decomposer:
        async def decompose(
            self, *, message: str, conversation: object, request_id: UUID
        ) -> TaskDecomposition:
            del conversation, request_id
            intent = Intent.GET_BALANCE if "余额" in message else Intent.TRANSFER
            return TaskDecomposition(
                tasks=[{"item_key": "task_1", "intent": intent, "evidence": message}]
            )

    store = MemoryBundleStore()
    orchestrator = ConversationOrchestrator(
        decomposer=Decomposer(),  # type: ignore[arg-type]
        task_manager=BundleTaskManager(),  # type: ignore[arg-type]
        store=store,
    )
    user_id, session_id = uuid4(), uuid4()
    context = TrustedAgentContext(
        authenticated_user_id=user_id, session_id=session_id, task_id=uuid4(), trace_id=uuid4()
    )
    old = await orchestrator.handle_turn(
        AgentTurnRequest(session_id=session_id, message="给朋友转账100元"), context
    )
    assert old.bundle.status == BundleStatus.NEEDS_CONFIRMATION
    fresh = await orchestrator.handle_turn(
        AgentTurnRequest(session_id=session_id, message="查询余额"), context
    )
    assert fresh.bundle.bundle_id != old.bundle.bundle_id
    assert fresh.bundle.status == BundleStatus.COMPLETED
    pending = store.get_bundle(bundle_id=old.bundle.bundle_id, user_id=user_id)
    assert pending is not None
    assert pending.status == BundleStatus.NEEDS_CONFIRMATION


@pytest.mark.asyncio
async def test_chat_reply_is_preserved_without_extra_composition() -> None:
    class ChatManager:
        async def create(self, request: AgentRequest, context: TrustedAgentContext) -> DurableTask:
            assert context.expected_intent == Intent.GENERAL_CHAT
            return _task(context, TaskStatus.COMPLETED, result=None).model_copy(
                update={"public_message": "你好！有什么可以帮你？"}
            )

    class FailingComposer:
        async def compose(self, **kwargs: object) -> str:
            raise AssertionError("reply must not require another model call")

    orchestrator = ConversationOrchestrator(
        decomposer=TaskDecomposer(
            FakeModelProvider(TaskDecomposition(tasks=[
                {"item_key": "task_1", "intent": Intent.GENERAL_CHAT, "evidence": "你好"}
            ]))
        ),
        task_manager=ChatManager(),  # type: ignore[arg-type]
        store=MemoryBundleStore(),
        conversation_composer=FailingComposer(),  # type: ignore[arg-type]
    )
    session_id = uuid4()
    context = TrustedAgentContext(
        authenticated_user_id=uuid4(), session_id=session_id,
        task_id=uuid4(), trace_id=uuid4(),
    )
    response = await orchestrator.handle_turn(
        AgentTurnRequest(session_id=session_id, message="你好"), context
    )
    assert response.bundle.status == BundleStatus.COMPLETED
    assert response.public_message == "你好！有什么可以帮你？"
