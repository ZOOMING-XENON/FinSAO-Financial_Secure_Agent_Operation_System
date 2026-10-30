"""Deterministic intent contracts and a conservative rule-first router."""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, JsonValue


class Intent(StrEnum):
    LIST_ACCOUNTS = "LIST_ACCOUNTS"
    GET_BALANCE = "GET_BALANCE"
    GET_TRANSACTIONS = "GET_TRANSACTIONS"
    TRANSFER = "TRANSFER"
    ANALYZE_SPENDING = "ANALYZE_SPENDING"
    LIST_BUDGETS = "LIST_BUDGETS"
    GET_BUDGET_STATUS = "GET_BUDGET_STATUS"
    CREATE_BUDGET = "CREATE_BUDGET"
    UPDATE_BUDGET = "UPDATE_BUDGET"
    LIST_SUBSCRIPTIONS = "LIST_SUBSCRIPTIONS"
    DETECT_RECURRING = "DETECT_RECURRING"
    CANCEL_SUBSCRIPTION = "CANCEL_SUBSCRIPTION"
    LIST_CARDS = "LIST_CARDS"
    GET_CARD = "GET_CARD"
    UPDATE_CARD_LIMIT = "UPDATE_CARD_LIMIT"
    FREEZE_CARD = "FREEZE_CARD"
    UNFREEZE_CARD = "UNFREEZE_CARD"
    REPORT_CARD_LOST = "REPORT_CARD_LOST"
    LIST_WEALTH_PRODUCTS = "LIST_WEALTH_PRODUCTS"
    COMPARE_WEALTH_PRODUCTS = "COMPARE_WEALTH_PRODUCTS"
    GET_WEALTH_RECOMMENDATIONS = "GET_WEALTH_RECOMMENDATIONS"
    ASSESS_RISK_PROFILE = "ASSESS_RISK_PROFILE"
    GET_HOLDINGS = "GET_HOLDINGS"
    SUBSCRIBE_WEALTH = "SUBSCRIBE_WEALTH"
    REDEEM_WEALTH = "REDEEM_WEALTH"
    LIST_SAVINGS_POTS = "LIST_SAVINGS_POTS"
    CREATE_SAVINGS_POT = "CREATE_SAVINGS_POT"
    CONTRIBUTE_SAVINGS_POT = "CONTRIBUTE_SAVINGS_POT"
    GENERAL_CHAT = "GENERAL_CHAT"
    UNKNOWN = "UNKNOWN"


REQUIRED_SLOTS_BY_INTENT: dict[Intent, tuple[str, ...]] = {
    Intent.GET_BALANCE: ("account_id",),
    Intent.GET_TRANSACTIONS: ("account_id",),
    Intent.TRANSFER: ("source_account_id", "destination_account_id", "amount", "currency"),
    Intent.ANALYZE_SPENDING: ("year", "month"),
    Intent.GET_BUDGET_STATUS: ("resource_id",),
    Intent.CREATE_BUDGET: ("category", "month_date", "limit_amount", "currency"),
    Intent.UPDATE_BUDGET: ("budget_id", "limit_amount"),
    Intent.CANCEL_SUBSCRIPTION: ("resource_id",),
    Intent.GET_CARD: ("resource_id",),
    Intent.UPDATE_CARD_LIMIT: ("card_id", "spending_limit"),
    Intent.FREEZE_CARD: ("resource_id",),
    Intent.UNFREEZE_CARD: ("resource_id",),
    Intent.REPORT_CARD_LOST: ("resource_id",),
    Intent.COMPARE_WEALTH_PRODUCTS: ("product_ids",),
    Intent.ASSESS_RISK_PROFILE: ("answers",),
    Intent.SUBSCRIBE_WEALTH: ("account_id", "product_id", "amount"),
    Intent.REDEEM_WEALTH: ("account_id", "product_id", "amount"),
    Intent.CREATE_SAVINGS_POT: ("name", "target_amount", "target_date", "currency"),
    Intent.CONTRIBUTE_SAVINGS_POT: ("pot_id", "amount"),
}


