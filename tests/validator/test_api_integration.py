from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from erechnung.api import create_app
from erechnung.config import load_settings
from erechnung.validator import ValidatorClient

pytestmark = pytest.mark.validator
ROOT = Path(__file__).resolve().parents[2]
FX = ROOT / "fixtures"


def test_end_to_end_pdf_and_xml(validator_url, monkeypatch):
    monkeypatch.delenv("ERE_API_KEY", raising=False)
    monkeypatch.setenv("ERE_AUTH_DISABLED", "1")
    c = TestClient(create_app(load_settings(ROOT), client=ValidatorClient(validator_url)))
    pdf = (FX / "zugferd" / "synthetisch" / "nordstern-elbnetz-RE-2026-0042.pdf").read_bytes()
    ok = c.post("/validate", files={"file": ("re.pdf", pdf, "application/pdf")}).json()
    assert ok["gueltig"] is True and ok["felder"]["rechnungsnummer"] == "RE-2026-0042"
    bad = (FX / "zugferd" / "synthetisch" / "nordstern-elbnetz-RE-2026-0044-steuerfehler.pdf").read_bytes()
    rej = c.post("/validate", files={"file": ("bad.pdf", bad, "application/pdf")}).json()
    assert rej["gueltig"] is False and rej["fehler"]
    assert c.get("/health").json()["status"] == "ok"
    doctype = b'<?xml version="1.0"?><!DOCTYPE a [<!ENTITY n "42">]><a>RE-&n;-1</a>'
    resp = c.post("/validate", files={"file": ("d.xml", doctype, "application/xml")})
    assert resp.status_code == 422 and resp.json() == {"detail": "DOCTYPE ist nicht erlaubt"}
