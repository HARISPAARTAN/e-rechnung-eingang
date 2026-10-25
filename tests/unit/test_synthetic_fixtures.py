from datetime import date
from decimal import Decimal
from pathlib import Path

from erechnung.extract import extract_fields
from erechnung.naming import archive_name
from erechnung.pdf import extract_embedded_xml
from erechnung.syntax import Syntax, detect_profile, detect_syntax, parse_xml, profile_level

ROOT = Path(__file__).resolve().parents[2]
SYN = ROOT / "fixtures" / "zugferd" / "synthetisch"
XPATH = ROOT / "src" / "erechnung" / "xpath"


def test_synthetic_invoice_round_trip():
    name, xml = extract_embedded_xml((SYN / "nordstern-elbnetz-RE-2026-0042.pdf").read_bytes())
    assert name.lower() == "factur-x.xml"
    root = parse_xml(xml)
    assert detect_syntax(root) is Syntax.CII and profile_level(detect_profile(root, Syntax.CII)) == "EN16931"
    f = extract_fields(root, Syntax.CII, XPATH)
    assert f.rechnungsnummer == "RE-2026-0042" and f.rechnungsdatum == date(2026, 10, 1)
    assert f.faelligkeitsdatum == date(2026, 10, 31) and f.waehrung == "EUR"
    assert f.verkaeufer_name == "Nordstern Projektmanagement GmbH" and f.verkaeufer_ust_idnr == "DE123456789"
    assert f.kaeufer_name == "Elbnetz GmbH" and f.iban == "DE02120300000000202051"
    assert f.netto == Decimal("1000.00") and f.steuer == Decimal("190.00") and f.brutto == Decimal("1190.00")
    assert archive_name(f, "pdf") == "2026-10-01_nordstern-projektmanagement-gmbh_re-2026-0042.pdf"


def test_leitweg_id_present_on_second_invoice():
    _, xml = extract_embedded_xml((SYN / "nordstern-helios-RE-2026-0043.pdf").read_bytes())
    f = extract_fields(parse_xml(xml), Syntax.CII, XPATH)
    assert f.leitweg_id == "04011000-12345-67" and f.kaeufer_name == "Helios Grid GmbH"


def test_tax_error_invoice_has_inconsistent_totals():
    _, xml = extract_embedded_xml((SYN / "nordstern-elbnetz-RE-2026-0044-steuerfehler.pdf").read_bytes())
    f = extract_fields(parse_xml(xml), Syntax.CII, XPATH)
    assert f.netto == Decimal("1500.00") and f.steuer == Decimal("295.00") and f.brutto == Decimal("1795.00")
