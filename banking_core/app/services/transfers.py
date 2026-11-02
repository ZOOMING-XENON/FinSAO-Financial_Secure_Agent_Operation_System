import hashlib
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from banking_core.app.domain.enums import (
    AccountStatus,
    Currency,
    TransactionKind,
    TransactionOrigin,
    TransactionStatus,
    TransferStatus,
)
from banking_core.app.domain.money import quantize_money
from banking_core.app.persistence.models import (
    AccountModel,
    AuditEventModel,
    TransactionModel,
    TransferDraftModel,
)
from banking_core.app.security.transfer_authorization import TransferAuthorizationVerifier
from banking_core.app.services.errors import (
    AuthorizationError,
    ConflictError,
    ForbiddenError,
    InsufficientFundsError,
    NotFoundError,
    ValidationError,
)
from banking_core.app.services.ledger import LedgerService
from shared.tracing import current_trace_id

ALLOWED_TRANSITIONS: dict[TransferStatus, set[TransferStatus]] = {
    TransferStatus.DRAFT: {
        TransferStatus.PENDING_AUTHORIZATION,
        TransferStatus.CANCELLED,
        TransferStatus.EXPIRED,
    },
    TransferStatus.PENDING_AUTHORIZATION: {
        TransferStatus.AUTHORIZED,
        TransferStatus.CANCELLED,
        TransferStatus.EXPIRED,
    },
    TransferStatus.AUTHORIZED: {TransferStatus.PROCESSING, TransferStatus.EXPIRED},
    TransferStatus.PROCESSING: {TransferStatus.COMPLETED, TransferStatus.FAILED},
    TransferStatus.COMPLETED: set(),
    TransferStatus.FAILED: set(),
    TransferStatus.CANCELLED: set(),
    TransferStatus.EXPIRED: set(),
}


def transition(draft: TransferDraftModel, target: TransferStatus) -> None:
    if target not in ALLOWED_TRANSITIONS[draft.status]:
        raise ConflictError(f"invalid transfer transition: {draft.status} -> {target}")
    draft.status = target


