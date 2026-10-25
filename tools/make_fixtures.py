"""Generate synthetic ZUGFeRD (Factur-X, profile EN 16931) PDFs from fictional company data.

Usage: uv run python tools/make_fixtures.py [name ...]
Writes fixtures/zugferd/synthetisch/<name>.xml and <name>.pdf. The third invoice carries a wrong tax total on purpose.
The XML-only invoice RE-2026-0045 carries a document-level allowance (BT-107) and a prepaid amount (BT-113) and is written
as CII (<name>.xml) and UBL (<name>_ubl.xml), so that line total, tax basis, gross and amount due all differ.
Without names every fixture is rewritten; the PDFs then change byte-wise (timestamps), so pass names to limit the run.
"""

from __future__ import annotations

import io
import sys
import tempfile
from decimal import Decimal
from pathlib import Path

import facturx
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

OUT = Path(__file__).resolve().parents[1] / "fixtures" / "zugferd" / "synthetisch"
# Factur-X / ZUGFeRD 2.x profile EN 16931 (COMFORT) uses the bare EN identifier; the KoSIT scenario "EN16931 (CII)" matches exactly this.
GUIDELINE = "urn:cen.eu:en16931:2017"

SPECS = [
    {
        "name": "nordstern-elbnetz-RE-2026-0042",
        "nummer": "RE-2026-0042", "datum": "20261001", "faellig": "20261031", "typ": "380",
        "verkaeufer": "Nordstern Projektmanagement GmbH", "verkaeufer_ustid": "DE123456789",
        "verkaeufer_strasse": "Hafenstraße 12", "verkaeufer_plz": "20457", "verkaeufer_ort": "Hamburg",
        "kaeufer": "Elbnetz GmbH", "kaeufer_strasse": "Netzallee 3", "kaeufer_plz": "21079", "kaeufer_ort": "Hamburg",
        "iban": "DE02120300000000202051", "leitweg": None,
        "positionen": [("Projektsteuerung Oktober", Decimal("8"), Decimal("95.00")), ("Fahrtkosten", Decimal("1"), Decimal("240.00"))],
        "steuersatz": Decimal("19.00"), "steuer_fehler": Decimal("0"),
    },
    {
        "name": "nordstern-helios-RE-2026-0043",
        "nummer": "RE-2026-0043", "datum": "20261005", "faellig": "20261104", "typ": "380",
        "verkaeufer": "Nordstern Projektmanagement GmbH", "verkaeufer_ustid": "DE123456789",
        "verkaeufer_strasse": "Hafenstraße 12", "verkaeufer_plz": "20457", "verkaeufer_ort": "Hamburg",
        "kaeufer": "Helios Grid GmbH", "kaeufer_strasse": "Sonnenweg 8", "kaeufer_plz": "80331", "kaeufer_ort": "München",
        "iban": "DE02120300000000202051", "leitweg": "04011000-12345-67",
        "positionen": [("Qualitätssicherung Umspannwerk", Decimal("12"), Decimal("110.00"))],
        "steuersatz": Decimal("19.00"), "steuer_fehler": Decimal("0"),
    },
    {
        "name": "nordstern-elbnetz-RE-2026-0044-steuerfehler",
        "nummer": "RE-2026-0044", "datum": "20261010", "faellig": "20261109", "typ": "380",
        "verkaeufer": "Nordstern Projektmanagement GmbH", "verkaeufer_ustid": "DE123456789",
        "verkaeufer_strasse": "Hafenstraße 12", "verkaeufer_plz": "20457", "verkaeufer_ort": "Hamburg",
        "kaeufer": "Elbnetz GmbH", "kaeufer_strasse": "Netzallee 3", "kaeufer_plz": "21079", "kaeufer_ort": "Hamburg",
        "iban": "DE02120300000000202051", "leitweg": None,
        "positionen": [("Schulung Baustellendokumentation", Decimal("1"), Decimal("1500.00"))],
        "steuersatz": Decimal("19.00"), "steuer_fehler": Decimal("10.00"),
    },
]

