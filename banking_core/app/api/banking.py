from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query
from sqlalchemy.orm import Session

from banking_core.app.api.dependencies import (
    get_current_user_id,
    get_db_session,
    get_transfer_verifier,
)
from banking_core.app.schemas.banking import (
    AccountResponse,
    BalanceResponse,
    BeneficiaryCreateRequest,
    BeneficiaryResolutionResponse,
    BeneficiaryResponse,
    CommitTransferRequest,
    RecentRecipientResponse,
    TransactionPage,
    TransferDraftRequest,
    TransferDraftResponse,
    TransferReceipt,
)
from banking_core.app.security.transfer_authorization import TransferAuthorizationVerifier
from banking_core.app.services.accounts import AccountService
from banking_core.app.services.beneficiaries import BeneficiaryService
from banking_core.app.services.expenses import ExpenseFilters, ExpenseService
from banking_core.app.services.recipients import RecentRecipientService
from banking_core.app.services.transfers import TransferService

router = APIRouter()
Db = Annotated[Session, Depends(get_db_session)]
Actor = Annotated[UUID, Depends(get_current_user_id)]
Verifier = Annotated[TransferAuthorizationVerifier, Depends(get_transfer_verifier)]


@router.get("/accounts", response_model=list[AccountResponse], tags=["accounts"])
def get_accounts(session: Db, actor_id: Actor) -> list[AccountResponse]:
    return [
        AccountResponse.model_validate(item)
        for item in AccountService(session).get_accounts(actor_id)
    ]


@router.get("/accounts/{account_id}/balance", response_model=BalanceResponse, tags=["accounts"])
def get_balance(account_id: UUID, session: Db, actor_id: Actor) -> BalanceResponse:
    account = AccountService(session).get_balance(account_id, actor_id)
    return BalanceResponse(
        account_id=account.id, balance=account.balance, currency=account.currency
    )


def _expense_page(
    session: Session,
    actor_id: UUID,
    *,
    account_id: UUID | None,
    start: datetime | None,
    end: datetime | None,
    limit: int,
    offset: int,
    category: str | None,
    merchant: str | None,
    minimum_amount: Decimal | None,
    maximum_amount: Decimal | None,
    sort_by: Literal["posted_at", "amount", "category", "merchant"],
    sort_direction: Literal["asc", "desc"],
) -> TransactionPage:
    items = ExpenseService(session).list(
        actor_id,
        ExpenseFilters(
            account_id=account_id,
            start=start,
            end=end,
            limit=limit,
            offset=offset,
            category=category,
            merchant=merchant,
            minimum_amount=minimum_amount,
            maximum_amount=maximum_amount,
            sort_by=sort_by,
            sort_direction=sort_direction,
        ),
    )
    return TransactionPage(items=items, limit=limit, offset=offset)


@router.get(
    "/accounts/{account_id}/transactions", response_model=TransactionPage, tags=["accounts"]
)
def get_transactions(
    account_id: UUID,
    session: Db,
    actor_id: Actor,
    start: datetime | None = None,
    end: datetime | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0, le=1000)] = 0,
    category: str | None = None,
    merchant: str | None = None,
    minimum_amount: Decimal | None = None,
    maximum_amount: Decimal | None = None,
    sort_by: Literal["posted_at", "amount", "category", "merchant"] = "posted_at",
    sort_direction: Literal["asc", "desc"] = "desc",
) -> TransactionPage:
    return _expense_page(
        session,
        actor_id,
        account_id=account_id,
        start=start,
        end=end,
        limit=limit,
        offset=offset,
        category=category,
        merchant=merchant,
        minimum_amount=minimum_amount,
        maximum_amount=maximum_amount,
        sort_by=sort_by,
        sort_direction=sort_direction,
    )


@router.get("/transactions", response_model=TransactionPage, tags=["accounts"])
def list_expenses(
    session: Db,
    actor_id: Actor,
    start: datetime | None = None,
    end: datetime | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0, le=1000)] = 0,
    category: str | None = None,
    merchant: str | None = None,
    minimum_amount: Decimal | None = None,
    maximum_amount: Decimal | None = None,
    sort_by: Literal["posted_at", "amount", "category", "merchant"] = "posted_at",
    sort_direction: Literal["asc", "desc"] = "desc",
) -> TransactionPage:
    return _expense_page(
        session,
        actor_id,
        account_id=None,
        start=start,
        end=end,
        limit=limit,
        offset=offset,
        category=category,
        merchant=merchant,
        minimum_amount=minimum_amount,
        maximum_amount=maximum_amount,
        sort_by=sort_by,
        sort_direction=sort_direction,
    )


