from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from banking_core.app.domain.enums import (
    Currency,
    TransactionKind,
    TransactionOrigin,
    TransactionStatus,
)
from banking_core.app.domain.money import quantize_money
from banking_core.app.persistence.models import (
    AccountModel,
    AuditEventModel,
    TransactionModel,
)
from banking_core.app.services.errors import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
    ValidationError,
)
from shared.expense_taxonomy import normalize_category
from shared.tracing import current_trace_id

MANUAL_ORIGINS = frozenset({TransactionOrigin.CASH, TransactionOrigin.MANUAL})


class ExpenseRecordService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(
        self,
        user_id: UUID,
        *,
        amount: Decimal,
        currency: Currency,
        merchant: str,
        category: str | None,
        occurred_at: datetime | None,
        account_id: UUID | None,
        origin: TransactionOrigin,
        idempotency_key: str,
    ) -> TransactionModel:
        amount = quantize_money(amount)
        if amount <= 0:
            raise ValidationError("expense amount must be positive")
        merchant = merchant.strip()
        if not merchant:
            raise ValidationError("expense merchant is required")
        if len(merchant) > 120:
            merchant = merchant[:120]
        if origin not in MANUAL_ORIGINS:
            origin = TransactionOrigin.MANUAL
        if account_id is not None:
            account = self.session.get(AccountModel, account_id)
            if (
                account is None
                or account.is_system
                or account.user_id != user_id
            ):
                raise ForbiddenError("account is not available")
            if account.currency != currency:
                raise ValidationError("expense currency must match the account currency")
        try:
            normalized_category = normalize_category(category) if category else "UNKNOWN"
        except ValueError as exc:
            raise ValidationError("unsupported expense category") from exc
        existing = self.session.scalar(
            select(TransactionModel).where(
                TransactionModel.user_id == user_id,
                TransactionModel.idempotency_key == idempotency_key,
            )
        )
        if existing is not None:
            if (
                existing.amount != amount
                or existing.currency != currency
                or existing.merchant != merchant
                or existing.category != normalized_category
                or existing.origin != origin
            ):
                raise ConflictError("idempotency key reused with a different expense")
            return existing
        occurred = occurred_at or datetime.now(UTC)
        if occurred.tzinfo is None:
            raise ValidationError("expense time must be timezone-aware")
        transaction = TransactionModel(
            id=uuid4(),
            user_id=user_id,
            account_id=account_id,
            reference=f"EXP-{uuid4()}",
            status=TransactionStatus.COMPLETED,
            kind=TransactionKind.EXPENSE,
            origin=origin,
            amount=amount,
            currency=currency,
            description=merchant,
            merchant=merchant,
            category=normalized_category,
            category_source="USER" if category else None,
            category_version="expense-v1" if category else None,
            category_labeled_at=datetime.now(UTC) if category else None,
            posted_at=occurred,
            idempotency_key=idempotency_key,
        )
        self.session.add(transaction)
        self._audit(user_id, "expense.create", transaction)
        try:
            self.session.commit()
        except IntegrityError:
            self.session.rollback()
            existing = self.session.scalar(
                select(TransactionModel).where(
                    TransactionModel.user_id == user_id,
                    TransactionModel.idempotency_key == idempotency_key,
                )
            )
            if existing is None:
                raise ConflictError("expense idempotency conflict") from None
            if (
                existing.amount != amount
                or existing.currency != currency
                or existing.merchant != merchant
            ):
                raise ConflictError("expense idempotency conflict") from None
            return existing
        self.session.refresh(transaction)
        return transaction

    def get(self, expense_id: UUID, user_id: UUID) -> TransactionModel:
        transaction = self.session.get(TransactionModel, expense_id)
        if transaction is None or transaction.deleted_at is not None:
            raise NotFoundError("expense not found")
        if transaction.user_id != user_id or transaction.kind != TransactionKind.EXPENSE:
            raise ForbiddenError("expense belongs to another user")
        return transaction

    def update(
        self,
        expense_id: UUID,
        user_id: UUID,
        *,
        amount: Decimal | None = None,
        currency: Currency | None = None,
        merchant: str | None = None,
        category: str | None = None,
        occurred_at: datetime | None = None,
        account_id: UUID | None = None,
    ) -> TransactionModel:
        transaction = self.get(expense_id, user_id)
        if transaction.origin not in MANUAL_ORIGINS:
            raise ForbiddenError("bank transactions cannot be edited here")
        if amount is not None:
            amount = quantize_money(amount)
            if amount <= 0:
                raise ValidationError("expense amount must be positive")
            transaction.amount = amount
        if currency is not None:
            transaction.currency = currency
        if merchant is not None:
            merchant = merchant.strip()
            if not merchant:
                raise ValidationError("expense merchant is required")
            transaction.merchant = merchant[:120]
            transaction.description = transaction.merchant
        if category is not None:
            try:
                transaction.category = normalize_category(category)
            except ValueError as exc:
                raise ValidationError("unsupported expense category") from exc
            transaction.category_source = "USER"
            transaction.category_version = "expense-v1"
            transaction.category_labeled_at = datetime.now(UTC)
        if occurred_at is not None:
            if occurred_at.tzinfo is None:
                raise ValidationError("expense time must be timezone-aware")
            transaction.posted_at = occurred_at
        if account_id is not None:
            account = self.session.get(AccountModel, account_id)
            if account is None or account.is_system or account.user_id != user_id:
                raise ForbiddenError("account is not available")
            transaction.account_id = account_id
        self._audit(user_id, "expense.update", transaction)
        self.session.commit()
        self.session.refresh(transaction)
        return transaction

    def delete(self, expense_id: UUID, user_id: UUID) -> None:
        transaction = self.get(expense_id, user_id)
        if transaction.origin not in MANUAL_ORIGINS:
            raise ForbiddenError("bank transactions cannot be deleted here")
        transaction.deleted_at = datetime.now(UTC)
        self._audit(user_id, "expense.delete", transaction)
        self.session.commit()

    def _audit(self, user_id: UUID, action: str, transaction: TransactionModel) -> None:
        self.session.add(
            AuditEventModel(
                id=uuid4(),
                actor_user_id=user_id,
                action=action,
                resource_type="expense",
                resource_id=str(transaction.id),
                trace_id=current_trace_id(),
                outcome="COMPLETED",
                details={
                    "amount": str(transaction.amount),
                    "currency": transaction.currency.value,
                },
            )
        )
