from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from banking_core.app.domain.enums import (
    TransactionDirection,
    TransactionKind,
    TransactionOrigin,
)
from banking_core.app.persistence.models import AccountModel, LedgerEntryModel, TransactionModel
from banking_core.app.services.accounts import AccountService
from shared.expense_taxonomy import normalize_category


@dataclass(frozen=True)
class TransactionHistoryItem:
    transaction: TransactionModel
    direction: TransactionDirection
    account_id: UUID | None


@dataclass(frozen=True)
class AccountTransactionFilters:
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


class TransactionHistoryService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def account_history(
        self, account_id: UUID, user_id: UUID, filters: AccountTransactionFilters
    ) -> list[TransactionHistoryItem]:
        AccountService(self.session).get_account(account_id, user_id)
        query = (
            select(TransactionModel, LedgerEntryModel)
            .join(LedgerEntryModel, LedgerEntryModel.transaction_id == TransactionModel.id)
            .where(
                LedgerEntryModel.account_id == account_id,
                TransactionModel.deleted_at.is_(None),
            )
        )
        if filters.start is not None:
            query = query.where(TransactionModel.posted_at >= filters.start)
        if filters.end is not None:
            query = query.where(TransactionModel.posted_at < filters.end)
        if filters.category is not None:
            query = query.where(
                TransactionModel.category == normalize_category(filters.category)
            )
        if filters.merchant is not None:
            query = query.where(
                func.coalesce(TransactionModel.merchant, TransactionModel.description).ilike(
                    f"%{filters.merchant}%"
                )
            )
        if filters.minimum_amount is not None:
            query = query.where(TransactionModel.amount >= filters.minimum_amount)
        if filters.maximum_amount is not None:
            query = query.where(TransactionModel.amount <= filters.maximum_amount)
        column = {
            "posted_at": TransactionModel.posted_at,
            "amount": TransactionModel.amount,
            "category": TransactionModel.category,
            "merchant": TransactionModel.description,
        }[filters.sort_by]
        order = column.asc() if filters.sort_direction == "asc" else column.desc()
        query = query.order_by(
            order.nullslast(),
            TransactionModel.posted_at.asc().nullslast(),
            TransactionModel.id.asc(),
        ).limit(filters.limit).offset(filters.offset)
        return [
            TransactionHistoryItem(
                transaction=transaction,
                direction=(
                    TransactionDirection.DEBIT
                    if entry.credit > 0
                    else TransactionDirection.CREDIT
                ),
                account_id=account_id,
            )
            for transaction, entry in self.session.execute(query).all()
        ]

    def activity(self, user_id: UUID, limit: int, offset: int) -> list[TransactionHistoryItem]:
        bank_rows = self.session.execute(
            select(TransactionModel, LedgerEntryModel)
            .join(LedgerEntryModel, LedgerEntryModel.transaction_id == TransactionModel.id)
            .join(AccountModel, AccountModel.id == LedgerEntryModel.account_id)
            .where(
                AccountModel.user_id == user_id,
                TransactionModel.deleted_at.is_(None),
            )
        ).all()
        items: dict[UUID, TransactionHistoryItem] = {}
        for transaction, entry in bank_rows:
            direction = (
                TransactionDirection.MOVE
                if transaction.kind == TransactionKind.TRANSFER
                else TransactionDirection.DEBIT
                if entry.credit > 0
                else TransactionDirection.CREDIT
            )
            existing = items.get(transaction.id)
            if existing is None:
                items[transaction.id] = TransactionHistoryItem(
                    transaction=transaction,
                    direction=direction,
                    account_id=entry.account_id,
                )
            elif transaction.kind == TransactionKind.TRANSFER:
                items[transaction.id] = TransactionHistoryItem(
                    transaction=existing.transaction,
                    direction=TransactionDirection.MOVE,
                    account_id=existing.account_id,
                )
        manual_rows = self.session.scalars(
            select(TransactionModel).where(
                TransactionModel.user_id == user_id,
                TransactionModel.origin.in_(
                    (TransactionOrigin.CASH, TransactionOrigin.MANUAL)
                ),
                TransactionModel.deleted_at.is_(None),
            )
        )
        for transaction in manual_rows:
            items[transaction.id] = TransactionHistoryItem(
                transaction=transaction,
                direction=(
                    TransactionDirection.CREDIT
                    if transaction.kind in {TransactionKind.INCOME, TransactionKind.REFUND}
                    else TransactionDirection.DEBIT
                ),
                account_id=transaction.account_id,
            )
        ordered = sorted(
            items.values(),
            key=lambda item: (
                item.transaction.posted_at or datetime.min.replace(tzinfo=UTC),
                str(item.transaction.id),
            ),
            reverse=True,
        )
        return ordered[offset : offset + limit]
