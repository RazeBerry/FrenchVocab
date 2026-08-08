from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]


def test_deployment_shell_scripts_are_syntactically_valid() -> None:
    scripts = sorted((ROOT / "scripts" / "deploy").glob("*.sh"))

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
