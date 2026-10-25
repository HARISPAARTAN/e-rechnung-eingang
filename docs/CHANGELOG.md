# Changelog

## v0.1.0 (2026-10-25) Meilenstein 1

- Prüfdienst (FastAPI) mit `/health` und `/validate`: PDF/A-3- und XML-Erkennung, eingebettetes XML, UBL/CII, Profil,
  KoSIT-Validator 1.6.3 mit XRechnung-Konfiguration 3.0.2 (2026-08-31), EN-16931-Felder, Archivname, API-Key.
- Beispielrechnungen (XRechnung-Testsuite, ZUGFeRD-Korpus, synthetische ZUGFeRD-PDFs), Unit-, API- und Integrationstests.
- Docker-Image mit Validator-Daemon, Compose, GitHub-Actions-Workflow (unit, validator, image).
