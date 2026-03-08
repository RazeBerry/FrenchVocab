from vocab_builder.compat import config_home, config_homes_for_read, runtime_root
from vocab_builder.core import VocabBuilder


class _StubClient:
    def stream(self, _prompt: str, *, thinking_level: str = "low"):  # noqa: ARG002
        yield ""

    def model_label(self) -> str:
        return "Stub LLM"


def test_runtime_root_uses_config_dir_outside_git_checkout(tmp_path, monkeypatch):
    source_root = tmp_path / "site-packages"
    source_root.mkdir()
    config_dir = tmp_path / "config-home"
    monkeypatch.setenv("VOCABBUILDER_CONFIG_DIR", str(config_dir))

    assert runtime_root(source_root, create=True) == config_dir
    assert config_dir.is_dir()


def test_config_home_prefers_new_dir_but_keeps_legacy_read_fallback(tmp_path, monkeypatch):
    monkeypatch.delenv("VOCABBUILDER_CONFIG_DIR", raising=False)
    monkeypatch.delenv("FRENCHVOCAB_CONFIG_DIR", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    legacy_dir = tmp_path / ".frenchvocab"
    legacy_dir.mkdir()

    preferred_dir = config_home(create=True)

    assert preferred_dir == tmp_path / ".vocabbuilder"
    assert preferred_dir.is_dir()
    assert config_homes_for_read() == (preferred_dir, legacy_dir)


def test_builder_without_latex_file_uses_writable_runtime_root(tmp_path, monkeypatch):
    config_dir = tmp_path / "config-home"
    monkeypatch.setenv("VOCABBUILDER_CONFIG_DIR", str(config_dir))
    monkeypatch.setenv("GEMINI_API_KEY", "AIza" + "x" * 36)

    builder = VocabBuilder(
        None,
        provider="gemini",
        verbose=False,
        client=_StubClient(),
        language="fr",
    )

    assert builder.project_root == config_dir
    assert builder.latex_file == config_dir / "FrenchVocab.tex"
    assert builder.latex_file.exists()
    assert builder.exported_words_file.parent == config_dir
