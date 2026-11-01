from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from banking_core.app.domain.enums import (
    AccountStatus,
    CardStatus,
    RiskTier,
    TransactionKind,
    TransactionOrigin,
    TransactionStatus,
    WealthOrderType,
)
from banking_core.app.persistence.models import (
    AccountModel,
    AuditEventModel,
    CardModel,
    RiskAssessmentModel,
    TransactionModel,
    WealthHoldingModel,
    WealthOrderModel,
    WealthProductModel,
)
from banking_core.app.security.approvals import consume_resource_authorization
from banking_core.app.services.errors import (
    AuthorizationError,
    ConflictError,
    ForbiddenError,
    InsufficientFundsError,
    NotFoundError,
)
from banking_core.app.services.ledger import LedgerService
from shared.tracing import current_trace_id


class CardService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def list(self, user_id: UUID) -> list[CardModel]:
        return list(
            self.session.scalars(
                select(CardModel).join(AccountModel).where(AccountModel.user_id == user_id)
            )
        )

    def get(self, card_id: UUID, user_id: UUID) -> CardModel:
        card = self.session.get(CardModel, card_id)
        if card is None:
            raise NotFoundError("card not found")
        account = self.session.get(AccountModel, card.account_id)
        if account is None or account.user_id != user_id:
            raise ForbiddenError("card belongs to another user")
        return card

    def set_frozen(
        self,
        card_id: UUID,
        user_id: UUID,
        frozen: bool,
        authorization_ref: str,
    ) -> CardModel:
        card = self.get(card_id, user_id)
        if card.status in {CardStatus.LOST, CardStatus.CANCELLED, CardStatus.EXPIRED}:
            raise ConflictError("card state cannot be changed")
        action = "card.freeze" if frozen else "card.unfreeze"
        if not consume_resource_authorization(
            self.session,
            operation_id=card_id,
            actor_id=user_id,
            action=action,
            authorization_ref=authorization_ref,
        ):
            raise AuthorizationError("yellow authorization required")
        card.status = CardStatus.FROZEN if frozen else CardStatus.ACTIVE
        self.session.add(
            AuditEventModel(
                id=uuid4(),
                actor_user_id=user_id,
                action=action,
                resource_type="card",
                resource_id=str(card_id),
                trace_id=current_trace_id(),
                outcome="COMPLETED",
                details={},
            )
        )
        self.session.commit()
        return card

    def update_limit(
        self, card_id: UUID, user_id: UUID, limit: Decimal, authorization_ref: str
    ) -> CardModel:
        if limit <= 0:
            raise ConflictError("card limit must be positive")
        card = self.get(card_id, user_id)
        if not consume_resource_authorization(
            self.session,
            operation_id=card_id,
            actor_id=user_id,
            action="card.limit",
            authorization_ref=authorization_ref,
            amount=limit,
        ):
            raise AuthorizationError("yellow authorization required")
        card.spending_limit = limit
        self.session.add(
            AuditEventModel(
                id=uuid4(),
                actor_user_id=user_id,
                action="card.limit",
                resource_type="card",
                resource_id=str(card_id),
                trace_id=current_trace_id(),
                outcome="COMPLETED",
                details={"spending_limit": str(limit)},
            )
        )
        self.session.commit()
        return card

    def report_lost(self, card_id: UUID, user_id: UUID, authorization_ref: str) -> CardModel:
        card = self.get(card_id, user_id)
        if card.status == CardStatus.LOST:
            return card
        if not consume_resource_authorization(
            self.session,
            operation_id=card_id,
            actor_id=user_id,
            action="card.report_lost",
            authorization_ref=authorization_ref,
        ):
            raise AuthorizationError("red authorization required")
        card.status = CardStatus.LOST
        self.session.add(
            AuditEventModel(
                id=uuid4(),
                actor_user_id=user_id,
                action="card.report_lost",
                resource_type="card",
                resource_id=str(card_id),
                trace_id=current_trace_id(),
                outcome="COMPLETED",
                details={},
            )
        )
        self.session.commit()
        return card


