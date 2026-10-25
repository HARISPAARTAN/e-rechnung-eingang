"""tools/smoke_remote.py against a mocked service (respx); no network."""

import http.server
import threading
from pathlib import Path

import httpx
import pytest
import respx

from tools import smoke_remote

ROOT = Path(__file__).resolve().parents[2]
BASE = "https://ca-erechnung.example.azurecontainerapps.io"
REAL_PROBE = smoke_remote.declared_length_probe  # the autouse fixture below replaces the module attribute
JSON = {"content-type": "application/json"}


@pytest.fixture
def fake_clock(monkeypatch):
    """Replace the clock: sleeping advances it, so the measured cold start is deterministic."""
    now = [1000.0]
    monkeypatch.setattr(smoke_remote, "_monotonic", lambda: now[0])
    monkeypatch.setattr(smoke_remote, "_sleep", lambda s: now.__setitem__(0, now[0] + s))
    return now


@pytest.fixture(autouse=True)
def declared(monkeypatch):
    """Stub for the http.client probe: 413 above the limit, a wait (timeout) below it, as the real service behaves."""
    results = {smoke_remote.OVER_LIMIT: 413, smoke_remote.UNDER_LIMIT: "error:TimeoutError"}
    monkeypatch.setattr(
        smoke_remote, "declared_length_probe", lambda base, key, length, timeout=10: results[length]
    )
    return results


def _mock(router, *, ubl_status=200, too_large=None, after_reset=None):
    router.get(f"{BASE}/health").mock(
        side_effect=[
            httpx.Response(503, json={"status": "degraded"}),
            httpx.Response(200, json={"status": "ok"}),
        ]
    )
    posts = [
        httpx.Response(401, json={"detail": "unauthorized"}),
        httpx.Response(ubl_status, json={"gueltig": True}, headers=JSON),
        httpx.Response(200, json={"gueltig": True}, headers=JSON),
        too_large if too_large is not None else httpx.Response(413, json={"detail": "too large"}),
    ]
    if isinstance(too_large, Exception):  # the follow-up UBL call after a reset
        posts.append(after_reset or httpx.Response(200, json={"gueltig": True}, headers=JSON))
    router.post(f"{BASE}/validate").mock(side_effect=posts)


def test_run_ok(fake_clock):
    with respx.mock(assert_all_called=True) as router:
        _mock(router)
        result = smoke_remote.run(BASE + "/", "k", ROOT / "fixtures")
    assert result["ok"] is True
    assert result["health"] == {"status": 200, "seconds_until_ok": 5.0}
    assert result["no_key"] == 401
    assert result["ubl"] == {"status": 200, "gueltig": True}
    assert result["pdf"] == {"status": 200, "gueltig": True}
    assert result["too_large"] == 413
    assert result["declared_11mib"] == 413
    assert result["declared_9mib"] == "error:TimeoutError"
    assert result["after_reset"] is None


def test_run_sends_key_only_on_authenticated_calls(fake_clock):
    with respx.mock() as router:
        _mock(router)
        smoke_remote.run(BASE, "secret-key", ROOT / "fixtures")
        posts = [c.request for c in router.calls if c.request.method == "POST"]
    assert [p.headers.get("x-api-key") for p in posts] == [None, "secret-key", "secret-key", "secret-key"]


def test_run_fails_on_server_error(fake_clock):
    with respx.mock() as router:
        _mock(router, ubl_status=500)
        result = smoke_remote.run(BASE, "k", ROOT / "fixtures")
    assert result["ok"] is False
    assert result["ubl"]["status"] == 500


def test_run_reports_transport_error_as_status_zero(fake_clock):
    with respx.mock() as router:
        router.get(f"{BASE}/health").mock(return_value=httpx.Response(200, json={"status": "ok"}))
        router.post(f"{BASE}/validate").mock(
            side_effect=[
                httpx.Response(401),
                httpx.ConnectError("refused"),
                httpx.Response(200, json={"gueltig": True}, headers=JSON),
                httpx.Response(413),
            ]
        )
        result = smoke_remote.run(BASE, "k", ROOT / "fixtures")
    assert result["ubl"] == {"status": 0, "gueltig": None}
    assert result["ok"] is False


def test_run_accepts_fast_reset_when_service_still_validates(fake_clock):
    with respx.mock() as router:
        _mock(router, too_large=httpx.WriteError("connection reset"))
        result = smoke_remote.run(BASE, "k", ROOT / "fixtures")
    assert result["too_large"] == "reset:WriteError"
    assert result["after_reset"] == {"status": 200, "gueltig": True}
    assert result["ok"] is True


