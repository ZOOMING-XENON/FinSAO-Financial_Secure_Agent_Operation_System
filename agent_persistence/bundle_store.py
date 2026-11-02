"""Persistence adapters for multi-intent task bundles and session memory."""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from typing import Any, Protocol, cast
from uuid import UUID, uuid4

from sqlalchemy import Engine, delete, func, select
from sqlalchemy.orm import sessionmaker

from agent.bundle_contracts import (
    AgentTaskBundle,
    AgentTaskItem,
    BundleItemStatus,
    BundleStatus,
    ProposedTask,
)
from agent.contracts import ClarificationPayload, ConversationMessage, ConversationRole, TaskPlan
from agent.routing import Intent
from agent_persistence.models import (
    AgentBundleItemModel,
    AgentSessionMessageModel,
    AgentSessionModel,
    AgentTaskBundleModel,
)


class BundleStore(Protocol):
    def create_bundle(
        self, *, user_id: UUID, session_id: UUID, original_request: str, tasks: list[ProposedTask]
    ) -> AgentTaskBundle: ...

    def get_bundle(self, *, bundle_id: UUID, user_id: UUID) -> AgentTaskBundle | None: ...

    def update_item(
        self,
        *,
        bundle_id: UUID,
        user_id: UUID,
        item_id: UUID,
        status: BundleItemStatus,
        intent: Intent | None = None,
        clarification: ClarificationPayload | None = None,
        plan: TaskPlan | None = None,
        result: Any | None = None,
        task_id: UUID | None = None,
        error_code: str | None = None,
        confirmed_fields: dict[str, Any] | None = None,
    ) -> AgentTaskBundle: ...

    def update_bundle(
        self,
        *,
        bundle_id: UUID,
        user_id: UUID,
        status: BundleStatus,
        active_item_id: UUID | None,
    ) -> AgentTaskBundle: ...

    def append_message(
        self, *, user_id: UUID, session_id: UUID, role: ConversationRole, content: str
    ) -> None: ...

    def recent_messages(
        self, *, user_id: UUID, session_id: UUID, limit: int = 20
    ) -> list[ConversationMessage]: ...


class MemoryBundleStore:
    def __init__(self) -> None:
        self._owners: dict[UUID, UUID] = {}
        self._bundles: dict[UUID, AgentTaskBundle] = {}
        self._messages: dict[UUID, list[ConversationMessage]] = defaultdict(list)

    def create_bundle(
        self, *, user_id: UUID, session_id: UUID, original_request: str, tasks: list[ProposedTask]
    ) -> AgentTaskBundle:
        bundle_id = uuid4()
        items = [
            AgentTaskItem(
                item_id=uuid4(),
                item_key=task.item_key,
                intent=task.intent,
                evidence=task.evidence,
                proposed_slots=task.proposed_slots,
                status=BundleItemStatus.PROPOSED,
                depends_on=task.depends_on,
            )
            for task in tasks
        ]
        bundle = AgentTaskBundle(
            bundle_id=bundle_id,
            session_id=session_id,
            original_request=original_request,
            status=BundleStatus.RUNNING,
            active_item_id=items[0].item_id if items else None,
            items=items,
        )
        self._owners[bundle_id] = user_id
        self._bundles[bundle_id] = bundle
        return bundle.model_copy(deep=True)

    def get_bundle(self, *, bundle_id: UUID, user_id: UUID) -> AgentTaskBundle | None:
        if self._owners.get(bundle_id) != user_id:
            return None
        return self._bundles[bundle_id].model_copy(deep=True)

    def update_item(self, **kwargs: Any) -> AgentTaskBundle:
        bundle = self._owned(kwargs["bundle_id"], kwargs["user_id"])
        item_id = kwargs["item_id"]
        updates = {
            name: value
            for name, value in kwargs.items()
            if name
            in {"status", "intent", "clarification", "plan", "result", "task_id", "error_code"}
            and value is not None
        }
        bundle.items = [
            item.model_copy(update=updates) if item.item_id == item_id else item
            for item in bundle.items
        ]
        bundle.revision += 1
        return bundle.model_copy(deep=True)

    def update_bundle(self, **kwargs: Any) -> AgentTaskBundle:
        bundle = self._owned(kwargs["bundle_id"], kwargs["user_id"])
        bundle.status = kwargs["status"]
        bundle.active_item_id = kwargs["active_item_id"]
        bundle.revision += 1
        return bundle.model_copy(deep=True)

    def append_message(
        self, *, user_id: UUID, session_id: UUID, role: ConversationRole, content: str
    ) -> None:
        del user_id
        self._messages[session_id] = [
            *self._messages[session_id],
            ConversationMessage(role=role, content=content),
        ][-20:]

    def recent_messages(
        self, *, user_id: UUID, session_id: UUID, limit: int = 20
    ) -> list[ConversationMessage]:
        del user_id
        return list(self._messages[session_id][-limit:])

    def _owned(self, bundle_id: UUID, user_id: UUID) -> AgentTaskBundle:
        bundle = self.get_bundle(bundle_id=bundle_id, user_id=user_id)
        if bundle is None:
            raise KeyError(bundle_id)
        self._bundles[bundle_id] = bundle
        return bundle


