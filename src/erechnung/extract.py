"""EN 16931 header fields through one XPath map per syntax. Amounts as Decimal, dates as date, missing as None."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, fields
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from lxml import etree

from .syntax import NS, Syntax

DATE_FIELDS = {"rechnungsdatum", "faelligkeitsdatum"}
AMOUNT_FIELDS = {"netto", "steuer", "brutto", "faelliger_betrag"}


@dataclass(frozen=True)
class Felder:
    rechnungsnummer: str | None = None
    rechnungsdatum: date | None = None
    faelligkeitsdatum: date | None = None
    rechnungstyp: str | None = None
    waehrung: str | None = None
    leitweg_id: str | None = None
    verkaeufer_name: str | None = None
    verkaeufer_ust_idnr: str | None = None
    kaeufer_name: str | None = None
    iban: str | None = None
    netto: Decimal | None = None
    steuer: Decimal | None = None
    brutto: Decimal | None = None
    faelliger_betrag: Decimal | None = None


def _load_map(xpath_dir: Path, syntax: Syntax) -> dict[str, str]:
    return tomllib.loads((Path(xpath_dir) / f"{syntax.value.lower()}.toml").read_text(encoding="utf-8"))


def _first_text(root: etree._Element, expr: str) -> str | None:
    hits = root.xpath(expr, namespaces=NS)
    for hit in hits:
        text = hit if isinstance(hit, str) else (hit.text or "")
        text = text.strip()
        if text:
            return text
    return None


def _to_date(text: str) -> date | None:
    for fmt in ("%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(text[:10] if fmt == "%Y-%m-%d" else text[:8], fmt).date()
        except ValueError:
            continue
    return None


def _to_amount(text: str) -> Decimal | None:
    try:
        d = Decimal(text.replace(",", "."))
    except InvalidOperation:
        return None
    return d if d.is_finite() else None


def extract_fields(root: etree._Element, syntax: Syntax, xpath_dir: Path) -> Felder:
    expressions = _load_map(xpath_dir, syntax)
    values: dict[str, object] = {}
    for f in fields(Felder):
        expr = expressions.get(f.name)
        text = _first_text(root, expr) if expr else None
        if text is None:
            values[f.name] = None
        elif f.name in DATE_FIELDS:
            values[f.name] = _to_date(text)
        elif f.name in AMOUNT_FIELDS:
            values[f.name] = _to_amount(text)
        else:
            values[f.name] = text
    return Felder(**values)
