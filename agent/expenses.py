"""Feature-gated expense routing and deterministic expense intent support."""

from __future__ import annotations

from typing import Any

from agent.routing import Intent, IntentResult, Route, RuleRouter

EXPENSE_INTENTS = {
    Intent.RECORD_EXPENSE,
    Intent.UPDATE_EXPENSE,
    Intent.DELETE_EXPENSE,
    Intent.TRACK_EXPENSES,
    Intent.SUMMARIZE_EXPENSES,
    Intent.CORRECT_EXPENSE_CATEGORY,
}


EXPENSE_WRITE_INTENTS = {
    Intent.RECORD_EXPENSE,
    Intent.UPDATE_EXPENSE,
    Intent.DELETE_EXPENSE,
    Intent.CORRECT_EXPENSE_CATEGORY,
}


class ExpenseRouter:
    """Keep expense chat off until the feature flag is enabled."""

    def __init__(
        self, rules: RuleRouter, *, enabled: bool, capture_enabled: bool = True
    ) -> None:
        self._rules = rules
        self._enabled = enabled
        self._capture_enabled = capture_enabled

    def route(self, text: str, *, conversation: list[Any] | None = None) -> IntentResult:
        result = self._rules.route(text, conversation=conversation)
        if result.intent not in EXPENSE_INTENTS:
            return result
        if not self._enabled:
            return self._disabled()
        if result.intent in EXPENSE_WRITE_INTENTS and not self._capture_enabled:
            return self._disabled("expense capture is disabled")
        return result

    @staticmethod
    def _disabled(reason: str = "expense tracking is disabled") -> IntentResult:
        return IntentResult(
            intent=Intent.UNKNOWN,
            complexity=2,
            confidence=0.0,
            route=Route.SAFE_FALLBACK,
            reason=reason,
        )
