from collections.abc import Sequence
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from banking_core.app.domain.enums import AccountStatus, Currency, TransactionStatus
from banking_core.app.domain.money import quantize_money
from banking_core.app.persistence.models import (
    AccountModel,
    AuditEventModel,
    SavingsContributionModel,
    SavingsPotModel,
    TransactionModel,
)
from banking_core.app.security.approvals import consume_resource_authorization
from banking_core.app.services.errors import (
    AuthorizationError,
    ConflictError,
    ForbiddenError,
    InsufficientFundsError,
    NotFoundError,
)
from banking_core.app.services.ledger import LedgerService
from shared.tracing import current_trace_id


class SavingsPotService:
    """Account-funded savings goals with authorized, ledger-backed contributions."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def list(self, user_id: UUID) -> list[SavingsPotModel]:
        return list(
            self.session.scalars(
                select(SavingsPotModel)
                .where(SavingsPotModel.user_id == user_id)
                .order_by(SavingsPotModel.created_at, SavingsPotModel.id)
            )
        )

    def get(self, pot_id: UUID, user_id: UUID) -> SavingsPotModel:
        pot = self.session.get(SavingsPotModel, pot_id)
        if pot is None:
            raise NotFoundError("savings pot not found")
        if pot.user_id != user_id:
            raise ForbiddenError("savings pot belongs to another user")
        return pot

    def create(
        self,
        user_id: UUID,
        *,
        name: str,
        target_amount: Decimal,
        currency: Currency,
        target_date: date,
        idempotency_key: str,
    ) -> SavingsPotModel:
        existing = self.session.scalar(
            select(SavingsPotModel).where(
                SavingsPotModel.user_id == user_id,
                SavingsPotModel.idempotency_key == idempotency_key,
            )
        )
        if existing is not None:
            if (
                existing.name != name
                or existing.target_amount != target_amount
                or existing.currency != currency
                or existing.target_date != target_date
            ):
                raise ConflictError("idempotency key reused with different savings pot")
            return existing
        pot = SavingsPotModel(
            id=uuid4(),
            user_id=user_id,
            name=name,
            target_amount=target_amount,
            saved_amount=Decimal("0.00"),
            currency=currency,
            target_date=target_date,
            status="ACTIVE",
            allocation_mode="ACCOUNT_FUNDED",
            idempotency_key=idempotency_key,
        )
        self.session.add(pot)
        try:
            self.session.commit()
        except IntegrityError:
            self.session.rollback()
            return self.create(
                user_id,
                name=name,
                target_amount=target_amount,
                currency=currency,
                target_date=target_date,
                idempotency_key=idempotency_key,
            )
        self.session.refresh(pot)
        return pot

    def update(
        self,
        pot_id: UUID,
        user_id: UUID,
        *,
        name: str | None,
        target_amount: Decimal | None,
        target_date: date | None,
    ) -> SavingsPotModel:
        pot = self.get(pot_id, user_id)
        if name is not None:
            pot.name = name
        if target_amount is not None:
            pot.target_amount = target_amount
        if target_date is not None:
            pot.target_date = target_date
        pot.status = "COMPLETED" if pot.saved_amount >= pot.target_amount else "ACTIVE"
        self.session.commit()
        self.session.refresh(pot)
        return pot

    def delete(self, pot_id: UUID, user_id: UUID) -> None:
        pot = self.get(pot_id, user_id)
        if pot.saved_amount > 0:
            raise ConflictError("funded savings pot cannot be deleted")
        self.session.execute(
            delete(SavingsContributionModel).where(SavingsContributionModel.pot_id == pot_id)
        )
        self.session.execute(delete(SavingsPotModel).where(SavingsPotModel.id == pot_id))
        self.session.commit()

    def list_contributions(self, pot_id: UUID, user_id: UUID) -> Sequence[SavingsContributionModel]:
        self.get(pot_id, user_id)
        return list(
            self.session.scalars(
                select(SavingsContributionModel)
                .where(SavingsContributionModel.pot_id == pot_id)
                .order_by(SavingsContributionModel.created_at, SavingsContributionModel.id)
            )
        )

    def contribute(
        self,
        pot_id: UUID,
        user_id: UUID,
        *,
        source_account_id: UUID,
        amount: Decimal,
        note: str | None,
        idempotency_key: str,
        authorization_ref: str,
    ) -> SavingsContributionModel:
        amount = quantize_money(amount)
        existing = self.session.scalar(
            select(SavingsContributionModel).where(
                SavingsContributionModel.user_id == user_id,
                SavingsContributionModel.idempotency_key == idempotency_key,
            )
        )
        if existing is not None:
            if (
                existing.pot_id != pot_id
                or existing.source_account_id != source_account_id
                or existing.amount != amount
                or existing.note != note
            ):
                raise ConflictError("idempotency key reused with different contribution")
            return existing
        if self.session.in_transaction():
            self.session.rollback()
        with self.session.begin():
            pot = self.session.scalar(
                select(SavingsPotModel).where(SavingsPotModel.id == pot_id).with_for_update()
            )
            if pot is None:
                raise NotFoundError("savings pot not found")
            if pot.user_id != user_id:
                raise ForbiddenError("savings pot belongs to another user")
            accounts = list(
                self.session.scalars(
                    select(AccountModel)
                    .where(
                        (AccountModel.id == source_account_id)
                        | (
                            AccountModel.is_system.is_(True)
                            & (AccountModel.currency == pot.currency)
                        )
                    )
                    .order_by(AccountModel.id)
                    .with_for_update()
                )
            )
            source = next(
                (account for account in accounts if account.id == source_account_id), None
            )
            settlement = next((account for account in accounts if account.is_system), None)
            if (
                source is None
                or source.user_id != user_id
                or source.is_system
                or source.status != AccountStatus.ACTIVE
                or source.currency != pot.currency
            ):
                raise ForbiddenError("source account is unavailable")
            if settlement is None or settlement.status != AccountStatus.ACTIVE:
                raise ConflictError("savings settlement account is unavailable")
            if not consume_resource_authorization(
                self.session,
                operation_id=pot_id,
                actor_id=user_id,
                action="savings.contribute",
                authorization_ref=authorization_ref,
                amount=amount,
                account_id=source_account_id,
            ):
                raise AuthorizationError("valid savings contribution authorization required")
            if source.balance < amount:
                raise InsufficientFundsError("insufficient funds")
            source.balance -= amount
            settlement.balance += amount
            contribution_id = uuid4()
            transaction = TransactionModel(
                id=uuid4(),
                reference=f"SAV-{contribution_id}",
                status=TransactionStatus.COMPLETED,
                amount=amount,
                currency=pot.currency,
                description=f"Savings contribution: {pot.name}",
                category="SAVINGS",
                posted_at=datetime.now(UTC),
            )
            self.session.add(transaction)
            self.session.flush()
            ledger = LedgerService(self.session)
            ledger.post_transfer(
                transaction_id=transaction.id,
                source_account_id=source.id,
                destination_account_id=settlement.id,
                amount=amount,
                currency=pot.currency,
            )
            self.session.flush()
            ledger.verify_transaction_balanced(transaction.id)
            item = SavingsContributionModel(
                id=contribution_id,
                pot_id=pot_id,
                user_id=user_id,
                source_account_id=source_account_id,
                transaction_id=transaction.id,
                amount=amount,
                note=note,
                idempotency_key=idempotency_key,
            )
            self.session.add(item)
            pot.saved_amount += amount
            pot.status = "COMPLETED" if pot.saved_amount >= pot.target_amount else "ACTIVE"
            self.session.add(
                AuditEventModel(
                    id=uuid4(),
                    actor_user_id=user_id,
                    action="savings.contribute",
                    resource_type="savings_pot",
                    resource_id=str(pot_id),
                    trace_id=current_trace_id(),
                    outcome="COMPLETED",
                    details={
                        "source_account_id": str(source_account_id),
                        "transaction_id": str(transaction.id),
                        "amount": str(amount),
                    },
                )
            )
        self.session.refresh(item)
        return item