XML_ONLY_SPECS = [
    {
        "name": "nordstern-elbnetz-RE-2026-0045-nachlass",
        "nummer": "RE-2026-0045", "datum": "20261015", "faellig": "20261114", "typ": "380",
        "verkaeufer": "Nordstern Projektmanagement GmbH", "verkaeufer_ustid": "DE123456789",
        "verkaeufer_strasse": "Hafenstraße 12", "verkaeufer_plz": "20457", "verkaeufer_ort": "Hamburg",
        "kaeufer": "Elbnetz GmbH", "kaeufer_strasse": "Netzallee 3", "kaeufer_plz": "21079", "kaeufer_ort": "Hamburg",
        "iban": "DE02120300000000202051", "leitweg": None,
        "positionen": [("Baustellenbegehung", Decimal("10"), Decimal("100.00"))],
        "steuersatz": Decimal("19.00"), "steuer_fehler": Decimal("0"),
        "nachlass": Decimal("50.00"), "nachlass_grund": "Treuerabatt", "vorauszahlung": Decimal("300.00"),
    },
]


def _q(value: Decimal) -> str:
    return f"{value.quantize(Decimal('0.01'))}"


def totals(spec: dict) -> dict[str, Decimal]:
    """BT-106 line total, BT-107 allowances, BT-109 tax basis, BT-110 tax, BT-112 gross, BT-113 prepaid, BT-115 due."""
    zeilen = sum((menge * preis for _, menge, preis in spec["positionen"]), Decimal("0"))
    nachlass = spec.get("nachlass", Decimal("0"))
    netto = zeilen - nachlass
    steuer = (netto * spec["steuersatz"] / 100).quantize(Decimal("0.01")) + spec["steuer_fehler"]
    brutto = netto + steuer
    vorauszahlung = spec.get("vorauszahlung", Decimal("0"))
    return {"zeilen": zeilen, "nachlass": nachlass, "netto": netto, "steuer": steuer, "brutto": brutto,
            "vorauszahlung": vorauszahlung, "faellig": brutto - vorauszahlung}


