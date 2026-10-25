"""Remote smoke test against a deployed service: health (with cold-start timing), 401 without key, valid UBL and PDF, 413.

Oversize rule. The service decides on the declared Content-Length (ASGI guard) and answers 413 before it reads the
body. Two observations are combined:

1. Deterministic probe (decides on any OS): ``POST /validate`` with the key, ``Content-Length`` of 11 MiB and no body,
   sent with http.client. It must return 413 within the timeout. A second probe declares 9 MiB (below the limit) and must
   not return 413 (the server then waits for the body, so the probe times out); that shows the 413 depends on the size.
2. Real upload of an 11 MiB body with httpx. Expected: 413. Observed on one Windows machine (24 of 24 uploads at 10.1,
   10.5 and 11 MiB) and not on one GitHub Linux runner run: the ingress closes the connection while the client is still
   writing and a client that writes the whole body before it reads loses the response, which appears as a transport
   error. Only WriteError, ReadError and RemoteProtocolError within 5 s count as such a reset (reported as
   ``"reset:<ExceptionClass>"``); a timeout or a connection error fails. After a reset the service must still validate
   the valid UBL sample (200 and gueltig true), which shows that it is not hung or restarting.
"""

from __future__ import annotations

import argparse
import http.client
import json
import os
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit

import httpx

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures"
# relative to the fixtures directory
UBL = Path("xrechnung") / "01.01a-INVOICE_ubl.xml"
PDF = Path("zugferd") / "synthetisch" / "nordstern-elbnetz-RE-2026-0042.pdf"
MAX_UPLOAD = 10 * 1024 * 1024
OVER_LIMIT = MAX_UPLOAD + 1024 * 1024  # 11 MiB: above the limit plus the multipart slack of the guard
UNDER_LIMIT = 9 * 1024 * 1024
RESET_CLASSES = (
    "WriteError",
    "ReadError",
    "RemoteProtocolError",
)  # what a closed connection looks like in httpx
RESET_MAX_SECONDS = 5.0


def _monotonic() -> float:
    return time.monotonic()


def _sleep(seconds: float) -> None:
    time.sleep(seconds)


def wait_healthy(client: httpx.Client, base: str, timeout_s: float = 300) -> tuple[int, float]:
    """Poll /health until it answers 200 with status ok (a cold start can take minutes)."""
    start = _monotonic()
    last = 0
    while _monotonic() - start < timeout_s:
        try:
            r = client.get(f"{base}/health", timeout=30)
            last = r.status_code
            if r.status_code == 200 and r.json().get("status") == "ok":
                return r.status_code, _monotonic() - start
        except (httpx.HTTPError, ValueError):
            last = 0
        _sleep(5)
    return last, _monotonic() - start


def declared_length_probe(base: str, key: str, length: int, timeout: float = 10) -> int | str:
    """POST /validate with a declared Content-Length and no body; return the status or ``"error:<Class>"``."""
    u = urlsplit(base)
    cls = http.client.HTTPSConnection if u.scheme == "https" else http.client.HTTPConnection
    conn = cls(u.hostname, u.port, timeout=timeout)
    try:
        conn.putrequest("POST", f"{u.path.rstrip('/')}/validate")
        conn.putheader("X-Api-Key", key)
        conn.putheader("Content-Type", "multipart/form-data; boundary=smoke")
        conn.putheader("Content-Length", str(length))
        conn.endheaders()
        return conn.getresponse().status
    except (OSError, http.client.HTTPException) as exc:
        return f"error:{type(exc).__name__}"
    finally:
        conn.close()


def is_reset(too_large: int | str) -> bool:
    return isinstance(too_large, str) and too_large.startswith("reset:") and too_large[6:] in RESET_CLASSES


def oversize_rejected(
    declared: int | str,
    under_limit: int | str,
    too_large: int | str,
    too_large_seconds: float,
    after_reset: dict | None,
) -> bool:
    """Combine the deterministic probe with the real upload; see the module docstring.

    declared / under_limit: result of declared_length_probe at 11 MiB and 9 MiB; too_large: status of the real upload or
    ``"reset:<Class>"`` or ``"error:<Class>"``; after_reset: verdict of a valid UBL call made after a reset.
    """
    if declared != 413 or under_limit == 413:
        return False
    if too_large == 413:
        return True
    return (
        is_reset(too_large)
        and too_large_seconds < RESET_MAX_SECONDS
        and after_reset == {"status": 200, "gueltig": True}
    )


