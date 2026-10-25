from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from erechnung.api import create_app
from erechnung.config import load_settings
from erechnung.validator import Meldung, Pruefergebnis, ValidatorError

ROOT = Path(__file__).resolve().parents[2]
FX = ROOT / "fixtures"


class StubClient:
    def __init__(self, result=None, error=None, health=None):
        self.result, self.error, self.calls = result, error, []
        self._health = health if health is not None else {"status": "UP", "http": 200}

    def health(self):
        if isinstance(self._health, Exception):
            raise self._health
        return self._health

    def validate(self, xml, name="rechnung.xml"):
        self.calls.append(name)
        if self.error:
            raise self.error
        return self.result


def _client(stub, monkeypatch, api_key=None):
    if api_key:
        monkeypatch.setenv("ERE_API_KEY", api_key)
    else:
        monkeypatch.delenv("ERE_API_KEY", raising=False)
    return TestClient(create_app(load_settings(ROOT), client=stub))


def _accept():
    return Pruefergebnis(True, "accept", "XRechnung", [], [], None, b"<r/>")


def test_health(monkeypatch):
    c = _client(StubClient(), monkeypatch)
    body = c.get("/health").json()
    assert body["status"] == "ok" and body["validator"]["status"] == "UP" and body["versions"]["validator"] == "1.6.3"


def test_health_degraded_when_validator_unreachable(monkeypatch):
    c = _client(StubClient(health=ValidatorError("Validator nicht erreichbar: boom")), monkeypatch)
    body = c.get("/health").json()
    assert body["status"] == "degraded"
    assert body["validator"] == {"status": "DOWN", "detail": "Validator nicht erreichbar: boom"}


def test_health_degraded_when_validator_reports_down(monkeypatch):
    c = _client(StubClient(health={"status": "DOWN", "http": 503}), monkeypatch)
    body = c.get("/health").json()
    assert body["status"] == "degraded" and body["validator"] == {"status": "DOWN", "http": 503}


def test_validate_xml_fixture(monkeypatch):
    stub = StubClient(result=_accept())
    c = _client(stub, monkeypatch)
    files = {"file": ("01.01a-INVOICE_ubl.xml", (FX / "xrechnung" / "01.01a-INVOICE_ubl.xml").read_bytes(), "application/xml")}
    body = c.post("/validate", files=files).json()
    assert body["dateityp"] == "xml" and body["syntax"] == "UBL" and body["gueltig"] is True
    assert body["felder"]["rechnungsnummer"] and body["archivname"].endswith(".xml")
    assert stub.calls == ["01.01a-INVOICE_ubl.xml"]


def test_validate_pdf_fixture(monkeypatch):
    c = _client(StubClient(result=_accept()), monkeypatch)
    pdf = (FX / "zugferd" / "synthetisch" / "nordstern-elbnetz-RE-2026-0042.pdf").read_bytes()
    body = c.post("/validate", files={"file": ("re.pdf", pdf, "application/pdf")}).json()
    assert body["dateityp"] == "pdf" and body["syntax"] == "CII" and body["felder"]["brutto"] == 1190.0
    assert body["archivname"] == "2026-10-01_nordstern-projektmanagement-gmbh_re-2026-0042.pdf"


def test_profile_below_en16931_skips_validator(monkeypatch):
    stub = StubClient(result=_accept())
    c = _client(stub, monkeypatch)
    xml = (
        b'<rsm:CrossIndustryInvoice xmlns:rsm="urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100" '
        b'xmlns:ram="urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100">'
        b"<rsm:ExchangedDocumentContext><ram:GuidelineSpecifiedDocumentContextParameter><ram:ID>urn:factur-x.eu:1p0:minimum</ram:ID>"
        b"</ram:GuidelineSpecifiedDocumentContextParameter></rsm:ExchangedDocumentContext><rsm:ExchangedDocument><ram:ID>M-1</ram:ID></rsm:ExchangedDocument>"
        b"</rsm:CrossIndustryInvoice>"
    )
    body = c.post("/validate", files={"file": ("m.xml", xml, "application/xml")}).json()
    assert body["gueltig"] is None and body["warnungen"][0]["code"] == "PROFIL-AUSSERHALB" and stub.calls == []