@router.get(
    "/recipients/recent",
    response_model=list[RecentRecipientResponse],
    tags=["beneficiaries"],
)
def recent_recipients(
    session: Db,
    actor_id: Actor,
    start: datetime | None = None,
    end: datetime | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> list[RecentRecipientResponse]:
    return [
        RecentRecipientResponse(
            destination_account_id=item.destination_account_id,
            display_name=item.display_name,
            masked_account=item.masked_account,
            last_transfer_at=item.last_transfer_at,
            last_amount=item.last_amount,
            currency=item.currency,
            beneficiary_id=item.beneficiary_id,
        )
        for item in RecentRecipientService(session).list(
            actor_id, start=start, end=end, limit=limit
        )
    ]


@router.get("/beneficiaries", response_model=list[BeneficiaryResponse], tags=["beneficiaries"])
def list_beneficiaries(session: Db, actor_id: Actor) -> list[BeneficiaryResponse]:
    return [
        BeneficiaryResponse.model_validate(item)
        for item in BeneficiaryService(session).list_beneficiaries(actor_id)
    ]


@router.post(
    "/beneficiaries", response_model=BeneficiaryResponse, status_code=201, tags=["beneficiaries"]
)
def save_beneficiary(
    request: BeneficiaryCreateRequest, session: Db, actor_id: Actor
) -> BeneficiaryResponse:
    item = BeneficiaryService(session).save_beneficiary(
        actor_id,
        name=request.name,
        account_number=request.account_number,
        nickname=request.nickname,
    )
    return BeneficiaryResponse.model_validate(item)


@router.get(
    "/beneficiaries/resolve", response_model=BeneficiaryResolutionResponse, tags=["beneficiaries"]
)
def resolve_beneficiary(query: str, session: Db, actor_id: Actor) -> BeneficiaryResolutionResponse:
    result = BeneficiaryService(session).resolve_beneficiary(actor_id, query)
    return BeneficiaryResolutionResponse(status=result.status, matches=list(result.matches))


@router.post("/transfers/drafts", response_model=TransferDraftResponse, tags=["transfers"])
def create_transfer_draft(
    request: TransferDraftRequest,
    session: Db,
    actor_id: Actor,
    verifier: Verifier,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=120)],
) -> TransferDraftResponse:
    draft = TransferService(session, verifier).create_transfer_draft(
        user_id=actor_id,
        source_account_id=request.source_account_id,
        destination_account_id=request.destination_account_id,
        amount=request.amount,
        currency=request.currency,
        idempotency_key=idempotency_key,
    )
    return TransferDraftResponse.model_validate(draft)


@router.get(
    "/transfers/drafts/{draft_id}", response_model=TransferDraftResponse, tags=["transfers"]
)
def get_transfer_draft(
    draft_id: UUID, session: Db, actor_id: Actor, verifier: Verifier
) -> TransferDraftResponse:
    return TransferDraftResponse.model_validate(
        TransferService(session, verifier).get_transfer_draft(draft_id, actor_id)
    )


@router.post("/transfers/{draft_id}/commit", response_model=TransferReceipt, tags=["transfers"])
def commit_transfer(
    draft_id: UUID,
    request: CommitTransferRequest,
    session: Db,
    actor_id: Actor,
    verifier: Verifier,
) -> TransferReceipt:
    transaction = TransferService(session, verifier).commit_transfer(
        draft_id, actor_id, request.authorization_ref
    )
    return TransferReceipt(
        transaction_id=transaction.id,
        reference=transaction.reference,
        status=transaction.status,
        amount=transaction.amount,
        currency=transaction.currency,
    )


@router.get("/transfers/{transfer_id}", response_model=TransferDraftResponse, tags=["transfers"])
def get_transfer_status(
    transfer_id: UUID,
    session: Db,
    actor_id: Actor,
    verifier: Verifier,
) -> TransferDraftResponse:
    return TransferDraftResponse.model_validate(
        TransferService(session, verifier).get_transfer_status(transfer_id, actor_id)
    )
