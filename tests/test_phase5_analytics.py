from datetime import date
from decimal import Decimal
from typing import Any, cast
from uuid import uuid4

from sqlalchemy.orm import Session

from banking_core.app.domain.enums import Currency
from banking_core.app.services.analytics import BudgetService, categorize


def test_deterministic_category_rules_and_unknown() -> None:
    assert categorize("Demo Supermarket Purchase") == "GROCERIES"
    assert categorize("Unmapped Fictional Merchant") == "UNKNOWN"


class RecordingSession:
    def __init__(self) -> None:
        self.item: object | None = None

    def add(self, item: object) -> None:
        self.item = item

    def commit(self) -> None:
        pass


def test_budget_service_preserves_an_exact_day() -> None:
    session = RecordingSession()
    budget = BudgetService(cast(Session, cast(Any, session))).create(
        uuid4(), "DINING", date(2026, 11, 2), Decimal("100.00"), Currency.CNY
    )

    assert budget.month == date(2026, 11, 2)
    assert session.item is budget
