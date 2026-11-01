"""Add transaction ownership, kind, origin, merchant, and manual-expense metadata."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261101_0013"
down_revision: str | None = "20261031_0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

transaction_kind = sa.Enum(
    "EXPENSE",
    "INCOME",
    "REFUND",
    "TRANSFER",
    "OPENING_BALANCE",
    "ADJUSTMENT",
    name="transaction_kind",
    native_enum=False,
    create_constraint=True,
)
transaction_origin = sa.Enum(
    "BANK",
    "CARD",
    "CASH",
    "MANUAL",
    "IMPORT",
    name="transaction_origin",
    native_enum=False,
    create_constraint=True,
)


def upgrade() -> None:
    op.add_column("transactions", sa.Column("user_id", sa.Uuid(), nullable=True))
    op.add_column("transactions", sa.Column("account_id", sa.Uuid(), nullable=True))
    op.add_column(
        "transactions",
        sa.Column("kind", transaction_kind, nullable=False, server_default="EXPENSE"),
    )
    op.add_column(
        "transactions",
        sa.Column("origin", transaction_origin, nullable=False, server_default="BANK"),
    )
    op.add_column("transactions", sa.Column("merchant", sa.String(length=120), nullable=True))
    op.add_column(
        "transactions", sa.Column("idempotency_key", sa.String(length=120), nullable=True)
    )
    op.add_column(
        "transactions",
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_transactions_user_id_users", "transactions", "users", ["user_id"], ["id"]
    )
    op.create_foreign_key(
        "fk_transactions_account_id_accounts", "transactions", "accounts", ["account_id"], ["id"]
    )
    op.create_unique_constraint(
        "uq_transactions_user_idempotency", "transactions", ["user_id", "idempotency_key"]
    )
    op.create_index(
        "ix_transactions_user_kind_posted", "transactions", ["user_id", "kind", "posted_at"]
    )
    op.create_index(
        "ix_transactions_account_posted", "transactions", ["account_id", "posted_at"]
    )

    # A transaction belongs to the owner of the account whose ledger entry records
    # the money impact. For a transfer, the credit entry is the source account.
    op.execute(
        """
        UPDATE transactions AS t
        SET user_id = a.user_id, account_id = a.id
        FROM ledger_entries AS le
        JOIN accounts AS a ON a.id = le.account_id
        WHERE le.transaction_id = t.id
          AND le.credit > 0
          AND a.user_id IS NOT NULL
          AND t.user_id IS NULL
        """
    )
    op.execute(
        """
        UPDATE transactions AS t
        SET user_id = a.user_id, account_id = a.id
        FROM ledger_entries AS le
        JOIN accounts AS a ON a.id = le.account_id
        WHERE le.transaction_id = t.id
          AND a.user_id IS NOT NULL
          AND t.user_id IS NULL
        """
    )
    op.execute(
        """
        UPDATE transactions
        SET kind = 'OPENING_BALANCE'
        WHERE category = 'OPENING_BALANCE'
        """
    )
    op.execute(
        """
        UPDATE transactions
        SET kind = 'TRANSFER'
        WHERE category IN ('INTERNAL_TRANSFER', 'SAVINGS', 'WEALTH')
        """
    )
    op.execute(
        """
        UPDATE transactions AS t
        SET kind = 'INCOME'
        WHERE t.kind = 'EXPENSE'
          AND EXISTS (
              SELECT 1
              FROM ledger_entries AS le
              JOIN accounts AS a ON a.id = le.account_id
              WHERE le.transaction_id = t.id
                AND le.debit > 0
                AND a.user_id IS NOT NULL
          )
          AND NOT EXISTS (
              SELECT 1
              FROM ledger_entries AS le
              JOIN accounts AS a ON a.id = le.account_id
              WHERE le.transaction_id = t.id
                AND le.credit > 0
                AND a.user_id IS NOT NULL
          )
        """
    )
    op.execute(
        """
        UPDATE transactions
        SET merchant = description
        WHERE kind = 'EXPENSE' AND merchant IS NULL
        """
    )


def downgrade() -> None:
    op.drop_index("ix_transactions_account_posted", table_name="transactions")
    op.drop_index("ix_transactions_user_kind_posted", table_name="transactions")
    op.drop_constraint(
        "uq_transactions_user_idempotency", "transactions", type_="unique"
    )
    op.drop_constraint("fk_transactions_account_id_accounts", "transactions", type_="foreignkey")
    op.drop_constraint("fk_transactions_user_id_users", "transactions", type_="foreignkey")
    op.drop_column("transactions", "deleted_at")
    op.drop_column("transactions", "idempotency_key")
    op.drop_column("transactions", "merchant")
    op.drop_column("transactions", "origin")
    op.drop_column("transactions", "kind")
    op.drop_column("transactions", "account_id")
    op.drop_column("transactions", "user_id")
