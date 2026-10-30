from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from agent_tools.client import BankingHttpClient
from agent_tools.contracts import BaseBankingTool, ExecutionContext
from agent_tools.registry import ToolRegistry
from banking_core.app.domain.enums import Currency, TransactionStatus, TransferStatus
from banking_core.app.domain.money import MoneyDecimal


class EmptyInput(BaseModel):
    pass


class AccountItem(BaseModel):
    id: UUID
    account_number: str
    name: str
    currency: Currency
    status: str


class AccountsOutput(BaseModel):
    accounts: list[AccountItem]


class AccountIdInput(BaseModel):
    account_id: UUID


class BalanceOutput(BaseModel):
    account_id: UUID
    balance: Decimal
    currency: Currency


class TransactionsInput(BaseModel):
    account_id: UUID
    limit: int = Field(default=50, ge=1, le=200)
    offset: int = Field(default=0, ge=0)
    category: str | None = None
    merchant: str | None = None
    minimum_amount: MoneyDecimal | None = None
    maximum_amount: MoneyDecimal | None = None


class TransactionItem(BaseModel):
    id: UUID
    reference: str
    status: TransactionStatus
    amount: Decimal
    currency: Currency
    description: str
    category: str | None
    posted_at: datetime | None


class TransactionsOutput(BaseModel):
    items: list[TransactionItem]
    limit: int
    offset: int


class ResolveBeneficiaryInput(BaseModel):
    query: str = Field(min_length=1, max_length=120)


class BeneficiaryItem(BaseModel):
    id: UUID
    name: str
    nickname: str | None
    destination_account_id: UUID
    destination_account_number: str


class BeneficiariesOutput(BaseModel):
    beneficiaries: list[BeneficiaryItem]


class ResolveBeneficiaryOutput(BaseModel):
    status: str
    matches: list[BeneficiaryItem]


class ListBeneficiariesTool(BaseBankingTool[EmptyInput, BeneficiariesOutput]):
    name, description, action, risk_policy = (
        "list_beneficiaries",
        "List saved transfer beneficiaries with names, nicknames and destination accounts",
        "beneficiaries.list",
        "GREEN",
    )
    input_model, output_model = EmptyInput, BeneficiariesOutput

    def __init__(self, client: BankingHttpClient) -> None:
        self.client = client

    async def execute(
        self, input_data: EmptyInput, context: ExecutionContext
    ) -> BeneficiariesOutput:
        del input_data
        from pydantic import RootModel

        response = await self.client.request(
            "GET", "/beneficiaries", context, RootModel[list[BeneficiaryItem]]
        )
        return BeneficiariesOutput(beneficiaries=response.root)


class CreateTransferDraftInput(BaseModel):
    source_account_id: UUID
    destination_account_id: UUID
    amount: MoneyDecimal = Field(gt=0, max_digits=18, decimal_places=2)
    currency: Currency
    idempotency_key: str = Field(min_length=1, max_length=120)


class TransferIdInput(BaseModel):
    transfer_id: UUID


class TransferDraftOutput(BaseModel):
    id: UUID
    source_account_id: UUID
    destination_account_id: UUID
    amount: Decimal
    currency: Currency
    status: TransferStatus
    expires_at: datetime
    transaction_id: UUID | None


class CommitTransferInput(BaseModel):
    draft_id: UUID


class TransferReceiptOutput(BaseModel):
    transaction_id: UUID
    reference: str
    status: TransactionStatus
    amount: Decimal
    currency: Currency


class GetAccountsTool(BaseBankingTool[EmptyInput, AccountsOutput]):
    name, description, action, risk_policy = (
        "get_accounts",
        "List the user's accounts",
        "accounts.list",
        "GREEN",
    )
    input_model, output_model = EmptyInput, AccountsOutput

    def __init__(self, client: BankingHttpClient) -> None:
        self.client = client

    async def execute(self, input_data: EmptyInput, context: ExecutionContext) -> AccountsOutput:
        del input_data
        from pydantic import RootModel

        response = await self.client.request(
            "GET", "/accounts", context, RootModel[list[AccountItem]]
        )
        return AccountsOutput(accounts=response.root)


class GetBalanceTool(BaseBankingTool[AccountIdInput, BalanceOutput]):
    name, description, action, risk_policy = (
        "get_balance",
        "Read an account balance",
        "balance.query",
        "GREEN",
    )
    input_model, output_model = AccountIdInput, BalanceOutput

    def __init__(self, client: BankingHttpClient) -> None:
        self.client = client

    async def execute(self, input_data: AccountIdInput, context: ExecutionContext) -> BalanceOutput:
        return await self.client.request(
            "GET", f"/accounts/{input_data.account_id}/balance", context, BalanceOutput
        )


