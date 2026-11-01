import httpx
import pytest

from agent.jev_http import HttpJevAdapter, JevUnavailable


def response(
    forward: str = "TRACK_EXPENSES", reverse: str = "TRACK_EXPENSES"
) -> dict[str, object]:
    return {
        "model": "jev-1.13.0",
        "answers": {
            "intent_forward": {
                "type": "choice",
                "choice": forward,
                "confidence": 0.97,
                "probabilities": {forward: 0.97, "UNKNOWN": 0.03},
            },
            "intent_reverse": {
                "type": "choice",
                "choice": reverse,
                "confidence": 0.96,
                "probabilities": {reverse: 0.96, "UNKNOWN": 0.04},
            },
            "injection": {"type": "noul", "noul": 0.01},
            "in_scope": {"type": "noul", "noul": 0.99},
        },
        "usage": {"input_tokens": 120, "output_tokens": 12},
    }


@pytest.mark.asyncio
async def test_jev_adapter_parses_observation_and_order_consistency() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        payload = __import__("json").loads(request.content)
        assert payload["model"] == "jev-1.13.0"
        assert "CORRECT_EXPENSE_CATEGORY" not in payload["questions"]["intent_forward"]["criteria"]
        assert set(payload["questions"]) == {
            "intent_forward",
            "intent_reverse",
            "injection",
            "in_scope",
        }
        return httpx.Response(200, json=response())

    adapter = HttpJevAdapter(
        api_key="test", transport=httpx.MockTransport(handler)
    )
    result = await adapter.classify("show my expenses")
    await adapter.close()
    assert result.intent.value == "TRACK_EXPENSES"
    assert result.order_consistent is True
    assert result.in_scope_probability == 0.99


@pytest.mark.asyncio
async def test_jev_adapter_marks_order_inconsistency() -> None:
    adapter = HttpJevAdapter(
        api_key="test",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200, json=response("TRACK_EXPENSES", "SUMMARIZE_EXPENSES")
            )
        ),
    )
    result = await adapter.classify("show my expenses")
    await adapter.close()
    assert result.order_consistent is False


@pytest.mark.asyncio
async def test_jev_adapter_fails_closed_on_server_error() -> None:
    adapter = HttpJevAdapter(
        api_key="test",
        transport=httpx.MockTransport(lambda request: httpx.Response(500)),
    )
    with pytest.raises(JevUnavailable):
        await adapter.classify("show my expenses")
    await adapter.close()
