"""HTTP client for the KoSIT validator daemon and a parser for its XRechnung report (namespace varl/1)."""

from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import quote

import httpx
from lxml import etree

REP = "http://www.xoev.de/de/validator/varl/1"
SCN = "http://www.xoev.de/de/validator/framework/1/scenarios"
XHTML = "http://www.w3.org/1999/xhtml"
_NS = {"rep": REP, "s": SCN, "html": XHTML}
_PARSER = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True)


class ValidatorError(RuntimeError):
    """The daemon is unreachable, misconfigured or failed to process the document."""


@dataclass(frozen=True)
class Meldung:
    ebene: str
    code: str | None
    text: str
    ort: str | None = None
    zeile: int | None = None
    spalte: int | None = None


@dataclass
class Pruefergebnis:
    gueltig: bool | None
    empfehlung: str
    szenario: str | None
    fehler: list[Meldung] = field(default_factory=list)
    warnungen: list[Meldung] = field(default_factory=list)
    bericht_html: str | None = None
    bericht_xml: bytes = b""


def _int(value: str | None) -> int | None:
    try:
        return int(value) if value not in (None, "") else None
    except ValueError:
        return None


def parse_report(xml: bytes) -> Pruefergebnis:
    try:
        root = etree.fromstring(xml, parser=_PARSER)
    except etree.XMLSyntaxError as exc:
        raise ValidatorError("Validator lieferte kein XML") from exc
    if etree.QName(root).namespace != REP or etree.QName(root).localname != "report":
        raise ValidatorError("unerwartetes Berichtsformat (kein rep:report)")
    accept = root.find("rep:assessment/rep:accept", _NS)
    reject = root.find("rep:assessment/rep:reject", _NS)
    empfehlung = "accept" if accept is not None else ("reject" if reject is not None else "unbekannt")
    matched = root.find("rep:scenarioMatched", _NS)
    szenario = None
    if matched is not None:
        name = matched.find("s:scenario/s:name", _NS)
        szenario = (name.text or "").strip() if name is not None else "szenario"
    fehler: list[Meldung] = []
    warnungen: list[Meldung] = []
    for m in root.iter(f"{{{REP}}}message"):
        meldung = Meldung(
            ebene=(m.get("level") or "information").lower(),
            code=m.get("code"),
            text=" ".join((m.text or "").split()),
            ort=m.get("xpathLocation"),
            zeile=_int(m.get("lineNumber")),
            spalte=_int(m.get("columnNumber")),
        )
        if meldung.ebene == "error":
            fehler.append(meldung)
        elif meldung.ebene == "warning":
            warnungen.append(meldung)
    if matched is None:
        gueltig: bool | None = None
    else:
        gueltig = empfehlung == "accept" and not fehler
    html = root.find(".//html:html", _NS)
    bericht_html = etree.tostring(html, encoding="unicode") if html is not None else None
    return Pruefergebnis(gueltig, empfehlung, szenario, fehler, warnungen, bericht_html, xml)


class ValidatorClient:
    def __init__(self, base_url: str, timeout_s: float = 60.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s

    def health(self) -> dict:
        try:
            resp = httpx.get(f"{self.base_url}/server/health", timeout=5.0)
        except httpx.HTTPError as exc:
            raise ValidatorError(f"Validator nicht erreichbar: {exc}") from exc
        status = "UP" if resp.status_code == 200 and b"UP" in resp.content else "DOWN"
        return {"status": status, "http": resp.status_code}

    def validate(self, xml: bytes, name: str = "rechnung.xml") -> Pruefergebnis:
        try:
            resp = httpx.post(
                f"{self.base_url}/{quote(name, safe='')}", content=xml, headers={"Content-Type": "application/xml"}, timeout=self.timeout_s
            )
        except httpx.HTTPError as exc:
            raise ValidatorError(f"Validator nicht erreichbar: {exc}") from exc
        if resp.status_code in (200, 406):
            return parse_report(resp.content)
        raise ValidatorError(f"Validator antwortete mit HTTP {resp.status_code}: {resp.text[:300]}")
