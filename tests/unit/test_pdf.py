import io
from pathlib import Path

import pikepdf
import pytest

from erechnung.pdf import (
    EMBEDDED_NAMES,
    MAX_ATTACHMENT_BYTES,
    AttachmentTooLarge,
    NoEmbeddedInvoice,
    extract_embedded_xml,
    pdfa_conformance,
)
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


def _pdf(*attachments, af_order=None):
    """attachments: (name-tree key, file name, payload); af_order: file names for the catalog /AF array."""
    pdf = pikepdf.new()
    pdf.add_blank_page(page_size=(595, 842))
    for key, filename, payload in attachments:
        pdf.attachments[key] = pikepdf.AttachedFileSpec(pdf, payload, filename=filename)
    if af_order is not None:
        specs = {str(s.obj.get("/UF")): s.obj for s in pdf.attachments.values()}
        pdf.Root.AF = pikepdf.Array([specs[n] for n in af_order])
    out = io.BytesIO()
    pdf.save(out)
    return out.getvalue()


def test_matches_by_file_name_not_by_name_tree_key():
    name, xml = extract_embedded_xml(_pdf(("Rechnung 1", "factur-x.xml", b"<f/>")))
    assert name == "factur-x.xml" and xml == b"<f/>"


def test_known_names_follow_the_priority_order():
    data = _pdf(("a", "xrechnung.xml", b"<x/>"), ("b", "zugferd-invoice.xml", b"<z/>"), ("c", "factur-x.xml", b"<f/>"))
    assert extract_embedded_xml(data) == ("factur-x.xml", b"<f/>")
    data = _pdf(("a", "xrechnung.xml", b"<x/>"), ("b", "ZUGFeRD-invoice.xml", b"<z/>"))
    assert extract_embedded_xml(data) == ("ZUGFeRD-invoice.xml", b"<z/>")


def test_order_x_is_not_an_invoice_name():
    assert "order-x.xml" not in EMBEDDED_NAMES


def test_other_xml_attachments_follow_the_af_order():
    data = _pdf(("a", "aaa.xml", b"<a/>"), ("b", "bbb.xml", b"<b/>"), af_order=["bbb.xml", "aaa.xml"])
    assert extract_embedded_xml(data) == ("bbb.xml", b"<b/>")


def test_non_xml_attachments_are_ignored():
    with pytest.raises(NoEmbeddedInvoice):
        extract_embedded_xml(_pdf(("a", "bild.png", b"\x89PNG")))


def test_decoded_attachment_above_the_cap_is_refused():
    payload = b"<a>" + b"x" * (2 * 1024 * 1024) + b"</a>"  # compresses to a few KiB
    data = _pdf(("a", "factur-x.xml", payload))
    assert len(data) < 100_000
    with pytest.raises(AttachmentTooLarge):
        extract_embedded_xml(data, max_bytes=1024 * 1024)
    assert extract_embedded_xml(data, max_bytes=3 * 1024 * 1024)[1] == payload


def test_default_cap_is_50_mib():
    assert MAX_ATTACHMENT_BYTES == 50 * 1024 * 1024
