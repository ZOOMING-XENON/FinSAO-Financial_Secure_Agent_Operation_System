import os
from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal
from unittest.mock import Mock
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from langgraph.types import Command
from pydantic import BaseModel
from sqlalchemy import create_engine, func, select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from agent.contracts import (
    AgentRequest,
    AgentResponse,
    AgentResponseStatus,
    TrustedAgentContext,
)
from agent.durable import DurableTaskManager, TaskStatus
from agent.graph import postgres_agent_graph
from agent.proactive import ProactiveEventEngine
from agent.service import AgentService
from agent_persistence import SqlAlchemyTaskStore
from agent_tools.contracts import ExecutionContext, ToolResult, ToolResultStatus
from banking_core.app.api.dependencies import get_current_user_id, get_db_session
from banking_core.app.domain.enums import (
    Currency,
    TransactionDirection,
    TransactionKind,
    TransactionOrigin,
    TransferStatus,
)
from banking_core.app.main import app
from banking_core.app.persistence.models import (
    AccountModel,
    AuditEventModel,
    LedgerEntryModel,
    SafetyLockModel,
    TransactionModel,
    TransferDraftModel,
    UserModel,
    WealthHoldingModel,
    WealthProductModel,
)
from banking_core.app.security.approvals import (
    ApprovalService,
    DatabaseTransferAuthorizationVerifier,
    MockMfaProvider,
)
from banking_core.app.security.models import ApprovalStatus
from banking_core.app.security.transfer_authorization import (
    DenyAllTransferAuthorizationVerifier,
    DevelopmentTransferAuthorizationVerifier,
)
from banking_core.app.services.accounts import AccountService
from banking_core.app.services.analytics import BillAnalysisService, SubscriptionService
from banking_core.app.services.cards_wealth import CardService, WealthService
from banking_core.app.services.errors import (
    AuthorizationError,
    ConflictError,
    ForbiddenError,
    InsufficientFundsError,
)
from banking_core.app.services.expense_records import ExpenseRecordService
from banking_core.app.services.expenses import ExpenseFilters, ExpenseService
from banking_core.app.services.ledger import LedgerService
from banking_core.app.services.transaction_history import (
    AccountTransactionFilters,
    TransactionHistoryService,
)
from banking_core.app.services.transfers import TransferService
from scripts.seed_demo_data import seed

DATABASE_TEST_URL = os.getenv("DATABASE_TEST_URL")
pytestmark = pytest.mark.postgres


class _ReceiptFixture(BaseModel):
    status: str = "COMPLETED"


class _CountingGateway:
    def __init__(self) -> None:
        self.calls = 0

    async def execute(
        self, *, tool_name: str, arguments: dict[str, object], context: ExecutionContext
    ) -> ToolResult[BaseModel]:
        del tool_name, arguments, context
        self.calls += 1
        return ToolResult(
            status=ToolResultStatus.SUCCESS,
            data=_ReceiptFixture(),
        )


def require_postgres_url() -> str:
    if not DATABASE_TEST_URL:
        pytest.skip("DATABASE_TEST_URL is not configured")
    if not DATABASE_TEST_URL.startswith(("postgresql+psycopg://", "postgresql://")):
        pytest.fail("DATABASE_TEST_URL must point to PostgreSQL")
    return DATABASE_TEST_URL


@pytest.fixture
def migrated_database(monkeypatch: pytest.MonkeyPatch) -> Generator[str, None, None]:
    url = require_postgres_url()
    monkeypatch.setenv("DATABASE_URL", url)
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", url)
    command.downgrade(config, "base")
    command.upgrade(config, "head")
    yield url
    command.downgrade(config, "base")


