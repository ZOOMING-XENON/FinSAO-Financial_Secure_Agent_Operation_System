from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from agent_tools.client import BankingClientError, BankingHttpClient
from agent_tools.contracts import BaseBankingTool, ExecutionContext
from banking_core.app.domain.enums import Currency
from banking_core.app.domain.money import MoneyDecimal


class MonthInput(BaseModel):
    year: int
    month: int


class CategoryInput(BaseModel):
    transaction_id: UUID
    category: str


class BudgetCreateInput(BaseModel):
    category: str
    month: date
    limit_amount: MoneyDecimal
    currency: Currency = Currency.CNY


class BudgetUpdateInput(BaseModel):
    budget_id: UUID
    limit_amount: MoneyDecimal


class ResourceInput(BaseModel):
    resource_id: UUID


class NoInput(BaseModel):
    pass


class SummaryOutput(BaseModel):
    total: Decimal
    by_category: dict[str, Decimal]
    by_merchant: dict[str, Decimal]


class TransactionOutput(BaseModel):
    id: UUID
    reference: str
    status: str
    amount: Decimal
    currency: Currency
    description: str
    category: str | None
    posted_at: datetime | None


class BudgetOutput(BaseModel):
    id: UUID
    category: str
    month: date
    limit_amount: Decimal
    currency: Currency


class BudgetListOutput(BaseModel):
    items: list[BudgetOutput]


class BudgetStatusOutput(BaseModel):
    limit: Decimal
    used: Decimal
    remaining: Decimal
    estimate: Decimal
    threshold_exceeded: bool


class SubscriptionOutput(BaseModel):
    id: UUID
    merchant_name: str
    amount: Decimal
    currency: Currency
    next_billing_date: date
    active: bool
    status: str
    cancelled_at: datetime | None


class SubscriptionListOutput(BaseModel):
    items: list[SubscriptionOutput]


class RecurringEvidence(BaseModel):
    merchant: str
    confidence: str
    evidence_transaction_ids: list[UUID]
    estimated_next_billing_date: date


class RecurringListOutput(BaseModel):
    items: list[RecurringEvidence]


class AnalyticsTool(BaseBankingTool[BaseModel, BaseModel]):
    def __init__(
        self,
        client: BankingHttpClient,
        *,
        name: str,
        description: str,
        action: str,
        risk: str,
        input_model: type[BaseModel],
        output_model: type[BaseModel],
        method: str,
        path: str,
    ) -> None:
        self.client, self.name, self.description = client, name, description
        self.action, self.risk_policy = action, risk
        self.mutates_data = name in {
            "categorize_transaction",
            "create_budget",
            "update_budget",
            "cancel_subscription",
        }
        self.input_model, self.output_model = input_model, output_model
        self.method, self.path = method, path

    async def execute(self, input_data: BaseModel, context: ExecutionContext) -> BaseModel:
        values = input_data.model_dump(mode="json")
        path = self.path.format(**values)
        for key in ("transaction_id", "budget_id", "resource_id"):
            values.pop(key, None)
        if self.name == "cancel_subscription":
            if context.authorization_reference is None:
                raise BankingClientError(
                    "AUTHORIZATION_REQUIRED", "trusted authorization required", 403
                )
            values = {"authorization_ref": context.authorization_reference}
        raw_model = self.output_model
        if self.name in {"list_budgets", "list_subscriptions", "detect_recurring_payments"}:
            from pydantic import RootModel

            response = await self.client.request(
                self.method,
                path,
                context,
                RootModel[list[dict[str, Any]]],
                json=values if self.method != "GET" else None,
                params=values if self.method == "GET" else None,
                mutation=self.method != "GET",
            )
            return self.output_model.model_validate({"items": response.root})
        return await self.client.request(
            self.method,
            path,
            context,
            raw_model,
            json=values if self.method != "GET" else None,
            params=values if self.method == "GET" else None,
            mutation=self.method != "GET",
        )


class ExpenseQueryInput(BaseModel):
    account_id: UUID | None = None
    start: datetime | None = None
    end: datetime | None = None
    category: str | None = None
    merchant: str | None = None
    minimum_amount: MoneyDecimal | None = None
    maximum_amount: MoneyDecimal | None = None
    sort_by: Literal["posted_at", "amount", "category", "merchant"] = "posted_at"
    sort_direction: Literal["asc", "desc"] = "desc"
    limit: int = 50
    offset: int = Field(default=0, ge=0, le=1000)


class ExpenseSummaryInput(BaseModel):
    account_id: UUID | None = None
    start: datetime | None = None
    end: datetime | None = None
    category: str | None = None
    merchant: str | None = None
    minimum_amount: MoneyDecimal | None = None
    maximum_amount: MoneyDecimal | None = None


class ExpenseListOutput(BaseModel):
    items: list[TransactionOutput]
    limit: int
    offset: int


