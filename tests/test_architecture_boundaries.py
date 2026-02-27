import ast
from pathlib import Path


def _iter_import_targets(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield node.lineno, alias.name
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            yield node.lineno, node.module


def test_core_modules_do_not_import_cli_modules():
    violations = []
    for path in Path("core").rglob("*.py"):
        if path.name == "__init__.py":
            continue
        for lineno, target in _iter_import_targets(path):
            if target == "cli" or target.startswith("cli."):
                violations.append(f"{path}:{lineno} imports {target}")

    assert not violations, "Core layer must not import CLI modules:\n" + "\n".join(violations)
