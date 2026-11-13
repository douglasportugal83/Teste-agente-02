"""Normalização de nomes de símbolos e inferência de categoria para fontes externas."""

import re

from app.models.enums import AssetCategory
from app.services.catalog import DEFAULT_SYMBOLS, SYMBOL_ALIASES

_CATALOG = {name: (category, base, quote) for name, _, category, base, quote, _ in DEFAULT_SYMBOLS}
_FIAT = {"USD", "EUR", "GBP", "JPY", "CHF", "CAD", "AUD", "NZD", "SEK", "NOK", "MXN", "ZAR"}
_CRYPTO = {"BTC", "ETH", "LTC", "XRP", "SOL", "ADA", "DOGE", "BNB", "DOT", "LINK"}
_METALS = {"XAU", "XAG", "XPT", "XPD"}


def canonical_name(source_name: str) -> str:
    """'EURUSD.m' -> 'EURUSD'; 'USTEC' -> 'NAS100'; 'XAUUSDm' -> 'XAUUSD'."""
    name = source_name.strip().upper()
    name = re.split(r"[.\-_#]", name, maxsplit=1)[0] or name
    if name in SYMBOL_ALIASES:
        return SYMBOL_ALIASES[name]
    if name in _CATALOG:
        return name
    # Sufixos de corretora colados ao nome (ex.: "XAUUSDm", "EURUSDPRO").
    for known in (*_CATALOG, *SYMBOL_ALIASES):
        if name.startswith(known) and len(name) - len(known) <= 3:
            return SYMBOL_ALIASES.get(known, known)
    return name


def is_default_symbol(canonical: str) -> bool:
    return canonical in _CATALOG


def infer_category(canonical: str, path: str = "") -> AssetCategory:
    if canonical in _CATALOG:
        return _CATALOG[canonical][0]
    base, quote = canonical[:3], canonical[3:6]
    if base in _METALS:
        return AssetCategory.METALS
    if base in _CRYPTO or any(canonical.startswith(c) for c in _CRYPTO):
        return AssetCategory.CRYPTO
    if len(canonical) == 6 and base in _FIAT and quote in _FIAT:
        return AssetCategory.FOREX
    hint = path.lower()
    for words, category in (
        (("crypto", "cripto"), AssetCategory.CRYPTO),
        (("metal",), AssetCategory.METALS),
        (("indic", "index", "indices"), AssetCategory.INDICES),
        (("forex", "fx"), AssetCategory.FOREX),
    ):
        if any(word in hint for word in words):
            return category
    return AssetCategory.OTHER


def currencies(canonical: str) -> tuple[str | None, str | None]:
    if canonical in _CATALOG:
        return _CATALOG[canonical][1], _CATALOG[canonical][2]
    if len(canonical) == 6 and canonical.isalpha():
        return canonical[:3], canonical[3:]
    return None, None
