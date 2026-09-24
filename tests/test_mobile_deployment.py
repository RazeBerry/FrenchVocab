import os
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def test_deployment_shell_scripts_are_syntactically_valid() -> None:
    scripts = sorted((ROOT / "scripts" / "deploy").glob("*.sh"))
    scripts.append(ROOT / "scripts" / "macos" / "vocab")

    for script in scripts:
        subprocess.run(["sh", "-n", str(script)], check=True)


def _deployment_fixture(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    repo = tmp_path / "repo"
    deploy_dir = repo / "scripts" / "deploy"
    deploy_dir.mkdir(parents=True)
    script = deploy_dir / "deploy_vm.sh"
    script.write_bytes((ROOT / "scripts" / "deploy" / "deploy_vm.sh").read_bytes())
    script.chmod(0o755)

    subprocess.run(["git", "init", "-b", "main", str(repo)], check=True, capture_output=True)
    for name, value in (("user.name", "Deploy Test"), ("user.email", "deploy@example.test")):
        subprocess.run(["git", "-C", str(repo), "config", name, value], check=True)
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-m", "test: deployment fixture"], check=True, capture_output=True)
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "remote", "add", "origin", str(remote)], check=True)
    subprocess.run(["git", "-C", str(repo), "push", "-u", "origin", "main"], check=True, capture_output=True)

    config = tmp_path / "remote.env"
    config.write_text("VOCABBUILDER_REMOTE_USER=vm-user\nVOCABBUILDER_REMOTE_HOST=private-vm\n")
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    tailscale = fake_bin / "tailscale"
    tailscale.write_text(
        "#!/bin/sh\n"
        "test \"$1\" = ssh && test \"$2\" = 'vm-user@private-vm' || exit 2\n"
        "if test \"$3\" = 'df -Pk /tmp /opt/vocabbuilder'; then\n"
        "  printf 'Filesystem 1024-blocks Used Available Capacity Mounted on\\n'\n"
        "  printf '/dev/test 2000000 1 %s 1%% /tmp\\n' \"${FAKE_REMOTE_AVAILABLE:-1000000}\"\n"
        "  printf '/dev/test 2000000 1 %s 1%% /opt\\n' \"${FAKE_REMOTE_AVAILABLE:-1000000}\"\n"
        "else\n"
        "  printf '%s' \"$3\" > \"$REMOTE_COMMAND_FILE\"\n"
        "  sh -n -c \"$3\" || exit 3\n"
        "  tar -tf - > \"$ARCHIVE_MANIFEST_FILE\"\n"
        "fi\n",
        encoding="utf-8",
    )
    tailscale.chmod(0o755)
    env = {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "VOCABBUILDER_LAUNCHER_CONFIG": str(config),
        "REMOTE_COMMAND_FILE": str(tmp_path / "remote-command.txt"),
        "ARCHIVE_MANIFEST_FILE": str(tmp_path / "archive-manifest.txt"),
    }
    return script, env


def test_deploy_vm_streams_only_pushed_commit_and_checks_install(tmp_path: Path) -> None:
    script, env = _deployment_fixture(tmp_path)
    result = subprocess.run([str(script)], env=env, capture_output=True, text=True)

    assert result.returncode == 0, result.stderr
    assert "Deployed and verified" in result.stdout
    assert "scripts/deploy/deploy_vm.sh" in Path(env["ARCHIVE_MANIFEST_FILE"]).read_text()
    command = Path(env["REMOTE_COMMAND_FILE"]).read_text()
    assert "--delete --chown=root:root --exclude .venv" in command
    assert "Installed package differs from the archived source" in command
    assert "systemctl restart vocabbuilder-mobile.service" in command
    assert "http://127.0.0.1:8080/static/styles.css" in command


@pytest.mark.parametrize("change", ["tracked", "untracked"])
def test_deploy_vm_refuses_dirty_checkout(tmp_path: Path, change: str) -> None:
    script, env = _deployment_fixture(tmp_path)
    if change == "tracked":
        script.write_text(script.read_text() + "\n# local edit\n")
    else:
        (script.parents[2] / "new.txt").write_text("local file")

    result = subprocess.run([str(script)], env=env, capture_output=True, text=True)

    assert result.returncode != 0
    assert "Commit or remove local changes" in result.stderr
    assert not Path(env["REMOTE_COMMAND_FILE"]).exists()


