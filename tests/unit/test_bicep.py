"""deploy/containerapp.bicep compiles (needs the Azure CLI; CI has it) and carries the agreed probe and resource settings."""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
BICEP = ROOT / "deploy" / "containerapp.bicep"
PARAMS = ROOT / "deploy" / "containerapp.parameters.json"


@pytest.fixture(scope="module")
def arm() -> dict:
    az = shutil.which("az")
    if az is None:
        if os.environ.get("CI"):
            pytest.fail("Azure CLI (az) missing on the CI runner")
        pytest.skip("Azure CLI (az) not installed locally; the CI job 'bicep' runs this test")
    done = subprocess.run(
        [az, "bicep", "build", "--file", str(BICEP), "--stdout"],
        capture_output=True, text=True, encoding="utf-8", timeout=300,
    )
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def _resource(arm: dict, type_: str) -> dict:
    resources = arm["resources"]
    if isinstance(resources, dict):  # languageVersion 2.0 symbolic names
        resources = list(resources.values())
    return next(r for r in resources if r["type"] == type_)


@pytest.fixture
def app(arm) -> dict:
    return _resource(arm, "Microsoft.App/containerApps")


@pytest.fixture
def container(app) -> dict:
    (container,) = app["properties"]["template"]["containers"]
    return container


def _probes(container) -> dict:
    return {p["type"]: p for p in container["probes"]}


def test_three_health_probes(container):
    probes = _probes(container)
    assert set(probes) == {"Startup", "Liveness", "Readiness"}
    for probe in probes.values():
        assert probe["httpGet"] == {"path": "/health", "port": 8080}


def test_liveness_failure_threshold(container):
    assert _probes(container)["Liveness"]["failureThreshold"] == 3


def test_startup_allows_three_minutes(container):
    startup = _probes(container)["Startup"]
    assert startup["periodSeconds"] * startup["failureThreshold"] >= 180


def _param(arm: dict, ref: str):
    """Resolve "[parameters('x')]" to the value the parameters file sets, else the template default."""
    key = ref.removeprefix("[parameters('").removesuffix("')]")
    given = json.loads(PARAMS.read_text(encoding="utf-8"))["parameters"]
    return given[key]["value"] if key in given else arm["parameters"][key]["defaultValue"]


def test_scale_to_zero(arm, app):
    assert _param(arm, app["properties"]["template"]["scale"]["minReplicas"]) == 0


def test_resources(container):
    resources = container["resources"]
    assert resources["cpu"] == "[json('1.0')]"  # cpu is a decimal; Bicep compiles json('1.0') this way
    assert resources["memory"] == "2Gi"


def test_api_key_comes_from_secret(app, container):
    env = {e["name"]: e for e in container["env"]}
    assert env["ERE_API_KEY"] == {"name": "ERE_API_KEY", "secretRef": "api-key"}
    assert "value" not in env["ERE_API_KEY"]
    assert "ERE_AUTH_DISABLED" not in env
    secrets = {s["name"] for s in app["properties"]["configuration"]["secrets"]}
    assert secrets == {"api-key"}


def test_external_ingress_on_8080(app):
    ingress = app["properties"]["configuration"]["ingress"]
    assert ingress["external"] is True
    assert ingress["targetPort"] == 8080
    assert ingress["allowInsecure"] is False


def test_outputs(arm):
    assert {"fqdn", "appName"} <= set(arm["outputs"])
