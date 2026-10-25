# Changelog

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
- Kleineres: Anhänge nach Dateiname (`/UF`, `/F`) und `/AF`-Reihenfolge, Obergrenze 50 MiB; Fehlerantworten immer
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
