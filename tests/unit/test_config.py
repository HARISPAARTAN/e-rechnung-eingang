import shutil
from pathlib import Path

import pytest

from erechnung.config import load_settings

ROOT = Path(__file__).resolve().parents[2]
ENV = ("ERE_VALIDATOR_URL", "ERE_VALIDATOR_PORT", "ERE_API_KEY", "ERE_AUTH_DISABLED", "ERE_HTML_MAX_CHARS", "ERE_ROOT")


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in ENV:
        monkeypatch.delenv(name, raising=False)


def test_settings_from_config_toml():
    s = load_settings(ROOT)
    assert s.validator_version == "1.6.3" and s.config_release == "2026-08-31" and s.xrechnung_version == "3.0.2"
    assert s.daemon_port == 8081 and s.validator_url == "http://127.0.0.1:8081"
    assert s.timeout_s == 60.0 and s.max_upload_mb == 10 and s.api_key is None
    assert s.xpath_dir == ROOT / "src" / "erechnung" / "xpath"
    assert s.auth_disabled is False and s.auth_active is False and s.html_max_chars == 1_000_000


def test_settings_env_overrides(monkeypatch):
    monkeypatch.setenv("ERE_VALIDATOR_URL", "http://validator:9000/")
    monkeypatch.setenv("ERE_API_KEY", "geheim-4711")
    monkeypatch.setenv("ERE_HTML_MAX_CHARS", "500")
    s = load_settings(ROOT)
    assert s.validator_url == "http://validator:9000"
    assert s.api_key == "geheim-4711" and s.auth_active is True and s.html_max_chars == 500
    assert "geheim-4711" not in repr(s)


def test_validator_port_from_environment(monkeypatch):
    monkeypatch.setenv("ERE_VALIDATOR_PORT", "9123")
    s = load_settings(ROOT)
    assert s.daemon_port == 9123 and s.validator_url == "http://127.0.0.1:9123"


@pytest.mark.parametrize("value,expected", [("1", True), ("true", True), ("Yes", True), ("0", False), ("", False), ("no", False)])
def test_auth_disabled_flag(monkeypatch, value, expected):
    monkeypatch.setenv("ERE_AUTH_DISABLED", value)
    assert load_settings(ROOT).auth_disabled is expected


def test_load_settings_honours_ere_root(monkeypatch, tmp_path):
    shutil.copy(ROOT / "config.toml", tmp_path / "config.toml")
    text = (tmp_path / "config.toml").read_text(encoding="utf-8").replace("max_upload_mb = 10", "max_upload_mb = 3")
    (tmp_path / "config.toml").write_text(text, encoding="utf-8")
    monkeypatch.setenv("ERE_ROOT", str(tmp_path))
    s = load_settings()
    assert s.root == tmp_path.resolve() and s.max_upload_mb == 3
    assert s.xpath_dir == tmp_path.resolve() / "src" / "erechnung" / "xpath"


def test_default_root_is_the_source_tree():
    assert load_settings().root == ROOT
