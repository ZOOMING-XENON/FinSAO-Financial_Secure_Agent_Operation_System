import builtins
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from banking_core.app.domain.enums import Currency
from banking_core.app.persistence.models import (
    AccountModel,
    AuditEventModel,
    BudgetModel,
    LedgerEntryModel,
    RenewalReminderModel,
    SubscriptionModel,
    TransactionModel,
)
from banking_core.app.security.approvals import consume_resource_authorization
from banking_core.app.services.errors import (
    AuthorizationError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
)
from shared.tracing import current_trace_id

BUSINESS_TZ = ZoneInfo("Asia/Shanghai")
CATEGORY_RULES = {
    "stream": "ENTERTAINMENT",
    "market": "GROCERIES",
    "taxi": "TRANSPORT",
    "household": "HOUSEHOLD",
    "restaurant": "DINING",
}
EXCLUDED_SPENDING_CATEGORIES = {"INTERNAL_TRANSFER", "OPENING_BALANCE"}


def categorize(description: str) -> str:
    lowered = description.lower()
    return next((category for key, category in CATEGORY_RULES.items() if key in lowered), "UNKNOWN")


@dataclass(frozen=True)
class SpendingSummary:
    total: Decimal
    by_category: dict[str, Decimal]
    by_merchant: dict[str, Decimal]


class BillAnalysisService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def monthly_summary(self, user_id: UUID, year: int, month: int) -> SpendingSummary:
        start = datetime(year, month, 1, tzinfo=BUSINESS_TZ)
        end = datetime(year + (month == 12), month % 12 + 1, 1, tzinfo=BUSINESS_TZ)
        rows = self.session.execute(
            select(TransactionModel, LedgerEntryModel.credit)
            .join(LedgerEntryModel, LedgerEntryModel.transaction_id == TransactionModel.id)
            .join(AccountModel, AccountModel.id == LedgerEntryModel.account_id)
            .where(
                AccountModel.user_id == user_id,
                LedgerEntryModel.credit > 0,
                TransactionModel.posted_at >= start.astimezone(UTC),
                TransactionModel.posted_at < end.astimezone(UTC),
            )
        ).all()
        categories: defaultdict[str, Decimal] = defaultdict(lambda: Decimal("0.00"))
        merchants: defaultdict[str, Decimal] = defaultdict(lambda: Decimal("0.00"))
        total = Decimal("0.00")
        for transaction, amount in rows:
            category = transaction.category or categorize(transaction.description)
            if category in EXCLUDED_SPENDING_CATEGORIES:
                continue
            total += amount
            categories[category] += amount
            merchants[transaction.description] += amount
        return SpendingSummary(total, dict(categories), dict(merchants))

    def correct_category(
        self, transaction_id: UUID, user_id: UUID, category: str
    ) -> TransactionModel:
        transaction = self.session.scalar(
            select(TransactionModel)
            .join(LedgerEntryModel, LedgerEntryModel.transaction_id == TransactionModel.id)
            .join(AccountModel, AccountModel.id == LedgerEntryModel.account_id)
            .where(TransactionModel.id == transaction_id, AccountModel.user_id == user_id)
        )
        if transaction is None:
            raise NotFoundError("transaction not found")
        transaction.category = category.strip().upper()
        self.session.commit()
        return transaction

    def unusual_spending(self, user_id: UUID, year: int, month: int) -> list[tuple[str, Decimal]]:
        summary = self.monthly_summary(user_id, year, month)
        if not summary.by_merchant:
            return []
        average = summary.total / len(summary.by_merchant)
        return [
            (merchant, amount)
            for merchant, amount in summary.by_merchant.items()
            if amount > average * 2
        ]

    def monthly_comparison(self, user_id: UUID, year: int, month: int) -> dict[str, Decimal]:
        current = self.monthly_summary(user_id, year, month).total
        previous_year, previous_month = (year - 1, 12) if month == 1 else (year, month - 1)
        previous = self.monthly_summary(user_id, previous_year, previous_month).total
        return {"current": current, "previous": previous, "change": current - previous}


