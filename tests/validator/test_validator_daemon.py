from pathlib import Path

import pytest

from erechnung.pdf import extract_embedded_xml
from erechnung.validator import ValidatorClient, ValidatorError

pytestmark = pytest.mark.validator
FX = Path(__file__).resolve().parents[2] / "fixtures"


def test_health(validator_url):
    assert ValidatorClient(validator_url).health()["status"] == "UP"


@pytest.mark.parametrize("name", ["01.01a-INVOICE_ubl.xml", "01.01a-INVOICE_uncefact.xml", "01.02a-INVOICE_ubl.xml", "01.02a-INVOICE_uncefact.xml"])
def test_official_examples_are_accepted(validator_url, name):
    r = ValidatorClient(validator_url).validate((FX / "xrechnung" / name).read_bytes(), name)
    assert r.gueltig is True and r.fehler == [], [m.code for m in r.fehler]


def test_corpus_en16931_pdf_is_accepted(validator_url):
    _, xml = extract_embedded_xml((FX / "zugferd" / "corpus" / "EN16931_Einfach.pdf").read_bytes())
    r = ValidatorClient(validator_url).validate(xml, "EN16931_Einfach.xml")
    assert r.gueltig is True, [m.code for m in r.fehler]


def test_corpus_xrechnung_2_1_pdf_matches_no_scenario(validator_url):
    # The corpus file declares XRechnung 2.1; the pinned configuration only knows XRechnung 3.0.
    _, xml = extract_embedded_xml((FX / "zugferd" / "corpus" / "XRECHNUNG_Einfach.pdf").read_bytes())
    r = ValidatorClient(validator_url).validate(xml, "XRECHNUNG_Einfach.xml")
    assert r.gueltig is None and r.szenario is None and r.empfehlung == "reject"


def test_synthetic_en16931_invoice_is_accepted(validator_url):
    _, xml = extract_embedded_xml((FX / "zugferd" / "synthetisch" / "nordstern-elbnetz-RE-2026-0042.pdf").read_bytes())
    r = ValidatorClient(validator_url).validate(xml, "RE-2026-0042.xml")
    assert r.gueltig is True, [(m.code, m.text) for m in r.fehler]


def test_tax_error_invoice_is_rejected_with_a_br_rule(validator_url):
    _, xml = extract_embedded_xml((FX / "zugferd" / "synthetisch" / "nordstern-elbnetz-RE-2026-0044-steuerfehler.pdf").read_bytes())
    r = ValidatorClient(validator_url).validate(xml, "RE-2026-0044.xml")
    assert r.gueltig is False and any((m.code or "").startswith("BR-") for m in r.fehler)


def test_malformed_xml_raises_validator_error(validator_url):
    with pytest.raises(ValidatorError):
        ValidatorClient(validator_url).validate(b"<a><b></a>", "kaputt.xml")
