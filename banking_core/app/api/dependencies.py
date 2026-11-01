import hmac
from collections.abc import Generator
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from banking_core.app.config import get_settings
from banking_core.app.persistence.database import get_session_factory
from banking_core.app.security.approvals import DatabaseTransferAuthorizationVerifier
from banking_core.app.security.transfer_authorization import TransferAuthorizationVerifier


def get_db_session() -> Generator[Session, None, None]:
    with get_session_factory()() as session:
        yield session


def get_current_user_id(
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
) -> UUID:
    """Server-configured Phase 2 identity stub; it accepts no client identity input."""
    settings = get_settings()
    user_id = settings.development_user_id
    expected = settings.banking_service_token.get_secret_value()
    supplied = authorization.removeprefix("Bearer ") if authorization else ""
    if (
        settings.app_env != "development"
        or user_id is None
        or not expected
        or not hmac.compare_digest(supplied, expected)
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="valid service authentication is required",
        )
    return user_id


def get_labeling_worker_id(
    token: Annotated[str | None, Header(alias="X-Labeling-Token")] = None,
) -> UUID:
    """Service-scoped identity for the internal labeling worker."""
    settings = get_settings()
    expected = settings.labeling_service_token.get_secret_value()
    user_id = settings.labeling_service_user_id or settings.development_user_id
    if (
        user_id is None
        or not expected
        or not token
        or not hmac.compare_digest(token, expected)
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="valid labeling service token is required",
        )
    return user_id


def get_transfer_verifier(
    session: Annotated[Session, Depends(get_db_session)],
) -> TransferAuthorizationVerifier:
    return DatabaseTransferAuthorizationVerifier(session)
