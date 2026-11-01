from __future__ import annotations

import json

import httpx
import pytest

from agent.multimedia import MultimediaProvider, MultimediaSettings, MultimediaUnavailable


@pytest.mark.asyncio
async def test_receipt_vision_parses_structured_candidates() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/chat/completions"
        assert request.headers["authorization"] == "Bearer secret"
        body = json.loads(request.content)
        assert body["messages"][1]["content"][1]["type"] == "image_url"
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "items": [
                                        {
                                            "merchant": "Cafe",
                                            "amount": "18.50",
                                            "currency": "CNY",
                                            "date": "2026-11-01",
                                            "category": "DINING",
                                        }
                                    ]
                                }
                            )
                        }
                    }
                ]
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = MultimediaProvider(
        MultimediaSettings(
            enabled=True,
            vision_base_url="https://vision.test",
            vision_api_key="secret",
            vision_model="vision-model",
            speech_base_url=None,
            speech_api_key=None,
            speech_model=None,
            max_upload_bytes=1000,
        ),
        client=client,
    )
    try:
        result = await provider.extract_receipt(b"image", "image/png")
        assert result.items[0].merchant == "Cafe"
        assert result.items[0].amount == "18.50"
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_disabled_multimedia_fails_closed() -> None:
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(500)))
    provider = MultimediaProvider(
        MultimediaSettings(
            enabled=False,
            vision_base_url=None,
            vision_api_key=None,
            vision_model=None,
            speech_base_url=None,
            speech_api_key=None,
            speech_model=None,
            max_upload_bytes=1000,
        ),
        client=client,
    )
    try:
        with pytest.raises(RuntimeError, match="disabled"):
            await provider.extract_receipt(b"image", "image/png")
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_receipt_normalizes_currency_category_and_amount() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": "```json\n"
                            + json.dumps(
                                {
                                    "items": [
                                        {
                                            "merchant": "  Cafe  ",
                                            "amount": "18.5",
                                            "currency": "rmb",
                                            "date": "not-a-date",
                                            "category": "dining",
                                        }
                                    ]
                                }
                            )
                            + "\n```"
                        }
                    }
                ]
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = MultimediaProvider(
        MultimediaSettings(
            enabled=True,
            vision_base_url="https://vision.test",
            vision_api_key="secret",
            vision_model="vision-model",
            speech_base_url=None,
            speech_api_key=None,
            speech_model=None,
            max_upload_bytes=1000,
        ),
        client=client,
    )
    try:
        result = await provider.extract_receipt(b"image", "image/png")
        item = result.items[0]
        assert item.merchant == "Cafe"
        assert item.amount == "18.50"
        assert item.currency.value == "CNY"
        assert item.category == "DINING"
        assert item.date is None
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_speech_transcription_uses_configured_provider() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/audio/transcriptions"
        assert request.headers["authorization"] == "Bearer speech-secret"
        return httpx.Response(200, json={"text": "  I spent 5 dollars on coke  ", "language": "en"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = MultimediaProvider(
        MultimediaSettings(
            enabled=True,
            vision_base_url=None,
            vision_api_key=None,
            vision_model=None,
            speech_base_url="https://speech.test",
            speech_api_key="speech-secret",
            speech_model="speech-model",
            max_upload_bytes=1000,
        ),
        client=client,
    )
    try:
        result = await provider.transcribe(b"audio", "voice.webm", "audio/webm")
        assert result.text == "I spent 5 dollars on coke"
        assert result.language == "en"
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_capability_flags_and_provider_errors_fail_closed() -> None:
    async def fail(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    client = httpx.AsyncClient(transport=httpx.MockTransport(fail))
    provider = MultimediaProvider(
        MultimediaSettings(
            enabled=True,
            vision_base_url="https://vision.test",
            vision_api_key="secret",
            vision_model="vision-model",
            speech_base_url="https://speech.test",
            speech_api_key="secret",
            speech_model="speech-model",
            max_upload_bytes=1000,
            vision_enabled=False,
            speech_enabled=False,
        ),
        client=client,
    )
    try:
        with pytest.raises(MultimediaUnavailable, match="disabled"):
            await provider.extract_receipt(b"image", "image/png")
        with pytest.raises(MultimediaUnavailable, match="disabled"):
            await provider.transcribe(b"audio", "voice.webm", "audio/webm")
    finally:
        await client.aclose()