class BudgetService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(
        self, user_id: UUID, category: str, month: date, limit: Decimal, currency: Currency
    ) -> BudgetModel:
        if limit <= 0:
            raise ConflictError("budget limit must be positive")
        budget = BudgetModel(
            id=uuid4(),
            user_id=user_id,
            category=category.upper(),
            month=month,
            limit_amount=limit,
            currency=currency,
        )
        self.session.add(budget)
        self.session.commit()
        return budget

    def update(self, budget_id: UUID, user_id: UUID, limit: Decimal) -> BudgetModel:
        budget = self.session.get(BudgetModel, budget_id)
        if budget is None:
            raise NotFoundError("budget not found")
        if budget.user_id != user_id:
            raise ForbiddenError("budget belongs to another user")
        if limit <= 0:
            raise ConflictError("budget limit must be positive")
        budget.limit_amount = limit
        self.session.commit()
        return budget

    def list(self, user_id: UUID) -> list[BudgetModel]:
        return list(self.session.scalars(select(BudgetModel).where(BudgetModel.user_id == user_id)))

    def status(
        self,
        budget_id: UUID,
        user_id: UUID,
        as_of: date | None = None,
        threshold: Decimal = Decimal("0.80"),
    ) -> dict[str, Decimal | bool]:
        budget = self.session.get(BudgetModel, budget_id)
        if budget is None:
            raise NotFoundError("budget not found")
        if budget.user_id != user_id:
            raise ForbiddenError("budget belongs to another user")
        summary = BillAnalysisService(self.session).monthly_summary(
            user_id, budget.month.year, budget.month.month
        )
        used = summary.by_category.get(budget.category, Decimal("0.00"))
        today = as_of or datetime.now(BUSINESS_TZ).date()
        budget_key = (budget.month.year, budget.month.month)
        today_key = (today.year, today.month)
        if budget_key < today_key:
            estimate = used
        elif budget_key > today_key:
            estimate = Decimal("0.00")
        else:
            estimate = (used / max(1, today.day) * 30).quantize(Decimal("0.01"))
        return {
            "limit": budget.limit_amount,
            "used": used,
            "remaining": max(Decimal("0.00"), budget.limit_amount - used),
            "estimate": estimate,
            "threshold_exceeded": used >= budget.limit_amount * threshold,
        }


class SubscriptionService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def list(self, user_id: UUID) -> list[SubscriptionModel]:
        return list(
            self.session.scalars(
                select(SubscriptionModel).where(SubscriptionModel.user_id == user_id)
            )
        )

    def detect_recurring(self, user_id: UUID) -> builtins.list[dict[str, object]]:
        rows = self.session.execute(
            select(
                TransactionModel.id,
                TransactionModel.description,
                TransactionModel.amount,
                TransactionModel.posted_at,
            )
            .join(LedgerEntryModel, LedgerEntryModel.transaction_id == TransactionModel.id)
            .join(AccountModel, AccountModel.id == LedgerEntryModel.account_id)
            .where(AccountModel.user_id == user_id, LedgerEntryModel.credit > 0)
            .order_by(TransactionModel.description, TransactionModel.posted_at)
        ).all()
        groups: defaultdict[str, builtins.list[tuple[UUID, Decimal, datetime]]] = defaultdict(list)
        for transaction_id, description, amount, posted_at in rows:
            if posted_at is not None:
                groups[description].append((transaction_id, amount, posted_at))
        found: builtins.list[dict[str, object]] = []
        for merchant, events in groups.items():
            if len(events) < 3:
                continue
            stable = max(item[1] for item in events) - min(item[1] for item in events) <= Decimal(
                "1.00"
            )
            intervals = [
                (events[index][2].date() - events[index - 1][2].date()).days
                for index in range(1, len(events))
            ]
            if stable and all(25 <= days <= 35 for days in intervals):
                found.append(
                    {
                        "merchant": merchant,
                        "confidence": "HIGH",
                        "evidence_transaction_ids": [str(item[0]) for item in events],
                        "estimated_next_billing_date": str(
                            events[-1][2].date()
                            + timedelta(days=round(sum(intervals) / len(intervals)))
                        ),
                    }
                )
        return found

    def create_reminder(
        self, subscription_id: UUID, user_id: UUID, remind_on: date
    ) -> RenewalReminderModel:
        subscription = self.session.get(SubscriptionModel, subscription_id)
        if subscription is None:
            raise NotFoundError("subscription not found")
        if subscription.user_id != user_id:
            raise ForbiddenError("subscription belongs to another user")
        existing = self.session.scalar(
            select(RenewalReminderModel).where(
                RenewalReminderModel.subscription_id == subscription_id,
                RenewalReminderModel.remind_on == remind_on,
            )
        )
        if existing is not None:
            return existing
        reminder = RenewalReminderModel(
            id=uuid4(),
            subscription_id=subscription_id,
            user_id=user_id,
            remind_on=remind_on,
            delivered=False,
        )
        self.session.add(reminder)
        self.session.commit()
        return reminder

    def cancel(
        self, subscription_id: UUID, user_id: UUID, authorization_ref: str
    ) -> SubscriptionModel:
        subscription = self.session.get(SubscriptionModel, subscription_id)
        if subscription is None:
            raise NotFoundError("subscription not found")
        if subscription.user_id != user_id:
            raise ForbiddenError("subscription belongs to another user")
        if not subscription.active:
            return subscription
        if not consume_resource_authorization(
            self.session,
            operation_id=subscription_id,
            actor_id=user_id,
            action="subscription.cancel",
            authorization_ref=authorization_ref,
        ):
            raise AuthorizationError("valid cancellation authorization required")
        subscription.active = False
        subscription.status = "CANCELLED"
        subscription.cancelled_at = datetime.now(UTC)
        self.session.add(
            AuditEventModel(
                id=uuid4(),
                actor_user_id=user_id,
                action="subscription.cancel",
                resource_type="subscription",
                resource_id=str(subscription_id),
                trace_id=current_trace_id(),
                outcome="COMPLETED",
                details={},
            )
        )
        self.session.commit()
        return subscription
