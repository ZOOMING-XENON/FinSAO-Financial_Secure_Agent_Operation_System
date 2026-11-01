"""Deterministic parsing for user-reported expenses."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation

from shared.expense_taxonomy import categorize_merchant

_CURRENCY_MAP = {
    "$": "USD",
    "usd": "USD",
    "dollar": "USD",
    "dollars": "USD",
    "美元": "USD",
    "¥": "CNY",
    "cny": "CNY",
    "rmb": "CNY",
    "yuan": "CNY",
    "元": "CNY",
    "€": "EUR",
    "eur": "EUR",
    "euro": "EUR",
    "euros": "EUR",
}

_AMOUNT = re.compile(r"(?<![\d.])(\d+(?:\.\d{1,2})?)(?![\d.])")
_AMOUNT_WITH_CURRENCY = re.compile(
    r"(?<![\d.])(?P<amount>\d+(?:\.\d{1,2})?)\s*"
    r"(?P<currency>dollars?|usd|yuan|rmb|cny|元|美元|euros?|eur|\$|¥|€)",
    re.IGNORECASE,
)
_CURRENCY_WITH_AMOUNT = re.compile(
    r"(?P<currency>\$|¥|€|usd|cny|rmb|eur)\s*"
    r"(?P<amount>\d+(?:\.\d{1,2})?)",
    re.IGNORECASE,
)
_MERCHANT_AFTER = re.compile(
    r"^(?:on|for|at|from|to|买了|买|在)\s*(.+)$",
    re.IGNORECASE,
)
_LEADING = re.compile(
    r"^(?:i|we|me|my|the|a|an|this|that|just|"
    r"spent|paid|bought|charged|cost|"
    r"花了|我花了|消费|支付|买了|我买了)\s+",
    re.IGNORECASE,
)
_TRAILING = re.compile(
    r"\s+(?:today|yesterday|tonight|this morning|last night|"
    r"今天|昨天|今晚|今早|昨晚)$",
    re.IGNORECASE,
)
_NON_MERCHANT = {
    "i",
    "me",
    "spent",
    "spend",
    "paid",
    "pay",
    "bought",
    "buy",
    "charged",
    "cost",
    "got paid",
    "received",
    "我",
    "花了",
    "我花了",
    "消费",
    "支付",
    "买了",
    "我买了",
}


@dataclass(frozen=True, slots=True)
class ExpenseCapture:
    amount: str | None
    currency: str | None
    merchant: str | None
    occurred_at: datetime
    category: str | None
    origin: str
    ambiguous: bool = False


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", text)).strip()


def _currency(value: str | None) -> str | None:
    if not value:
        return None
    return _CURRENCY_MAP.get(value.casefold(), None)


def _clean_merchant(value: str | None) -> str | None:
    if not value:
        return None
    candidate = _TRAILING.sub("", value.strip(" \t,.;:!?。！？，；："))
    previous = None
    while candidate and candidate != previous:
        previous = candidate
        candidate = _LEADING.sub("", candidate).strip()
        candidate = re.sub(r"^(?:for|on|at|from|to|was|cost|me)\s+", "", candidate, flags=re.I)
        candidate = candidate.strip(" \t,.;:!?。！？，；：")
    candidate = re.sub(
        r"\s+(?:cost|cost me|was|for|at|on|from)$", "", candidate, flags=re.I
    ).strip()
    if not candidate or _AMOUNT.fullmatch(candidate):
        return None
    if candidate.casefold() in _NON_MERCHANT:
        return None
    return candidate[:120]


def _amount(text: str) -> tuple[Decimal | None, str | None, int, int]:
    match = _AMOUNT_WITH_CURRENCY.search(text)
    if match is not None:
        return (
            Decimal(match.group("amount")),
            _currency(match.group("currency")),
            match.start(),
            match.end(),
        )
    match = _CURRENCY_WITH_AMOUNT.search(text)
    if match is not None:
        return (
            Decimal(match.group("amount")),
            _currency(match.group("currency")),
            match.start(),
            match.end(),
        )
    match = _AMOUNT.search(text)
    if match is not None:
        try:
            return Decimal(match.group(1)), None, match.start(), match.end()
        except InvalidOperation:
            return None, None, match.start(), match.end()
    return None, None, 0, 0


def parse_expense(text: str, *, now: datetime) -> ExpenseCapture:
    normalized = _normalize(text)
    amount, currency, start, end = _amount(normalized)
    merchant: str | None = None
    if amount is None:
        marker = re.search(
            r"(?:on|for|at|from|买|买了|在)\s*(.+)$", normalized, re.IGNORECASE
        )
        merchant = _clean_merchant(
            marker.group(1) if marker is not None else normalized
        )
    else:
        after = normalized[end:].strip()
        after_match = _MERCHANT_AFTER.match(after)
        if after_match is not None:
            merchant = _clean_merchant(after_match.group(1))
        if merchant is None:
            before = normalized[:start].strip()
            if before:
                merchant = _clean_merchant(before)
    occurred_at = now
    lowered = normalized.casefold()
    if any(word in lowered for word in ("yesterday", "昨天")):
        occurred_at = now - timedelta(days=1)
    elif any(word in lowered for word in ("last night", "昨晚")):
        occurred_at = (now - timedelta(days=1)).replace(hour=20, minute=0, second=0, microsecond=0)
    elif any(word in lowered for word in ("this morning", "今早")):
        occurred_at = now.replace(hour=8, minute=0, second=0, microsecond=0)
    ambiguous = bool(
        merchant
        and (
            re.search(r"\band\b|、|以及|和", merchant, re.IGNORECASE)
            or len(_AMOUNT.findall(normalized)) > 1
        )
    )
    amount_text = format(amount.quantize(Decimal("0.01")), "f") if amount is not None else None
    return ExpenseCapture(
        amount=amount_text,
        currency=currency or ("CNY" if amount is not None else None),
        merchant=None if ambiguous else merchant,
        occurred_at=occurred_at,
        category=categorize_merchant(merchant) if merchant and not ambiguous else None,
        origin="CASH",
        ambiguous=ambiguous,
    )