def test_migration_and_seed_are_consistent_and_idempotent(migrated_database: str) -> None:
    engine = create_engine(migrated_database)
    with Session(engine) as session, session.begin():
        seed(session)
    with Session(engine) as session, session.begin():
        seed(session)

    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(UserModel)) == 13
        demo_recipients = list(
            session.scalars(
                select(AccountModel).where(
                    AccountModel.account_number.like("299%")
                    | AccountModel.account_number.like("390%")
                )
            )
        )
        assert len(demo_recipients) == 10
        assert {item.name for item in demo_recipients} >= {"爸爸演示收款账户", "妈妈演示收款账户"}
        assert session.scalar(select(func.count()).select_from(TransactionModel)) == 15
        assert session.scalar(select(func.count()).select_from(LedgerEntryModel)) == 30
        for transaction_id in session.scalars(select(TransactionModel.id)):
            debit, credit = session.execute(
                select(
                    func.coalesce(func.sum(LedgerEntryModel.debit), 0),
                    func.coalesce(func.sum(LedgerEntryModel.credit), 0),
                ).where(LedgerEntryModel.transaction_id == transaction_id)
            ).one()
            assert Decimal(debit) == Decimal(credit)


def test_agent_task_store_is_durable_owned_and_monotonic(migrated_database: str) -> None:
    store = SqlAlchemyTaskStore(migrated_database)
    user_id, other_id, session_id, task_id = uuid4(), uuid4(), uuid4(), uuid4()
    request = AgentRequest(session_id=session_id, message="转账草稿")
    context = TrustedAgentContext(
        authenticated_user_id=user_id,
        session_id=session_id,
        task_id=task_id,
        trace_id=uuid4(),
    )
    response = AgentResponse(
        request_id=request.request_id,
        session_id=session_id,
        task_id=task_id,
        status=AgentResponseStatus.WAITING_APPROVAL,
        message="waiting",
        result={"id": str(uuid4())},
    )
    task = store.create_from_response(request=request, context=context, response=response)
    assert task.status == TaskStatus.WAITING_APPROVAL
    assert store.get_task(task_id=task_id, user_id=other_id) is None
    first = store.append_event(task_id=task_id, event_type="ONE", payload={})
    second = store.append_event(task_id=task_id, event_type="TWO", payload={})
    assert (first.sequence, second.sequence) == (1, 2)
    assert store.claim_waiting(task_id=task_id, user_id=user_id) is not None
    assert store.claim_waiting(task_id=task_id, user_id=user_id) is None
    completed = store.transition(
        task_id=task_id,
        user_id=user_id,
        status=TaskStatus.COMPLETED,
        result={"status": "COMPLETED"},
    )
    assert completed.status == TaskStatus.COMPLETED


def test_proactive_events_require_opt_in_and_are_rate_limited(migrated_database: str) -> None:
    store = SqlAlchemyTaskStore(migrated_database)
    engine = ProactiveEventEngine(store)
    user_id = uuid4()
    now = datetime(2026, 10, 26, 12, 0, tzinfo=UTC)
    assert engine.suggest(user_id=user_id, event_kind="BUDGET_THRESHOLD", now=now) is None
    engine.configure(
        user_id=user_id,
        event_kind="BUDGET_THRESHOLD",
        enabled=True,
        quiet_start=time(23, 0),
        quiet_end=time(7, 0),
        minimum_interval_minutes=60,
    )
    suggestion = engine.suggest(user_id=user_id, event_kind="BUDGET_THRESHOLD", now=now)
    assert suggestion is not None
    assert not suggestion.automatic_financial_action
    assert engine.suggest(user_id=user_id, event_kind="BUDGET_THRESHOLD", now=now) is None


@pytest.mark.asyncio
async def test_duplicate_resume_does_not_repeat_commit(migrated_database: str) -> None:
    store = SqlAlchemyTaskStore(migrated_database)
    user_id, session_id, task_id, draft_id = uuid4(), uuid4(), uuid4(), uuid4()
    request = AgentRequest(session_id=session_id, message="转账")
    context = TrustedAgentContext(
        authenticated_user_id=user_id,
        session_id=session_id,
        task_id=task_id,
        trace_id=uuid4(),
    )
    store.create_from_response(
        request=request,
        context=context,
        response=AgentResponse(
            request_id=request.request_id,
            session_id=session_id,
            task_id=task_id,
            status=AgentResponseStatus.WAITING_APPROVAL,
            message="waiting",
            result={"id": str(draft_id)},
        ),
    )
    gateway = _CountingGateway()
    manager = DurableTaskManager(Mock(spec=AgentService), gateway, store)
    first = await manager.resume(
        task_id=task_id, user_id=user_id, authorization_reference="grant-fixture"
    )
    second = await manager.resume(
        task_id=task_id, user_id=user_id, authorization_reference="grant-replay"
    )
    assert first.status == second.status == TaskStatus.COMPLETED
    assert gateway.calls == 1


