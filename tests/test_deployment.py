"""Exercise rollout failure boundaries without connecting to a server or registry."""

import os
import re
import shutil
import subprocess
import time
from pathlib import Path

import pytest

DEPLOY = Path(__file__).resolve().parents[1] / "deploy"
IMAGE = "ghcr.io/isaiahmcnealy/athena@sha256:" + "a" * 64
RELEASE_FILES = (
    "deploy.sh",
    "manage.sh",
    "compose.yaml",
    "roles.sql",
    "Caddyfile",
    "backup.sh",
    "refresh.sh",
)
SERVER_ENV = {
    "POSTGRES_PASSWORD": "b" * 64,
    "ATHENA_WEB_DB_PASSWORD": "c" * 64,
    "ATHENA_INGEST_DB_PASSWORD": "d" * 64,
    "ATHENA_DOMAIN": "athena.example.com",
}


def write_env(root, **changes):
    values = {**SERVER_ENV, **changes}
    lines = [f"{name}={value}\n" for name, value in values.items() if value is not None]
    (root / ".env").write_text("".join(lines))


@pytest.fixture
def deployment(tmp_path):
    root = tmp_path / "server"
    release = root / "releases" / "new"
    release.mkdir(parents=True)
    for name in RELEASE_FILES:
        shutil.copy(DEPLOY / name, release / name)
    write_env(root)
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
        'if [[ "$*" == *pg_dump* && -z "${EMPTY_DUMP:-}" ]]; then printf "backup fixture"; fi\n'
    )
    fake_docker.chmod(0o755)
    fake_aws = tools / "aws"
    fake_aws.write_text('#!/usr/bin/env bash\nprintf "%s\\n" "$*" >> "$AWS_LOG"\n')
    fake_aws.chmod(0o755)
    env = {
        **os.environ,
        "PATH": f"{tools}:{os.environ['PATH']}",
        "ATHENA_DEPLOY_ROOT": str(root),
        "DOCKER_LOG": str(tmp_path / "docker.log"),
        "AWS_LOG": str(tmp_path / "aws.log"),
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
    steps = [
        "pg_dump",
        "run --rm --no-deps migrate",
        "psql -U athena",
        "--wait-timeout 120 web",
        "/api/papers",
        "--wait-timeout 120 caddy",
    ]
    assert [log.index(step) for step in steps] == sorted(log.index(step) for step in steps)
    assert not (root / ".deploy-lock").exists()
    manage = subprocess.run(
        ["bash", str(root / "current/manage.sh"), "ps"], env=env, capture_output=True
    )
    assert manage.returncode == 0
    assert str(release / "compose.yaml") in Path(env["DOCKER_LOG"]).read_text().splitlines()[-1]


@pytest.mark.parametrize(
    "failure", ["pull web", "pg_dump", "run --rm --no-deps migrate", "psql -U athena"]
)
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


@pytest.mark.parametrize(
    "failure", ["--wait-timeout 120 web", "/api/papers", "--wait-timeout 120 caddy"]
)
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


@pytest.mark.parametrize(
    "changes",
    [
        {"ATHENA_WEB_DB_PASSWORD": None},
        {"ATHENA_INGEST_DB_PASSWORD": "not-hex"},
        {"ATHENA_DOMAIN": None},
        {"ATHENA_DOMAIN": "https://athena.example.com"},
    ],
)
def test_rejects_incomplete_server_settings_before_touching_server(deployment, changes):
    root, _, env = deployment
    write_env(root, **changes)
    assert run_deploy(deployment).returncode != 0
    assert not Path(env["DOCKER_LOG"]).exists()


def test_rejects_release_without_role_definitions(deployment):
    _, release, env = deployment
    (release / "roles.sql").unlink()
    assert run_deploy(deployment).returncode != 0
    assert not Path(env["DOCKER_LOG"]).exists()


def run_job(deployment, script):
    """Run a scheduled job the way cron does: through the last successful release."""
    root, release, env = deployment
    (release / "image").write_text(IMAGE + "\n")
    (root / "current").unlink()
    (root / "current").symlink_to(release, target_is_directory=True)
    return subprocess.run(
        ["bash", str(root / "current" / script)], env=env, capture_output=True, text=True
    )


def test_scheduled_backup_writes_a_dump_and_prunes_only_old_scheduled_copies(deployment):
    root, _, env = deployment
    backups = root / "backups"
    backups.mkdir()
    month_ago = time.time() - 30 * 86400
    for name in ("scheduled-old.dump", "20260101T000000Z-release.dump"):
        (backups / name).write_text("old")
        os.utime(backups / name, (month_ago, month_ago))
    result = run_job(deployment, "backup.sh")
    assert result.returncode == 0, result.stderr
    names = sorted(path.name for path in backups.iterdir())
    assert len(names) == 2 and names[0] == "20260101T000000Z-release.dump"
    assert (backups / names[1]).read_text() == "backup fixture"
    assert not Path(env["AWS_LOG"]).exists()


def test_scheduled_backup_copies_off_host_when_configured(deployment):
    root, _, env = deployment
    write_env(root, BACKUP_S3_URI="s3://example-bucket/athena/")
    result = run_job(deployment, "backup.sh")
    assert result.returncode == 0, result.stderr
    upload = Path(env["AWS_LOG"]).read_text()
    assert upload.startswith("s3 cp --only-show-errors ")
    assert " s3://example-bucket/athena/scheduled-" in upload


@pytest.mark.parametrize("problem", [{"FAIL_COMMAND": "pg_dump"}, {"EMPTY_DUMP": "1"}])
def test_failed_or_empty_dump_is_not_kept_or_uploaded(deployment, problem):
    root, _, env = deployment
    write_env(root, BACKUP_S3_URI="s3://example-bucket/athena")
    env.update(problem)
    assert run_job(deployment, "backup.sh").returncode != 0
    assert not list((root / "backups").iterdir())
    assert not Path(env["AWS_LOG"]).exists()


def test_backup_rejects_a_destination_that_is_not_an_s3_uri(deployment):
    root, _, env = deployment
    write_env(root, BACKUP_S3_URI="example-bucket; touch unexpected")
    assert run_job(deployment, "backup.sh").returncode != 0
    assert not Path(env["DOCKER_LOG"]).exists()


def test_scheduled_refresh_imports_every_topic_and_releases_its_lock(deployment):
    root, _, env = deployment
    write_env(root, REFRESH_PER_QUERY="25")
    result = run_job(deployment, "refresh.sh")
    assert result.returncode == 0, result.stderr
    command = Path(env["DOCKER_LOG"]).read_text().splitlines()[-1]
    assert command.endswith("run --rm -T --no-deps ingest seed --per-query 25")
    assert not (root / ".refresh-lock").exists()


def test_refresh_skips_during_a_deployment_and_refuses_to_overlap(deployment):
    root, _, env = deployment
    (root / ".deploy-lock").mkdir()
    assert run_job(deployment, "refresh.sh").returncode == 0
    (root / ".deploy-lock").rmdir()
    (root / ".refresh-lock").mkdir()
    assert run_job(deployment, "refresh.sh").returncode != 0
    assert (root / ".refresh-lock").is_dir()
    assert not Path(env["DOCKER_LOG"]).exists()


def test_refresh_rejects_an_out_of_range_size(deployment):
    root, _, env = deployment
    write_env(root, REFRESH_PER_QUERY="5000")
    assert run_job(deployment, "refresh.sh").returncode != 0
    assert not Path(env["DOCKER_LOG"]).exists()


def test_bootstrap_writes_every_setting_the_example_documents():
    def names(text):
        return {
            line.split("=", 1)[0] for line in text.splitlines() if re.match(r"[A-Z0-9_]+=", line)
        }

    script = (DEPLOY / "bootstrap.sh").read_text()
    template = script.split("<< SETTINGS\n", 1)[1].split("\nSETTINGS\n", 1)[0]
    assert names(template) == names((DEPLOY / ".env.example").read_text())
