from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session

from banking_core.app.domain.enums import AccountStatus, Currency, RiskTier
from banking_core.app.persistence.models import (
    AccountModel,
    Base,
    LedgerEntryModel,
    SavingsContributionModel,
    UserModel,
)
from banking_core.app.security.approvals import ApprovalService, MockMfaProvider
from banking_core.app.services.errors import AuthorizationError, ConflictError
from banking_core.app.services.savings import SavingsPotService


@pytest.fixture
def savings_session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    event.listen(
        engine,
        "connect",
        lambda connection, _: connection.create_function("char_length", 1, len),
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        user = UserModel(
            id=uuid4(),
            display_name="Savings Owner",
            email="savings-owner@example.invalid",
            risk_tier=RiskTier.GREEN,
        )
        session.add_all(
            [
                user,
                AccountModel(
                    id=uuid4(),
                    user_id=user.id,
                    account_number="CHECKING-001",
                    name="Checking",
                    currency=Currency.CNY,
                    status=AccountStatus.ACTIVE,
                    balance=Decimal("5000.00"),
                    is_system=False,
                ),
                AccountModel(
                    id=uuid4(),
                    user_id=user.id,
                    account_number="SAVINGS-001",
                    name="Savings",
                    currency=Currency.CNY,
                    status=AccountStatus.ACTIVE,
                    balance=Decimal("3000.00"),
                    is_system=False,
                ),
                AccountModel(
                    id=uuid4(),
                    user_id=None,
                    account_number="SYSTEM-SAVINGS",
                    name="Savings settlement",
                    currency=Currency.CNY,
                    status=AccountStatus.ACTIVE,
                    balance=Decimal("0.00"),
                    is_system=True,
                ),
            ]
        )
        session.commit()
        yield session


def _accounts(session: Session) -> tuple[UserModel, AccountModel, AccountModel, AccountModel]:
    user = session.scalar(select(UserModel))
    assert user is not None
    owned = list(
        session.scalars(
            select(AccountModel)
            .where(AccountModel.user_id == user.id)
            .order_by(AccountModel.account_number)
        )
    )
    system = session.scalar(select(AccountModel).where(AccountModel.is_system.is_(True)))
    assert system is not None
    return user, owned[0], owned[1], system


def _pot(session: Session, user_id):
    return SavingsPotService(session).create(
        user_id,
        name="Emergency fund",
        target_amount=Decimal("5000.00"),
        currency=Currency.CNY,
        target_date=date(2027, 1, 1),
        idempotency_key="pot-1",
    )


def test_contribution_debits_account_posts_ledger_and_is_idempotent(
    savings_session: Session,
) -> None:
    user, checking, _, settlement = _accounts(savings_session)
    pot = _pot(savings_session, user.id)
    approval = ApprovalService(savings_session).create_for_operation(
        pot.id,
        user.id,
        operation_type="savings.contribute",
        target_account_id=checking.id,
        amount=Decimal("800.00"),
    )
    assert approval.risk_tier == RiskTier.YELLOW
    grant = ApprovalService(savings_session).decide(approval.id, user.id, True)
    assert grant is not None

    contribution = SavingsPotService(savings_session).contribute(
        pot.id,
        user.id,
        source_account_id=checking.id,
        amount=Decimal("800.00"),
        note="first deposit",
        idempotency_key="contribution-1",
        authorization_ref=str(grant.id),
    )
    savings_session.refresh(checking)
    savings_session.refresh(settlement)
    savings_session.refresh(pot)
    assert checking.balance == Decimal("4200.00")
    assert settlement.balance == Decimal("800.00")
    assert pot.saved_amount == Decimal("800.00")
    assert contribution.source_account_id == checking.id
    assert contribution.transaction_id is not None
    assert savings_session.scalar(
        select(func.count())
        .select_from(LedgerEntryModel)
        .where(LedgerEntryModel.transaction_id == contribution.transaction_id)
    ) == 2

    replay = SavingsPotService(savings_session).contribute(
        pot.id,
        user.id,
        source_account_id=checking.id,
        amount=Decimal("800.00"),
        note="first deposit",
        idempotency_key="contribution-1",
        authorization_ref=str(grant.id),
    )
    savings_session.refresh(checking)
    assert replay.id == contribution.id
    assert checking.balance == Decimal("4200.00")
    assert savings_session.scalar(select(func.count()).select_from(SavingsContributionModel)) == 1


def test_large_contribution_requires_mfa_and_authorization_is_payload_bound(
    savings_session: Session,
) -> None:
    user, checking, savings, _ = _accounts(savings_session)
    pot = _pot(savings_session, user.id)
    approval = ApprovalService(savings_session).create_for_operation(
        pot.id,
        user.id,
        operation_type="savings.contribute",
        target_account_id=checking.id,
        amount=Decimal("1500.00"),
    )
    assert approval.risk_tier == RiskTier.RED
    with pytest.raises(AuthorizationError, match="MFA"):
        ApprovalService(savings_session).decide(approval.id, user.id, True)

    challenge, code = MockMfaProvider(savings_session, "123456").create_challenge(
        approval.id, user.id
    )
    grant = MockMfaProvider(savings_session, "123456").verify(challenge.id, user.id, code)
    with pytest.raises(AuthorizationError):
        SavingsPotService(savings_session).contribute(
            pot.id,
            user.id,
            source_account_id=savings.id,
            amount=Decimal("1500.00"),
            note=None,
            idempotency_key="wrong-account",
            authorization_ref=str(grant.id),
        )
    savings_session.refresh(checking)
    savings_session.refresh(savings)
    assert checking.balance == Decimal("5000.00")
    assert savings.balance == Decimal("3000.00")

    SavingsPotService(savings_session).contribute(
        pot.id,
        user.id,
        source_account_id=checking.id,
        amount=Decimal("1500.00"),
        note=None,
        idempotency_key="large-contribution",
        authorization_ref=str(grant.id),
    )
    savings_session.refresh(checking)
    assert checking.balance == Decimal("3500.00")

    with pytest.raises(ConflictError, match="funded"):
        SavingsPotService(savings_session).delete(pot.id, user.id)
