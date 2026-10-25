"""Validator daemon for integration tests: use ERE_VALIDATOR_URL if set, else start the jar with java."""

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


def _wait(url: str, seconds: int = 90) -> bool:
    deadline = time.time() + seconds
    while time.time() < deadline:
        try:
            if httpx.get(f"{url}/server/health", timeout=3.0).status_code == 200:
                return True
        except httpx.HTTPError:
            pass
        time.sleep(2)
    return False


@pytest.fixture(scope="session")
def validator_url():
    url = os.environ.get("ERE_VALIDATOR_URL")
    if url:
        if not _wait(url.rstrip("/"), 15):
            pytest.skip(f"no validator at {url}")
        yield url.rstrip("/")
        return
    if not shutil.which("java") or not JAR.exists():
        pytest.skip("set ERE_VALIDATOR_URL or install java and run tools/get_validator.py")
    port = int(os.environ.get("ERE_TEST_PORT", "8089"))
    proc = subprocess.Popen(
        ["java", "-jar", str(JAR), "-s", str(CONFIG / "scenarios.xml"), "-r", str(CONFIG), "-D", "-H", "127.0.0.1", "-P", str(port), "--disable-gui"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    url = f"http://127.0.0.1:{port}"
    if not _wait(url):
        proc.terminate()
        pytest.fail("validator daemon did not become healthy")
    yield url
    proc.terminate()
    proc.wait(timeout=30)
