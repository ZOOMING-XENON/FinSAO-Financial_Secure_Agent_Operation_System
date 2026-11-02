"""Persistent multi-turn orchestration around the existing verified Agent service."""

from __future__ import annotations

from uuid import UUID, uuid4

from pydantic import JsonValue

from agent.bundle_contracts import (
    AgentTaskBundle,
    AgentTaskItem,
    AgentTurnRequest,
    AgentTurnResponse,
    BundleItemStatus,
    BundleStatus,
)
from agent.contracts import (
    AgentRequest,
    ClarificationConfirmation,
    ClarificationPayload,
    ConversationMessage,
    ConversationRole,
    TaskPlan,
    TrustedAgentContext,
)
from agent.conversation_style import ModelConversationComposer
from agent.durable import DurableTask, DurableTaskManager, TaskStatus
from agent.routing import Intent
from agent.task_decomposition import TaskDecomposer
from agent_persistence.bundle_store import BundleStore

_DEFERRED_INTENTS = {Intent.CREATE_SAVINGS_POT, Intent.CONTRIBUTE_SAVINGS_POT}


class ConversationOrchestrator:
    def __init__(
        self,
        *,
        decomposer: TaskDecomposer,
        task_manager: DurableTaskManager,
        store: BundleStore,
        conversation_composer: ModelConversationComposer | None = None,
    ) -> None:
        self._decomposer = decomposer
        self._tasks = task_manager
        self._store = store
        self._conversation_composer = conversation_composer

    async def handle_turn(
        self, request: AgentTurnRequest, context: TrustedAgentContext
    ) -> AgentTurnResponse:
        history = self._store.recent_messages(
            user_id=context.authenticated_user_id, session_id=request.session_id
        )
        if request.confirmation is None:
            self._store.append_message(
                user_id=context.authenticated_user_id,
                session_id=request.session_id,
                role=ConversationRole.USER,
                content=request.message,
            )
        if request.bundle_id is None:
            decomposition = await self._decomposer.decompose(
                message=request.message,
                conversation=history or request.conversation,
                request_id=request.request_id,
            )
            bundle = self._store.create_bundle(
                user_id=context.authenticated_user_id,
                session_id=request.session_id,
                original_request=request.message,
                tasks=decomposition.tasks,
            )
            if decomposition.needs_clarification:
                active = bundle.items[0]
                clarification = ClarificationPayload(
                    kind="MISSING_FIELDS",
                    intent=active.intent.value,
                    fields=[],
                )
                bundle = self._store.update_item(
                    bundle_id=bundle.bundle_id,
                    user_id=context.authenticated_user_id,
                    item_id=active.item_id,
                    status=BundleItemStatus.NEEDS_CLARIFICATION,
                    clarification=clarification,
                    result={"question": decomposition.clarification_question or "请补充任务细节。"},
                )
                bundle = self._store.update_bundle(
                    bundle_id=bundle.bundle_id,
                    user_id=context.authenticated_user_id,
                    status=BundleStatus.NEEDS_CLARIFICATION,
                    active_item_id=active.item_id,
                )
                return await self._respond(request, context, bundle)
        else:
            bundle = self._require_bundle(request.bundle_id, context.authenticated_user_id)
        if request.confirmation is not None:
            bundle = await self._confirm_item(request, context, bundle)
        elif request.reply_to_item_id is not None:
            active = self._item(bundle, request.reply_to_item_id)
            if (
                bundle.active_item_id != active.item_id
                or active.status != BundleItemStatus.NEEDS_CLARIFICATION
            ):
                raise ValueError("this clarification card is no longer active")
            if active.clarification is not None and active.clarification.fields:
                raise ValueError("use the active form to submit these fields")
            bundle = await self._run_item(
                bundle,
                active,
                context,
                message=f"{active.evidence}\n用户补充：{request.message}",
                conversation=history,
                locale=request.locale,
            )
        elif request.bundle_id is not None and request.confirmation is None:
            raise ValueError("a bundle continuation requires an explicit reply target")
        bundle = await self._advance(bundle, context, history, request.locale)
        return await self._respond(request, context, bundle)

    async def resume_item(
        self,
        *,
        bundle_id: UUID,
        item_id: UUID,
        authorization_reference: str,
        request_id: UUID,
        context: TrustedAgentContext,
        locale: str,
    ) -> AgentTurnResponse:
        bundle = self._require_bundle(bundle_id, context.authenticated_user_id)
        item = self._item(bundle, item_id)
        if item.task_id is None:
            raise ValueError("bundle item has no approval task")
        task = await self._tasks.resume(
            task_id=item.task_id,
            user_id=context.authenticated_user_id,
            authorization_reference=authorization_reference,
        )
        bundle = self._store.update_item(
            bundle_id=bundle_id,
            user_id=context.authenticated_user_id,
            item_id=item_id,
            status=self._item_status(task),
            result=task.result,
            plan=TaskPlan.model_validate(task.plan) if task.plan else None,
            task_id=task.id,
            error_code=task.error_code,
        )
        history = self._store.recent_messages(
            user_id=context.authenticated_user_id, session_id=bundle.session_id
        )
        bundle = await self._advance(bundle, context, history, locale)
        request = AgentTurnRequest(
            request_id=request_id,
            session_id=bundle.session_id,
            bundle_id=bundle_id,
            message="审批结果",
            locale="en-US" if locale == "en-US" else "zh-CN",
        )
        return await self._respond(request, context, bundle)

    async def _confirm_item(
        self,
        request: AgentTurnRequest,
        context: TrustedAgentContext,
        bundle: AgentTaskBundle,
    ) -> AgentTaskBundle:
        confirmation = request.confirmation
        assert confirmation is not None
        item = self._item(bundle, confirmation.item_id)
        if bundle.active_item_id != item.item_id or item.status not in {
            BundleItemStatus.NEEDS_CLARIFICATION,
            BundleItemStatus.NEEDS_CONFIRMATION,
        }:
            raise ValueError("this clarification card is no longer active")
        if item.intent != confirmation.intent:
            raise ValueError("confirmation intent does not match bundle item")
        if item.clarification is None or item.clarification.intent != item.intent.value:
            raise ValueError("confirmation does not match the active clarification")
        expected_fields = {field.name for field in item.clarification.fields}
        if not expected_fields or not expected_fields.issubset(confirmation.fields):
            raise ValueError("confirmation fields do not match the active form")
        for field in item.clarification.fields:
            if field.options and confirmation.fields[field.name] not in {
                option.value for option in field.options
            }:
                raise ValueError(f"invalid option for {field.name}")
        agent_request = AgentRequest(
            session_id=request.session_id,
            message=request.message,
            locale=request.locale,
            confirmation=ClarificationConfirmation(
                intent=confirmation.intent, fields=confirmation.fields
            ),
        )
        task = await self._create_task(agent_request, context)
        return self._store.update_item(
            bundle_id=bundle.bundle_id,
            user_id=context.authenticated_user_id,
            item_id=item.item_id,
            status=self._item_status(task),
            result=task.result,
            plan=TaskPlan.model_validate(task.plan) if task.plan else None,
            task_id=task.id,
            error_code=task.error_code,
            confirmed_fields=confirmation.fields,
        )

    async def _advance(
        self,
        bundle: AgentTaskBundle,
        context: TrustedAgentContext,
        history: list[ConversationMessage],
        locale: str,
    ) -> AgentTaskBundle:
        while True:
            next_item = self._next_runnable(bundle)
            if next_item is None:
                break
            if next_item.intent in _DEFERRED_INTENTS:
                bundle = self._store.update_item(
                    bundle_id=bundle.bundle_id,
                    user_id=context.authenticated_user_id,
                    item_id=next_item.item_id,
                    status=BundleItemStatus.DEFERRED_UNSUPPORTED,
                    result={"reason": "savings product behavior is awaiting confirmation"},
                )
                continue
            bundle = await self._run_item(
                bundle,
                next_item,
                context,
                message=next_item.evidence,
                conversation=history,
                locale=locale,
            )
            updated = self._item(bundle, next_item.item_id)
            if updated.status != BundleItemStatus.COMPLETED:
                break
        status, active = self._bundle_status(bundle)
        return self._store.update_bundle(
            bundle_id=bundle.bundle_id,
            user_id=context.authenticated_user_id,
            status=status,
            active_item_id=active,
        )

    async def _run_item(
        self,
        bundle: AgentTaskBundle,
        item: AgentTaskItem,
        context: TrustedAgentContext,
        *,
        message: str,
        conversation: list[ConversationMessage],
        locale: str,
    ) -> AgentTaskBundle:
        request = AgentRequest(
            session_id=bundle.session_id,
            message=message,
            conversation=conversation,
            locale="en-US" if locale == "en-US" else "zh-CN",
        )
        task = await self._create_task(
            request, context,
            expected_intent=None if item.intent == Intent.UNKNOWN else item.intent,
            expected_slots=item.proposed_slots,
            verified_balances=[
                {
                    "ref": completed.item_key,
                    "account_id": completed.result["account_id"],
                    "balance": completed.result["balance"],
                    "currency": completed.result["currency"],
                }
                for completed in bundle.items
                if completed.intent == Intent.GET_BALANCE
                and completed.status == BundleItemStatus.COMPLETED
                and isinstance(completed.result, dict)
                and all(
                    key in completed.result
                    for key in ("account_id", "balance", "currency")
                )
            ],
        )
        clarification = None
        if isinstance(task.result, dict) and isinstance(task.result.get("clarification"), dict):
            clarification = ClarificationPayload.model_validate(task.result["clarification"])
        resolved_intent = Intent(clarification.intent) if clarification is not None else item.intent
        result = task.result
        if task.status == TaskStatus.NEEDS_CLARIFICATION and task.public_message:
            result = {
                **(result if isinstance(result, dict) else {}),
                "question": task.public_message,
            }
        elif task.status in {TaskStatus.COMPLETED, TaskStatus.FAILED} and result is None:
            result = {"reply": task.public_message or ""}
        return self._store.update_item(
            bundle_id=bundle.bundle_id,
            user_id=context.authenticated_user_id,
            item_id=item.item_id,
            status=self._item_status(task, clarification),
            intent=resolved_intent,
            clarification=clarification,
            plan=TaskPlan.model_validate(task.plan) if task.plan else None,
            result=result,
            task_id=task.id,
            error_code=task.error_code,
        )

    async def _create_task(
        self, request: AgentRequest, parent_context: TrustedAgentContext,
        expected_intent: Intent | None = None,
        expected_slots: dict[str, JsonValue] | None = None,
        verified_balances: list[dict[str, JsonValue]] | None = None,
    ) -> DurableTask:
        context = TrustedAgentContext(
            authenticated_user_id=parent_context.authenticated_user_id,
            session_id=request.session_id,
            task_id=uuid4(),
            trace_id=parent_context.trace_id,
            expected_intent=expected_intent,
            expected_slots=expected_slots,
            verified_balances=verified_balances,
        )
        return await self._tasks.create(request, context)

    async def _respond(
        self,
        request: AgentTurnRequest,
        context: TrustedAgentContext,
        bundle: AgentTaskBundle,
    ) -> AgentTurnResponse:
        message = self._compose(bundle, request.locale)
        self._store.append_message(
            user_id=context.authenticated_user_id,
            session_id=request.session_id,
            role=ConversationRole.ASSISTANT,
            content=message,
        )
        return AgentTurnResponse(
            request_id=request.request_id,
            session_id=request.session_id,
            bundle=bundle,
            public_message=message,
        )

    @staticmethod
    def _compose(bundle: AgentTaskBundle, locale: str) -> str:
        english = locale == "en-US"
        if len(bundle.items) == 1 and bundle.items[0].status in {
            BundleItemStatus.COMPLETED,
            BundleItemStatus.FAILED,
        }:
            result = bundle.items[0].result
            if isinstance(result, dict):
                reply = result.get("reply")
                if isinstance(reply, str) and reply:
                    return reply
        completed = sum(item.status == BundleItemStatus.COMPLETED for item in bundle.items)
        deferred = sum(
            item.status == BundleItemStatus.DEFERRED_UNSUPPORTED for item in bundle.items
        )
        active = next(
            (item for item in bundle.items if item.item_id == bundle.active_item_id), None
        )
        if active is not None and active.status in {
            BundleItemStatus.NEEDS_CLARIFICATION,
            BundleItemStatus.NEEDS_CONFIRMATION,
        }:
            question = (
                active.result.get("question")
                if isinstance(active.result, dict) and active.result.get("question")
                else "Please review the highlighted fields."
                if english
                else "我已经整理到这一步，请检查并补充当前卡片。"
            )
            prefix = (
                f"I separated this into {len(bundle.items)} tasks. "
                if english and len(bundle.items) > 1
                else f"我把这次需求整理成了 {len(bundle.items)} 项。"
                if len(bundle.items) > 1
                else ""
            )
            return prefix + str(question)
        if active is not None and active.status == BundleItemStatus.WAITING_APPROVAL:
            return (
                "The details are ready. Please review the approval card to continue."
                if english
                else "信息已经整理好了，请检查审批卡片后再继续。"
            )
        if bundle.status in {BundleStatus.COMPLETED, BundleStatus.PARTIALLY_COMPLETED}:
            if english:
                return (
                    f"I completed {completed} task(s)."
                    + (f" {deferred} savings task(s) remain deferred." if deferred else "")
                )
            return (
                f"这次已经完成 {completed} 项。"
                + (f"另有 {deferred} 项储蓄任务暂缓处理。" if deferred else "")
            )
        return (
            "I’m working through the tasks in order."
            if english
            else "我正在按顺序处理这些任务。"
        )

    @staticmethod
    def _item_status(
        task: DurableTask, clarification: ClarificationPayload | None = None
    ) -> BundleItemStatus:
        if task.status == TaskStatus.COMPLETED:
            return BundleItemStatus.COMPLETED
        if task.status == TaskStatus.WAITING_APPROVAL:
            return BundleItemStatus.WAITING_APPROVAL
        if task.status == TaskStatus.FAILED:
            return BundleItemStatus.FAILED
        if task.status == TaskStatus.NEEDS_CLARIFICATION:
            if clarification is not None and clarification.kind == "CONFIRM_INFERRED":
                return BundleItemStatus.NEEDS_CONFIRMATION
            return BundleItemStatus.NEEDS_CLARIFICATION
        return BundleItemStatus.FAILED

    @staticmethod
    def _next_runnable(bundle: AgentTaskBundle) -> AgentTaskItem | None:
        complete_keys = {
            item.item_key
            for item in bundle.items
            if item.status
            in {BundleItemStatus.COMPLETED, BundleItemStatus.DEFERRED_UNSUPPORTED}
        }
        return next(
            (
                item
                for item in bundle.items
                if item.status == BundleItemStatus.PROPOSED
                and set(item.depends_on).issubset(complete_keys)
            ),
            None,
        )

    @staticmethod
    def _bundle_status(bundle: AgentTaskBundle) -> tuple[BundleStatus, UUID | None]:
        active_states = {
            BundleItemStatus.NEEDS_CLARIFICATION: BundleStatus.NEEDS_CLARIFICATION,
            BundleItemStatus.NEEDS_CONFIRMATION: BundleStatus.NEEDS_CONFIRMATION,
            BundleItemStatus.WAITING_APPROVAL: BundleStatus.WAITING_APPROVAL,
        }
        for item in bundle.items:
            if item.status in active_states:
                return active_states[item.status], item.item_id
        if any(item.status == BundleItemStatus.FAILED for item in bundle.items):
            return BundleStatus.PARTIALLY_COMPLETED, None
        if all(
            item.status in {BundleItemStatus.COMPLETED, BundleItemStatus.DEFERRED_UNSUPPORTED}
            for item in bundle.items
        ):
            status = (
                BundleStatus.PARTIALLY_COMPLETED
                if any(
                    item.status == BundleItemStatus.DEFERRED_UNSUPPORTED
                    for item in bundle.items
                )
                else BundleStatus.COMPLETED
            )
            return status, None
        return BundleStatus.RUNNING, None

    def _require_bundle(self, bundle_id: UUID, user_id: UUID) -> AgentTaskBundle:
        bundle = self._store.get_bundle(bundle_id=bundle_id, user_id=user_id)
        if bundle is None:
            raise KeyError(bundle_id)
        return bundle

    @staticmethod
    def _item(bundle: AgentTaskBundle, item_id: UUID) -> AgentTaskItem:
        item = next((candidate for candidate in bundle.items if candidate.item_id == item_id), None)
        if item is None:
            raise KeyError(item_id)
        return item
