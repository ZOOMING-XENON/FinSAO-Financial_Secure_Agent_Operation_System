"""add agent task bundles and session messages

Revision ID: 20261102_0014
Revises: 20261101_0013
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261102_0014"
down_revision: str | None = "20261101_0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agent_task_bundles",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "session_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agent_sessions.id"),
            nullable=False,
            index=True,
        ),
        sa.Column("original_request", sa.Text(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, index=True),
        sa.Column("active_item_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "agent_bundle_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "bundle_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agent_task_bundles.id"),
            nullable=False,
            index=True,
        ),
        sa.Column("item_key", sa.String(40), nullable=False),
        sa.Column("intent", sa.String(48), nullable=False),
        sa.Column("evidence", sa.Text(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, index=True),
        sa.Column("depends_on", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("proposed_slots", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("confirmed_fields", postgresql.JSONB(), nullable=True),
        sa.Column("clarification", postgresql.JSONB(), nullable=True),
        sa.Column("plan", postgresql.JSONB(), nullable=True),
        sa.Column("result", postgresql.JSONB(), nullable=True),
        sa.Column(
            "task_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agent_tasks.id"),
            nullable=True,
            index=True,
        ),
        sa.Column("error_code", sa.String(80), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("bundle_id", "item_key", name="uq_agent_bundle_item_key"),
    )
    op.create_table(
        "agent_session_messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "session_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agent_sessions.id"),
            nullable=False,
            index=True,
        ),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("session_id", "sequence", name="uq_agent_session_message_sequence"),
    )


def downgrade() -> None:
    op.drop_table("agent_session_messages")
    op.drop_table("agent_bundle_items")
    op.drop_table("agent_task_bundles")
