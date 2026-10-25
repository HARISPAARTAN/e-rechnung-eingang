"""UploadGuard: key and size are checked before the body is read (driven through the raw ASGI interface)."""

import asyncio
import json
import time
from pathlib import Path

from fastapi.testclient import TestClient

from erechnung.api import create_app
from erechnung.config import load_settings
from erechnung.validator import Pruefergebnis

ROOT = Path(__file__).resolve().parents[2]
UBL = ROOT / "fixtures" / "xrechnung" / "01.01a-INVOICE_ubl.xml"
MB = 1024 * 1024
BOUNDARY = b"guardtestboundary"


class StubClient:
    def __init__(self):
        self.calls = []

    def health(self):
        return {"status": "UP", "http": 200}

    def validate(self, xml, name="rechnung.xml"):
        self.calls.append(name)
        return Pruefergebnis(True, "accept", "XRechnung", [], [], None)


def _app(monkeypatch, stub, api_key=None):
    if api_key:
        monkeypatch.setenv("ERE_API_KEY", api_key)
    else:
        monkeypatch.delenv("ERE_API_KEY", raising=False)
        monkeypatch.setenv("ERE_AUTH_DISABLED", "1")
    return create_app(load_settings(ROOT), client=stub)


class Body:
    """ASGI receive callable that yields the body in chunks and records how much was pulled."""

    PREFIX = (
        b"--" + BOUNDARY + b"\r\n"
        b'Content-Disposition: form-data; name="file"; filename="big.xml"\r\n'
        b"Content-Type: application/xml\r\n\r\n<a>"
    )

    def __init__(self, total: int, chunk: int = MB):
        self.total, self.chunk, self.sent, self.calls = total, chunk, 0, 0

    async def __call__(self):
        self.calls += 1
        if self.sent >= self.total:
            await asyncio.sleep(0)
            return {"type": "http.disconnect"}
        n = min(self.chunk, self.total - self.sent)
        payload = (self.PREFIX + b"x" * (n - len(self.PREFIX))) if self.sent == 0 else b"x" * n
        self.sent += n
        return {"type": "http.request", "body": payload, "more_body": self.sent < self.total}


def _call(app, headers, receive):
    messages = []

    async def send(message):
        messages.append(message)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/validate",
        "raw_path": b"/validate",
        "root_path": "",
        "query_string": b"",
        "headers": [(b"host", b"testserver"), (b"content-type", b"multipart/form-data; boundary=" + BOUNDARY), *headers],
        "client": ("127.0.0.1", 1234),
        "server": ("testserver", 80),
    }
    asyncio.run(app(scope, receive, send))
    start = next(m for m in messages if m["type"] == "http.response.start")
    body = b"".join(m.get("body", b"") for m in messages if m["type"] == "http.response.body")
    return start["status"], json.loads(body)


def test_401_without_key_does_not_read_a_12_mb_body(monkeypatch):
    stub = StubClient()
    app = _app(monkeypatch, stub, api_key="geheim")
    receive = Body(12 * MB)
    t0 = time.perf_counter()
    status, body = _call(app, [(b"content-length", str(12 * MB).encode())], receive)
    assert status == 401 and body == {"detail": "API-Schlüssel fehlt oder ist ungültig"}
    assert receive.calls == 0 and receive.sent == 0 and stub.calls == []
    assert time.perf_counter() - t0 < 1.0


def test_401_with_wrong_key_does_not_read_the_body(monkeypatch):
    app = _app(monkeypatch, StubClient(), api_key="geheim")
    receive = Body(1000)
    status, _ = _call(app, [(b"x-api-key", b"falsch")], receive)
    assert status == 401 and receive.calls == 0


def test_413_from_content_length_alone(monkeypatch):
    stub = StubClient()
    app = _app(monkeypatch, stub)
    receive = Body(100)  # small body, forged large header
    status, body = _call(app, [(b"content-length", str(50 * MB).encode())], receive)
    assert status == 413 and body == {"detail": "Datei größer als 10 MB"}
    assert receive.calls == 0 and stub.calls == []


def test_413_for_chunked_upload_above_the_limit_stops_reading(monkeypatch):
    stub = StubClient()
    app = _app(monkeypatch, stub)
    receive = Body(30 * MB)  # no content-length: transfer-encoding chunked
    status, body = _call(app, [(b"transfer-encoding", b"chunked")], receive)
    assert status == 413 and body == {"detail": "Datei größer als 10 MB"}
    assert receive.sent <= 11 * MB, "stream consumed past the limit"
    assert stub.calls == []


def test_chunked_upload_below_the_limit_passes_the_guard(monkeypatch):
    stub = StubClient()
    app = _app(monkeypatch, stub)
    data = UBL.read_bytes()
    multipart = (
        b"--" + BOUNDARY + b"\r\n"
        b'Content-Disposition: form-data; name="file"; filename="a.xml"\r\n'
        b"Content-Type: application/xml\r\n\r\n" + data + b"\r\n--" + BOUNDARY + b"--\r\n"
    )
    chunks = [multipart[i : i + 4096] for i in range(0, len(multipart), 4096)]

    async def receive():
        if chunks:
            return {"type": "http.request", "body": chunks.pop(0), "more_body": bool(chunks)}
        await asyncio.sleep(0)
        return {"type": "http.disconnect"}

    status, body = _call(app, [(b"transfer-encoding", b"chunked")], receive)
    assert status == 200 and body["syntax"] == "UBL" and stub.calls == ["a.xml"]


def test_valid_upload_below_the_limit_returns_200(monkeypatch):
    stub = StubClient()
    c = TestClient(_app(monkeypatch, stub, api_key="geheim"))
    resp = c.post("/validate", files={"file": ("a.xml", UBL.read_bytes(), "application/xml")}, headers={"X-Api-Key": "geheim"})
    assert resp.status_code == 200 and stub.calls == ["a.xml"]


def test_guard_leaves_other_routes_alone(monkeypatch):
    c = TestClient(_app(monkeypatch, StubClient(), api_key="geheim"))
    assert c.get("/health").status_code == 200
