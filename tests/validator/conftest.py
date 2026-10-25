"""Validator daemon for integration tests.

With ERE_VALIDATOR_URL set, that daemon is used (for example the Docker container from the README); if it does not
answer UP, the session fails instead of skipping. Without it the jar is started with a local java; in CI (CI set) a
missing java or jar is a failure too, elsewhere a skip.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[2]
JAR = ROOT / ".validator" / "validator.jar"
CONFIG = ROOT / ".validator" / "config"


def _is_up(url: str) -> bool:
    try:
        resp = httpx.get(f"{url}/server/health", timeout=3.0)
    except httpx.HTTPError:
        return False
    return resp.status_code == 200 and b"UP" in resp.content


def _wait(url: str, seconds: int, proc: subprocess.Popen | None = None) -> str | None:
    """None when the daemon is UP, else the reason it is not."""
    deadline = time.time() + seconds
    while time.time() < deadline:
        if proc is not None and proc.poll() is not None:
            return f"java exited early with code {proc.returncode}"
        if _is_up(url):
            return None
        time.sleep(1)
    return f"no UP from {url}/server/health within {seconds} s"


@pytest.fixture(scope="session")
def validator_url():
    url = os.environ.get("ERE_VALIDATOR_URL")
    if url:
        url = url.rstrip("/")
        reason = _wait(url, 30)
        if reason:
            pytest.fail(f"ERE_VALIDATOR_URL is set but the daemon is not usable: {reason}")
        yield url
        return
    if not shutil.which("java") or not JAR.exists():
        message = "set ERE_VALIDATOR_URL or install java and run tools/get_validator.py"
        if os.environ.get("CI"):
            pytest.fail(message)
        pytest.skip(message)
    port = int(os.environ.get("ERE_TEST_PORT", "8089"))
    proc = subprocess.Popen(
        ["java", "-jar", str(JAR), "-s", str(CONFIG / "scenarios.xml"), "-r", str(CONFIG), "-D", "-H", "127.0.0.1", "-P", str(port), "--disable-gui"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    url = f"http://127.0.0.1:{port}"
    reason = _wait(url, 90, proc)
    if reason:
        proc.terminate()
        pytest.fail(f"validator daemon did not become healthy: {reason}")
    yield url
    proc.terminate()
    proc.wait(timeout=30)
