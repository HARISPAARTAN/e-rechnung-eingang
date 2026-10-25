from pathlib import Path

import httpx
import pytest

from erechnung.validator import (
    ValidatorClient,
    ValidatorError,
    ValidatorRejectedInput,
    parse_report,
    short_location,
)

REPORTS = Path(__file__).resolve().parents[2] / "fixtures" / "reports"


def test_accept_report():
    r = parse_report((REPORTS / "accept-ubl.xml").read_bytes())
    assert r.gueltig is True and r.empfehlung == "accept"
    assert r.szenario and "xrechnung" in r.szenario.lower()
    assert r.fehler == []


def test_reject_report_has_error_messages_with_codes():
    r = parse_report((REPORTS / "reject-cii.xml").read_bytes())
    assert r.gueltig is False and r.empfehlung == "reject"
    assert r.fehler, "expected at least one error message"
    first = r.fehler[0]
    assert first.ebene == "error" and first.code and first.text
    assert all(m.ebene == "warning" for m in r.warnungen)


def test_no_scenario_matched_is_unknown():
    xml = (
        b'<rep:report xmlns:rep="http://www.xoev.de/de/validator/varl/1" varlVersion="1.0.0">'
        b"<rep:noScenarioMatched/><rep:assessment><rep:reject><rep:explanation/></rep:reject></rep:assessment></rep:report>"
    )
    r = parse_report(xml)
    assert r.gueltig is None and r.szenario is None and r.empfehlung == "reject"


def test_html_body_raises_validator_error():
    with pytest.raises(ValidatorError, match="Validator lieferte kein XML"):
        parse_report(b"<html><body><h1>502 Bad Gateway</h1><hr><center>nginx</center></body></html>")


def test_unreachable_daemon_raises_without_the_url(caplog):
    with caplog.at_level("WARNING", logger="erechnung.validator"), pytest.raises(ValidatorError) as info:
        ValidatorClient("http://127.0.0.1:1", timeout_s=1.0).validate(b"<a/>")
    assert str(info.value) in {"Validator nicht erreichbar (ConnectError)", "Validator nicht erreichbar (ConnectTimeout)"}
    assert "127.0.0.1" not in str(info.value)
    assert any("transport error" in r.getMessage() for r in caplog.records)


def test_unreachable_health_hides_the_url():
    with pytest.raises(ValidatorError) as info:
        ValidatorClient("http://127.0.0.1:1").health()
    assert str(info.value).startswith("Validator nicht erreichbar (") and "127.0.0.1" not in str(info.value)


def test_validate_quotes_the_name_in_the_url(monkeypatch):
    seen = []

    def fake_post(url, **kwargs):
        seen.append(url)
        return httpx.Response(200, content=(REPORTS / "accept-ubl.xml").read_bytes())

    monkeypatch.setattr(httpx, "post", fake_post)
    ValidatorClient("http://d:8081").validate(b"<a/>", "a b/../c?.xml")
    assert seen == ["http://d:8081/a%20b%2F..%2Fc%3F.xml"]


def test_ort_uses_prefixes_instead_of_namespace_uris():
    r = parse_report((REPORTS / "reject-cii.xml").read_bytes())
    first = r.fehler[0]
    assert first.ort == (
        "/rsm:CrossIndustryInvoice[1]/rsm:SupplyChainTradeTransaction[1]"
        "/ram:ApplicableHeaderTradeSettlement[1]/ram:ApplicableTradeTax[1]"
    )
    assert all("Q{" not in (m.ort or "") for m in r.fehler + r.warnungen)


def test_short_location_keeps_unknown_namespaces():
    assert short_location("/Q{urn:x}a[1]/Q{urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2}ID[1]") == (
        "/Q{urn:x}a[1]/cbc:ID[1]"
    )
    assert short_location(None) is None


def _respond_with(monkeypatch, status, content):
    monkeypatch.setattr(httpx, "post", lambda url, **kw: httpx.Response(status, content=content))


def test_daemon_4xx_with_report_is_rejected_input_with_first_error(monkeypatch):
    _respond_with(monkeypatch, 422, (REPORTS / "reject-cii.xml").read_bytes())
    with pytest.raises(ValidatorRejectedInput) as info:
        ValidatorClient("http://d:8081").validate(b"<a/>")
    assert str(info.value).startswith("[BR-CO-17]-VAT category tax amount")
    assert isinstance(info.value, ValidatorError)


def test_daemon_4xx_without_report_uses_the_first_300_characters(monkeypatch):
    _respond_with(monkeypatch, 400, b"bad request " + b"y" * 500)
    with pytest.raises(ValidatorRejectedInput) as info:
        ValidatorClient("http://d:8081").validate(b"<a/>")
    assert str(info.value).startswith("bad request ") and len(str(info.value)) == 300


def test_daemon_5xx_stays_a_transient_validator_error(monkeypatch):
    _respond_with(monkeypatch, 500, b"<html>Internal Server Error</html>")
    with pytest.raises(ValidatorError) as info:
        ValidatorClient("http://d:8081").validate(b"<a/>")
    assert not isinstance(info.value, ValidatorRejectedInput)
    assert str(info.value) == "Validator antwortete mit HTTP 500"
