"""Embedded e-invoice XML out of a ZUGFeRD / Factur-X PDF/A-3."""

from __future__ import annotations

import io
import zlib

import pikepdf

# Priority order: Factur-X / ZUGFeRD 2.x, ZUGFeRD 1.0, XRechnung in a PDF container.
EMBEDDED_NAMES = ("factur-x.xml", "zugferd-invoice.xml", "xrechnung.xml")
# Fallback for library callers only; the API passes settings.max_upload_mb (the daemon is proven safe at 10 MiB).
_FALLBACK_MAX_BYTES = 10 * 1024 * 1024


class NoEmbeddedInvoice(ValueError):
    """The PDF carries no embedded invoice XML."""


class AttachmentTooLarge(ValueError):
    """The embedded XML decodes to more than the cap (the upload limit)."""


class UnsupportedEncoding(ValueError):
    """The embedded file uses a filter chain that cannot be decoded with a bound."""

    def __init__(self) -> None:
        super().__init__("Eingebettete Datei: nicht unterstützte Kodierung")


def _text(value) -> str:
    return str(value) if value is not None else ""


def _filename(spec_obj) -> str:
    """/UF (Unicode) before /F, as PDF 2.0 recommends."""
    return _text(spec_obj.get("/UF")) or _text(spec_obj.get("/F"))


def _as_list(value) -> list:
    if value is None:
        return []
    if isinstance(value, pikepdf.Array):
        return list(value)
    return [value]


def _plain_flate_params(parms) -> bool:
    """No DecodeParms, an empty dictionary (or null), or Predictor 1: Flate output is the file itself."""
    items = _as_list(parms)
    if not items:
        return True
    if len(items) > 1:
        return False
    params = items[0]
    if params is None:
        return True
    if not isinstance(params, pikepdf.Dictionary):
        return False
    predictor = params.get("/Predictor")
    if predictor is None:
        return True
    try:
        return int(predictor) == 1
    except (TypeError, ValueError):
        return False  # a malformed Predictor is an unsupported encoding (422), not a server error


def _bounded_bytes(stream: pikepdf.Stream, limit: int) -> bytes:
    """Decode an embedded file stream while never holding more than limit + 1 decoded bytes.

    Only two encodings are accepted: no filter (raw bytes) and plain /FlateDecode (inflated with max_length). Every
    other filter, filter chain or predictor is refused instead of decoded, because pikepdf's read_bytes() has no bound.
    """
    filters = [str(f) for f in _as_list(stream.get("/Filter"))]
    if not filters:
        data = stream.read_raw_bytes()
    elif filters == ["/FlateDecode"] and _plain_flate_params(stream.get("/DecodeParms")):
        inflater = zlib.decompressobj()
        try:
            data = inflater.decompress(stream.read_raw_bytes(), limit + 1)
        except zlib.error as exc:
            raise pikepdf.PdfError(f"eingebettete Datei nicht dekodierbar: {exc}") from exc
    else:
        raise UnsupportedEncoding()
    if len(data) > limit:
        raise AttachmentTooLarge(f"eingebettete Rechnung größer als {limit // (1024 * 1024)} MB")
    return data


def extract_embedded_xml(data: bytes, max_bytes: int = _FALLBACK_MAX_BYTES) -> tuple[str, bytes]:
    """Return (attachment file name, XML bytes).

    Attachments are matched by their file name (/UF or /F), not by the name-tree key. Known names win in the order of
    EMBEDDED_NAMES; after them any other .xml attachment, in the order of the catalog's /AF array, then name-tree order.
    """
    with pikepdf.open(io.BytesIO(data)) as pdf:
        af = pdf.Root.get("/AF")
        af_order = [_filename(f).lower() for f in af] if isinstance(af, pikepdf.Array) else []
        candidates: list[tuple[tuple[int, int], str, pikepdf.Object]] = []
        for position, (key, spec) in enumerate(pdf.attachments.items()):
            name = _filename(spec.obj) or key
            lower = name.lower()
            if lower in EMBEDDED_NAMES:
                rank = (0, EMBEDDED_NAMES.index(lower))
            elif lower.endswith(".xml"):
                rank = (1, af_order.index(lower) if lower in af_order else len(af_order) + position)
            else:
                continue
            candidates.append((rank, name, spec.obj))
        if candidates:
            _, name, spec_obj = min(candidates, key=lambda c: c[0])
            ef = spec_obj.get("/EF")
            stream = (ef.get("/UF") or ef.get("/F")) if ef is not None else None
            if not isinstance(stream, pikepdf.Stream):
                raise NoEmbeddedInvoice(f"Anhang {name} enthält keine Datei")
            return name, _bounded_bytes(stream, max_bytes)
    raise NoEmbeddedInvoice("keine eingebettete E-Rechnung gefunden (factur-x.xml / zugferd-invoice.xml)")


def pdfa_conformance(data: bytes) -> str | None:
    """'3B', '3U' ... from the XMP metadata, or None."""
    with pikepdf.open(io.BytesIO(data)) as pdf, pdf.open_metadata() as meta:
        part = meta.get("pdfaid:part")
        conf = meta.get("pdfaid:conformance")
        if part is None:
            return None
        return f"{part}{conf or ''}"
