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

`POST /validate` nimmt eine Datei als Multipart-Feld `file` entgegen (XRechnung-XML oder ZUGFeRD-PDF/A-3) und
antwortet mit JSON. Die Schlüssel in dieser Reihenfolge:

| Schlüssel | Inhalt |
|---|---|
| `dateityp` | `pdf` oder `xml`, nach Inhalt erkannt |
| `syntax` | `UBL` oder `CII` |
| `profil` | CustomizationID (UBL) bzw. Guideline-Parameter (CII) |
| `gueltig` | `true`/`false` nach KoSIT-Prüfung; `null`, wenn nicht geprüft wurde |
| `szenario` | Name des KoSIT-Prüfszenarios oder `null` |
| `fehler`, `warnungen` | Meldungen mit `ebene`, `code`, `text`, `ort` (XPath mit Präfixen wie `ubl:`, `cbc:`, `ram:`), `zeile`, `spalte` |
| `felder` | `rechnungsnummer`, `rechnungsdatum`, `faelligkeitsdatum`, `rechnungstyp`, `waehrung`, `leitweg_id`, `verkaeufer_name`, `verkaeufer_ust_idnr`, `kaeufer_name`, `iban`, `netto`, `steuer`, `brutto`, `faelliger_betrag` (fehlende Felder `null`) |
| `archivname` | `JJJJ-MM-TT_verkaeufer_rechnungsnummer.pdf\|xml` |
| `validator_bericht_html` | HTML-Bericht des KoSIT-Validators; `null` ohne Prüfung oder wenn er länger als `ERE_HTML_MAX_CHARS` (Standard 1.000.000 Zeichen, Grenze eines Dataverse-Mehrzeilenfelds) ist |
| `bericht_html_vollstaendig` | `false` nur, wenn der HTML-Bericht wegen seiner Größe weggelassen wurde |
| `datei_sha256` | SHA-256 der hochgeladenen Datei (hex) |

Archivnamen sind nicht eindeutig (`RE/2026/42` und `RE-2026-42` ergeben denselben Namen; Akzente werden gefaltet,
`Société` wird `societe`); die Datei selbst identifiziert `datei_sha256`. `GET /health` meldet `status`
(`ok` mit HTTP 200, `degraded` mit HTTP 503, wenn der Validator-Daemon nicht antwortet), `auth` (ob der API-Schlüssel
verlangt wird), den Zustand des Validators und die Versionen. Das Schema steht unter `/docs`.

Statuscodes von `/validate`:

| Code | Wann |
|---|---|
| 200 | Datei verarbeitet; das Prüfergebnis steht in `gueltig`, `fehler`, `warnungen` |
| 400 | `Content-Length` nicht numerisch oder Multipart-Inhalt nicht lesbar |
| 401 | Header `X-Api-Key` fehlt oder ist falsch (geprüft, bevor der Inhalt gelesen wird) |
| 413 | Datei größer als 10 MB (`max_upload_mb` in `config.toml`; per `Content-Length` oder beim Mitzählen eines gestreamten Uploads) |
| 422 | dauerhafter Eingabefehler: weder PDF noch XML, PDF nicht lesbar oder verschlüsselt, kein eingebettetes XML, eingebettetes XML größer als die Upload-Grenze oder in nicht unterstützter Kodierung, XML nicht wohlgeformt, DOCTYPE, unbekannte Syntax, fehlendes Feld `file`, oder der Validator hat die Eingabe abgewiesen |
| 502 | Validator-Daemon nicht erreichbar oder interner Fehler (vorübergehend, Wiederholung sinnvoll) |

Fehlerantworten haben immer die Form `{"detail": "..."}` mit einem Text.

Profile ohne Prüfszenario werden nicht an den Validator geschickt, die Felder werden trotzdem ausgelesen; die Antwort
lautet `gueltig: null` mit der Warnung `PROFIL-AUSSERHALB`. ZUGFeRD MINIMUM und BASIC WL enthalten keine vollständige
strukturierte Rechnung und sind damit keine E-Rechnung im Sinne des § 14 UStG. ZUGFeRD BASIC ist EN-16931-konform und
nach dem BMF-Schreiben vom 15. Oktober 2024 zulässig, die KoSIT-Konfiguration 3.0.2 hat dafür aber kein Prüfszenario.

