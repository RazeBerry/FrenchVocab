from pathlib import Path
import re
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


def test_workflows_use_current_node24_action_generations() -> None:
    workflows = "\n".join(
        path.read_text() for path in sorted((ROOT / ".github" / "workflows").glob("*.yml"))
    )

    checkout_versions = re.findall(r"actions/checkout@(v\d+)", workflows)
    setup_python_versions = re.findall(r"actions/setup-python@(v\d+)", workflows)

    assert checkout_versions and set(checkout_versions) == {"v7"}
    assert setup_python_versions and set(setup_python_versions) == {"v7"}
