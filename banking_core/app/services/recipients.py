from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from banking_core.app.domain.enums import TransferStatus
from banking_core.app.persistence.models import AccountModel, TransferDraftModel


@dataclass(frozen=True)
class RecentRecipient:
    destination_account_id: UUID
    display_name: str
    masked_account: str
    last_transfer_at: datetime
    last_amount: Decimal
    currency: str
    beneficiary_id: UUID | None = None


class RecentRecipientService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def list(
        self,
        user_id: UUID,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int = 20,
    ) -> list[RecentRecipient]:
        query = (
            select(
                TransferDraftModel.destination_account_id,
                AccountModel.name,
                AccountModel.account_number,
                func.max(TransferDraftModel.created_at),
                func.max(TransferDraftModel.amount),
                TransferDraftModel.currency,
            )
            .join(AccountModel, AccountModel.id == TransferDraftModel.destination_account_id)
            .where(
                TransferDraftModel.user_id == user_id,
                TransferDraftModel.status == TransferStatus.COMPLETED,
            )
            .group_by(
                TransferDraftModel.destination_account_id,
                AccountModel.name,
                AccountModel.account_number,
                TransferDraftModel.currency,
            )
            .order_by(func.max(TransferDraftModel.created_at).desc())
            .limit(limit)
        )
        if start is not None:
            query = query.where(TransferDraftModel.created_at >= start)
        if end is not None:
            query = query.where(TransferDraftModel.created_at < end)
        rows = self.session.execute(query).all()
        return [
            RecentRecipient(
                destination_account_id=destination_account_id,
                display_name=name,
                masked_account=f"****{account_number[-4:]}",
                last_transfer_at=last_transfer_at,
                last_amount=last_amount,
                currency=currency.value,
            )
            for (
                destination_account_id,
                name,
                account_number,
                last_transfer_at,
                last_amount,
                currency,
            ) in rows
        ]
