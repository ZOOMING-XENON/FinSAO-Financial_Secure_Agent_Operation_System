from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from banking_core.app.api.dependencies import get_current_user_id, get_db_session
from banking_core.app.config import get_settings
from banking_core.app.schemas.security import (
    ApprovalDecisionRequest,
    ApprovalResponse,
    AuthorizationResponse,
    CreateApprovalRequest,
    MfaChallengeResponse,
    MfaVerifyRequest,
)
from banking_core.app.security.approvals import ApprovalService, MockMfaProvider

router = APIRouter(prefix="/security", tags=["security"])
Db = Annotated[Session, Depends(get_db_session)]
Actor = Annotated[UUID, Depends(get_current_user_id)]


@router.post("/approvals", response_model=ApprovalResponse, status_code=status.HTTP_201_CREATED)
def create_approval(
    request: CreateApprovalRequest, session: Db, actor_id: Actor
) -> ApprovalResponse:
    approval = ApprovalService(session).create_for_operation(
        request.operation_id,
        actor_id,
        operation_type=request.operation_type,
        target_account_id=request.target_account_id,
        amount=request.amount,
    )
    return ApprovalResponse.model_validate(approval)


@router.get("/approvals/{approval_id}", response_model=ApprovalResponse)
def get_approval(approval_id: UUID, session: Db, actor_id: Actor) -> ApprovalResponse:
    return ApprovalResponse.model_validate(ApprovalService(session).get(approval_id, actor_id))


@router.post("/approvals/{approval_id}/decision", response_model=AuthorizationResponse | None)
def decide_approval(
    approval_id: UUID, request: ApprovalDecisionRequest, session: Db, actor_id: Actor
) -> AuthorizationResponse | None:
    grant = ApprovalService(session).decide(approval_id, actor_id, request.accepted)
    if grant is None:
        return None
    return AuthorizationResponse(authorization_ref=grant.id, expires_at=grant.expires_at)


@router.post("/approvals/{approval_id}/mfa", response_model=MfaChallengeResponse)
def create_mfa_challenge(approval_id: UUID, session: Db, actor_id: Actor) -> MfaChallengeResponse:
    configured = get_settings().mock_mfa_code
    provider = MockMfaProvider(
        session, configured.get_secret_value() if configured is not None else None
    )
    challenge, _trusted_code = provider.create_challenge(approval_id, actor_id)
    return MfaChallengeResponse(challenge_id=challenge.id, expires_at=challenge.expires_at)


@router.post("/mfa/{challenge_id}/verify", response_model=AuthorizationResponse)
def verify_mfa(
    challenge_id: UUID, request: MfaVerifyRequest, session: Db, actor_id: Actor
) -> AuthorizationResponse:
    grant = MockMfaProvider(session).verify(challenge_id, actor_id, request.code)
    return AuthorizationResponse(authorization_ref=grant.id, expires_at=grant.expires_at)
