from __future__ import annotations

import re

from agent.contracts import TaskPlan

BUDGET_CATEGORIES = {
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

FIELD_LABELS = {
    "zh-CN": {
        "category": "预算类别",
        "month_date": "预算月份",
        "limit_amount": "预算上限",
        "source_account_id": "付款账户",
        "destination_account_id": "收款人（可输入姓名自动匹配）",
        "amount": "金额",
        "currency": "币种",
        "merchant": "商户",
        "occurred_at": "消费时间",
        "expense_id": "支出记录 ID",
        "name": "储蓄目标名称",
        "target_amount": "目标金额",
        "target_date": "目标日期",
        "account_id": "账户",
        "product_id": "理财产品",
        "resource_id": "目标资源",
    },
    "en-US": {
        "category": "Category",
        "month_date": "Budget month",
        "limit_amount": "Budget limit",
        "source_account_id": "Source account",
        "destination_account_id": "Beneficiary",
        "amount": "Amount",
        "currency": "Currency",
        "merchant": "Merchant",
        "occurred_at": "Expense time",
        "expense_id": "Expense ID",
        "name": "Savings goal name",
        "target_amount": "Target amount",
        "target_date": "Target date",
        "account_id": "Account",
        "product_id": "Investment product",
        "resource_id": "Resource",
    },
}


def is_english(locale: str) -> bool:
    return locale == "en-US"


def contains_cjk(value: str) -> bool:
    return re.search(r"[\u3400-\u9fff]", value) is not None


_ENGLISH_ENTITY_NAMES = {
    "爸爸": "Dad",
    "妈妈": "Mom",
    "爷爷": "Grandpa",
    "奶奶": "Grandma",
    "外公": "Grandpa",
    "外婆": "Grandma",
    "儿子": "Son",
    "女儿": "Daughter",
    "日常账户": "Checking",
    "活期账户": "Checking",
    "储蓄账户": "Savings",
}


def localize_entity_name(value: object, locale: str) -> str:
    """Localize built-in demo roles while preserving custom names."""
    text = str(value or "")
    if not is_english(locale):
        return text
    return _ENGLISH_ENTITY_NAMES.get(text, text)


_ENGLISH_PURPOSE = {
    "record_expense": "Record an expense",
    "update_expense": "Update an expense",
    "delete_expense": "Delete an expense",
    "get_accounts": "List the user's accounts",
    "get_balance": "Read an account balance",
    "get_transactions": "Read transaction history",
    "get_expenses": "List expenses",
    "summarize_expenses": "Summarize expenses",
    "create_transfer_draft": "Prepare a transfer",
    "commit_transfer": "Commit an approved transfer",
    "get_transfer_status": "Check transfer status",
    "resolve_beneficiary": "Resolve a recipient",
    "list_beneficiaries": "List saved recipients",
    "list_recent_recipients": "List recent recipients",
    "analyze_spending": "Analyze spending",
    "list_budgets": "List budgets",
    "get_budget_status": "Read budget usage",
    "create_budget": "Create a budget",
    "update_budget": "Update a budget",
    "list_subscriptions": "List subscriptions",
    "detect_recurring_payments": "Detect recurring payments",
    "cancel_subscription": "Cancel a subscription",
    "list_cards": "List cards",
    "get_card_status": "Read card status",
    "update_card_limit": "Update a card limit",
    "freeze_card": "Freeze a card",
    "unfreeze_card": "Unfreeze a card",
    "report_card_lost": "Report a card lost",
    "list_wealth_products": "List wealth products",
    "compare_wealth_products": "Compare wealth products",
    "get_wealth_recommendations": "Get wealth recommendations",
    "assess_risk_profile": "Assess risk profile",
    "get_holdings": "List holdings",
    "list_savings_pots": "List savings goals",
    "create_savings_pot": "Create a savings goal",
    "contribute_savings_pot": "Contribute to a savings goal",
}


def localize_plan(plan: TaskPlan, locale: str) -> TaskPlan:
    if not is_english(locale):
        return plan
    steps = []
    for step in plan.steps:
        tool = step.tool_call.tool_name if step.tool_call is not None else None
        purpose = _ENGLISH_PURPOSE.get(tool or "", "Execute the requested action")
        steps.append(step.model_copy(update={"purpose": purpose}))
    first_tool = next(
        (
            step.tool_call.tool_name
            for step in plan.steps
            if step.tool_call is not None
        ),
        None,
    )
    goal = _ENGLISH_PURPOSE.get(first_tool or "", "Complete the request")
    return plan.model_copy(update={"goal": goal, "steps": steps})
