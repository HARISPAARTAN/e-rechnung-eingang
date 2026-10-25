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

`POST /validate` takes a file in the multipart field `file` (XRechnung XML or ZUGFeRD PDF/A-3) and answers with JSON.
The keys are German; in this order:

| Key | Content |
|---|---|
| `dateityp` | `pdf` or `xml`, detected by content |
| `syntax` | `UBL` or `CII` |
| `profil` | CustomizationID (UBL) or guideline parameter (CII) |
| `gueltig` | `true`/`false` from the KoSIT validation; `null` when not validated |
| `szenario` | name of the KoSIT scenario or `null` |
| `fehler`, `warnungen` | messages with `ebene`, `code`, `text`, `ort` (XPath with prefixes such as `ubl:`, `cbc:`, `ram:`), `zeile`, `spalte` |
| `felder` | `rechnungsnummer`, `rechnungsdatum`, `faelligkeitsdatum`, `rechnungstyp`, `waehrung`, `leitweg_id`, `verkaeufer_name`, `verkaeufer_ust_idnr`, `kaeufer_name`, `iban`, `netto`, `steuer`, `brutto`, `faelliger_betrag` (missing fields `null`) |
| `archivname` | `YYYY-MM-DD_seller_invoicenumber.pdf\|xml` |
| `validator_bericht_html` | the KoSIT validator's HTML report; `null` without validation or when longer than `ERE_HTML_MAX_CHARS` (default 1,000,000 characters, the limit of a Dataverse multiline text column) |
| `bericht_html_vollstaendig` | `false` only when the HTML report was left out because of its size |
| `datei_sha256` | SHA-256 of the uploaded file (hex) |

Archive names are not unique (`RE/2026/42` and `RE-2026-42` give the same name; accents are folded, `Société` becomes
`societe`); `datei_sha256` identifies the file itself. `GET /health` reports `status` (`ok` with HTTP 200,
`degraded` with HTTP 503 when the validator daemon does not answer), `auth` (whether the API key is required), the
validator's state and the versions. The schema is served at `/docs`.

Status codes of `/validate`:

| Code | When |
|---|---|
| 200 | file processed; the verdict is in `gueltig`, `fehler`, `warnungen` |
| 400 | `Content-Length` not numeric or multipart body unreadable |
| 401 | header `X-Api-Key` missing or wrong (checked before the body is read) |
| 413 | file larger than 10 MB (`max_upload_mb` in `config.toml`; from `Content-Length` or by counting a streamed upload) |
| 422 | permanent input error: neither PDF nor XML, PDF unreadable or encrypted, no embedded XML, embedded XML larger than the upload limit or in an unsupported encoding, XML not well-formed, DOCTYPE, unknown syntax, missing field `file`, or the validator refused the input |
| 502 | validator daemon unreachable or failing (transient, worth a retry) |

Error responses always have the shape `{"detail": "..."}` with a string.

Profiles without a validation scenario are not sent to the validator; the fields are still extracted and the answer is
`gueltig: null` with the warning `PROFIL-AUSSERHALB`. ZUGFeRD MINIMUM and BASIC WL carry no complete structured
invoice and are therefore not e-invoices under § 14 UStG. ZUGFeRD BASIC is EN 16931-compliant and accepted by the
BMF letter of 15 October 2024, but the KoSIT configuration 3.0.2 has no scenario for it.

No AI: e-invoices are structured XML, the fields are read deterministically with XPath.

## Quick start

The service requires an API key. Without `ERE_API_KEY` and without the explicit development opt-out
`ERE_AUTH_DISABLED=1` the container exits at start with an error message. A configured key is always enforced.

```bash
ERE_API_KEY=secret docker compose up --build -d     # service on http://127.0.0.1:8080 (other port: ERE_PORT=18080)
curl -H "X-Api-Key: secret" -F "file=@fixtures/zugferd/synthetisch/nordstern-elbnetz-RE-2026-0042.pdf" http://127.0.0.1:8080/validate

ERE_AUTH_DISABLED=1 docker compose up --build -d    # local only: no key
```

The validator daemon runs in the same container and listens on 127.0.0.1 only. When either process dies the container
exits so the platform restarts it.

## Development and tests

`uv sync --dev`, then `uv run pytest` (unit and API tests with a stubbed validator).

Integration tests against the real validator: `uv run python tools/get_validator.py` downloads the jar and the
configuration into `.validator/`. With a local Java 21, `uv run pytest tests/validator -m validator` starts the daemon
itself. Without Java, run it in Docker:

```bash
docker run -d --name ere-validator -p 8089:8081 -v "$PWD/.validator:/v" eclipse-temurin:21-jre \
  java -jar /v/validator.jar -s /v/config/scenarios.xml -r /v/config -D -H 0.0.0.0 -P 8081 --disable-gui
ERE_VALIDATOR_URL=http://127.0.0.1:8089 uv run pytest tests/validator -m validator
docker rm -f ere-validator
```

`ERE_VALIDATOR_URL` points to an externally reachable daemon; when it is set (or `CI` is) and no daemon answers `UP`
there, the tests fail instead of being skipped. In Git Bash on Windows prefix `docker run` with `MSYS_NO_PATHCONV=1`.
The key in `ERE_API_KEY` must be ASCII.

## Sample invoices

Official instances from the XRechnung test suite, two files from the ZUGFeRD corpus, three synthetic ZUGFeRD PDFs
of fictional companies (one of them with a deliberately wrong tax total) and one synthetic invoice with an allowance
and a prepaid amount as UBL and CII. Licences in [fixtures/LICENSES.md](fixtures/LICENSES.md).
`XRECHNUNG_Einfach.pdf` from the corpus is an XRechnung 2.1 document; the 3.0.2 configuration has no scenario for it,
so the answer is `gueltig: null` with the warning `KEIN-SZENARIO`.

## Tests and CI

Unit tests (detection, PDF attachment, syntax, extraction against fixed golden values, archive name, report, version
pins), API tests with a stubbed validator, integration tests against the daemon, image build with a smoke test (401
without key, XRechnung and ZUGFeRD PDF valid). GitHub Actions runs all three stages.

## Decisions and limits

See `docs/decisions/` (KoSIT validator, Dataverse intake, Azure Container Apps, no AI extraction; in German) and
`docs/CHANGELOG.md`. Not included: issuing invoices, DATEV export, OCR of paper invoices.

## Licence

Code: MIT. Sample data: see fixtures/LICENSES.md. Validator and configuration: Apache License 2.0 (KoSIT).
