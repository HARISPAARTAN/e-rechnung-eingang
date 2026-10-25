from pathlib import Path

import httpx
import pytest

from erechnung.validator import ValidatorClient, ValidatorError, parse_report

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


def test_unreachable_daemon_raises():
    with pytest.raises(ValidatorError):
        ValidatorClient("http://127.0.0.1:1", timeout_s=1.0).validate(b"<a/>")


def test_validate_quotes_the_name_in_the_url(monkeypatch):
    seen = []

    def fake_post(url, **kwargs):
        seen.append(url)
        return httpx.Response(200, content=(REPORTS / "accept-ubl.xml").read_bytes())

    monkeypatch.setattr(httpx, "post", fake_post)
    ValidatorClient("http://d:8081").validate(b"<a/>", "a b/../c?.xml")
    assert seen == ["http://d:8081/a%20b%2F..%2Fc%3F.xml"]
