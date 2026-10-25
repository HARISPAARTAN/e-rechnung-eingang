from datetime import date
from decimal import Decimal

from erechnung.extract import Felder
from erechnung.report import build_report
from erechnung.validator import Meldung, Pruefergebnis


def test_report_shape_and_json_types():
    p = Pruefergebnis(True, "accept", "XRechnung 3.0.2 UBL", [], [Meldung("warning", "BR-DE-W", "Hinweis")], "<html/>")
    f = Felder(rechnungsnummer="RE-1", rechnungsdatum=date(2026, 10, 1), brutto=Decimal("1190.00"), waehrung="EUR")
    r = build_report("xml", "UBL", "urn:x", p, f, "2026-10-01_a_re-1.xml", [])
    assert r["dateityp"] == "xml" and r["syntax"] == "UBL" and r["profil"] == "urn:x" and r["gueltig"] is True
    assert r["fehler"] == [] and r["warnungen"] == [{"ebene": "warning", "code": "BR-DE-W", "text": "Hinweis", "ort": None, "zeile": None, "spalte": None}]
    assert r["felder"]["rechnungsdatum"] == "2026-10-01" and r["felder"]["brutto"] == 1190.0 and r["felder"]["netto"] is None
    assert r["archivname"] == "2026-10-01_a_re-1.xml" and r["validator_bericht_html"] == "<html/>"
    assert r["szenario"] == "XRechnung 3.0.2 UBL" and r["bericht_html_vollstaendig"] is True and r["datei_sha256"] is None


def test_report_without_validation():
    w = [Meldung("warning", "PROFIL-AUSSERHALB", "Profil außerhalb der XRechnung-Prüfregeln")]
    r = build_report("pdf", "CII", "urn:factur-x.eu:1p0:basic", None, Felder(), "0000-00-00_unbekannt_unbekannt.pdf", w)
    assert r["gueltig"] is None and r["warnungen"][0]["code"] == "PROFIL-AUSSERHALB" and r["validator_bericht_html"] is None


def test_html_above_the_limit_is_omitted_with_flag():
    p = Pruefergebnis(True, "accept", "X", [], [], "<html>" + "x" * 100 + "</html>")
    r = build_report("xml", "UBL", None, p, Felder(), "a.xml", [], datei_sha256="ab" * 32, html_max_chars=100)
    assert r["validator_bericht_html"] is None and r["bericht_html_vollstaendig"] is False and r["datei_sha256"] == "ab" * 32


def test_html_at_the_limit_is_kept():
    html = "<html>" + "x" * 87 + "</html>"
    assert len(html) == 100
    r = build_report("xml", "UBL", None, Pruefergebnis(True, "accept", "X", [], [], html), Felder(), "a.xml", [], html_max_chars=100)
    assert r["validator_bericht_html"] == html and r["bericht_html_vollstaendig"] is True


def test_report_validates_against_the_response_model():
    from erechnung.report import ValidateResponse

    p = Pruefergebnis(False, "reject", "X", [Meldung("error", "BR-1", "t", "ubl:Invoice[1]", 1, 2)], [], None)
    f = Felder(rechnungsnummer="RE-1", rechnungsdatum=date(2026, 10, 1), brutto=Decimal("1190.00"))
    r = build_report("xml", "UBL", "urn:x", p, f, "a.xml", [], datei_sha256="00" * 32)
    assert ValidateResponse.model_validate(r).model_dump(mode="json") == r
