"""Least-privilege tool disclosure based only on trusted stage and intent."""

from __future__ import annotations

from agent.contracts import TrustedAgentContext
from agent.routing import Intent
from agent_tools.registry import ToolRegistry


class CapabilityBroker:
    _ACTIONS: dict[Intent, set[str]] = {
        Intent.LIST_ACCOUNTS: {"accounts.list"},
        Intent.GET_BALANCE: {"accounts.list", "balance.query"},
        Intent.GET_TRANSACTIONS: {"accounts.list", "transactions.query"},
        Intent.TRACK_EXPENSES: {"expenses.query"},
        Intent.SUMMARIZE_EXPENSES: {"expenses.summary"},
        Intent.CORRECT_EXPENSE_CATEGORY: set(),
        Intent.TRANSFER: {
            "accounts.list",
            "balance.query",
            "beneficiaries.list",
            "beneficiaries.resolve",
            "transfer.draft",
            "transfer.status",
        },
        Intent.ANALYZE_SPENDING: {"bills.query"},
        Intent.LIST_BUDGETS: {"budget.query"},
        Intent.GET_BUDGET_STATUS: {"budget.query"},
        Intent.CREATE_BUDGET: {"budget.create"},
        Intent.UPDATE_BUDGET: {"budget.update"},
        Intent.LIST_SUBSCRIPTIONS: {"bills.query"},
        Intent.DETECT_RECURRING: {"bills.query"},
        Intent.CANCEL_SUBSCRIPTION: {"subscription.cancel"},
        Intent.LIST_CARDS: {"cards.list"},
        Intent.GET_CARD: {"cards.status"},
        Intent.UPDATE_CARD_LIMIT: {"card.limit"},
        Intent.FREEZE_CARD: {"card.freeze"},
        Intent.UNFREEZE_CARD: {"card.unfreeze"},
        Intent.REPORT_CARD_LOST: {"card.report_lost"},
        Intent.LIST_WEALTH_PRODUCTS: {"wealth.list"},
        Intent.COMPARE_WEALTH_PRODUCTS: {"wealth.compare"},
        Intent.GET_WEALTH_RECOMMENDATIONS: {"wealth.recommendations"},
        Intent.ASSESS_RISK_PROFILE: {"wealth.assess"},
        Intent.GET_HOLDINGS: {"wealth.holdings"},
        Intent.SUBSCRIBE_WEALTH: {"wealth.draft", "wealth.status"},
        Intent.REDEEM_WEALTH: {"wealth.redemption_draft", "wealth.status"},
        Intent.LIST_SAVINGS_POTS: {"savings.list"},
        Intent.CREATE_SAVINGS_POT: {"savings.create"},
        Intent.CONTRIBUTE_SAVINGS_POT: {"savings.contribute"},
        Intent.GENERAL_CHAT: set(),
        Intent.UNKNOWN: set(),
    }

    def __init__(self, registry: ToolRegistry) -> None:
        self._registry = registry

    def allowed_actions(
        self, *, context: TrustedAgentContext, intent: Intent, stage: str = "planning"
    ) -> set[str]:
        del context
        actions = set(self._ACTIONS[intent])
        if stage != "authorized_execution":
            actions.discard("transfer.commit")
        return actions

    def schemas(
        self, *, context: TrustedAgentContext, intent: Intent, stage: str = "planning"
    ) -> list[dict[str, object]]:
        actions = self.allowed_actions(context=context, intent=intent, stage=stage)
        return self._registry.list_allowed(actions)
