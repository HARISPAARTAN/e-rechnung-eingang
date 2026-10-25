from datetime import date
from decimal import Decimal

from erechnung.extract import Felder
from erechnung.report import build_report
from erechnung.validator import Meldung, Pruefergebnis


def test_report_shape_and_json_types():
    p = Pruefergebnis(True, "accept", "XRechnung 3.0.2 UBL", [], [Meldung("warning", "BR-DE-W", "Hinweis")], "<html/>", b"<r/>")
    f = Felder(rechnungsnummer="RE-1", rechnungsdatum=date(2026, 10, 1), brutto=Decimal("1190.00"), waehrung="EUR")
    r = build_report("xml", "UBL", "urn:x", p, f, "2026-10-01_a_re-1.xml", [])
    assert r["dateityp"] == "xml" and r["syntax"] == "UBL" and r["profil"] == "urn:x" and r["gueltig"] is True
    assert r["fehler"] == [] and r["warnungen"] == [{"ebene": "warning", "code": "BR-DE-W", "text": "Hinweis", "ort": None, "zeile": None, "spalte": None}]
    assert r["felder"]["rechnungsdatum"] == "2026-10-01" and r["felder"]["brutto"] == 1190.0 and r["felder"]["netto"] is None
    assert r["archivname"] == "2026-10-01_a_re-1.xml" and r["validator_bericht_html"] == "<html/>"
    assert r["szenario"] == "XRechnung 3.0.2 UBL"


def test_report_without_validation():
    w = [Meldung("warning", "PROFIL-AUSSERHALB", "Profil außerhalb der XRechnung-Prüfregeln")]
    r = build_report("pdf", "CII", "urn:factur-x.eu:1p0:basic", None, Felder(), "0000-00-00_unbekannt_unbekannt.pdf", w)
    assert r["gueltig"] is None and r["warnungen"][0]["code"] == "PROFIL-AUSSERHALB" and r["validator_bericht_html"] is None
