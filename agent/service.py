"""Single-turn safe Agent service; durable approval/resume belongs to P3."""

from __future__ import annotations

import logging
from collections.abc import Awaitable
from typing import Any, Protocol
from uuid import uuid4

from agent.capabilities import CapabilityBroker
from agent.context import FactSource, SlotFact, SlotState, SlotTracker
from agent.contracts import (
    AgentError,
    AgentRequest,
    AgentResponse,
    AgentResponseStatus,
    ClarificationField,
    ClarificationOption,
    ClarificationPayload,
    ConversationMessage,
    ConversationRole,
    TaskPlan,
    TrustedAgentContext,
)
from agent.jev_http import JevUnavailable
from agent.localization import (
    BUDGET_CATEGORIES,
    FIELD_LABELS,
    contains_cjk,
    is_english,
    localize_plan,
)
from agent.planning import PlanValidationError, PlanVerifier
from agent.responses import SafeResponseGenerator
from agent.routing import REQUIRED_SLOTS_BY_INTENT, Intent, IntentResult, Route
from agent_tools.contracts import ExecutionContext, ToolResult, ToolResultStatus

logger = logging.getLogger(__name__)


class Gateway(Protocol):
    async def execute(
        self, *, tool_name: str, arguments: dict[str, Any], context: ExecutionContext
    ) -> ToolResult[Any]: ...


class Router(Protocol):
    def route(
        self, text: str, *, conversation: list[Any] | None = None
    ) -> IntentResult | Awaitable[IntentResult]: ...


class PlanReviewer(Protocol):
    async def review_plan(self, text: str, plan: TaskPlan) -> float: ...


class Planner(Protocol):
    def create(
        self,
        intent: IntentResult,
        slots: SlotState,
        *,
        system_idempotency_key: str | None = None,
        request: AgentRequest | None = None,
        allowed_tools: list[dict[str, object]] | None = None,
    ) -> TaskPlan | Awaitable[TaskPlan]: ...