def test_deploy_vm_refuses_unpushed_commit(tmp_path: Path) -> None:
    script, env = _deployment_fixture(tmp_path)
    repo = script.parents[2]
    (repo / "new.txt").write_text("committed but not pushed")
    subprocess.run(["git", "-C", str(repo), "add", "new.txt"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-m", "test: new commit"], check=True, capture_output=True)

    result = subprocess.run([str(script)], env=env, capture_output=True, text=True)

    assert result.returncode != 0
    assert "not the pushed tip" in result.stderr
    assert not Path(env["REMOTE_COMMAND_FILE"]).exists()


def test_deploy_vm_refuses_low_remote_space(tmp_path: Path) -> None:
    script, env = _deployment_fixture(tmp_path)
    env["FAKE_REMOTE_AVAILABLE"] = "1"

    result = subprocess.run([str(script)], env=env, capture_output=True, text=True)

    assert result.returncode != 0
    assert "below the estimated peak" in result.stderr
    assert not Path(env["REMOTE_COMMAND_FILE"]).exists()


def test_mobile_service_keeps_one_request_state_worker() -> None:
    unit = (ROOT / "deploy" / "vocabbuilder-mobile.service").read_text(
        encoding="utf-8"
    )

    assert "vocabbuilder-mobile" in unit
    assert "--workers" not in unit


def test_deployment_keeps_rotatable_credentials_out_of_systemd_environment() -> None:
    installer = (ROOT / "scripts" / "deploy" / "install_mobile_server.sh").read_text(
        encoding="utf-8"
    )
    launcher = (ROOT / "scripts" / "deploy" / "run_remote_cli.sh").read_text(
        encoding="utf-8"
    )

    assert 'CREDENTIAL_FILE="$DATA_DIR/.env"' in installer
    assert "grep -Ev '^(GEMINI_API_KEY|ANTHROPIC_API_KEY)='" in installer
    assert 'GEMINI_API_KEY="${GEMINI_API_KEY:-}"' not in launcher
    assert 'ANTHROPIC_API_KEY="${ANTHROPIC_API_KEY:-}"' not in launcher


def test_remote_cli_preserves_rich_interactive_input() -> None:
    launcher = (ROOT / "scripts" / "deploy" / "run_remote_cli.sh").read_text(
        encoding="utf-8"
    )

    assert "VOCABBUILDER_LOW_LATENCY_INPUT" not in launcher


def test_installer_prepares_operator_owned_export_directory() -> None:
    installer = (ROOT / "scripts" / "deploy" / "install_mobile_server.sh").read_text(
        encoding="utf-8"
    )

    assert '"$DATA_DIR/exports"' in installer


def test_macos_launcher_starts_local_remote_client(tmp_path: Path) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    captured = tmp_path / "python-arguments.txt"
    fake_python = fake_bin / "python"
    fake_python.write_text(
        "#!/bin/sh\nprintf '%s\\n' \"$@\" > \"$CAPTURED_ARGUMENTS\"\n",
        encoding="utf-8",
    )
    fake_python.chmod(0o755)
    env = {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "CAPTURED_ARGUMENTS": str(captured),
        "VOCABBUILDER_REMOTE_HOST": "private-vm",
        "VOCABBUILDER_LAUNCHER_CONFIG": str(tmp_path / "missing.env"),
    }

    subprocess.run(
        [
            str(ROOT / "scripts" / "macos" / "vocab"),
            "--language",
            "de",
            "--provider",
            "gemini",
        ],
        check=True,
        env=env,
    )

    assert captured.read_text(encoding="utf-8").splitlines() == [
        "-m",
        "vocab_builder.cli.remote_client",
        "--remote-host",
        "private-vm",
        "--language",
        "de",
        "--provider",
        "gemini",
    ]


def test_macos_launcher_retains_explicit_legacy_ssh_escape_hatch(tmp_path: Path) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    captured = tmp_path / "tailscale-arguments.txt"
    fake_tailscale = fake_bin / "tailscale"
    fake_tailscale.write_text(
        "#!/bin/sh\nprintf '%s\\n' \"$@\" > \"$CAPTURED_ARGUMENTS\"\n",
        encoding="utf-8",
    )
    fake_tailscale.chmod(0o755)
    env = {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "CAPTURED_ARGUMENTS": str(captured),
        "VOCABBUILDER_REMOTE_USER": "vm-user",
        "VOCABBUILDER_REMOTE_HOST": "private-vm",
        "VOCABBUILDER_LEGACY_SSH_CLI": "1",
        "VOCABBUILDER_LAUNCHER_CONFIG": str(tmp_path / "missing.env"),
    }

    subprocess.run(
        [str(ROOT / "scripts" / "macos" / "vocab"), "quote'and;operators"],
        check=True,
        env=env,
    )

    assert captured.read_text(encoding="utf-8").splitlines() == [
        "ssh",
        "vm-user@private-vm",
        "-t",
        "sudo /usr/local/sbin/vocabbuilder-cli 'quote'\\''and;operators'",
    ]
