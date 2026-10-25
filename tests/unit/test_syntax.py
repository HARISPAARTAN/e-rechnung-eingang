from pathlib import Path

import pytest

from erechnung.pdf import extract_embedded_xml
from erechnung.syntax import (
    MalformedXml,
    Syntax,
    UnsupportedSyntax,
    detect_profile,
    detect_syntax,
    parse_xml,
    profile_level,
)

FX = Path(__file__).resolve().parents[2] / "fixtures"


def test_ubl_fixture_is_ubl_with_xrechnung_profile():
    root = parse_xml((FX / "xrechnung" / "01.01a-INVOICE_ubl.xml").read_bytes())
    assert detect_syntax(root) is Syntax.UBL
    assert "xrechnung" in (detect_profile(root, Syntax.UBL) or "").lower()
    assert profile_level(detect_profile(root, Syntax.UBL)) == "XRECHNUNG"


def test_cii_fixture_is_cii():
    root = parse_xml((FX / "xrechnung" / "01.01a-INVOICE_uncefact.xml").read_bytes())
    assert detect_syntax(root) is Syntax.CII
    assert profile_level(detect_profile(root, Syntax.CII)) == "XRECHNUNG"


def test_corpus_pdf_is_cii_en16931():
    _, xml = extract_embedded_xml((FX / "zugferd" / "corpus" / "EN16931_Einfach.pdf").read_bytes())
    root = parse_xml(xml)
    assert detect_syntax(root) is Syntax.CII
    assert profile_level(detect_profile(root, Syntax.CII)) == "EN16931"


@pytest.mark.parametrize(
    "profile,level",
    [
        ("urn:factur-x.eu:1p0:minimum", "MINIMUM"),
        ("urn:factur-x.eu:1p0:basicwl", "BASIC WL"),
        ("urn:cen.eu:en16931:2017", "EN16931"),
        ("urn:cen.eu:en16931:2017#compliant#urn:factur-x.eu:1p0:basic", "BASIC"),
        ("urn:cen.eu:en16931:2017#compliant#urn:factur-x.eu:1p0:en16931", "EN16931"),
        ("urn:cen.eu:en16931:2017#conformant#urn:factur-x.eu:1p0:extended", "EXTENDED"),
        ("urn:cen.eu:en16931:2017#compliant#urn:xeinkauf.de:kosit:xrechnung_3.0", "XRECHNUNG"),
        (None, "UNKNOWN"),
    ],
)
def test_profile_levels(profile, level):
    assert profile_level(profile) == level


def test_malformed_and_unsupported():
    with pytest.raises(MalformedXml):
        parse_xml(b"<a><b></a>")
    with pytest.raises(UnsupportedSyntax):
        detect_syntax(parse_xml(b"<other xmlns='urn:x'/>"))


def test_parser_refuses_external_entities(tmp_path):
    secret = tmp_path / "secret.txt"
    secret.write_text("GEHEIM-4711", encoding="utf-8")
    evil = (
        '<?xml version="1.0"?><!DOCTYPE a [<!ENTITY x SYSTEM "' + secret.as_uri() + '">]><a>&x;</a>'
    ).encode("utf-8")
    with pytest.raises(MalformedXml, match="DOCTYPE ist nicht erlaubt") as info:
        parse_xml(evil)
    assert "GEHEIM-4711" not in str(info.value)


def test_internal_entity_is_refused_not_truncated():
    with pytest.raises(MalformedXml, match="DOCTYPE ist nicht erlaubt"):
        parse_xml(b'<?xml version="1.0"?><!DOCTYPE a [<!ENTITY n "42">]><a>RE-&n;-1</a>')


@pytest.mark.parametrize(
    "doc",
    [
        b"<!DOCTYPE a><a/>",
        b'\xef\xbb\xbf<?xml version="1.0"?>\n<!-- c --><!DOCTYPE a SYSTEM "a.dtd"><a/>',
        '<?xml version="1.0" encoding="UTF-16"?><!DOCTYPE a><a/>'.encode("utf-16"),
    ],
)
def test_any_doctype_is_refused(doc):
    with pytest.raises(MalformedXml, match="DOCTYPE"):
        parse_xml(doc)


def test_plain_document_still_parses():
    assert parse_xml(b'\xef\xbb\xbf<?xml version="1.0"?><a>RE-1</a>').text == "RE-1"
