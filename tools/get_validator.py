"""Download the KoSIT validator jar and the XRechnung configuration into .validator/ (git-ignored), pinned by SHA-256.

Usage: uv run python tools/get_validator.py [--print-sha]
With --print-sha the tool prints the checksums and exits 0 even when config.toml still says "pending".
"""

from __future__ import annotations

import hashlib
import sys
import urllib.request
import zipfile
from pathlib import Path

from erechnung.config import load_settings

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / ".validator"


def _fetch(url: str, path: Path) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        print(f"download {url}")
        urllib.request.urlretrieve(url, path)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    s = load_settings(ROOT)
    print_only = "--print-sha" in sys.argv
    jar_url = f"https://github.com/itplr-kosit/validator/releases/download/v{s.validator_version}/validator-{s.validator_version}-standalone.jar"
    cfg_url = (
        f"https://github.com/itplr-kosit/validator-configuration-xrechnung/releases/download/v{s.config_release}/"
        f"xrechnung-{s.xrechnung_version}-validator-configuration-{s.config_release}.zip"
    )
    jar_sha = _fetch(jar_url, TARGET / "validator.jar")
    cfg_sha = _fetch(cfg_url, TARGET / "config.zip")
    print(f"validator.jar sha256 {jar_sha}")
    print(f"config.zip    sha256 {cfg_sha}")
    if print_only:
        return
    mismatched = [
        (path, got, want)
        for path, got, want in ((TARGET / "validator.jar", jar_sha, s.validator_sha256), (TARGET / "config.zip", cfg_sha, s.config_sha256))
        if got != want
    ]
    if mismatched:
        for path, got, want in mismatched:
            print(f"checksum mismatch: {path} has sha256 {got}, config.toml expects {want}", file=sys.stderr)
        stale = [str(p) for p in (TARGET / "validator.jar", TARGET / "config.zip", TARGET / "config")]
        print(
            "If config.toml was bumped to a new version, the cached files are the old release; delete them and rerun:\n  "
            + "\n  ".join(stale),
            file=sys.stderr,
        )
        sys.exit(1)
    cfg_dir = TARGET / "config"
    if not (cfg_dir / "scenarios.xml").exists():
        with zipfile.ZipFile(TARGET / "config.zip") as zf:
            zf.extractall(cfg_dir)
        inner = [p for p in cfg_dir.iterdir() if p.is_dir() and (p / "scenarios.xml").exists()]
        if not (cfg_dir / "scenarios.xml").exists() and inner:
            for item in inner[0].iterdir():
                item.rename(cfg_dir / item.name)
    print("ready:", TARGET / "validator.jar", cfg_dir / "scenarios.xml")


if __name__ == "__main__":
    main()
