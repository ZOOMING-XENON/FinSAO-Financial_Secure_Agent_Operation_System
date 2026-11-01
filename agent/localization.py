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


def localize_plan(plan: TaskPlan, locale: str) -> TaskPlan:
    return plan
