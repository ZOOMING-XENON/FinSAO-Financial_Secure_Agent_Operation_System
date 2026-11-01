"""Shared expense taxonomy, merchant aliases, and query vocabulary."""

from __future__ import annotations

import re
import unicodedata

EXPENSE_CATEGORIES = frozenset(
    {
        "DINING",
        "GROCERIES",
        "TRANSPORT",
        "HOUSEHOLD",
        "UTILITIES",
        "ENTERTAINMENT",
        "SUBSCRIPTIONS",
        "HEALTHCARE",
        "EDUCATION",
        "CHILDCARE",
        "TRAVEL",
        "SHOPPING",
        "PERSONAL_CARE",
        "PETS",
        "GIFTS",
        "INSURANCE",
        "TAXES",
        "FEES",
        "REPAIRS",
        "OTHER",
        "INTERNAL_TRANSFER",
        "OPENING_BALANCE",
        "UNKNOWN",
    }
)
EXCLUDED_EXPENSE_CATEGORIES = frozenset({"INTERNAL_TRANSFER", "OPENING_BALANCE"})
EXPENSE_SORT_FIELDS = frozenset({"posted_at", "amount", "category", "merchant"})
EXPENSE_SORT_DIRECTIONS = frozenset({"asc", "desc"})

CATEGORY_ALIASES: dict[str, str] = {
    "coffee": "DINING",
    "latte": "DINING",
    "lunch": "DINING",
    "dinner": "DINING",
    "breakfast": "DINING",
    "restaurant": "DINING",
    "cafe": "DINING",
    "takeout": "DINING",
    "takeaway": "DINING",
    "coke": "GROCERIES",
    "cola": "GROCERIES",
    "soda": "GROCERIES",
    "milk": "GROCERIES",
    "eggs": "GROCERIES",
    "grocery": "GROCERIES",
    "groceries": "GROCERIES",
    "supermarket": "GROCERIES",
    "market": "GROCERIES",
    "taxi": "TRANSPORT",
    "didi": "TRANSPORT",
    "uber": "TRANSPORT",
    "metro": "TRANSPORT",
    "bus": "TRANSPORT",
    "fuel": "TRANSPORT",
    "parking": "TRANSPORT",
    "rent": "HOUSEHOLD",
    "electricity": "UTILITIES",
    "water bill": "UTILITIES",
    "internet": "UTILITIES",
    "phone bill": "UTILITIES",
    "netflix": "SUBSCRIPTIONS",
    "spotify": "SUBSCRIPTIONS",
    "icloud": "SUBSCRIPTIONS",
    "subscription": "SUBSCRIPTIONS",
    "movie": "ENTERTAINMENT",
    "cinema": "ENTERTAINMENT",
    "pharmacy": "HEALTHCARE",
    "clinic": "HEALTHCARE",
    "hospital": "HEALTHCARE",
    "doctor": "HEALTHCARE",
    "medicine": "HEALTHCARE",
    "tuition": "EDUCATION",
    "course": "EDUCATION",
    "book": "EDUCATION",
    "school": "EDUCATION",
    "daycare": "CHILDCARE",
    "nanny": "CHILDCARE",
    "flight": "TRAVEL",
    "hotel": "TRAVEL",
    "airbnb": "TRAVEL",
    "train": "TRAVEL",
    "clothes": "SHOPPING",
    "shoes": "SHOPPING",
    "shirt": "SHOPPING",
    "haircut": "PERSONAL_CARE",
    "salon": "PERSONAL_CARE",
    "soap": "PERSONAL_CARE",
    "pet": "PETS",
    "vet": "PETS",
    "dog food": "PETS",
    "cat food": "PETS",
    "gift": "GIFTS",
    "present": "GIFTS",
    "insurance": "INSURANCE",
    "tax": "TAXES",
    "fee": "FEES",
    "repair": "REPAIRS",
    "plumber": "REPAIRS",
}


def normalize_category(value: str) -> str:
    category = value.strip().upper()
    if category not in EXPENSE_CATEGORIES:
        raise ValueError(f"unsupported expense category: {value}")
    return category


def normalize_merchant(value: str) -> str:
    text = unicodedata.normalize("NFKC", value).casefold()
    text = re.sub(r"\s+", " ", text).strip()
    return text[:80]


def categorize_merchant(value: str) -> str | None:
    normalized = normalize_merchant(value)
    if not normalized:
        return None
    for alias in sorted(CATEGORY_ALIASES, key=len, reverse=True):
        if alias in normalized:
            return CATEGORY_ALIASES[alias]
    return None


def escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
