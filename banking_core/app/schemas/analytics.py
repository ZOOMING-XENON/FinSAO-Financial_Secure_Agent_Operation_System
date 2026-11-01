from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from banking_core.app.domain.enums import Currency
from banking_core.app.domain.money import MoneyDecimal


class AnalyticsModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class SpendingSummaryResponse(BaseModel):
    total: Decimal
    by_category: dict[str, Decimal]
    by_merchant: dict[str, Decimal]


class CategoryCorrectionRequest(BaseModel):
    category: str = Field(min_length=1, max_length=80)


class BudgetRequest(BaseModel):
    category: str = Field(min_length=1, max_length=80)
    month: date
    limit_amount: MoneyDecimal = Field(gt=0)
    currency: Currency = Currency.CNY


class BudgetUpdateRequest(BaseModel):
    limit_amount: MoneyDecimal = Field(gt=0)


class BudgetResponse(AnalyticsModel):
    id: UUID
    category: str
    month: date
    limit_amount: Decimal
    currency: Currency


class BudgetStatusResponse(BaseModel):
    limit: Decimal
    used: Decimal
    remaining: Decimal
    estimate: Decimal
    threshold_exceeded: bool


class ReminderRequest(BaseModel):
    remind_on: date


class ReminderResponse(AnalyticsModel):
    id: UUID
    subscription_id: UUID
    remind_on: date
    delivered: bool


class SubscriptionResponse(AnalyticsModel):
    id: UUID
    merchant_name: str
    amount: Decimal
    currency: Currency
    next_billing_date: date
    active: bool
    status: str
    cancelled_at: datetime | None


class CancelSubscriptionRequest(BaseModel):
    authorization_ref: str

class ExpenseSummaryResponse(BaseModel):
    total: Decimal | None
    transaction_count: int
    totals_by_currency: dict[str, Decimal]
    by_category: dict[str, dict[str, Decimal]]
    by_merchant: dict[str, dict[str, Decimal]]

class ExpenseLabelWriteRequest(BaseModel):
    category: str = Field(min_length=1, max_length=80)
    source: Literal["JEV", "RULE"]
    observed_source: str | None = None
    observed_version: str | None = None
    version: str = Field(min_length=1, max_length=32)

class ExpenseLabelAttemptRequest(BaseModel):
    policy_version: str = Field(min_length=1, max_length=32)
    succeeded: bool
    error: str | None = Field(default=None, max_length=120)
