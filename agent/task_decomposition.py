"""Hybrid Jev/LLM decomposition of a user turn into bounded banking tasks."""

from __future__ import annotations

import json
import logging
import re
from uuid import UUID

from agent.bundle_contracts import ProposedTask, TaskDecomposition
from agent.contracts import ConversationMessage, ConversationRole, TrustLabel
from agent.jev_http import JevAdapter, JevUnavailable
from agent.providers import ModelProvider, ProviderError
from agent.routing import CHAT_UNAVAILABLE_INTENTS, Intent, RuleRouter

logger = logging.getLogger(__name__)

_TRUSTED_FIELDS = {
    "user_id",
    "authenticated_user_id",
    "authorization_reference",
    "mfa_code",
    "risk_tier",
    "approved",
    "idempotency_key",
}
_COMPLEX_MARKERS = re.compile(
    r"(?:同时|并且|然后|另外|以及|还要|再给|and\s+then|also|as\s+well\s+as)", re.I
)
_INJECTION_MARKERS = re.compile(
    r"(?:忽略.{0,12}(?:指令|规则)|绕过.{0,12}(?:审批|验证)|"
    r"ignore.{0,20}(?:instruction|rule)|bypass.{0,20}(?:approval|verification))",
    re.I,
)


class TaskDecomposer:
    def __init__(
        self,
        provider: ModelProvider | None,
        *,
        jev_adapter: JevAdapter | None = None,
        jev_min_confidence: float = 0.8,
        max_injection: float = 0.03,
        min_in_scope: float = 0.97,
    ) -> None:
        self._provider = provider
        self._jev = jev_adapter
        self._jev_min_confidence = jev_min_confidence
        self._max_injection = max_injection
        self._min_in_scope = min_in_scope
        self._rules = RuleRouter()

    async def decompose(
        self,
        *,
        message: str,
        conversation: list[ConversationMessage],
        request_id: UUID,
    ) -> TaskDecomposition:
        observation = None
        if self._jev is not None and self._jev.available:
            try:
                observation = await self._jev.classify(message)
            except JevUnavailable:
                observation = None
        if (
            observation is not None
            and observation.injection_probability > self._max_injection
            and _INJECTION_MARKERS.search(message)
        ):
            return TaskDecomposition(
                tasks=[
                    ProposedTask(
                        item_key="unsafe_request",
                        intent=Intent.UNKNOWN,
                        evidence=message,
                    )
                ],
                needs_clarification=True,
                clarification_question="请求包含可能改变系统规则或绕过授权的内容，请重新表述。",
            )
        if (
            observation is not None
            and observation.confidence >= self._jev_min_confidence
            and observation.in_scope_probability >= self._min_in_scope
            and observation.order_consistent
            and observation.intent not in {
                Intent.UNKNOWN,
                Intent.GENERAL_CHAT,
                Intent.TRACK_EXPENSES,
                Intent.SUMMARIZE_EXPENSES,
                Intent.GET_BUDGET_STATUS,
            }
            and observation.intent not in CHAT_UNAVAILABLE_INTENTS
            and not _COMPLEX_MARKERS.search(message)
        ):
            return TaskDecomposition(
                tasks=[
                    ProposedTask(
                        item_key="task_1",
                        intent=observation.intent,
                        evidence=message,
                    )
                ]
            )
        provider = self._provider
        if provider is None or not provider.available:
            routed = self._rules.route(message)
            return TaskDecomposition(
                tasks=[
                    ProposedTask(
                        item_key="task_1",
                        intent=routed.intent,
                        evidence=message,
                    )
                ],
                needs_clarification=(
                    routed.intent == Intent.UNKNOWN or bool(_COMPLEX_MARKERS.search(message))
                ),
                clarification_question=(
                    "我暂时无法可靠拆分这些任务，请一次说明一个任务。"
                    if routed.intent == Intent.UNKNOWN or _COMPLEX_MARKERS.search(message)
                    else None
                ),
            )
        prompt = self._prompt(message, conversation)
        first = await self._generate(provider, prompt, request_id)
        error = self._validation_error(first, message)
        if error is None:
            return first
        repair_prompt = (
            prompt
            + "\nPrevious output: "
            + first.model_dump_json()
            + "\nValidation error: "
            + error
            + "\nRepair the output once."
        )
        repaired = await self._generate(provider, repair_prompt, request_id)
        repaired_error = self._validation_error(repaired, message)
        if repaired_error is not None:
            return TaskDecomposition(
                tasks=[ProposedTask(item_key="task_1", intent=Intent.UNKNOWN, evidence=message)],
                needs_clarification=True,
                clarification_question="我理解到多个可能的任务，但还不能可靠拆分。请确认要先处理哪一项。",
            )
        return repaired

    async def _generate(
        self, provider: ModelProvider, prompt: str, request_id: UUID
    ) -> TaskDecomposition:
        supported = ", ".join(intent.value for intent in Intent)
        messages = [
            ConversationMessage(
                role=ConversationRole.SYSTEM,
                trust=TrustLabel.SYSTEM_POLICY,
                content=(
                    "Split the current banking request into at most five independent tasks. "
                    "Use recent conversation only to resolve references. Every evidence value "
                    "must be an exact contiguous quote from current_message. Keep query and "
                    "write actions separate. Do not invent identifiers, authorization, MFA, "
                    "risk, approval, or successful outcomes. Return exactly one JSON object: "
                    '{"tasks":[{"item_key":"task_1","intent":"INTENT",'
                    '"evidence":"exact quote","proposed_slots":{},"depends_on":[]}],'
                    '"needs_clarification":false,"clarification_question":null}. '
                    "Create only actions the user asks for. A past meal or purchase mentioned "
                    "as the reason for settling money is context for TRANSFER, not a request to "
                    "RECORD_EXPENSE, unless the user explicitly asks to record or log it. AA or "
                    "equal-split settlement is TRANSFER; when who paid is unclear, keep TRANSFER "
                    "and ask who paid. Do not ask for an account number when a saved beneficiary "
                    "name or pronoun can be resolved downstream. Chinese 预留 or earmarking money "
                    "for a named future event is CREATE_SAVINGS_POT, not CREATE_BUDGET. A request "
                    "to list categorized spending is TRACK_EXPENSES; GET_TRANSACTIONS is only for "
                    "raw account ledger history. "
                    "For expense queries, put a requested count such as 最近三笔 into "
                    "proposed_slots.limit as an integer, and put the category into "
                    "proposed_slots.category using its uppercase category code. For budget "
                    "status queries, put the requested category code into proposed_slots.category. "
                    f"intent must be one of: {supported}."
                ),
            ),
            ConversationMessage(role=ConversationRole.USER, content=prompt),
        ]
        try:
            result = await provider.generate_structured(
                messages=messages,
                output_model=TaskDecomposition,
                request_id=request_id,
                temperature=0,
                max_tokens=1_024,
            )
            return result.output
        except ProviderError as exc:
            logger.warning(
                "task decomposition failed code=%s status=%s request_id=%s",
                exc.code,
                exc.status_code,
                request_id,
            )
            return TaskDecomposition(
                tasks=[ProposedTask(item_key="task_1", intent=Intent.UNKNOWN, evidence=prompt)],
                needs_clarification=True,
                clarification_question="模型暂时无法完成任务拆分，请一次说明一个任务。",
            )

    @staticmethod
    def _prompt(message: str, conversation: list[ConversationMessage]) -> str:
        history = [
            {"role": item.role.value, "content": item.content}
            for item in conversation[-20:]
            if item.role in {ConversationRole.USER, ConversationRole.ASSISTANT}
        ]
        return json.dumps(
            {"recent_conversation": history, "current_message": message}, ensure_ascii=False
        )

    @staticmethod
    def _validation_error(result: TaskDecomposition, message: str) -> str | None:
        for task in result.tasks:
            if task.evidence not in message:
                return f"evidence for {task.item_key} is not an exact current-message quote"
            if _TRUSTED_FIELDS.intersection(task.proposed_slots):
                return f"trusted fields are forbidden for {task.item_key}"
        return None
