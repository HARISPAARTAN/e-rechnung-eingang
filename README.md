# E-Rechnung-Eingang

[![CI](https://github.com/HARISPAARTAN/e-rechnung-eingang/actions/workflows/ci.yml/badge.svg)](https://github.com/HARISPAARTAN/e-rechnung-eingang/actions/workflows/ci.yml)

Prüfdienst und Eingangs-Workflow für elektronische Rechnungen in Deutschland. English version: [README.en.md](README.en.md).

**Stand:** Die Meilensteine 1 und 2 sind fertig: der Prüfdienst (Docker) validiert XRechnung-XML und ZUGFeRD-PDFs mit dem
KoSIT-Validator, extrahiert die Rechnungsfelder nach EN 16931 und schlägt einen Archivnamen vor, und er läuft auf Azure
Container Apps (siehe [Betrieb auf Azure](#betrieb-auf-azure)). Die Meilensteine 3 und 4 (Dataverse mit Power Automate,
Power-BI-Seite) folgen.

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
| 413 | Datei größer als 10 MiB (`max_upload_mb` in `config.toml`; per `Content-Length` oder beim Mitzählen eines gestreamten Uploads) |
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

## Betrieb auf Azure

Der Dienst läuft als Azure Container App (`ca-erechnung`, Region `germanywestcentral`, 1 vCPU und 2 GiB, 0 bis 1
Replik) hinter einem öffentlichen HTTPS-Endpunkt. Einrichtung und Betrieb stehen im Runbook
[deploy/README.md](deploy/README.md).

### Aufruf

```bash
curl https://ca-erechnung.icyriver-dc3b68c8.germanywestcentral.azurecontainerapps.io/health
curl -H "X-Api-Key: $ERE_API_KEY" -F "file=@rechnung.xml" https://ca-erechnung.icyriver-dc3b68c8.germanywestcentral.azurecontainerapps.io/validate
```

`/health` ist offen, `/validate` verlangt den Header `X-Api-Key`. Der Schlüssel liegt als Secret der Container App
(`api-key`) und lokal in der git-ignorierten Datei `deploy/.secrets/ere_api_key`; er steht in keinem Repository.
Die Antwort nach einer Pause kommt erst nach dem Kaltstart (siehe unten), Clients brauchen für den ersten Aufruf also
ein Timeout von mindestens 60 s und sollten bei 502 oder 503 wiederholen.

### Bereitstellung und Proben

- **Bereitstellung:** Ein Tag `v*` startet den Workflow `release`: Er baut das Image und legt es öffentlich unter
  `ghcr.io/harispaartan/e-rechnung-eingang:<tag>` ab. Der Job `deploy` meldet sich per OIDC an Azure an (kein gespeichertes
  Azure-Passwort; Umgebung `production`), setzt das neue Image auf die Container App und führt `tools/smoke_remote.py`
  gegen die laufende URL aus (Health, 401 ohne Schlüssel, gültige XRechnung und ZUGFeRD-PDF, Upload über 10 MiB); das
  Ergebnis liegt als Artefakt `smoke.xml` am Lauf. Die erste Bereitstellung und die Einrichtung des Zugriffs macht der
  Eigentümer mit `deploy/azure.sh` und `deploy/github-oidc.sh`.
- **OIDC-Subjects:** GitHub stellt das Subject der Umgebung in zwei Formen aus, und Entra vergleicht es exakt. Das Skript legt
  deshalb zwei Federated Credentials an: `repo:HARISPAARTAN/e-rechnung-eingang:environment:production` und
  `repo:HARISPAARTAN@<Owner-ID>/e-rechnung-eingang@<Repo-ID>:environment:production`. Fehlt eines, scheitert der Login
  mit `AADSTS700213` und nennt den erwarteten Wert. Das Skript vergleicht auch das Subject vorhandener Credentials und
  bricht bei Abweichung ab (etwa nach einer Umbenennung; `REPO` steht fest im Skript).
- **Proben:** Alle drei rufen `GET /health` auf Port 8080 auf; als Erfolg gilt 200 bis 399. `/health` antwortet 503, wenn
  der Validator-Daemon nicht antwortet, und lässt damit jede Probe fehlschlagen. Startup: bis zu rund 190 s für den
  Start (Schwelle 36 mal 5 s). Readiness: nach 3 Fehlschlägen im Abstand von 10 s bekommt die Replik keinen Verkehr.
  Liveness: nach 3 Fehlschlägen im Abstand von 30 s wird der Container neu gestartet.
- **Keep-alive:** Azure löscht Umgebungen nach 90 Tagen Leerlauf. Der Workflow `keepalive` ruft am 1. jedes Monats
  `/health` auf (Variable `ERE_BASE_URL`) und schreibt die Kaltstartzeit ins Log; er lässt sich auch von Hand starten.
- **Schlüssel rotieren:** Datei löschen, `deploy/azure.sh <tag>` erneut ausführen, die aktive Revision neu starten (ein
  geändertes Secret allein ändert eine laufende Replik nicht), das GitHub-Secret `ERE_API_KEY` aktualisieren.
  Einzelheiten im Runbook.

### Kaltstart und Kontingent

Gemessen am 2026-10-25 (vom Heimnetz des Eigentümers, Revision `ca-erechnung--0000001`):

- **Kaltstart** nach Skalierung auf null: **22,6 s** bis `/health` mit 200 antwortet (Image-Pull 5 s, Container und
  Validator-Daemon bis uvicorn rund 9 s). Das sind etwa 18 bis 23 s: laut Log war die Replik rund 18 bis 20 s nach der
  Anfrage bereit, der Rest ist vermutlich der 5-s-Takt des Tests (Schlussfolgerung, nicht einzeln gemessen). Eine Replik
  wird nach 300 s ohne Anfrage abgeschaltet.
- **Warm:** `/health` in 0,1 s, `/validate` in 0,1 bis 0,3 s.
- **Kontingent:** Die Gratiskontingente (180.000 vCPU-s, 360.000 GiB-s, 2 Millionen Anfragen im Monat) reichen als
  Obergrenze für rund 545 Sitzungen im Monat zu je 330 Replik-Sekunden (Kaltstart plus 300 s Wartezeit bis zur
  Abschaltung). Eine Demo mit 30 Sitzungen und 500 Prüfungen (zusammen 150 s) braucht rund 10.050 vCPU-s und
  20.100 GiB-s, also rund 5,6 Prozent. Eine dauerhaft laufende Replik käme auf das 14-Fache des Kontingents.
- **Übergroße Uploads:** Der Dienst antwortet über 10 MiB mit 413, entschieden an der angegebenen `Content-Length`. Beobachtet:
  `curl` (getestet bei 10,1 bis 11 MiB) und ein GitHub-Linux-Runner sehen das 413; `httpx` auf einem Windows-Rechner sah
  bei 24 von 24 Uploads statt der Antwort einen Verbindungsabbruch, vermutlich weil der Ingress die Verbindung schließt,
  während noch geschrieben wird. Clients sollten einen schnellen Abbruch bei einem Upload über 10 MiB als abgelehnt
  behandeln, aber nicht einen Timeout.

## Entscheidungen und Grenzen

Siehe `docs/decisions/` (KoSIT-Validator, Dataverse-Eingang, Azure Container Apps, keine KI-Extraktion) und
`docs/CHANGELOG.md`. Nicht enthalten: Ausstellen von Rechnungen, DATEV-Export, OCR von Papierrechnungen.

## Lizenz

Code: MIT. Beispieldaten: siehe fixtures/LICENSES.md. Validator und Konfiguration: Apache License 2.0 (KoSIT).
