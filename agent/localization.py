"""Small deterministic translations for Agent-owned user-facing text."""

from __future__ import annotations

import re

from agent.contracts import TaskPlan

_CJK = re.compile(r"[\u3400-\u9fff]")

FIELD_LABELS: dict[str, dict[str, str]] = {
    "zh-CN": {
        "category": "预算类别",
        "month_date": "预算月份",
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
        "budget_id": "预算",
        "card_id": "银行卡",
        "spending_limit": "消费限额",
        "product_ids": "理财产品",
        "answers": "风险测评答案",
        "pot_id": "储蓄目标",
    },
    "en-US": {
        "category": "Budget category",
        "month_date": "Budget month",
        "limit_amount": "Budget limit",
        "source_account_id": "Paying account",
        "destination_account_id": "Recipient (enter a saved name)",
        "amount": "Amount",
        "currency": "Currency",
        "name": "Savings goal name",
        "target_amount": "Target amount",
        "target_date": "Target date",
        "account_id": "Account",
        "product_id": "Investment product",
        "resource_id": "Item",
        "budget_id": "Budget",
        "card_id": "Card",
        "spending_limit": "Spending limit",
        "product_ids": "Investment products",
        "answers": "Risk assessment answers",
        "pot_id": "Savings goal",
    },
}

BUDGET_CATEGORIES: dict[str, dict[str, str]] = {
    "zh-CN": {
        "HOUSEHOLD": "家居",
        "GROCERIES": "日用",
        "TRANSPORT": "交通",
        "ENTERTAINMENT": "娱乐",
        "DINING": "餐饮",
        "HEALTHCARE": "医疗",
        "EDUCATION": "教育",
        "TRAVEL": "旅行",
    },
    "en-US": {
        "HOUSEHOLD": "Household",
        "GROCERIES": "Groceries",
        "TRANSPORT": "Transport",
        "ENTERTAINMENT": "Entertainment",
        "DINING": "Dining",
        "HEALTHCARE": "Healthcare",
        "EDUCATION": "Education",
        "TRAVEL": "Travel",
    },
}

_EN_PLAN_PURPOSES = {
    "get_accounts": "View bank accounts",
    "get_balance": "View account balance",
    "get_transactions": "View account transactions",
    "create_transfer_draft": "Prepare a transfer without moving funds",
    "analyze_spending": "Analyze monthly spending",
    "list_budgets": "View budgets",
    "get_budget_status": "View budget status",
    "create_budget": "Create a budget",
    "update_budget": "Update a budget",
    "list_subscriptions": "View subscriptions",
    "detect_recurring_payments": "Detect recurring payments",
    "cancel_subscription": "Cancel a subscription",
    "list_cards": "View cards",
    "get_card_status": "View card status",
    "update_card_limit": "Update a card spending limit",
    "freeze_card": "Freeze a card",
    "unfreeze_card": "Unfreeze a card",
    "report_card_lost": "Report a lost card",
    "list_wealth_products": "View investment products",
    "compare_wealth_products": "Compare investment products",
    "get_wealth_recommendations": "View investment recommendations",
    "assess_risk_profile": "Complete a risk assessment",
    "get_holdings": "View investment holdings",
    "create_wealth_subscription_draft": "Prepare an investment purchase",
    "create_wealth_redemption_draft": "Prepare an investment redemption",
    "list_savings_pots": "View savings goals",
    "create_savings_pot": "Create a savings goal",
    "contribute_savings_pot": "Add money to a savings goal",
}


def is_english(locale: str) -> bool:
    return locale == "en-US"


def contains_cjk(value: str) -> bool:
    return bool(_CJK.search(value))


def localize_plan(plan: TaskPlan, locale: str) -> TaskPlan:
    """Translate the fixed plan copy while preserving verified calls and dependencies."""

    if not is_english(locale):
        return plan
    raw = plan.model_dump(mode="python")
    purposes: list[str] = []
    for step in raw["steps"]:
        call = step.get("tool_call")
        tool_name = call.get("tool_name") if call else None
        purpose = _EN_PLAN_PURPOSES.get(tool_name or "")
        if purpose is None and contains_cjk(str(step["purpose"])):
            purpose = "Process the requested banking task"
        if purpose is not None:
            step["purpose"] = purpose
        purposes.append(str(step["purpose"]))
    if len(purposes) == 1:
        raw["goal"] = purposes[0]
    elif contains_cjk(str(raw["goal"])):
        raw["goal"] = "Complete the requested banking tasks"
    return TaskPlan.model_validate(raw)