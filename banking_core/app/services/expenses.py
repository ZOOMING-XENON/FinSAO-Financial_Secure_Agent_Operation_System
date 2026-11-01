from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from banking_core.app.domain.enums import TransactionStatus
from banking_core.app.persistence.models import AccountModel, LedgerEntryModel, TransactionModel
from shared.expense_taxonomy import (
    EXCLUDED_EXPENSE_CATEGORIES,
    escape_like,
    normalize_category,
    normalize_merchant,
)

MAX_MERCHANT_GROUPS = 100


@dataclass(frozen=True)
class ExpenseFilters:
    account_id: UUID | None = None
    start: datetime | None = None
    end: datetime | None = None
    category: str | None = None
    merchant: str | None = None
    minimum_amount: Decimal | None = None
    maximum_amount: Decimal | None = None
    sort_by: Literal["posted_at", "amount", "category", "merchant"] = "posted_at"
    sort_direction: Literal["asc", "desc"] = "desc"
    limit: int = 50
    offset: int = 0


@dataclass(frozen=True)
class ExpenseSummary:
    total: Decimal | None
    transaction_count: int
    totals_by_currency: dict[str, Decimal]
    by_category: dict[str, dict[str, Decimal]]
    by_merchant: dict[str, dict[str, Decimal]]


class ExpenseService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def _base_query(self, user_id: UUID, filters: ExpenseFilters) -> Any:
        query = (
            select(TransactionModel)
            .join(LedgerEntryModel, LedgerEntryModel.transaction_id == TransactionModel.id)
            .join(AccountModel, AccountModel.id == LedgerEntryModel.account_id)
            .where(
                AccountModel.user_id == user_id,
                LedgerEntryModel.credit > 0,
                TransactionModel.status == TransactionStatus.COMPLETED,
                or_(
                    TransactionModel.category.is_(None),
                    TransactionModel.category.notin_(EXCLUDED_EXPENSE_CATEGORIES),
                ),
            )
        )
        if filters.account_id is not None:
            query = query.where(LedgerEntryModel.account_id == filters.account_id)
        if filters.start is not None:
            query = query.where(TransactionModel.posted_at >= filters.start)
        if filters.end is not None:
            query = query.where(TransactionModel.posted_at < filters.end)
        if filters.category is not None:
            query = query.where(TransactionModel.category == normalize_category(filters.category))
        if filters.merchant is not None:
            query = query.where(
                TransactionModel.description.ilike(
                    f"%{escape_like(filters.merchant)}%", escape="\\"
                )
            )
        if filters.minimum_amount is not None:
            query = query.where(TransactionModel.amount >= filters.minimum_amount)
        if filters.maximum_amount is not None:
            query = query.where(TransactionModel.amount <= filters.maximum_amount)
        return query

    def list(self, user_id: UUID, filters: ExpenseFilters) -> list[TransactionModel]:
        if filters.offset > 1000:
            raise ValueError("offset exceeds maximum policy")
        sort_column = {
            "posted_at": TransactionModel.posted_at,
            "amount": TransactionModel.amount,
            "category": TransactionModel.category,
            "merchant": TransactionModel.description,
        }[filters.sort_by]
        order = sort_column.asc() if filters.sort_direction == "asc" else sort_column.desc()
        query = self._base_query(user_id, filters).order_by(
            order.nullslast(),
            TransactionModel.posted_at.asc().nullslast(),
            TransactionModel.id.asc(),
        )
        query = query.limit(filters.limit).offset(filters.offset)
        return list(self.session.scalars(query).unique())

    def summary(self, user_id: UUID, filters: ExpenseFilters) -> ExpenseSummary:
        rows = list(self.session.scalars(self._base_query(user_id, filters)).unique())
        totals: dict[str, Decimal] = {}
        by_category: dict[str, dict[str, Decimal]] = {}
        by_merchant: dict[str, dict[str, Decimal]] = {}
        count = 0
        for transaction in rows:
            currency = transaction.currency.value
            amount = transaction.amount
            count += 1
            totals[currency] = totals.get(currency, Decimal("0.00")) + amount
            category = transaction.category or "UNKNOWN"
            by_category.setdefault(currency, {})
            by_category[currency][category] = (
                by_category[currency].get(category, Decimal("0.00")) + amount
            )
            merchant = normalize_merchant(transaction.description)
            if not merchant:
                merchant = "unknown"
            by_merchant.setdefault(currency, {})
            if merchant not in by_merchant[currency] and len(by_merchant[currency]) >= MAX_MERCHANT_GROUPS:
                merchant = "other"
            by_merchant[currency][merchant] = (
                by_merchant[currency].get(merchant, Decimal("0.00")) + amount
            )
        total = next(iter(totals.values())) if len(totals) == 1 else None
        return ExpenseSummary(total, count, totals, by_category, by_merchant)
