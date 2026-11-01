"""Run one bounded expense-labeling batch against a running Banking Core."""

from __future__ import annotations

import argparse
import asyncio
from uuid import uuid4

from pydantic import BaseModel, RootModel

from agent.config import get_agent_settings
from agent.jev_http import HttpJevAdapter
from agent.labeling import ExpenseLabelingWorker
from agent.privacy_broker import PrivacyBroker
from agent_tools.client import BankingClientError, BankingHttpClient
from agent_tools.contracts import ExecutionContext


class LabelingTransaction(BaseModel):
    id: str
    description: str
    category: str | None = None
    category_source: str | None = None
    category_version: str | None = None


class EmptyResponse(BaseModel):
    pass


class LabelWriteResponse(BaseModel):
    id: str
    category: str | None = None
    category_source: str | None = None
    category_version: str | None = None


class LabelingAuthenticator:
    def __init__(self, service_token: str, labeling_token: str) -> None:
        self._service_token = service_token
        self._labeling_token = labeling_token

    def headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._service_token}",
            "X-Labeling-Token": self._labeling_token,
        }


async def run(batch_size: int, delay: float) -> None:
    settings = get_agent_settings()
    if not settings.expense_labeling_jev_enabled:
        raise SystemExit("EXPENSE_LABELING_JEV_ENABLED is false")
    if settings.jev_api_key is None:
        raise SystemExit("JEV_API_KEY is required for labeling")
    adapter = HttpJevAdapter(
        api_key=settings.jev_api_key.get_secret_value(),
        base_url=settings.jev_base_url,
        model=settings.jev_model,
        timeout_seconds=settings.jev_timeout_seconds,
    )
    client = BankingHttpClient(
        settings.banking_base_url,
        LabelingAuthenticator(
            settings.banking_service_token.get_secret_value(),
            settings.banking_labeling_token.get_secret_value(),
        ),
    )
    worker = ExpenseLabelingWorker(
        adapter=adapter, privacy_broker=PrivacyBroker(), min_confidence=0.8
    )
    context = ExecutionContext(uuid4(), uuid4(), uuid4(), uuid4())
    try:
        pending = await client.request(
            "GET",
            "/internal/expense-labeling/transactions",
            context,
            RootModel[list[LabelingTransaction]],
            params={"limit": batch_size},
        )
        for item in pending.root:
            category = await worker.label(item.description)
            if category is None:
                await client.request(
                    "POST",
                    f"/internal/expense-labeling/transactions/{item.id}/attempt",
                    context,
                    EmptyResponse,
                    json={"policy_version": "jev-label-v1", "succeeded": False},
                    mutation=True,
                )
                continue
            try:
                await client.request(
                    "POST",
                    f"/internal/expense-labeling/transactions/{item.id}/label",
                    context,
                    LabelWriteResponse,
                    json={
                        "category": category,
                        "source": "JEV",
                        "observed_source": item.category_source,
                        "observed_version": item.category_version,
                        "version": "jev-label-v1",
                    },
                    idempotency_key=f"expense-label:{item.id}:jev-label-v1",
                    mutation=True,
                )
            except BankingClientError:
                await client.request(
                    "POST",
                    f"/internal/expense-labeling/transactions/{item.id}/attempt",
                    context,
                    EmptyResponse,
                    json={"policy_version": "jev-label-v1", "succeeded": False},
                    mutation=True,
                )
            await asyncio.sleep(delay)
    finally:
        await client.close()
        await adapter.close()


async def run_forever(batch_size: int, delay: float, interval: float) -> None:
    while True:
        await run(batch_size, delay)
        await asyncio.sleep(interval)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch-size", type=int, default=20)
    parser.add_argument("--delay", type=float, default=0.0)
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--interval", type=float, default=60.0)
    args = parser.parse_args()
    if args.loop:
        asyncio.run(run_forever(args.batch_size, args.delay, args.interval))
    else:
        asyncio.run(run(args.batch_size, args.delay))


if __name__ == "__main__":
    main()
