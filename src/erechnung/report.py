"""Assemble the JSON report from the validation result and the extracted fields; response models for OpenAPI."""

from __future__ import annotations

import datetime as dt
from dataclasses import asdict
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from .extract import Felder
from .validator import Meldung, Pruefergebnis

DEFAULT_HTML_MAX_CHARS = 1_000_000  # a Dataverse multiline text column holds at most 1,048,576 characters


def _json_value(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dt.date):
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
    datei_sha256: str | None = None,
    html_max_chars: int = DEFAULT_HTML_MAX_CHARS,
) -> dict:
    fehler = _meldungen(pruefung.fehler) if pruefung else []
    warnungen = _meldungen(list(zusatz_warnungen) + (pruefung.warnungen if pruefung else []))
    html = pruefung.bericht_html if pruefung else None
    vollstaendig = True
    if html is not None and len(html) > html_max_chars:
        html, vollstaendig = None, False
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
        "validator_bericht_html": html,
        "bericht_html_vollstaendig": vollstaendig,
        "datei_sha256": datei_sha256,
    }


class MeldungModel(BaseModel):
    ebene: str = Field(description="error, warning oder information")
    code: str | None = Field(description="Regelkennung, z. B. BR-DE-15")
    text: str
    ort: str | None = Field(description="XPath der Fundstelle mit Präfixen (ubl:, cbc:, cac:, rsm:, ram:, udt:, qdt:)")
    zeile: int | None
    spalte: int | None


class FelderModel(BaseModel):
    rechnungsnummer: str | None = Field(description="BT-1")
    rechnungsdatum: dt.date | None = Field(description="BT-2")
    faelligkeitsdatum: dt.date | None = Field(description="BT-9")
    rechnungstyp: str | None = Field(description="BT-3")
    waehrung: str | None = Field(description="BT-5")
    leitweg_id: str | None = Field(description="BT-10")
    verkaeufer_name: str | None = Field(description="BT-27, sonst BT-28")
    verkaeufer_ust_idnr: str | None = Field(description="BT-31")
    kaeufer_name: str | None = Field(description="BT-44, sonst BT-45")
    iban: str | None = Field(description="BT-84")
    netto: float | None = Field(description="BT-109")
    steuer: float | None = Field(description="BT-110")
    brutto: float | None = Field(description="BT-112")
    faelliger_betrag: float | None = Field(description="BT-115")


class ValidateResponse(BaseModel):
    dateityp: str = Field(description="pdf oder xml (nach Inhalt erkannt)")
    syntax: str = Field(description="UBL oder CII")
    profil: str | None
    gueltig: bool | None = Field(description="null, wenn nicht geprüft (Profil außerhalb, kein Szenario)")
    szenario: str | None
    fehler: list[MeldungModel]
    warnungen: list[MeldungModel]
    felder: FelderModel
    archivname: str
    validator_bericht_html: str | None = Field(description="HTML-Bericht des KoSIT-Validators; null, wenn zu groß")
    bericht_html_vollstaendig: bool = Field(description="false, wenn der HTML-Bericht wegen seiner Größe weggelassen wurde")
    datei_sha256: str | None = Field(description="SHA-256 der hochgeladenen Datei (hex)")


class ValidatorZustand(BaseModel):
    model_config = ConfigDict(extra="allow")
    status: str = Field(description="UP oder DOWN; dazu http (Statuscode) oder detail (Fehler)")


class Versionen(BaseModel):
    service: str
    validator: str
    scenarios: str


class HealthResponse(BaseModel):
    status: str = Field(description="ok (HTTP 200) oder degraded (HTTP 503)")
    auth: bool = Field(description="ob /validate den X-Api-Key verlangt")
    validator: ValidatorZustand
    versions: Versionen