def test_run_sends_valid_ubl_with_key_after_reset(fake_clock):
    with respx.mock() as router:
        _mock(router, too_large=httpx.ReadError("reset"))
        smoke_remote.run(BASE, "secret-key", ROOT / "fixtures")
        posts = [c.request for c in router.calls if c.request.method == "POST"]
    assert len(posts) == 5
    assert posts[4].headers["x-api-key"] == "secret-key"
    assert b"01.01a-INVOICE_ubl.xml" in posts[4].content[:400]


def test_run_fails_on_reset_when_service_cannot_validate_afterwards(fake_clock):
    with respx.mock() as router:
        _mock(
            router, too_large=httpx.WriteError("reset"), after_reset=httpx.Response(502, json={"detail": "x"})
        )
        result = smoke_remote.run(BASE, "k", ROOT / "fixtures")
    assert result["too_large"] == "reset:WriteError"
    assert result["after_reset"] == {"status": 502, "gueltig": None}
    assert result["ok"] is False


def test_run_fails_on_timeout_during_oversize_upload(fake_clock):
    with respx.mock() as router:
        _mock(router, too_large=httpx.ReadTimeout("hang"))
        result = smoke_remote.run(BASE, "k", ROOT / "fixtures")
    assert result["too_large"] == "error:ReadTimeout"
    assert result["after_reset"] is None
    assert result["ok"] is False


def test_run_fails_on_connect_error_during_oversize_upload(fake_clock):
    with respx.mock() as router:
        _mock(router, too_large=httpx.ConnectError("refused"))
        result = smoke_remote.run(BASE, "k", ROOT / "fixtures")
    assert result["too_large"] == "error:ConnectError"
    assert result["ok"] is False


def test_run_fails_on_slow_reset(fake_clock):
    def slow_reset(request):
        fake_clock[0] += 30
        raise httpx.ReadError("reset after 30 s")

    with respx.mock() as router:
        router.get(f"{BASE}/health").mock(return_value=httpx.Response(200, json={"status": "ok"}))
        outcomes = [
            httpx.Response(401),
            httpx.Response(200, json={"gueltig": True}, headers=JSON),
            httpx.Response(200, json={"gueltig": True}, headers=JSON),
            slow_reset,
            httpx.Response(200, json={"gueltig": True}, headers=JSON),
        ]
        router.post(f"{BASE}/validate").mock(side_effect=lambda request: _next(outcomes, request))
        result = smoke_remote.run(BASE, "k", ROOT / "fixtures")
    assert result["too_large"] == "reset:ReadError"
    assert result["too_large_seconds"] == 30.0
    assert result["ok"] is False


def _next(outcomes, request):
    item = outcomes.pop(0)
    return item(request) if callable(item) else item


def test_run_fails_when_deterministic_probe_does_not_give_413(fake_clock, declared):
    declared[smoke_remote.OVER_LIMIT] = "error:TimeoutError"
    with respx.mock() as router:
        _mock(router)
        result = smoke_remote.run(BASE, "k", ROOT / "fixtures")
    assert result["declared_11mib"] == "error:TimeoutError"
    assert result["too_large"] == 413  # the real upload alone is not enough
    assert result["ok"] is False


def test_run_fails_when_probe_below_the_limit_also_gives_413(fake_clock, declared):
    declared[smoke_remote.UNDER_LIMIT] = 413
    with respx.mock() as router:
        _mock(router)
        result = smoke_remote.run(BASE, "k", ROOT / "fixtures")
    assert result["ok"] is False


RESET_OK = {"status": 200, "gueltig": True}


@pytest.mark.parametrize(
    ("declared", "under", "too_large", "seconds", "after", "expected"),
    [
        (413, "error:TimeoutError", 413, 0.2, None, True),
        (413, "error:TimeoutError", "reset:WriteError", 1.0, RESET_OK, True),
        (413, 200, "reset:ReadError", 1.0, RESET_OK, False),  # 9 MiB must time out, not answer
        (413, 404, 413, 0.2, None, False),
        (413, 502, 413, 0.2, None, False),
        (413, "error:ConnectionResetError", 413, 0.2, None, False),
        (413, "error:ConnectionRefusedError", 413, 0.2, None, False),
        (413, "error:TimeoutError", "reset:RemoteProtocolError", 4.9, RESET_OK, True),
        (413, "error:TimeoutError", "reset:ReadError", 5.0, RESET_OK, False),  # too slow
        (413, "error:TimeoutError", "reset:ReadError", 1.0, None, False),  # no follow-up proof
        (413, "error:TimeoutError", "reset:ReadError", 1.0, {"status": 200, "gueltig": False}, False),
        (413, "error:TimeoutError", "reset:ReadError", 1.0, {"status": 0, "gueltig": None}, False),
        (413, "error:TimeoutError", "error:ReadTimeout", 1.0, RESET_OK, False),
        (413, "error:TimeoutError", "error:ConnectError", 0.1, RESET_OK, False),
        (413, "error:TimeoutError", "reset:ConnectError", 0.1, RESET_OK, False),  # not a reset class
        (413, "error:TimeoutError", 200, 1.0, None, False),  # the oversize file was accepted
        (413, "error:TimeoutError", 422, 1.0, None, False),
        (413, "error:TimeoutError", "reset", 1.0, RESET_OK, False),  # old label without the class
        ("error:TimeoutError", "error:TimeoutError", 413, 0.2, None, False),
        (200, "error:TimeoutError", 413, 0.2, None, False),
        (413, 413, 413, 0.2, None, False),  # the limit is not size dependent
    ],
)
def test_oversize_rule(declared, under, too_large, seconds, after, expected):
    assert smoke_remote.oversize_rejected(declared, under, too_large, seconds, after) is expected


