import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_deployment_shell_scripts_are_syntactically_valid() -> None:
    scripts = sorted((ROOT / "scripts" / "deploy").glob("*.sh"))
    scripts.append(ROOT / "scripts" / "macos" / "vocab")

    for script in scripts:
        subprocess.run(["sh", "-n", str(script)], check=True)


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


def test_macos_launcher_safely_forwards_cli_arguments(tmp_path: Path) -> None:
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
        "VOCABBUILDER_LAUNCHER_CONFIG": str(tmp_path / "missing.env"),
    }

    subprocess.run(
        [
            str(ROOT / "scripts" / "macos" / "vocab"),
            "--language",
            "de",
            "--latex-file",
            "/tmp/My Vocab.tex",
            "quote'and;operators",
        ],
        check=True,
        env=env,
    )

    assert captured.read_text(encoding="utf-8").splitlines() == [
        "ssh",
        "vm-user@private-vm",
        "-t",
        "sudo /usr/local/sbin/vocabbuilder-cli '--language' 'de' "
        "'--latex-file' '/tmp/My Vocab.tex' 'quote'\\''and;operators'",
    ]
