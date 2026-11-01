from datetime import datetime
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from banking_core.app.api.dependencies import (
    get_current_user_id,
    get_db_session,
    get_labeling_worker_id,
)
from banking_core.app.schemas.analytics import (
    BudgetRequest,
    BudgetResponse,
    BudgetStatusResponse,
    BudgetUpdateRequest,
    CancelSubscriptionRequest,
    CategoryCorrectionRequest,
    ExpenseLabelWriteRequest,
    ExpenseLabelAttemptRequest,
    ExpenseSummaryResponse,
    ReminderRequest,
    ReminderResponse,
    SpendingSummaryResponse,
    SubscriptionResponse,
)
from banking_core.app.schemas.banking import LabelingTransactionResponse, TransactionResponse
from banking_core.app.services.analytics import (
    BillAnalysisService,
    BudgetService,
    SubscriptionService,
)
from banking_core.app.services.expense_labeling import (
    LabelAttempt,
    ExpenseLabelingService,
    LabelWrite,
)
from banking_core.app.services.expenses import ExpenseFilters, ExpenseService

router = APIRouter(tags=["analytics"])
Db = Annotated[Session, Depends(get_db_session)]
Actor = Annotated[UUID, Depends(get_current_user_id)]
LabelingWorker = Annotated[UUID, Depends(get_labeling_worker_id)]


@router.get("/analytics/expenses/summary", response_model=ExpenseSummaryResponse)
def expense_summary(
    session: Db,
    actor: Actor,
    account_id: UUID | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
    category: str | None = None,
    merchant: str | None = None,
    minimum_amount: Decimal | None = None,
    maximum_amount: Decimal | None = None,
) -> ExpenseSummaryResponse:
    summary = ExpenseService(session).summary(
        actor,
        ExpenseFilters(
            account_id=account_id,
            start=start,
            end=end,
            category=category,
            merchant=merchant,
            minimum_amount=minimum_amount,
            maximum_amount=maximum_amount,
        ),
    )
    return ExpenseSummaryResponse(
        total=summary.total,
        transaction_count=summary.transaction_count,
        totals_by_currency=summary.totals_by_currency,
        by_category=summary.by_category,
        by_merchant=summary.by_merchant,
    )


@router.get(
    "/internal/expense-labeling/transactions",
    response_model=list[LabelingTransactionResponse],
)
def pending_expense_labels(
    session: Db,
    worker: LabelingWorker,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[LabelingTransactionResponse]:
    return [
        LabelingTransactionResponse.model_validate(item)
        for item in ExpenseLabelingService(session).pending(worker, limit=limit)
    ]


@router.post(
    "/internal/expense-labeling/transactions/{transaction_id}/label",
    response_model=TransactionResponse,
)
def write_expense_label(
    transaction_id: UUID,
    request: ExpenseLabelWriteRequest,
    session: Db,
    actor: LabelingWorker,
) -> TransactionResponse:
    transaction = ExpenseLabelingService(session).apply(
        transaction_id,
        actor,
        LabelWrite(
            category=request.category,
            source=request.source,
            observed_source=request.observed_source,
            observed_version=request.observed_version,
            version=request.version,
        ),
    )
    return TransactionResponse.model_validate(transaction)


@router.post(
    "/internal/expense-labeling/transactions/{transaction_id}/attempt",
    status_code=204,
)
def record_expense_label_attempt(
    transaction_id: UUID,
    request: ExpenseLabelAttemptRequest,
    session: Db,
    actor: LabelingWorker,
) -> None:
    ExpenseLabelingService(session).record_attempt(
        transaction_id,
        actor,
        LabelAttempt(
            policy_version=request.policy_version,
            succeeded=request.succeeded,
            error=request.error,
        ),
    )


@router.get("/analytics/monthly-summary", response_model=SpendingSummaryResponse)
def monthly_summary(
    year: int, month: Annotated[int, Query(ge=1, le=12)], session: Db, actor: Actor
) -> SpendingSummaryResponse:
    summary = BillAnalysisService(session).monthly_summary(actor, year, month)
    return SpendingSummaryResponse.model_validate(summary, from_attributes=True)


@router.get("/analytics/spending", response_model=SpendingSummaryResponse)
def analyze_spending(
    year: int, month: Annotated[int, Query(ge=1, le=12)], session: Db, actor: Actor
) -> SpendingSummaryResponse:
    return monthly_summary(year, month, session, actor)


@router.patch("/transactions/{transaction_id}/category", response_model=TransactionResponse)
def categorize_transaction(
    transaction_id: UUID, request: CategoryCorrectionRequest, session: Db, actor: Actor
) -> TransactionResponse:
    item = BillAnalysisService(session).correct_category(transaction_id, actor, request.category)
    return TransactionResponse.model_validate(item)


@router.post("/budgets", response_model=BudgetResponse)
def create_budget(request: BudgetRequest, session: Db, actor: Actor) -> BudgetResponse:
    item = BudgetService(session).create(
        actor, request.category, request.month, request.limit_amount, request.currency
    )
    return BudgetResponse.model_validate(item)


@router.patch("/budgets/{budget_id}", response_model=BudgetResponse)
def update_budget(
    budget_id: UUID, request: BudgetUpdateRequest, session: Db, actor: Actor
) -> BudgetResponse:
    return BudgetResponse.model_validate(
        BudgetService(session).update(budget_id, actor, request.limit_amount)
    )


@router.get("/budgets", response_model=list[BudgetResponse])
def list_budgets(session: Db, actor: Actor) -> list[BudgetResponse]:
    return [BudgetResponse.model_validate(item) for item in BudgetService(session).list(actor)]


@router.get("/budgets/{budget_id}/status", response_model=BudgetStatusResponse)
def budget_status(budget_id: UUID, session: Db, actor: Actor) -> BudgetStatusResponse:
    return BudgetStatusResponse.model_validate(BudgetService(session).status(budget_id, actor))


@router.post("/subscriptions/{subscription_id}/reminders", response_model=ReminderResponse)
def create_subscription_reminder(
    subscription_id: UUID, request: ReminderRequest, session: Db, actor: Actor
) -> ReminderResponse:
    item = SubscriptionService(session).create_reminder(subscription_id, actor, request.remind_on)
    return ReminderResponse.model_validate(item)


@router.get("/subscriptions", response_model=list[SubscriptionResponse])
def list_subscriptions(session: Db, actor: Actor) -> list[SubscriptionResponse]:
    return [
        SubscriptionResponse.model_validate(item)
        for item in SubscriptionService(session).list(actor)
    ]


@router.get("/subscriptions/detect-recurring")
def detect_recurring(session: Db, actor: Actor) -> list[dict[str, object]]:
    return SubscriptionService(session).detect_recurring(actor)


@router.post("/subscriptions/{subscription_id}/cancel", response_model=SubscriptionResponse)
def cancel_subscription(
    subscription_id: UUID, request: CancelSubscriptionRequest, session: Db, actor: Actor
) -> SubscriptionResponse:
    item = SubscriptionService(session).cancel(subscription_id, actor, request.authorization_ref)
    return SubscriptionResponse.model_validate(item)