def _verdict(r: httpx.Response) -> dict:
    is_json = r.headers.get("content-type", "").startswith("application/json")
    return {"status": r.status_code, "gueltig": r.json().get("gueltig") if is_json else None}


def _post_outcome(
    client: httpx.Client, url: str, name: str, data: bytes, mime: str, key: str | None
) -> tuple[httpx.Response | None, str | None]:
    headers = {"X-Api-Key": key} if key else {}
    try:
        return client.post(url, headers=headers, files={"file": (name, data, mime)}), None
    except httpx.HTTPError as exc:
        return None, type(exc).__name__


def _post(
    client: httpx.Client, url: str, name: str, data: bytes, mime: str, key: str | None
) -> httpx.Response | None:
    return _post_outcome(client, url, name, data, mime, key)[0]


def run(
    base_url: str, api_key: str, fixtures_dir: Path | str = FIXTURES, health_timeout_s: float = 300
) -> dict:
    base = base_url.rstrip("/")
    fixtures = Path(fixtures_dir)
    ubl = (fixtures / UBL).read_bytes()
    pdf = (fixtures / PDF).read_bytes()
    url = f"{base}/validate"
    out: dict = {}
    with httpx.Client(timeout=120) as c:
        status, secs = wait_healthy(c, base, health_timeout_s)
        out["health"] = {"status": status, "seconds_until_ok": round(secs, 1)}
        r = _post(c, url, "a.xml", ubl, "application/xml", None)
        out["no_key"] = r.status_code if r is not None else 0
        r = _post(c, url, UBL.name, ubl, "application/xml", api_key)
        out["ubl"] = _verdict(r) if r is not None else {"status": 0, "gueltig": None}
        r = _post(c, url, PDF.name, pdf, "application/pdf", api_key)
        out["pdf"] = _verdict(r) if r is not None else {"status": 0, "gueltig": None}
        out["declared_11mib"] = declared_length_probe(base, api_key, OVER_LIMIT)
        out["declared_9mib"] = declared_length_probe(base, api_key, UNDER_LIMIT, timeout=3)
        big = b"<a>" + b"x" * (OVER_LIMIT - 7) + b"</a>"
        start = _monotonic()
        r, exc_name = _post_outcome(c, url, "big.xml", big, "application/xml", api_key)
        out["too_large_seconds"] = round(_monotonic() - start, 1)
        if r is not None:
            out["too_large"] = r.status_code
        elif exc_name in RESET_CLASSES:
            out["too_large"] = f"reset:{exc_name}"
        else:
            out["too_large"] = f"error:{exc_name}"
        out["after_reset"] = None
        if is_reset(out["too_large"]):
            r = _post(c, url, UBL.name, ubl, "application/xml", api_key)
            out["after_reset"] = _verdict(r) if r is not None else {"status": 0, "gueltig": None}
    out["ok"] = (
        out["health"]["status"] == 200
        and out["no_key"] == 401
        and out["ubl"] == {"status": 200, "gueltig": True}
        and out["pdf"] == {"status": 200, "gueltig": True}
        and oversize_rejected(
            out["declared_11mib"],
            out["declared_9mib"],
            out["too_large"],
            out["too_large_seconds"],
            out["after_reset"],
        )
    )
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--base-url", required=True)
    p.add_argument("--key-file", default="deploy/.secrets/ere_api_key")
    p.add_argument(
        "--key-env", default=None, help="read the key from this environment variable instead of the key file"
    )
    p.add_argument("--junit", default=None, help="write a minimal JUnit XML file")
    a = p.parse_args(argv)
    key = os.environ.get(a.key_env, "") if a.key_env else Path(a.key_file).read_text(encoding="utf-8").strip()
    if not key:
        print("API-Schlüssel fehlt", file=sys.stderr)
        return 2
    result = run(a.base_url, key)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    if a.junit:
        failures = 0 if result["ok"] else 1
        Path(a.junit).write_text(
            f'<testsuite name="smoke" tests="1" failures="{failures}"><testcase name="remote_smoke">'
            + ("" if result["ok"] else "<failure>see stdout</failure>")
            + "</testcase></testsuite>",
            encoding="utf-8",
        )
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
