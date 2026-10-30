"""Load deterministic, fictional demo data. Safe to run repeatedly."""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Protocol, TypeVar
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import select
from sqlalchemy.orm import Session

from banking_core.app.domain.enums import (
    AccountStatus,
    CardStatus,
    Currency,
    RiskTier,
    TransactionStatus,
)
from banking_core.app.persistence.database import get_session_factory
from banking_core.app.persistence.models import (
    AccountModel,
    BeneficiaryModel,
    BudgetModel,
    CardModel,
    LedgerEntryModel,
    SavingsPotModel,
    SubscriptionModel,
    TransactionModel,
    UserModel,
    WealthProductModel,
)


class Identified(Protocol):
    id: UUID


ModelT = TypeVar("ModelT", bound=Identified)
SEED_NAMESPACE = uuid5(NAMESPACE_URL, "https://example.invalid/mock-banking-core/v1")
UTC = UTC

# Fictional saved recipients used to demonstrate natural-language beneficiary resolution.
DEMO_RECIPIENTS: tuple[tuple[str, str, str], ...] = (
    ("father", "爸爸", "299000000001"),
    ("mother", "妈妈", "390000000002"),
    ("grandfather", "爷爷", "299000000003"),
    ("grandmother", "奶奶", "390000000004"),
    ("maternal-grandfather", "外公", "299000000005"),
    ("maternal-grandmother", "外婆", "390000000006"),
    ("older-brother", "哥哥", "299000000007"),
    ("older-sister", "姐姐", "390000000008"),
    ("friend-wang", "好友小王", "299000000009"),
    ("friend-li", "好友小李", "390000000010"),
)


def stable_id(key: str) -> UUID:
    return uuid5(SEED_NAMESPACE, key)


def add_once(session: Session, model: ModelT) -> ModelT:
    model_id = model.id
    existing = session.get(type(model), model_id)
    if existing is not None:
        return existing
    session.add(model)
    return model


def add_posting(
    session: Session,
    *,
    key: str,
    debit_account_id: UUID,
    credit_account_id: UUID,
    amount: Decimal,
    posted_at: datetime,
    description: str,
    category: str,
) -> None:
    transaction_id = stable_id(f"transaction:{key}")
    add_once(
        session,
        TransactionModel(
            id=transaction_id,
            reference=f"DEMO-{key.upper()}",
            status=TransactionStatus.COMPLETED,
            amount=amount,
            currency=Currency.CNY,
            description=description,
            category=category,
            posted_at=posted_at,
        ),
    )
    add_once(
        session,
        LedgerEntryModel(
            id=stable_id(f"ledger:{key}:debit"),
            transaction_id=transaction_id,
            account_id=debit_account_id,
            debit=amount,
            credit=Decimal("0.00"),
            currency=Currency.CNY,
            created_at=posted_at,
        ),
    )
    add_once(
        session,
        LedgerEntryModel(
            id=stable_id(f"ledger:{key}:credit"),
            transaction_id=transaction_id,
            account_id=credit_account_id,
            debit=Decimal("0.00"),
            credit=amount,
            currency=Currency.CNY,
            created_at=posted_at,
        ),
    )


