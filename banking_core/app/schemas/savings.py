from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from banking_core.app.domain.enums import Currency
from banking_core.app.domain.money import MoneyDecimal


class SavingsModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class SavingsPotCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    target_amount: MoneyDecimal = Field(gt=0)
    currency: Currency = Currency.CNY
    target_date: date
    idempotency_key: str = Field(min_length=1, max_length=120)


class SavingsPotUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    target_amount: MoneyDecimal | None = Field(default=None, gt=0)
    target_date: date | None = None


class SavingsPotResponse(SavingsModel):
    id: UUID
    name: str
    target_amount: Decimal
    saved_amount: Decimal
    currency: Currency
    target_date: date
    status: str
    allocation_mode: Literal["ACCOUNT_FUNDED"]
    created_at: datetime
    updated_at: datetime


class SavingsContributionRequest(BaseModel):
    source_account_id: UUID
    amount: MoneyDecimal = Field(gt=0)
    note: str | None = Field(default=None, max_length=255)
    idempotency_key: str = Field(min_length=1, max_length=120)
    authorization_ref: UUID


class SavingsContributionResponse(SavingsModel):
    id: UUID
    pot_id: UUID
    # Nullable only for contribution rows created before funded pots were introduced.
    source_account_id: UUID | None
    transaction_id: UUID | None
    amount: Decimal
    note: str | None
    created_at: datetime
