"""Feature-gated expense routing and deterministic expense intent support."""

from __future__ import annotations

from typing import Any

from agent.routing import Intent, IntentResult, Route, RuleRouter

EXPENSE_INTENTS = {
    Intent.TRACK_EXPENSES,
    Intent.SUMMARIZE_EXPENSES,
    Intent.CORRECT_EXPENSE_CATEGORY,
}


class ExpenseRouter:
    """Keep expense chat off until the feature flag is enabled."""

    def __init__(self, rules: RuleRouter, *, enabled: bool) -> None:
        self._rules = rules
        self._enabled = enabled

    def route(self, text: str, *, conversation: list[Any] | None = None) -> IntentResult:
        result = self._rules.route(text, conversation=conversation)
        if self._enabled or result.intent not in EXPENSE_INTENTS:
            return result
        return IntentResult(
            intent=Intent.UNKNOWN,
            complexity=2,
            confidence=0.0,
            route=Route.SAFE_FALLBACK,
            reason="expense tracking is disabled",
        )
