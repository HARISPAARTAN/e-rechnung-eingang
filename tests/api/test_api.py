import hashlib
import io
from pathlib import Path

import pikepdf
import pytest
from fastapi.testclient import TestClient

from erechnung.api import CONFIG_ERROR, create_app
from erechnung.config import load_settings
from erechnung.validator import Meldung, Pruefergebnis, ValidatorError, ValidatorRejectedInput

ROOT = Path(__file__).resolve().parents[2]
FX = ROOT / "fixtures"
UBL = FX / "xrechnung" / "01.01a-INVOICE_ubl.xml"


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


def _client(stub, monkeypatch, api_key=None, **env):
    if api_key:
        monkeypatch.setenv("ERE_API_KEY", api_key)
        monkeypatch.delenv("ERE_AUTH_DISABLED", raising=False)
    else:
        monkeypatch.delenv("ERE_API_KEY", raising=False)
        monkeypatch.setenv("ERE_AUTH_DISABLED", "1")
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    return TestClient(create_app(load_settings(ROOT), client=stub))


def _accept(html=None):
    return Pruefergebnis(True, "accept", "XRechnung", [], [], html)


def _post_ubl(c, **kwargs):
    return c.post("/validate", files={"file": ("a.xml", UBL.read_bytes(), "application/xml")}, **kwargs)


def test_health(monkeypatch):
    resp = _client(StubClient(), monkeypatch).get("/health")
    body = resp.json()
    assert resp.status_code == 200
    assert body["status"] == "ok" and body["validator"] == {"status": "UP", "http": 200} and body["versions"]["validator"] == "1.6.3"
    assert body["auth"] is False


def test_health_reports_auth_when_key_is_set(monkeypatch):
    body = _client(StubClient(), monkeypatch, api_key="geheim").get("/health").json()
    assert body["auth"] is True and list(body) == ["status", "auth", "validator", "versions"]


def test_health_degraded_when_validator_unreachable_is_503(monkeypatch):
    resp = _client(StubClient(health=ValidatorError("Validator nicht erreichbar: boom")), monkeypatch).get("/health")
    assert resp.status_code == 503
    body = resp.json()
    assert body["status"] == "degraded"
    assert body["validator"] == {"status": "DOWN", "detail": "Validator nicht erreichbar: boom"}
    assert body["versions"]["service"]


def test_health_degraded_when_validator_reports_down_is_503(monkeypatch):
    resp = _client(StubClient(health={"status": "DOWN", "http": 503}), monkeypatch).get("/health")
    assert resp.status_code == 503
    assert resp.json()["status"] == "degraded" and resp.json()["validator"] == {"status": "DOWN", "http": 503}


def test_create_app_without_key_fails_closed(monkeypatch):
    monkeypatch.delenv("ERE_API_KEY", raising=False)
    monkeypatch.delenv("ERE_AUTH_DISABLED", raising=False)
    with pytest.raises(RuntimeError, match="ERE_API_KEY fehlt"):
        create_app(load_settings(ROOT), client=StubClient())
    assert CONFIG_ERROR == "ERE_API_KEY fehlt; für Entwicklung ERE_AUTH_DISABLED=1 setzen"


@pytest.mark.parametrize("value", ["1", "true", "yes", "TRUE"])
def test_auth_disabled_serves_without_key(monkeypatch, value):
    monkeypatch.delenv("ERE_API_KEY", raising=False)
    monkeypatch.setenv("ERE_AUTH_DISABLED", value)
    c = TestClient(create_app(load_settings(ROOT), client=StubClient(result=_accept())))
    assert _post_ubl(c).status_code == 200


def test_auth_disabled_zero_still_fails_closed(monkeypatch):
    monkeypatch.delenv("ERE_API_KEY", raising=False)
    monkeypatch.setenv("ERE_AUTH_DISABLED", "0")
    with pytest.raises(RuntimeError):
        create_app(load_settings(ROOT), client=StubClient())