class AgentService:
    def __init__(
        self,
        *,
        router: Router,
        slots: SlotTracker,
        planner: Planner,
        verifier: PlanVerifier,
        capabilities: CapabilityBroker,
        gateway: Gateway,
        responses: SafeResponseGenerator | None = None,
        plan_reviewer: PlanReviewer | None = None,
        plan_review_threshold: float = 0.5,
    ) -> None:
        self._router = router
        self._slots = slots
        self._planner = planner
        self._verifier = verifier
        self._capabilities = capabilities
        self._gateway = gateway
        self._responses = responses or SafeResponseGenerator()
        self._plan_reviewer = plan_reviewer
        self._plan_review_threshold = plan_review_threshold

    async def handle(self, request: AgentRequest, context: TrustedAgentContext) -> AgentResponse:
        if request.confirmation is not None:
            confirmed_intent = request.confirmation.intent
            intent = IntentResult(
                intent=confirmed_intent,
                complexity=3,
                confidence=1.0,
                route=Route.PLANNER,
                reason="user-confirmed clarification form",
                required_slots=list(REQUIRED_SLOTS_BY_INTENT[confirmed_intent]),
            )
            slot_state = self._slots.from_confirmation(request.confirmation.fields, intent)
        else:
            contextual_text, active_conversation = self._active_context(request)
            routed = self._router.route(request.message, conversation=active_conversation)
            intent = await routed if isinstance(routed, Awaitable) else routed
            if intent.intent == Intent.CORRECT_EXPENSE_CATEGORY:
                return AgentResponse(
                    request_id=request.request_id,
                    session_id=request.session_id,
                    task_id=context.task_id,
                    status=AgentResponseStatus.NEEDS_CLARIFICATION,
                    message=(
                        "Category correction is available only through the structured "
                        "transaction view in v1."
                    ),
                )
            if intent.intent == Intent.GENERAL_CHAT:
                reply = intent.reply
                if is_english(request.locale) and (not reply or contains_cjk(reply)):
                    reply = "Hello! I can help with your bank accounts and financial tasks."
                return AgentResponse(
                    request_id=request.request_id,
                    session_id=request.session_id,
                    task_id=context.task_id,
                    status=AgentResponseStatus.COMPLETED,
                    message=reply or "你好，我可以帮助你处理银行账户与财务任务。",
                )
            if intent.route == Route.SAFE_FALLBACK:
                fallback = intent.reply
                if is_english(request.locale) and (not fallback or contains_cjk(fallback)):
                    fallback = (
                        "I couldn't identify that request safely. Please describe the account, "
                        "spending, budget, subscription, card, investment, savings, or transfer "
                        "task you want to complete."
                    )
                return AgentResponse(
                    request_id=request.request_id,
                    session_id=request.session_id,
                    task_id=context.task_id,
                    status=AgentResponseStatus.NEEDS_CLARIFICATION,
                    message=(
                        fallback
                        or "当前请求无法安全识别，请明确说明账户、消费、预算、订阅、银行卡、"
                        "理财、储蓄罐或转账需求。"
                    ),
                )
            slot_state = self._slots.extract(contextual_text, intent)
        inferred = any(fact.source.value == "MODEL_INFERRED" for fact in slot_state.facts.values())
        if slot_state.missing or inferred:
            return await self._clarification_response(request, context, intent, slot_state)
        try:
            actions = self._capabilities.allowed_actions(context=context, intent=intent.intent)
            planned = self._planner.create(
                intent,
                slot_state,
                system_idempotency_key=str(context.task_id),
                request=request,
                allowed_tools=self._capabilities.schemas(context=context, intent=intent.intent),
            )
            plan = await planned if isinstance(planned, Awaitable) else planned
            verified = self._verifier.verify(plan, actions)
        except PlanValidationError as exc:
            needs_input = exc.code in {"INFERRED_ARGUMENT", "MISSING_SLOTS"}
            validation_message = (
                (
                    "The plan contains financial details that you have not confirmed. "
                    "Please provide or confirm them."
                    if needs_input
                    else "The plan did not pass deterministic safety checks."
                )
                if is_english(request.locale)
                else (
                    "计划包含未经用户确认的金融参数，请补充或明确相关信息。"
                    if needs_input
                    else "计划未通过确定性安全校验。"
                )
            )
            return AgentResponse(
                request_id=request.request_id,
                session_id=request.session_id,
                task_id=context.task_id,
                status=(
                    AgentResponseStatus.NEEDS_CLARIFICATION
                    if needs_input
                    else AgentResponseStatus.FAILED
                ),
                message=validation_message,
                error=AgentError(code=exc.code, message=str(exc)),
            )
        if self._plan_reviewer is not None:
            try:
                review = await self._plan_reviewer.review_plan(request.message, plan)
            except (JevUnavailable, TimeoutError) as exc:
                logger.warning("plan review unavailable: %s", type(exc).__name__)
                return AgentResponse(
                    request_id=request.request_id,
                    session_id=request.session_id,
                    task_id=context.task_id,
                    status=AgentResponseStatus.NEEDS_CLARIFICATION,
                    message=(
                        "Plan review is temporarily unavailable; no action was executed."
                        if is_english(request.locale)
                        else "计划复核暂不可用，未执行任何操作。"
                    ),
                    plan=localize_plan(plan, request.locale),
                    error=AgentError(
                        code="PLAN_REVIEW_UNAVAILABLE",
                        message="plan review provider unavailable",
                    ),
                )
            if review < self._plan_review_threshold:
                return AgentResponse(
                    request_id=request.request_id,
                    session_id=request.session_id,
                    task_id=context.task_id,
                    status=AgentResponseStatus.NEEDS_CLARIFICATION,
                    message=(
                        "The plan does not match the request. Please clarify your request."
                        if is_english(request.locale)
                        else "计划与请求不一致，请补充或明确需求。"
                    ),
                    plan=localize_plan(plan, request.locale),
                    error=AgentError(
                        code="PLAN_REVIEW_REJECTED", message="plan review below threshold"
                    ),
                )
        execution_context = ExecutionContext(
            authenticated_user_id=context.authenticated_user_id,
            session_id=context.session_id,
            task_id=context.task_id,
            trace_id=context.trace_id,
            authorization_reference=context.authorization_reference,
        )
        last_result: ToolResult[Any] | None = None
        for step_id in verified.ordered_step_ids:
            step = next(item for item in plan.steps if item.step_id == step_id)
            if step.tool_call is None:
                continue
            last_result = await self._gateway.execute(
                tool_name=step.tool_call.tool_name,
                arguments=dict(step.tool_call.arguments),
                context=execution_context,
            )
            if last_result.status != ToolResultStatus.SUCCESS:
                break
        if last_result is None:
            return AgentResponse(
                request_id=request.request_id,
                session_id=request.session_id,
                task_id=context.task_id,
                status=AgentResponseStatus.FAILED,
                message=(
                    "The plan has no executable steps."
                    if is_english(request.locale)
                    else "计划没有可执行步骤。"
                ),
                plan=localize_plan(plan, request.locale),
                error=AgentError(code="NO_EXECUTABLE_STEP", message="empty execution"),
            )
        response_status = (
            AgentResponseStatus.COMPLETED
            if last_result.status == ToolResultStatus.SUCCESS
            else AgentResponseStatus.WAITING_APPROVAL
            if last_result.status
            in {ToolResultStatus.WAITING_APPROVAL, ToolResultStatus.MFA_REQUIRED}
            else AgentResponseStatus.FAILED
        )
        data = last_result.data.model_dump(mode="json") if last_result.data is not None else None
        public_plan = localize_plan(plan, request.locale)
        return AgentResponse(
            request_id=request.request_id,
            session_id=request.session_id,
            task_id=context.task_id,
            status=response_status,
            message=(
                self._responses.compose(
                    status=response_status,
                    plan=public_plan,
                    data=data,
                )
            ),
            plan=public_plan,
            result=data,
            error=(
                None
                if response_status != AgentResponseStatus.FAILED
                else AgentError(
                    code=last_result.error_code or "TOOL_EXECUTION_FAILED",
                    message=last_result.message or "tool execution failed",
                )
            ),
        )

    @staticmethod
    def _active_context(
        request: AgentRequest,
    ) -> tuple[str, list[ConversationMessage]]:
        active: list[ConversationMessage] = []
        in_clarification = False
        for message in reversed(request.conversation):
            if message.role == ConversationRole.ASSISTANT:
                if message.content.startswith("[CLARIFICATION]"):
                    in_clarification = True
                    active.append(message)
                    continue
                if in_clarification:
                    break
                continue
            if message.role == ConversationRole.USER and in_clarification:
                active.append(message)
        active.reverse()
        user_text = [
            message.content
            for message in active
            if message.role == ConversationRole.USER
        ]
        user_text.append(request.message)
        return "\n".join(user_text), active

    async def _clarification_response(
        self,
        request: AgentRequest,
        context: TrustedAgentContext,
        intent: IntentResult,
        slots: SlotState,
    ) -> AgentResponse:
        labels = FIELD_LABELS[request.locale]
        input_types = {
            "category": "combobox",
            "month_date": "month",
            "limit_amount": "amount",
            "source_account_id": "select",
            "destination_account_id": "combobox",
            "account_id": "select",
            "target_date": "date",
            "amount": "amount",
            "target_amount": "amount",
        }
        options: dict[str, list[ClarificationOption]] = {}
        if intent.intent == Intent.CREATE_BUDGET:
            options["category"] = [
                ClarificationOption(
                    value=label,
                    label=(
                        f"{label} ({value})"
                        if is_english(request.locale)
                        else f"{label}（{value}）"
                    ),
                )
                for value, label in BUDGET_CATEGORIES[request.locale].items()
            ]
        execution_context = ExecutionContext(
            authenticated_user_id=context.authenticated_user_id,
            session_id=context.session_id,
            task_id=context.task_id,
            trace_id=context.trace_id,
        )
        if intent.intent == Intent.TRANSFER:
            accounts = await self._gateway.execute(
                tool_name="get_accounts", arguments={}, context=execution_context
            )
            if accounts.status == ToolResultStatus.SUCCESS and accounts.data is not None:
                payload = accounts.data.model_dump(mode="json")
                options["source_account_id"] = [
                    ClarificationOption(
                        value=str(item["id"]),
                        label=f'{item["name"]} · {item["account_number"]}',
                    )
                    for item in payload.get("accounts", [])
                    if item.get("status") == "ACTIVE"
                ]
            beneficiaries = await self._gateway.execute(
                tool_name="list_beneficiaries",
                arguments={},
                context=execution_context,
            )
            if beneficiaries.status == ToolResultStatus.SUCCESS and beneficiaries.data is not None:
                payload = beneficiaries.data.model_dump(mode="json")
                items = payload.get("beneficiaries", [])
                options["destination_account_id"] = [
                    ClarificationOption(
                        value=str(item["destination_account_id"]),
                        label=(
                            f'{item["name"]}'
                            + (
                                f' ({item["nickname"]})'
                                if is_english(request.locale) and item.get("nickname")
                                else f'（{item["nickname"]}）'
                                if item.get("nickname")
                                else ""
                            )
                            + (
                                f' · ending in {str(item["destination_account_number"])[-4:]}'
                                if is_english(request.locale)
                                else f' · 尾号 {str(item["destination_account_number"])[-4:]}'
                            )
                        ),
                    )
                    for item in items
                ]
                query = slots.facts.get("beneficiary_query")
                if query is not None and "destination_account_id" not in slots.facts:
                    normalized = str(query.value).strip().lower()
                    matches = [
                        item
                        for item in items
                        if str(item["name"]).lower() == normalized
                        or str(item.get("nickname") or "").lower() == normalized
                    ]
                    if len(matches) == 1:
                        slots.facts["destination_account_id"] = SlotFact(
                            "destination_account_id",
                            str(matches[0]["destination_account_id"]),
                            FactSource.TOOL_VERIFIED,
                        )
                        slots.missing = [
                            name for name in slots.missing if name != "destination_account_id"
                        ]
        field_names = list(dict.fromkeys([*intent.required_slots, *slots.facts.keys()]))
        field_names = [name for name in field_names if name != "beneficiary_query"]
        fields = [
            ClarificationField(
                name=name,
                label=labels.get(name, name.replace("_", " ")),
                input_type=input_types.get(name, "text"),
                required=name in intent.required_slots,
                value=slots.facts[name].value if name in slots.facts else None,
                inferred=(
                    name in slots.facts and slots.facts[name].source.value == "MODEL_INFERRED"
                ),
                options=options.get(name, []),
            )
            for name in field_names
        ]
        inferred_labels = [field.label for field in fields if field.inferred]
        missing_labels = [labels.get(name, name.replace("_", " ")) for name in slots.missing]
        if intent.intent == Intent.TRANSFER:
            message = "请选择付款账户，并输入或选择以前保存的收款人；系统不会要求你复制内部 UUID。"
        elif inferred_labels:
            suffix = f"，并补充：{'、'.join(missing_labels)}" if missing_labels else ""
            message = f"我根据上下文推断了{'、'.join(inferred_labels)}{suffix}。请检查表单后确认。"
        else:
            message = f"为了继续，请补充：{'、'.join(missing_labels)}。"
        clarification = ClarificationPayload(
            kind="CONFIRM_INFERRED" if inferred_labels else "MISSING_FIELDS",
            intent=intent.intent.value,
            fields=fields,
        )
        return AgentResponse(
            request_id=request.request_id,
            session_id=request.session_id,
            task_id=context.task_id,
            status=AgentResponseStatus.NEEDS_CLARIFICATION,
            message=message,
            result={"clarification": clarification.model_dump(mode="json")},
        )


def new_trusted_context(user_id: Any, session_id: Any) -> TrustedAgentContext:
    """Development helper; production middleware must provide these trusted values."""
    return TrustedAgentContext(
        authenticated_user_id=user_id,
        session_id=session_id,
        task_id=uuid4(),
        trace_id=uuid4(),
    )