Keine KI: E-Rechnungen sind strukturiertes XML, die Felder werden deterministisch per XPath gelesen.

## Schnellstart

Der Dienst verlangt einen API-Schlüssel. Ohne `ERE_API_KEY` und ohne die ausdrückliche Entwicklungsfreigabe
`ERE_AUTH_DISABLED=1` beendet sich der Container beim Start mit einer Fehlermeldung. Ein gesetzter Schlüssel gilt immer.

```bash
ERE_API_KEY=geheim docker compose up --build -d     # Dienst auf http://127.0.0.1:8080 (anderer Port: ERE_PORT=18080)
curl -H "X-Api-Key: geheim" -F "file=@fixtures/zugferd/synthetisch/nordstern-elbnetz-RE-2026-0042.pdf" http://127.0.0.1:8080/validate

ERE_AUTH_DISABLED=1 docker compose up --build -d     # nur lokal: ohne Schlüssel
```

Der Validator-Daemon läuft im selben Container und hört nur auf 127.0.0.1. Stirbt einer der beiden Prozesse, beendet
sich der Container, damit die Plattform ihn neu startet.

## Entwicklung und Tests

`uv sync --dev`, dann `uv run pytest` (Unit- und API-Tests mit gestubbtem Validator).

Integrationstests gegen den echten Validator: `uv run python tools/get_validator.py` lädt Jar und Konfiguration nach
`.validator/`. Mit lokalem Java 21 startet `uv run pytest tests/validator -m validator` den Daemon selbst. Ohne Java
läuft er in Docker:

```bash
docker run -d --name ere-validator -p 8089:8081 -v "$PWD/.validator:/v" eclipse-temurin:21-jre \
  java -jar /v/validator.jar -s /v/config/scenarios.xml -r /v/config -D -H 0.0.0.0 -P 8081 --disable-gui
ERE_VALIDATOR_URL=http://127.0.0.1:8089 uv run pytest tests/validator -m validator
docker rm -f ere-validator
```

`ERE_VALIDATOR_URL` zeigt auf einen von außen erreichbaren Daemon; ist sie gesetzt (oder `CI`) und antwortet dort
kein Daemon mit `UP`, schlagen die Tests fehl, statt übersprungen zu werden. Unter Git Bash auf Windows
`MSYS_NO_PATHCONV=1` vor `docker run` setzen. Der Schlüssel in `ERE_API_KEY` muss aus ASCII-Zeichen bestehen.

## Beispielrechnungen

Offizielle Instanzen der XRechnung-Testsuite, zwei Dateien des ZUGFeRD-Korpus, drei synthetische ZUGFeRD-PDFs
fiktiver Firmen (eine davon mit absichtlich falscher Steuersumme) und eine synthetische Rechnung mit Nachlass und
Vorauszahlung als UBL und CII. Lizenzen in [fixtures/LICENSES.md](fixtures/LICENSES.md).
`XRECHNUNG_Einfach.pdf` aus dem Korpus ist ein XRechnung-2.1-Dokument; die Konfiguration 3.0.2 hat dafür kein
Prüfszenario, die Antwort lautet `gueltig: null` mit der Warnung `KEIN-SZENARIO`.

## Tests und CI

Unit-Tests (Erkennung, PDF-Anhang, Syntax, Extraktion mit festen Sollwerten, Archivname, Bericht, Versions-Pins),
API-Tests mit gestubbtem Validator, Integrationstests gegen den Daemon, Image-Build mit Smoke-Test (401 ohne Schlüssel,
XRechnung und ZUGFeRD-PDF gültig). GitHub Actions führt alle drei Stufen aus.

## Entscheidungen und Grenzen

Siehe `docs/decisions/` (KoSIT-Validator, Dataverse-Eingang, Azure Container Apps, keine KI-Extraktion) und
`docs/CHANGELOG.md`. Nicht enthalten: Ausstellen von Rechnungen, DATEV-Export, OCR von Papierrechnungen.

## Lizenz

Code: MIT. Beispieldaten: siehe fixtures/LICENSES.md. Validator und Konfiguration: Apache License 2.0 (KoSIT).
