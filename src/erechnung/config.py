"""Typed settings: config.toml for versions and limits, environment variables for URLs, ports and secrets."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

_TRUE = {"1", "true", "yes"}


@dataclass(frozen=True)
class Settings:
    root: Path
    validator_version: str
    validator_sha256: str
    config_release: str
    config_sha256: str
    xrechnung_version: str
    daemon_port: int
    validator_url: str
    timeout_s: float
    max_upload_mb: int
    api_key: str | None = field(repr=False, default=None)
    xpath_dir: Path = Path(".")
    auth_disabled: bool = False
    html_max_chars: int = 1_000_000

    @property
    def auth_active(self) -> bool:
        """A configured key is always enforced; ERE_AUTH_DISABLED only matters when no key is set."""
        return bool(self.api_key)


def _default_root() -> Path:
    env = os.environ.get("ERE_ROOT")
    return Path(env) if env else Path(__file__).resolve().parents[2]


def load_settings(root: Path | None = None) -> Settings:
    root = (root or _default_root()).resolve()
    data = tomllib.loads((root / "config.toml").read_text(encoding="utf-8"))
    v, s = data["validator"], data["service"]
    port = int(os.environ.get("ERE_VALIDATOR_PORT") or v["daemon_port"])
    url = os.environ.get("ERE_VALIDATOR_URL") or f"http://127.0.0.1:{port}"
    return Settings(
        root=root,
        validator_version=str(v["version"]),
        validator_sha256=str(v["jar_sha256"]),
        config_release=str(v["config_release"]),
        config_sha256=str(v["config_sha256"]),
        xrechnung_version=str(v["xrechnung_version"]),
        daemon_port=port,
        validator_url=url.rstrip("/"),
        timeout_s=float(v["timeout_s"]),
        max_upload_mb=int(s["max_upload_mb"]),
        api_key=os.environ.get("ERE_API_KEY") or None,
        xpath_dir=root / "src" / "erechnung" / "xpath",
        auth_disabled=os.environ.get("ERE_AUTH_DISABLED", "").strip().lower() in _TRUE,
        html_max_chars=int(os.environ.get("ERE_HTML_MAX_CHARS") or 1_000_000),
    )
