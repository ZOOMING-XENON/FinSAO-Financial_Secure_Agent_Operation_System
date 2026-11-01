import pytest

from agent.jev_http import JevCategoryObservation
from agent.labeling import ExpenseLabelingWorker
from agent.privacy_broker import PrivacyBroker


class FakeCategoryJev:
    def __init__(self, observation: JevCategoryObservation) -> None:
        self.observation = observation
        self.calls: list[str] = []

    async def classify_category(self, text: str) -> JevCategoryObservation:
        self.calls.append(text)
        return self.observation


@pytest.mark.asyncio
async def test_labeling_worker_redacts_and_labels() -> None:
    adapter = FakeCategoryJev(
        JevCategoryObservation(
            category="DINING", confidence=0.95, order_consistent=True, model="jev"
        )
    )
    worker = ExpenseLabelingWorker(
        adapter=adapter, privacy_broker=PrivacyBroker(names=("Alice",))
    )
    assert await worker.label("restaurant meal") == "DINING"
    assert adapter.calls == ["restaurant meal"]


@pytest.mark.asyncio
async def test_labeling_worker_discards_inconsistent_or_low_confidence() -> None:
    for observation in (
        JevCategoryObservation(
            category="DINING", confidence=0.95, order_consistent=False, model="jev"
        ),
        JevCategoryObservation(
            category="DINING", confidence=0.2, order_consistent=True, model="jev"
        ),
    ):
        worker = ExpenseLabelingWorker(
            adapter=FakeCategoryJev(observation),
            privacy_broker=PrivacyBroker(),
        )
        assert await worker.label("restaurant") is None

@pytest.mark.asyncio
async def test_labeling_policy_blocks_transfer_and_pii() -> None:
    adapter = FakeCategoryJev(
        JevCategoryObservation(
            category="DINING", confidence=0.95, order_consistent=True, model="jev"
        )
    )
    worker = ExpenseLabelingWorker(
        adapter=adapter, privacy_broker=PrivacyBroker(names=("Alice",))
    )
    assert await worker.label("transfer to beneficiary") is None
    assert await worker.label("Alice restaurant") is None
    assert adapter.calls == []