def test_module_app_is_built_lazily_and_fails_with_the_config_error(monkeypatch):
    import erechnung.api as api

    monkeypatch.delenv("ERE_API_KEY", raising=False)
    monkeypatch.delenv("ERE_AUTH_DISABLED", raising=False)
    monkeypatch.delitem(api.__dict__, "app", raising=False)
    with pytest.raises(RuntimeError, match="ERE_API_KEY fehlt"):
        api.app  # noqa: B018


def test_validate_xml_fixture(monkeypatch):
    stub = StubClient(result=_accept())
    c = _client(stub, monkeypatch)
    data = UBL.read_bytes()
    body = c.post("/validate", files={"file": ("01.01a-INVOICE_ubl.xml", data, "application/xml")}).json()
    assert body["dateityp"] == "xml" and body["syntax"] == "UBL" and body["gueltig"] is True
    assert body["felder"]["rechnungsnummer"] and body["archivname"].endswith(".xml")
    assert body["datei_sha256"] == hashlib.sha256(data).hexdigest()
    assert body["bericht_html_vollstaendig"] is True
    assert list(body)[-3:] == ["validator_bericht_html", "bericht_html_vollstaendig", "datei_sha256"]
    assert stub.calls == ["01.01a-INVOICE_ubl.xml"]


def test_validate_pdf_fixture(monkeypatch):
    c = _client(StubClient(result=_accept()), monkeypatch)
    pdf = (FX / "zugferd" / "synthetisch" / "nordstern-elbnetz-RE-2026-0042.pdf").read_bytes()
    body = c.post("/validate", files={"file": ("re.pdf", pdf, "application/pdf")}).json()
    assert body["dateityp"] == "pdf" and body["syntax"] == "CII" and body["felder"]["brutto"] == 1190.0
    assert body["felder"]["rechnungsdatum"] == "2026-10-01"
    assert body["archivname"] == "2026-10-01_nordstern-projektmanagement-gmbh_re-2026-0042.pdf"


def test_html_report_is_dropped_above_the_limit(monkeypatch):
    c = _client(StubClient(result=_accept("<html>" + "x" * 50 + "</html>")), monkeypatch, ERE_HTML_MAX_CHARS="40")
    body = _post_ubl(c).json()
    assert body["validator_bericht_html"] is None and body["bericht_html_vollstaendig"] is False


def test_html_report_is_kept_below_the_limit(monkeypatch):
    c = _client(StubClient(result=_accept("<html/>")), monkeypatch, ERE_HTML_MAX_CHARS="40")
    body = _post_ubl(c).json()
    assert body["validator_bericht_html"] == "<html/>" and body["bericht_html_vollstaendig"] is True


def _cii_with_profile(profile: str) -> bytes:
    return (
        b'<rsm:CrossIndustryInvoice xmlns:rsm="urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100" '
        b'xmlns:ram="urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100">'
        b"<rsm:ExchangedDocumentContext><ram:GuidelineSpecifiedDocumentContextParameter><ram:ID>" + profile.encode() + b"</ram:ID>"
        b"</ram:GuidelineSpecifiedDocumentContextParameter></rsm:ExchangedDocumentContext><rsm:ExchangedDocument><ram:ID>M-1</ram:ID></rsm:ExchangedDocument>"
        b"</rsm:CrossIndustryInvoice>"
    )


@pytest.mark.parametrize(
    "profile,text",
    [
        ("urn:factur-x.eu:1p0:minimum", "Profil MINIMUM: keine vollständige E-Rechnung im Sinne des § 14 UStG, keine Prüfung möglich"),
        ("urn:factur-x.eu:1p0:basicwl", "Profil BASIC WL: keine vollständige E-Rechnung im Sinne des § 14 UStG, keine Prüfung möglich"),
        (
            "urn:cen.eu:en16931:2017#compliant#urn:factur-x.eu:1p0:basic",
            "Profil BASIC: EN-16931-konform, aber ohne KoSIT-Prüfszenario; Prüfung übersprungen",
        ),
    ],
)
def test_profiles_outside_the_scenarios_skip_the_validator(monkeypatch, profile, text):
    stub = StubClient(result=_accept())
    c = _client(stub, monkeypatch)
    body = c.post("/validate", files={"file": ("m.xml", _cii_with_profile(profile), "application/xml")}).json()
    assert body["gueltig"] is None and stub.calls == []
    assert body["warnungen"][0]["code"] == "PROFIL-AUSSERHALB" and body["warnungen"][0]["text"] == text
    assert body["felder"]["rechnungsnummer"] == "M-1"


