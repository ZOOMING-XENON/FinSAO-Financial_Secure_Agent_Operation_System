"""Conversation facts and slots with explicit provenance."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from agent.expense_capture import parse_expense
from agent.routing import Intent, IntentResult
from shared.expense_taxonomy import EXPENSE_CATEGORIES


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

    def from_confirmation(self, fields: dict[str, Any], intent: IntentResult) -> SlotState:
        """Bind already-confirmed form values without asking an LLM to reinterpret them."""
        optional_fields = {
            Intent.RECORD_EXPENSE: (
                "category",
                "occurred_at",
                "account_id",
                "origin",
            ),
            Intent.UPDATE_EXPENSE: (
                "amount",
                "currency",
                "merchant",
                "category",
                "occurred_at",
                "account_id",
            ),
        }.get(intent.intent, ())
        fields_to_bind = (*intent.required_slots, *optional_fields)
        facts = {
            name: SlotFact(name, fields[name], FactSource.USER_EXPLICIT)
            for name in fields_to_bind
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
            if currency:
                facts["currency"] = SlotFact("currency", currency, FactSource.USER_EXPLICIT)
            beneficiary = re.search(
                r"(?:给|向)\s*([A-Za-z\u4e00-\u9fff][A-Za-z0-9_\-\u4e00-\u9fff ]{0,39}?)"
                r"\s*(?:转账|汇款|转)",
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
        elif intent.intent == Intent.RECORD_EXPENSE:
            capture = parse_expense(text, now=datetime.now(ZoneInfo("Asia/Shanghai")))
            if capture.amount is not None:
                facts["amount"] = SlotFact("amount", capture.amount, FactSource.USER_EXPLICIT)
            if capture.currency is not None:
                facts["currency"] = SlotFact(
                    "currency", capture.currency, FactSource.USER_EXPLICIT
                )
            if capture.merchant is not None:
                facts["merchant"] = SlotFact(
                    "merchant", capture.merchant, FactSource.USER_EXPLICIT
                )
            if capture.category is not None:
                facts["category"] = SlotFact(
                    "category", capture.category, FactSource.USER_EXPLICIT
                )
            facts["occurred_at"] = SlotFact(
                "occurred_at", capture.occurred_at.isoformat(), FactSource.USER_EXPLICIT
            )
            facts["origin"] = SlotFact("origin", capture.origin, FactSource.SYSTEM_CONSTANT)
            if capture.ambiguous:
                facts["expense_ambiguity"] = SlotFact(
                    "expense_ambiguity", "true", FactSource.SYSTEM_CONSTANT
                )
            if ids:
                facts["account_id"] = SlotFact(
                    "account_id", str(UUID(ids[0])), FactSource.USER_EXPLICIT
                )
        elif intent.intent in {Intent.UPDATE_EXPENSE, Intent.DELETE_EXPENSE}:
            if ids:
                facts["expense_id"] = SlotFact(
                    "expense_id", str(UUID(ids[0])), FactSource.USER_EXPLICIT
                )
            reference = re.search(
                r"(?:delete|remove|change|update|edit|modify)\s+"
                r"(?:the\s+|this\s+|that\s+)?(.+?)\s*"
                r"(?:expense|transaction)",
                text,
                re.IGNORECASE,
            )
            if reference is not None:
                facts["expense_ref"] = SlotFact(
                    "expense_ref", reference.group(1).strip(), FactSource.USER_EXPLICIT
                )
            if intent.intent == Intent.UPDATE_EXPENSE:
                if amount:
                    facts["amount"] = SlotFact("amount", amount, FactSource.USER_EXPLICIT)
                for category_name in EXPENSE_CATEGORIES:
                    if re.search(rf"\b{category_name}\b", text, re.IGNORECASE):
                        facts["category"] = SlotFact(
                            "category", category_name, FactSource.USER_EXPLICIT
                        )
                        break
        elif intent.intent in {Intent.TRACK_EXPENSES, Intent.SUMMARIZE_EXPENSES}:
            lowered = text.lower()
            now = datetime.now(ZoneInfo("Asia/Shanghai"))
            start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            end = (
                start.replace(year=start.year + 1, month=1)
                if start.month == 12
                else start.replace(month=start.month + 1)
            )
            if any(word in lowered for word in ("last month", "上个月", "上月")):
                end = start
                start = (
                    start.replace(year=start.year - 1, month=12)
                    if start.month == 1
                    else start.replace(month=start.month - 1)
                )
            elif any(word in lowered for word in ("last 7 days", "最近7天", "近7天")):
                end = now + timedelta(days=1)
                start = now - timedelta(days=6)
            elif any(word in lowered for word in ("yesterday", "昨天")):
                end = now.replace(hour=0, minute=0, second=0, microsecond=0)
                start = end - timedelta(days=1)
            elif any(word in lowered for word in ("today", "今天")):
                start = now.replace(hour=0, minute=0, second=0, microsecond=0)
                end = start + timedelta(days=1)
            if ids:
                facts["account_id"] = SlotFact(
                    "account_id", str(UUID(ids[0])), FactSource.USER_EXPLICIT
                )
            facts["start"] = SlotFact("start", start.isoformat(), FactSource.SYSTEM_CONSTANT)
            facts["end"] = SlotFact("end", end.isoformat(), FactSource.SYSTEM_CONSTANT)
            categories = {
                "dining": "DINING",
                "restaurant": "DINING",
                "餐饮": "DINING",
                "grocer": "GROCERIES",
                "supermarket": "GROCERIES",
                "超市": "GROCERIES",
                "transport": "TRANSPORT",
                "taxi": "TRANSPORT",
                "交通": "TRANSPORT",
                "household": "HOUSEHOLD",
                "家庭": "HOUSEHOLD",
                "entertainment": "ENTERTAINMENT",
                "娱乐": "ENTERTAINMENT",
                "health": "HEALTHCARE",
                "医疗": "HEALTHCARE",
                "education": "EDUCATION",
                "教育": "EDUCATION",
                "travel": "TRAVEL",
                "旅行": "TRAVEL",
                "shopping": "SHOPPING",
                "购物": "SHOPPING",
                "utilities": "UTILITIES",
                "水电": "UTILITIES",
                "fees": "FEES",
                "费用": "FEES",
            }
            for word, cat_value in categories.items():
                if word in lowered:
                    facts["category"] = SlotFact(
                        "category", cat_value, FactSource.USER_EXPLICIT
                    )
                    break
            sort_by, sort_direction = "posted_at", "desc"
            if any(word in lowered for word in ("largest", "biggest", "最大", "金额最大")):
                sort_by, sort_direction = "amount", "desc"
            elif any(word in lowered for word in ("smallest", "最小", "金额最小")):
                sort_by, sort_direction = "amount", "asc"
            elif any(word in lowered for word in ("oldest", "最早")):
                sort_by, sort_direction = "posted_at", "asc"
            elif any(word in lowered for word in ("by merchant", "按商家")):
                sort_by, sort_direction = "merchant", "asc"
            elif any(word in lowered for word in ("by category", "按类别")):
                sort_by, sort_direction = "category", "asc"
            if any(word in lowered for word in ("ascending", "升序")):
                sort_direction = "asc"
            elif any(word in lowered for word in ("descending", "降序")):
                sort_direction = "desc"
            facts["sort_by"] = SlotFact("sort_by", sort_by, FactSource.SYSTEM_CONSTANT)
            facts["sort_direction"] = SlotFact(
                "sort_direction", sort_direction, FactSource.SYSTEM_CONSTANT
            )
            limit_match = re.search(r"(?:top|前)\s*(\d+)", lowered)
            if limit_match is None:
                limit_match = re.search(r"(\d+)\s*(?:largest|smallest|expenses)", lowered)
            if limit_match is not None:
                facts["limit"] = SlotFact(
                    "limit", int(limit_match.group(1)), FactSource.USER_EXPLICIT
                )
            range_match = re.search(
                r"(?:between|从)\s*(\d+(?:\.\d{1,2})?)\s*(?:and|到)\s*(\d+(?:\.\d{1,2})?)",
                lowered,
            )
            if range_match is not None:
                facts["minimum_amount"] = SlotFact(
                    "minimum_amount", range_match.group(1), FactSource.USER_EXPLICIT
                )
                facts["maximum_amount"] = SlotFact(
                    "maximum_amount", range_match.group(2), FactSource.USER_EXPLICIT
                )
            elif any(word in lowered for word in ("over", "above", "大于")):
                over = re.search(r"(?:over|above|大于)\s*(\d+(?:\.\d{1,2})?)", lowered)
                if over is not None:
                    facts["minimum_amount"] = SlotFact(
                        "minimum_amount", over.group(1), FactSource.USER_EXPLICIT
                    )
            elif any(word in lowered for word in ("under", "below", "小于")):
                under = re.search(r"(?:under|below|小于)\s*(\d+(?:\.\d{1,2})?)", lowered)
                if under is not None:
                    facts["maximum_amount"] = SlotFact(
                        "maximum_amount", under.group(1), FactSource.USER_EXPLICIT
                    )
        elif intent.intent == Intent.ANALYZE_SPENDING:
            match = re.search(r"(20\d{2})[-年/](\d{1,2})", text)
            today = date.today()
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
            category: str | None = next(
                (
                    value
                    for word, value in {
                        "家居": "HOUSEHOLD",
                        "日用": "GROCERIES",
                        "交通": "TRANSPORT",
                        "娱乐": "ENTERTAINMENT",
                        "餐饮": "DINING",
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
            month_match = re.search(r"(20\d{2})[-年/](\d{1,2})", text)
            if category:
                facts["category"] = SlotFact("category", category, FactSource.USER_EXPLICIT)
            if month_match:
                month_value = f"{int(month_match.group(1)):04d}-{int(month_match.group(2)):02d}-01"
                facts["month_date"] = SlotFact("month_date", month_value, FactSource.USER_EXPLICIT)
            if amount:
                facts["limit_amount"] = SlotFact("limit_amount", amount, FactSource.USER_EXPLICIT)
            if re.search(r"元|块|rmb|cny", text, re.IGNORECASE):
                facts["currency"] = SlotFact("currency", "CNY", FactSource.USER_EXPLICIT)
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
            if intent.intent == Intent.TRANSFER and name in {
                "amount", "currency", "source_account_id", "destination_account_id"
            }:
                continue
            if (
                name in intent.required_slots
                and name not in facts
                and value is not None
                and value != ""
            ):
                facts[name] = SlotFact(name, value, FactSource.MODEL_INFERRED)
        if intent.intent == Intent.TRANSFER:
            proposed_amount = intent.proposed_slots.get("amount")
            if (
                "amount" not in facts
                and proposed_amount is not None
                and not isinstance(proposed_amount, bool)
            ):
                try:
                    candidate = Decimal(str(proposed_amount))
                    if (
                        candidate.is_finite()
                        and 0 < candidate <= Decimal("1000000000")
                        and candidate == candidate.quantize(Decimal("0.01"))
                    ):
                        facts["amount"] = SlotFact(
                            "amount", format(candidate, ".2f"), FactSource.MODEL_INFERRED
                        )
                except InvalidOperation:
                    pass
            recipient = intent.proposed_slots.get("recipient")
            if recipient is None:
                recipient = intent.proposed_slots.get("beneficiary_query")
            if (
                "beneficiary_query" not in facts
                and isinstance(recipient, str)
                and 0 < len(recipient.strip()) <= 80
            ):
                facts["beneficiary_query"] = SlotFact(
                    "beneficiary_query", recipient.strip(), FactSource.MODEL_INFERRED
                )
            if "currency" not in facts:
                proposed_currency = intent.proposed_slots.get("currency")
                if isinstance(proposed_currency, str) and proposed_currency.upper() in {
                    "CNY", "USD", "EUR"
                }:
                    facts["currency"] = SlotFact(
                        "currency", proposed_currency.upper(), FactSource.MODEL_INFERRED
                    )
                else:
                    facts["currency"] = SlotFact(
                        "currency", "CNY", FactSource.SYSTEM_CONSTANT
                    )
        if intent.intent in {Intent.TRACK_EXPENSES, Intent.SUMMARIZE_EXPENSES}:
            proposed_limit = intent.proposed_slots.get("limit")
            if "limit" not in facts and not isinstance(proposed_limit, bool):
                try:
                    limit = int(proposed_limit)  # type: ignore[arg-type]
                except (TypeError, ValueError):
                    limit = 0
                if 1 <= limit <= 200 and str(proposed_limit) == str(limit):
                    facts["limit"] = SlotFact("limit", limit, FactSource.MODEL_INFERRED)
            proposed_category = intent.proposed_slots.get("category")
            if "category" not in facts and isinstance(proposed_category, str):
                category = proposed_category.upper()
                if category in EXPENSE_CATEGORIES:
                    facts["category"] = SlotFact(
                        "category", category, FactSource.MODEL_INFERRED
                    )
        missing = [slot for slot in intent.required_slots if slot not in facts]
        return SlotState(facts=facts, missing=missing)
