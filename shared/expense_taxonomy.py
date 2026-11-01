"""Shared expense taxonomy and query vocabulary."""

from __future__ import annotations

import re
import unicodedata

EXPENSE_CATEGORIES = frozenset(
    {
        "DINING",
        "GROCERIES",
        "TRANSPORT",
        "HOUSEHOLD",
        "ENTERTAINMENT",
        "HEALTHCARE",
        "EDUCATION",
        "TRAVEL",
        "SHOPPING",
        "UTILITIES",
        "FEES",
        "INTERNAL_TRANSFER",
        "OPENING_BALANCE",
        "UNKNOWN",
    }
)
EXCLUDED_EXPENSE_CATEGORIES = frozenset({"INTERNAL_TRANSFER", "OPENING_BALANCE"})
EXPENSE_SORT_FIELDS = frozenset({"posted_at", "amount", "category", "merchant"})
EXPENSE_SORT_DIRECTIONS = frozenset({"asc", "desc"})


def normalize_category(value: str) -> str:
    category = value.strip().upper()
    if category not in EXPENSE_CATEGORIES:
        raise ValueError(f"unsupported expense category: {value}")
    return category


def normalize_merchant(value: str) -> str:
    text = unicodedata.normalize("NFKC", value).casefold()
    text = re.sub(r"\s+", " ", text).strip()
    return text[:80]


def escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
