from collections.abc import Sequence
from datetime import UTC, date, datetime
from decimal import ROUND_DOWN, Decimal
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from banking_core.app.config import get_settings
from banking_core.app.domain.enums import (
    AccountStatus,
    Currency,
    TransactionKind,
    TransactionOrigin,
    TransactionStatus,
)
from banking_core.app.domain.money import quantize_money
from banking_core.app.persistence.models import (
    AccountModel,
    AuditEventModel,
    SavingsContributionModel,
    SavingsInterestPaymentModel,
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

BUSINESS_TZ = ZoneInfo("Asia/Shanghai")
CENT = Decimal("0.01")
CARRY = Decimal("0.00000001")
DAYS_PER_YEAR = Decimal(365)


def business_today() -> date:
    return datetime.now(BUSINESS_TZ).date()


def accrue_pot_interest(session: Session, pot: SavingsPotModel, today: date) -> Decimal:
    """Credit simple daily interest on the pot's balance up to (not including) today.

    Interest is worked out on whole business days at the pot's annual rate (365-day year).
    Sub-cent amounts are carried in ``interest_carry`` and paid once they reach a cent, so
    nothing is lost to rounding. Callers run this before any balance change, which makes each
    day's interest use the balance the pot really had that day.

    Pot money is held in the system settlement account, which is also the bank's equity
    account. Paying interest therefore moves value from bank equity to the customer's pot
    inside that same account: the pot balance grows, the account balance does not change, and
    no ledger posting is needed. Each credit is recorded as a payment row and an audit event.
    Returns the amount paid now (0.00 if none).
    """
    start = pot.interest_accrued_until or pot.created_at.astimezone(BUSINESS_TZ).date()
    days = (today - start).days
    if days <= 0:
        return Decimal("0.00")
    balance = pot.saved_amount
    accrued = pot.interest_carry + balance * pot.interest_rate * days / DAYS_PER_YEAR
    paid = accrued.quantize(CENT, rounding=ROUND_DOWN)
    pot.interest_carry = (accrued - paid).quantize(CARRY, rounding=ROUND_DOWN)
    pot.interest_accrued_until = today
    if paid <= 0:
        return Decimal("0.00")
    pot.saved_amount += paid
    pot.interest_earned += paid
    pot.status = "COMPLETED" if pot.saved_amount >= pot.target_amount else "ACTIVE"
    session.add(
        SavingsInterestPaymentModel(
            id=uuid4(),
            pot_id=pot.id,
            user_id=pot.user_id,
            period_start=start,
            period_end=today,
            rate=pot.interest_rate,
            balance=balance,
            amount=paid,
        )
    )
    session.add(
        AuditEventModel(
            id=uuid4(),
            actor_user_id=pot.user_id,
            action="savings.interest",
            resource_type="savings_pot",
            resource_id=str(pot.id),
            trace_id=current_trace_id(),
            outcome="COMPLETED",
            details={
                "period_start": start.isoformat(),
                "period_end": today.isoformat(),
                "rate": str(pot.interest_rate),
                "balance": str(balance),
                "amount": str(paid),
            },
        )
    )
    return paid


class SavingsPotService:
    """Account-funded savings goals with authorized, ledger-backed contributions."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def list(self, user_id: UUID, *, today: date | None = None) -> list[SavingsPotModel]:
        self.accrue_interest(user_id, today=today)
        return list(
            self.session.scalars(
                select(SavingsPotModel)
                .where(SavingsPotModel.user_id == user_id)
                .order_by(SavingsPotModel.created_at, SavingsPotModel.id)
            )
        )

    def get(self, pot_id: UUID, user_id: UUID, *, today: date | None = None) -> SavingsPotModel:
        pot = self._owned(pot_id, user_id)
        self.accrue_interest(user_id, today=today, pot_id=pot_id)
        self.session.refresh(pot)
        return pot

    def _owned(self, pot_id: UUID, user_id: UUID) -> SavingsPotModel:
        pot = self.session.get(SavingsPotModel, pot_id)
        if pot is None:
            raise NotFoundError("savings pot not found")
        if pot.user_id != user_id:
            raise ForbiddenError("savings pot belongs to another user")
        return pot

    def accrue_interest(
        self, user_id: UUID, *, today: date | None = None, pot_id: UUID | None = None
    ) -> Decimal:
        """Bring the user's pots (or one pot) up to date with interest. Safe to call repeatedly:
        a pot is credited at most once per business day."""
        today = today or business_today()
        query = select(SavingsPotModel).where(
            SavingsPotModel.user_id == user_id,
            (SavingsPotModel.interest_accrued_until.is_(None))
            | (SavingsPotModel.interest_accrued_until < today),
        )
        if pot_id is not None:
            query = query.where(SavingsPotModel.id == pot_id)
        if self.session.in_transaction():
            self.session.commit()
        total = Decimal("0.00")
        with self.session.begin():
            for pot in self.session.scalars(query.order_by(SavingsPotModel.id).with_for_update()):
                total += accrue_pot_interest(self.session, pot, today)
        return total

    def list_interest(self, pot_id: UUID, user_id: UUID) -> Sequence[SavingsInterestPaymentModel]:
        self.get(pot_id, user_id)
        return list(
            self.session.scalars(
                select(SavingsInterestPaymentModel)
                .where(SavingsInterestPaymentModel.pot_id == pot_id)
                .order_by(
                    SavingsInterestPaymentModel.period_end.desc(), SavingsInterestPaymentModel.id
                )
            )
        )

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
            interest_rate=get_settings().savings_interest_rate,
            interest_accrued_until=business_today(),
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
            # Interest up to today is earned on the balance before this deposit.
            accrue_pot_interest(self.session, pot, business_today())
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
                user_id=user_id,
                account_id=source.id,
                reference=f"SAV-{contribution_id}",
                status=TransactionStatus.COMPLETED,
                kind=TransactionKind.TRANSFER,
                origin=TransactionOrigin.BANK,
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