def build_cii_xml(spec: dict) -> bytes:
    t = totals(spec)
    netto, steuer, brutto = t["netto"], t["steuer"], t["brutto"]
    lines = []
    for i, (text, menge, preis) in enumerate(spec["positionen"], start=1):
        lines.append(f"""
    <ram:IncludedSupplyChainTradeLineItem>
      <ram:AssociatedDocumentLineDocument><ram:LineID>{i}</ram:LineID></ram:AssociatedDocumentLineDocument>
      <ram:SpecifiedTradeProduct><ram:Name>{text}</ram:Name></ram:SpecifiedTradeProduct>
      <ram:SpecifiedLineTradeAgreement><ram:NetPriceProductTradePrice><ram:ChargeAmount>{_q(preis)}</ram:ChargeAmount></ram:NetPriceProductTradePrice></ram:SpecifiedLineTradeAgreement>
      <ram:SpecifiedLineTradeDelivery><ram:BilledQuantity unitCode="C62">{menge}</ram:BilledQuantity></ram:SpecifiedLineTradeDelivery>
      <ram:SpecifiedLineTradeSettlement>
        <ram:ApplicableTradeTax><ram:TypeCode>VAT</ram:TypeCode><ram:CategoryCode>S</ram:CategoryCode><ram:RateApplicablePercent>{_q(spec["steuersatz"])}</ram:RateApplicablePercent></ram:ApplicableTradeTax>
        <ram:SpecifiedTradeSettlementLineMonetarySummation><ram:LineTotalAmount>{_q(menge * preis)}</ram:LineTotalAmount></ram:SpecifiedTradeSettlementLineMonetarySummation>
      </ram:SpecifiedLineTradeSettlement>
    </ram:IncludedSupplyChainTradeLineItem>""")
    leitweg = f"<ram:BuyerReference>{spec['leitweg']}</ram:BuyerReference>" if spec["leitweg"] else ""
    nachlass = ""
    if t["nachlass"]:
        nachlass = f"""
      <ram:SpecifiedTradeAllowanceCharge><ram:ChargeIndicator><udt:Indicator>false</udt:Indicator></ram:ChargeIndicator><ram:ActualAmount>{_q(t["nachlass"])}</ram:ActualAmount><ram:Reason>{spec["nachlass_grund"]}</ram:Reason><ram:CategoryTradeTax><ram:TypeCode>VAT</ram:TypeCode><ram:CategoryCode>S</ram:CategoryCode><ram:RateApplicablePercent>{_q(spec["steuersatz"])}</ram:RateApplicablePercent></ram:CategoryTradeTax></ram:SpecifiedTradeAllowanceCharge>"""
    summe_nachlass = f"\n        <ram:AllowanceTotalAmount>{_q(t['nachlass'])}</ram:AllowanceTotalAmount>" if t["nachlass"] else ""
    summe_voraus = f"\n        <ram:TotalPrepaidAmount>{_q(t['vorauszahlung'])}</ram:TotalPrepaidAmount>" if t["vorauszahlung"] else ""
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<rsm:CrossIndustryInvoice xmlns:rsm="urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100"
  xmlns:ram="urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100"
  xmlns:udt="urn:un:unece:uncefact:data:standard:UnqualifiedDataType:100">
  <rsm:ExchangedDocumentContext>
    <ram:GuidelineSpecifiedDocumentContextParameter><ram:ID>{GUIDELINE}</ram:ID></ram:GuidelineSpecifiedDocumentContextParameter>
  </rsm:ExchangedDocumentContext>
  <rsm:ExchangedDocument>
    <ram:ID>{spec["nummer"]}</ram:ID>
    <ram:TypeCode>{spec["typ"]}</ram:TypeCode>
    <ram:IssueDateTime><udt:DateTimeString format="102">{spec["datum"]}</udt:DateTimeString></ram:IssueDateTime>
  </rsm:ExchangedDocument>
  <rsm:SupplyChainTradeTransaction>{''.join(lines)}
    <ram:ApplicableHeaderTradeAgreement>
      {leitweg}
      <ram:SellerTradeParty>
        <ram:Name>{spec["verkaeufer"]}</ram:Name>
        <ram:PostalTradeAddress><ram:PostcodeCode>{spec["verkaeufer_plz"]}</ram:PostcodeCode><ram:LineOne>{spec["verkaeufer_strasse"]}</ram:LineOne><ram:CityName>{spec["verkaeufer_ort"]}</ram:CityName><ram:CountryID>DE</ram:CountryID></ram:PostalTradeAddress>
        <ram:SpecifiedTaxRegistration><ram:ID schemeID="VA">{spec["verkaeufer_ustid"]}</ram:ID></ram:SpecifiedTaxRegistration>
      </ram:SellerTradeParty>
      <ram:BuyerTradeParty>
        <ram:Name>{spec["kaeufer"]}</ram:Name>
        <ram:PostalTradeAddress><ram:PostcodeCode>{spec["kaeufer_plz"]}</ram:PostcodeCode><ram:LineOne>{spec["kaeufer_strasse"]}</ram:LineOne><ram:CityName>{spec["kaeufer_ort"]}</ram:CityName><ram:CountryID>DE</ram:CountryID></ram:PostalTradeAddress>
      </ram:BuyerTradeParty>
    </ram:ApplicableHeaderTradeAgreement>
    <ram:ApplicableHeaderTradeDelivery>
      <ram:ActualDeliverySupplyChainEvent><ram:OccurrenceDateTime><udt:DateTimeString format="102">{spec["datum"]}</udt:DateTimeString></ram:OccurrenceDateTime></ram:ActualDeliverySupplyChainEvent>
    </ram:ApplicableHeaderTradeDelivery>
    <ram:ApplicableHeaderTradeSettlement>
      <ram:InvoiceCurrencyCode>EUR</ram:InvoiceCurrencyCode>
      <ram:SpecifiedTradeSettlementPaymentMeans><ram:TypeCode>58</ram:TypeCode><ram:PayeePartyCreditorFinancialAccount><ram:IBANID>{spec["iban"]}</ram:IBANID></ram:PayeePartyCreditorFinancialAccount></ram:SpecifiedTradeSettlementPaymentMeans>
      <ram:ApplicableTradeTax><ram:CalculatedAmount>{_q(steuer)}</ram:CalculatedAmount><ram:TypeCode>VAT</ram:TypeCode><ram:BasisAmount>{_q(netto)}</ram:BasisAmount><ram:CategoryCode>S</ram:CategoryCode><ram:RateApplicablePercent>{_q(spec["steuersatz"])}</ram:RateApplicablePercent></ram:ApplicableTradeTax>{nachlass}
      <ram:SpecifiedTradePaymentTerms><ram:DueDateDateTime><udt:DateTimeString format="102">{spec["faellig"]}</udt:DateTimeString></ram:DueDateDateTime></ram:SpecifiedTradePaymentTerms>
      <ram:SpecifiedTradeSettlementHeaderMonetarySummation>
        <ram:LineTotalAmount>{_q(t["zeilen"])}</ram:LineTotalAmount>{summe_nachlass}
        <ram:TaxBasisTotalAmount>{_q(netto)}</ram:TaxBasisTotalAmount>
        <ram:TaxTotalAmount currencyID="EUR">{_q(steuer)}</ram:TaxTotalAmount>
        <ram:GrandTotalAmount>{_q(brutto)}</ram:GrandTotalAmount>{summe_voraus}
        <ram:DuePayableAmount>{_q(t["faellig"])}</ram:DuePayableAmount>
      </ram:SpecifiedTradeSettlementHeaderMonetarySummation>
    </ram:ApplicableHeaderTradeSettlement>
  </rsm:SupplyChainTradeTransaction>
