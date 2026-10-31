from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

from banking_core.app.api.dependencies import get_current_user_id, get_db_session
from banking_core.app.schemas.savings import (
    SavingsContributionRequest,
    SavingsContributionResponse,
    SavingsPotCreateRequest,
    SavingsPotResponse,
    SavingsPotUpdateRequest,
)
from banking_core.app.services.savings import SavingsPotService

router = APIRouter(prefix="/savings-pots", tags=["savings-pots"])
Db = Annotated[Session, Depends(get_db_session)]
Actor = Annotated[UUID, Depends(get_current_user_id)]


@router.get("", response_model=list[SavingsPotResponse])
def list_savings_pots(session: Db, actor: Actor) -> list[SavingsPotResponse]:
    return [
        SavingsPotResponse.model_validate(item) for item in SavingsPotService(session).list(actor)
    ]


@router.post("", response_model=SavingsPotResponse, status_code=status.HTTP_201_CREATED)
def create_savings_pot(
    request: SavingsPotCreateRequest, session: Db, actor: Actor
) -> SavingsPotResponse:
    item = SavingsPotService(session).create(
        actor,
        name=request.name,
        target_amount=request.target_amount,
        currency=request.currency,
        target_date=request.target_date,
        idempotency_key=request.idempotency_key,
    )
    return SavingsPotResponse.model_validate(item)


@router.get("/{pot_id}", response_model=SavingsPotResponse)
def get_savings_pot(pot_id: UUID, session: Db, actor: Actor) -> SavingsPotResponse:
    return SavingsPotResponse.model_validate(SavingsPotService(session).get(pot_id, actor))


@router.patch("/{pot_id}", response_model=SavingsPotResponse)
def update_savings_pot(
    pot_id: UUID, request: SavingsPotUpdateRequest, session: Db, actor: Actor
) -> SavingsPotResponse:
    item = SavingsPotService(session).update(
        pot_id,
        actor,
        name=request.name,
        target_amount=request.target_amount,
        target_date=request.target_date,
    )
    return SavingsPotResponse.model_validate(item)


@router.delete("/{pot_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_savings_pot(pot_id: UUID, session: Db, actor: Actor) -> Response:
    SavingsPotService(session).delete(pot_id, actor)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{pot_id}/contributions", response_model=list[SavingsContributionResponse])
def list_savings_contributions(
    pot_id: UUID, session: Db, actor: Actor
) -> list[SavingsContributionResponse]:
    return [
        SavingsContributionResponse.model_validate(item)
        for item in SavingsPotService(session).list_contributions(pot_id, actor)
    ]


@router.post(
    "/{pot_id}/contributions",
    response_model=SavingsContributionResponse,
    status_code=status.HTTP_201_CREATED,
)
def contribute_savings_pot(
    pot_id: UUID, request: SavingsContributionRequest, session: Db, actor: Actor
) -> SavingsContributionResponse:
    item = SavingsPotService(session).contribute(
        pot_id,
        actor,
        source_account_id=request.source_account_id,
        amount=request.amount,
        note=request.note,
        idempotency_key=request.idempotency_key,
        authorization_ref=str(request.authorization_ref),
    )
    return SavingsContributionResponse.model_validate(item)
