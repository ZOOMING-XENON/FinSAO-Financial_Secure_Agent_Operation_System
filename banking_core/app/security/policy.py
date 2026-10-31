from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from banking_core.app.domain.enums import RiskTier, TransferStatus
from banking_core.app.persistence.models import TransferDraftModel
from banking_core.app.security.models import PolicyDecision, PolicyStatus

BUSINESS_TIMEZONE = ZoneInfo("Asia/Shanghai")
YELLOW_TRANSFER_LIMIT = Decimal("1000.00")


class PolicyEngine:
    def __init__(self, session: Session) -> None:
        self.session = session

    def daily_outgoing(self, actor_id: UUID, now: datetime | None = None) -> Decimal:
        local_now = (now or datetime.now(UTC)).astimezone(BUSINESS_TIMEZONE)
        start_local = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
        start_utc = start_local.astimezone(UTC)
        statuses = [
            TransferStatus.PENDING_AUTHORIZATION,
            TransferStatus.AUTHORIZED,
            TransferStatus.PROCESSING,
            TransferStatus.COMPLETED,
        ]
        total = self.session.scalar(
            select(func.coalesce(func.sum(TransferDraftModel.amount), 0)).where(
                TransferDraftModel.user_id == actor_id,
                TransferDraftModel.status.in_(statuses),
                TransferDraftModel.created_at >= start_utc,
            )
        )
        return Decimal(total or 0)

    def evaluate(
        self, action: str, actor: UUID, resource: dict[str, Any], context: dict[str, Any]
    ) -> PolicyDecision:
        del context
        green = {"balance.query", "transactions.query", "bills.query", "investment_returns.query"}
        yellow = {
            "subscription.cancel",
            "virtual_card.apply",
            "card.limit",
            "card.freeze",
            "card.unfreeze",
        }
        red = {
            "password.change",
            "card.report_lost",
            "wealth.subscribe",
            "wealth.redeem",
        }
        if action in green:
            return PolicyDecision(
                action=action,
                risk_tier=RiskTier.GREEN,
                status=PolicyStatus.ALLOWED,
                reason="read-only operation",
            )
        if action == "transfer.commit":
            cumulative = self.daily_outgoing(actor)
            tier = RiskTier.YELLOW if cumulative <= YELLOW_TRANSFER_LIMIT else RiskTier.RED
            status = (
                PolicyStatus.REQUIRES_CONFIRMATION
                if tier == RiskTier.YELLOW
                else PolicyStatus.REQUIRES_MFA
            )
            return PolicyDecision(
                action=action,
                risk_tier=tier,
                status=status,
                reason=f"daily reserved and committed outgoing amount is CNY {cumulative:.2f}",
            )
        if action == "savings.contribute":
            amount = Decimal(str(resource.get("amount", "0")))
            tier = RiskTier.YELLOW if amount <= YELLOW_TRANSFER_LIMIT else RiskTier.RED
            return PolicyDecision(
                action=action,
                risk_tier=tier,
                status=(
                    PolicyStatus.REQUIRES_CONFIRMATION
                    if tier == RiskTier.YELLOW
                    else PolicyStatus.REQUIRES_MFA
                ),
                reason=f"savings contribution amount is CNY {amount:.2f}",
            )
        if action in yellow:
            return PolicyDecision(
                action=action,
                risk_tier=RiskTier.YELLOW,
                status=PolicyStatus.REQUIRES_CONFIRMATION,
                reason="explicit confirmation required",
            )
        if action in red:
            return PolicyDecision(
                action=action,
                risk_tier=RiskTier.RED,
                status=PolicyStatus.REQUIRES_MFA,
                reason="strong verification required",
            )
        return PolicyDecision(
            action=action,
            risk_tier=RiskTier.RED,
            status=PolicyStatus.DENIED,
            reason="operation has no allow policy",
        )