</rsm:CrossIndustryInvoice>
"""
    return xml.encode("utf-8")


def _iso(d: str) -> str:
    return f"{d[:4]}-{d[4:6]}-{d[6:]}"


def build_ubl_xml(spec: dict) -> bytes:
    """The same invoice as UBL 2.1, CustomizationID EN 16931 (KoSIT scenario "EN16931 (UBL)")."""
    t = totals(spec)
    rate = _q(spec["steuersatz"])
    tax_category = f'<cbc:ID>S</cbc:ID><cbc:Percent>{rate}</cbc:Percent><cac:TaxScheme><cbc:ID>VAT</cbc:ID></cac:TaxScheme>'
    lines = []
    for i, (text, menge, preis) in enumerate(spec["positionen"], start=1):
        lines.append(f"""
  <cac:InvoiceLine>
    <cbc:ID>{i}</cbc:ID>
    <cbc:InvoicedQuantity unitCode="C62">{menge}</cbc:InvoicedQuantity>
    <cbc:LineExtensionAmount currencyID="EUR">{_q(menge * preis)}</cbc:LineExtensionAmount>
    <cac:Item><cbc:Name>{text}</cbc:Name><cac:ClassifiedTaxCategory>{tax_category}</cac:ClassifiedTaxCategory></cac:Item>
    <cac:Price><cbc:PriceAmount currencyID="EUR">{_q(preis)}</cbc:PriceAmount></cac:Price>
  </cac:InvoiceLine>""")
    leitweg = f"\n  <cbc:BuyerReference>{spec['leitweg']}</cbc:BuyerReference>" if spec["leitweg"] else ""
    nachlass = ""
    if t["nachlass"]:
        nachlass = f"""
  <cac:AllowanceCharge>
    <cbc:ChargeIndicator>false</cbc:ChargeIndicator>
    <cbc:AllowanceChargeReason>{spec["nachlass_grund"]}</cbc:AllowanceChargeReason>
    <cbc:Amount currencyID="EUR">{_q(t["nachlass"])}</cbc:Amount>
    <cac:TaxCategory>{tax_category}</cac:TaxCategory>
  </cac:AllowanceCharge>"""
    summe_nachlass = f'\n    <cbc:AllowanceTotalAmount currencyID="EUR">{_q(t["nachlass"])}</cbc:AllowanceTotalAmount>' if t["nachlass"] else ""
    summe_voraus = f'\n    <cbc:PrepaidAmount currencyID="EUR">{_q(t["vorauszahlung"])}</cbc:PrepaidAmount>' if t["vorauszahlung"] else ""
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"
  xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"
  xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2">
  <cbc:CustomizationID>{GUIDELINE}</cbc:CustomizationID>
  <cbc:ID>{spec["nummer"]}</cbc:ID>
  <cbc:IssueDate>{_iso(spec["datum"])}</cbc:IssueDate>
  <cbc:DueDate>{_iso(spec["faellig"])}</cbc:DueDate>
  <cbc:InvoiceTypeCode>{spec["typ"]}</cbc:InvoiceTypeCode>
  <cbc:DocumentCurrencyCode>EUR</cbc:DocumentCurrencyCode>{leitweg}
  <cac:AccountingSupplierParty>
    <cac:Party>
      <cac:PostalAddress><cbc:StreetName>{spec["verkaeufer_strasse"]}</cbc:StreetName><cbc:CityName>{spec["verkaeufer_ort"]}</cbc:CityName><cbc:PostalZone>{spec["verkaeufer_plz"]}</cbc:PostalZone><cac:Country><cbc:IdentificationCode>DE</cbc:IdentificationCode></cac:Country></cac:PostalAddress>
      <cac:PartyTaxScheme><cbc:CompanyID>{spec["verkaeufer_ustid"]}</cbc:CompanyID><cac:TaxScheme><cbc:ID>VAT</cbc:ID></cac:TaxScheme></cac:PartyTaxScheme>
      <cac:PartyLegalEntity><cbc:RegistrationName>{spec["verkaeufer"]}</cbc:RegistrationName></cac:PartyLegalEntity>
    </cac:Party>
  </cac:AccountingSupplierParty>
  <cac:AccountingCustomerParty>
    <cac:Party>
      <cac:PostalAddress><cbc:StreetName>{spec["kaeufer_strasse"]}</cbc:StreetName><cbc:CityName>{spec["kaeufer_ort"]}</cbc:CityName><cbc:PostalZone>{spec["kaeufer_plz"]}</cbc:PostalZone><cac:Country><cbc:IdentificationCode>DE</cbc:IdentificationCode></cac:Country></cac:PostalAddress>
      <cac:PartyLegalEntity><cbc:RegistrationName>{spec["kaeufer"]}</cbc:RegistrationName></cac:PartyLegalEntity>
    </cac:Party>
  </cac:AccountingCustomerParty>
  <cac:Delivery><cbc:ActualDeliveryDate>{_iso(spec["datum"])}</cbc:ActualDeliveryDate></cac:Delivery>
  <cac:PaymentMeans>
    <cbc:PaymentMeansCode>58</cbc:PaymentMeansCode>
    <cac:PayeeFinancialAccount><cbc:ID>{spec["iban"]}</cbc:ID></cac:PayeeFinancialAccount>
  </cac:PaymentMeans>{nachlass}
  <cac:TaxTotal>
    <cbc:TaxAmount currencyID="EUR">{_q(t["steuer"])}</cbc:TaxAmount>
    <cac:TaxSubtotal>
      <cbc:TaxableAmount currencyID="EUR">{_q(t["netto"])}</cbc:TaxableAmount>
      <cbc:TaxAmount currencyID="EUR">{_q(t["steuer"])}</cbc:TaxAmount>
      <cac:TaxCategory>{tax_category}</cac:TaxCategory>
    </cac:TaxSubtotal>
  </cac:TaxTotal>
  <cac:LegalMonetaryTotal>
    <cbc:LineExtensionAmount currencyID="EUR">{_q(t["zeilen"])}</cbc:LineExtensionAmount>
    <cbc:TaxExclusiveAmount currencyID="EUR">{_q(t["netto"])}</cbc:TaxExclusiveAmount>
    <cbc:TaxInclusiveAmount currencyID="EUR">{_q(t["brutto"])}</cbc:TaxInclusiveAmount>{summe_nachlass}{summe_voraus}
    <cbc:PayableAmount currencyID="EUR">{_q(t["faellig"])}</cbc:PayableAmount>
  </cac:LegalMonetaryTotal>{''.join(lines)}
</Invoice>
"""
    return xml.encode("utf-8")