class WealthService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def list_products(
        self, product_type: str | None = None, risk: RiskTier | None = None
    ) -> list[WealthProductModel]:
        query = select(WealthProductModel)
        if product_type:
            query = query.where(WealthProductModel.product_type == product_type)
        if risk:
            query = query.where(WealthProductModel.risk_tier == risk)
        return list(self.session.scalars(query.order_by(WealthProductModel.code)))

    def compare_products(self, product_ids: list[UUID]) -> list[WealthProductModel]:
        if len(product_ids) < 2 or len(product_ids) > 10:
            raise ConflictError("between two and ten products are required")
        if len(set(product_ids)) != len(product_ids):
            raise ConflictError("product comparison cannot contain duplicates")
        products = list(
            self.session.scalars(
                select(WealthProductModel)
                .where(WealthProductModel.id.in_(set(product_ids)))
                .order_by(WealthProductModel.code)
            )
        )
        if len(products) != len(product_ids):
            raise NotFoundError("one or more products were not found")
        return products

    def check_suitability(self, user_id: UUID, product: WealthProductModel) -> bool:
        assessment = self.session.scalar(
            select(RiskAssessmentModel)
            .where(RiskAssessmentModel.user_id == user_id)
            .order_by(RiskAssessmentModel.created_at.desc())
        )
        tiers = {RiskTier.GREEN: 1, RiskTier.YELLOW: 2, RiskTier.RED: 3}
        return assessment is not None and tiers[assessment.risk_tier] >= tiers[product.risk_tier]

    def recommend_products(self, user_id: UUID) -> list[WealthProductModel]:
        """Return deterministic suitable products; this is not personalized advice."""
        products = self.list_products()
        return [product for product in products if self.check_suitability(user_id, product)]

    def assess(self, user_id: UUID, answers: list[int]) -> RiskAssessmentModel:
        if len(answers) != 5 or any(answer not in range(1, 6) for answer in answers):
            raise ConflictError("five answers from 1 to 5 are required")
        score = sum(answers)
        tier = RiskTier.GREEN if score <= 10 else RiskTier.YELLOW if score <= 18 else RiskTier.RED
        result = RiskAssessmentModel(id=uuid4(), user_id=user_id, score=score, risk_tier=tier)
        self.session.add(result)
        self.session.commit()
        return result

    def holdings(self, user_id: UUID) -> list[WealthHoldingModel]:
        return list(
            self.session.scalars(
                select(WealthHoldingModel).where(WealthHoldingModel.user_id == user_id)
            )
        )

    def create_order(
        self,
        user_id: UUID,
        account_id: UUID,
        product_id: UUID,
        amount: Decimal,
        idempotency_key: str,
    ) -> WealthOrderModel:
        existing = self.session.scalar(
            select(WealthOrderModel).where(
                WealthOrderModel.user_id == user_id,
                WealthOrderModel.idempotency_key == idempotency_key,
            )
        )
        if existing:
            if (
                existing.account_id != account_id
                or existing.product_id != product_id
                or existing.amount != amount
                or existing.order_type != WealthOrderType.SUBSCRIPTION
            ):
                raise ConflictError("idempotency key reused with different wealth order")
            return existing
        account, product = (
            self.session.get(AccountModel, account_id),
            self.session.get(WealthProductModel, product_id),
        )
        if account is None or account.user_id != user_id:
            raise ForbiddenError("account unavailable")
        if product is None:
            raise NotFoundError("product not found")
        if not self.check_suitability(user_id, product):
            raise ForbiddenError("product is unsuitable for current risk profile")
        if amount < product.minimum_amount or account.currency != product.currency:
            raise ConflictError("order amount or currency is invalid")
        order = WealthOrderModel(
            id=uuid4(),
            user_id=user_id,
            account_id=account_id,
            product_id=product_id,
            amount=amount,
            currency=product.currency,
            status="PENDING_AUTHORIZATION",
            order_type=WealthOrderType.SUBSCRIPTION,
            idempotency_key=idempotency_key,
        )
        self.session.add(order)
        try:
            self.session.commit()
        except IntegrityError:
            self.session.rollback()
            concurrent = self.session.scalar(
                select(WealthOrderModel).where(
                    WealthOrderModel.user_id == user_id,
                    WealthOrderModel.idempotency_key == idempotency_key,
                )
            )
            if (
                concurrent is None
                or concurrent.account_id != account_id
                or concurrent.product_id != product_id
                or concurrent.amount != amount
                or concurrent.order_type != WealthOrderType.SUBSCRIPTION
            ):
                raise ConflictError("idempotency key conflict") from None
            return concurrent
        return order

    def create_redemption_order(
        self,
        user_id: UUID,
        account_id: UUID,
        product_id: UUID,
        amount: Decimal,
        idempotency_key: str,
    ) -> WealthOrderModel:
        existing = self.session.scalar(
            select(WealthOrderModel).where(
                WealthOrderModel.user_id == user_id,
                WealthOrderModel.idempotency_key == idempotency_key,
            )
        )
        if existing:
            if (
                existing.account_id != account_id
                or existing.product_id != product_id
                or existing.amount != amount
                or existing.order_type != WealthOrderType.REDEMPTION
            ):
                raise ConflictError("idempotency key reused with different wealth order")
            return existing
        account = self.session.get(AccountModel, account_id)
        product = self.session.get(WealthProductModel, product_id)
        if account is None or account.user_id != user_id:
            raise ForbiddenError("account unavailable")
        if product is None:
            raise NotFoundError("product not found")
        if not product.supports_redemption:
            raise ConflictError("product does not support redemption")
        holding = self.session.scalar(
            select(WealthHoldingModel).where(
                WealthHoldingModel.user_id == user_id,
                WealthHoldingModel.product_id == product_id,
            )
        )
        if amount <= 0 or holding is None or holding.amount < amount:
            raise ConflictError("redemption exceeds available holding")
        if account.currency != product.currency:
            raise ConflictError("redemption account currency is invalid")
        order = WealthOrderModel(
            id=uuid4(),
            user_id=user_id,
            account_id=account_id,
            product_id=product_id,
            amount=amount,
            currency=product.currency,
            status="PENDING_AUTHORIZATION",
            order_type=WealthOrderType.REDEMPTION,
            idempotency_key=idempotency_key,
        )
        self.session.add(order)
        try:
            self.session.commit()
        except IntegrityError:
            self.session.rollback()
            concurrent = self.session.scalar(
                select(WealthOrderModel).where(
                    WealthOrderModel.user_id == user_id,
                    WealthOrderModel.idempotency_key == idempotency_key,
                )
            )
            if (
                concurrent is None
                or concurrent.account_id != account_id
                or concurrent.product_id != product_id
                or concurrent.amount != amount
                or concurrent.order_type != WealthOrderType.REDEMPTION
            ):
                raise ConflictError("idempotency key conflict") from None
            return concurrent
        return order

    def get_order(self, order_id: UUID, user_id: UUID) -> WealthOrderModel:
        order = self.session.get(WealthOrderModel, order_id)
        if order is None:
            raise NotFoundError("wealth order not found")
        if order.user_id != user_id:
            raise ForbiddenError("wealth order belongs to another user")
        return order

    def commit_order(
        self, order_id: UUID, user_id: UUID, authorization_ref: str
    ) -> WealthOrderModel:
        if self.session.in_transaction():
            self.session.rollback()
        with self.session.begin():
            order = self.session.scalar(
                select(WealthOrderModel).where(WealthOrderModel.id == order_id).with_for_update()
            )
            if order is None:
                raise NotFoundError("wealth order not found")
            if order.user_id != user_id:
                raise ForbiddenError("wealth order belongs to another user")
            if order.status == "COMPLETED":
                return order
            action = (
                "wealth.subscribe"
                if order.order_type == WealthOrderType.SUBSCRIPTION
                else "wealth.redeem"
            )
            if not consume_resource_authorization(
                self.session,
                operation_id=order_id,
                actor_id=user_id,
                action=action,
                authorization_ref=authorization_ref,
            ):
                raise AuthorizationError("red authorization required")
            accounts = list(
                self.session.scalars(
                    select(AccountModel)
                    .where(
                        (AccountModel.id == order.account_id)
                        | (
                            AccountModel.is_system.is_(True)
                            & (AccountModel.currency == order.currency)
                        )
                    )
                    .order_by(AccountModel.id)
                    .with_for_update()
                )
            )
            source = next(a for a in accounts if a.id == order.account_id)
            system = next((a for a in accounts if a.is_system), None)
            if (
                source.user_id != user_id
                or source.status != AccountStatus.ACTIVE
                or source.currency != order.currency
            ):
                raise ForbiddenError("wealth settlement account is unavailable")
            if system is None or system.status != AccountStatus.ACTIVE:
                raise ConflictError("mock settlement account is unavailable")
            holding = self.session.scalar(
                select(WealthHoldingModel)
                .where(
                    WealthHoldingModel.user_id == user_id,
                    WealthHoldingModel.product_id == order.product_id,
                )
                .with_for_update()
            )
            if order.order_type == WealthOrderType.SUBSCRIPTION:
                if source.balance < order.amount:
                    raise InsufficientFundsError("insufficient funds")
                source.balance -= order.amount
                system.balance += order.amount
                debit_account_id, credit_account_id = source.id, system.id
                description = "Mock wealth subscription"
            else:
                if holding is None or holding.amount < order.amount:
                    raise ConflictError("redemption exceeds available holding")
                system.balance -= order.amount
                source.balance += order.amount
                debit_account_id, credit_account_id = system.id, source.id
                description = "Mock wealth redemption"
            transaction = TransactionModel(
                id=uuid4(),
                user_id=user_id,
                account_id=source.id,
                reference=f"WLT-{order.id}",
                status=TransactionStatus.COMPLETED,
                kind=TransactionKind.TRANSFER,
                origin=TransactionOrigin.BANK,
                amount=order.amount,
                currency=order.currency,
                description=description,
                category="WEALTH",
                posted_at=datetime.now(UTC),
            )
            self.session.add(transaction)
            self.session.flush()
            LedgerService(self.session).post_transfer(
                transaction_id=transaction.id,
                source_account_id=debit_account_id,
                destination_account_id=credit_account_id,
                amount=order.amount,
                currency=order.currency,
            )
            if holding is None:
                if order.order_type == WealthOrderType.REDEMPTION:
                    raise ConflictError("redemption holding was not found")
                holding = WealthHoldingModel(
                    id=uuid4(),
                    user_id=user_id,
                    product_id=order.product_id,
                    amount=Decimal("0.00"),
                    currency=order.currency,
                )
                self.session.add(holding)
            if order.order_type == WealthOrderType.SUBSCRIPTION:
                holding.amount += order.amount
            else:
                holding.amount -= order.amount
            order.transaction_id = transaction.id
            order.status = "COMPLETED"
            self.session.add(
                AuditEventModel(
                    id=uuid4(),
                    actor_user_id=user_id,
                    action=action,
                    resource_type="wealth_order",
                    resource_id=str(order.id),
                    trace_id=current_trace_id(),
                    outcome="COMPLETED",
                    details={"transaction_id": str(transaction.id)},
                )
            )
            return order
