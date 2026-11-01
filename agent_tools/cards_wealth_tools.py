from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, RootModel

from agent_tools.client import BankingClientError, BankingHttpClient
from agent_tools.contracts import BaseBankingTool, ExecutionContext
from banking_core.app.domain.enums import CardStatus, Currency, RiskTier, WealthOrderType
from banking_core.app.domain.money import MoneyDecimal


class NoInput(BaseModel):
    pass


class ResourceInput(BaseModel):
    resource_id: UUID


class CardLimitInput(BaseModel):
    card_id: UUID
    spending_limit: MoneyDecimal = Field(gt=0)


class ProductFilterInput(BaseModel):
    product_type: str | None = None
    risk_tier: str | None = None


class CompareInput(BaseModel):
    product_ids: list[UUID] = Field(min_length=2, max_length=10)


class RiskInput(BaseModel):
    answers: list[int] = Field(min_length=5, max_length=5)


class WealthDraftInput(BaseModel):
    account_id: UUID
    product_id: UUID
    amount: MoneyDecimal = Field(gt=0)
    idempotency_key: str


class CardOutput(BaseModel):
    id: UUID
    account_id: UUID
    label: str
    last_four: str
    status: CardStatus
    spending_limit: Decimal


class CardListOutput(BaseModel):
    items: list[CardOutput]


class ProductOutput(BaseModel):
    id: UUID
    code: str
    name: str
    product_type: str
    risk_tier: RiskTier
    minimum_amount: Decimal
    currency: Currency
    supports_redemption: bool


class ProductListOutput(BaseModel):
    items: list[ProductOutput]


class RiskOutput(BaseModel):
    id: UUID
    score: int
    risk_tier: RiskTier


class HoldingOutput(BaseModel):
    id: UUID
    product_id: UUID
    amount: Decimal
    currency: Currency


class HoldingListOutput(BaseModel):
    items: list[HoldingOutput]


class WealthOrderOutput(BaseModel):
    id: UUID
    account_id: UUID
    product_id: UUID
    amount: Decimal
    currency: Currency
    status: str
    order_type: WealthOrderType
    transaction_id: UUID | None


class EndpointTool(BaseBankingTool[BaseModel, BaseModel]):
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
        list_response: bool = False,
    ) -> None:
        self.client = client
        self.name, self.description, self.action = name, description, action
        self.risk_policy, self.input_model, self.output_model = risk, input_model, output_model
        self.mutates_data = name in {
            "update_card_limit",
            "freeze_card",
            "unfreeze_card",
            "report_card_lost",
            "assess_risk_profile",
            "create_wealth_subscription_draft",
            "commit_wealth_subscription",
            "create_wealth_redemption_draft",
            "commit_wealth_redemption",
        }
        self.method, self.path, self.list_response = method, path, list_response

    async def execute(self, input_data: BaseModel, context: ExecutionContext) -> BaseModel:
        values = input_data.model_dump(mode="json", exclude_none=True)
        idempotency_key = values.get("idempotency_key")
        path = self.path.format(**values)
        for key in ("resource_id", "card_id"):
            values.pop(key, None)
        if self.name in {
            "update_card_limit",
            "freeze_card",
            "unfreeze_card",
            "report_card_lost",
            "commit_wealth_subscription",
            "commit_wealth_redemption",
        }:
            if context.authorization_reference is None:
                raise BankingClientError(
                    "AUTHORIZATION_REQUIRED", "trusted MFA authorization required", 403
                )
            values["authorization_ref"] = context.authorization_reference
        is_get = self.method == "GET"
        if self.list_response:
            response = await self.client.request(
                self.method,
                path,
                context,
                RootModel[list[dict[str, Any]]],
                params=values if is_get else None,
                json=None if is_get else values,
                idempotency_key=str(idempotency_key) if idempotency_key else None,
                mutation=not is_get,
            )
            return self.output_model.model_validate({"items": response.root})
        return await self.client.request(
            self.method,
            path,
            context,
            self.output_model,
            params=values if is_get else None,
            json=None if is_get else values,
            idempotency_key=str(idempotency_key) if idempotency_key else None,
            mutation=not is_get,
        )