def test_langgraph_postgres_checkpoint_survives_runtime_restart(migrated_database: str) -> None:
    connection_string = migrated_database.replace("postgresql+psycopg://", "postgresql://")
    thread_id = str(uuid4())
    config = {"configurable": {"thread_id": thread_id}}
    state = {
        "task_id": str(uuid4()),
        "session_id": str(uuid4()),
        "trace_id": str(uuid4()),
        "request_text": "转账",
        "needs_approval": True,
        "approval_preview": {"amount": "800.00"},
    }
    with postgres_agent_graph(connection_string) as graph:
        interrupted = graph.invoke(state, config)
        assert interrupted["status"] == "WAITING_APPROVAL"
    with postgres_agent_graph(connection_string) as restarted_graph:
        resumed = restarted_graph.invoke(
            Command(resume={"authorization_reference": "fixture-grant"}), config
        )
        assert resumed["status"] == "COMPLETED"


def test_phase2_transfer_guarantees(
    migrated_database: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = create_engine(migrated_database)
    with Session(engine) as session, session.begin():
        seed(session)
    with Session(engine) as session:
        users = list(session.scalars(select(UserModel).order_by(UserModel.email)))
        owner, other = users[0], users[1]
        owner_accounts = AccountService(session).get_accounts(owner.id)
        other_accounts = AccountService(session).get_accounts(other.id)
        source, destination = owner_accounts[0], other_accounts[0]
        with pytest.raises(ForbiddenError):
            AccountService(session).get_account(source.id, other.id)

        deny_service = TransferService(session, DenyAllTransferAuthorizationVerifier())
        draft = deny_service.create_transfer_draft(
            user_id=owner.id,
            source_account_id=source.id,
            destination_account_id=destination.id,
            amount=Decimal("25.00"),
            currency=Currency.CNY,
            idempotency_key="phase2-success",
        )
        same = deny_service.create_transfer_draft(
            user_id=owner.id,
            source_account_id=source.id,
            destination_account_id=destination.id,
            amount=Decimal("25.00"),
            currency=Currency.CNY,
            idempotency_key="phase2-success",
        )
        assert same.id == draft.id
        with pytest.raises(ConflictError):
            deny_service.create_transfer_draft(
                user_id=owner.id,
                source_account_id=source.id,
                destination_account_id=destination.id,
                amount=Decimal("26.00"),
                currency=Currency.CNY,
                idempotency_key="phase2-success",
            )
        with pytest.raises(AuthorizationError):
            deny_service.commit_transfer(draft.id, owner.id, "forged")

        before_source, before_destination = source.balance, destination.balance
        verifier = DevelopmentTransferAuthorizationVerifier({(draft.id, owner.id, "test-grant")})
        transaction = TransferService(session, verifier).commit_transfer(
            draft.id, owner.id, "test-grant"
        )
        session.refresh(source)
        session.refresh(destination)
        assert source.balance == before_source - Decimal("25.00")
        assert destination.balance == before_destination + Decimal("25.00")
        completed = session.get(TransferDraftModel, draft.id)
        assert completed is not None and completed.status == TransferStatus.COMPLETED
        assert (
            TransferService(session, verifier).commit_transfer(draft.id, owner.id, "test-grant").id
            == transaction.id
        )
        debit, credit = session.execute(
            select(func.sum(LedgerEntryModel.debit), func.sum(LedgerEntryModel.credit)).where(
                LedgerEntryModel.transaction_id == transaction.id
            )
        ).one()
        assert debit == credit == Decimal("25.00")

        expired_draft = deny_service.create_transfer_draft(
            user_id=owner.id,
            source_account_id=source.id,
            destination_account_id=destination.id,
            amount=Decimal("5.00"),
            currency=Currency.CNY,
            idempotency_key="phase2-expired",
        )
        expired_draft.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        session.commit()
        with pytest.raises(ConflictError, match="expired"):
            TransferService(
                session,
                DevelopmentTransferAuthorizationVerifier(
                    {(expired_draft.id, owner.id, "expired-grant")}
                ),
            ).commit_transfer(expired_draft.id, owner.id, "expired-grant")
        session.refresh(expired_draft)
        assert expired_draft.status == TransferStatus.EXPIRED

        rollback_draft = deny_service.create_transfer_draft(
            user_id=owner.id,
            source_account_id=source.id,
            destination_account_id=destination.id,
            amount=Decimal("10.00"),
            currency=Currency.CNY,
            idempotency_key="phase2-forced-rollback",
        )
        rollback_verifier = DevelopmentTransferAuthorizationVerifier(
            {(rollback_draft.id, owner.id, "rollback-grant")}
        )
        session.refresh(source)
        session.refresh(destination)
        rollback_balances = source.balance, destination.balance

        def fail_posting(*args: object, **kwargs: object) -> None:
            del args, kwargs
            raise RuntimeError("injected ledger failure")

        monkeypatch.setattr(LedgerService, "post_transfer", fail_posting)
        with pytest.raises(RuntimeError, match="injected ledger failure"):
            TransferService(session, rollback_verifier).commit_transfer(
                rollback_draft.id, owner.id, "rollback-grant"
            )
        session.refresh(source)
        session.refresh(destination)
        assert (source.balance, destination.balance) == rollback_balances


def test_concurrent_transfers_cannot_overspend(migrated_database: str) -> None:
    engine = create_engine(migrated_database)
    with Session(engine) as session, session.begin():
        seed(session)
    with Session(engine) as session:
        users = list(session.scalars(select(UserModel).order_by(UserModel.email)))
        owner, recipient = users[0], users[1]
        source = AccountService(session).get_accounts(owner.id)[0]
        destination = AccountService(session).get_accounts(recipient.id)[0]
        initial = source.balance
        owner_id, source_id = owner.id, source.id
        drafts = [
            TransferService(session, DenyAllTransferAuthorizationVerifier()).create_transfer_draft(
                user_id=owner.id,
                source_account_id=source.id,
                destination_account_id=destination.id,
                amount=Decimal("8000.00"),
                currency=Currency.CNY,
                idempotency_key=f"concurrent-{index}",
            )
            for index in range(2)
        ]
        draft_ids = [item.id for item in drafts]

    def commit(draft_id: UUID) -> str:
        with Session(engine) as worker:
            verifier = DevelopmentTransferAuthorizationVerifier(
                {(draft_id, owner_id, f"grant-{draft_id}")}
            )
            try:
                TransferService(worker, verifier).commit_transfer(
                    draft_id, owner_id, f"grant-{draft_id}"
                )
                return "completed"
            except InsufficientFundsError:
                return "insufficient"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(commit, draft_ids))
    assert sorted(results) == ["completed", "insufficient"]
    with Session(engine) as session:
        persisted_source = session.get(AccountModel, source_id)
        assert persisted_source is not None
        assert persisted_source.balance == initial - Decimal("8000.00")


