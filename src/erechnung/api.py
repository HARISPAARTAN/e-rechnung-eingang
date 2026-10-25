"""FastAPI service: GET /health, POST /validate (multipart file). The KoSIT daemon runs beside it."""

from __future__ import annotations

import hmac
import re
from typing import Annotated

import pikepdf
from fastapi import Depends, FastAPI, File, Header, HTTPException, UploadFile

from . import __version__
from .config import Settings, load_settings
from .extract import extract_fields
from .naming import archive_name
from .pdf import NoEmbeddedInvoice, extract_embedded_xml
from .report import build_report
from .sniff import detect_type
from .syntax import MalformedXml, UnsupportedSyntax, detect_profile, detect_syntax, parse_xml, profile_level
from .validator import Meldung, ValidatorClient, ValidatorError

UNCHECKED_LEVELS = {"MINIMUM", "BASIC WL", "BASIC"}
PROFIL_WARNUNG = Meldung("warning", "PROFIL-AUSSERHALB", "Profil außerhalb der XRechnung-Prüfregeln")
SZENARIO_WARNUNG = Meldung(
    "warning", "KEIN-SZENARIO", "Kein Prüfszenario für dieses Profil (erwartet: XRechnung 3.0 oder EN 16931)"
)
_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")
_MAX_NAME = 80


def safe_name(filename: str | None) -> str:
    """Upload name reduced to [A-Za-z0-9._-], at most 80 characters, ending in .xml; it goes into the daemon URL."""
    name = _UNSAFE.sub("-", filename or "").lstrip(".-")[:_MAX_NAME] or "rechnung.xml"
    if not name.lower().endswith(".xml"):
        name = name[: _MAX_NAME - 4] + ".xml"
    return name


def create_app(settings: Settings | None = None, client: ValidatorClient | None = None) -> FastAPI:
    settings = settings or load_settings()
    client = client or ValidatorClient(settings.validator_url, settings.timeout_s)
    app = FastAPI(title="E-Rechnung-Eingang Prüfdienst", version=__version__)

    def require_key(x_api_key: Annotated[str | None, Header()] = None) -> None:
        if settings.api_key and not hmac.compare_digest(
            (x_api_key or "").encode("utf-8"), settings.api_key.encode("utf-8")
        ):
            raise HTTPException(status_code=401, detail="ungültiger oder fehlender X-Api-Key")

    @app.get("/health")
    def health() -> dict:
        try:
            validator = client.health()
        except ValidatorError as exc:
            validator = {"status": "DOWN", "detail": str(exc)}
        return {
            "status": "ok" if validator.get("status") == "UP" else "degraded",
            "validator": validator,
            "versions": {
                "service": __version__,
                "validator": settings.validator_version,
                "scenarios": f"xrechnung-{settings.xrechnung_version}-{settings.config_release}",
            },
        }

    @app.post("/validate", dependencies=[Depends(require_key)])
    def validate(file: Annotated[UploadFile, File()]) -> dict:
        limit = settings.max_upload_mb * 1024 * 1024
        data = file.file.read(limit + 1)
        if len(data) > limit:
            raise HTTPException(status_code=413, detail=f"Datei größer als {settings.max_upload_mb} MB")
        dateityp = detect_type(data)
        if dateityp == "unknown":
            raise HTTPException(status_code=422, detail="weder PDF noch XML")
        try:
            xml = extract_embedded_xml(data)[1] if dateityp == "pdf" else data
            root = parse_xml(xml)
            syntax = detect_syntax(root)
        except pikepdf.PdfError as exc:
            raise HTTPException(status_code=422, detail="PDF nicht lesbar") from exc
        except (NoEmbeddedInvoice, MalformedXml, UnsupportedSyntax) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        profil = detect_profile(root, syntax)
        zusatz: list[Meldung] = []
        pruefung = None
        if profile_level(profil) in UNCHECKED_LEVELS:
            zusatz.append(PROFIL_WARNUNG)
        else:
            try:
                pruefung = client.validate(xml, safe_name(file.filename))
            except ValidatorError as exc:
                raise HTTPException(status_code=502, detail=str(exc)) from exc
            if pruefung.szenario is None:
                zusatz.append(SZENARIO_WARNUNG)
        felder = extract_fields(root, syntax, settings.xpath_dir)
        return build_report(dateityp, syntax.value, profil, pruefung, felder, archive_name(felder, dateityp), zusatz)

    return app


app = create_app()