def request_hash(source: UUID, destination: UUID, amount: Decimal, currency: Currency) -> str:
    payload = json.dumps(
        {
            "source": str(source),
            "destination": str(destination),
            "amount": str(amount),
            "currency": currency.value,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode()).hexdigest()


class TransferService:
    def __init__(self, session: Session, verifier: TransferAuthorizationVerifier) -> None:
        self.session = session
        self.verifier = verifier

    def create_transfer_draft(
        self,
        *,
        user_id: UUID,
        source_account_id: UUID,
        destination_account_id: UUID,
        amount: Decimal,
        currency: Currency,
        idempotency_key: str,
    ) -> TransferDraftModel:
        amount = quantize_money(amount)
        if amount <= 0 or source_account_id == destination_account_id:
            raise ValidationError("invalid transfer")
        digest = request_hash(source_account_id, destination_account_id, amount, currency)
        existing = self.session.scalar(
            select(TransferDraftModel).where(
                TransferDraftModel.user_id == user_id,
                TransferDraftModel.idempotency_key == idempotency_key,
            )
        )
        if existing is not None:
            if existing.request_hash != digest:
                raise ConflictError("idempotency key reused with different payload")
            return existing
        source = self.session.get(AccountModel, source_account_id)
        destination = self.session.get(AccountModel, destination_account_id)
        if source is None or destination is None:
            raise NotFoundError("account not found")
        if source.user_id != user_id:
            raise ForbiddenError("source account belongs to another user")
        if source.currency != currency or destination.currency != currency:
            raise ValidationError("currency mismatch")
        draft = TransferDraftModel(
            id=uuid4(),
            user_id=user_id,
            source_account_id=source_account_id,
            destination_account_id=destination_account_id,
            amount=amount,
            currency=currency,
            status=TransferStatus.DRAFT,
            idempotency_key=idempotency_key,
            request_hash=digest,
            expires_at=datetime.now(UTC) + timedelta(minutes=15),
        )
        transition(draft, TransferStatus.PENDING_AUTHORIZATION)
        self.session.add(draft)
        try:
            self.session.commit()
        except IntegrityError:
            self.session.rollback()
            concurrent = self.session.scalar(
                select(TransferDraftModel).where(
                    TransferDraftModel.user_id == user_id,
                    TransferDraftModel.idempotency_key == idempotency_key,
                )
            )
            if concurrent is None or concurrent.request_hash != digest:
                raise ConflictError("idempotency key conflict") from None
            return concurrent
        return draft

    def get_transfer_draft(self, draft_id: UUID, user_id: UUID) -> TransferDraftModel:
        draft = self.session.get(TransferDraftModel, draft_id)
        if draft is None:
            raise NotFoundError("transfer draft not found")
        if draft.user_id != user_id:
            raise ForbiddenError("transfer belongs to another user")
        return draft

    def commit_transfer(
        self, draft_id: UUID, user_id: UUID, authorization_ref: str
    ) -> TransactionModel:
        if self.session.in_transaction():
            self.session.rollback()
        with self.session.begin():
            draft = self.session.scalar(
                select(TransferDraftModel)
                .where(TransferDraftModel.id == draft_id)
                .with_for_update()
            )
            if draft is None:
                raise NotFoundError("transfer draft not found")
            if draft.user_id != user_id:
                raise ForbiddenError("transfer belongs to another user")
            if draft.status == TransferStatus.COMPLETED and draft.transaction_id is not None:
                transaction = self.session.get(TransactionModel, draft.transaction_id)
                if transaction is None:
                    raise ConflictError("completed transfer is missing its transaction")
                return transaction
            if datetime.now(UTC) >= draft.expires_at:
                transition(draft, TransferStatus.EXPIRED)
            else:
                return self._commit_locked(draft, user_id, authorization_ref)
        raise ConflictError("transfer draft expired")

    def _commit_locked(
        self, draft: TransferDraftModel, user_id: UUID, authorization_ref: str
    ) -> TransactionModel:
        if not self.verifier.verify(draft, user_id, authorization_ref):
            raise AuthorizationError("valid transfer authorization required")
        transition(draft, TransferStatus.AUTHORIZED)
        transition(draft, TransferStatus.PROCESSING)
        account_ids = sorted([draft.source_account_id, draft.destination_account_id], key=str)
        locked = list(
            self.session.scalars(
                select(AccountModel)
                .where(AccountModel.id.in_(account_ids))
                .order_by(AccountModel.id)
                .with_for_update()
            )
        )
        accounts = {account.id: account for account in locked}
        source, destination = (
            accounts[draft.source_account_id],
            accounts[draft.destination_account_id],
        )
        if source.user_id != user_id or source.status != AccountStatus.ACTIVE:
            raise ForbiddenError("source account is not available")
        if destination.status != AccountStatus.ACTIVE:
            raise ConflictError("destination account is not available")
        if source.balance < draft.amount:
            raise InsufficientFundsError("insufficient funds")
        source.balance -= draft.amount
        destination.balance += draft.amount
        transaction = TransactionModel(
            id=uuid4(),
            user_id=user_id,
            account_id=source.id,
            reference=f"TRF-{draft.id}",
            status=TransactionStatus.COMPLETED,
            kind=TransactionKind.TRANSFER,
            origin=TransactionOrigin.BANK,
            amount=draft.amount,
            currency=draft.currency,
            description="Account transfer",
            category="INTERNAL_TRANSFER",
            posted_at=datetime.now(UTC),
        )
        self.session.add(transaction)
        self.session.flush()
        ledger = LedgerService(self.session)
        ledger.post_transfer(
            transaction_id=transaction.id,
            source_account_id=source.id,
            destination_account_id=destination.id,
            amount=draft.amount,
            currency=draft.currency,
        )
        self.session.flush()
        ledger.verify_transaction_balanced(transaction.id)
        draft.transaction_id = transaction.id
        transition(draft, TransferStatus.COMPLETED)
        self.session.add(
            AuditEventModel(
                id=uuid4(),
                actor_user_id=user_id,
                action="transfer.commit",
                resource_type="transfer",
                resource_id=str(draft.id),
                trace_id=current_trace_id(),
                outcome="COMPLETED",
                details={"transaction_id": str(transaction.id)},
            )
        )
        return transaction

    def cancel_transfer(self, draft_id: UUID, user_id: UUID) -> TransferDraftModel:
        """Cancel a transfer the user decided not to send, so it no longer reserves part of
        the daily limit. Only drafts that have not been authorized can be cancelled; doing it
        twice is harmless."""
        if self.session.in_transaction():
            self.session.rollback()
        with self.session.begin():
            draft = self.session.scalar(
                select(TransferDraftModel)
                .where(TransferDraftModel.id == draft_id)
                .with_for_update()
            )
            if draft is None:
                raise NotFoundError("transfer draft not found")
            if draft.user_id != user_id:
                raise ForbiddenError("transfer belongs to another user")
            if draft.status != TransferStatus.CANCELLED:
                transition(draft, TransferStatus.CANCELLED)
                self.session.add(
                    AuditEventModel(
                        id=uuid4(),
                        actor_user_id=user_id,
                        action="transfer.cancel",
                        resource_type="transfer_draft",
                        resource_id=str(draft.id),
                        trace_id=current_trace_id(),
                        outcome="CANCELLED",
                        details={"amount": str(draft.amount)},
                    )
                )
        self.session.refresh(draft)
        return draft

    def get_transfer_status(self, transfer_id: UUID, user_id: UUID) -> TransferDraftModel:
        draft = self.session.scalar(
            select(TransferDraftModel).where(
                (TransferDraftModel.id == transfer_id)
                | (TransferDraftModel.transaction_id == transfer_id)
            )
        )
        if draft is None:
            raise NotFoundError("transfer not found")
        if draft.user_id != user_id:
            raise ForbiddenError("transfer belongs to another user")
        return draft
