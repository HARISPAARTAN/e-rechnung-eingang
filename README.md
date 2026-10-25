# E-Rechnung-Eingang

[![CI](https://github.com/HARISPAARTAN/e-rechnung-eingang/actions/workflows/ci.yml/badge.svg)](https://github.com/HARISPAARTAN/e-rechnung-eingang/actions/workflows/ci.yml)

Prüfdienst und Eingangs-Workflow für elektronische Rechnungen in Deutschland. English version: [README.en.md](README.en.md).

**Stand:** Meilenstein 1 ist fertig: der Prüfdienst (Docker) validiert XRechnung-XML und ZUGFeRD-PDFs mit dem
KoSIT-Validator, extrahiert die Rechnungsfelder nach EN 16931 und schlägt einen Archivnamen vor. Meilensteine 2 bis 4
(Azure-Betrieb, Dataverse mit Power Automate, Power-BI-Seite) folgen.

## Warum

Seit 2025 muss jedes Unternehmen E-Rechnungen empfangen, ab 2027/2028 auch ausstellen (siehe [docs/mandate.md](docs/mandate.md)).
Dieses Projekt zeigt die Eingangsseite: prüfen, auslesen, freigeben, ablegen, auswerten.

## Prüfdienst

`POST /validate` nimmt eine Datei entgegen (XRechnung-XML oder ZUGFeRD-PDF/A-3) und antwortet mit JSON:
Dateityp, Syntax (UBL oder CII), Profil, Prüfergebnis mit Fehlern und Warnungen des KoSIT-Validators,
die Felder Rechnungsnummer, Datum, Fälligkeit, Währung, Leitweg-ID, Verkäufer, USt-IdNr, Käufer, IBAN, Netto, Steuer,
Brutto und fälliger Betrag, sowie der Archivname `JJJJ-MM-TT_verkaeufer_rechnungsnummer.pdf|xml`.
`GET /health` meldet den Zustand des Validators und die Versionen. Profile unterhalb EN 16931 (MINIMUM, BASIC WL, BASIC)
liegen außerhalb der XRechnung-Prüfregeln und werden mit `gueltig: null` und der Warnung `PROFIL-AUSSERHALB` beantwortet.

Uploads sind auf 10 MB begrenzt (`max_upload_mb` in `config.toml`, darüber HTTP 413). Die Grenze schützt den Puffer im
Prozess; im Betrieb setzt der Ingress oder Reverse Proxy die harte Obergrenze für die Anfragegröße.

Keine KI: E-Rechnungen sind strukturiertes XML, die Felder werden deterministisch per XPath gelesen.

## Schnellstart

```bash
docker compose up --build        # Dienst auf http://127.0.0.1:8080, Validator-Daemon im selben Container
curl -F "file=@fixtures/zugferd/synthetisch/nordstern-elbnetz-RE-2026-0042.pdf" http://127.0.0.1:8080/validate
```

Entwicklung ohne Docker-Image: `uv sync --dev`, `uv run pytest` (Unit- und API-Tests). Für die Integrationstests
mit dem echten Validator: `uv run python tools/get_validator.py`, dann entweder Java 21 lokal oder der Daemon in Docker
(siehe `tests/validator/conftest.py`) und `ERE_VALIDATOR_URL=http://127.0.0.1:8081 uv run pytest -m validator`.
Mit gesetztem `ERE_API_KEY` verlangt `/validate` den Header `X-Api-Key`. Der Schlüssel muss aus ASCII-Zeichen bestehen.

## Beispielrechnungen

Offizielle Instanzen der XRechnung-Testsuite, zwei Dateien des ZUGFeRD-Korpus und drei synthetische ZUGFeRD-PDFs
fiktiver Firmen (eine davon mit absichtlich falscher Steuersumme). Lizenzen in [fixtures/LICENSES.md](fixtures/LICENSES.md).
`XRECHNUNG_Einfach.pdf` aus dem Korpus ist ein XRechnung-2.1-Dokument; die Konfiguration 3.0.2 hat dafür kein
Prüfszenario, die Antwort lautet `gueltig: null` mit der Warnung `KEIN-SZENARIO`.

## Tests und CI

Unit-Tests (Erkennung, PDF-Anhang, Syntax, Extraktion, Archivname, Bericht), API-Tests mit gestubbtem Validator,
Integrationstests gegen den Daemon, Image-Build mit Smoke-Test. GitHub Actions führt alle drei Stufen aus.

## Entscheidungen und Grenzen

Siehe `docs/decisions/` (KoSIT-Validator, Dataverse-Eingang, Azure Container Apps, keine KI-Extraktion) und
`docs/CHANGELOG.md`. Nicht enthalten: Ausstellen von Rechnungen, DATEV-Export, OCR von Papierrechnungen.

## Lizenz

Code: MIT. Beispieldaten: siehe fixtures/LICENSES.md. Validator und Konfiguration: Apache License 2.0 (KoSIT).
