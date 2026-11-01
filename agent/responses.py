"""Safe user-facing responses derived only from verified tool results."""

from __future__ import annotations

from typing import Any

from agent.contracts import AgentResponseStatus, TaskPlan


class SafeResponseGenerator:
    """Compose prose without inventing banking facts or exposing authorization data."""

    def compose(
        self,
        *,
        status: AgentResponseStatus,
        plan: TaskPlan,
        data: Any | None,
        locale: str = "zh-CN",
    ) -> str:
        tool_name = next(
            (
                step.tool_call.tool_name
                for step in reversed(plan.steps)
                if step.tool_call is not None
            ),
            "unknown",
        )
        english = locale == "en-US"
        if status == AgentResponseStatus.WAITING_APPROVAL:
            if english:
                return "Banking Core verified the plan and draft. Approval is required to continue."
            return "计划和草稿已由 Banking Core 验证，必须完成审批后才能继续。"
        if status == AgentResponseStatus.FAILED:
            if english:
                return "Banking Core did not confirm that the operation succeeded."
            return "Banking Core 未确认操作成功。"
        english_counts = {
            "get_accounts": ("account", "accounts"),
            "list_cards": ("card", "cards"),
            "list_budgets": ("budget", "budgets"),
            "list_subscriptions": ("subscription", "subscriptions"),
            "list_wealth_products": ("investment product", "investment products"),
            "get_holdings": ("holding", "holdings"),
            "list_savings_pots": ("savings goal", "savings goals"),
        }
        chinese_counts = {
            "get_accounts": "个账户",
            "list_cards": "张银行卡",
            "list_budgets": "条预算",
            "list_subscriptions": "条订阅",
            "list_wealth_products": "个理财产品",
            "get_holdings": "条持仓",
            "list_savings_pots": "个储蓄目标",
        }
        if tool_name in english_counts and isinstance(data, dict):
            items = data.get("accounts", data.get("items", []))
            if isinstance(items, list):
                if english:
                    singular, plural = english_counts[tool_name]
                    noun = singular if len(items) == 1 else plural
                    return f"Banking Core returned {len(items)} {noun}."
                return f"已从 Banking Core 查询到 {len(items)} {chinese_counts[tool_name]}。"
        if english:
            return "Banking Core returned the result. Only verified tool data is shown."
        return "操作结果已由 Banking Core 返回；展示内容只使用已验证的工具结果。"