def test_422_for_text_broken_xml_and_pdf_without_attachment(monkeypatch):
    c = _client(StubClient(result=_accept()), monkeypatch)
    for name in ("text.txt", "kaputt.xml", "kein-anhang.pdf"):
        resp = c.post("/validate", files={"file": (name, (FX / "broken" / name).read_bytes(), "application/octet-stream")})
        assert resp.status_code == 422, name
        assert isinstance(resp.json()["detail"], str) and resp.json()["detail"]


def test_422_detail_is_a_string_when_the_file_part_is_missing(monkeypatch):
    c = _client(StubClient(result=_accept()), monkeypatch)
    resp = c.post("/validate", data={"other": "x"})
    assert resp.status_code == 422
    assert isinstance(resp.json()["detail"], str) and "file" in resp.json()["detail"]


def test_doctype_is_422_and_the_validator_is_not_called(monkeypatch):
    stub = StubClient(result=_accept())
    c = _client(stub, monkeypatch)
    xml = b'<?xml version="1.0"?><!DOCTYPE a [<!ENTITY n "42">]><a>RE-&n;-1</a>'
    resp = c.post("/validate", files={"file": ("d.xml", xml, "application/xml")})
    assert resp.status_code == 422 and resp.json() == {"detail": "DOCTYPE ist nicht erlaubt"} and stub.calls == []


def test_502_when_validator_fails(monkeypatch, caplog):
    c = _client(StubClient(error=ValidatorError("down")), monkeypatch)
    with caplog.at_level("WARNING", logger="erechnung.api"):
        resp = _post_ubl(c)
    assert resp.status_code == 502 and "down" in resp.json()["detail"]
    assert any("502" in r.getMessage() for r in caplog.records)


def test_daemon_4xx_is_422(monkeypatch, caplog):
    c = _client(StubClient(error=ValidatorRejectedInput("DOCTYPE is disallowed")), monkeypatch)
    with caplog.at_level("WARNING", logger="erechnung.api"):
        resp = _post_ubl(c)
    assert resp.status_code == 422
    assert resp.json() == {"detail": "Validator hat die Eingabe abgewiesen: DOCTYPE is disallowed"}
    assert any("422" in r.getMessage() for r in caplog.records)


def test_api_key_required_when_configured(monkeypatch):
    c = _client(StubClient(result=_accept()), monkeypatch, api_key="geheim")
    resp = _post_ubl(c)
    assert resp.status_code == 401 and resp.json() == {"detail": "API-Schlüssel fehlt oder ist ungültig"}
    assert _post_ubl(c, headers={"X-Api-Key": "falsch"}).status_code == 401
    assert _post_ubl(c, headers={"X-Api-Key": "geheim"}).status_code == 200
    assert c.get("/health").status_code == 200


def test_configured_key_wins_over_auth_disabled(monkeypatch):
    c = _client(StubClient(result=_accept()), monkeypatch, api_key="geheim", ERE_AUTH_DISABLED="1")
    assert _post_ubl(c).status_code == 401
    assert c.get("/health").json()["auth"] is True


def test_non_ascii_api_key_does_not_crash(monkeypatch):
    c = _client(StubClient(result=_accept()), monkeypatch, api_key="geheim")
    assert _post_ubl(c, headers={"X-Api-Key": "falsch-ä".encode()}).status_code == 401


