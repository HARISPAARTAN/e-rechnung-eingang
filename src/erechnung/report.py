"""Assemble the JSON report from the validation result and the extracted fields."""

from __future__ import annotations

from dataclasses import asdict
from datetime import date
from decimal import Decimal

from .extract import Felder
from .validator import Meldung, Pruefergebnis


def _json_value(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, date):
        return value.isoformat()
    return value


def _meldungen(items: list[Meldung]) -> list[dict]:
    return [asdict(m) for m in items]


def build_report(
    dateityp: str,
    syntax: str,
    profil: str | None,
    pruefung: Pruefergebnis | None,
    felder: Felder,
    archivname: str,
    zusatz_warnungen: list[Meldung],
) -> dict:
    fehler = _meldungen(pruefung.fehler) if pruefung else []
    warnungen = _meldungen(list(zusatz_warnungen) + (pruefung.warnungen if pruefung else []))
    return {
        "dateityp": dateityp,
        "syntax": syntax,
        "profil": profil,
        "gueltig": pruefung.gueltig if pruefung else None,
        "szenario": pruefung.szenario if pruefung else None,
        "fehler": fehler,
        "warnungen": warnungen,
        "felder": {k: _json_value(v) for k, v in asdict(felder).items()},
        "archivname": archivname,
        "validator_bericht_html": pruefung.bericht_html if pruefung else None,
    }
