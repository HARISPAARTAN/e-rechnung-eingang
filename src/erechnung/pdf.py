"""Embedded e-invoice XML out of a ZUGFeRD / Factur-X PDF/A-3."""

from __future__ import annotations

import io

import pikepdf

EMBEDDED_NAMES = ("factur-x.xml", "zugferd-invoice.xml", "xrechnung.xml", "order-x.xml")


class NoEmbeddedInvoice(ValueError):
    """The PDF carries no embedded invoice XML."""


def extract_embedded_xml(data: bytes) -> tuple[str, bytes]:
    """Return (attachment name, XML bytes); known names win over any other .xml attachment."""
    with pikepdf.open(io.BytesIO(data)) as pdf:
        names = list(pdf.attachments.keys())
        known = [n for n in names if n.lower() in EMBEDDED_NAMES]
        other = [n for n in names if n.lower().endswith(".xml") and n not in known]
        for name in known + other:
            return name, pdf.attachments[name].get_file().read_bytes()
    raise NoEmbeddedInvoice("keine eingebettete E-Rechnung gefunden (factur-x.xml / zugferd-invoice.xml)")


def pdfa_conformance(data: bytes) -> str | None:
    """'3B', '3U' ... from the XMP metadata, or None."""
    with pikepdf.open(io.BytesIO(data)) as pdf, pdf.open_metadata() as meta:
        part = meta.get("pdfaid:part")
        conf = meta.get("pdfaid:conformance")
        if part is None:
            return None
        return f"{part}{conf or ''}"