def test_posted_ledger_entries_are_immutable(migrated_database: str) -> None:
    engine = create_engine(migrated_database)
    with Session(engine) as session, session.begin():
        seed(session)
    with Session(engine) as session:
        entry = session.scalars(select(LedgerEntryModel)).first()
        assert entry is not None
        entry.credit = Decimal("999.00")
        with pytest.raises(DBAPIError, match="append-only"):
            session.flush()


def test_security_approval_payload_mfa_and_audit(migrated_database: str) -> None:
    engine = create_engine(migrated_database)
    with Session(engine) as session, session.begin():
        seed(session)
    with Session(engine) as session:
        users = list(session.scalars(select(UserModel).order_by(UserModel.email)))
        owner, recipient = users[0], users[1]
        source = AccountService(session).get_accounts(owner.id)[0]
        destination = AccountService(session).get_accounts(recipient.id)[0]
        draft = TransferService(
            session, DenyAllTransferAuthorizationVerifier()
        ).create_transfer_draft(
            user_id=owner.id,
            source_account_id=source.id,
            destination_account_id=destination.id,
            amount=Decimal("800.00"),
            currency=Currency.CNY,
            idempotency_key="security-yellow",
        )
        approval = ApprovalService(session).create_for_operation(draft.id, owner.id)
        grant = ApprovalService(session).decide(approval.id, owner.id, True)
        assert grant is not None
        TransferService(session, DatabaseTransferAuthorizationVerifier(session)).commit_transfer(
            draft.id, owner.id, str(grant.id)
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(AuditEventModel)
                .where(AuditEventModel.action == "transfer.commit")
            )
            == 1
        )

        tampered = TransferService(
            session, DenyAllTransferAuthorizationVerifier()
        ).create_transfer_draft(
            user_id=owner.id,
            source_account_id=source.id,
            destination_account_id=destination.id,
            amount=Decimal("100.00"),
            currency=Currency.CNY,
            idempotency_key="security-tamper",
        )
        tampered_approval = ApprovalService(session).create_for_operation(tampered.id, owner.id)
        tampered_grant = ApprovalService(session).decide(tampered_approval.id, owner.id, True)
        assert tampered_grant is not None
        tampered.amount = Decimal("101.00")
        session.commit()
        with pytest.raises(AuthorizationError):
            TransferService(
                session, DatabaseTransferAuthorizationVerifier(session)
            ).commit_transfer(tampered.id, owner.id, str(tampered_grant.id))

        red = TransferService(
            session, DenyAllTransferAuthorizationVerifier()
        ).create_transfer_draft(
            user_id=owner.id,
            source_account_id=source.id,
            destination_account_id=destination.id,
            amount=Decimal("1500.00"),
            currency=Currency.CNY,
            idempotency_key="security-red",
        )
        red_approval = ApprovalService(session).create_for_operation(red.id, owner.id)
        with pytest.raises(AuthorizationError):
            ApprovalService(session).decide(red_approval.id, owner.id, True)
        expired_challenge, expired_code = MockMfaProvider(session).create_challenge(
            red_approval.id, owner.id
        )
        expired_challenge.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        session.commit()
        with pytest.raises(AuthorizationError, match="expired"):
            MockMfaProvider(session).verify(expired_challenge.id, owner.id, expired_code)
        challenge, code = MockMfaProvider(session).create_challenge(red_approval.id, owner.id)
        challenge_id = challenge.id
        wrong_code = "999999" if code != "999999" else "888888"
        for _ in range(3):
            with pytest.raises(AuthorizationError):
                MockMfaProvider(session).verify(challenge_id, owner.id, wrong_code)
        lock = session.get(SafetyLockModel, owner.id)
        assert lock is not None and lock.locked_until is not None

        red_approval.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        session.commit()
        expired = ApprovalService(session).get(red_approval.id, owner.id)
        assert expired.status == ApprovalStatus.EXPIRED.value


