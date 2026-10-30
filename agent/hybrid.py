"""Configurable LLM-only or rule-first routing with deterministic safety boundaries."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from datetime import date
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator

from agent.context import FactSource, SlotState
from agent.contracts import (
    AgentRequest,
    ArgumentSourceKind,
    ConversationMessage,
    ConversationRole,
    TaskPlan,
    TrustLabel,
)
from agent.planning import BaselinePlanner
from agent.providers import ModelProvider, ProviderError
from agent.routing import REQUIRED_SLOTS_BY_INTENT, Intent, IntentResult, Route, RuleRouter

logger = logging.getLogger(__name__)


class LlmIntentDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    intent: Intent
    confidence: float = Field(ge=0, le=1)
    reply: str | None = Field(default=None, max_length=1_000)
    proposed_slots: dict[str, JsonValue] = Field(default_factory=dict)
    slot_evidence: dict[str, str] = Field(default_factory=dict)

    @field_validator("proposed_slots")
    @classmethod
    def reject_trusted_slots(cls, value: dict[str, JsonValue]) -> dict[str, JsonValue]:
        forbidden = {
            "user_id",
            "authenticated_user_id",
            "authorization_ref",
            "authorization_reference",
            "mfa_code",
            "risk_tier",
            "approved",
        }
        if forbidden.intersection(value):
            raise ValueError("trusted fields are forbidden in inferred slots")
        return value


class LlmTaskDecomposition(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tasks: list[str] = Field(min_length=1, max_length=5)

    @field_validator("tasks")
    @classmethod
    def validate_tasks(cls, value: list[str]) -> list[str]:
        cleaned = [task.strip() for task in value if task.strip()]
        if not cleaned or any(len(task) > 2_000 for task in cleaned):
            raise ValueError("invalid decomposed tasks")
        return cleaned


class HybridRouter:
    """Use LLM-first routing by default; retain hybrid only as an explicit experiment."""

    def __init__(
        self,
        rules: RuleRouter,
        provider: ModelProvider | None,
        *,
        confidence_threshold: float = 0.65,
        routing_mode: str = "llm_only",
        today: Callable[[], date] = date.today,
    ) -> None:
        self._rules = rules
        self._provider = provider
        self._confidence_threshold = confidence_threshold
        self._routing_mode = routing_mode
        self._today = today

    async def decompose(
        self, text: str, *, conversation: list[Any] | None = None
    ) -> list[str]:
        """Use the model to split compound language without executing any task."""
        if self._provider is None or not self._provider.available:
            return [text]
        messages = [
            ConversationMessage(
                role=ConversationRole.SYSTEM,
                trust=TrustLabel.SYSTEM_POLICY,
                content=(
                    "将用户当前消息分解为 1 到 5 个可独立处理、按原始顺序排列的"
                    "金融子任务。只输出 JSON：{\"tasks\":[\"...\"]}。必须原样保留每个"
                    "金额、币种、日期、人名和否定词，不得补写原文中没有的事实。"
                    "不要把单一任务的修饰语拆开。上下文只能用于解析指代，"
                    "当前消息中的数值始终优先。"
                ),
            ),
            *(conversation or [])[-6:],
            ConversationMessage(role=ConversationRole.USER, content=text),
        ]
        try:
            generated = await self._provider.generate_structured(
                messages=messages,
                output_model=LlmTaskDecomposition,
                temperature=0,
                max_tokens=768,
            )
        except ProviderError:
            return [text]
        return generated.output.tasks

    async def route(
        self, text: str, *, conversation: list[Any] | None = None
    ) -> IntentResult:
        deterministic: IntentResult | None = None
        if self._rules.has_instruction_marker(text):
            return self._rules.route(text, conversation=conversation)
        if self._routing_mode == "hybrid":
            deterministic = self._rules.route(text, conversation=conversation)
            if deterministic.route != Route.SAFE_FALLBACK:
                return deterministic
        if self._provider is None or not self._provider.available:
            return self._unavailable_fallback(deterministic)
        supported = ", ".join(intent.value for intent in Intent if intent != Intent.UNKNOWN)
        today = self._today().isoformat()
        messages = [
            ConversationMessage(
                role=ConversationRole.SYSTEM,
                trust=TrustLabel.SYSTEM_POLICY,
                content=(
                    "你是银行助手的结构化意图与候选参数提取器。只输出一个 JSON 对象，"
                    "字段必须严格为："
                    '{"intent":"枚举值","confidence":0到1,"reply":null或字符串,'
                    '"proposed_slots":{"字段名":"候选值"},'
                    '"slot_evidence":{"字段名":"用户原文中的最短证据片段"}}。'
                    "不要输出分析、Markdown 或额外字段。不得声称金融操作成功，"
                    "不得生成身份、授权、验证码或风险等级。普通问候使用 GENERAL_CHAT；"
                    "普通问候的 reply 给出简短自然回复，银行任务的 reply 使用 null；"
                    "当前消息的优先级高于历史对话；当前消息已经构成完整子任务时，"
                    "不得从历史中复制金额、日期或收款人。复合请求中的金额必须就近绑定到"
                    "同一子任务，不得把转账金额用作预算上限。从用户当前消息和连续澄清"
                    "上下文中提取候选参数。金额使用两位小数字符串，"
                    "slot_evidence 只能逐字引用当前用户消息中的最短片段；"
                    "没有直接原文证据的候选值不得伪造证据，应省略该 evidence。"
                    "币种默认 CNY；相对日期可以根据今天换算，但只能作为 proposed_slots，"
                    "后端会要求用户确认后才执行。创建预算使用 CREATE_BUDGET，而不是"
                    "LIST_BUDGETS；month_date 始终使用 YYYY-MM-DD，用户只说月份时取该月 1 日，"
                    "用户说今天、明天、后天或具体日期时必须保留精确到日的日期。"
                    "对于预算或储蓄目标，可根据用户明确说明的用途提出简短、可读的自定义"
                    "category/name，例如‘给妈妈过生日’可提出‘妈妈生日’；这仍只是待确认候选。"
                    "不得猜测 UUID、账户、银行卡、联系人或理财产品标识；用户没有明确提供"
                    "这些标识时应省略对应 slot。"
                    f"今天是 {today}。"
                    f"支持的 intent: {supported}。"
                ),
            ),
            *(conversation or [])[-10:],
            ConversationMessage(role=ConversationRole.USER, content=text),
        ]
        try:
            generated = await self._provider.generate_structured(
                messages=messages,
                output_model=LlmIntentDecision,
                temperature=0,
                max_tokens=512,
            )
        except ProviderError as exc:
            logger.warning(
                "LLM intent fallback failed provider=%s code=%s request_id=%s",
                exc.provider,
                exc.code,
                exc.request_id,
            )
            return self._unavailable_fallback(deterministic)
        decision = generated.output
        if decision.confidence < self._confidence_threshold or decision.intent == Intent.UNKNOWN:
            return self._unavailable_fallback(deterministic)
        required_slots = list(REQUIRED_SLOTS_BY_INTENT.get(decision.intent, ()))
        proposed_slots = {
            name: value
            for name, value in decision.proposed_slots.items()
            if name in required_slots and value is not None and value != ""
        }
        proposed_evidence = {
            name: evidence
            for name, evidence in decision.slot_evidence.items()
            if name in proposed_slots and evidence and evidence in text
        }
        return IntentResult(
            intent=decision.intent,
            complexity=1 if decision.intent == Intent.GENERAL_CHAT else 3,
            confidence=decision.confidence,
            route=(Route.RULE_DIRECT if decision.intent == Intent.GENERAL_CHAT else Route.PLANNER),
            reason=f"llm:{generated.provider}/{generated.model}",
            required_slots=required_slots,
            proposed_slots=proposed_slots,
            proposed_evidence=proposed_evidence,
            reply=decision.reply,
        )

    def _unavailable_fallback(self, deterministic: IntentResult | None) -> IntentResult:
        if self._routing_mode == "hybrid" and deterministic is not None:
            return deterministic
        return IntentResult(
            intent=Intent.UNKNOWN,
            complexity=2,
            confidence=0,
            route=Route.SAFE_FALLBACK,
            reason="llm-only routing unavailable or below confidence threshold",
        )


class HybridPlanner:
    """Generate a candidate DAG with the LLM, then leave execution to PlanVerifier."""

    def __init__(self, baseline: BaselinePlanner, provider: ModelProvider | None) -> None:
        self._baseline = baseline
        self._provider = provider

    async def create(
        self,
        intent: IntentResult,
        slots: SlotState,
        *,
        system_idempotency_key: str | None = None,
        request: AgentRequest | None = None,
        allowed_tools: list[dict[str, object]] | None = None,
    ) -> TaskPlan:
        if not intent.reason.startswith("llm:") or self._provider is None or request is None:
            return self._baseline.create(
                intent,
                slots,
                system_idempotency_key=system_idempotency_key,
            )
        tool_json = json.dumps(allowed_tools or [], ensure_ascii=False, default=str)
        fact_json = json.dumps(
            {
                name: {"value": fact.value, "source": fact.source.value}
                for name, fact in slots.facts.items()
            },
            ensure_ascii=False,
        )
        messages = [
            ConversationMessage(
                role=ConversationRole.SYSTEM,
                trust=TrustLabel.SYSTEM_POLICY,
                content=(
                    "为银行请求生成严格 TaskPlan JSON。只能使用提供的工具；不得添加身份、"
                    "授权、MFA 或风险字段。每个参数都必须有 argument_sources。没有明确事实的"
                    "参数标记 MODEL_INFERRED，它会被安全验证器拒绝并触发澄清。工具："
                    f"{tool_json}\n可信槽位：{fact_json}"
                ),
            ),
            ConversationMessage(role=ConversationRole.USER, content=request.message),
        ]
        try:
            generated = await self._provider.generate_structured(
                messages=messages,
                output_model=TaskPlan,
                request_id=request.request_id,
                temperature=0,
                max_tokens=2_048,
            )
        except ProviderError as exc:
            logger.warning(
                "LLM plan fallback failed provider=%s code=%s request_id=%s",
                exc.provider,
                exc.code,
                exc.request_id,
            )
            return self._baseline.create(
                intent,
                slots,
                system_idempotency_key=system_idempotency_key,
            )
        return self._server_bind_sources(generated.output, slots, system_idempotency_key)

    @staticmethod
    def _server_bind_sources(
        plan: TaskPlan, slots: SlotState, system_idempotency_key: str | None
    ) -> TaskPlan:
        raw = plan.model_dump(mode="python")
        slot_aliases = {"month": "month_date"}
        for step in raw["steps"]:
            call = step.get("tool_call")
            if call is None:
                continue
            sources: dict[str, dict[str, str]] = {}
            for name, value in call["arguments"].items():
                slot_name = slot_aliases.get(name, name)
                fact = slots.facts.get(slot_name)
                if fact is None or str(value) != str(fact.value):
                    matches = [
                        candidate
                        for candidate in slots.facts.values()
                        if str(value) == str(candidate.value)
                    ]
                    fact = matches[0] if len(matches) == 1 else None
                if name == "idempotency_key" and system_idempotency_key:
                    call["arguments"][name] = system_idempotency_key
                    sources[name] = {
                        "kind": ArgumentSourceKind.SYSTEM_CONSTANT.value,
                        "reference": "trusted task id binding",
                    }
                elif fact is not None and str(value) == str(fact.value):
                    kind = {
                        FactSource.USER_EXPLICIT: ArgumentSourceKind.USER_EXPLICIT,
                        FactSource.TOOL_VERIFIED: ArgumentSourceKind.TOOL_VERIFIED,
                        FactSource.SYSTEM_CONSTANT: ArgumentSourceKind.SYSTEM_CONSTANT,
                        FactSource.MODEL_INFERRED: ArgumentSourceKind.MODEL_INFERRED,
                    }[fact.source]
                    sources[name] = {
                        "kind": kind.value,
                        "reference": f"slot:{fact.name}",
                    }
                else:
                    sources[name] = {
                        "kind": ArgumentSourceKind.MODEL_INFERRED.value,
                        "reference": "untrusted model output",
                    }
            step["argument_sources"] = sources
        return TaskPlan.model_validate(raw)
