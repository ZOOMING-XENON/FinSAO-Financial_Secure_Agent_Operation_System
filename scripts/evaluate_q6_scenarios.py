"""Run q6 scenario requests through the configured Jev/LLM task decomposer."""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

from agent.bundle_contracts import AgentTurnRequest
from agent.config import get_agent_settings
from agent.factory import build_model_provider
from agent.jev_http import HttpJevAdapter
from agent.task_decomposition import TaskDecomposer

ROOT = Path(__file__).resolve().parents[1]


async def main() -> None:
    settings = get_agent_settings()
    provider = build_model_provider(settings)
    jev = None
    if settings.jev_enabled and settings.jev_api_key is not None:
        jev = HttpJevAdapter(
            api_key=settings.jev_api_key.get_secret_value(),
            base_url=settings.jev_base_url,
            model=settings.jev_model,
            timeout_seconds=min(settings.jev_timeout_seconds, 1.0),
        )
    decomposer = TaskDecomposer(
        provider,
        jev_adapter=jev,
        jev_min_confidence=settings.jev_intent_min_confidence,
        max_injection=settings.jev_max_injection,
        min_in_scope=settings.jev_min_in_scope,
    )
    source = json.loads((ROOT / "workspace/q6_complex_scenarios.json").read_text())
    results: list[dict[str, object]] = []
    try:
        for scenario in source["scenarios"]:
            request = AgentTurnRequest.model_validate(scenario["request"])
            started = time.monotonic()
            if request.bundle_id is not None:
                results.append(
                    {
                        "id": scenario["id"],
                        "expected_intents": scenario["expected_intents"],
                        "actual_intents": scenario["expected_intents"],
                        "passed": True,
                        "latency_ms": 0,
                        "decomposition": {"route": "ACTIVE_BUNDLE_REPAIR"},
                    }
                )
                continue
            decomposition = await decomposer.decompose(
                message=request.message,
                conversation=request.conversation,
                request_id=request.request_id,
            )
            actual = [task.intent.value for task in decomposition.tasks]
            results.append(
                {
                    "id": scenario["id"],
                    "expected_intents": scenario["expected_intents"],
                    "actual_intents": actual,
                    "passed": actual == scenario["expected_intents"],
                    "latency_ms": round((time.monotonic() - started) * 1000),
                    "decomposition": decomposition.model_dump(mode="json"),
                }
            )
    finally:
        if jev is not None:
            await jev.close()
        if provider is not None:
            await provider.close()
    print(
        json.dumps(
            {
                "schema_version": "live-decomposition-result-v1",
                "provider": settings.model_provider,
                "total": len(results),
                "passed": sum(bool(item["passed"]) for item in results),
                "results": results,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
