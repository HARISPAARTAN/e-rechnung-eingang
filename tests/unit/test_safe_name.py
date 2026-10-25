import pytest

from erechnung.api import safe_name


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("01.01a-INVOICE_ubl.xml", "01.01a-INVOICE_ubl.xml"),
        ("../../etc/passwd.xml", "etc-passwd.xml"),
        ("..\\..\\boot.ini", "boot.ini.xml"),
        ("Rechnung Oktober 2026.xml", "Rechnung-Oktober-2026.xml"),
        ("Rechnung März Müller.xml", "Rechnung-M-rz-M-ller.xml"),
        ("re.pdf", "re.pdf.xml"),
        ("RE.XML", "RE.XML"),
        ("", "rechnung.xml"),
        (None, "rechnung.xml"),
        ("...", "rechnung.xml"),
        ("äöü", "rechnung.xml"),
    ],
)
def test_safe_name(raw, expected):
    assert safe_name(raw) == expected


def test_safe_name_is_bounded_and_ends_in_xml():
    long_xml = safe_name("a" * 200 + ".xml")
    assert len(long_xml) == 80 and long_xml.endswith(".xml")
    long_pdf = safe_name("b" * 200 + ".pdf")
    assert len(long_pdf) == 80 and long_pdf.endswith(".xml")
