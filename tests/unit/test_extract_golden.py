"""All 14 fields pinned to literal values read from the fixture files by hand, not derived from the code under test."""

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from erechnung.extract import Felder, extract_fields
from erechnung.syntax import detect_syntax, parse_xml

ROOT = Path(__file__).resolve().parents[2]
XR = ROOT / "fixtures" / "xrechnung"
SYN = ROOT / "fixtures" / "zugferd" / "synthetisch"
XPATH = ROOT / "src" / "erechnung" / "xpath"

CASE_01_01A = Felder(
    rechnungsnummer="123456XX",
    rechnungsdatum=date(2016, 4, 4),
    faelligkeitsdatum=None,
    rechnungstyp="380",
    waehrung="EUR",
    leitweg_id="04011000-12345-03",
    verkaeufer_name="[Seller name]",
    verkaeufer_ust_idnr="DE 123456789",
    kaeufer_name="[Buyer name]",
    iban="DE79000000001234567890",
    netto=Decimal("314.86"),
    steuer=Decimal("22.04"),
    brutto=Decimal("336.9"),
    faelliger_betrag=Decimal("336.9"),
)

CASE_01_02A = Felder(
    rechnungsnummer="123456",
    rechnungsdatum=date(2016, 6, 21),
    faelligkeitsdatum=None,
    rechnungstyp="380",
    waehrung="EUR",
    leitweg_id="04011000-12346-97",
    verkaeufer_name="[Seller name]",
    verkaeufer_ust_idnr="DE123456789",
    kaeufer_name="[Buyer name]",
    iban="DE79000000001234567890",
    netto=Decimal("11.78"),
    steuer=Decimal("0.82"),
    brutto=Decimal("12.6"),
    faelliger_betrag=Decimal("12.6"),
)

# RE-2026-0045: line total BT-106 1000.00, allowance BT-107 50.00, tax basis BT-109 950.00, tax BT-110 180.50,
# gross BT-112 1130.50, prepaid BT-113 300.00, amount due BT-115 830.50. All four differ, so swapping XPaths shows.
NACHLASS = Felder(
    rechnungsnummer="RE-2026-0045",
    rechnungsdatum=date(2026, 10, 15),
    faelligkeitsdatum=date(2026, 11, 14),
    rechnungstyp="380",
    waehrung="EUR",
    leitweg_id=None,
    verkaeufer_name="Nordstern Projektmanagement GmbH",
    verkaeufer_ust_idnr="DE123456789",
    kaeufer_name="Elbnetz GmbH",
    iban="DE02120300000000202051",
    netto=Decimal("950.00"),
    steuer=Decimal("180.50"),
    brutto=Decimal("1130.50"),
    faelliger_betrag=Decimal("830.50"),
)


def _fields(path: Path) -> Felder:
    root = parse_xml(path.read_bytes())
    return extract_fields(root, detect_syntax(root), XPATH)


@pytest.mark.parametrize(
    "path,expected",
    [
        (XR / "01.01a-INVOICE_ubl.xml", CASE_01_01A),
        (XR / "01.01a-INVOICE_uncefact.xml", CASE_01_01A),
        (XR / "01.02a-INVOICE_ubl.xml", CASE_01_02A),
        (XR / "01.02a-INVOICE_uncefact.xml", CASE_01_02A),
        (SYN / "nordstern-elbnetz-RE-2026-0045-nachlass.xml", NACHLASS),
        (SYN / "nordstern-elbnetz-RE-2026-0045-nachlass_ubl.xml", NACHLASS),
    ],
    ids=lambda v: v.name if isinstance(v, Path) else "",
)
def test_all_fields_match_the_golden_values(path, expected):
    assert _fields(path) == expected


@pytest.mark.parametrize("name", ["nordstern-elbnetz-RE-2026-0045-nachlass.xml", "nordstern-elbnetz-RE-2026-0045-nachlass_ubl.xml"])
def test_allowance_and_prepaid_keep_the_totals_apart(name):
    f = _fields(SYN / name)
    line_total, prepaid = Decimal("1000.00"), Decimal("300.00")
    assert f.netto != line_total  # BT-109, not BT-106
    assert f.netto + f.steuer == f.brutto  # BT-112
    assert f.brutto - prepaid == f.faelliger_betrag  # BT-115, not BT-112