def render_base_pdf(spec: dict) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    y = 800
    for line in (
        f"{spec['verkaeufer']} · {spec['verkaeufer_strasse']} · {spec['verkaeufer_plz']} {spec['verkaeufer_ort']}",
        f"Rechnung {spec['nummer']} vom {spec['datum'][6:]}.{spec['datum'][4:6]}.{spec['datum'][:4]}",
        f"An: {spec['kaeufer']}, {spec['kaeufer_strasse']}, {spec['kaeufer_plz']} {spec['kaeufer_ort']}",
        "",
        *[f"{text}: {menge} x {preis} EUR" for text, menge, preis in spec["positionen"]],
        "",
        f"Zahlbar bis {spec['faellig'][6:]}.{spec['faellig'][4:6]}.{spec['faellig'][:4]} auf IBAN {spec['iban']}",
        "Fiktive Rechnung für Testzwecke (E-Rechnung-Eingang).",
    ):
        c.drawString(60, y, line)
        y -= 18
    c.showPage()
    c.save()
    return buf.getvalue()


def write_fixture(spec: dict, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    xml_path = out_dir / f"{spec['name']}.xml"
    pdf_path = out_dir / f"{spec['name']}.pdf"
    xml_path.write_bytes(build_cii_xml(spec))
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp) / "base.pdf"
        base.write_bytes(render_base_pdf(spec))
        facturx.generate_from_file(str(base), str(xml_path), output_pdf_file=str(pdf_path))
    return pdf_path


def write_xml_only(spec: dict, out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    cii, ubl = out_dir / f"{spec['name']}.xml", out_dir / f"{spec['name']}_ubl.xml"
    cii.write_bytes(build_cii_xml(spec))
    ubl.write_bytes(build_ubl_xml(spec))
    return [cii, ubl]


if __name__ == "__main__":
    wanted = set(sys.argv[1:])
    for spec in SPECS:
        if not wanted or spec["name"] in wanted:
            print("wrote", write_fixture(spec, OUT))
    for spec in XML_ONLY_SPECS:
        if not wanted or spec["name"] in wanted:
            print("wrote", *write_xml_only(spec, OUT))