class Route(StrEnum):
    RULE_DIRECT = "RULE_DIRECT"
    PLANNER = "PLANNER"
    SAFE_FALLBACK = "SAFE_FALLBACK"


class IntentResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    intent: Intent
    complexity: int = Field(ge=1, le=5)
    confidence: float = Field(ge=0, le=1)
    route: Route
    reason: str
    required_slots: list[str] = Field(default_factory=list)
    proposed_slots: dict[str, JsonValue] = Field(default_factory=dict)
    proposed_evidence: dict[str, str] = Field(default_factory=dict)
    reply: str | None = None


class RuleRouter:
    """Fast-path exact and high-confidence rules; everything else fails closed."""

    _INJECTION_MARKERS = (
        "忽略规则",
        "忽略之前",
        "system prompt",
        "隐藏工具",
        "绕过审批",
        "伪造授权",
    )

    @classmethod
    def has_instruction_marker(cls, text: str) -> bool:
        """Fast safety screening only; this does not classify business intent."""
        normalized = re.sub(r"\s+", "", text).lower()
        return any(marker in normalized for marker in cls._INJECTION_MARKERS)

    @staticmethod
    def _result(
        intent: Intent,
        *,
        route: Route = Route.RULE_DIRECT,
        complexity: int = 1,
        confidence: float = 0.98,
        reason: str = "deterministic supported intent",
        required_slots: list[str] | None = None,
    ) -> IntentResult:
        return IntentResult(
            intent=intent,
            complexity=complexity,
            confidence=confidence,
            route=route,
            reason=reason,
            required_slots=required_slots or [],
        )

    def route(
        self, text: str, *, conversation: list[Any] | None = None
    ) -> IntentResult:
        del conversation
        normalized = re.sub(r"\s+", "", text).lower()
        if self.has_instruction_marker(text):
            return self._result(
                Intent.UNKNOWN,
                route=Route.SAFE_FALLBACK,
                complexity=5,
                confidence=1.0,
                reason="untrusted instruction marker requires safe fallback",
            )
        if any(word in normalized for word in ("转账", "转给", "汇款")) or re.search(
            r"转\d", normalized
        ):
            return self._result(
                Intent.TRANSFER,
                route=Route.PLANNER,
                complexity=3,
                confidence=0.9,
                reason="write operation requires verified planning",
                required_slots=[
                    "source_account_id",
                    "destination_account_id",
                    "amount",
                    "currency",
                ],
            )
        if normalized in {"查看我的账户", "我的账户", "账户列表", "查看账户"}:
            return self._result(Intent.LIST_ACCOUNTS, confidence=1.0)
        if "余额" in normalized:
            return self._result(
                Intent.GET_BALANCE,
                route=Route.RULE_DIRECT,
                confidence=0.98,
                reason="deterministic supported intent",
                required_slots=["account_id"],
            )
        if any(word in normalized for word in ("流水", "交易记录", "明细")):
            return self._result(Intent.GET_TRANSACTIONS, required_slots=["account_id"])
        if any(word in normalized for word in ("消费", "支出", "花费")):
            return self._result(Intent.ANALYZE_SPENDING, required_slots=["year", "month"])
        if "预算" in normalized:
            if any(word in normalized for word in ("创建", "新增", "设置", "预留")):
                return self._result(
                    Intent.CREATE_BUDGET,
                    route=Route.PLANNER,
                    complexity=2,
                    required_slots=["category", "month_date", "limit_amount", "currency"],
                )
            if any(word in normalized for word in ("修改", "更新", "调整")):
                return self._result(
                    Intent.UPDATE_BUDGET,
                    route=Route.PLANNER,
                    complexity=2,
                    required_slots=["budget_id", "limit_amount"],
                )
            if any(word in normalized for word in ("状态", "使用", "剩余")):
                return self._result(Intent.GET_BUDGET_STATUS, required_slots=["resource_id"])
            return self._result(Intent.LIST_BUDGETS)
        if any(word in normalized for word in ("订阅", "自动续费", "周期扣款")):
            if any(word in normalized for word in ("取消", "关闭")):
                return self._result(
                    Intent.CANCEL_SUBSCRIPTION,
                    route=Route.PLANNER,
                    complexity=2,
                    required_slots=["resource_id"],
                )
            if any(word in normalized for word in ("检测", "识别")):
                return self._result(Intent.DETECT_RECURRING)
            return self._result(Intent.LIST_SUBSCRIPTIONS)
        if any(word in normalized for word in ("银行卡", "卡片", "信用卡")):
            if "解冻" in normalized:
                return self._result(
                    Intent.UNFREEZE_CARD, route=Route.PLANNER, required_slots=["resource_id"]
                )
            if "冻结" in normalized:
                return self._result(
                    Intent.FREEZE_CARD, route=Route.PLANNER, required_slots=["resource_id"]
                )
            if "挂失" in normalized:
                return self._result(
                    Intent.REPORT_CARD_LOST,
                    route=Route.PLANNER,
                    complexity=3,
                    required_slots=["resource_id"],
                )
            if any(word in normalized for word in ("限额", "额度")) and any(
                word in normalized for word in ("修改", "设置", "调整")
            ):
                return self._result(
                    Intent.UPDATE_CARD_LIMIT,
                    route=Route.PLANNER,
                    required_slots=["card_id", "spending_limit"],
                )
            return self._result(Intent.LIST_CARDS)
        if any(word in normalized for word in ("持仓", "我的理财")):
            return self._result(Intent.GET_HOLDINGS)
        if any(word in normalized for word in ("理财", "基金", "产品")):
            if any(word in normalized for word in ("风险测评", "风险评估")):
                return self._result(
                    Intent.ASSESS_RISK_PROFILE,
                    route=Route.PLANNER,
                    required_slots=["answers"],
                )
            if any(word in normalized for word in ("比较", "对比")):
                return self._result(
                    Intent.COMPARE_WEALTH_PRODUCTS,
                    route=Route.PLANNER,
                    required_slots=["product_ids"],
                )
            if any(word in normalized for word in ("申购", "购买")):
                return self._result(
                    Intent.SUBSCRIBE_WEALTH,
                    route=Route.PLANNER,
                    complexity=3,
                    required_slots=["account_id", "product_id", "amount"],
                )
            if "赎回" in normalized:
                return self._result(
                    Intent.REDEEM_WEALTH,
                    route=Route.PLANNER,
                    complexity=3,
                    required_slots=["account_id", "product_id", "amount"],
                )
            if "推荐" in normalized:
                return self._result(Intent.GET_WEALTH_RECOMMENDATIONS)
            return self._result(Intent.LIST_WEALTH_PRODUCTS)
        if any(word in normalized for word in ("储蓄罐", "储藏罐", "储蓄目标")):
            if any(word in normalized for word in ("创建", "新增", "设置")):
                return self._result(
                    Intent.CREATE_SAVINGS_POT,
                    route=Route.PLANNER,
                    required_slots=["name", "target_amount", "target_date", "currency"],
                )
            if any(word in normalized for word in ("存入", "投入", "贡献")):
                return self._result(
                    Intent.CONTRIBUTE_SAVINGS_POT,
                    route=Route.PLANNER,
                    required_slots=["pot_id", "amount"],
                )
            return self._result(Intent.LIST_SAVINGS_POTS)
        return self._result(
            Intent.UNKNOWN,
            route=Route.SAFE_FALLBACK,
            complexity=2,
            confidence=0.0,
            reason="request is outside deterministic supported intents",
        )
