"""Single-turn safe Agent service; durable approval/resume belongs to P3."""

from __future__ import annotations

import logging
import re
from collections.abc import Awaitable
from datetime import datetime
from typing import Any, Protocol
from uuid import uuid4
from zoneinfo import ZoneInfo

from pydantic import ValidationError

from agent.beneficiary_ranking import ModelBeneficiaryRanker
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
from agent.jev_http import JevAuthError, JevUnavailable
from agent.localization import (
    BUDGET_CATEGORIES,
    FIELD_LABELS,
    contains_cjk,
    is_english,
    localize_entity_name,
    localize_plan,
)
from agent.planning import PlanValidationError, PlanVerifier
from agent.responses import SafeResponseGenerator
from agent.routing import REQUIRED_SLOTS_BY_INTENT, Intent, IntentResult, Route
from agent.transfer_reasoning import ModelTransferReasoner, VerifiedBalance
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
    async def review_plan(
        self, text: str, plan: TaskPlan, intent: Intent | None = None
    ) -> float: ...


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
        beneficiary_ranker: ModelBeneficiaryRanker | None = None,
        transfer_reasoner: ModelTransferReasoner | None = None,
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
        self._beneficiary_ranker = beneficiary_ranker
        self._transfer_reasoner = transfer_reasoner

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
            if (
                context.expected_intent is not None
                and context.expected_intent != Intent.GENERAL_CHAT
            ):
                intent = IntentResult(
                    intent=context.expected_intent,
                    complexity=3,
                    confidence=1.0,
                    route=Route.PLANNER,
                    reason="server-verified bundle intent",
                    required_slots=list(REQUIRED_SLOTS_BY_INTENT.get(context.expected_intent, ())),
                    proposed_slots=context.expected_slots,
                )
            else:
                routed = self._router.route(request.message, conversation=active_conversation)
                intent = await routed if isinstance(routed, Awaitable) else routed
            transfer_analysis = None
            if (
                (
                    intent.intent == Intent.TRANSFER
                    or (
                        context.expected_intent is None
                        and intent.intent not in {Intent.GENERAL_CHAT, Intent.UNKNOWN}
                    )
                )
                and self._transfer_reasoner is not None
            ):
                transfer_analysis = await self._transfer_reasoner.analyze(
                    message=request.message,
                    conversation=request.conversation,
                    request_id=request.request_id,
                    verified_balances=self._verified_balances(context),
                )
                if transfer_analysis is not None and (
                    transfer_analysis.multiple_actions
                    or (
                        intent.intent == Intent.TRANSFER
                        and transfer_analysis.requires_clarification
                    )
                ):
                    percentage_needs_balance = (
                        intent.intent == Intent.TRANSFER
                        and transfer_analysis.requires_clarification
                        and transfer_analysis.percentage_requested
                    )
                    message = (
                        "I found multiple financial actions. Please review them separately; "
                        "no action was executed."
                        if transfer_analysis.multiple_actions and is_english(request.locale)
                        else "我识别到多项资金操作。请分别审核；目前没有执行任何操作。"
                        if transfer_analysis.multiple_actions
                        else (
                            "I need a verified account balance to calculate this percentage. "
                            "No transfer was made."
                        )
                        if percentage_needs_balance and is_english(request.locale)
                        else "需要先确认用于计算的账户余额，才能得出转账金额；目前没有转账。"
                        if percentage_needs_balance
                        else "I need the bill total, number of people, and who paid before "
                        "calculating the transfer. No action was executed."
                        if is_english(request.locale)
                        else (
                            "请明确账单总额、分摊人数及谁先付款，再计算转账额；"
                            "目前没有执行任何操作。"
                        )
                    )
                    return AgentResponse(
                        request_id=request.request_id,
                        session_id=request.session_id,
                        task_id=context.task_id,
                        status=AgentResponseStatus.NEEDS_CLARIFICATION,
                        message=message,
                    )
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
            if intent.intent == Intent.GET_BUDGET_STATUS and "resource_id" in slot_state.missing:
                if not await self._resolve_budget_reference(request, context, slot_state):
                    return AgentResponse(
                        request_id=request.request_id,
                        session_id=request.session_id,
                        task_id=context.task_id,
                        status=AgentResponseStatus.FAILED,
                        message=(
                            "I couldn't load your budgets. Please try again."
                            if is_english(request.locale)
                            else "暂时无法读取预算，请稍后重试。"
                        ),
                        error=AgentError(
                            code="BUDGET_LOOKUP_FAILED",
                            message="budget lookup failed",
                            retryable=True,
                        ),
                    )
                candidates = slot_state.facts.get("budget_candidates")
                if candidates is not None and not candidates.value:
                    return AgentResponse(
                        request_id=request.request_id,
                        session_id=request.session_id,
                        task_id=context.task_id,
                        status=AgentResponseStatus.COMPLETED,
                        message=(
                            "No matching budget was found for this month."
                            if is_english(request.locale)
                            else "没有找到本月匹配的预算。"
                        ),
                    )
            if (
                intent.intent == Intent.TRANSFER
                and transfer_analysis is not None
                and transfer_analysis.amount is not None
            ):
                slot_state.facts["amount"] = SlotFact(
                    "amount", transfer_analysis.amount, FactSource.MODEL_INFERRED
                )
                slot_state.missing = [name for name in slot_state.missing if name != "amount"]
                if transfer_analysis.source_account_id is not None:
                    slot_state.facts["source_account_id"] = SlotFact(
                        "source_account_id",
                        str(transfer_analysis.source_account_id),
                        FactSource.TOOL_VERIFIED,
                    )
                    slot_state.missing = [
                        name for name in slot_state.missing if name != "source_account_id"
                    ]
                currency_fact = slot_state.facts.get("currency")
                if (
                    transfer_analysis.currency is not None
                    and (
                        currency_fact is None
                        or currency_fact.source == FactSource.SYSTEM_CONSTANT
                    )
                ):
                    slot_state.facts["currency"] = SlotFact(
                        "currency", transfer_analysis.currency, FactSource.TOOL_VERIFIED
                    )
        if (
            intent.intent in {Intent.UPDATE_EXPENSE, Intent.DELETE_EXPENSE}
            and "expense_id" not in slot_state.facts
        ):
            await self._resolve_expense_reference(context, slot_state)
        inferred = any(
            fact.source == FactSource.MODEL_INFERRED
            and not (
                intent.intent in {Intent.TRACK_EXPENSES, Intent.SUMMARIZE_EXPENSES}
                and name in {"limit", "category"}
            )
            for name, fact in slot_state.facts.items()
        )
        if slot_state.missing or inferred:
            return await self._clarification_response(
                request,
                context,
                intent,
                slot_state,
                transfer_calculation=(
                    transfer_analysis.calculation
                    if request.confirmation is None and transfer_analysis is not None
                    else None
                ),
            )
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
        reviewer = self._plan_reviewer
        should_review = (
            reviewer is not None
            and intent.reason.startswith(("llm:", "jev:"))
            and intent.intent not in {
                Intent.RECORD_EXPENSE,
                Intent.UPDATE_EXPENSE,
                Intent.DELETE_EXPENSE,
            }
            and any(
                step.tool_call is not None
                and step.tool_call.tool_name
                in {
                    "create_transfer_draft",
                    "commit_transfer",
                    "create_wealth_subscription_draft",
                    "commit_wealth_subscription",
                    "create_wealth_redemption_draft",
                    "commit_wealth_redemption",
                    "cancel_subscription",
                    "update_card_limit",
                    "freeze_card",
                    "unfreeze_card",
                    "report_card_lost",
                    "contribute_savings_pot",
                }
                for step in plan.steps
            )
        )
        if should_review and reviewer is not None:
            try:
                review = await reviewer.review_plan(
                    request.message, plan, intent.intent
                )
            except (JevUnavailable, TimeoutError) as exc:
                logger.warning("plan review unavailable: %s", type(exc).__name__)
                auth_failed = isinstance(exc, JevAuthError)
                return AgentResponse(
                    request_id=request.request_id,
                    session_id=request.session_id,
                    task_id=context.task_id,
                    status=AgentResponseStatus.NEEDS_CLARIFICATION,
                    message=(
                        "Plan review is not configured correctly; no action was executed."
                        if auth_failed and is_english(request.locale)
                        else "计划审查未正确配置，未执行任何操作。"
                        if auth_failed
                        else "Plan review is temporarily unavailable; no action was executed."
                        if is_english(request.locale)
                        else "计划审查暂时不可用，未执行任何操作。"
                    ),
                    plan=localize_plan(plan, request.locale),
                    error=AgentError(
                        code=(
                            "JEV_AUTH_INVALID"
                            if auth_failed
                            else "PLAN_REVIEW_UNAVAILABLE"
                        ),
                        message=(
                            "Jev authentication failed"
                            if auth_failed
                            else "plan review provider unavailable"
                        ),
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
                    locale=request.locale,
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
    def _verified_balances(context: TrustedAgentContext) -> list[VerifiedBalance]:
        balances: list[VerifiedBalance] = []
        for raw in context.verified_balances:
            try:
                balances.append(VerifiedBalance.model_validate(raw))
            except ValidationError:
                continue
        return balances

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

    async def _resolve_expense_reference(
        self, context: TrustedAgentContext, slots: SlotState
    ) -> None:
        reference = slots.facts.get("expense_ref")
        if reference is None:
            return
        execution_context = ExecutionContext(
            authenticated_user_id=context.authenticated_user_id,
            session_id=context.session_id,
            task_id=context.task_id,
            trace_id=context.trace_id,
        )
        result = await self._gateway.execute(
            tool_name="get_expenses",
            arguments={
                "merchant": str(reference.value),
                "limit": 5,
                "sort_by": "posted_at",
                "sort_direction": "desc",
            },
            context=execution_context,
        )
        if result.status != ToolResultStatus.SUCCESS or result.data is None:
            return
        payload = result.data.model_dump(mode="json")
        items = payload.get("items", [])
        if not isinstance(items, list) or not items:
            return
        if len(items) > 1:
            slots.facts["expense_candidates"] = SlotFact(
                "expense_candidates", items, FactSource.TOOL_VERIFIED
            )
            return
        expense_id = items[0].get("id") if isinstance(items[0], dict) else None
        if not expense_id:
            return
        slots.facts["expense_id"] = SlotFact(
            "expense_id", str(expense_id), FactSource.TOOL_VERIFIED
        )
        slots.missing = [name for name in slots.missing if name != "expense_id"]

    async def _resolve_budget_reference(
        self, request: AgentRequest, context: TrustedAgentContext, slots: SlotState
    ) -> bool:
        execution_context = ExecutionContext(
            authenticated_user_id=context.authenticated_user_id,
            session_id=context.session_id,
            task_id=context.task_id,
            trace_id=context.trace_id,
        )
        result = await self._gateway.execute(
            tool_name="list_budgets", arguments={}, context=execution_context
        )
        if result.status != ToolResultStatus.SUCCESS or result.data is None:
            return False
        payload = result.data.model_dump(mode="json")
        month = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m")
        current = [
            item for item in payload.get("items", [])
            if isinstance(item, dict) and str(item.get("month", "")).startswith(month)
        ]
        proposed_category = context.expected_slots.get("category")
        if (
            isinstance(proposed_category, str)
            and proposed_category.upper() in BUDGET_CATEGORIES[request.locale]
        ):
            requested = [proposed_category.upper()]
        else:
            requested = [
                key for key, label in BUDGET_CATEGORIES[request.locale].items()
                if key.casefold() in request.message.casefold()
                or label.casefold() in request.message.casefold()
            ]
        if requested:
            current = [
                item for item in current
                if str(item.get("category", "")).casefold() in {
                    key.casefold() for key in requested
                }
            ]
        slots.facts["budget_candidates"] = SlotFact(
            "budget_candidates", current, FactSource.TOOL_VERIFIED
        )
        if len(current) == 1:
            slots.facts["resource_id"] = SlotFact(
                "resource_id", str(current[0]["id"]), FactSource.TOOL_VERIFIED
            )
            slots.missing = [name for name in slots.missing if name != "resource_id"]
        return True

    async def _clarification_response(
        self,
        request: AgentRequest,
        context: TrustedAgentContext,
        intent: IntentResult,
        slots: SlotState,
        transfer_calculation: str | None = None,
    ) -> AgentResponse:
        labels = FIELD_LABELS[request.locale]
        input_types = {
            "category": "combobox",
            "expense_id": "select",
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
        beneficiary_suggestion: tuple[str, str] | None = None
        candidates = slots.facts.get("expense_candidates")
        if candidates is not None and isinstance(candidates.value, list):
            options["expense_id"] = [
                ClarificationOption(
                    value=str(item.get("id")),
                    label=(
                        f'{item.get("merchant") or item.get("description") or "expense"} '
                        f'{item.get("amount", "")} {item.get("currency", "")} '
                        f'({item.get("posted_at", "")})'
                    ),
                )
                for item in candidates.value
                if isinstance(item, dict) and item.get("id")
            ]
        budget_candidates = slots.facts.get("budget_candidates")
        if intent.intent == Intent.GET_BUDGET_STATUS and budget_candidates is not None:
            options["resource_id"] = []
            for item in budget_candidates.value:
                category = str(item["category"])
                label = BUDGET_CATEGORIES[request.locale].get(category, category)
                options["resource_id"].append(
                    ClarificationOption(
                        value=str(item["id"]), label=f'{label} · {item["month"]}'
                    )
                )
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
                active_accounts = [
                    item for item in payload.get("accounts", []) if item.get("status") == "ACTIVE"
                ]
                options["source_account_id"] = [
                    ClarificationOption(
                        value=str(item["id"]),
                        label=(
                            f'{localize_entity_name(item["name"], request.locale)}'
                            f' · {item["account_number"]}'
                        ),
                    )
                    for item in active_accounts
                ]
                if "source_account_id" not in slots.facts:
                    requested_name = (
                        "Savings"
                        if re.search(
                            r"\b(?:savings?|saving account)\b|储蓄",
                            request.message,
                            re.IGNORECASE,
                        )
                        else "Checking"
                    )
                    currency = slots.facts.get("currency")
                    matches = [
                        item
                        for item in active_accounts
                        if str(item.get("name") or "").casefold() == requested_name.casefold()
                        and (
                            currency is None
                            or str(item.get("currency") or "") == str(currency.value)
                        )
                    ]
                    if len(matches) == 1:
                        slots.facts["source_account_id"] = SlotFact(
                            "source_account_id",
                            str(matches[0]["id"]),
                            FactSource.TOOL_VERIFIED,
                        )
                        slots.missing = [
                            name for name in slots.missing if name != "source_account_id"
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
                            f'{localize_entity_name(item["name"], request.locale)}'
                            + (
                                f' ({localize_entity_name(item["nickname"], request.locale)})'
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
                        matched_source = (
                            FactSource.MODEL_INFERRED
                            if query.source == FactSource.MODEL_INFERRED
                            else FactSource.TOOL_VERIFIED
                        )
                        slots.facts["destination_account_id"] = SlotFact(
                            "destination_account_id",
                            str(matches[0]["destination_account_id"]),
                            matched_source,
                        )
                        slots.missing = [
                            name for name in slots.missing if name != "destination_account_id"
                        ]
                        if matched_source == FactSource.MODEL_INFERRED:
                            display_name = localize_entity_name(
                                matches[0].get("name"), request.locale
                            )
                            reason = (
                                "It matches the person named in your request."
                                if is_english(request.locale)
                                else "与您这轮提到的人相符"
                            )
                            beneficiary_suggestion = (display_name, reason)
                if (
                    "destination_account_id" not in slots.facts
                    and self._beneficiary_ranker is not None
                    and items
                ):
                    recommendation = await self._beneficiary_ranker.rank(
                        message=request.message,
                        conversation=request.conversation,
                        candidates=items,
                        locale=request.locale,
                        request_id=request.request_id,
                    )
                    if recommendation is not None:
                        selected = recommendation.candidate
                        slots.facts["destination_account_id"] = SlotFact(
                            "destination_account_id",
                            str(selected["destination_account_id"]),
                            FactSource.MODEL_INFERRED,
                        )
                        slots.missing = [
                            name for name in slots.missing if name != "destination_account_id"
                        ]
                        display_name = localize_entity_name(
                            selected.get("name"), request.locale
                        )
                        reason = recommendation.reason
                        if is_english(request.locale) and contains_cjk(reason):
                            reason = "It best matches the recent conversation."
                        beneficiary_suggestion = (display_name, reason)
        if intent.intent == Intent.RECORD_EXPENSE:
            field_names = ["amount", "currency", "merchant"]
            if "category" in slots.facts:
                field_names.append("category")
        elif intent.intent in {Intent.UPDATE_EXPENSE, Intent.DELETE_EXPENSE}:
            field_names = ["expense_id", *(
                name
                for name in ("amount", "currency", "merchant", "category")
                if name in slots.facts
            )]
        else:
            field_names = list(
                dict.fromkeys([*intent.required_slots, *slots.facts.keys()])
            )
            field_names = [
                name for name in field_names
                if name not in {"beneficiary_query", "budget_candidates", "expense_candidates"}
            ]
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
        if (
            intent.intent == Intent.RECORD_EXPENSE
            and "expense_ambiguity" in slots.facts
        ):
            message = (
                "I found more than one possible expense. Please record them one at a "
                "time, or provide one merchant for this entry."
                if is_english(request.locale)
                else "??????????????????????????????"
            )
        elif intent.intent == Intent.TRANSFER:
            if beneficiary_suggestion is not None:
                name, reason = beneficiary_suggestion
                message = (
                    f"AI suggested {name}: {reason} Review every field before confirming."
                    if is_english(request.locale)
                    else f"AI 建议收款人为 {name}：{reason} 请在确认前检查所有字段。"
                )
            else:
                message = (
                    "Review the source account and choose a saved beneficiary. The form never "
                    "asks you to copy an internal UUID."
                    if is_english(request.locale)
                    else "请检查付款账户，并选择以前保存的收款人；系统不会要求你复制内部 UUID。"
                )
            if transfer_calculation is not None:
                message = (
                    f"Calculated share: {transfer_calculation}. {message}"
                    if is_english(request.locale)
                    else f"平摊金额：{transfer_calculation}。{message}"
                )
        elif inferred_labels:
            suffix = (
                f" and add: {', '.join(missing_labels)}" if missing_labels else ""
            )
            zh_suffix = (
                f"，并补充：{'、'.join(missing_labels)}" if missing_labels else ""
            )
            message = (
                f"I inferred {', '.join(inferred_labels)}{suffix}. Please review and confirm."
                if is_english(request.locale)
                else f"我根据上下文推断了{'、'.join(inferred_labels)}{zh_suffix}。"
                "请检查表单后确认。"
            )
        else:
            message = (
                f"To continue, provide: {', '.join(missing_labels)}."
                if is_english(request.locale)
                else f"为了继续，请补充：{'、'.join(missing_labels)}。"
            )
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
