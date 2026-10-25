"""deploy/github-oidc.sh is an owner script and is never run in CI; these checks pin the two OIDC subject forms."""

import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "deploy" / "github-oidc.sh"


@pytest.fixture(scope="module")
def text() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def test_creates_both_subject_forms(text):
    # names only, and the numeric-id form GitHub presents (AADSTS700213 on the first real deploy)
    assert 'SUBJECT_NAMES="repo:${REPO}:environment:production"' in text
    assert 'SUBJECT_IDS="repo:${OWNER}@${OWNER_ID}/${NAME}@${REPO_ID}:environment:production"' in text
    assert 'ensure_credential "github-production" "$SUBJECT_NAMES"' in text
    assert 'ensure_credential "github-production-ids" "$SUBJECT_IDS"' in text


def test_reads_numeric_ids_from_github(text):
    assert "gh api" in text
    assert "--jq '.owner.id'" in text
    assert "--jq '.id'" in text


def test_credentials_are_created_only_when_missing(text):
    assert "federated-credential list" in text
    assert text.count("federated-credential create") == 1  # one place, called per subject


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash not available")
def test_syntax_is_valid():
    # the resolved path: on Windows a bare "bash" can pick the WSL launcher instead of Git Bash
    subprocess.run([shutil.which("bash"), "-n", SCRIPT.name], check=True, cwd=SCRIPT.parent)
