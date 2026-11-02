from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

from agent.bundle_contracts import ProposedTask
from agent_persistence.bundle_store import SqlAlchemyBundleStore
from agent_persistence.models import (
    AgentBundleItemModel,
    AgentSessionModel,
    AgentTaskBundleModel,
)


def test_bundle_store_flushes_parent_rows_before_items() -> None:
    writes: list[str] = []
    db = MagicMock()
    db.get.return_value = None

    def record_add(model: object) -> None:
        writes.append(type(model).__name__)

    db.add.side_effect = record_add
    db.flush.side_effect = lambda: writes.append("flush")
    sessions = MagicMock()
    sessions.begin.return_value.__enter__.return_value = db
    store = SqlAlchemyBundleStore.__new__(SqlAlchemyBundleStore)
    store._sessions = sessions  # type: ignore[assignment]
    store.get_bundle = MagicMock(return_value=None)  # type: ignore[method-assign]

    store.create_bundle(
        user_id=uuid4(),
        session_id=uuid4(),
        original_request="查余额并转账",
        tasks=[
            ProposedTask(item_key="balance", intent="GET_BALANCE", evidence="查余额"),
            ProposedTask(item_key="transfer", intent="TRANSFER", evidence="转账"),
        ],
    )

    assert writes == [
        AgentSessionModel.__name__,
        "flush",
        AgentTaskBundleModel.__name__,
        "flush",
        AgentBundleItemModel.__name__,
        AgentBundleItemModel.__name__,
    ]
