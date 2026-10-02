"""Exercise rollout failure boundaries without connecting to a server or registry."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

DEPLOY = Path(__file__).resolve().parents[1] / "deploy"
IMAGE = "ghcr.io/isaiahmcnealy/athena@sha256:" + "a" * 64


@pytest.fixture
def deployment(tmp_path):
    root = tmp_path / "server"
    release = root / "releases" / "new"
    release.mkdir(parents=True)
    for name in ("deploy.sh", "manage.sh", "compose.yaml"):
        shutil.copy(DEPLOY / name, release / name)
    (root / ".env").write_text("POSTGRES_PASSWORD=" + "b" * 64 + "\n")
    old = root / "releases" / "old"
    old.mkdir()
    (root / "current").symlink_to(old, target_is_directory=True)
    tools = tmp_path / "bin"
    tools.mkdir()
    fake_docker = tools / "docker"
    fake_docker.write_text(
        "#!/usr/bin/env bash\n"
        'printf "%s\\n" "$*" >> "$DOCKER_LOG"\n'
        'if [[ -n "${FAIL_COMMAND:-}" && "$*" == *"$FAIL_COMMAND"* ]]; then exit 42; fi\n'
        'if [[ "$*" == *pg_dump* ]]; then printf "backup fixture"; fi\n'
    )
    fake_docker.chmod(0o755)
    env = {
        **os.environ,
        "PATH": f"{tools}:{os.environ['PATH']}",
        "ATHENA_DEPLOY_ROOT": str(root),
        "DOCKER_LOG": str(tmp_path / "docker.log"),
        "FAIL_COMMAND": "",
    }
    return root, release, env


def run_deploy(deployment, image=IMAGE):
    _, release, env = deployment
    return subprocess.run(
        ["bash", str(release / "deploy.sh"), image], env=env, capture_output=True, text=True
    )


def test_success_records_release_only_after_backup_and_readiness(deployment):
    root, release, env = deployment
    result = run_deploy(deployment)
    assert result.returncode == 0, result.stderr
    assert (root / "current").resolve() == release
    assert (root / "previous").resolve().name == "old"
    assert (release / "image").read_text().strip() == IMAGE
    backups = list((root / "backups").glob("*.dump"))
    assert len(backups) == 1
    assert backups[0].read_text() == "backup fixture"
    log = Path(env["DOCKER_LOG"]).read_text()
    assert log.index("pg_dump") < log.index("run --rm --no-deps migrate")
    assert log.index("run --rm --no-deps migrate") < log.index("--wait-timeout 120 web")
    assert not (root / ".deploy-lock").exists()
    manage = subprocess.run(
        ["bash", str(root / "current/manage.sh"), "ps"], env=env, capture_output=True
    )
    assert manage.returncode == 0
    assert str(release / "compose.yaml") in Path(env["DOCKER_LOG"]).read_text().splitlines()[-1]


@pytest.mark.parametrize("failure", ["pull web", "pg_dump", "run --rm --no-deps migrate"])
def test_failure_before_rollout_preserves_running_app(deployment, failure):
    root, release, env = deployment
    env["FAIL_COMMAND"] = failure
    assert run_deploy(deployment).returncode != 0
    assert "--wait-timeout 120 web" not in Path(env["DOCKER_LOG"]).read_text()
    assert (root / "current").resolve().name == "old"
    assert not (release / "image").exists()
    assert not (root / ".deploy-lock").exists()
    if failure == "pg_dump":
        assert not list((root / "backups").glob("*.dump"))


@pytest.mark.parametrize("failure", ["--wait-timeout 120 web", "/api/papers"])
def test_unhealthy_rollout_is_not_recorded_as_successful(deployment, failure):
    root, release, env = deployment
    env["FAIL_COMMAND"] = failure
    assert run_deploy(deployment).returncode != 0
    assert (root / "current").resolve().name == "old"
    assert not (release / "image").exists()
    assert not (root / ".deploy-lock").exists()


def test_concurrent_deployment_does_not_remove_existing_lock(deployment):
    root, _, env = deployment
    (root / ".deploy-lock").mkdir()
    assert run_deploy(deployment).returncode != 0
    assert (root / ".deploy-lock").is_dir()
    assert not Path(env["DOCKER_LOG"]).exists()


@pytest.mark.parametrize("image", ["ghcr.io/owner/app:latest", "invalid; touch unexpected"])
def test_requires_immutable_image_before_touching_server(deployment, image):
    _, _, env = deployment
    assert run_deploy(deployment, image).returncode != 0
    assert not Path(env["DOCKER_LOG"]).exists()


def test_rejects_placeholder_password_before_touching_server(deployment):
    root, _, env = deployment
    shutil.copy(DEPLOY / ".env.example", root / ".env")
    assert run_deploy(deployment).returncode != 0
    assert not Path(env["DOCKER_LOG"]).exists()