class _Handler(http.server.BaseHTTPRequestHandler):
    """413 for a declared length over 10 MiB, otherwise wait for the body that never comes (like the guard)."""

    def do_POST(self):  # noqa: N802
        n = int(self.headers["Content-Length"])
        self.server.seen.append((self.path, self.headers.get("X-Api-Key"), n))
        if n > 10 * 1024 * 1024 + 65536:
            self.send_response(413)
            self.send_header("Content-Length", "0")
            self.end_headers()
        else:
            self.rfile.read(n)  # blocks until the client gives up

    def log_message(self, *args):
        pass


@pytest.fixture
def local_service():
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    server.seen = []
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}", server
    server.shutdown()
    server.server_close()


def test_declared_length_probe_gets_413_without_a_body(local_service):
    base, server = local_service
    assert REAL_PROBE(base, "the-key", smoke_remote.OVER_LIMIT) == 413
    assert server.seen == [("/validate", "the-key", smoke_remote.OVER_LIMIT)]


def test_declared_length_probe_below_limit_times_out(local_service):
    base, _ = local_service
    assert REAL_PROBE(base, "k", smoke_remote.UNDER_LIMIT, timeout=0.5) == "error:TimeoutError"


def test_declared_length_probe_reports_connection_error():
    assert REAL_PROBE("http://127.0.0.1:9", "k", 1, timeout=1).startswith("error:")


def test_run_fails_on_wrong_oversize_status(fake_clock):
    with respx.mock() as router:
        _mock(router, too_large=httpx.Response(200, json={"gueltig": True}, headers=JSON))
        result = smoke_remote.run(BASE, "k", ROOT / "fixtures")
    assert result["too_large"] == 200
    assert result["ok"] is False


def test_run_fails_when_call_without_key_is_accepted(fake_clock):
    with respx.mock() as router:
        router.get(f"{BASE}/health").mock(return_value=httpx.Response(200, json={"status": "ok"}))
        router.post(f"{BASE}/validate").mock(
            side_effect=[
                httpx.Response(200, json={"gueltig": True}, headers=JSON),
                httpx.Response(200, json={"gueltig": True}, headers=JSON),
                httpx.Response(200, json={"gueltig": True}, headers=JSON),
                httpx.Response(413),
            ]
        )
        result = smoke_remote.run(BASE, "k", ROOT / "fixtures")
    assert result["no_key"] == 200
    assert result["ok"] is False


def test_run_times_out_when_never_healthy(fake_clock):
    with respx.mock() as router:
        router.get(f"{BASE}/health").mock(return_value=httpx.Response(503, json={"status": "degraded"}))
        router.post(f"{BASE}/validate").mock(return_value=httpx.Response(401))
        result = smoke_remote.run(BASE, "k", ROOT / "fixtures", health_timeout_s=20)
    assert result["ok"] is False
    assert result["health"]["status"] == 503


def test_fixtures_exist():
    assert smoke_remote.UBL.name == "01.01a-INVOICE_ubl.xml"  # valid UBL, as used by tests/api
    assert (ROOT / "fixtures" / smoke_remote.UBL).is_file()
    assert (ROOT / "fixtures" / smoke_remote.PDF).is_file()


def test_main_junit_and_exit_code(fake_clock, tmp_path, monkeypatch, capsys):
    junit = tmp_path / "smoke.xml"
    monkeypatch.setenv("ERE_TEST_KEY", "very-secret-key")
    with respx.mock() as router:
        _mock(router)
        code = smoke_remote.main(["--base-url", BASE, "--key-env", "ERE_TEST_KEY", "--junit", str(junit)])
    assert code == 0
    assert 'failures="0"' in junit.read_text(encoding="utf-8")
    assert "very-secret-key" not in capsys.readouterr().out  # the key is never printed


def test_main_without_key_returns_2(monkeypatch):
    monkeypatch.delenv("ERE_TEST_KEY", raising=False)
    assert smoke_remote.main(["--base-url", BASE, "--key-env", "ERE_TEST_KEY"]) == 2
