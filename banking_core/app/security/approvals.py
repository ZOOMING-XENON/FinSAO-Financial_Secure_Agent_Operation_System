import hashlib
import hmac
import json
import secrets
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from banking_core.app.domain.enums import AccountStatus, Currency, RiskTier, WealthOrderType
from banking_core.app.persistence.models import (
    AccountModel,
    ApprovalModel,
    AuditEventModel,
    AuthorizationGrantModel,
    CardModel,
    MfaChallengeModel,
    SafetyLockModel,
    SavingsPotModel,
    SubscriptionModel,
    TransferDraftModel,
    UserModel,
    WealthOrderModel,
)
from banking_core.app.security.models import ApprovalStatus, PolicyStatus
from banking_core.app.security.policy import PolicyEngine
from banking_core.app.services.errors import (
    AuthorizationError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
)
from shared.tracing import current_trace_id


def _is_expired(expires_at: datetime) -> bool:
    """SQLite drops timezone metadata; treat its stored timestamps as UTC."""
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    return datetime.now(UTC) >= expires_at


class ApprovalService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create_for_transfer(self, draft_id: UUID, actor_id: UUID) -> ApprovalModel:
        if self.session.in_transaction():
            self.session.rollback()
        with self.session.begin():
            self.session.scalar(select(UserModel).where(UserModel.id == actor_id).with_for_update())
            draft = self.session.get(TransferDraftModel, draft_id)
            if draft is None:
                raise NotFoundError("transfer draft not found")
            if draft.user_id != actor_id:
                raise ForbiddenError("operation belongs to another user")
            existing = self.session.scalar(
                select(ApprovalModel).where(
                    ApprovalModel.operation_id == draft.id,
                    ApprovalModel.status.in_(
                        [ApprovalStatus.PENDING.value, ApprovalStatus.CONFIRMED.value]
                    ),
                )
            )
            if existing is not None:
                return existing
            decision = PolicyEngine(self.session).evaluate("transfer.commit", actor_id, {}, {})
            if decision.status == PolicyStatus.DENIED:
                raise AuthorizationError("operation denied by policy")
            approval = ApprovalModel(
                id=uuid4(),
                actor_user_id=actor_id,
                operation_id=draft.id,
                operation_type="transfer.commit",
                target_account_id=draft.source_account_id,
                recipient_id=draft.destination_account_id,
                amount=draft.amount,
                currency=draft.currency,
                payload_hash=draft.request_hash or "",
                risk_tier=decision.risk_tier,
                status=ApprovalStatus.PENDING.value,
                expires_at=min(draft.expires_at, datetime.now(UTC) + timedelta(minutes=10)),
            )
            self.session.add(approval)
            self._audit(actor_id, "approval.create", decision.status.value, draft.id)
            return approval

    def create_for_operation(
        self,
        operation_id: UUID,
        actor_id: UUID,
        operation_type: str | None = None,
        target_account_id: UUID | None = None,
        amount: Decimal | None = None,
    ) -> ApprovalModel:
        if self.session.get(TransferDraftModel, operation_id) is not None:
            if operation_type not in {None, "transfer.commit"}:
                raise AuthorizationError("operation type does not match resource")
            return self.create_for_transfer(operation_id, actor_id)
        # Serialize approval creation per actor so concurrent requests cannot
        # manufacture multiple active grants for the same resource operation.
        self.session.scalar(select(UserModel).where(UserModel.id == actor_id).with_for_update())
        subscription = self.session.get(SubscriptionModel, operation_id)
        action = "subscription.cancel"
        owner_id = subscription.user_id if subscription is not None else None
        resolved_target_account_id: UUID | None = None
        currency: Currency | None = None
        resource_id: UUID | None = None
        if subscription is None:
            card = self.session.get(CardModel, operation_id)
            if card is not None:
                account = self.session.get(AccountModel, card.account_id)
                owner_id = account.user_id if account is not None else None
                action = operation_type or "card.report_lost"
                if action not in {
                    "card.report_lost",
                    "card.limit",
                    "card.freeze",
                    "card.unfreeze",
                }:
                    raise AuthorizationError("unsupported card operation")
                if action == "card.limit" and (amount is None or amount <= 0):
                    raise AuthorizationError("card limit approval requires exact positive amount")
                if action != "card.limit":
                    amount = None
                resolved_target_account_id = card.account_id
            else:
                order = self.session.get(WealthOrderModel, operation_id)
                if order is not None:
                    expected_action = (
                        "wealth.subscribe"
                        if order.order_type == WealthOrderType.SUBSCRIPTION
                        else "wealth.redeem"
                    )
                    if operation_type not in {None, expected_action}:
                        raise AuthorizationError("operation type does not match resource")
                    owner_id = order.user_id
                    action = expected_action
                    resolved_target_account_id = order.account_id
                    resource_id = order.product_id
                    amount = order.amount
                    currency = order.currency
                else:
                    pot = self.session.get(SavingsPotModel, operation_id)
                    if pot is not None:
                        action = operation_type or "savings.contribute"
                        if action != "savings.contribute":
                            raise AuthorizationError("operation type does not match resource")
                        if amount is None or amount <= 0 or target_account_id is None:
                            raise AuthorizationError(
                                "savings contribution approval requires source account and amount"
                            )
                        account = self.session.get(AccountModel, target_account_id)
                        if (
                            account is None
                            or account.user_id != actor_id
                            or account.is_system
                            or account.status != AccountStatus.ACTIVE
                            or account.currency != pot.currency
                        ):
                            raise ForbiddenError("source account is unavailable")
                        owner_id = pot.user_id
                        resolved_target_account_id = target_account_id
                        currency = pot.currency
        elif operation_type not in {None, "subscription.cancel"}:
            raise AuthorizationError("operation type does not match resource")
        elif subscription is not None:
            amount = None
        if owner_id is None:
            raise NotFoundError("operation not found")
        if owner_id != actor_id:
            raise ForbiddenError("operation belongs to another user")
        payload_hash = resource_payload_hash(
            action,
            operation_id,
            account_id=resolved_target_account_id,
            resource_id=resource_id,
            amount=amount,
            currency=currency,
        )
        existing = self.session.scalar(
            select(ApprovalModel).where(
                ApprovalModel.operation_id == operation_id,
                ApprovalModel.operation_type == action,
                ApprovalModel.payload_hash == payload_hash,
                ApprovalModel.status.in_(
                    [ApprovalStatus.PENDING.value, ApprovalStatus.CONFIRMED.value]
                ),
            )
        )
        if existing is not None:
            return existing
        decision = PolicyEngine(self.session).evaluate(
            action, actor_id, {"amount": amount} if amount is not None else {}, {}
        )
        if decision.status == PolicyStatus.DENIED:
            raise AuthorizationError("operation denied by policy")
        approval = ApprovalModel(
            id=uuid4(),
            actor_user_id=actor_id,
            operation_id=operation_id,
            operation_type=action,
            target_account_id=resolved_target_account_id,
            amount=amount,
            currency=currency,
            payload_hash=payload_hash,
            risk_tier=decision.risk_tier,
            status=ApprovalStatus.PENDING.value,
            expires_at=datetime.now(UTC) + timedelta(minutes=10),
        )
        self.session.add(approval)
        self._audit(actor_id, "approval.create", decision.status.value, operation_id)
        self.session.commit()
        return approval

    def get(self, approval_id: UUID, actor_id: UUID) -> ApprovalModel:
        approval = self.session.get(ApprovalModel, approval_id)
        if approval is None:
            raise NotFoundError("approval not found")
        if approval.actor_user_id != actor_id:
            raise ForbiddenError("approval belongs to another user")
        if (
            approval.status == ApprovalStatus.PENDING.value
            and _is_expired(approval.expires_at)
        ):
            approval.status = ApprovalStatus.EXPIRED.value
            self.session.commit()
        return approval

    def decide(
        self, approval_id: UUID, actor_id: UUID, accepted: bool
    ) -> AuthorizationGrantModel | None:
        self.get(approval_id, actor_id)
        if self.session.in_transaction():
            self.session.rollback()
        with self.session.begin():
            approval = self.session.scalar(
                select(ApprovalModel).where(ApprovalModel.id == approval_id).with_for_update()
            )
            if approval is None:
                raise NotFoundError("approval not found")
            self._validate_pending(approval, actor_id)
            if not accepted:
                approval.status = ApprovalStatus.REJECTED.value
                self._audit(actor_id, "approval.reject", "REJECTED", approval.operation_id)
                return None
            if approval.risk_tier == RiskTier.RED:
                raise AuthorizationError("MFA is required")
            return self._issue_grant(approval)

    def authorize_after_mfa(self, approval_id: UUID, actor_id: UUID) -> AuthorizationGrantModel:
        approval = self.session.scalar(
            select(ApprovalModel).where(ApprovalModel.id == approval_id).with_for_update()
        )
        if approval is None:
            raise NotFoundError("approval not found")
        self._validate_pending(approval, actor_id)
        if approval.risk_tier != RiskTier.RED:
            raise ConflictError("MFA grant is only valid for red operations")
        return self._issue_grant(approval)

    def _validate_pending(self, approval: ApprovalModel, actor_id: UUID) -> None:
        if approval.actor_user_id != actor_id:
            raise ForbiddenError("wrong approval actor")
        if approval.status != ApprovalStatus.PENDING.value:
            raise ConflictError("approval is not pending")
        if _is_expired(approval.expires_at):
            approval.status = ApprovalStatus.EXPIRED.value
            raise AuthorizationError("approval expired")

    def _issue_grant(self, approval: ApprovalModel) -> AuthorizationGrantModel:
        approval.status = ApprovalStatus.CONFIRMED.value
        grant = AuthorizationGrantModel(
            id=uuid4(),
            approval_id=approval.id,
            operation_id=approval.operation_id,
            actor_user_id=approval.actor_user_id,
            payload_hash=approval.payload_hash,
            expires_at=approval.expires_at,
        )
        self.session.add(grant)
        self._audit(approval.actor_user_id, "approval.confirm", "AUTHORIZED", approval.operation_id)
        return grant

    def _audit(self, actor: UUID, action: str, outcome: str, operation: UUID) -> None:
        self.session.add(
            AuditEventModel(
                id=uuid4(),
                actor_user_id=actor,
                action=action,
                resource_type="operation",
                resource_id=str(operation),
                trace_id=current_trace_id(),
                outcome=outcome,
                details={},
            )
        )


