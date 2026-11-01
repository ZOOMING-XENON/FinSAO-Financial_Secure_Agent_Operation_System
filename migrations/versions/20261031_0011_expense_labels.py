"""Add expense category provenance metadata."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261031_0011"
down_revision: str | None = "20261031_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("transactions", sa.Column("category_source", sa.String(16), nullable=True))
    op.add_column("transactions", sa.Column("category_version", sa.String(32), nullable=True))
    op.add_column(
        "transactions",
        sa.Column("category_labeled_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        "UPDATE transactions SET category_source = 'RULE', category_version = 'legacy' "
        "WHERE category IS NOT NULL"
    )


def downgrade() -> None:
    op.drop_column("transactions", "category_labeled_at")
    op.drop_column("transactions", "category_version")
    op.drop_column("transactions", "category_source")
