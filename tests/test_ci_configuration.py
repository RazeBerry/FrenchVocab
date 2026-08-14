from pathlib import Path
import tomllib


ROOT = Path(__file__).resolve().parents[1]


def test_ruff_policy_is_explicit() -> None:
    config = tomllib.loads((ROOT / "pyproject.toml").read_text())

    assert config["tool"]["ruff"]["target-version"] == "py311"
    assert config["tool"]["ruff"]["lint"]["select"] == ["E4", "E7", "E9", "F"]


def test_ci_constrains_ruff_to_reviewed_compatibility_line() -> None:
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text()

    assert '"ruff~=0.16.0"' in workflow


def test_ci_installs_mobile_dependencies_before_full_test_collection() -> None:
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text()

    assert 'pip install -e ".[mobile]"' in workflow
