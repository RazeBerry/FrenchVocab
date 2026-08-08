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
    for path in Path("vocab_builder/core").rglob("*.py"):
        if path.name == "__init__.py":
            continue
        for lineno, target in _iter_import_targets(path):
            if target == "cli" or target.startswith("cli.") or target == "vocab_builder.cli" or target.startswith("vocab_builder.cli."):
                violations.append(f"{path}:{lineno} imports {target}")

    assert not violations, "Core layer must not import CLI modules:\n" + "\n".join(violations)


def test_core_directory_contains_no_tex_artifacts():
    tex_files = sorted(Path("vocab_builder/core").glob("*.tex"))
    assert not tex_files, "vocab_builder/core/ should not contain tracked .tex artifacts"


def test_vocab_controller_file_size_budget():
    line_count = len(Path("vocab_builder/core/vocab.py").read_text(encoding="utf-8").splitlines())
    assert line_count <= 1450, f"vocab_builder/core/vocab.py is too large ({line_count} lines); extract responsibilities into helper modules"


def test_mobile_adapter_uses_only_the_public_builder_contract():
    path = Path("vocab_builder/mobile/service.py")
    tree = ast.parse(path.read_text(encoding="utf-8"))
    violations = [
        f"{path}:{node.lineno} accesses builder.{node.attr}"
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Attribute)
        and isinstance(node.value.value, ast.Name)
        and node.value.value.id == "self"
        and node.value.attr == "builder"
        and node.attr.startswith("_")
    ]

    assert not violations, "Mobile must depend on VocabBuilder's public port:\n" + "\n".join(violations)
