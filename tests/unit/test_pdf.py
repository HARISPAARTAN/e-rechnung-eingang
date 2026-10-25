from pathlib import Path

import pytest

from erechnung.pdf import NoEmbeddedInvoice, extract_embedded_xml, pdfa_conformance
from tests.helpers import make_pdf_with_attachment, make_plain_pdf

BROKEN = Path(__file__).resolve().parents[2] / "fixtures" / "broken"


def test_extracts_factur_x_xml_case_insensitively():
    name, xml = extract_embedded_xml(make_pdf_with_attachment("Factur-X.xml", b"<rsm:CrossIndustryInvoice/>"))
    assert name == "Factur-X.xml" and xml == b"<rsm:CrossIndustryInvoice/>"


def test_extracts_legacy_zugferd_name():
    name, _ = extract_embedded_xml(make_pdf_with_attachment("ZUGFeRD-invoice.xml", b"<x/>"))
    assert name == "ZUGFeRD-invoice.xml"


def test_falls_back_to_any_xml_attachment():
    name, _ = extract_embedded_xml(make_pdf_with_attachment("rechnung.xml", b"<x/>"))
    assert name == "rechnung.xml"


def test_prefers_known_name_over_other_xml():
    import io

    import pikepdf

    pdf = pikepdf.new()
    pdf.add_blank_page(page_size=(595, 842))
    pdf.attachments["aaa-notes.xml"] = pikepdf.AttachedFileSpec(pdf, b"<n/>")
    pdf.attachments["factur-x.xml"] = pikepdf.AttachedFileSpec(pdf, b"<f/>")
    out = io.BytesIO()
    pdf.save(out)
    name, xml = extract_embedded_xml(out.getvalue())
    assert name == "factur-x.xml" and xml == b"<f/>"


def test_plain_pdf_raises():
    with pytest.raises(NoEmbeddedInvoice, match="keine eingebettete E-Rechnung"):
        extract_embedded_xml(make_plain_pdf())


def test_broken_fixtures_exist_and_behave():
    assert (BROKEN / "kaputt.xml").read_bytes().startswith(b"<")
    assert (BROKEN / "text.txt").read_bytes() == b"Das ist keine Rechnung.\n"
    with pytest.raises(NoEmbeddedInvoice):
        extract_embedded_xml((BROKEN / "kein-anhang.pdf").read_bytes())


def test_pdfa_conformance_none_for_plain_pdf():
    assert pdfa_conformance(make_plain_pdf()) is None
