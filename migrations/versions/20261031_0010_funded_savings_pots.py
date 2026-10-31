"""Make savings-pot contributions account-funded and auditable."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261031_0010"
down_revision: str | None = "20261027_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "savings_contributions",
        sa.Column("source_account_id", sa.Uuid(), nullable=True),
    )
    op.add_column(
        "savings_contributions",
        sa.Column("transaction_id", sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        "fk_savings_contributions_source_account",
        "savings_contributions",
        "accounts",
        ["source_account_id"],
        ["id"],
    )
    op.create_foreign_key(
        "fk_savings_contributions_transaction",
        "savings_contributions",
        "transactions",
        ["transaction_id"],
        ["id"],
    )
    op.execute(
        "UPDATE savings_pots SET allocation_mode = 'ACCOUNT_FUNDED' "
        "WHERE allocation_mode = 'VIRTUAL_ALLOCATION'"
    )
    op.alter_column(
        "savings_pots",
        "allocation_mode",
        server_default="ACCOUNT_FUNDED",
    )


def downgrade() -> None:
    op.alter_column(
        "savings_pots",
        "allocation_mode",
        server_default="VIRTUAL_ALLOCATION",
    )
    op.execute(
        "UPDATE savings_pots SET allocation_mode = 'VIRTUAL_ALLOCATION' "
        "WHERE allocation_mode = 'ACCOUNT_FUNDED'"
    )
    op.drop_constraint(
        "fk_savings_contributions_transaction",
        "savings_contributions",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_savings_contributions_source_account",
        "savings_contributions",
        type_="foreignkey",
    )
    op.drop_column("savings_contributions", "transaction_id")
    op.drop_column("savings_contributions", "source_account_id")
