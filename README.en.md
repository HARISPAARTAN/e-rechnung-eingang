# E-Rechnung-Eingang

[![CI](https://github.com/HARISPAARTAN/e-rechnung-eingang/actions/workflows/ci.yml/badge.svg)](https://github.com/HARISPAARTAN/e-rechnung-eingang/actions/workflows/ci.yml)

Validation service and intake workflow for electronic invoices in Germany. German version: [README.md](README.md).

**Status:** Milestones 1 and 2 are done: the validation service (Docker) validates XRechnung XML and ZUGFeRD PDFs with the
KoSIT validator, extracts the EN 16931 invoice fields and proposes an archive name, and it runs on Azure Container Apps
(see [Operation on Azure](#operation-on-azure)). Milestones 3 and 4 (Dataverse with Power Automate, Power BI page)
follow.

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
| 413 | file larger than 10 MiB (`max_upload_mb` in `config.toml`; from `Content-Length` or by counting a streamed upload) |
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

## Operation on Azure

The service runs as an Azure Container App (`ca-erechnung`, region `germanywestcentral`, 1 vCPU and 2 GiB, 0 to 1
replica). Setup and operation are described in the runbook [deploy/README.md](deploy/README.md) (in German). The public HTTPS
endpoint is https://ca-erechnung.icyriver-dc3b68c8.germanywestcentral.azurecontainerapps.io.

### Calling it

```bash
curl https://ca-erechnung.icyriver-dc3b68c8.germanywestcentral.azurecontainerapps.io/health
curl -H "X-Api-Key: $ERE_API_KEY" -F "file=@invoice.xml" https://ca-erechnung.icyriver-dc3b68c8.germanywestcentral.azurecontainerapps.io/validate
```

`/health` is open, `/validate` needs the `X-Api-Key` header. The key is a secret of the container app (`api-key`) and
lives locally in the git-ignored file `deploy/.secrets/ere_api_key`; it is in no repository. After an idle period the
first answer waits for the cold start (see below), so clients should use a timeout of at least 60 s for the first call
and retry on 502 or 503.

### Deployment and probes

- **Deployment:** a tag `v*` starts the `release` workflow: it builds the image and publishes it publicly as
  `ghcr.io/harispaartan/e-rechnung-eingang:<tag>`. The `deploy` job signs in to Azure with OIDC (no stored Azure
  password; environment `production`), sets the new image on the container app and runs `tools/smoke_remote.py`
  against the live URL (health, 401 without key, valid XRechnung and ZUGFeRD PDF, upload over 10 MiB); the result is
  attached to the run as the `smoke.xml` artifact. The owner does the first deployment and the access setup with
  `deploy/azure.sh` and `deploy/github-oidc.sh`.
- **OIDC subjects:** GitHub issues the subject of the environment in two forms and Entra compares it exactly, so the
  script creates two federated credentials: `repo:HARISPAARTAN/e-rechnung-eingang:environment:production` and
  `repo:HARISPAARTAN@<owner id>/e-rechnung-eingang@<repo id>:environment:production`. If one is missing, the login fails
  with `AADSTS700213` and names the expected value. The script also compares the subject of existing credentials and
  stops on a mismatch (for example after a rename; `REPO` is fixed in the script).
- **Probes:** all three call `GET /health` on port 8080; 200 to 399 counts as success. `/health` answers 503 when the
  validator daemon does not respond, which makes every probe fail. Startup: up to about 190 s for the start (threshold
  36 times 5 s). Readiness: after 3 failures 10 s apart the replica receives no traffic. Liveness: after 3 failures
  30 s apart the container is restarted.
- **Keep-alive:** Azure deletes environments after 90 days of idleness. The `keepalive` workflow calls `/health` on the
  1st of every month (variable `ERE_BASE_URL`) and logs the cold-start time; it can also be started by hand.
- **Key rotation:** delete the file, run `deploy/azure.sh <tag>` again, restart the active revision (a changed secret
  alone does not change a running replica), update the GitHub secret `ERE_API_KEY`. Details in the runbook.

### Cold start and free grant

Measured on 2026-10-25 (from the owner's home network, revision `ca-erechnung--0000001`):

- **Cold start** after scale-to-zero: **22.6 s** until `/health` answers 200 (image pull 5 s, container and validator
  daemon up to uvicorn about 9 s). That is about 18 to 23 s: according to the log the replica was ready about 18 to
  20 s after the request, and the rest is probably the 5 s polling step of the test (an inference, not measured
  separately). A replica is shut down after 300 s without requests.
- **Warm:** `/health` in 0.1 s, `/validate` in 0.1 to 0.3 s.
- **Grant:** the free monthly grants (180,000 vCPU-s, 360,000 GiB-s, 2 million requests) allow, as an upper bound,
  about 545 sessions a month at 330 replica-seconds each (cold start plus 300 s wait before shutdown). A demo with
  30 sessions and 500 checks (150 s together) needs about 10,050 vCPU-s and 20,100 GiB-s, roughly 5.6 percent. A replica that never
  scaled down would use 14 times the grant.
- **Oversized uploads:** the service answers 413 above 10 MiB, decided from the declared `Content-Length`. Observed:
  `curl` (tested at 10.1 to 11 MiB) and a GitHub Linux runner see the 413; `httpx` on one Windows machine saw a
  connection reset instead of the response in 24 of 24 uploads, probably because the ingress closes the connection
  while the client is still writing. Clients should treat a fast reset on an upload over 10 MiB as rejected, but not
  a timeout.

## Decisions and limits

See `docs/decisions/` (KoSIT validator, Dataverse intake, Azure Container Apps, no AI extraction; in German) and
`docs/CHANGELOG.md`. Not included: issuing invoices, DATEV export, OCR of paper invoices.

## Licence

Code: MIT. Sample data: see fixtures/LICENSES.md. Validator and configuration: Apache License 2.0 (KoSIT).
