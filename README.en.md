# E-Rechnung-Eingang

[![CI](https://github.com/HARISPAARTAN/e-rechnung-eingang/actions/workflows/ci.yml/badge.svg)](https://github.com/HARISPAARTAN/e-rechnung-eingang/actions/workflows/ci.yml)

Validation service and intake workflow for electronic invoices in Germany. German version: [README.md](README.md).

**Status:** Milestone 1 is done: the validation service (Docker) validates XRechnung XML and ZUGFeRD PDFs with the
KoSIT validator, extracts the EN 16931 invoice fields and proposes an archive name. Milestones 2 to 4
(Azure hosting, Dataverse with Power Automate, Power BI page) follow.

## Why

Since 2025 every German business must be able to receive e-invoices, from 2027/2028 also issue them (see
[docs/mandate.md](docs/mandate.md), in German). This project covers the receiving side: validate, extract, approve, file, report.

## Validation service

`POST /validate` takes a file (XRechnung XML or ZUGFeRD PDF/A-3) and answers with JSON:
file type, syntax (UBL or CII), profile, validation result with the KoSIT validator's errors and warnings,
the fields invoice number, date, due date, currency, Leitweg-ID, seller, VAT ID, buyer, IBAN, net, tax,
gross and amount due, plus the archive name `YYYY-MM-DD_seller_invoicenumber.pdf|xml`.
`GET /health` reports the validator's state and the versions. Profiles below EN 16931 (MINIMUM, BASIC WL, BASIC)
are outside the XRechnung rules and are answered with `gueltig: null` and the warning `PROFIL-AUSSERHALB`.

Uploads are limited to 10 MB (`max_upload_mb` in `config.toml`, HTTP 413 above it). The limit bounds the in-process
buffer; in production the ingress or reverse proxy sets the hard request-size limit.

No AI: e-invoices are structured XML, the fields are read deterministically with XPath.

The JSON keys are German (`dateityp`, `profil`, `gueltig`, `fehler`, `warnungen`, `felder`, `archivname`).

## Quick start

```bash
docker compose up --build        # service on http://127.0.0.1:8080, validator daemon in the same container
curl -F "file=@fixtures/zugferd/synthetisch/nordstern-elbnetz-RE-2026-0042.pdf" http://127.0.0.1:8080/validate
```

Development without the Docker image: `uv sync --dev`, `uv run pytest` (unit and API tests). For the integration tests
against the real validator: `uv run python tools/get_validator.py`, then either Java 21 locally or the daemon in Docker
(see `tests/validator/conftest.py`) and `ERE_VALIDATOR_URL=http://127.0.0.1:8081 uv run pytest -m validator`.
With `ERE_API_KEY` set, `/validate` requires the header `X-Api-Key`. The key must be ASCII.

## Sample invoices

Official instances from the XRechnung test suite, two files from the ZUGFeRD corpus and three synthetic ZUGFeRD PDFs
of fictional companies (one of them with a deliberately wrong tax total). Licences in [fixtures/LICENSES.md](fixtures/LICENSES.md).
`XRECHNUNG_Einfach.pdf` from the corpus is an XRechnung 2.1 document; the 3.0.2 configuration has no scenario for it,
so the answer is `gueltig: null` with the warning `KEIN-SZENARIO`.

## Tests and CI

Unit tests (detection, PDF attachment, syntax, extraction, archive name, report), API tests with a stubbed validator,
integration tests against the daemon, image build with a smoke test. GitHub Actions runs all three stages.

## Decisions and limits

See `docs/decisions/` (KoSIT validator, Dataverse intake, Azure Container Apps, no AI extraction; in German) and
`docs/CHANGELOG.md`. Not included: issuing invoices, DATEV export, OCR of paper invoices.

## Licence

Code: MIT. Sample data: see fixtures/LICENSES.md. Validator and configuration: Apache License 2.0 (KoSIT).
