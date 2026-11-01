"""Expense-labeling worker with a strict description eligibility policy."""

from __future__ import annotations

import re
from typing import Protocol

from agent.jev_http import JevCategoryObservation, JevUnavailable
from agent.privacy_broker import PrivacyBroker, TokenizedText


class ExpenseJevAdapter(Protocol):
    async def classify_category(self, text: str) -> JevCategoryObservation: ...


class ExpenseDescriptionPolicy:
    _BLOCKED = (
        "transfer",
        "beneficiary",
        "account",
        "card",
        "phone",
        "email",
        "@",
        "转账",
        "汇款",
        "收款人",
        "账号",
        "手机",
    )
    _SAFE_TEXT = re.compile(r"^[A-Za-z\u4e00-\u9fff][A-Za-z\u4e00-\u9fff &'.-]{1,63}$")

    def allows(self, tokenized: TokenizedText) -> bool:
        text = tokenized.text.strip()
        lowered = text.lower()
        if any(word in lowered for word in self._BLOCKED):
            return False
        if tokenized.replacements:
            return False
        if re.search(r"\d", text):
            return False
        return bool(self._SAFE_TEXT.fullmatch(text))


class ExpenseLabelingWorker:
    def __init__(
        self,
        *,
        adapter: ExpenseJevAdapter,
        privacy_broker: PrivacyBroker,
        min_confidence: float = 0.8,
        policy: ExpenseDescriptionPolicy | None = None,
    ) -> None:
        self._adapter = adapter
        self._privacy_broker = privacy_broker
        self._min_confidence = min_confidence
        self._policy = policy or ExpenseDescriptionPolicy()

    async def label(self, description: str) -> str | None:
        try:
            tokenized = self._privacy_broker.tokenize(description)
        except ValueError:
            return None
        if not self._policy.allows(tokenized):
            return None
        try:
            observation = await self._adapter.classify_category(tokenized.text)
        except JevUnavailable:
            return None
        if not observation.order_consistent or observation.confidence < self._min_confidence:
            return None
        return observation.category
