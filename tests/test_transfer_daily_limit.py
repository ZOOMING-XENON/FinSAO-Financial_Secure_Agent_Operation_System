from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session

from banking_core.app.domain.enums import (
    AccountStatus,
    Currency,
    RiskTier,
    TransferStatus,
)
from banking_core.app.persistence.models import (
    AccountModel,
    AuditEventModel,
    Base,
    TransferDraftModel,
    UserModel,
)
from banking_core.app.security.policy import PolicyEngine
from banking_core.app.security.transfer_authorization import (
    DenyAllTransferAuthorizationVerifier,
)
from banking_core.app.services.errors import ConflictError, ForbiddenError
from banking_core.app.services.transfers import TransferService

# 14:00 in Shanghai on 2 November 2026.
NOW = datetime(2026, 11, 2, 6, 0, tzinfo=UTC)


@pytest.fixture
def db() -> Session:
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
            display_name="Payer",
            email="payer@example.invalid",
            risk_tier=RiskTier.GREEN,
        )
        session.add(user)
        for number in ("SRC-1", "DST-1"):
            session.add(
                AccountModel(
                    id=uuid4(),
                    user_id=user.id,
                    account_number=number,
                    name=number,
                    currency=Currency.CNY,
                    status=AccountStatus.ACTIVE,
                    balance=Decimal("5000.00"),
                    is_system=False,
                )
            )
        session.commit()
        yield session


def _user_and_accounts(db: Session) -> tuple[UserModel, AccountModel, AccountModel]:
    user = db.scalar(select(UserModel))
    src, dst = db.scalars(select(AccountModel).order_by(AccountModel.account_number.desc()))
    assert user is not None
    return user, src, dst


def _draft(db: Session, amount: str, status: TransferStatus, expires_in_minutes: int) -> UUID:
    user, src, dst = _user_and_accounts(db)
    draft = TransferDraftModel(
        id=uuid4(),
        user_id=user.id,
        source_account_id=src.id,
        destination_account_id=dst.id,
        amount=Decimal(amount),
        currency=Currency.CNY,
        status=status,
        expires_at=NOW + timedelta(minutes=expires_in_minutes),
        created_at=NOW - timedelta(minutes=30),
        updated_at=NOW - timedelta(minutes=30),
    )
    db.add(draft)
    db.commit()
    return draft.id


def test_abandoned_expired_drafts_do_not_count_towards_the_daily_limit(db: Session) -> None:
    user, *_ = _user_and_accounts(db)
    _draft(db, "800.00", TransferStatus.PENDING_AUTHORIZATION, expires_in_minutes=-15)
    _draft(db, "300.00", TransferStatus.PENDING_AUTHORIZATION, expires_in_minutes=10)
    _draft(db, "250.00", TransferStatus.COMPLETED, expires_in_minutes=-15)
    _draft(db, "999.00", TransferStatus.CANCELLED, expires_in_minutes=10)
    # Only the live draft (300) and the completed transfer (250) count: 550, so still YELLOW.
    assert PolicyEngine(db).daily_outgoing(user.id, now=NOW) == Decimal("550.00")


def test_live_drafts_still_reserve_their_amount(db: Session) -> None:
    user, *_ = _user_and_accounts(db)
    _draft(db, "800.00", TransferStatus.PENDING_AUTHORIZATION, expires_in_minutes=10)
    _draft(db, "300.00", TransferStatus.AUTHORIZED, expires_in_minutes=10)
    assert PolicyEngine(db).daily_outgoing(user.id, now=NOW) == Decimal("1100.00")


