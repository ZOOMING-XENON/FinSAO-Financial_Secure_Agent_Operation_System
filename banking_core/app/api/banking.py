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
from banking_core.app.domain.enums import TransactionDirection
from banking_core.app.schemas.banking import (
    AccountResponse,
    BalanceResponse,
    BeneficiaryCreateRequest,
    BeneficiaryResolutionResponse,
    BeneficiaryResponse,
    CommitTransferRequest,
    ExpenseCreateRequest,
    ExpenseUpdateRequest,
    RecentRecipientResponse,
    TransactionPage,
    TransactionResponse,
    TransferDraftRequest,
    TransferDraftResponse,
    TransferReceipt,
)
from banking_core.app.security.transfer_authorization import TransferAuthorizationVerifier
from banking_core.app.services.accounts import AccountService
from banking_core.app.services.beneficiaries import BeneficiaryService
from banking_core.app.services.expense_records import ExpenseRecordService
from banking_core.app.services.expenses import ExpenseFilters, ExpenseService
from banking_core.app.services.recipients import RecentRecipientService
from banking_core.app.services.transaction_history import (
    AccountTransactionFilters,
    TransactionHistoryItem,
    TransactionHistoryService,
)
from banking_core.app.services.transfers import TransferService

router = APIRouter()
Db = Annotated[Session, Depends(get_db_session)]
Actor = Annotated[UUID, Depends(get_current_user_id)]
Verifier = Annotated[TransferAuthorizationVerifier, Depends(get_transfer_verifier)]


def _transaction_response(
    transaction: object,
    *,
    direction: TransactionDirection | None = None,
    account_id: UUID | None = None,
) -> TransactionResponse:
    response = TransactionResponse.model_validate(transaction)
    return response.model_copy(update={"direction": direction, "account_id": account_id})


def _history_response(item: TransactionHistoryItem) -> TransactionResponse:
    return _transaction_response(
        item.transaction,
        direction=item.direction,
        account_id=item.account_id,
    )


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
    return TransactionPage(
        items=[
            _transaction_response(item, direction=TransactionDirection.DEBIT)
            for item in items
        ],
        limit=limit,
        offset=offset,
    )


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
    items = TransactionHistoryService(session).account_history(
        account_id,
        actor_id,
        AccountTransactionFilters(
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
    return TransactionPage(
        items=[_history_response(item) for item in items],
        limit=limit,
        offset=offset,
    )


@router.get("/transactions", response_model=TransactionPage, tags=["accounts"])
def list_expenses(
    session: Db,
    actor_id: Actor,
    account_id: UUID | None = None,
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


@router.get("/activity", response_model=TransactionPage, tags=["accounts"])
def activity(
    session: Db,
    actor_id: Actor,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0, le=1000)] = 0,
) -> TransactionPage:
    items = TransactionHistoryService(session).activity(actor_id, limit, offset)
    return TransactionPage(
        items=[_history_response(item) for item in items],
        limit=limit,
        offset=offset,
    )


@router.post("/expenses", response_model=TransactionResponse, tags=["expenses"])
def create_expense(
    request: ExpenseCreateRequest,
    session: Db,
    actor_id: Actor,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=120)],
) -> TransactionResponse:
    transaction = ExpenseRecordService(session).create(
        actor_id,
        amount=request.amount,
        currency=request.currency,
        merchant=request.merchant,
        category=request.category,
        occurred_at=request.occurred_at,
        account_id=request.account_id,
        origin=request.origin,
        idempotency_key=idempotency_key,
    )
    return _transaction_response(transaction, direction=TransactionDirection.DEBIT)


@router.get("/expenses/{expense_id}", response_model=TransactionResponse, tags=["expenses"])
def get_expense(expense_id: UUID, session: Db, actor_id: Actor) -> TransactionResponse:
    transaction = ExpenseRecordService(session).get(expense_id, actor_id)
    return _transaction_response(transaction, direction=TransactionDirection.DEBIT)


@router.patch("/expenses/{expense_id}", response_model=TransactionResponse, tags=["expenses"])
def update_expense(
    expense_id: UUID,
    request: ExpenseUpdateRequest,
    session: Db,
    actor_id: Actor,
) -> TransactionResponse:
    transaction = ExpenseRecordService(session).update(
        expense_id,
        actor_id,
        amount=request.amount,
        currency=request.currency,
        merchant=request.merchant,
        category=request.category,
        occurred_at=request.occurred_at,
        account_id=request.account_id,
    )
    return _transaction_response(transaction, direction=TransactionDirection.DEBIT)


@router.delete("/expenses/{expense_id}", status_code=204, tags=["expenses"])
def delete_expense(expense_id: UUID, session: Db, actor_id: Actor) -> None:
    ExpenseRecordService(session).delete(expense_id, actor_id)


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
