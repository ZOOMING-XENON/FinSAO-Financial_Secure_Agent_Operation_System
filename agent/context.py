"""Conversation facts and slots with explicit provenance."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Any
from uuid import UUID

from agent.routing import Intent, IntentResult


class FactSource(StrEnum):
    USER_EXPLICIT = "USER_EXPLICIT"
    TOOL_VERIFIED = "TOOL_VERIFIED"
    SYSTEM_CONSTANT = "SYSTEM_CONSTANT"
    MODEL_INFERRED = "MODEL_INFERRED"


@dataclass(frozen=True, slots=True)
class SlotFact:
    name: str
    value: Any
    source: FactSource


@dataclass(slots=True)
class SlotState:
    facts: dict[str, SlotFact] = field(default_factory=dict)
    missing: list[str] = field(default_factory=list)


class SlotTracker:
    _AMOUNT = re.compile(r"(?<![\d.])(\d+(?:\.\d{1,2})?)\s*(?:元|块|rmb|cny)", re.IGNORECASE)
    _UUID = re.compile(
        r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-"
        r"[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}\b"
    )

    def __init__(self, today: Callable[[], date] = date.today) -> None:
        self._today = today

    @staticmethod
    def _amount_value(match: re.Match[str] | None) -> str | None:
        if match is None:
            return None
        try:
            parsed = Decimal(match.group(1)).quantize(Decimal("0.01"))
        except InvalidOperation:
            return None
        return format(parsed, "f") if parsed > 0 else None

    def _budget_date(self, text: str) -> str | None:
        exact = re.search(
            r"(20\d{2})[-./年](\d{1,2})[-./月](\d{1,2})(?:日)?",
            text,
        )
        if exact:
            try:
                return date(*(int(exact.group(i)) for i in range(1, 4))).isoformat()
            except ValueError:
                return None
        relative_days = {"今天": 0, "明天": 1, "后天": 2}
        for phrase, days in relative_days.items():
            if phrase in text:
                return (self._today() + timedelta(days=days)).isoformat()
        days_later = re.search(r"(?<!\d)(\d{1,3})\s*天后", text)
        if days_later:
            return (self._today() + timedelta(days=int(days_later.group(1)))).isoformat()
        month = re.search(r"(20\d{2})[-年/](\d{1,2})(?:月)?", text)
        if month:
            try:
                return date(int(month.group(1)), int(month.group(2)), 1).isoformat()
            except ValueError:
                return None
        return None

    def from_confirmation(self, fields: dict[str, Any], intent: IntentResult) -> SlotState:
        """Bind already-confirmed form values without asking an LLM to reinterpret them."""
        facts = {
            name: SlotFact(name, fields[name], FactSource.USER_EXPLICIT)
            for name in intent.required_slots
            if name in fields and fields[name] not in (None, "", [])
        }
        if intent.intent == Intent.TRANSFER and fields.get("include_balance") not in (
            None,
            "",
            [],
        ):
            facts["include_balance"] = SlotFact(
                "include_balance", fields["include_balance"], FactSource.USER_EXPLICIT
            )
        missing = [name for name in intent.required_slots if name not in facts]
        return SlotState(facts=facts, missing=missing)

    def from_llm_evidence(self, text: str, intent: IntentResult) -> SlotState:
        """Bind LLM candidates, trusting only values supported by quoted user text.

        The model performs semantic extraction. This method is deliberately limited to
        provenance validation and does not classify the user's business intent.
        """
        facts: dict[str, SlotFact] = {}
        for name, value in intent.proposed_slots.items():
            if name not in intent.required_slots or value in (None, "", []):
                continue
            evidence = intent.proposed_evidence.get(name)
            source = (
                FactSource.USER_EXPLICIT
                if evidence is not None
                and evidence in text
                and self._evidence_supports(name, value, evidence)
                else FactSource.MODEL_INFERRED
            )
            facts[name] = SlotFact(name, value, source)
        missing = [name for name in intent.required_slots if name not in facts]
        return SlotState(facts=facts, missing=missing)

    def _evidence_supports(self, name: str, value: Any, evidence: str) -> bool:
        numeric_slots = {
            "amount",
            "limit_amount",
            "spending_limit",
            "target_amount",
            "year",
            "month",
        }
        if name in numeric_slots:
            match = re.search(r"(?<!\d)(\d+(?:\.\d{1,2})?)(?!\d)", evidence)
            if match is None:
                return False
            try:
                return Decimal(match.group(1)) == Decimal(str(value))
            except InvalidOperation:
                return False
        if name in {"month_date", "target_date"}:
            return self._budget_date(evidence) == str(value)
        if name == "currency":
            normalized = evidence.strip().lower()
            currency_markers = {
                "CNY": {"元", "块", "rmb", "cny", "人民币"},
                "USD": {"usd", "美元", "美刀"},
                "EUR": {"eur", "欧元"},
            }
            return any(
                marker in normalized
                for marker in currency_markers.get(str(value).upper(), set())
            )
        if isinstance(value, list):
            return all(str(item) in evidence for item in value)
        return str(value).strip().casefold() == evidence.strip().casefold()

    def extract(self, text: str, intent: IntentResult) -> SlotState:
        facts: dict[str, SlotFact] = {}
        ids = self._UUID.findall(text)
        amount_match = self._AMOUNT.search(text)
        amount: str | None = None
        if amount_match:
            try:
                parsed = Decimal(amount_match.group(1)).quantize(Decimal("0.01"))
                if parsed > 0:
                    amount = format(parsed, "f")
            except InvalidOperation:
                pass
        if intent.intent == Intent.TRANSFER:
            if amount is None:
                transfer_amount = re.search(
                    r"(?:转账|汇款|转)\s*(\d+(?:\.\d{1,2})?)",
                    text,
                    re.IGNORECASE,
                )
                if transfer_amount:
                    try:
                        parsed = Decimal(transfer_amount.group(1)).quantize(Decimal("0.01"))
                        if parsed > 0:
                            amount = format(parsed, "f")
                    except InvalidOperation:
                        pass
            if "余额" in text:
                facts["include_balance"] = SlotFact(
                    "include_balance", "true", FactSource.USER_EXPLICIT
                )
            if ids:
                facts["source_account_id"] = SlotFact(
                    "source_account_id", str(UUID(ids[0])), FactSource.USER_EXPLICIT
                )
            if len(ids) > 1:
                facts["destination_account_id"] = SlotFact(
                    "destination_account_id", str(UUID(ids[1])), FactSource.USER_EXPLICIT
                )
            if amount:
                facts["amount"] = SlotFact("amount", amount, FactSource.USER_EXPLICIT)
            currency = "CNY" if re.search(r"元|块|rmb|cny", text, re.IGNORECASE) else None
            if currency is None and amount is not None and re.search(r"转账|汇款", text):
                currency = "CNY"
            if currency:
                facts["currency"] = SlotFact("currency", currency, FactSource.USER_EXPLICIT)
            beneficiary = re.search(
                r"(?:给|向)\s*([A-Za-z\u4e00-\u9fff][A-Za-z0-9_\-\u4e00-\u9fff ]{0,39}?)"
                r"\s*(?:转账|汇款|转)",
                text,
                re.IGNORECASE,
            )
            if beneficiary is None:
                beneficiary = re.search(
                    r"(?:转账|汇款|转)\s*\d+(?:\.\d{1,2})?\s*"
                    r"(?:元|块|rmb|cny)?\s*(?:给|向)\s*"
                    r"([A-Za-z\u4e00-\u9fff][A-Za-z0-9_\-\u4e00-\u9fff ]{0,39})",
                    text,
                    re.IGNORECASE,
                )
            if beneficiary:
                facts["beneficiary_query"] = SlotFact(
                    "beneficiary_query",
                    beneficiary.group(1).strip(),
                    FactSource.USER_EXPLICIT,
                )
        elif intent.intent in {Intent.GET_BALANCE, Intent.GET_TRANSACTIONS} and ids:
            facts["account_id"] = SlotFact(
                "account_id", str(UUID(ids[0])), FactSource.USER_EXPLICIT
            )
        elif intent.intent == Intent.ANALYZE_SPENDING:
            match = re.search(r"(20\d{2})[-年/](\d{1,2})", text)
            today = self._today()
            year, month = (
                (int(match.group(1)), int(match.group(2))) if match else (today.year, today.month)
            )
            source = FactSource.USER_EXPLICIT if match else FactSource.SYSTEM_CONSTANT
            facts["year"] = SlotFact("year", str(year), source)
            facts["month"] = SlotFact("month", str(month), source)
        elif (
            intent.intent
            in {
                Intent.GET_BUDGET_STATUS,
                Intent.CANCEL_SUBSCRIPTION,
                Intent.GET_CARD,
                Intent.FREEZE_CARD,
                Intent.UNFREEZE_CARD,
                Intent.REPORT_CARD_LOST,
            }
            and ids
        ):
            facts["resource_id"] = SlotFact(
                "resource_id", str(UUID(ids[0])), FactSource.USER_EXPLICIT
            )
        elif intent.intent == Intent.UPDATE_CARD_LIMIT:
            if ids:
                facts["card_id"] = SlotFact("card_id", str(UUID(ids[0])), FactSource.USER_EXPLICIT)
            if amount:
                facts["spending_limit"] = SlotFact(
                    "spending_limit", amount, FactSource.USER_EXPLICIT
                )
        elif intent.intent == Intent.UPDATE_BUDGET:
            if ids:
                facts["budget_id"] = SlotFact(
                    "budget_id", str(UUID(ids[0])), FactSource.USER_EXPLICIT
                )
            if amount:
                facts["limit_amount"] = SlotFact("limit_amount", amount, FactSource.USER_EXPLICIT)
        elif intent.intent == Intent.CREATE_BUDGET:
            category = next(
                (
                    value
                    for word, value in {
                        "家居": "HOUSEHOLD",
                        "日用": "GROCERIES",
                        "交通": "TRANSPORT",
                        "娱乐": "ENTERTAINMENT",
                        "餐饮": "DINING",
                        "早餐": "DINING",
                        "午餐": "DINING",
                        "晚餐": "DINING",
                    }.items()
                    if word in text
                ),
                None,
            )
            custom_category = re.search(
                r"(?:类别|分类|category)\s*(?:是|为|[:：=])?\s*([^，,;\n]+)",
                text,
                re.IGNORECASE,
            )
            if category is None and custom_category:
                category = custom_category.group(1).strip()
            budget_amount = self._amount_value(
                re.search(
                    r"(?:预留|预算(?:上限|限额)?(?:为|是|[:：=])?)\s*"
                    r"(\d+(?:\.\d{1,2})?)",
                    text,
                )
            )
            if budget_amount is None:
                budget_amount = self._amount_value(
                    re.search(r"(\d+(?:\.\d{1,2})?)\s*(?:元|块)?(?:的)?预算", text)
                )
            budget_date = self._budget_date(text)
            if category:
                facts["category"] = SlotFact("category", category, FactSource.USER_EXPLICIT)
            if budget_date:
                facts["month_date"] = SlotFact(
                    "month_date", budget_date, FactSource.USER_EXPLICIT
                )
            if budget_amount or amount:
                facts["limit_amount"] = SlotFact(
                    "limit_amount", budget_amount or amount, FactSource.USER_EXPLICIT
                )
            if re.search(r"元|块|rmb|cny", text, re.IGNORECASE):
                facts["currency"] = SlotFact("currency", "CNY", FactSource.USER_EXPLICIT)
            elif budget_amount:
                facts["currency"] = SlotFact("currency", "CNY", FactSource.SYSTEM_CONSTANT)
        elif intent.intent == Intent.CREATE_SAVINGS_POT:
            name_match = re.search(
                r"(?:创建|新增|设置)(?:一个)?(.{1,30}?)(?:储蓄罐|储藏罐|储蓄目标)", text
            )
            date_match = re.search(r"(20\d{2})[-./年](\d{1,2})[-./月](\d{1,2})(?:日)?", text)
            if name_match:
                facts["name"] = SlotFact(
                    "name", name_match.group(1).strip(), FactSource.USER_EXPLICIT
                )
            else:
                event_match = re.search(
                    r"(?:我)?(妈妈|母亲|爸爸|父亲|奶奶|爷爷|外婆|外公|孩子|女儿|儿子)"
                    r"(?:要|将要|快要)?(?:过)?生日",
                    text,
                )
                if event_match:
                    facts["name"] = SlotFact(
                        "name",
                        f"{event_match.group(1)}生日",
                        FactSource.MODEL_INFERRED,
                    )
            if amount:
                facts["target_amount"] = SlotFact("target_amount", amount, FactSource.USER_EXPLICIT)
            if date_match:
                facts["target_date"] = SlotFact(
                    "target_date",
                    f"{int(date_match.group(1)):04d}-{int(date_match.group(2)):02d}-"
                    f"{int(date_match.group(3)):02d}",
                    FactSource.USER_EXPLICIT,
                )
            if re.search(r"元|块|rmb|cny", text, re.IGNORECASE):
                facts["currency"] = SlotFact("currency", "CNY", FactSource.USER_EXPLICIT)
        elif intent.intent == Intent.CONTRIBUTE_SAVINGS_POT:
            if ids:
                facts["pot_id"] = SlotFact("pot_id", str(UUID(ids[0])), FactSource.USER_EXPLICIT)
            if amount:
                facts["amount"] = SlotFact("amount", amount, FactSource.USER_EXPLICIT)
        elif intent.intent == Intent.COMPARE_WEALTH_PRODUCTS and len(ids) >= 2:
            facts["product_ids"] = SlotFact(
                "product_ids", [str(UUID(value)) for value in ids], FactSource.USER_EXPLICIT
            )
        elif intent.intent == Intent.ASSESS_RISK_PROFILE:
            answers = [int(value) for value in re.findall(r"(?<!\d)([1-5])(?!\d)", text)]
            if len(answers) == 5:
                facts["answers"] = SlotFact("answers", answers, FactSource.USER_EXPLICIT)
        elif intent.intent in {Intent.SUBSCRIBE_WEALTH, Intent.REDEEM_WEALTH}:
            if ids:
                facts["account_id"] = SlotFact(
                    "account_id", str(UUID(ids[0])), FactSource.USER_EXPLICIT
                )
            if len(ids) > 1:
                facts["product_id"] = SlotFact(
                    "product_id", str(UUID(ids[1])), FactSource.USER_EXPLICIT
                )
            if amount:
                facts["amount"] = SlotFact("amount", amount, FactSource.USER_EXPLICIT)
        for name, value in intent.proposed_slots.items():
            if (
                name in intent.required_slots
                and name not in facts
                and value is not None
                and value != ""
            ):
                facts[name] = SlotFact(name, value, FactSource.MODEL_INFERRED)
        missing = [slot for slot in intent.required_slots if slot not in facts]
        return SlotState(facts=facts, missing=missing)