class ExpenseSummaryOutput(BaseModel):
    total: Decimal | None
    transaction_count: int
    totals_by_currency: dict[str, Decimal]
    by_category: dict[str, dict[str, Decimal]]
    by_merchant: dict[str, dict[str, Decimal]]


def _params(values: dict[str, object]) -> dict[str, str | int | float | bool | None]:
    result: dict[str, str | int | float | bool | None] = {}
    for key, value in values.items():
        if value is None:
            continue
        if isinstance(value, Decimal):
            result[key] = str(value)
        elif isinstance(value, (str, int, float, bool)):
            result[key] = value
        else:
            result[key] = str(value)
    return result


class GetExpensesTool(BaseBankingTool[ExpenseQueryInput, ExpenseListOutput]):
    name = "get_expenses"
    description = "List expenses with filters, sorting, and pagination"
    action = "expenses.query"
    risk_policy = "GREEN"
    input_model = ExpenseQueryInput
    output_model = ExpenseListOutput

    def __init__(self, client: BankingHttpClient) -> None:
        self.client = client

    async def execute(
        self, input_data: ExpenseQueryInput, context: ExecutionContext
    ) -> ExpenseListOutput:
        values = _params(input_data.model_dump(mode="json"))
        account_id = values.pop("account_id", None)
        path = f"/accounts/{account_id}/transactions" if account_id else "/transactions"
        return await self.client.request(
            "GET", path, context, ExpenseListOutput, params=values
        )


class SummarizeExpensesTool(BaseBankingTool[ExpenseSummaryInput, ExpenseSummaryOutput]):
    name = "summarize_expenses"
    description = "Summarize expenses with filters"
    action = "expenses.summary"
    risk_policy = "GREEN"
    input_model = ExpenseSummaryInput
    output_model = ExpenseSummaryOutput

    def __init__(self, client: BankingHttpClient) -> None:
        self.client = client

    async def execute(
        self, input_data: ExpenseSummaryInput, context: ExecutionContext
    ) -> ExpenseSummaryOutput:
        return await self.client.request(
            "GET",
            "/analytics/expenses/summary",
            context,
            ExpenseSummaryOutput,
            params=_params(input_data.model_dump(mode="json")),
        )


def analytics_tools(client: BankingHttpClient) -> list[BaseBankingTool[Any, Any]]:
    specs: list[tuple[str, str, str, str, type[BaseModel], type[BaseModel], str, str]] = [
        (
            "get_monthly_summary",
            "Monthly spending summary",
            "bills.query",
            "GREEN",
            MonthInput,
            SummaryOutput,
            "GET",
            "/analytics/monthly-summary",
        ),
        (
            "analyze_spending",
            "Analyze spending",
            "bills.query",
            "GREEN",
            MonthInput,
            SummaryOutput,
            "GET",
            "/analytics/spending",
        ),
        (
            "categorize_transaction",
            "Correct a transaction category",
            "transaction.categorize",
            "GREEN",
            CategoryInput,
            TransactionOutput,
            "PATCH",
            "/transactions/{transaction_id}/category",
        ),
        (
            "list_budgets",
            "List budgets",
            "budget.query",
            "GREEN",
            NoInput,
            BudgetListOutput,
            "GET",
            "/budgets",
        ),
        (
            "get_budget_status",
            "Read budget usage",
            "budget.query",
            "GREEN",
            ResourceInput,
            BudgetStatusOutput,
            "GET",
            "/budgets/{resource_id}/status",
        ),
        (
            "create_budget",
            "Create a virtual budget",
            "budget.create",
            "GREEN",
            BudgetCreateInput,
            BudgetOutput,
            "POST",
            "/budgets",
        ),
        (
            "update_budget",
            "Update a virtual budget",
            "budget.update",
            "GREEN",
            BudgetUpdateInput,
            BudgetOutput,
            "PATCH",
            "/budgets/{budget_id}",
        ),
        (
            "list_subscriptions",
            "List subscriptions",
            "bills.query",
            "GREEN",
            NoInput,
            SubscriptionListOutput,
            "GET",
            "/subscriptions",
        ),
        (
            "detect_recurring_payments",
            "Detect recurring payments",
            "bills.query",
            "GREEN",
            NoInput,
            RecurringListOutput,
            "GET",
            "/subscriptions/detect-recurring",
        ),
        (
            "cancel_subscription",
            "Cancel an authorized subscription",
            "subscription.cancel",
            "YELLOW",
            ResourceInput,
            SubscriptionOutput,
            "POST",
            "/subscriptions/{resource_id}/cancel",
        ),
    ]
    return [
        GetExpensesTool(client),
        SummarizeExpensesTool(client),
        *[
            AnalyticsTool(
                client,
                name=n,
                description=d,
                action=a,
                risk=r,
                input_model=i,
                output_model=o,
                method=m,
                path=p,
            )
            for n, d, a, r, i, o, m, p in specs
        ],
    ]
