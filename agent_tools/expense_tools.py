from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, RootModel

from agent_tools.client import BankingHttpClient
from agent_tools.contracts import BaseBankingTool, ExecutionContext
from banking_core.app.domain.enums import (
    Currency,
    TransactionDirection,
    TransactionKind,
    TransactionOrigin,
    TransactionStatus,
)
from banking_core.app.domain.money import MoneyDecimal


class ExpenseItem(BaseModel):
    id: UUID
    reference: str
    status: TransactionStatus
    kind: TransactionKind
    origin: TransactionOrigin
    direction: TransactionDirection | None = None
    account_id: UUID | None = None
    amount: Decimal
    currency: Currency
    description: str
    merchant: str | None = None
    category: str | None
    category_source: str | None = None
    posted_at: datetime | None


class RecordExpenseInput(BaseModel):
    amount: MoneyDecimal = Field(gt=0, max_digits=18, decimal_places=2)
    currency: Currency
    merchant: str = Field(min_length=1, max_length=120)
    category: str | None = Field(default=None, max_length=80)
    occurred_at: datetime | None = None
    account_id: UUID | None = None
    origin: TransactionOrigin = TransactionOrigin.CASH
    idempotency_key: str = Field(min_length=1, max_length=120)


class UpdateExpenseInput(BaseModel):
    expense_id: UUID
    amount: MoneyDecimal | None = Field(default=None, gt=0, max_digits=18, decimal_places=2)
    currency: Currency | None = None
    merchant: str | None = Field(default=None, min_length=1, max_length=120)
    category: str | None = Field(default=None, max_length=80)
    occurred_at: datetime | None = None
    account_id: UUID | None = None


class DeleteExpenseInput(BaseModel):
    expense_id: UUID


class DeleteExpenseOutput(BaseModel):
    deleted: bool


class RecordExpenseTool(BaseBankingTool[RecordExpenseInput, ExpenseItem]):
    name = "record_expense"
    description = "Record a completed expense without moving bank funds"
    action = "expenses.create"
    risk_policy = "GREEN"
    mutates_data = True
    input_model = RecordExpenseInput
    output_model = ExpenseItem

    def __init__(self, client: BankingHttpClient) -> None:
        self.client = client

    async def execute(
        self, input_data: RecordExpenseInput, context: ExecutionContext
    ) -> ExpenseItem:
        body = input_data.model_dump(exclude={"idempotency_key"}, mode="json")
        return await self.client.request(
            "POST",
            "/expenses",
            context,
            ExpenseItem,
            json=body,
            idempotency_key=input_data.idempotency_key,
            mutation=True,
        )


class UpdateExpenseTool(BaseBankingTool[UpdateExpenseInput, ExpenseItem]):
    name = "update_expense"
    description = "Update a recorded expense"
    action = "expenses.update"
    risk_policy = "GREEN"
    mutates_data = True
    input_model = UpdateExpenseInput
    output_model = ExpenseItem

    def __init__(self, client: BankingHttpClient) -> None:
        self.client = client

    async def execute(
        self, input_data: UpdateExpenseInput, context: ExecutionContext
    ) -> ExpenseItem:
        body = input_data.model_dump(exclude={"expense_id"}, mode="json")
        return await self.client.request(
            "PATCH",
            f"/expenses/{input_data.expense_id}",
            context,
            ExpenseItem,
            json=body,
            mutation=True,
        )


class DeleteExpenseTool(BaseBankingTool[DeleteExpenseInput, DeleteExpenseOutput]):
    name = "delete_expense"
    description = "Delete a recorded expense"
    action = "expenses.delete"
    risk_policy = "GREEN"
    mutates_data = True
    input_model = DeleteExpenseInput
    output_model = DeleteExpenseOutput

    def __init__(self, client: BankingHttpClient) -> None:
        self.client = client

    async def execute(
        self, input_data: DeleteExpenseInput, context: ExecutionContext
    ) -> DeleteExpenseOutput:
        await self.client.request(
            "DELETE",
            f"/expenses/{input_data.expense_id}",
            context,
            RootModel[dict[str, object]],
            mutation=True,
        )
        return DeleteExpenseOutput(deleted=True)


def expense_tools(client: BankingHttpClient) -> list[BaseBankingTool[Any, Any]]:
    return [
        RecordExpenseTool(client),
        UpdateExpenseTool(client),
        DeleteExpenseTool(client),
    ]