def test_413_for_oversized_upload(monkeypatch):
    c = _client(StubClient(result=_accept()), monkeypatch)
    big = b"<a>" + b"x" * (10 * 1024 * 1024 + 1) + b"</a>"
    resp = c.post("/validate", files={"file": ("big.xml", big, "application/xml")})
    assert resp.status_code == 413 and resp.json() == {"detail": "Datei größer als 10 MB"}


@pytest.mark.parametrize("ebene", ["error", "warning"])
def test_messages_are_passed_through(monkeypatch, ebene):
    m = Meldung(ebene, "BR-01", "Text", "/x", 3, 4)
    result = Pruefergebnis(ebene != "error", "reject" if ebene == "error" else "accept", "X", [m] if ebene == "error" else [], [m] if ebene == "warning" else [], None)
    c = _client(StubClient(result=result), monkeypatch)
    body = _post_ubl(c).json()
    key = "fehler" if ebene == "error" else "warnungen"
    assert body[key] == [{"ebene": ebene, "code": "BR-01", "text": "Text", "ort": "/x", "zeile": 3, "spalte": 4}]


def test_no_scenario_matched_adds_warning(monkeypatch):
    c = _client(StubClient(result=Pruefergebnis(None, "reject", None, [], [], None)), monkeypatch)
    body = _post_ubl(c).json()
    assert body["gueltig"] is None and body["szenario"] is None
    assert [w["code"] for w in body["warnungen"]] == ["KEIN-SZENARIO"]


def test_upload_name_is_sanitised_before_the_daemon(monkeypatch):
    stub = StubClient(result=_accept())
    c = _client(stub, monkeypatch)
    c.post("/validate", files={"file": ("../../März Rechnung?.xml", UBL.read_bytes(), "application/xml")})
    assert stub.calls == ["M-rz-Rechnung-.xml"]


def test_unreadable_pdf_is_422(monkeypatch):
    c = _client(StubClient(result=_accept()), monkeypatch)
    resp = c.post("/validate", files={"file": ("x.pdf", b"%PDF-1.7\nthis is not a pdf at all", "application/pdf")})
    assert resp.status_code == 422 and resp.json()["detail"] == "PDF nicht lesbar"


def test_encrypted_pdf_is_422(monkeypatch):
    pdf = pikepdf.new()
    pdf.add_blank_page(page_size=(595, 842))
    out = io.BytesIO()
    pdf.save(out, encryption=pikepdf.Encryption(user="x", owner="y"))
    c = _client(StubClient(result=_accept()), monkeypatch)
    resp = c.post("/validate", files={"file": ("enc.pdf", out.getvalue(), "application/pdf")})
    assert resp.status_code == 422 and resp.json() == {"detail": "PDF nicht lesbar"}


def test_unsupported_attachment_encoding_is_422(monkeypatch):
    pdf = pikepdf.new()
    pdf.add_blank_page(page_size=(595, 842))
    pdf.attachments["k"] = pikepdf.AttachedFileSpec(pdf, b"x", filename="factur-x.xml")
    pdf.attachments["k"].obj.EF.F.write(b"3c612f3e>", filter=pikepdf.Name.ASCIIHexDecode)
    out = io.BytesIO()
    pdf.save(out, compress_streams=False, stream_decode_level=pikepdf.StreamDecodeLevel.none)
    stub = StubClient(result=_accept())
    c = _client(stub, monkeypatch)
    resp = c.post("/validate", files={"file": ("x.pdf", out.getvalue(), "application/pdf")})
    assert resp.status_code == 422 and resp.json() == {"detail": "Eingebettete Datei: nicht unterstützte Kodierung"}
    assert stub.calls == []


def test_openapi_documents_the_contract(monkeypatch):
    schema = _client(StubClient(), monkeypatch).get("/openapi.json").json()
    props = schema["components"]["schemas"]["ValidateResponse"]["properties"]
    assert {"syntax", "szenario", "validator_bericht_html", "bericht_html_vollstaendig", "datei_sha256"} <= set(props)
    assert "auth" in schema["components"]["schemas"]["HealthResponse"]["properties"]
