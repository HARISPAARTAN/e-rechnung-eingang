"""Archive name: date, seller slug and invoice-number slug. The original file itself is never renamed."""

from __future__ import annotations

import re

from .extract import Felder

_UMLAUTS = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss", "Ä": "ae", "Ö": "oe", "Ü": "ue"})
_MAX = 60


def slug(text: str | None) -> str:
    if not text or not text.strip():
        return "unbekannt"
    s = text.translate(_UMLAUTS).lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    s = re.sub(r"-{2,}", "-", s)
    return (s[:_MAX].rstrip("-")) or "unbekannt"


def archive_name(felder: Felder, dateityp: str) -> str:
    datum = felder.rechnungsdatum.isoformat() if felder.rechnungsdatum else "0000-00-00"
    return f"{datum}_{slug(felder.verkaeufer_name)}_{slug(felder.rechnungsnummer)}.{dateityp}"