def cards_wealth_tools(client: BankingHttpClient) -> list[BaseBankingTool[Any, Any]]:
    specs: list[tuple[str, str, str, str, type[BaseModel], type[BaseModel], str, str, bool]] = [
        (
            "list_cards",
            "List cards",
            "cards.list",
            "GREEN",
            NoInput,
            CardListOutput,
            "GET",
            "/cards",
            True,
        ),
        (
            "get_card_status",
            "Get current card details and operation status",
            "cards.status",
            "GREEN",
            ResourceInput,
            CardOutput,
            "GET",
            "/cards/{resource_id}",
            False,
        ),
        (
            "update_card_limit",
            "Update card limit",
            "card.limit",
            "YELLOW",
            CardLimitInput,
            CardOutput,
            "PATCH",
            "/cards/{card_id}/limit",
            False,
        ),
        (
            "freeze_card",
            "Freeze a card",
            "card.freeze",
            "YELLOW",
            ResourceInput,
            CardOutput,
            "POST",
            "/cards/{resource_id}/freeze",
            False,
        ),
        (
            "unfreeze_card",
            "Unfreeze a card",
            "card.unfreeze",
            "YELLOW",
            ResourceInput,
            CardOutput,
            "POST",
            "/cards/{resource_id}/unfreeze",
            False,
        ),
        (
            "report_card_lost",
            "Report a card lost",
            "card.report_lost",
            "RED",
            ResourceInput,
            CardOutput,
            "POST",
            "/cards/{resource_id}/report-lost",
            False,
        ),
        (
            "list_wealth_products",
            "List mock wealth products",
            "wealth.list",
            "GREEN",
            ProductFilterInput,
            ProductListOutput,
            "GET",
            "/wealth/products",
            True,
        ),
        (
            "compare_wealth_products",
            "Compare mock products",
            "wealth.compare",
            "GREEN",
            CompareInput,
            ProductListOutput,
            "POST",
            "/wealth/products/compare",
            True,
        ),
        (
            "get_wealth_recommendations",
            "List products allowed by the latest deterministic risk assessment",
            "wealth.recommendations",
            "GREEN",
            NoInput,
            ProductListOutput,
            "GET",
            "/wealth/recommendations",
            True,
        ),
        (
            "assess_risk_profile",
            "Run deterministic risk assessment",
            "wealth.assess",
            "GREEN",
            RiskInput,
            RiskOutput,
            "POST",
            "/wealth/risk-assessment",
            False,
        ),
        (
            "get_holdings",
            "List mock holdings",
            "wealth.holdings",
            "GREEN",
            NoInput,
            HoldingListOutput,
            "GET",
            "/wealth/holdings",
            True,
        ),
        (
            "create_wealth_subscription_draft",
            "Prepare mock wealth order",
            "wealth.draft",
            "RED",
            WealthDraftInput,
            WealthOrderOutput,
            "POST",
            "/wealth/orders",
            False,
        ),
        (
            "commit_wealth_subscription",
            "Commit authorized mock wealth order",
            "wealth.subscribe",
            "RED",
            ResourceInput,
            WealthOrderOutput,
            "POST",
            "/wealth/orders/{resource_id}/commit",
            False,
        ),
        (
            "create_wealth_redemption_draft",
            "Prepare a supported mock wealth redemption",
            "wealth.redemption_draft",
            "RED",
            WealthDraftInput,
            WealthOrderOutput,
            "POST",
            "/wealth/redemptions",
            False,
        ),
        (
            "get_wealth_order_status",
            "Get persisted wealth order status",
            "wealth.status",
            "GREEN",
            ResourceInput,
            WealthOrderOutput,
            "GET",
            "/wealth/orders/{resource_id}",
            False,
        ),
        (
            "commit_wealth_redemption",
            "Commit an authorized mock wealth redemption",
            "wealth.redeem",
            "RED",
            ResourceInput,
            WealthOrderOutput,
            "POST",
            "/wealth/orders/{resource_id}/commit",
            False,
        ),
    ]
    return [
        EndpointTool(
            client,
            name=name,
            description=description,
            action=action,
            risk=risk,
            input_model=input_model,
            output_model=output_model,
            method=method,
            path=path,
            list_response=list_response,
        )
        for (
            name,
            description,
            action,
            risk,
            input_model,
            output_model,
            method,
            path,
            list_response,
        ) in specs
    ]
