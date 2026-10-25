"""Tell PDF from XML by content, not by file name."""

from __future__ import annotations

BOM = b"\xef\xbb\xbf"


def detect_type(data: bytes) -> str:
    if data.startswith(b"%PDF-"):
        return "pdf"
    body = data[3:] if data.startswith(BOM) else data
    if body.lstrip().startswith(b"<"):
        return "xml"
    return "unknown"