def test_422_for_text_broken_xml_and_pdf_without_attachment(monkeypatch):
    c = _client(StubClient(result=_accept()), monkeypatch)
    for name in ("text.txt", "kaputt.xml", "kein-anhang.pdf"):
        resp = c.post("/validate", files={"file": (name, (FX / "broken" / name).read_bytes(), "application/octet-stream")})
        assert resp.status_code == 422, name
        assert resp.json()["detail"]


def test_502_when_validator_fails(monkeypatch):
    c = _client(StubClient(error=ValidatorError("down")), monkeypatch)
    resp = c.post("/validate", files={"file": ("a.xml", (FX / "xrechnung" / "01.01a-INVOICE_ubl.xml").read_bytes(), "application/xml")})
    assert resp.status_code == 502 and "down" in resp.json()["detail"]


def test_api_key_required_when_configured(monkeypatch):
    c = _client(StubClient(result=_accept()), monkeypatch, api_key="geheim")
    files = {"file": ("a.xml", (FX / "xrechnung" / "01.01a-INVOICE_ubl.xml").read_bytes(), "application/xml")}
    assert c.post("/validate", files=files).status_code == 401
    assert c.post("/validate", files=files, headers={"X-Api-Key": "falsch"}).status_code == 401
    assert c.post("/validate", files=files, headers={"X-Api-Key": "geheim"}).status_code == 200
    assert c.get("/health").status_code == 200


def test_non_ascii_api_key_does_not_crash(monkeypatch):
    files = {"file": ("a.xml", (FX / "xrechnung" / "01.01a-INVOICE_ubl.xml").read_bytes(), "application/xml")}
    c = _client(StubClient(result=_accept()), monkeypatch, api_key="geheim")
    assert c.post("/validate", files=files, headers={"X-Api-Key": "falsch-ä".encode()}).status_code == 401


def test_413_for_oversized_upload(monkeypatch):
    c = _client(StubClient(result=_accept()), monkeypatch)
    big = b"<a>" + b"x" * (10 * 1024 * 1024 + 1) + b"</a>"
    assert c.post("/validate", files={"file": ("big.xml", big, "application/xml")}).status_code == 413


@pytest.mark.parametrize("ebene", ["error", "warning"])
def test_messages_are_passed_through(monkeypatch, ebene):
    m = Meldung(ebene, "BR-01", "Text", "/x", 3, 4)
    result = Pruefergebnis(ebene != "error", "reject" if ebene == "error" else "accept", "X", [m] if ebene == "error" else [], [m] if ebene == "warning" else [], None, b"")
    c = _client(StubClient(result=result), monkeypatch)
    body = c.post("/validate", files={"file": ("a.xml", (FX / "xrechnung" / "01.01a-INVOICE_ubl.xml").read_bytes(), "application/xml")}).json()
    key = "fehler" if ebene == "error" else "warnungen"
    assert body[key] == [{"ebene": ebene, "code": "BR-01", "text": "Text", "ort": "/x", "zeile": 3, "spalte": 4}]


def test_no_scenario_matched_adds_warning(monkeypatch):
    c = _client(StubClient(result=Pruefergebnis(None, "reject", None, [], [], None, b"")), monkeypatch)
    body = c.post("/validate", files={"file": ("a.xml", (FX / "xrechnung" / "01.01a-INVOICE_ubl.xml").read_bytes(), "application/xml")}).json()
    assert body["gueltig"] is None and body["szenario"] is None
    assert [w["code"] for w in body["warnungen"]] == ["KEIN-SZENARIO"]


def test_upload_name_is_sanitised_before_the_daemon(monkeypatch):
    stub = StubClient(result=_accept())
    c = _client(stub, monkeypatch)
    xml = (FX / "xrechnung" / "01.01a-INVOICE_ubl.xml").read_bytes()
    c.post("/validate", files={"file": ("../../März Rechnung?.xml", xml, "application/xml")})
    assert stub.calls == ["M-rz-Rechnung-.xml"]


def test_unreadable_pdf_is_422(monkeypatch):
    c = _client(StubClient(result=_accept()), monkeypatch)
    resp = c.post("/validate", files={"file": ("x.pdf", b"%PDF-1.7\nthis is not a pdf at all", "application/pdf")})
    assert resp.status_code == 422 and resp.json()["detail"] == "PDF nicht lesbar"
