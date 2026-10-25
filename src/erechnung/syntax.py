"""Parse safely, tell UBL from CII, read the profile (CustomizationID / guideline parameter)."""

from __future__ import annotations

from enum import StrEnum

from lxml import etree

NS = {
    "ubl": "urn:oasis:names:specification:ubl:schema:xsd:Invoice-2",
    "ubl_cn": "urn:oasis:names:specification:ubl:schema:xsd:CreditNote-2",
    "cbc": "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2",
    "cac": "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2",
    "rsm": "urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100",
    "ram": "urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100",
    "udt": "urn:un:unece:uncefact:data:standard:UnqualifiedDataType:100",
}
_PARSER = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=False, remove_blank_text=False)


class Syntax(StrEnum):
    UBL = "UBL"
    CII = "CII"


class MalformedXml(ValueError):
    pass


class UnsupportedSyntax(ValueError):
    pass


def parse_xml(data: bytes) -> etree._Element:
    try:
        return etree.fromstring(data, parser=_PARSER)
    except etree.XMLSyntaxError as exc:
        raise MalformedXml(f"XML nicht wohlgeformt: {exc}") from exc


def detect_syntax(root: etree._Element) -> Syntax:
    ns = etree.QName(root).namespace
    if ns in (NS["ubl"], NS["ubl_cn"]):
        return Syntax.UBL
    if ns == NS["rsm"]:
        return Syntax.CII
    raise UnsupportedSyntax(f"unbekanntes Wurzelelement {root.tag}")


def detect_profile(root: etree._Element, syntax: Syntax) -> str | None:
    if syntax is Syntax.UBL:
        hits = root.xpath("cbc:CustomizationID/text()", namespaces=NS)
    else:
        hits = root.xpath(
            "rsm:ExchangedDocumentContext/ram:GuidelineSpecifiedDocumentContextParameter/ram:ID/text()",
            namespaces=NS,
        )
    return str(hits[0]).strip() if hits else None


def profile_level(profile: str | None) -> str:
    if not profile:
        return "UNKNOWN"
    tail = profile.lower().split("#")[-1].split(":")[-1]
    mapping = {"minimum": "MINIMUM", "basicwl": "BASIC WL", "basic": "BASIC", "en16931": "EN16931", "extended": "EXTENDED"}
    if "xrechnung" in profile.lower():
        return "XRECHNUNG"
    for needle, level in mapping.items():
        if tail.startswith(needle):
            return level
    if "en16931" in profile.lower():
        return "EN16931"
    return "UNKNOWN"
