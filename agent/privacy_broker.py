"""Deterministic egress redaction for model-bound text."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass


@dataclass(frozen=True)
class TokenizedText:
    text: str
    replacements: dict[str, str]


class PrivacyBroker:
    """Best-effort deterministic identifiers-only redaction.

    This covers phones, emails, UUIDs, account/card-like digit runs, and
    configured names. Free-text name recall is deliberately not claimed.
    """

    _RESERVED = re.compile(r"\[(?:PERSON|PHONE|EMAIL|ACCOUNT|CARD|AMOUNT)_\d+\]|\$[ARC]\d+")
    _RULES = (
        ("EMAIL", re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")),
        (
            "UUID",
            re.compile(
                r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-"
                r"[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}\b"
            ),
        ),
        ("PHONE", re.compile(r"(?<!\d)(?:\+?86[- ]?)?1[3-9]\d{9}(?!\d)")),
        ("CARD", re.compile(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)")),
        ("ACCOUNT", re.compile(r"(?<!\d)\d{8,20}(?!\d)")),
    )

    def __init__(self, names: tuple[str, ...] = ()) -> None:
        self._names = tuple(name for name in names if name)

    def tokenize(self, text: str) -> TokenizedText:
        normalized = unicodedata.normalize("NFKC", text)
        if self._RESERVED.search(normalized):
            raise ValueError("reserved placeholder syntax is not allowed in user text")
        replacements: dict[str, str] = {}
        counters: dict[str, int] = {}
        result = normalized
        for label, pattern in self._RULES:
            def replace(match: re.Match[str], label: str = label) -> str:
                value = match.group(0)
                for token, original in replacements.items():
                    if original == value:
                        return token
                counters[label] = counters.get(label, 0) + 1
                token = f"[{label}_{counters[label]}]"
                replacements[token] = value
                return token

            result = pattern.sub(replace, result)
        person_count = 0
        for name in sorted(self._names, key=len, reverse=True):
            if name in result:
                person_count += 1
                token = f"[PERSON_{person_count}]"
                replacements[token] = name
                result = result.replace(name, token)
        return TokenizedText(text=result, replacements=replacements)

    def has_residual_identifier(self, text: str) -> bool:
        if self._RESERVED.search(text):
            return True
        return any(pattern.search(text) for _, pattern in self._RULES)
