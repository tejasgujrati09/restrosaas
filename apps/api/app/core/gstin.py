"""GSTIN validation: structure plus the mod-36 check character."""

from __future__ import annotations

import re

_STRUCTURE = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")
_ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def _check_char(body: str) -> str:
    total = 0
    for index, char in enumerate(body):
        product = _ALPHABET.index(char) * (1 if index % 2 == 0 else 2)
        total += product // 36 + product % 36
    return _ALPHABET[(36 - total % 36) % 36]


def is_valid_gstin(gstin: str) -> bool:
    return bool(_STRUCTURE.fullmatch(gstin)) and _check_char(gstin[:14]) == gstin[14]


def gstin_state_code(gstin: str) -> str:
    return gstin[:2]
