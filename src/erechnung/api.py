"""FastAPI service: GET /health, POST /validate (multipart file). The KoSIT daemon runs beside it."""

from __future__ import annotations

import hashlib
import hmac
import logging
import re
from typing import Annotated

import pikepdf
from fastapi import Depends, FastAPI, File, Header, HTTPException, Request, Response, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from . import __version__
from .config import Settings, load_settings
from .extract import extract_fields
from .guard import KEY_DETAIL, UploadGuard
from .naming import archive_name
from .pdf import AttachmentTooLarge, NoEmbeddedInvoice, extract_embedded_xml
from .report import HealthResponse, ValidateResponse, build_report
from .sniff import detect_type
from .syntax import MalformedXml, UnsupportedSyntax, detect_profile, detect_syntax, parse_xml, profile_level
from .validator import Meldung, ValidatorClient, ValidatorError, ValidatorRejectedInput

log = logging.getLogger("erechnung.api")

_KEINE_E_RECHNUNG = "keine vollständige E-Rechnung im Sinne des § 14 UStG, keine Prüfung möglich"
PROFIL_WARNUNGEN = {
    "MINIMUM": Meldung("warning", "PROFIL-AUSSERHALB", f"Profil MINIMUM: {_KEINE_E_RECHNUNG}"),
    "BASIC WL": Meldung("warning", "PROFIL-AUSSERHALB", f"Profil BASIC WL: {_KEINE_E_RECHNUNG}"),
    "BASIC": Meldung(
        "warning", "PROFIL-AUSSERHALB", "Profil BASIC: EN-16931-konform, aber ohne KoSIT-Prüfszenario; Prüfung übersprungen"
    ),
}
UNCHECKED_LEVELS = set(PROFIL_WARNUNGEN)
SZENARIO_WARNUNG = Meldung(
    "warning", "KEIN-SZENARIO", "Kein Prüfszenario für dieses Profil (erwartet: XRechnung 3.0 oder EN 16931)"
)
CONFIG_ERROR = "ERE_API_KEY fehlt; für Entwicklung ERE_AUTH_DISABLED=1 setzen"
_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")
_MAX_NAME = 80


def safe_name(filename: str | None) -> str:
    """Upload name reduced to [A-Za-z0-9._-], at most 80 characters, ending in .xml; it goes into the daemon URL."""
    name = _UNSAFE.sub("-", filename or "").lstrip(".-")[:_MAX_NAME] or "rechnung.xml"
    if not name.lower().endswith(".xml"):
        name = name[: _MAX_NAME - 4] + ".xml"
    return name


def _reject(status: int, detail: str, cause: str) -> HTTPException:
    log.warning("/validate %s: %s", status, cause)
    return HTTPException(status_code=status, detail=detail)


def create_app(settings: Settings | None = None, client: ValidatorClient | None = None) -> FastAPI:
    settings = settings or load_settings()
    if not settings.api_key and not settings.auth_disabled:
        raise RuntimeError(CONFIG_ERROR)
    client = client or ValidatorClient(settings.validator_url, settings.timeout_s)
    app = FastAPI(title="E-Rechnung-Eingang Prüfdienst", version=__version__)
    app.add_middleware(UploadGuard, api_key=settings.api_key, max_upload_mb=settings.max_upload_mb)

    @app.exception_handler(RequestValidationError)
    async def request_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        errors = exc.errors()
        first = errors[0] if errors else {}
        loc = ".".join(str(p) for p in first.get("loc", ()) if p != "body")
        detail = f"{loc}: {first.get('msg', 'ungültige Anfrage')}" if loc else str(first.get("msg", "ungültige Anfrage"))
        log.warning("%s %s 422: %s", request.method, request.url.path, detail)
        return JSONResponse(status_code=422, content={"detail": detail})

    def require_key(x_api_key: Annotated[str | None, Header()] = None) -> None:
        if settings.api_key and not hmac.compare_digest(
            (x_api_key or "").encode("utf-8"), settings.api_key.encode("utf-8")
        ):
            raise HTTPException(status_code=401, detail=KEY_DETAIL)

    @app.get("/health", response_model=HealthResponse, responses={503: {"model": HealthResponse}})
    def health(response: Response) -> dict:
        try:
            validator = client.health()
        except ValidatorError as exc:
            validator = {"status": "DOWN", "detail": str(exc)}
        ok = validator.get("status") == "UP"
        if not ok:
            response.status_code = 503
        return {
            "status": "ok" if ok else "degraded",
            "auth": settings.auth_active,
            "validator": validator,
            "versions": {
                "service": __version__,
                "validator": settings.validator_version,
                "scenarios": f"xrechnung-{settings.xrechnung_version}-{settings.config_release}",
            },
        }

    @app.post("/validate", dependencies=[Depends(require_key)], response_model=ValidateResponse)
    def validate(file: Annotated[UploadFile, File()]) -> dict:
        limit = settings.max_upload_mb * 1024 * 1024
        data = file.file.read(limit + 1)
        if len(data) > limit:
            raise _reject(413, f"Datei größer als {settings.max_upload_mb} MB", f"upload over {limit} bytes")
        dateityp = detect_type(data)
        if dateityp == "unknown":
            raise _reject(422, "weder PDF noch XML", "neither PDF nor XML")
        try:
            xml = extract_embedded_xml(data)[1] if dateityp == "pdf" else data
            root = parse_xml(xml)
            syntax = detect_syntax(root)
        except pikepdf.PikepdfError as exc:
            raise _reject(422, "PDF nicht lesbar", f"{type(exc).__name__}: {exc}") from exc
        except (NoEmbeddedInvoice, AttachmentTooLarge, MalformedXml, UnsupportedSyntax) as exc:
            raise _reject(422, str(exc), f"{type(exc).__name__}: {exc}") from exc
        profil = detect_profile(root, syntax)
        zusatz: list[Meldung] = []
        pruefung = None
        level = profile_level(profil)
        if level in UNCHECKED_LEVELS:
            zusatz.append(PROFIL_WARNUNGEN[level])
        else:
            try:
                pruefung = client.validate(xml, safe_name(file.filename))
            except ValidatorRejectedInput as exc:
                raise _reject(422, f"Validator hat die Eingabe abgewiesen: {exc}", f"daemon 4xx: {exc}") from exc
            except ValidatorError as exc:
                raise _reject(502, str(exc), f"daemon error: {exc}") from exc
            if pruefung.szenario is None:
                zusatz.append(SZENARIO_WARNUNG)
        felder = extract_fields(root, syntax, settings.xpath_dir)
        return build_report(
            dateityp,
            syntax.value,
            profil,
            pruefung,
            felder,
            archive_name(felder, dateityp),
            zusatz,
            datei_sha256=hashlib.sha256(data).hexdigest(),
            html_max_chars=settings.html_max_chars,
        )

    return app


def __getattr__(name: str) -> FastAPI:
    """Module-level `app` for `uvicorn erechnung.api:app`, built on first access so importing the module never fails;
    a missing ERE_API_KEY surfaces as the RuntimeError above when the server loads the app."""
    if name == "app":
        instance = create_app()
        globals()["app"] = instance
        return instance
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
