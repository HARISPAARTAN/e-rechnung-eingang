from pathlib import Path

from erechnung.config import load_settings

ROOT = Path(__file__).resolve().parents[2]


def test_settings_from_config_toml(monkeypatch):
    monkeypatch.delenv("ERE_VALIDATOR_URL", raising=False)
    monkeypatch.delenv("ERE_API_KEY", raising=False)
    s = load_settings(ROOT)
    assert s.validator_version == "1.6.3" and s.config_release == "2026-08-31" and s.xrechnung_version == "3.0.2"
    assert s.daemon_port == 8081 and s.validator_url == "http://127.0.0.1:8081"
    assert s.timeout_s == 60.0 and s.max_upload_mb == 10 and s.api_key is None
    assert s.xpath_dir == ROOT / "src" / "erechnung" / "xpath"


def test_settings_env_overrides(monkeypatch):
    monkeypatch.setenv("ERE_VALIDATOR_URL", "http://validator:9000/")
    monkeypatch.setenv("ERE_API_KEY", "k")
    s = load_settings(ROOT)
    assert s.validator_url == "http://validator:9000"
    assert s.api_key == "k"
