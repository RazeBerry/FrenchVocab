from vocab_builder.core.esc_config import read_esc_sequence_timeout


def test_read_esc_sequence_timeout_defaults_when_unset(monkeypatch):
    monkeypatch.delenv("FRENCHVOCAB_ESC_SEQUENCE_TIMEOUT", raising=False)
    assert read_esc_sequence_timeout() == 0.03


def test_read_esc_sequence_timeout_uses_valid_env(monkeypatch):
    monkeypatch.setenv("FRENCHVOCAB_ESC_SEQUENCE_TIMEOUT", "0.07")
    assert read_esc_sequence_timeout() == 0.07


def test_read_esc_sequence_timeout_rejects_invalid_env(monkeypatch):
    monkeypatch.setenv("FRENCHVOCAB_ESC_SEQUENCE_TIMEOUT", "not-a-number")
    assert read_esc_sequence_timeout() == 0.03


def test_read_esc_sequence_timeout_rejects_negative_env(monkeypatch):
    monkeypatch.setenv("FRENCHVOCAB_ESC_SEQUENCE_TIMEOUT", "-1")
    assert read_esc_sequence_timeout() == 0.03

