# Changelog

## v0.2.0 (2026-10-25, in Vorbereitung) Meilenstein 2 Betrieb auf Azure Container Apps

- Bereitstellung: `deploy/containerapp.bicep` (Verbrauchsplan, 1 vCPU und 2 GiB, Replikate 0 bis 1, Secret `api-key`, Startup-,
  Liveness- und Readiness-Probe auf `/health`), Owner-Skripte `deploy/azure.sh` und `deploy/github-oidc.sh` (zwei
  Federated Credentials wegen der beiden Subject-Formen von GitHub), Runbook `deploy/README.md`.
- Workflows: `release` baut und veröffentlicht das Image auf GHCR und aktualisiert die Container App per OIDC, danach
  Smoke-Test gegen die Live-URL (`tools/smoke_remote.py`, Artefakt `smoke.xml`); `keepalive` ruft monatlich `/health` auf.
- Smoke-Test: Entscheidung über eine Anfrage ohne Körper mit `Content-Length` 11 MiB (erwartet 413, auf jedem System) und
  eine Gegenprobe mit 9 MiB; der echte Upload gilt bei 413 oder einem schnellen Abbruch (unter 5 s) als abgelehnt, wenn
  danach ein gültiges UBL 200 und `gueltig: true` ergibt, Timeouts schlagen fehl. `deploy/github-oidc.sh` legt beide
  Credentials an, vergleicht das Subject und bricht bei Abweichung ab.
- Gemessen: Kaltstart 22,6 s, warm 0,1 s (siehe "M2 Betrieb" unten und README "Betrieb auf Azure").
- Versionen: Paket und Dienst 0.2.0. Tag `v0.2.0` folgt nach grünem CI und Prüfung.

## M2 Betrieb: erste Azure-Bereitstellung (2026-10-25)

- Erstbereitstellung mit `deploy/azure.sh v0.2.0-rc1` in `rg-erechnung` (`germanywestcentral`), Container App
  `ca-erechnung`, Revisionen `ca-erechnung--hbq4h1u` (rc1) und `ca-erechnung--0000001` (rc2). GHCR-Paket öffentlich, der Pull
  brauchte keine Zugangsdaten.
- Kaltstart nach Skalierung auf null 22,6 s, etwa 18 bis 23 s (Image-Pull 5,0 s, uvicorn 9 s nach Containerstart; laut Log bereit rund 18 bis 20 s nach der Anfrage, der Rest vermutlich der 5-s-Takt des Tests), warm `/health` 0,1 s und
  `/validate` 0,1 bis 0,3 s. Startup-, Liveness- und Readiness-Probe liefern 200, kein `ProbeFailed`, Revision `Healthy`.
- Gratiskontingent (Obergrenze): rund 330 Replik-Sekunden je Sitzung, eine Demo mit 30 Sitzungen und 500 Prüfungen (150 s)
  braucht rund 5,6 Prozent der Kontingente (Rechnung im Runbook).
- Übergroße Uploads: Der Dienst antwortet über 10 MiB mit 413. Beobachtet: `curl` (10,1 bis 11 MiB) und ein Linux-Runner
  sehen es; `httpx` auf einem Windows-Rechner sah in 24 von 24 Uploads einen Verbindungsabbruch. Regel im Smoke-Test siehe oben.

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
