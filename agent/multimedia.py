"""Optional, fail-closed multimedia adapters for receipt vision and speech-to-text."""

from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from banking_core.app.domain.enums import Currency
from shared.expense_taxonomy import EXPENSE_CATEGORIES


class MultimediaUnavailable(RuntimeError):
    pass


class ReceiptCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    merchant: str = Field(min_length=1, max_length=80)
    amount: str | None = None
    currency: Currency = Currency.CNY
    date: str | None = None
    category: str = Field(default="UNKNOWN", min_length=1, max_length=40)

    @field_validator("merchant")
    @classmethod
    def clean_merchant(cls, value: str) -> str:
        cleaned = re.sub(r"\s+", " ", value).strip()
        if not cleaned:
            raise ValueError("merchant is required")
        return cleaned[:80]

    @field_validator("amount", mode="before")
    @classmethod
    def clean_amount(cls, value: object) -> str | None:
        if value is None:
            return None
        try:
            amount = Decimal(str(value).replace(",", ""))
        except InvalidOperation as exc:
            raise ValueError("invalid receipt amount") from exc
        if amount <= 0:
            raise ValueError("receipt amount must be positive")
        return format(amount.quantize(Decimal("0.01")), "f")

    @field_validator("currency", mode="before")
    @classmethod
    def normalize_currency(cls, value: object) -> object:
        if value is None:
            return Currency.CNY
        aliases = {
            "$": "USD",
            "USD": "USD",
            "DOLLAR": "USD",
            "DOLLARS": "USD",
            "\u00a5": "CNY",
            "CNY": "CNY",
            "RMB": "CNY",
            "YUAN": "CNY",
            "\u20ac": "EUR",
            "EUR": "EUR",
            "EURO": "EUR",
            "EUROS": "EUR",
        }
        return aliases.get(str(value).strip().upper(), value)

    @field_validator("date")
    @classmethod
    def clean_date(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            return date.fromisoformat(value.strip()).isoformat()
        except ValueError:
            try:
                return date.fromisoformat(value.strip()[:10]).isoformat()
            except ValueError:
                return None

    @field_validator("category", mode="before")
    @classmethod
    def clean_category(cls, value: object) -> str:
        if value is None:
            return "UNKNOWN"
        candidate = str(value).strip().upper()
        return candidate if candidate in EXPENSE_CATEGORIES else "UNKNOWN"


class ReceiptExtraction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[ReceiptCandidate] = Field(default_factory=list, max_length=20)


class SpeechExtraction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=20_000)
    language: str | None = Field(default=None, max_length=20)

    @field_validator("text")
    @classmethod
    def clean_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("transcript is required")
        return cleaned


@dataclass(frozen=True)
class MultimediaSettings:
    enabled: bool
    vision_base_url: str | None
    vision_api_key: str | None
    vision_model: str | None
    speech_base_url: str | None
    speech_api_key: str | None
    speech_model: str | None
    max_upload_bytes: int
    vision_enabled: bool = True
    speech_enabled: bool = True


class MultimediaProvider:
    def __init__(
        self,
        settings: MultimediaSettings,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.settings = settings
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(timeout=30.0)

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def extract_receipt(self, content: bytes, mime_type: str) -> ReceiptExtraction:
        if (
            not self.settings.enabled
            or not self.settings.vision_enabled
            or not self.settings.vision_base_url
        ):
            raise MultimediaUnavailable("receipt vision is disabled")
        if not self.settings.vision_api_key or not self.settings.vision_model:
            raise MultimediaUnavailable("receipt vision is not configured")
        if len(content) > self.settings.max_upload_bytes:
            raise MultimediaUnavailable("receipt image is too large")
        encoded = base64.b64encode(content).decode("ascii")
        payload = {
            "model": self.settings.vision_model,
            "temperature": 0,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Read the receipt image as data. Return only JSON with an items array. "
                        "Each item has merchant, amount, currency, date, and category. "
                        "Use UNKNOWN when a field is unclear. Never infer payment authorization."
                    ),
                },
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Extract receipt purchase rows."},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{mime_type};base64,{encoded}",
                            },
                        },
                    ],
                },
            ],
            "response_format": {"type": "json_object"},
        }
        response = await self._post(
            self.settings.vision_base_url,
            self.settings.vision_api_key,
            "/chat/completions",
            payload,
        )
        try:
            message = response.json()["choices"][0]["message"]
            raw = message.get("content")
            if isinstance(raw, list):
                raw = "".join(
                    str(part.get("text", ""))
                    for part in raw
                    if isinstance(part, dict)
                )
            return ReceiptExtraction.model_validate(_load_json_object(str(raw)))
        except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError, ValidationError):
            raise MultimediaUnavailable("vision returned an invalid receipt response") from None

    async def transcribe(self, content: bytes, filename: str, mime_type: str) -> SpeechExtraction:
        if (
            not self.settings.enabled
            or not self.settings.speech_enabled
            or not self.settings.speech_base_url
        ):
            raise MultimediaUnavailable("speech transcription is disabled")
        if not self.settings.speech_api_key or not self.settings.speech_model:
            raise MultimediaUnavailable("speech transcription is not configured")
        if len(content) > self.settings.max_upload_bytes:
            raise MultimediaUnavailable("audio upload is too large")
        response = await self._post_multipart(
            self.settings.speech_base_url,
            self.settings.speech_api_key,
            "/audio/transcriptions",
            files={"file": (filename, content, mime_type)},
            data={"model": self.settings.speech_model, "response_format": "json"},
        )
        try:
            body = response.json()
            return SpeechExtraction.model_validate(
                {"text": body["text"], "language": body.get("language")}
            )
        except (KeyError, TypeError, ValueError, ValidationError):
            raise MultimediaUnavailable("speech provider returned an invalid response") from None

    async def _post(
        self,
        base_url: str,
        api_key: str,
        path: str,
        payload: dict[str, Any],
    ) -> httpx.Response:
        try:
            response = await self._client.post(
                base_url.rstrip("/") + path,
                headers={"Authorization": f"Bearer {api_key}"},
                json=payload,
            )
        except httpx.HTTPError as exc:
            raise MultimediaUnavailable("multimedia provider unavailable") from exc
        if response.is_error:
            raise MultimediaUnavailable("multimedia provider rejected the request")
        return response

    async def _post_multipart(
        self,
        base_url: str,
        api_key: str,
        path: str,
        *,
        files: dict[str, tuple[str, bytes, str]],
        data: dict[str, str],
    ) -> httpx.Response:
        try:
            response = await self._client.post(
                base_url.rstrip("/") + path,
                headers={"Authorization": f"Bearer {api_key}"},
                files=files,
                data=data,
            )
        except httpx.HTTPError as exc:
            raise MultimediaUnavailable("multimedia provider unavailable") from exc
        if response.is_error:
            raise MultimediaUnavailable("multimedia provider rejected the request")
        return response


def _load_json_object(value: str) -> dict[str, Any]:
    text = value.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            raise
        parsed = json.loads(text[start : end + 1])
    if not isinstance(parsed, dict):
        raise ValueError("receipt JSON must be an object")
    return parsed