class SqlAlchemyBundleStore:
    def __init__(self, engine: Engine) -> None:
        self._sessions = sessionmaker(bind=engine, expire_on_commit=False)

    def create_bundle(
        self, *, user_id: UUID, session_id: UUID, original_request: str, tasks: list[ProposedTask]
    ) -> AgentTaskBundle:
        now = datetime.now(UTC)
        bundle_id = uuid4()
        item_ids = [uuid4() for _ in tasks]
        with self._sessions.begin() as db:
            session = db.get(AgentSessionModel, session_id)
            if session is None:
                db.add(
                    AgentSessionModel(
                        id=session_id,
                        user_id=user_id,
                        status="ACTIVE",
                        created_at=now,
                        updated_at=now,
                    )
                )
                db.flush()
            elif session.user_id != user_id:
                raise PermissionError("session belongs to another user")
            db.add(
                AgentTaskBundleModel(
                    id=bundle_id,
                    session_id=session_id,
                    original_request=original_request,
                    status=BundleStatus.RUNNING.value,
                    active_item_id=item_ids[0] if item_ids else None,
                    revision=1,
                    created_at=now,
                    updated_at=now,
                )
            )
            db.flush()
            for item_id, task in zip(item_ids, tasks, strict=True):
                db.add(
                    AgentBundleItemModel(
                        id=item_id,
                        bundle_id=bundle_id,
                        item_key=task.item_key,
                        intent=task.intent.value,
                        evidence=task.evidence,
                        status=BundleItemStatus.PROPOSED.value,
                        depends_on=task.depends_on,
                        proposed_slots=task.proposed_slots,
                        confirmed_fields=None,
                        clarification=None,
                        plan=None,
                        result=None,
                        task_id=None,
                        error_code=None,
                        created_at=now,
                        updated_at=now,
                    )
                )
        return self.get_bundle(bundle_id=bundle_id, user_id=user_id)  # type: ignore[return-value]

    def get_bundle(self, *, bundle_id: UUID, user_id: UUID) -> AgentTaskBundle | None:
        with self._sessions() as db:
            bundle = db.execute(
                select(AgentTaskBundleModel)
                .join(AgentSessionModel, AgentSessionModel.id == AgentTaskBundleModel.session_id)
                .where(AgentTaskBundleModel.id == bundle_id, AgentSessionModel.user_id == user_id)
            ).scalar_one_or_none()
            if bundle is None:
                return None
            items = list(
                db.scalars(
                    select(AgentBundleItemModel)
                    .where(AgentBundleItemModel.bundle_id == bundle_id)
                    .order_by(AgentBundleItemModel.created_at, AgentBundleItemModel.item_key)
                )
            )
            return self._to_bundle(bundle, items)

    def update_item(
        self,
        *,
        bundle_id: UUID,
        user_id: UUID,
        item_id: UUID,
        status: BundleItemStatus,
        intent: Intent | None = None,
        clarification: ClarificationPayload | None = None,
        plan: TaskPlan | None = None,
        result: Any | None = None,
        task_id: UUID | None = None,
        error_code: str | None = None,
        confirmed_fields: dict[str, Any] | None = None,
    ) -> AgentTaskBundle:
        now = datetime.now(UTC)
        with self._sessions.begin() as db:
            self._assert_owned(db, bundle_id, user_id)
            item = db.get(AgentBundleItemModel, item_id)
            if item is None or item.bundle_id != bundle_id:
                raise KeyError(item_id)
            item.status = status.value
            if intent is not None:
                item.intent = intent.value
            item.clarification = clarification.model_dump(mode="json") if clarification else None
            item.plan = plan.model_dump(mode="json") if plan else None
            if result is not None:
                item.result = result
            if task_id is not None:
                item.task_id = task_id
            item.error_code = error_code
            if confirmed_fields is not None:
                item.confirmed_fields = confirmed_fields
            item.updated_at = now
            bundle = db.get(AgentTaskBundleModel, bundle_id)
            assert bundle is not None
            bundle.revision += 1
            bundle.updated_at = now
        return self.get_bundle(bundle_id=bundle_id, user_id=user_id)  # type: ignore[return-value]

    def update_bundle(
        self,
        *,
        bundle_id: UUID,
        user_id: UUID,
        status: BundleStatus,
        active_item_id: UUID | None,
    ) -> AgentTaskBundle:
        with self._sessions.begin() as db:
            bundle = self._assert_owned(db, bundle_id, user_id)
            bundle.status = status.value
            bundle.active_item_id = active_item_id
            bundle.revision += 1
            bundle.updated_at = datetime.now(UTC)
        return self.get_bundle(bundle_id=bundle_id, user_id=user_id)  # type: ignore[return-value]

    def append_message(
        self, *, user_id: UUID, session_id: UUID, role: ConversationRole, content: str
    ) -> None:
        now = datetime.now(UTC)
        with self._sessions.begin() as db:
            session = db.get(AgentSessionModel, session_id)
            if session is None:
                db.add(
                    AgentSessionModel(
                        id=session_id,
                        user_id=user_id,
                        status="ACTIVE",
                        created_at=now,
                        updated_at=now,
                    )
                )
                db.flush()
            elif session.user_id != user_id:
                raise PermissionError("session belongs to another user")
            sequence = int(
                db.scalar(
                    select(func.coalesce(func.max(AgentSessionMessageModel.sequence), 0)).where(
                        AgentSessionMessageModel.session_id == session_id
                    )
                )
                or 0
            ) + 1
            db.add(
                AgentSessionMessageModel(
                    id=uuid4(),
                    session_id=session_id,
                    sequence=sequence,
                    role=role.value,
                    content=content,
                    created_at=now,
                )
            )
            cutoff = sequence - 20
            if cutoff > 0:
                db.execute(
                    delete(AgentSessionMessageModel).where(
                        AgentSessionMessageModel.session_id == session_id,
                        AgentSessionMessageModel.sequence <= cutoff,
                    )
                )

    def recent_messages(
        self, *, user_id: UUID, session_id: UUID, limit: int = 20
    ) -> list[ConversationMessage]:
        with self._sessions() as db:
            session = db.get(AgentSessionModel, session_id)
            if session is None:
                return []
            if session.user_id != user_id:
                raise PermissionError("session belongs to another user")
            rows = list(
                db.scalars(
                    select(AgentSessionMessageModel)
                    .where(AgentSessionMessageModel.session_id == session_id)
                    .order_by(AgentSessionMessageModel.sequence.desc())
                    .limit(limit)
                )
            )
            rows.reverse()
            return [
                ConversationMessage(role=ConversationRole(row.role), content=row.content)
                for row in rows
            ]

    def _assert_owned(self, db: Any, bundle_id: UUID, user_id: UUID) -> AgentTaskBundleModel:
        bundle = db.execute(
            select(AgentTaskBundleModel)
            .join(AgentSessionModel, AgentSessionModel.id == AgentTaskBundleModel.session_id)
            .where(AgentTaskBundleModel.id == bundle_id, AgentSessionModel.user_id == user_id)
        ).scalar_one_or_none()
        if bundle is None:
            raise KeyError(bundle_id)
        return cast(AgentTaskBundleModel, bundle)

    @staticmethod
    def _to_bundle(
        bundle: AgentTaskBundleModel, items: list[AgentBundleItemModel]
    ) -> AgentTaskBundle:
        return AgentTaskBundle(
            bundle_id=bundle.id,
            session_id=bundle.session_id,
            original_request=bundle.original_request,
            status=BundleStatus(bundle.status),
            active_item_id=bundle.active_item_id,
            revision=bundle.revision,
            items=[
                AgentTaskItem(
                    item_id=item.id,
                    item_key=item.item_key,
                    intent=Intent(item.intent),
                    evidence=item.evidence,
                    proposed_slots=item.proposed_slots or {},
                    status=BundleItemStatus(item.status),
                    depends_on=list(item.depends_on or []),
                    clarification=(
                        ClarificationPayload.model_validate(item.clarification)
                        if item.clarification
                        else None
                    ),
                    plan=TaskPlan.model_validate(item.plan) if item.plan else None,
                    result=item.result,
                    task_id=item.task_id,
                    error_code=item.error_code,
                )
                for item in items
            ],
        )
