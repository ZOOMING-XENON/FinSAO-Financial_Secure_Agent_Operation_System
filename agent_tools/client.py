from __future__ import annotations

from typing import Protocol, TypeVar, cast

import httpx
from pydantic import BaseModel

from agent_tools.contracts import ExecutionContext

ResponseT = TypeVar("ResponseT", bound=BaseModel)


class ServiceAuthenticator(Protocol):
    def headers(self) -> dict[str, str]: ...


class StaticServiceAuthenticator:
    def __init__(self, token: str) -> None:
        self._token = token

    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token}"}


class BankingClientError(Exception):
    def __init__(self, code: str, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.code, self.message, self.status_code = code, message, status_code


class UnknownMutationOutcome(BankingClientError):
    pass


class BankingHttpClient:
    def __init__(
        self,
        base_url: str,
        authenticator: ServiceAuthenticator,
        timeout: float = 5.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._client = httpx.AsyncClient(base_url=base_url, timeout=timeout, transport=transport)
        self._authenticator = authenticator

    async def close(self) -> None:
        await self._client.aclose()

    async def request(
        self,
        method: str,
        path: str,
        context: ExecutionContext,
        response_model: type[ResponseT],
        *,
        json: dict[str, object] | None = None,
        params: dict[str, str | int | float | bool | None] | None = None,
        idempotency_key: str | None = None,
        mutation: bool = False,
    ) -> ResponseT:
        headers = self._authenticator.headers() | {"X-Trace-Id": str(context.trace_id)}
        if idempotency_key is not None:
            headers["Idempotency-Key"] = idempotency_key
        try:
            response = await self._client.request(
                method, path, headers=headers, json=json, params=params
            )
        except httpx.TimeoutException as exc:
            if mutation:
                raise UnknownMutationOutcome(
                    "UNKNOWN_OUTCOME", "mutation outcome is unknown; reconcile by operation status"
                ) from exc
            raise BankingClientError("UPSTREAM_TIMEOUT", "banking service timed out") from exc
        except httpx.HTTPError as exc:
            raise BankingClientError("UPSTREAM_UNAVAILABLE", "banking service unavailable") from exc
        if response.is_error:
            body = (
                response.json()
                if response.headers.get("content-type", "").startswith("application/json")
                else {}
            )
            raise BankingClientError(
                str(body.get("code", "UPSTREAM_ERROR")),
                str(body.get("message", body.get("detail", "banking request failed"))),
                response.status_code,
            )
        if response.status_code == 204:
            return cast(ResponseT, None)
        return response_model.model_validate(response.json())
