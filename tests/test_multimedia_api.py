from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient

from agent.app import app, get_trusted_user_id


def _client() -> TestClient:
    app.dependency_overrides[get_trusted_user_id] = lambda: uuid4()
    return TestClient(app)


def test_receipt_endpoint_rejects_unsupported_type() -> None:
    client = _client()
    try:
        response = client.post(
            "/agent/receipts/parse",
            files={"upload": ("x.txt", b"hello", "text/plain")},
        )
        assert response.status_code == 415
        assert response.json()["detail"]["code"] == "UNSUPPORTED_MEDIA_TYPE"
    finally:
        app.dependency_overrides.clear()


def test_receipt_endpoint_rejects_invalid_signature() -> None:
    client = _client()
    try:
        response = client.post(
            "/agent/receipts/parse",
            files={"upload": ("x.png", b"not-an-image", "image/png")},
        )
        assert response.status_code == 415
        assert response.json()["detail"]["code"] == "INVALID_MEDIA"
    finally:
        app.dependency_overrides.clear()


def test_receipt_endpoint_fails_closed_when_disabled() -> None:
    client = _client()
    try:
        response = client.post(
            "/agent/receipts/parse",
            files={"upload": ("x.png", b"\x89PNG\r\n\x1a\nreceipt", "image/png")},
        )
        assert response.status_code == 503
        assert response.json()["detail"]["code"] == "MULTIMEDIA_UNAVAILABLE"
    finally:
        app.dependency_overrides.clear()


def test_audio_endpoint_fails_closed_when_disabled() -> None:
    client = _client()
    try:
        response = client.post(
            "/agent/audio/transcribe",
            files={"upload": ("voice.webm", b"\x1aE\xdf\xa3audio", "audio/webm")},
        )
        assert response.status_code == 503
        assert response.json()["detail"]["code"] == "MULTIMEDIA_UNAVAILABLE"
    finally:
        app.dependency_overrides.clear()
