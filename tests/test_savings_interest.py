from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from banking_core.app.domain.enums import RiskTier
from banking_core.app.persistence.models import (
    AuditEventModel,
    LedgerEntryModel,
    SavingsInterestPaymentModel,
    UserModel,
)
from banking_core.app.security.approvals import ApprovalService
from banking_core.app.services.errors import ForbiddenError
from banking_core.app.services.savings import SavingsPotService, business_today
from tests.test_savings_security import _accounts, _pot, savings_session  # noqa: F401

DAY0 = date(2026, 10, 1)


@pytest.fixture
def db(savings_session: Session) -> Session:  # noqa: F811 - reuse the savings test database
    return savings_session


def _funded_pot(session: Session, saved: str, since: date = DAY0):
    user, *_ = _accounts(session)
    pot = _pot(session, user.id)
    pot.saved_amount = Decimal(saved)
    pot.interest_accrued_until = since
    session.commit()
    return user, pot


def _payments(session: Session) -> list[SavingsInterestPaymentModel]:
    return list(session.scalars(select(SavingsInterestPaymentModel)))


def test_interest_is_simple_daily_interest_and_carries_sub_cents(db: Session) -> None:
    user, pot = _funded_pot(db, "1000.00")
    paid = SavingsPotService(db).accrue_interest(
        user.id, today=DAY0 + timedelta(days=30)
    )
    db.refresh(pot)
    # 1000 × 1.5% × 30 / 365 = 1.23287671…
    assert paid == Decimal("1.23")
    assert pot.saved_amount == Decimal("1001.23")
    assert pot.interest_earned == Decimal("1.23")
    assert pot.interest_carry == Decimal("0.00287671")
    assert pot.interest_accrued_until == DAY0 + timedelta(days=30)
    [payment] = _payments(db)
    assert (payment.period_start, payment.period_end) == (DAY0, DAY0 + timedelta(days=30))
    assert payment.balance == Decimal("1000.00")
    assert payment.amount == Decimal("1.23")
    audit = db.scalar(
        select(AuditEventModel).where(AuditEventModel.action == "savings.interest")
    )
    assert audit is not None and audit.details["amount"] == "1.23"
    # Value moves from bank equity to the pot inside the same system account: no ledger rows.
    assert db.scalar(select(func.count()).select_from(LedgerEntryModel)) == 0


def test_interest_is_credited_at_most_once_per_day(db: Session) -> None:
    user, pot = _funded_pot(db, "1000.00")
    service = SavingsPotService(db)
    today = DAY0 + timedelta(days=10)
    first = service.accrue_interest(user.id, today=today)
    again = service.accrue_interest(user.id, today=today)
    service.list(user.id, today=today)
    service.get(pot.id, user.id, today=today)
    assert first == Decimal("0.41")
    assert again == Decimal("0.00")
    assert len(_payments(db)) == 1


def test_small_balances_accumulate_until_a_cent_is_due(db: Session) -> None:
    user, pot = _funded_pot(db, "10.00")
    service = SavingsPotService(db)
    for day in range(1, 101):
        service.accrue_interest(user.id, today=DAY0 + timedelta(days=day))
    db.refresh(pot)
    # 10 × 1.5% × 100 / 365 = 0.0411: paid out as four one-cent credits, nothing lost.
    assert pot.interest_earned == Decimal("0.04")
    assert len(_payments(db)) == 4
    assert Decimal("0") < pot.interest_carry < Decimal("0.01")


def test_empty_pot_earns_nothing_but_moves_its_date(db: Session) -> None:
    user, pot = _funded_pot(db, "0.00")
    SavingsPotService(db).accrue_interest(user.id, today=DAY0 + timedelta(days=5))
    db.refresh(pot)
    assert pot.interest_earned == Decimal("0.00")
    assert pot.interest_accrued_until == DAY0 + timedelta(days=5)
    assert _payments(db) == []


def test_deposit_credits_interest_on_the_balance_before_it(db: Session) -> None:
    user, checking, _, _ = _accounts(db)
    _, pot = _funded_pot(db, "1000.00", since=business_today() - timedelta(days=30))
    approval = ApprovalService(db).create_for_operation(
        pot.id,
        user.id,
        operation_type="savings.contribute",
        target_account_id=checking.id,
        amount=Decimal("500.00"),
    )
    grant = ApprovalService(db).decide(approval.id, user.id, True)
    assert grant is not None
    SavingsPotService(db).contribute(
        pot.id,
        user.id,
        source_account_id=checking.id,
        amount=Decimal("500.00"),
        note=None,
        idempotency_key="deposit-after-interest",
        authorization_ref=str(grant.id),
    )
    db.refresh(pot)
    [payment] = _payments(db)
    assert payment.balance == Decimal("1000.00")
    assert pot.saved_amount == Decimal("1501.23")
    assert pot.interest_accrued_until == business_today()


def test_new_pot_starts_today_and_another_user_cannot_read_its_interest(db: Session) -> None:
    user, *_ = _accounts(db)
    pot = _pot(db, user.id)
    assert pot.interest_accrued_until == business_today()
    assert pot.interest_rate == Decimal("0.0150")
    stranger = UserModel(
        id=uuid4(), display_name="Stranger", email="s@example.invalid", risk_tier=RiskTier.GREEN
    )
    db.add(stranger)
    db.commit()
    with pytest.raises(ForbiddenError):
        SavingsPotService(db).list_interest(pot.id, stranger.id)
    assert SavingsPotService(db).list_interest(pot.id, user.id) == []
