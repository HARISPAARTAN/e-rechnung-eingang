"""One source for the validator pins: Dockerfile ARG defaults and the daemon port must agree with config.toml."""

import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE = (ROOT / "Dockerfile").read_text(encoding="utf-8")
ENTRYPOINT = (ROOT / "docker" / "entrypoint.sh").read_text(encoding="utf-8")
CONFIG = tomllib.loads((ROOT / "config.toml").read_text(encoding="utf-8"))["validator"]


def _args() -> dict[str, str]:
    return dict(re.findall(r"^ARG (\w+)=(\S+)$", DOCKERFILE, flags=re.M))


def test_dockerfile_arg_defaults_equal_config_toml():
    args = _args()
    assert args == {
        "VALIDATOR_VERSION": CONFIG["version"],
        "VALIDATOR_SHA256": CONFIG["jar_sha256"],
        "CONFIG_RELEASE": CONFIG["config_release"],
        "XRECHNUNG_VERSION": CONFIG["xrechnung_version"],
        "CONFIG_SHA256": CONFIG["config_sha256"],
    }


def test_daemon_port_has_one_source_in_the_image():
    port = str(CONFIG["daemon_port"])
    assert re.findall(r"ERE_VALIDATOR_PORT=(\d+)", DOCKERFILE) == [port]
    standalone = rf"\b{port}\b"  # word boundaries keep digests out of the count
    assert len(re.findall(standalone, DOCKERFILE)) == 1, "the port number must appear only in ENV ERE_VALIDATOR_PORT"
    assert not re.search(standalone, ENTRYPOINT)
    assert '-P "${ERE_VALIDATOR_PORT}"' in ENTRYPOINT and "${ERE_VALIDATOR_PORT}/server/health" in ENTRYPOINT
    assert "ERE_VALIDATOR_URL" not in DOCKERFILE  # settings derive the URL from ERE_VALIDATOR_PORT


def test_settings_read_the_port_from_the_environment(monkeypatch):
    from erechnung.config import load_settings

    monkeypatch.delenv("ERE_VALIDATOR_URL", raising=False)
    monkeypatch.setenv("ERE_VALIDATOR_PORT", "18081")
    assert load_settings(ROOT).validator_url == "http://127.0.0.1:18081"