def test_analytics_cards_and_wealth_integration(migrated_database: str) -> None:
    engine = create_engine(migrated_database)
    with Session(engine) as session, session.begin():
        seed(session)
    with Session(engine) as session:
        owner = session.scalar(
            select(UserModel).where(UserModel.email == "lin.xiaoyu@example.invalid")
        )
        assert owner is not None
        summary = BillAnalysisService(session).monthly_summary(owner.id, 2026, 3)
        assert summary.total == Decimal("142.60")
        subscription = SubscriptionService(session).list(owner.id)[0]
        approval = ApprovalService(session).create_for_operation(subscription.id, owner.id)
        grant = ApprovalService(session).decide(approval.id, owner.id, True)
        assert grant is not None
        cancelled = SubscriptionService(session).cancel(subscription.id, owner.id, str(grant.id))
        assert not cancelled.active and cancelled.status == "CANCELLED"

        card = CardService(session).list(owner.id)[0]
        limit_approval = ApprovalService(session).create_for_operation(
            card.id,
            owner.id,
            operation_type="card.limit",
            amount=Decimal("6000.00"),
        )
        limit_grant = ApprovalService(session).decide(limit_approval.id, owner.id, True)
        assert limit_grant is not None
        with pytest.raises(AuthorizationError):
            CardService(session).update_limit(
                card.id, owner.id, Decimal("6500.00"), str(limit_grant.id)
            )
        assert CardService(session).update_limit(
            card.id, owner.id, Decimal("6000.00"), str(limit_grant.id)
        ).spending_limit == Decimal("6000.00")
        freeze_approval = ApprovalService(session).create_for_operation(
            card.id, owner.id, operation_type="card.freeze"
        )
        freeze_grant = ApprovalService(session).decide(freeze_approval.id, owner.id, True)
        assert freeze_grant is not None
        assert (
            CardService(session)
            .set_frozen(card.id, owner.id, True, str(freeze_grant.id))
            .status.value
            == "FROZEN"
        )
        unfreeze_approval = ApprovalService(session).create_for_operation(
            card.id, owner.id, operation_type="card.unfreeze"
        )
        unfreeze_grant = ApprovalService(session).decide(unfreeze_approval.id, owner.id, True)
        assert unfreeze_grant is not None
        assert (
            CardService(session)
            .set_frozen(card.id, owner.id, False, str(unfreeze_grant.id))
            .status.value
            == "ACTIVE"
        )
        second_freeze_approval = ApprovalService(session).create_for_operation(
            card.id, owner.id, operation_type="card.freeze"
        )
        assert second_freeze_approval.id != freeze_approval.id
        second_freeze_grant = ApprovalService(session).decide(
            second_freeze_approval.id, owner.id, True
        )
        assert second_freeze_grant is not None
        CardService(session).set_frozen(card.id, owner.id, True, str(second_freeze_grant.id))
        card_approval = ApprovalService(session).create_for_operation(card.id, owner.id)
        challenge, code = MockMfaProvider(session).create_challenge(card_approval.id, owner.id)
        card_grant = MockMfaProvider(session).verify(challenge.id, owner.id, code)
        assert (
            CardService(session).report_lost(card.id, owner.id, str(card_grant.id)).status.value
            == "LOST"
        )
        with pytest.raises(ConflictError):
            CardService(session).set_frozen(card.id, owner.id, False, str(unfreeze_grant.id))

        assessment = WealthService(session).assess(owner.id, [5, 5, 5, 5, 5])
        assert assessment.risk_tier.value == "RED"
        product = session.scalar(
            select(WealthProductModel).where(WealthProductModel.code == "DEMO-BOND-01")
        )
        assert product is not None
        account = AccountService(session).get_accounts(owner.id)[0]
        order = WealthService(session).create_order(
            owner.id, account.id, product.id, Decimal("1000.00"), "wealth-integration"
        )
        order_approval = ApprovalService(session).create_for_operation(order.id, owner.id)
        wealth_challenge, wealth_code = MockMfaProvider(session).create_challenge(
            order_approval.id, owner.id
        )
        wealth_grant = MockMfaProvider(session).verify(wealth_challenge.id, owner.id, wealth_code)
        completed = WealthService(session).commit_order(order.id, owner.id, str(wealth_grant.id))
        assert completed.status == "COMPLETED"
        holding = session.scalar(
            select(WealthHoldingModel).where(
                WealthHoldingModel.user_id == owner.id,
                WealthHoldingModel.product_id == product.id,
            )
        )
        assert holding is not None and holding.amount == Decimal("1000.00")

        balance_after_subscription = account.balance
        redemption = WealthService(session).create_redemption_order(
            owner.id,
            account.id,
            product.id,
            Decimal("400.00"),
            "wealth-redemption-integration",
        )
        redemption_approval = ApprovalService(session).create_for_operation(redemption.id, owner.id)
        redemption_challenge, redemption_code = MockMfaProvider(session).create_challenge(
            redemption_approval.id, owner.id
        )
        redemption_grant = MockMfaProvider(session).verify(
            redemption_challenge.id, owner.id, redemption_code
        )
        redeemed = WealthService(session).commit_order(
            redemption.id, owner.id, str(redemption_grant.id)
        )
        session.refresh(account)
        session.refresh(holding)
        assert redeemed.status == "COMPLETED"
        assert holding.amount == Decimal("600.00")
        assert account.balance == balance_after_subscription + Decimal("400.00")