def test_cancel_frees_the_reservation_and_is_audited(db: Session) -> None:
    user, *_ = _user_and_accounts(db)
    draft_id = _draft(db, "800.00", TransferStatus.PENDING_AUTHORIZATION, expires_in_minutes=10)
    service = TransferService(db, DenyAllTransferAuthorizationVerifier())
    cancelled = service.cancel_transfer(draft_id, user.id)
    again = service.cancel_transfer(draft_id, user.id)
    assert cancelled.status == again.status == TransferStatus.CANCELLED
    assert PolicyEngine(db).daily_outgoing(user.id, now=NOW) == Decimal("0")
    events = list(
        db.scalars(select(AuditEventModel).where(AuditEventModel.action == "transfer.cancel"))
    )
    assert len(events) == 1


def test_cancel_rejects_other_users_and_completed_transfers(db: Session) -> None:
    user, *_ = _user_and_accounts(db)
    service = TransferService(db, DenyAllTransferAuthorizationVerifier())
    pending = _draft(db, "100.00", TransferStatus.PENDING_AUTHORIZATION, expires_in_minutes=10)
    with pytest.raises(ForbiddenError):
        service.cancel_transfer(pending, uuid4())
    done = _draft(db, "100.00", TransferStatus.COMPLETED, expires_in_minutes=10)
    with pytest.raises(ConflictError):
        service.cancel_transfer(done, user.id)


def test_activity_shows_transfers_to_others_as_money_out(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    import banking_core.app.services.transfers as transfers_module

    class NaiveClock(datetime):
        # SQLite drops time zones; keep the commit path's clock naive UTC to match.
        @classmethod
        def now(cls, tz: object = None) -> datetime:  # type: ignore[override]
            return datetime.utcnow()

    monkeypatch.setattr(transfers_module, "datetime", NaiveClock)
    from banking_core.app.domain.enums import TransactionDirection
    from banking_core.app.security.transfer_authorization import (
        DevelopmentTransferAuthorizationVerifier,
    )
    from banking_core.app.services.transaction_history import TransactionHistoryService

    user, src, own = _user_and_accounts(db)
    friend = UserModel(
        id=uuid4(), display_name="Friend", email="friend@example.invalid", risk_tier=RiskTier.GREEN
    )
    friend_account = AccountModel(
        id=uuid4(),
        user_id=friend.id,
        account_number="FRIEND-1",
        name="Friend",
        currency=Currency.CNY,
        status=AccountStatus.ACTIVE,
        balance=Decimal("0.00"),
        is_system=False,
    )
    db.add_all([friend, friend_account])
    db.commit()

    def send(destination: UUID, key: str) -> UUID:
        draft = TransferService(db, DenyAllTransferAuthorizationVerifier()).create_transfer_draft(
            user_id=user.id,
            source_account_id=src.id,
            destination_account_id=destination,
            amount=Decimal("20.00"),
            currency=Currency.CNY,
            idempotency_key=key,
        )
        verifier = DevelopmentTransferAuthorizationVerifier({(draft.id, user.id, "ok")})
        return TransferService(db, verifier).commit_transfer(draft.id, user.id, "ok").id

    to_friend = send(friend_account.id, "to-friend")
    to_self = send(own.id, "to-self")
    activity = {
        i.transaction.id: i.direction
        for i in TransactionHistoryService(db).activity(user.id, 50, 0)
    }
    friend_view = {
        i.transaction.id: i.direction
        for i in TransactionHistoryService(db).activity(friend.id, 50, 0)
    }
    system = AccountModel(
        id=uuid4(),
        user_id=None,
        account_number="SYS-1",
        name="Settlement",
        currency=Currency.CNY,
        status=AccountStatus.ACTIVE,
        balance=Decimal("0.00"),
        is_system=True,
    )
    db.add(system)
    db.commit()
    to_pot = send(system.id, "to-pot")
    activity = {
        i.transaction.id: i.direction
        for i in TransactionHistoryService(db).activity(user.id, 50, 0)
    }
    assert activity[to_pot] == TransactionDirection.MOVE
    assert activity[to_friend] == TransactionDirection.DEBIT
    assert activity[to_self] == TransactionDirection.MOVE
    assert friend_view[to_friend] == TransactionDirection.CREDIT
