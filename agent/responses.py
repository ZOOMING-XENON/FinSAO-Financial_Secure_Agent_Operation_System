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
    ) -> str:
        tool_name = next(
            (
                step.tool_call.tool_name
                for step in reversed(plan.steps)
                if step.tool_call is not None
            ),
            "unknown",
        )
        if status == AgentResponseStatus.WAITING_APPROVAL:
            return (
                "我已经把这项操作整理好了，Banking Core 也完成了草稿校验。"
                "为了保护您的资金安全，还需要您在安全界面确认或完成验证；"
                "在此之前不会发生实际资金变动。"
            )
        if status == AgentResponseStatus.FAILED:
            return (
                "这次操作还没有得到 Banking Core 的成功确认，"
                "所以我不会把它说成已完成。您可以根据页面上的错误提示检查信息后再试一次。"
            )
        counts = {
            "get_accounts": "个账户",
            "list_cards": "张银行卡",
            "list_budgets": "条预算",
            "list_subscriptions": "条订阅",
            "list_wealth_products": "个理财产品",
            "get_holdings": "条持仓",
            "list_savings_pots": "个储蓄目标",
        }
        if tool_name in counts and isinstance(data, dict):
            items = data.get("accounts", data.get("items", []))
            if isinstance(items, list):
                return (
                    f"已经帮您查到 {len(items)} {counts[tool_name]}。"
                    "下面展示的是 Banking Core 返回的实际结果，"
                    "我没有补写或猜测其中的金融数据。"
                )
        return (
            "这一步已经处理完成。下面的内容来自 Banking Core "
            "返回并校验过的结果，金额、日期和状态都不是由对话模型自行生成的。"
        )
