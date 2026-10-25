from erechnung.sniff import detect_type
from tests.helpers import make_plain_pdf


def test_detects_pdf():
    assert detect_type(make_plain_pdf()) == "pdf"


def test_detects_xml_with_and_without_bom_and_whitespace():
    assert detect_type(b'<?xml version="1.0"?><a/>') == "xml"
    assert detect_type(b"\n  <a/>") == "xml"
    assert detect_type(b"\xef\xbb\xbf<a/>") == "xml"


def test_unknown_for_text_and_empty():
    assert detect_type(b"hello") == "unknown"
    assert detect_type(b"") == "unknown"
