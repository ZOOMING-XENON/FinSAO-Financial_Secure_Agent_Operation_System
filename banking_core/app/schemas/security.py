from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from banking_core.app.domain.enums import Currency, RiskTier
from banking_core.app.domain.money import MoneyDecimal
from banking_core.app.security.models import ApprovalStatus


class SecurityModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class CreateApprovalRequest(BaseModel):
    operation_id: UUID
    operation_type: str | None = None
    target_account_id: UUID | None = None
    amount: MoneyDecimal | None = None


class ApprovalResponse(SecurityModel):
    id: UUID
    operation_id: UUID
    operation_type: str
    target_account_id: UUID | None
    recipient_id: UUID | None
    amount: Decimal | None
    currency: Currency | None
    risk_tier: RiskTier
    status: ApprovalStatus
    expires_at: datetime


class ApprovalDecisionRequest(BaseModel):
    accepted: bool


class AuthorizationResponse(SecurityModel):
    authorization_ref: UUID
    expires_at: datetime


class MfaChallengeResponse(SecurityModel):
    challenge_id: UUID
    expires_at: datetime


class MfaVerifyRequest(BaseModel):
    code: str = Field(pattern=r"^\d{6}$")