def test_transfer_history_and_manual_expense_activity(migrated_database: str) -> None:
    engine = create_engine(migrated_database)
    with Session(engine) as session, session.begin():
        seed(session)
    with Session(engine) as session:
        owner = session.scalar(
            select(UserModel).where(UserModel.email == "lin.xiaoyu@example.invalid")
        )
        assert owner is not None
        source = session.scalar(
            select(AccountModel).where(
                AccountModel.user_id == owner.id,
                AccountModel.name == "Checking",
            )
        )
        destination = session.scalar(
            select(AccountModel).where(
                AccountModel.user_id != owner.id,
                AccountModel.name == "Checking",
                AccountModel.is_system.is_(False),
            )
        )
        assert source is not None and destination is not None
        draft = TransferService(
            session, DenyAllTransferAuthorizationVerifier()
        ).create_transfer_draft(
            user_id=owner.id,
            source_account_id=source.id,
            destination_account_id=destination.id,
            amount=Decimal("10.00"),
            currency=Currency.CNY,
            idempotency_key="history-transfer",
        )
        verifier = DevelopmentTransferAuthorizationVerifier({(draft.id, owner.id, "grant")})
        TransferService(session, verifier).commit_transfer(draft.id, owner.id, "grant")
        source_history = TransactionHistoryService(session).account_history(
            source.id, owner.id, AccountTransactionFilters()
        )
        destination_history = TransactionHistoryService(session).account_history(
            destination.id, destination.user_id, AccountTransactionFilters()
        )
        assert any(
            item.transaction.kind == TransactionKind.TRANSFER
            and item.direction == TransactionDirection.DEBIT
            for item in source_history
        )
        assert any(
            item.transaction.kind == TransactionKind.TRANSFER
            and item.direction == TransactionDirection.CREDIT
            for item in destination_history
        )
        assert not any(
            item.kind == TransactionKind.TRANSFER
            for item in ExpenseService(session).list(owner.id, ExpenseFilters())
        )

        balance_before = source.balance
        expense = ExpenseRecordService(session).create(
            owner.id,
            amount=Decimal("5.00"),
            currency=Currency.CNY,
            merchant="coke",
            category=None,
            occurred_at=datetime.now(UTC),
            account_id=None,
            origin=TransactionOrigin.CASH,
            idempotency_key="manual-coke",
        )
        assert expense.kind == TransactionKind.EXPENSE
        assert expense.origin == TransactionOrigin.CASH
        session.refresh(source)
        assert source.balance == balance_before
        expenses = ExpenseService(session).list(owner.id, ExpenseFilters())
        assert any(item.id == expense.id for item in expenses)
        summary = ExpenseService(session).summary(owner.id, ExpenseFilters())
        assert summary.totals_by_currency[Currency.CNY.value] >= Decimal("5.00")
        activity = TransactionHistoryService(session).activity(owner.id, 50, 0)
        assert any(
            item.transaction.id == expense.id
            and item.direction == TransactionDirection.DEBIT
            for item in activity
        )


