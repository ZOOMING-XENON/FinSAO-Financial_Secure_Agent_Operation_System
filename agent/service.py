"""Single-turn safe Agent service; durable approval/resume belongs to P3."""

from __future__ import annotations

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
from agent.planning import PlanValidationError, PlanVerifier
from agent.responses import SafeResponseGenerator
from agent.routing import REQUIRED_SLOTS_BY_INTENT, Intent, IntentResult, Route
from agent_tools.contracts import ExecutionContext, ToolResult, ToolResultStatus


class Gateway(Protocol):
    async def execute(
        self, *, tool_name: str, arguments: dict[str, Any], context: ExecutionContext
    ) -> ToolResult[Any]: ...


class Router(Protocol):
    def route(
        self, text: str, *, conversation: list[Any] | None = None
    ) -> IntentResult | Awaitable[IntentResult]: ...


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
    ) -> None:
        self._router = router
        self._slots = slots
        self._planner = planner
        self._verifier = verifier
        self._capabilities = capabilities
        self._gateway = gateway
        self._responses = responses or SafeResponseGenerator()

    async def handle(self, request: AgentRequest, context: TrustedAgentContext) -> AgentResponse:
        if request.confirmation is not None:
            confirmed_intent = request.confirmation.intent
            intent = IntentResult(
                intent=confirmed_intent,
                complexity=3,
                confidence=1.0,
                route=Route.PLANNER,
                reason="llm:confirmed clarification form",
                required_slots=list(REQUIRED_SLOTS_BY_INTENT[confirmed_intent]),
            )
            slot_state = self._slots.from_confirmation(request.confirmation.fields, intent)
        else:
            contextual_text, active_conversation = self._active_context(request)
            routed = self._router.route(request.message, conversation=active_conversation)
            intent = await routed if isinstance(routed, Awaitable) else routed
            if intent.intent == Intent.GENERAL_CHAT:
                return AgentResponse(
                    request_id=request.request_id,
                    session_id=request.session_id,
                    task_id=context.task_id,
                    status=AgentResponseStatus.COMPLETED,
                    message=intent.reply or "你好，我可以帮助你处理银行账户与财务任务。",
                )
            if intent.route == Route.SAFE_FALLBACK:
                return AgentResponse(
                    request_id=request.request_id,
                    session_id=request.session_id,
                    task_id=context.task_id,
                    status=AgentResponseStatus.NEEDS_CLARIFICATION,
                    message=(
                        intent.reply
                        or "当前请求无法安全识别，请明确说明账户、消费、预算、订阅、银行卡、"
                        "理财、储蓄罐或转账需求。"
                    ),
                )
            slot_state = (
                self._slots.from_llm_evidence(request.message, intent)
                if intent.reason.startswith("llm:")
                else self._slots.extract(contextual_text, intent)
            )
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
            return AgentResponse(
                request_id=request.request_id,
                session_id=request.session_id,
                task_id=context.task_id,
                status=(
                    AgentResponseStatus.NEEDS_CLARIFICATION
                    if needs_input
                    else AgentResponseStatus.FAILED
                ),
                message=(
                    "计划包含未经用户确认的金融参数，请补充或明确相关信息。"
                    if needs_input
                    else "计划未通过确定性安全校验。"
                ),
                error=AgentError(code=exc.code, message=str(exc)),
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
                message="计划没有可执行步骤。",
                plan=plan,
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
        return AgentResponse(
            request_id=request.request_id,
            session_id=request.session_id,
            task_id=context.task_id,
            status=response_status,
            message=(
                self._responses.compose(status=response_status, plan=plan, data=data)
            ),
            plan=plan,
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
        # The current message is the strongest expression of user intent.  Put it first
        # so deterministic extractors take its recipient, amount and dates before older
        # clarification context.  Older messages remain available only to fill fields
        # that the current message omitted.
        return "\n".join([request.message, *user_text]), active

    async def _clarification_response(
        self,
        request: AgentRequest,
        context: TrustedAgentContext,
        intent: IntentResult,
        slots: SlotState,
    ) -> AgentResponse:
        labels = {
            "category": "预算类别",
            "month_date": "预算日期",
            "limit_amount": "预算上限",
            "source_account_id": "付款账户",
            "destination_account_id": "收款人（可输入姓名自动匹配）",
            "amount": "金额",
            "currency": "币种",
            "name": "储蓄目标名称",
            "target_amount": "目标金额",
            "target_date": "目标日期",
            "account_id": "账户",
            "product_id": "理财产品",
            "resource_id": "目标资源",
        }
        input_types = {
            "category": "combobox",
            "month_date": "date",
            "limit_amount": "amount",
            "source_account_id": "select",
            "destination_account_id": "combobox",
            "account_id": "select",
            "target_date": "date",
            "amount": "amount",
            "target_amount": "amount",
        }
        options: dict[str, list[ClarificationOption]] = {}
        resolved_beneficiary: dict[str, Any] | None = None
        beneficiary_resolution_status: str | None = None
        if intent.intent == Intent.CREATE_BUDGET:
            options["category"] = [
                ClarificationOption(value=label, label=f"{label}（{value}）")
                for value, label in {
                    "HOUSEHOLD": "家居",
                    "GROCERIES": "日用",
                    "TRANSPORT": "交通",
                    "ENTERTAINMENT": "娱乐",
                    "DINING": "餐饮",
                    "HEALTHCARE": "医疗",
                    "EDUCATION": "教育",
                    "TRAVEL": "旅行",
                }.items()
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
            query = slots.facts.get("beneficiary_query")
            if query is not None and "destination_account_id" not in slots.facts:
                resolution = await self._gateway.execute(
                    tool_name="resolve_beneficiary",
                    arguments={"query": str(query.value)},
                    context=execution_context,
                )
                if resolution.status == ToolResultStatus.SUCCESS and resolution.data is not None:
                    resolution_payload = resolution.data.model_dump(mode="json")
                    beneficiary_resolution_status = str(resolution_payload.get("status", ""))
                    matches = resolution_payload.get("matches", [])
                    if beneficiary_resolution_status == "RESOLVED" and len(matches) == 1:
                        resolved_beneficiary = matches[0]
                        slots.facts["destination_account_id"] = SlotFact(
                            "destination_account_id",
                            str(resolved_beneficiary["destination_account_id"]),
                            FactSource.TOOL_VERIFIED,
                        )
                        slots.missing = [
                            name for name in slots.missing if name != "destination_account_id"
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
                            + (f'（{item["nickname"]}）' if item.get("nickname") else "")
                            + f' · 尾号 {str(item["destination_account_number"])[-4:]}'
                        ),
                    )
                    for item in items
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
            if resolved_beneficiary is not None:
                account_tail = str(resolved_beneficiary["destination_account_number"])[-4:]
                message = (
                    f'我匹配到了已保存的收款人“{resolved_beneficiary["name"]}”'
                    f'（账户尾号 {account_tail}）。为了确保信息无误，'
                    "我给您发了一份确认表单，请核对付款账户、收款人和金额；"
                    "确认后才会创建转账草稿并进入授权。"
                )
            elif beneficiary_resolution_status == "AMBIGUOUS":
                message = "找到多个同名收款人，请核对账户尾号后选择；确认前不会转账。"
            elif beneficiary_resolution_status == "NOT_FOUND":
                message = "未在已保存的收款人中找到该名称，请从列表选择或先添加收款人。"
            else:
                message = (
                    "请选择付款账户，并输入或选择以前保存的收款人；"
                    "系统不会要求你复制内部 UUID。"
                )
        elif inferred_labels:
            suffix = f"，并补充：{'、'.join(missing_labels)}" if missing_labels else ""
            message = (
                f"我先按您的描述整理出了{'、'.join(inferred_labels)}{suffix}。"
                "这些内容里有模型理解的部分，所以想请您花几秒核对一下下方表单；"
                "您确认后，我就会接着往下处理。"
            )
        else:
            message = (
                f"这件事我已经开始处理了，不过还差：{'、'.join(missing_labels)}。"
                "请在下方表单里补充一下，收到您的回复后我会从这里继续，"
                "不需要您重新描述整个需求。"
            )
        clarification = ClarificationPayload(
            kind=(
                "CONFIRM_RESOLVED_BENEFICIARY"
                if resolved_beneficiary is not None
                else "CONFIRM_INFERRED"
                if inferred_labels
                else "MISSING_FIELDS"
            ),
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