def seed(session: Session) -> None:
    users = [
        ("lin", "Lin Xiaoyu", "lin.xiaoyu@example.invalid", RiskTier.GREEN),
        ("chen", "Chen Ming", "chen.ming@example.invalid", RiskTier.YELLOW),
        ("zhou", "Zhou An", "zhou.an@example.invalid", RiskTier.RED),
    ]
    for key, name, email, tier in users:
        add_once(
            session,
            UserModel(id=stable_id(f"user:{key}"), display_name=name, email=email, risk_tier=tier),
        )

    for key, name, _ in DEMO_RECIPIENTS:
        add_once(
            session,
            UserModel(
                id=stable_id(f"user:demo-recipient:{key}"),
                display_name=name,
                email=f"demo-recipient-{key}@example.invalid",
                risk_tier=RiskTier.GREEN,
            ),
        )
    session.flush()

    system_account_id = stable_id("account:system:settlement")
    add_once(
        session,
        AccountModel(
            id=system_account_id,
            user_id=None,
            account_number="SYS-DEMO-SETTLEMENT",
            name="Demo Settlement Equity",
            currency=Currency.CNY,
            status=AccountStatus.ACTIVE,
            balance=Decimal("0.00"),
            is_system=True,
        ),
    )

    account_ids: dict[str, UUID] = {}
    for user_index, (user_key, _, _, _) in enumerate(users, start=1):
        for account_index, account_kind in enumerate(("checking", "savings"), start=1):
            account_key = f"{user_key}:{account_kind}"
            account_id = stable_id(f"account:{account_key}")
            account_ids[account_key] = account_id
            add_once(
                session,
                AccountModel(
                    id=account_id,
                    user_id=stable_id(f"user:{user_key}"),
                    account_number=f"DEMO{user_index:02d}{account_index:02d}000001",
                    name=account_kind.title(),
                    currency=Currency.CNY,
                    status=AccountStatus.ACTIVE,
                    balance=Decimal("0.00"),
                    is_system=False,
                ),
            )

    for key, name, account_number in DEMO_RECIPIENTS:
        add_once(
            session,
            AccountModel(
                id=stable_id(f"account:demo-recipient:{key}"),
                user_id=stable_id(f"user:demo-recipient:{key}"),
                account_number=account_number,
                name=f"{name}演示收款账户",
                currency=Currency.CNY,
                status=AccountStatus.ACTIVE,
                balance=Decimal("0.00"),
                is_system=False,
            ),
        )
    session.flush()

    for user_key, _, _, _ in users:
        add_once(
            session,
            BeneficiaryModel(
                id=stable_id(f"beneficiary:{user_key}:friend"),
                user_id=stable_id(f"user:{user_key}"),
                name="Demo Friend",
                nickname="Friend",
                destination_account_id=account_ids[
                    "chen:checking" if user_key != "chen" else "lin:checking"
                ],
            ),
        )
        for recipient_key, recipient_name, _ in DEMO_RECIPIENTS:
            add_once(
                session,
                BeneficiaryModel(
                    id=stable_id(f"beneficiary:{user_key}:{recipient_key}"),
                    user_id=stable_id(f"user:{user_key}"),
                    name=recipient_name,
                    nickname=None,
                    destination_account_id=stable_id(
                        f"account:demo-recipient:{recipient_key}"
                    ),
                ),
            )

    # Opening capital and all historical activity are represented by balanced postings.
    for user_number, (user_key, _, _, _) in enumerate(users):
        for account_kind, opening in (
            ("checking", Decimal("12000.00")),
            ("savings", Decimal("30000.00")),
        ):
            key = f"opening-{user_key}-{account_kind}"
            add_posting(
                session,
                key=key,
                debit_account_id=account_ids[f"{user_key}:{account_kind}"],
                credit_account_id=system_account_id,
                amount=opening,
                posted_at=datetime(2026, 1, 1, 8, 0, tzinfo=UTC),
                description="Deterministic demo opening balance",
                category="OPENING_BALANCE",
            )

        for month, amount in ((1, "128.40"), (2, "156.80"), (3, "142.60")):
            add_posting(
                session,
                key=f"expense-{user_key}-2026-{month:02d}",
                debit_account_id=system_account_id,
                credit_account_id=account_ids[f"{user_key}:checking"],
                amount=Decimal(amount),
                posted_at=datetime(2026, month, 15, 12, 0, tzinfo=UTC),
                description="Fictional monthly household purchase",
                category="HOUSEHOLD",
            )

        add_once(
            session,
            SubscriptionModel(
                id=stable_id(f"subscription:{user_key}"),
                user_id=stable_id(f"user:{user_key}"),
                merchant_name=f"Demo Stream {user_key.title()}",
                amount=Decimal("25.00"),
                currency=Currency.CNY,
                next_billing_date=date(2026, 4, 15),
                active=True,
            ),
        )
        add_once(
            session,
            BudgetModel(
                id=stable_id(f"budget:{user_key}:2026-03"),
                user_id=stable_id(f"user:{user_key}"),
                category="HOUSEHOLD",
                month=date(2026, 3, 1),
                limit_amount=Decimal("1500.00"),
                currency=Currency.CNY,
            ),
        )
        add_once(
            session,
            CardModel(
                id=stable_id(f"card:{user_key}"),
                account_id=account_ids[f"{user_key}:checking"],
                label="Fictional Demo Card",
                last_four=f"{1000 + user_number:04d}",
                status=CardStatus.ACTIVE,
                spending_limit=Decimal("5000.00"),
            ),
        )
        add_once(
            session,
            SavingsPotModel(
                id=stable_id(f"savings-pot:{user_key}:travel"),
                user_id=stable_id(f"user:{user_key}"),
                name="Demo Travel Fund",
                target_amount=Decimal("8000.00"),
                saved_amount=Decimal("2400.00"),
                currency=Currency.CNY,
                target_date=date(2027, 5, 1),
                status="ACTIVE",
                allocation_mode="VIRTUAL_ALLOCATION",
                idempotency_key=f"seed-{user_key}-travel",
            ),
        )

    for code, name, product_type, tier, minimum, redeemable in [
        ("DEMO-MMF-01", "Demo Liquidity Fund", "MONEY_MARKET_FUND", RiskTier.GREEN, "100.00", True),
        ("DEMO-BOND-01", "Demo Steady Bond Fund", "BOND_FUND", RiskTier.YELLOW, "1000.00", True),
        ("DEMO-GOV-01", "Demo Government Bond", "GOVERNMENT_BOND", RiskTier.GREEN, "1000.00", True),
        (
            "DEMO-FIXED-01",
            "Demo Fixed Income Plan",
            "FIXED_INCOME",
            RiskTier.YELLOW,
            "5000.00",
            False,
        ),
    ]:
        product = add_once(
            session,
            WealthProductModel(
                id=stable_id(f"wealth:{code}"),
                code=code,
                name=name,
                product_type=product_type,
                risk_tier=tier,
                minimum_amount=Decimal(minimum),
                currency=Currency.CNY,
                supports_redemption=redeemable,
            ),
        )
        product.supports_redemption = redeemable

    session.flush()
    totals: defaultdict[UUID, Decimal] = defaultdict(lambda: Decimal("0.00"))
    for entry in session.scalars(select(LedgerEntryModel)):
        totals[entry.account_id] += entry.debit - entry.credit
    for account in session.scalars(select(AccountModel)):
        account.balance = totals[account.id]


def main() -> None:
    with get_session_factory()() as session, session.begin():
        seed(session)
    print("Demo data seeded successfully (idempotent).")


if __name__ == "__main__":
    main()