def test_expense_api_create_update_delete_and_activity(migrated_database: str) -> None:
    engine = create_engine(migrated_database)
    with Session(engine) as session, session.begin():
        seed(session)
    with Session(engine) as session:
        owner = session.scalar(
            select(UserModel).where(UserModel.email == "lin.xiaoyu@example.invalid")
        )
        assert owner is not None

    def override_session():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db_session] = override_session
    app.dependency_overrides[get_current_user_id] = lambda: owner.id
    try:
        with TestClient(app) as client:
            created = client.post(
                "/expenses",
                headers={"Idempotency-Key": "api-coke"},
                json={
                    "amount": "5.00",
                    "currency": "CNY",
                    "merchant": "coke",
                    "category": "GROCERIES",
                    "origin": "CASH",
                },
            )
            assert created.status_code == 200, created.text
            payload = created.json()
            assert payload["kind"] == "EXPENSE"
            assert payload["direction"] == "DEBIT"
            expense_id = payload["id"]
            updated = client.patch(
                f"/expenses/{expense_id}", json={"category": "DINING"}
            )
            assert updated.status_code == 200, updated.text
            assert updated.json()["category"] == "DINING"
            activity = client.get("/activity", params={"limit": 100})
            assert activity.status_code == 200
            assert any(item["id"] == expense_id for item in activity.json()["items"])
            listed = client.get("/transactions", params={"limit": 100})
            assert listed.status_code == 200
            assert any(item["id"] == expense_id for item in listed.json()["items"])
            deleted = client.delete(f"/expenses/{expense_id}")
            assert deleted.status_code == 204
            after = client.get("/activity", params={"limit": 100})
            assert not any(item["id"] == expense_id for item in after.json()["items"])
    finally:
        app.dependency_overrides.clear()
