"""Download the official example invoices once and copy the selected files into fixtures/.

Usage: uv run python tools/get_fixtures.py
Sources: XRechnung test suite v2026-08-31 (Apache 2.0) and the ZUGFeRD corpus (Apache 2.0).
"""

from __future__ import annotations

import hashlib
import shutil
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOWNLOADS = ROOT / "fixtures" / "_downloads"
TESTSUITE_URL = (
    "https://github.com/itplr-kosit/xrechnung-testsuite/releases/download/v2026-08-31/"
    "xrechnung-3.0.2-testsuite-2026-08-31.zip"
)
TESTSUITE_FILES = [
    "01.01a-INVOICE_ubl.xml",
    "01.01a-INVOICE_uncefact.xml",
    "01.02a-INVOICE_ubl.xml",
    "01.02a-INVOICE_uncefact.xml",
]
CORPUS_BASE = "https://raw.githubusercontent.com/ZUGFeRD/corpus/master/XML-Rechnung/FX/"
CORPUS_FILES = ["EN16931_Einfach.pdf", "XRECHNUNG_Einfach.pdf"]


def download(url: str, target: Path) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        print(f"download {url}")
        urllib.request.urlretrieve(url, target)
    print(f"{target.name}: sha256 {hashlib.sha256(target.read_bytes()).hexdigest()}")
    return target


def main() -> None:
    zip_path = download(TESTSUITE_URL, DOWNLOADS / "xrechnung-testsuite.zip")
    out = ROOT / "fixtures" / "xrechnung"
    out.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as zf:
        members = {Path(m).name: m for m in zf.namelist() if m.endswith(".xml")}
        for name in TESTSUITE_FILES:
            member = members[name]
            (out / name).write_bytes(zf.read(member))
            print(f"copied {member} -> fixtures/xrechnung/{name}")
    corpus = ROOT / "fixtures" / "zugferd" / "corpus"
    corpus.mkdir(parents=True, exist_ok=True)
    for name in CORPUS_FILES:
        src = download(CORPUS_BASE + name, DOWNLOADS / name)
        shutil.copyfile(src, corpus / name)
        print(f"copied {name} -> fixtures/zugferd/corpus/{name}")


if __name__ == "__main__":
    main()
