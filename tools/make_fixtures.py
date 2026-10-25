"""Generate synthetic ZUGFeRD (Factur-X, profile EN 16931) PDFs from fictional company data.

Usage: uv run python tools/make_fixtures.py
Writes fixtures/zugferd/synthetisch/<name>.xml and <name>.pdf. The third invoice carries a wrong tax total on purpose.
"""

from __future__ import annotations

import io
import tempfile
from decimal import Decimal
from pathlib import Path

import facturx
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

OUT = Path(__file__).resolve().parents[1] / "fixtures" / "zugferd" / "synthetisch"
GUIDELINE = "urn:cen.eu:en16931:2017#compliant#urn:factur-x.eu:1p0:en16931"

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


def _q(value: Decimal) -> str:
    return f"{value.quantize(Decimal('0.01'))}"


def build_cii_xml(spec: dict) -> bytes:
    netto = sum((menge * preis for _, menge, preis in spec["positionen"]), Decimal("0"))
    steuer = (netto * spec["steuersatz"] / 100).quantize(Decimal("0.01")) + spec["steuer_fehler"]
    brutto = netto + steuer
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
      <ram:ApplicableTradeTax><ram:CalculatedAmount>{_q(steuer)}</ram:CalculatedAmount><ram:TypeCode>VAT</ram:TypeCode><ram:BasisAmount>{_q(netto)}</ram:BasisAmount><ram:CategoryCode>S</ram:CategoryCode><ram:RateApplicablePercent>{_q(spec["steuersatz"])}</ram:RateApplicablePercent></ram:ApplicableTradeTax>
      <ram:SpecifiedTradePaymentTerms><ram:DueDateDateTime><udt:DateTimeString format="102">{spec["faellig"]}</udt:DateTimeString></ram:DueDateDateTime></ram:SpecifiedTradePaymentTerms>
      <ram:SpecifiedTradeSettlementHeaderMonetarySummation>
        <ram:LineTotalAmount>{_q(netto)}</ram:LineTotalAmount>
        <ram:TaxBasisTotalAmount>{_q(netto)}</ram:TaxBasisTotalAmount>
        <ram:TaxTotalAmount currencyID="EUR">{_q(steuer)}</ram:TaxTotalAmount>
        <ram:GrandTotalAmount>{_q(brutto)}</ram:GrandTotalAmount>
        <ram:DuePayableAmount>{_q(brutto)}</ram:DuePayableAmount>
      </ram:SpecifiedTradeSettlementHeaderMonetarySummation>
    </ram:ApplicableHeaderTradeSettlement>
  </rsm:SupplyChainTradeTransaction>
</rsm:CrossIndustryInvoice>
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


if __name__ == "__main__":
    for spec in SPECS:
        print("wrote", write_fixture(spec, OUT))
