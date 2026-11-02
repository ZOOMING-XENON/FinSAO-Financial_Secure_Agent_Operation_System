"""Interest on savings pots: per-pot rate, accrual state and a payment history."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261102_0015"
down_revision: str | None = "20261102_0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "savings_pots",
        sa.Column(
            "interest_rate", sa.Numeric(6, 4), nullable=False, server_default="0.0150"
        ),
    )
    op.add_column("savings_pots", sa.Column("interest_accrued_until", sa.Date(), nullable=True))
    op.add_column(
        "savings_pots",
        sa.Column("interest_carry", sa.Numeric(18, 8), nullable=False, server_default="0"),
    )
    op.add_column(
        "savings_pots",
        sa.Column("interest_earned", sa.Numeric(18, 2), nullable=False, server_default="0"),
    )
    op.create_check_constraint(
        "ck_savings_pot_interest_rate", "savings_pots", "interest_rate >= 0 AND interest_rate < 1"
    )
    op.create_table(
        "savings_interest_payments",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "pot_id",
            sa.Uuid(),
            sa.ForeignKey("savings_pots.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("rate", sa.Numeric(6, 4), nullable=False),
        sa.Column("balance", sa.Numeric(18, 2), nullable=False),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("amount > 0", name="ck_savings_interest_positive"),
        sa.CheckConstraint("period_end > period_start", name="ck_savings_interest_period"),
        sa.UniqueConstraint("pot_id", "period_end", name="uq_savings_interest_pot_period"),
    )
    op.create_index(
        "ix_savings_interest_payments_pot_id", "savings_interest_payments", ["pot_id"]
    )
    op.create_index(
        "ix_savings_interest_payments_user_id", "savings_interest_payments", ["user_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_savings_interest_payments_user_id", "savings_interest_payments")
    op.drop_index("ix_savings_interest_payments_pot_id", "savings_interest_payments")
    op.drop_table("savings_interest_payments")
    op.drop_constraint("ck_savings_pot_interest_rate", "savings_pots", type_="check")
    op.drop_column("savings_pots", "interest_earned")
    op.drop_column("savings_pots", "interest_carry")
    op.drop_column("savings_pots", "interest_accrued_until")
    op.drop_column("savings_pots", "interest_rate")
