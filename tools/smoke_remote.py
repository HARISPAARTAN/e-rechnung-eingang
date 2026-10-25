"""Remote smoke test against a deployed service: health (with cold-start timing), 401 without key, valid UBL and PDF, 413."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures"
# relative to the fixtures directory
UBL = Path("xrechnung") / "01.01a-INVOICE_ubl.xml"
PDF = Path("zugferd") / "synthetisch" / "nordstern-elbnetz-RE-2026-0042.pdf"
MAX_UPLOAD = 10 * 1024 * 1024


def wait_healthy(client: httpx.Client, base: str, timeout_s: float = 300) -> tuple[int, float]:
    """Poll /health until it answers 200 with status ok (a cold start can take minutes)."""
    start = time.monotonic()
    last = 0
    while time.monotonic() - start < timeout_s:
        try:
            r = client.get(f"{base}/health", timeout=30)
            last = r.status_code
            if r.status_code == 200 and r.json().get("status") == "ok":
                return r.status_code, time.monotonic() - start
        except (httpx.HTTPError, ValueError):
            last = 0
        time.sleep(5)
    return last, time.monotonic() - start


def _verdict(r: httpx.Response) -> dict:
    is_json = r.headers.get("content-type", "").startswith("application/json")
    return {"status": r.status_code, "gueltig": r.json().get("gueltig") if is_json else None}


def _post(client: httpx.Client, url: str, name: str, data: bytes, mime: str, key: str | None) -> httpx.Response | None:
    headers = {"X-Api-Key": key} if key else {}
    try:
        return client.post(url, headers=headers, files={"file": (name, data, mime)})
    except httpx.HTTPError:
        return None


def run(base_url: str, api_key: str, fixtures_dir: Path | str = FIXTURES, health_timeout_s: float = 300) -> dict:
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
        big = b"<a>" + b"x" * (MAX_UPLOAD + 1024 * 1024) + b"</a>"
        r = _post(c, url, "big.xml", big, "application/xml", api_key)
        out["too_large"] = r.status_code if r is not None else 0
    out["ok"] = (
        out["health"]["status"] == 200
        and out["no_key"] == 401
        and out["ubl"] == {"status": 200, "gueltig": True}
        and out["pdf"] == {"status": 200, "gueltig": True}
        and out["too_large"] == 413
    )
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--base-url", required=True)
    p.add_argument("--key-file", default="deploy/.secrets/ere_api_key")
    p.add_argument("--key-env", default=None, help="read the key from this environment variable instead of the key file")
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
