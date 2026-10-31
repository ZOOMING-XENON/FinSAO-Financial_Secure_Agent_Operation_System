from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from banking_core.app.domain.enums import (
    AccountStatus,
    CardStatus,
    Currency,
    RiskTier,
    TransactionStatus,
    TransferStatus,
    WealthOrderType,
)

MONEY = Numeric(precision=18, scale=2, asdecimal=True)


def enum_column(enum_type: type[Any], name: str) -> Enum:
    return Enum(
        enum_type,
        name=name,
        native_enum=False,
        create_constraint=True,
        validate_strings=True,
    )


class Base(DeclarativeBase):
    type_annotation_map = {dict[str, Any]: JSON().with_variant(JSONB(), "postgresql")}


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class UserModel(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    email: Mapped[str] = mapped_column(String(254), unique=True, nullable=False)
    risk_tier: Mapped[RiskTier] = mapped_column(
        enum_column(RiskTier, "risk_tier"), default=RiskTier.GREEN, nullable=False
    )


class AccountModel(TimestampMixin, Base):
    __tablename__ = "accounts"
    __table_args__ = (
        CheckConstraint(
            "(is_system AND user_id IS NULL) OR (NOT is_system AND user_id IS NOT NULL)",
            name="ck_accounts_owner_or_system",
        ),
        CheckConstraint(
            "balance >= 0 OR is_system", name="ck_accounts_customer_balance_nonnegative"
        ),
        Index("ix_accounts_user_id", "user_id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    account_number: Mapped[str] = mapped_column(String(34), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    currency: Mapped[Currency] = mapped_column(enum_column(Currency, "currency"), nullable=False)
    status: Mapped[AccountStatus] = mapped_column(
        enum_column(AccountStatus, "account_status"), nullable=False
    )
    balance: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0.00"), nullable=False)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class BeneficiaryModel(TimestampMixin, Base):
    __tablename__ = "beneficiaries"
    __table_args__ = (
        UniqueConstraint("user_id", "destination_account_id", name="uq_beneficiary_owner_target"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    nickname: Mapped[str | None] = mapped_column(String(80))
    destination_account_id: Mapped[UUID] = mapped_column(ForeignKey("accounts.id"), nullable=False)


class TransactionModel(TimestampMixin, Base):
    __tablename__ = "transactions"
    __table_args__ = (CheckConstraint("amount > 0", name="ck_transactions_positive_amount"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    reference: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    status: Mapped[TransactionStatus] = mapped_column(
        enum_column(TransactionStatus, "transaction_status"), nullable=False
    )
    amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    currency: Mapped[Currency] = mapped_column(enum_column(Currency, "currency"), nullable=False)
    description: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str | None] = mapped_column(String(80))
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)


class LedgerEntryModel(Base):
    __tablename__ = "ledger_entries"
    __table_args__ = (
        CheckConstraint(
            "(debit > 0 AND credit = 0) OR (credit > 0 AND debit = 0)",
            name="ck_ledger_exactly_one_side",
        ),
        UniqueConstraint("transaction_id", "account_id", name="uq_ledger_transaction_account"),
        Index("ix_ledger_account_created", "account_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    transaction_id: Mapped[UUID] = mapped_column(
        ForeignKey("transactions.id", ondelete="RESTRICT"), nullable=False
    )
    account_id: Mapped[UUID] = mapped_column(
        ForeignKey("accounts.id", ondelete="RESTRICT"), nullable=False
    )
    debit: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0.00"), nullable=False)
    credit: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0.00"), nullable=False)
    currency: Mapped[Currency] = mapped_column(enum_column(Currency, "currency"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class TransferDraftModel(TimestampMixin, Base):
    __tablename__ = "transfer_drafts"
    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_transfer_drafts_positive_amount"),
        UniqueConstraint("user_id", "idempotency_key", name="uq_transfer_user_idempotency"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    source_account_id: Mapped[UUID] = mapped_column(ForeignKey("accounts.id"), nullable=False)
    destination_account_id: Mapped[UUID] = mapped_column(ForeignKey("accounts.id"), nullable=False)
    amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    currency: Mapped[Currency] = mapped_column(enum_column(Currency, "currency"), nullable=False)
    status: Mapped[TransferStatus] = mapped_column(
        enum_column(TransferStatus, "transfer_status"), nullable=False
    )
    idempotency_key: Mapped[str | None] = mapped_column(String(120))
    request_hash: Mapped[str | None] = mapped_column(String(64))
    transaction_id: Mapped[UUID | None] = mapped_column(ForeignKey("transactions.id"))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class BudgetModel(TimestampMixin, Base):
    __tablename__ = "budgets"
    __table_args__ = (
        CheckConstraint("limit_amount > 0", name="ck_budgets_positive_limit"),
        UniqueConstraint("user_id", "category", "month", name="uq_budget_user_category_month"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    category: Mapped[str] = mapped_column(String(80), nullable=False)
    month: Mapped[date] = mapped_column(Date, nullable=False)
    limit_amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    currency: Mapped[Currency] = mapped_column(enum_column(Currency, "currency"), nullable=False)


class SubscriptionModel(TimestampMixin, Base):
    __tablename__ = "subscriptions"
    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_subscriptions_positive_amount"),
        UniqueConstraint("user_id", "merchant_name", name="uq_subscription_user_merchant"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    merchant_name: Mapped[str] = mapped_column(String(120), nullable=False)
    amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    currency: Mapped[Currency] = mapped_column(enum_column(Currency, "currency"), nullable=False)
    next_billing_date: Mapped[date] = mapped_column(Date, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="ACTIVE", nullable=False)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RenewalReminderModel(TimestampMixin, Base):
    __tablename__ = "renewal_reminders"
    __table_args__ = (
        UniqueConstraint("subscription_id", "remind_on", name="uq_reminder_subscription_date"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    subscription_id: Mapped[UUID] = mapped_column(ForeignKey("subscriptions.id"), nullable=False)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    remind_on: Mapped[date] = mapped_column(Date, nullable=False)
    delivered: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class CardModel(TimestampMixin, Base):
    __tablename__ = "cards"
    __table_args__ = (
        CheckConstraint("spending_limit > 0", name="ck_cards_positive_limit"),
        CheckConstraint("char_length(last_four) = 4", name="ck_cards_last_four_length"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    account_id: Mapped[UUID] = mapped_column(ForeignKey("accounts.id"), nullable=False, index=True)
    label: Mapped[str] = mapped_column(String(80), nullable=False)
    last_four: Mapped[str] = mapped_column(String(4), nullable=False)
    status: Mapped[CardStatus] = mapped_column(
        enum_column(CardStatus, "card_status"), nullable=False
    )
    spending_limit: Mapped[Decimal] = mapped_column(MONEY, nullable=False)


class WealthProductModel(TimestampMixin, Base):
    __tablename__ = "wealth_products"
    __table_args__ = (CheckConstraint("minimum_amount > 0", name="ck_wealth_positive_minimum"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    code: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    product_type: Mapped[str] = mapped_column(String(80), nullable=False)
    risk_tier: Mapped[RiskTier] = mapped_column(enum_column(RiskTier, "risk_tier"), nullable=False)
    minimum_amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    currency: Mapped[Currency] = mapped_column(enum_column(Currency, "currency"), nullable=False)
    supports_redemption: Mapped[bool] = mapped_column(default=True, nullable=False)


class RiskAssessmentModel(TimestampMixin, Base):
    __tablename__ = "risk_assessments"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    score: Mapped[int] = mapped_column(nullable=False)
    risk_tier: Mapped[RiskTier] = mapped_column(
        enum_column(RiskTier, "assessment_risk_tier"), nullable=False
    )


class WealthHoldingModel(TimestampMixin, Base):
    __tablename__ = "wealth_holdings"
    __table_args__ = (
        UniqueConstraint("user_id", "product_id", name="uq_holding_user_product"),
        CheckConstraint("amount >= 0", name="ck_holding_nonnegative"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    product_id: Mapped[UUID] = mapped_column(ForeignKey("wealth_products.id"), nullable=False)
    amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    currency: Mapped[Currency] = mapped_column(
        enum_column(Currency, "holding_currency"), nullable=False
    )


class WealthOrderModel(TimestampMixin, Base):
    __tablename__ = "wealth_orders"
    __table_args__ = (
        UniqueConstraint("user_id", "idempotency_key", name="uq_wealth_user_idempotency"),
        CheckConstraint("amount > 0", name="ck_wealth_order_positive"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    account_id: Mapped[UUID] = mapped_column(ForeignKey("accounts.id"), nullable=False)
    product_id: Mapped[UUID] = mapped_column(ForeignKey("wealth_products.id"), nullable=False)
    amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    currency: Mapped[Currency] = mapped_column(
        enum_column(Currency, "wealth_order_currency"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    order_type: Mapped[WealthOrderType] = mapped_column(
        enum_column(WealthOrderType, "wealth_order_type"),
        nullable=False,
        default=WealthOrderType.SUBSCRIPTION,
    )
    idempotency_key: Mapped[str] = mapped_column(String(120), nullable=False)
    transaction_id: Mapped[UUID | None] = mapped_column(ForeignKey("transactions.id"))


class SavingsPotModel(TimestampMixin, Base):
    __tablename__ = "savings_pots"
    __table_args__ = (
        CheckConstraint("target_amount > 0", name="ck_savings_pot_positive_target"),
        CheckConstraint("saved_amount >= 0", name="ck_savings_pot_nonnegative_saved"),
        UniqueConstraint("user_id", "idempotency_key", name="uq_savings_pot_user_key"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    target_amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    saved_amount: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0.00"), nullable=False)
    currency: Mapped[Currency] = mapped_column(
        enum_column(Currency, "savings_pot_currency"), nullable=False
    )
    target_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="ACTIVE", nullable=False)
    allocation_mode: Mapped[str] = mapped_column(
        String(32), default="ACCOUNT_FUNDED", nullable=False
    )
    idempotency_key: Mapped[str] = mapped_column(String(120), nullable=False)


class SavingsContributionModel(Base):
    __tablename__ = "savings_contributions"
    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_savings_contribution_positive"),
        UniqueConstraint("user_id", "idempotency_key", name="uq_savings_contribution_user_key"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    pot_id: Mapped[UUID] = mapped_column(
        ForeignKey("savings_pots.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    source_account_id: Mapped[UUID | None] = mapped_column(ForeignKey("accounts.id"))
    transaction_id: Mapped[UUID | None] = mapped_column(ForeignKey("transactions.id"))
    amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    note: Mapped[str | None] = mapped_column(String(255))
    idempotency_key: Mapped[str] = mapped_column(String(120), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class AuditEventModel(Base):
    __tablename__ = "audit_events"
    __table_args__ = (Index("ix_audit_actor_occurred", "actor_user_id", "occurred_at"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    actor_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(80), nullable=False)
    resource_id: Mapped[str | None] = mapped_column(String(80))
    trace_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    outcome: Mapped[str] = mapped_column(String(40), nullable=False)
    details: Mapped[dict[str, Any]] = mapped_column(default=dict, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ApprovalModel(TimestampMixin, Base):
    __tablename__ = "approvals"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    actor_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    operation_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    operation_type: Mapped[str] = mapped_column(String(100), nullable=False)
    target_account_id: Mapped[UUID | None] = mapped_column(ForeignKey("accounts.id"))
    recipient_id: Mapped[UUID | None] = mapped_column(ForeignKey("accounts.id"))
    amount: Mapped[Decimal | None] = mapped_column(MONEY)
    currency: Mapped[Currency | None] = mapped_column(enum_column(Currency, "approval_currency"))
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    risk_tier: Mapped[RiskTier] = mapped_column(
        enum_column(RiskTier, "approval_risk_tier"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AuthorizationGrantModel(Base):
    __tablename__ = "authorization_grants"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    approval_id: Mapped[UUID] = mapped_column(
        ForeignKey("approvals.id"), unique=True, nullable=False
    )
    operation_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    actor_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class MfaChallengeModel(Base):
    __tablename__ = "mfa_challenges"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    approval_id: Mapped[UUID] = mapped_column(
        ForeignKey("approvals.id"), nullable=False, index=True
    )
    actor_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    code_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    salt: Mapped[str] = mapped_column(String(64), nullable=False)
    attempts: Mapped[int] = mapped_column(default=0, nullable=False)
    max_attempts: Mapped[int] = mapped_column(default=3, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SafetyLockModel(Base):
    __tablename__ = "safety_locks"

    actor_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), primary_key=True)
    failure_count: Mapped[int] = mapped_column(default=0, nullable=False)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
