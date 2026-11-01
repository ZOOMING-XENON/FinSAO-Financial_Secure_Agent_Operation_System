"""Privacy-preserving wrapper around a plan reviewer."""

from __future__ import annotations

from agent.contracts import TaskPlan
from agent.jev_http import JevUnavailable
from agent.privacy_broker import PrivacyBroker
from agent.routing import Intent
from agent.service import PlanReviewer


class PrivacyPreservingReviewer:
    def __init__(self, reviewer: PlanReviewer, broker: PrivacyBroker) -> None:
        self._reviewer = reviewer
        self._broker = broker

    async def review_plan(
        self, text: str, plan: TaskPlan, intent: Intent | None = None
    ) -> float:
        try:
            redacted = self._broker.tokenize(text).text
        except ValueError as exc:
            raise JevUnavailable("plan review text failed redaction") from exc
        return await self._reviewer.review_plan(redacted, plan, intent)