class DatabaseTransferAuthorizationVerifier:
    def __init__(self, session: Session) -> None:
        self.session = session

    def verify(self, draft: TransferDraftModel, actor_id: UUID, authorization_ref: str) -> bool:
        try:
            grant_id = UUID(authorization_ref)
        except ValueError:
            return False
        grant = self.session.scalar(
            select(AuthorizationGrantModel)
            .where(AuthorizationGrantModel.id == grant_id)
            .with_for_update()
        )
        if grant is None or grant.consumed_at is not None or _is_expired(grant.expires_at):
            return False
        current_hash = hashlib.sha256(
            json.dumps(
                {
                    "source": str(draft.source_account_id),
                    "destination": str(draft.destination_account_id),
                    "amount": str(draft.amount),
                    "currency": draft.currency.value,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        if (
            grant.actor_user_id != actor_id
            or grant.operation_id != draft.id
            or grant.payload_hash != draft.request_hash
            or draft.request_hash != current_hash
        ):
            return False
        approval = self.session.get(ApprovalModel, grant.approval_id)
        decision = PolicyEngine(self.session).evaluate("transfer.commit", actor_id, {}, {})
        if (
            approval is None
            or approval.actor_user_id != actor_id
            or approval.operation_id != draft.id
            or approval.operation_type != "transfer.commit"
            or approval.payload_hash != current_hash
            or approval.status != ApprovalStatus.CONFIRMED.value
            or (approval.risk_tier == RiskTier.YELLOW and decision.risk_tier == RiskTier.RED)
        ):
            return False
        grant.consumed_at = datetime.now(UTC)
        if approval is not None:
            approval.status = ApprovalStatus.CONSUMED.value
        return True


def resource_payload_hash(
    action: str,
    operation_id: UUID,
    *,
    account_id: UUID | None = None,
    resource_id: UUID | None = None,
    amount: Decimal | None = None,
    currency: Currency | None = None,
) -> str:
    payload = {
        "action": action,
        "operation_id": str(operation_id),
        "account_id": str(account_id) if account_id else None,
        "resource_id": str(resource_id) if resource_id else None,
        "amount": str(amount) if amount is not None else None,
        "currency": currency.value if currency else None,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def consume_resource_authorization(
    session: Session,
    *,
    operation_id: UUID,
    actor_id: UUID,
    action: str,
    authorization_ref: str,
    amount: Decimal | None = None,
    account_id: UUID | None = None,
) -> bool:
    try:
        grant_id = UUID(authorization_ref)
    except ValueError:
        return False
    grant = session.scalar(
        select(AuthorizationGrantModel)
        .where(AuthorizationGrantModel.id == grant_id)
        .with_for_update()
    )
    if action.startswith("card."):
        card = session.get(CardModel, operation_id)
        if card is None:
            return False
        expected = resource_payload_hash(
            action,
            operation_id,
            account_id=card.account_id,
            amount=amount if action == "card.limit" else None,
        )
    elif action in {"wealth.subscribe", "wealth.redeem"}:
        order = session.get(WealthOrderModel, operation_id)
        if order is None:
            return False
        expected_action = (
            "wealth.subscribe"
            if order.order_type == WealthOrderType.SUBSCRIPTION
            else "wealth.redeem"
        )
        if action != expected_action:
            return False
        expected = resource_payload_hash(
            action,
            operation_id,
            account_id=order.account_id,
            resource_id=order.product_id,
            amount=order.amount,
            currency=order.currency,
        )
    elif action == "savings.contribute":
        pot = session.get(SavingsPotModel, operation_id)
        if pot is None or amount is None or account_id is None:
            return False
        approval_for_source = session.scalar(
            select(ApprovalModel).where(ApprovalModel.id == grant.approval_id)
        ) if grant is not None else None
        if (
            approval_for_source is None
            or approval_for_source.target_account_id != account_id
        ):
            return False
        expected = resource_payload_hash(
            action,
            operation_id,
            account_id=account_id,
            amount=amount,
            currency=pot.currency,
        )
    else:
        expected = resource_payload_hash(action, operation_id)
    if (
        grant is None
        or grant.actor_user_id != actor_id
        or grant.operation_id != operation_id
        or grant.payload_hash != expected
        or grant.consumed_at is not None
        or _is_expired(grant.expires_at)
    ):
        return False
    approval = session.get(ApprovalModel, grant.approval_id)
    if (
        approval is None
        or approval.actor_user_id != actor_id
        or approval.operation_id != operation_id
        or approval.operation_type != action
        or approval.payload_hash != expected
        or approval.status != ApprovalStatus.CONFIRMED.value
    ):
        return False
    grant.consumed_at = datetime.now(UTC)
    approval.status = ApprovalStatus.CONSUMED.value
    return True


class MockMfaProvider:
    def __init__(self, session: Session, development_code: str | None = None) -> None:
        self.session = session
        if development_code is not None and (
            len(development_code) != 6 or not development_code.isdigit()
        ):
            raise ValueError("development MFA code must contain six digits")
        self.development_code = development_code

    def create_challenge(self, approval_id: UUID, actor_id: UUID) -> tuple[MfaChallengeModel, str]:
        approval = ApprovalService(self.session).get(approval_id, actor_id)
        if approval.risk_tier != RiskTier.RED or approval.status != ApprovalStatus.PENDING.value:
            raise ConflictError("approval does not require an MFA challenge")
        code = self.development_code or f"{secrets.randbelow(1_000_000):06d}"
        salt = secrets.token_hex(16)
        challenge = MfaChallengeModel(
            id=uuid4(),
            approval_id=approval_id,
            actor_user_id=actor_id,
            code_hash=self._hash(code, salt),
            salt=salt,
            attempts=0,
            max_attempts=3,
            expires_at=datetime.now(UTC) + timedelta(minutes=5),
        )
        self.session.add(challenge)
        self.session.commit()
        return challenge, code

    def verify(self, challenge_id: UUID, actor_id: UUID, code: str) -> AuthorizationGrantModel:
        if self.session.in_transaction():
            self.session.rollback()
        failure: str | None = None
        grant: AuthorizationGrantModel | None = None
        with self.session.begin():
            challenge = self.session.scalar(
                select(MfaChallengeModel)
                .where(MfaChallengeModel.id == challenge_id)
                .with_for_update()
            )
            if challenge is None or challenge.actor_user_id != actor_id:
                raise AuthorizationError("invalid MFA challenge")
            lock = self.session.get(SafetyLockModel, actor_id)
            if (
                lock is not None
                and lock.locked_until is not None
                and datetime.now(UTC) < lock.locked_until
            ):
                raise AuthorizationError("actor is temporarily locked")
            if challenge.verified_at is not None:
                raise AuthorizationError("MFA challenge already used")
            if _is_expired(challenge.expires_at):
                raise AuthorizationError("MFA challenge expired")
            challenge.attempts += 1
            if not hmac.compare_digest(challenge.code_hash, self._hash(code, challenge.salt)):
                if lock is None:
                    lock = SafetyLockModel(actor_user_id=actor_id, failure_count=0)
                    self.session.add(lock)
                lock.failure_count += 1
                if challenge.attempts >= challenge.max_attempts:
                    lock.locked_until = datetime.now(UTC) + timedelta(minutes=15)
                failure = "invalid MFA code"
            else:
                challenge.verified_at = datetime.now(UTC)
                grant = ApprovalService(self.session).authorize_after_mfa(
                    challenge.approval_id, actor_id
                )
        if failure is not None:
            raise AuthorizationError(failure)
        if grant is None:
            raise AuthorizationError("MFA verification failed")
        return grant

    @staticmethod
    def _hash(code: str, salt: str) -> str:
        return hashlib.pbkdf2_hmac("sha256", code.encode(), salt.encode(), 120_000).hex()
