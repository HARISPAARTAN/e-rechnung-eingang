"""tools/smoke_remote.py against a mocked service (respx); no network."""

from pathlib import Path

import httpx
import pytest
import respx

from tools import smoke_remote

ROOT = Path(__file__).resolve().parents[2]
BASE = "https://ca-erechnung.example.azurecontainerapps.io"
JSON = {"content-type": "application/json"}


@pytest.fixture
def fake_clock(monkeypatch):
    """Replace the clock: sleeping advances it, so the measured cold start is deterministic."""
    now = [1000.0]
    monkeypatch.setattr(smoke_remote.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(smoke_remote.time, "sleep", lambda s: now.__setitem__(0, now[0] + s))
    return now


def _mock(router, *, ubl_status=200):
    router.get(f"{BASE}/health").mock(
        side_effect=[
            httpx.Response(503, json={"status": "degraded"}),
            httpx.Response(200, json={"status": "ok"}),
        ]
    )
    router.post(f"{BASE}/validate").mock(
        side_effect=[
            httpx.Response(401, json={"detail": "unauthorized"}),
            httpx.Response(ubl_status, json={"gueltig": True}, headers=JSON),
            httpx.Response(200, json={"gueltig": True}, headers=JSON),
            httpx.Response(413, json={"detail": "too large"}),
        ]
    )


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
