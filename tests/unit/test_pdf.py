import io
import tracemalloc
import zlib
from pathlib import Path

import pikepdf
import pytest

from erechnung.pdf import (
    AttachmentTooLarge,
    NoEmbeddedInvoice,
    UnsupportedEncoding,
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


def test_order_x_does_not_beat_an_invoice_name():
    # order-x.xml is an order, not an invoice: even first in /AF it loses against xrechnung.xml
    data = _pdf(("a", "order-x.xml", b"<o/>"), ("b", "xrechnung.xml", b"<x/>"), af_order=["order-x.xml", "xrechnung.xml"])
    assert extract_embedded_xml(data) == ("xrechnung.xml", b"<x/>")


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


def _pdf_with_stream(raw: bytes, filter_, decode_parms=None) -> bytes:
    """One factur-x.xml attachment whose embedded-file stream carries exactly raw, /Filter and /DecodeParms."""
    pdf = pikepdf.new()
    pdf.add_blank_page(page_size=(595, 842))
    pdf.attachments["k"] = pikepdf.AttachedFileSpec(pdf, b"x", filename="factur-x.xml")
    pdf.attachments["k"].obj.EF.F.write(raw, filter=filter_, decode_parms=decode_parms)
    out = io.BytesIO()
    pdf.save(out, compress_streams=False, stream_decode_level=pikepdf.StreamDecodeLevel.none)  # keep the stream as written
    return out.getvalue()


def test_flate_with_empty_decode_parms_is_bounded_by_the_cap():
    bomb = zlib.compress(b"<a>" + b"x" * (64 * 1024 * 1024) + b"</a>", 9)  # 64 MiB inflated, about 64 KiB raw
    data = _pdf_with_stream(bomb, pikepdf.Name.FlateDecode, pikepdf.Dictionary())
    assert len(data) < 200_000
    tracemalloc.start()
    try:
        with pytest.raises(AttachmentTooLarge):
            extract_embedded_xml(data, max_bytes=256 * 1024)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert peak < 8 * 1024 * 1024, f"held {peak} bytes while refusing a 64 MiB inflate with a 256 KiB cap"


@pytest.mark.parametrize("parms", [None, pikepdf.Dictionary(), pikepdf.Dictionary(Predictor=1), pikepdf.Array([pikepdf.Dictionary()])])
def test_plain_flate_variants_are_decoded(parms):
    payload = b"<rsm:CrossIndustryInvoice/>"
    data = _pdf_with_stream(zlib.compress(payload), pikepdf.Name.FlateDecode, parms)
    assert extract_embedded_xml(data, max_bytes=1024) == ("factur-x.xml", payload)


def test_unfiltered_stream_is_length_checked():
    data = _pdf_with_stream(b"<a>" + b"x" * 2000 + b"</a>", None)
    with pytest.raises(AttachmentTooLarge):
        extract_embedded_xml(data, max_bytes=1000)
    assert extract_embedded_xml(data, max_bytes=4096)[1].startswith(b"<a>x")


@pytest.mark.parametrize(
    "filter_,parms,raw",
    [
        (pikepdf.Name.ASCIIHexDecode, None, b"3c612f3e>"),
        (pikepdf.Array([pikepdf.Name.ASCIIHexDecode, pikepdf.Name.FlateDecode]), None, zlib.compress(b"<a/>").hex().encode() + b">"),
        (pikepdf.Name.FlateDecode, pikepdf.Dictionary(Predictor=12, Columns=4), zlib.compress(b"<a/>")),
    ],
    ids=["ascii-hex", "filter-chain", "png-predictor"],
)
def test_other_encodings_are_refused_not_decoded(filter_, parms, raw):
    with pytest.raises(UnsupportedEncoding, match="Eingebettete Datei: nicht unterstützte Kodierung"):
        extract_embedded_xml(_pdf_with_stream(raw, filter_, parms))


def test_synthetic_fixture_pdf_still_parses_under_the_upload_cap():
    data = (Path(__file__).resolve().parents[2] / "fixtures" / "zugferd" / "synthetisch" / "nordstern-elbnetz-RE-2026-0042.pdf").read_bytes()
    name, xml = extract_embedded_xml(data, max_bytes=10 * 1024 * 1024)
    assert name.lower() == "factur-x.xml" and b"RE-2026-0042" in xml
