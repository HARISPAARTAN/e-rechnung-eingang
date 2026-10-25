from datetime import date
from decimal import Decimal
from pathlib import Path

from erechnung.extract import Felder, extract_fields
from erechnung.pdf import extract_embedded_xml
from erechnung.syntax import Syntax, detect_syntax, parse_xml

ROOT = Path(__file__).resolve().parents[2]
FX = ROOT / "fixtures"
XPATH = ROOT / "src" / "erechnung" / "xpath"


def _fields(data: bytes) -> Felder:
    root = parse_xml(data)
    return extract_fields(root, detect_syntax(root), XPATH)


def test_ubl_and_cii_versions_of_the_same_case_agree():
    ubl = _fields((FX / "xrechnung" / "01.01a-INVOICE_ubl.xml").read_bytes())
    cii = _fields((FX / "xrechnung" / "01.01a-INVOICE_uncefact.xml").read_bytes())
    for name in ("rechnungsnummer", "rechnungsdatum", "waehrung", "verkaeufer_name", "kaeufer_name", "brutto", "faelliger_betrag"):
        assert getattr(ubl, name) == getattr(cii, name), name
    assert isinstance(ubl.rechnungsdatum, date) and isinstance(ubl.brutto, Decimal)
    assert ubl.leitweg_id and ubl.rechnungstyp in {"380", "384", "381", "326", "389", "875", "876", "877"}


def test_corpus_pdf_fields():
    _, xml = extract_embedded_xml((FX / "zugferd" / "corpus" / "EN16931_Einfach.pdf").read_bytes())
    f = _fields(xml)
    assert f.rechnungsnummer and f.rechnungsdatum and f.waehrung == "EUR"
    assert f.brutto is not None and f.brutto > 0 and f.netto is not None and f.steuer is not None
    assert f.brutto == f.netto + f.steuer


def test_missing_fields_are_none_not_errors():
    root = parse_xml(
        b'<Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2" '
        b'xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2"><cbc:ID>X</cbc:ID></Invoice>'
    )
    f = extract_fields(root, Syntax.UBL, XPATH)
    assert f.rechnungsnummer == "X" and f.rechnungsdatum is None and f.brutto is None and f.iban is None


_CBC = 'xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2" '
_CAC = 'xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"'
_INVOICE_NS = 'xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2" '
_CREDIT_NS = 'xmlns="urn:oasis:names:specification:ubl:schema:xsd:CreditNote-2" '


def test_ubl_name_fallback_to_party_name():
    f = _fields(
        (
            "<Invoice " + _INVOICE_NS + _CBC + _CAC + ">"
            "<cac:AccountingSupplierParty><cac:Party><cac:PartyName><cbc:Name>Nur Handelsname GmbH</cbc:Name></cac:PartyName></cac:Party></cac:AccountingSupplierParty>"
            "<cac:AccountingCustomerParty><cac:Party>"
            "<cac:PartyName><cbc:Name>Kaeufer Handelsname</cbc:Name></cac:PartyName>"
            "<cac:PartyLegalEntity><cbc:RegistrationName>   </cbc:RegistrationName></cac:PartyLegalEntity>"
            "</cac:Party></cac:AccountingCustomerParty>"
            "</Invoice>"
        ).encode("utf-8")
    )
    assert f.verkaeufer_name == "Nur Handelsname GmbH"
    assert f.kaeufer_name == "Kaeufer Handelsname"


def test_ubl_credit_note_due_date_under_payment_means():
    f = _fields(
        (
            "<CreditNote " + _CREDIT_NS + _CBC + _CAC + ">"
            "<cac:PaymentMeans><cbc:PaymentDueDate>2026-03-15</cbc:PaymentDueDate></cac:PaymentMeans>"
            "</CreditNote>"
        ).encode("utf-8")
    )
    assert f.faelligkeitsdatum == date(2026, 3, 15)


def test_non_finite_amount_is_none():
    f = _fields(
        (
            "<Invoice " + _INVOICE_NS + _CBC + _CAC + ">"
            "<cac:LegalMonetaryTotal><cbc:PayableAmount>NaN</cbc:PayableAmount>"
            "<cbc:TaxInclusiveAmount>Infinity</cbc:TaxInclusiveAmount></cac:LegalMonetaryTotal>"
            "</Invoice>"
        ).encode("utf-8")
    )
    assert f.faelliger_betrag is None and f.brutto is None