class GetTransactionsTool(BaseBankingTool[TransactionsInput, TransactionsOutput]):
    name, description, action, risk_policy = (
        "get_transactions",
        "Read transaction history",
        "transactions.query",
        "GREEN",
    )
    input_model, output_model = TransactionsInput, TransactionsOutput

    def __init__(self, client: BankingHttpClient) -> None:
        self.client = client

    async def execute(
        self, input_data: TransactionsInput, context: ExecutionContext
    ) -> TransactionsOutput:
        return await self.client.request(
            "GET",
            f"/accounts/{input_data.account_id}/transactions",
            context,
            TransactionsOutput,
            params={
                "limit": input_data.limit,
                "offset": input_data.offset,
                "category": input_data.category,
                "merchant": input_data.merchant,
                "minimum_amount": str(input_data.minimum_amount)
                if input_data.minimum_amount is not None
                else None,
                "maximum_amount": str(input_data.maximum_amount)
                if input_data.maximum_amount is not None
                else None,
            },
        )


class ResolveBeneficiaryTool(BaseBankingTool[ResolveBeneficiaryInput, ResolveBeneficiaryOutput]):
    name, description, action, risk_policy = (
        "resolve_beneficiary",
        "Match a saved beneficiary by name or nickname and return the verified destination account",
        "beneficiaries.resolve",
        "GREEN",
    )
    input_model, output_model = ResolveBeneficiaryInput, ResolveBeneficiaryOutput

    def __init__(self, client: BankingHttpClient) -> None:
        self.client = client

    async def execute(
        self, input_data: ResolveBeneficiaryInput, context: ExecutionContext
    ) -> ResolveBeneficiaryOutput:
        return await self.client.request(
            "GET",
            "/beneficiaries/resolve",
            context,
            ResolveBeneficiaryOutput,
            params={"query": input_data.query},
        )


class CreateTransferDraftTool(BaseBankingTool[CreateTransferDraftInput, TransferDraftOutput]):
    name, description, action, risk_policy = (
        "create_transfer_draft",
        "Prepare but do not execute a transfer",
        "transfer.draft",
        "YELLOW_OR_RED",
    )
    input_model, output_model = CreateTransferDraftInput, TransferDraftOutput

    def __init__(self, client: BankingHttpClient) -> None:
        self.client = client

    async def execute(
        self, input_data: CreateTransferDraftInput, context: ExecutionContext
    ) -> TransferDraftOutput:
        body = input_data.model_dump(exclude={"idempotency_key"}, mode="json")
        return await self.client.request(
            "POST",
            "/transfers/drafts",
            context,
            TransferDraftOutput,
            json=body,
            idempotency_key=input_data.idempotency_key,
            mutation=True,
        )


class GetTransferStatusTool(BaseBankingTool[TransferIdInput, TransferDraftOutput]):
    name, description, action, risk_policy = (
        "get_transfer_status",
        "Reconcile transfer state",
        "transfer.status",
        "GREEN",
    )
    input_model, output_model = TransferIdInput, TransferDraftOutput

    def __init__(self, client: BankingHttpClient) -> None:
        self.client = client

    async def execute(
        self, input_data: TransferIdInput, context: ExecutionContext
    ) -> TransferDraftOutput:
        return await self.client.request(
            "GET", f"/transfers/{input_data.transfer_id}", context, TransferDraftOutput
        )


class CommitTransferTool(BaseBankingTool[CommitTransferInput, TransferReceiptOutput]):
    name, description, action, risk_policy = (
        "commit_transfer",
        "Commit an already authorized transfer",
        "transfer.commit",
        "YELLOW_OR_RED",
    )
    input_model, output_model = CommitTransferInput, TransferReceiptOutput

    def __init__(self, client: BankingHttpClient) -> None:
        self.client = client

    async def execute(
        self, input_data: CommitTransferInput, context: ExecutionContext
    ) -> TransferReceiptOutput:
        if context.authorization_reference is None:
            from agent_tools.client import BankingClientError

            raise BankingClientError(
                "AUTHORIZATION_REQUIRED", "trusted authorization reference required", 403
            )
        return await self.client.request(
            "POST",
            f"/transfers/{input_data.draft_id}/commit",
            context,
            TransferReceiptOutput,
            json={"authorization_ref": context.authorization_reference},
            mutation=True,
        )


def register_default_tools(registry: ToolRegistry, client: BankingHttpClient) -> None:
    from agent_tools.analytics_tools import analytics_tools
    from agent_tools.cards_wealth_tools import cards_wealth_tools
    from agent_tools.savings_tools import savings_tools

    tools: list[BaseBankingTool[Any, Any]] = [
        GetAccountsTool(client),
        GetBalanceTool(client),
        GetTransactionsTool(client),
        ListBeneficiariesTool(client),
        ResolveBeneficiaryTool(client),
        CreateTransferDraftTool(client),
        GetTransferStatusTool(client),
        CommitTransferTool(client),
    ]
    for tool in tools:
        registry.register(tool)
    for tool in analytics_tools(client):
        registry.register(tool)
    for tool in cards_wealth_tools(client):
        registry.register(tool)
    for tool in savings_tools(client):
        registry.register(tool)
