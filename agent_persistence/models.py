from __future__ import annotations

from datetime import datetime, time
from typing import Any
from uuid import UUID

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, Time, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class AgentSessionModel(Base):
    __tablename__ = "agent_sessions"
    id: Mapped[UUID] = mapped_column(primary_key=True)
    user_id: Mapped[UUID] = mapped_column(index=True)
    status: Mapped[str] = mapped_column(String(24))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AgentTaskModel(Base):
    __tablename__ = "agent_tasks"
    id: Mapped[UUID] = mapped_column(primary_key=True)
    session_id: Mapped[UUID] = mapped_column(ForeignKey("agent_sessions.id"), index=True)
    trace_id: Mapped[UUID]
    status: Mapped[str] = mapped_column(String(32), index=True)
    request_message: Mapped[str] = mapped_column(Text)
    public_message: Mapped[str | None] = mapped_column(Text)
    plan: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    result: Mapped[Any | None] = mapped_column(JSONB)
    error_code: Mapped[str | None] = mapped_column(String(80))
    recovery_action: Mapped[str | None] = mapped_column(String(40))
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AgentTaskBundleModel(Base):
    __tablename__ = "agent_task_bundles"
    id: Mapped[UUID] = mapped_column(primary_key=True)
    session_id: Mapped[UUID] = mapped_column(ForeignKey("agent_sessions.id"), index=True)
    original_request: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), index=True)
    active_item_id: Mapped[UUID | None]
    revision: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AgentBundleItemModel(Base):
    __tablename__ = "agent_bundle_items"
    __table_args__ = (UniqueConstraint("bundle_id", "item_key"),)
    id: Mapped[UUID] = mapped_column(primary_key=True)
    bundle_id: Mapped[UUID] = mapped_column(ForeignKey("agent_task_bundles.id"), index=True)
    item_key: Mapped[str] = mapped_column(String(40))
    intent: Mapped[str] = mapped_column(String(48))
    evidence: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), index=True)
    depends_on: Mapped[list[str]] = mapped_column(JSONB)
    proposed_slots: Mapped[dict[str, Any]] = mapped_column(JSONB)
    confirmed_fields: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    clarification: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    plan: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    result: Mapped[Any | None] = mapped_column(JSONB)
    task_id: Mapped[UUID | None] = mapped_column(ForeignKey("agent_tasks.id"), index=True)
    error_code: Mapped[str | None] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AgentSessionMessageModel(Base):
    __tablename__ = "agent_session_messages"
    __table_args__ = (UniqueConstraint("session_id", "sequence"),)
    id: Mapped[UUID] = mapped_column(primary_key=True)
    session_id: Mapped[UUID] = mapped_column(ForeignKey("agent_sessions.id"), index=True)
    sequence: Mapped[int]
    role: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AgentEventModel(Base):
    __tablename__ = "agent_events"
    __table_args__ = (UniqueConstraint("task_id", "sequence"),)
    id: Mapped[UUID] = mapped_column(primary_key=True)
    task_id: Mapped[UUID] = mapped_column(ForeignKey("agent_tasks.id"), index=True)
    sequence: Mapped[int]
    event_type: Mapped[str] = mapped_column(String(48))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ProactiveSubscriptionModel(Base):
    __tablename__ = "agent_proactive_subscriptions"
    __table_args__ = (UniqueConstraint("user_id", "event_kind"),)
    id: Mapped[UUID] = mapped_column(primary_key=True)
    user_id: Mapped[UUID] = mapped_column(index=True)
    event_kind: Mapped[str] = mapped_column(String(48))
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    quiet_start: Mapped[time | None] = mapped_column(Time)
    quiet_end: Mapped[time | None] = mapped_column(Time)
    minimum_interval_minutes: Mapped[int] = mapped_column(Integer, default=1440)
    last_emitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
