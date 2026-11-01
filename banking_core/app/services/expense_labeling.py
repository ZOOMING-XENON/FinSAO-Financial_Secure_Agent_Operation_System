from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from banking_core.app.domain.enums import TransactionKind, TransactionStatus
from banking_core.app.persistence.models import ExpenseLabelAttemptModel, TransactionModel
from banking_core.app.services.errors import ConflictError, ForbiddenError, NotFoundError
from shared.expense_taxonomy import normalize_category

PRECEDENCE = {"USER": 3, "RULE": 2, "JEV": 1}
LABEL_POLICY_VERSION = "jev-label-v1"
LEASE_DURATION = timedelta(minutes=5)
MAX_ATTEMPTS = 5


@dataclass(frozen=True)
class LabelWrite:
    category: str
    source: str
    observed_source: str | None
    observed_version: str | None
    version: str


@dataclass(frozen=True)
class LabelAttempt:
    policy_version: str
    succeeded: bool
    error: str | None = None


class ExpenseLabelingService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def pending(self, user_id: UUID, *, limit: int = 50) -> list[TransactionModel]:
        now = datetime.now(UTC)
        transactions = list(
            self.session.scalars(
                select(TransactionModel)
                .outerjoin(
                    ExpenseLabelAttemptModel,
                    and_(
                        ExpenseLabelAttemptModel.transaction_id == TransactionModel.id,
                        ExpenseLabelAttemptModel.policy_version == LABEL_POLICY_VERSION,
                    ),
                )
                .where(
                    TransactionModel.user_id == user_id,
                    TransactionModel.kind == TransactionKind.EXPENSE,
                    TransactionModel.status == TransactionStatus.COMPLETED,
                    TransactionModel.deleted_at.is_(None),
                    or_(
                        TransactionModel.category_source.is_(None),
                        and_(
                            TransactionModel.category_source == "RULE",
                            or_(
                                TransactionModel.category.is_(None),
                                TransactionModel.category == "UNKNOWN",
                            ),
                        ),
                    ),
                    or_(
                        ExpenseLabelAttemptModel.id.is_(None),
                        ExpenseLabelAttemptModel.status == "PENDING",
                        and_(
                            ExpenseLabelAttemptModel.status == "RETRY",
                            ExpenseLabelAttemptModel.next_attempt_at <= now,
                        ),
                        and_(
                            ExpenseLabelAttemptModel.status == "IN_PROGRESS",
                            ExpenseLabelAttemptModel.lease_until <= now,
                        ),
                    ),
                )
                .order_by(TransactionModel.posted_at.desc())
                .limit(limit)
            )
        )
        claimed: list[TransactionModel] = []
        for candidate in transactions:
            transaction = self.session.scalar(
                select(TransactionModel)
                .where(TransactionModel.id == candidate.id)
                .with_for_update()
            )
            if transaction is None or transaction.deleted_at is not None:
                continue
            if transaction.category_source == "USER":
                continue
            if transaction.category_source == "RULE" and transaction.category not in {
                None,
                "UNKNOWN",
            }:
                continue
            if transaction.category_source not in {None, "RULE"}:
                continue
            attempt = self.session.scalar(
                select(ExpenseLabelAttemptModel)
                .where(
                    ExpenseLabelAttemptModel.transaction_id == transaction.id,
                    ExpenseLabelAttemptModel.policy_version == LABEL_POLICY_VERSION,
                )
                .with_for_update()
            )
            if attempt is not None and (
                attempt.status == "SUCCEEDED"
                or (
                    attempt.status == "RETRY"
                    and attempt.next_attempt_at is not None
                    and attempt.next_attempt_at > now
                )
                or (
                    attempt.status == "IN_PROGRESS"
                    and attempt.lease_until is not None
                    and attempt.lease_until > now
                )
            ):
                continue
            if attempt is None:
                attempt = ExpenseLabelAttemptModel(
                    transaction_id=transaction.id,
                    policy_version=LABEL_POLICY_VERSION,
                )
                self.session.add(attempt)
            attempt.status = "IN_PROGRESS"
            attempt.lease_until = now + LEASE_DURATION
            claimed.append(transaction)
        self.session.commit()
        return claimed

    def record_attempt(
        self, transaction_id: UUID, user_id: UUID, attempt: LabelAttempt
    ) -> ExpenseLabelAttemptModel:
        transaction = self.session.scalar(
            select(TransactionModel).where(
                TransactionModel.id == transaction_id,
                TransactionModel.user_id == user_id,
                TransactionModel.kind == TransactionKind.EXPENSE,
                TransactionModel.deleted_at.is_(None),
            )
        )
        if transaction is None:
            raise NotFoundError("transaction not found")
        if attempt.policy_version != LABEL_POLICY_VERSION:
            raise ForbiddenError("unsupported labeling policy")
        if attempt.succeeded and (
            transaction.category_source not in {"JEV", "RULE"}
            or transaction.category_version != attempt.policy_version
        ):
            raise ConflictError("successful attempt requires a persisted label")
        row = self.session.scalar(
            select(ExpenseLabelAttemptModel).where(
                ExpenseLabelAttemptModel.transaction_id == transaction_id,
                ExpenseLabelAttemptModel.policy_version == attempt.policy_version,
            )
        )
        if row is None:
            row = ExpenseLabelAttemptModel(
                transaction_id=transaction_id,
                policy_version=attempt.policy_version,
            )
            self.session.add(row)
        row.attempt_count += 1
        if attempt.succeeded:
            row.status = "SUCCEEDED"
        elif row.attempt_count >= MAX_ATTEMPTS:
            row.status = "DEAD_LETTER"
        else:
            row.status = "RETRY"
        row.last_error = None if attempt.succeeded else (attempt.error or "label unavailable")[:120]
        row.next_attempt_at = (
            None
            if attempt.succeeded or row.status == "DEAD_LETTER"
            else datetime.now(UTC) + LEASE_DURATION
        )
        row.lease_until = None
        self.session.commit()
        return row

    def apply(
        self, transaction_id: UUID, user_id: UUID, write: LabelWrite
    ) -> TransactionModel:
        if write.source not in {"JEV", "RULE"}:
            raise ForbiddenError("derived labels must be JEV or RULE")
        transaction = self.session.scalar(
            select(TransactionModel)
            .where(
                TransactionModel.id == transaction_id,
                TransactionModel.user_id == user_id,
                TransactionModel.kind == TransactionKind.EXPENSE,
                TransactionModel.deleted_at.is_(None),
            )
            .with_for_update()
        )
        if transaction is None:
            raise NotFoundError("transaction not found")
        if transaction.category_source == "USER":
            raise ConflictError("user correction wins")
        if (
            transaction.category_source == write.source
            and transaction.category_version == write.version
            and transaction.category == normalize_category(write.category)
        ):
            return transaction
        if (
            write.observed_source is not None
            and transaction.category_source != write.observed_source
        ) or (
            write.observed_version is not None
            and transaction.category_version != write.observed_version
        ):
            raise ConflictError("label compare-and-set mismatch")
        current = PRECEDENCE.get(transaction.category_source or "", 0)
        if PRECEDENCE[write.source] <= current:
            raise ConflictError("derived label would not increase precedence")
        transaction.category = normalize_category(write.category)
        transaction.category_source = write.source
        transaction.category_version = write.version
        transaction.category_labeled_at = datetime.now(UTC)
        attempt = self.session.scalar(
            select(ExpenseLabelAttemptModel).where(
                ExpenseLabelAttemptModel.transaction_id == transaction_id,
                ExpenseLabelAttemptModel.policy_version == write.version,
            )
        )
        if attempt is not None:
            attempt.status = "SUCCEEDED"
            attempt.attempt_count += 1
            attempt.next_attempt_at = None
            attempt.lease_until = None
        self.session.commit()
        return transaction
