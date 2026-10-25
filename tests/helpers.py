"""Small PDF builders for tests (pikepdf only, no reportlab)."""

from __future__ import annotations

import io

import pikepdf


def make_plain_pdf() -> bytes:
    pdf = pikepdf.new()
    pdf.add_blank_page(page_size=(595, 842))
    out = io.BytesIO()
    pdf.save(out)
    return out.getvalue()


def make_pdf_with_attachment(name: str, payload: bytes) -> bytes:
    pdf = pikepdf.new()
    pdf.add_blank_page(page_size=(595, 842))
    pdf.attachments[name] = pikepdf.AttachedFileSpec(pdf, payload, mime_type="text/xml")
    out = io.BytesIO()
    pdf.save(out)
    return out.getvalue()
