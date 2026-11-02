import json
from pathlib import Path

from agent.bundle_contracts import AgentTurnRequest, AgentTurnResponse


WORKSPACE = Path(__file__).resolve().parents[1] / "workspace"


def test_q6_scenarios_use_real_turn_request_contract() -> None:
    payload = json.loads((WORKSPACE / "q6_complex_scenarios.json").read_text())
    assert len(payload["scenarios"]) == 10
    for scenario in payload["scenarios"]:
        AgentTurnRequest.model_validate(scenario["request"])


def test_q6_results_use_real_turn_response_contract() -> None:
    payload = json.loads((WORKSPACE / "q6_complex_results.json").read_text())
    results = [AgentTurnResponse.model_validate(item) for item in payload["results"]]
    assert results[0].bundle.items[0].result == {
        "balance": "29998.00",
        "currency": "CNY",
    }
    assert results[0].bundle.items[1].status.value == "NEEDS_CONFIRMATION"
    assert results[1].bundle.items[0].status.value == "DEFERRED_UNSUPPORTED"
