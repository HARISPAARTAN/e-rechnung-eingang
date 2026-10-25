# Changelog

## M2 Betrieb: erste Azure-Bereitstellung (2026-10-25)

- Erstbereitstellung mit `deploy/azure.sh v0.2.0-rc1` in `rg-erechnung` (`germanywestcentral`), Container App
  `ca-erechnung`, Revisionen `ca-erechnung--hbq4h1u` (rc1) und `ca-erechnung--0000001` (rc2). GHCR-Paket öffentlich, der Pull
  brauchte keine Zugangsdaten.
- Kaltstart nach Skalierung auf null 22,6 s (Image-Pull 5,0 s, uvicorn 9 s nach Containerstart), warm `/health` 0,1 s und
  `/validate` 0,1 bis 0,3 s. Startup-, Liveness- und Readiness-Probe liefern 200, kein `ProbeFailed`, Revision `Healthy`.
- Gratiskontingent: rund 330 Replik-Sekunden je Sitzung, eine Demo mit 30 Sitzungen und 500 Prüfungen kostet rund 5,5
  Prozent der Kontingente (Rechnung im Runbook).
- Übergroße Uploads: Der Dienst antwortet über 10 MB mit 413 (`curl` und der Linux-Runner sehen es); Python/`httpx` unter
  Windows sieht einen Verbindungsabbruch. `tools/smoke_remote.py` erwartet 413 und akzeptiert den Abbruch nur, wenn
  `/health` danach 200 meldet.

## v0.1.1 (2026-10-25) Härtung nach Review

- Betrieb (vor Meilenstein 2): `/health` antwortet 503, wenn der Daemon ausfällt, und meldet `auth`; tini als PID 1,
  das Startskript überwacht Java und uvicorn und beendet den Container, wenn einer stirbt; Java mit
  `-XX:+ExitOnOutOfMemoryError`. API-Schlüssel und Größe werden vor dem Lesen des Inhalts geprüft (ASGI-Guard), der
  Schlüssel ist Pflicht (`ERE_AUTH_DISABLED=1` nur für Entwicklung). Image mehrstufig aus `uv.lock`, Basis per Digest
  gepinnt, Temurin-21-JRE, `ERE_ROOT`; Test gegen Abweichungen der Validator-Pins zwischen Dockerfile und `config.toml`.
  HTML-Bericht über `ERE_HTML_MAX_CHARS` wird weggelassen (`bericht_html_vollstaendig: false`).
- Vertrag (vor Meilenstein 3): DOCTYPE wird mit 422 abgelehnt; eine 4xx-Antwort des Daemons ergibt 422 statt 502;
  verschlüsselte PDFs 422; BT-110 nur in Rechnungswährung; Sollwert-Tests für alle 14 Felder und eine synthetische
  Rechnung mit Nachlass und Vorauszahlung (UBL und CII).
- Kleineres: Anhänge nach Dateiname (`/UF`, `/F`) und `/AF`-Reihenfolge, jede Dekodierung durch die Upload-Grenze begrenzt (nur ungefiltert oder einfaches Flate, sonst 422), Java mit `-Xmx1g`; Fehlerantworten immer
  `{"detail": "..."}`, Ursachen von 422 und 502 im Log; `ort` mit Präfixen statt Namensräumen; Antwortmodelle in
  OpenAPI; Akzente im Archivnamen gefaltet, `datei_sha256` im Bericht; `PROFIL-AUSSERHALB` unterscheidet MINIMUM und
  BASIC WL (keine E-Rechnung nach § 14 UStG) von BASIC (EN-16931-konform, ohne KoSIT-Szenario); CI mit
  `uv sync --locked`, Smoke-Test mit 401 und PDF, `permissions: contents: read`; README mit allen Schlüsseln und
  Statuscodes.

## v0.1.0 (2026-10-25) Meilenstein 1

- Prüfdienst (FastAPI) mit `/health` und `/validate`: PDF/A-3- und XML-Erkennung, eingebettetes XML, UBL/CII, Profil,
  KoSIT-Validator 1.6.3 mit XRechnung-Konfiguration 3.0.2 (2026-08-31), EN-16931-Felder, Archivname, API-Key.
- Beispielrechnungen (XRechnung-Testsuite, ZUGFeRD-Korpus, synthetische ZUGFeRD-PDFs), Unit-, API- und Integrationstests.
- Docker-Image mit Validator-Daemon, Compose, GitHub-Actions-Workflow (unit, validator, image).
