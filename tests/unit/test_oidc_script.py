"""deploy/github-oidc.sh is an owner script and is never run against Entra in CI. These tests run it with stub `az`
and `gh` executables on PATH (bash scripts that log their arguments and keep a tiny state in a temp directory)."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "deploy" / "github-oidc.sh"
BASH = shutil.which(
    "bash"
)  # the resolved path: on Windows a bare "bash" can pick the WSL launcher instead of Git Bash
OWNER_ID, REPO_ID = "81414581", "1432721171"
SUBJECT_NAMES = "repo:HARISPAARTAN/e-rechnung-eingang:environment:production"
SUBJECT_IDS = f"repo:HARISPAARTAN@{OWNER_ID}/e-rechnung-eingang@{REPO_ID}:environment:production"

pytestmark = pytest.mark.skipif(BASH is None, reason="bash not available")

AZ_STUB = r"""#!/usr/bin/env bash
echo "az $*" >> "$STUB_DIR/az.log"
case "$1 $2 $3" in
  "account show "*) if [[ "$*" == *tenantId* ]]; then echo tenant-1; else echo sub-1; fi ;;
  "ad app list"*) [ -f "$STUB_DIR/app" ] && echo app-1 || true ;;
  "ad app create"*) touch "$STUB_DIR/app"; echo app-1 ;;
  "ad sp create"*) ;;
  "ad app show"*) echo obj-1 ;;
  "ad app federated-credential")
    if [ "$4" = "list" ]; then
      [[ "$*" =~ name==\'([^\']+)\' ]] || exit 3
      name="${BASH_REMATCH[1]}"
      if [[ "$*" == *length* ]]; then
        [ -f "$STUB_DIR/cred-$name" ] && echo 1 || echo 0
      else
        cat "$STUB_DIR/cred-$name"
      fi
    elif [ "$4" = "create" ]; then
      all="$*"; file="${all#*@}"; file="${file%% *}"
      name=$(sed -n 's/.*"name":"\([^"]*\)".*/\1/p' "$file")
      sed -n 's/.*"subject":"\([^"]*\)".*/\1/p' "$file" > "$STUB_DIR/cred-$name"
    fi ;;
  "role assignment list"*) [ -f "$STUB_DIR/role" ] && echo 1 || echo 0 ;;
  "role assignment create"*) touch "$STUB_DIR/role" ;;
  *) echo "unexpected az call: $*" >&2; exit 9 ;;
esac
"""

GH_STUB = r"""#!/usr/bin/env bash
echo "gh $*" >> "$STUB_DIR/gh.log"
case "${GH_MODE:-ok}" in
  ok) echo 81414581; echo 1432721171 ;;
  unauth) echo "gh: To get started with GitHub CLI, please run: gh auth login" >&2; exit 4 ;;
  null) echo null; echo null ;;
  empty) ;;
esac
"""


@pytest.fixture
def env(tmp_path):
    stubs = tmp_path / "bin"
    state = tmp_path / "state"
    work = tmp_path / "work"
    for d in (stubs, state, work):
        d.mkdir()
    for name, body in (("az", AZ_STUB), ("gh", GH_STUB)):
        (stubs / name).write_text(body, encoding="utf-8", newline="\n")
        (stubs / name).chmod(0o755)  # Linux needs the execute bit (Windows ignores it)
    return {"stubs": stubs, "state": state, "work": work}


def run_script(env, gh_mode="ok"):
    e = dict(os.environ)
    e["PATH"] = f"{env['stubs']}{os.pathsep}{e['PATH']}"
    e["STUB_DIR"] = str(env["state"])
    e["GH_MODE"] = gh_mode
    return subprocess.run(
        [BASH, str(SCRIPT)], cwd=env["work"], env=e, capture_output=True, text=True, timeout=60
    )


def log(env, name):
    f = env["state"] / f"{name}.log"
    return f.read_text(encoding="utf-8") if f.exists() else ""


def test_fresh_run_creates_app_both_credentials_and_role(env):
    r = run_script(env)
    assert r.returncode == 0, r.stderr
    assert (env["state"] / "cred-github-production").read_text().strip() == SUBJECT_NAMES
    assert (env["state"] / "cred-github-production-ids").read_text().strip() == SUBJECT_IDS
    assert (env["state"] / "role").exists()
    assert "az ad app create" in log(env, "az")
    assert "AZURE_CLIENT_ID=app-1" in r.stdout
    assert "gh api repos/HARISPAARTAN/e-rechnung-eingang --jq .owner.id, .id" in log(env, "gh")
    assert log(env, "gh").count("gh api") == 1
    assert not (env["work"] / "deploy" / ".secrets" / "federated-credential.json").exists()


def test_rerun_is_idempotent(env):
    assert run_script(env).returncode == 0
    before = log(env, "az")
    r = run_script(env)
    assert r.returncode == 0, r.stderr
    new_calls = log(env, "az")[len(before) :]
    assert "federated-credential create" not in new_calls
    assert "ad app create" not in new_calls
    assert "role assignment create" not in new_calls
    assert r.stdout.count("existiert bereits") == 3


def test_stale_subject_fails_loudly_with_both_values_and_the_remedy(env):
    assert run_script(env).returncode == 0
    (env["state"] / "cred-github-production-ids").write_text(
        "repo:OLDOWNER@1/old-repo@2:environment:production\n"
    )
    r = run_script(env)
    assert r.returncode != 0
    assert "repo:OLDOWNER@1/old-repo@2:environment:production" in r.stderr
    assert SUBJECT_IDS in r.stderr
    assert "federated-credential delete" in r.stderr
    # the credential is neither silently accepted nor overwritten
    assert (env["state"] / "cred-github-production-ids").read_text().strip().startswith("repo:OLDOWNER")


def test_unauthenticated_gh_fails_before_az_is_called(env):
    r = run_script(env, gh_mode="unauth")
    assert r.returncode != 0
    assert log(env, "az") == ""
    assert not (env["state"] / "app").exists()


@pytest.mark.parametrize("mode", ["null", "empty"])
def test_missing_ids_fail_closed_before_az_is_called(env, mode):
    r = run_script(env, gh_mode=mode)
    assert r.returncode != 0
    assert "Abbruch" in r.stderr
    assert log(env, "az") == ""


def test_credential_file_is_removed_when_the_script_aborts(env):
    assert run_script(env).returncode == 0
    (env["state"] / "cred-github-production").write_text("repo:x\n")
    assert run_script(env).returncode != 0
    assert not (env["work"] / "deploy" / ".secrets" / "federated-credential.json").exists()


def test_syntax_is_valid():
    subprocess.run([BASH, "-n", SCRIPT.name], check=True, cwd=SCRIPT.parent)
