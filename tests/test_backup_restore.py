"""A daily archive restores to a readable collection and reaches the Mac."""

import io
import os
from pathlib import Path
import subprocess
import tarfile
from unittest.mock import MagicMock

import pytest

from vocab_builder.cli.backup_pull import pull_latest
from vocab_builder.cli.remote_client import RemoteAPIError
from vocab_builder.core.vocab_repository import VocabRepository
from vocab_builder.languages import get_language_config
from vocab_builder.mobile.storage import MobileStorage

ROOT = Path(__file__).resolve().parents[1]
BACKUP = ROOT / "scripts" / "deploy" / "backup_mobile_data.sh"
RESTORE = ROOT / "scripts" / "deploy" / "restore_mobile_data.sh"


def _fake_bin(tmp_path: Path) -> tuple[Path, Path]:
    """Stand-ins for systemctl, which records its calls, and flock, absent on macOS."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    calls = tmp_path / "systemctl.log"
    (bin_dir / "systemctl").write_text(f'#!/bin/sh\necho "$@" >> "{calls}"\n', encoding="utf-8")
    (bin_dir / "flock").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    for tool in bin_dir.iterdir():
        tool.chmod(0o755)
    return bin_dir, calls


def _run(script: Path, data: Path, bin_dir: Path, *args: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", "VOCABBUILDER_DATA_DIR": str(data)}
    return subprocess.run(["sh", str(script), *args], env=env, capture_output=True, text=True)


def _collection(data: Path) -> VocabRepository:
    return VocabRepository(
        latex_file=data / "FrenchVocab.tex",
        entry_command="\\entry",
        language_config=get_language_config("fr"),
        ui=MagicMock(),
    )


def test_archive_restores_the_collection_and_sets_the_replaced_files_aside(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    bin_dir, calls = _fake_bin(tmp_path)
    _collection(data).create_initial_tex_file()
    archived = (data / "FrenchVocab.tex").read_text(encoding="utf-8")
    entries = _collection(data).get_all_latex_entries()
    (data / "history").mkdir()
    (data / "history" / "fr_translations.jsonl").write_text('{"word": "flâner"}\n', encoding="utf-8")
    (data / ".env").write_text("GEMINI_API_KEY=old\n", encoding="utf-8")

    assert _run(BACKUP, data, bin_dir).returncode == 0
    (archive,) = (data / "backups").glob("vocabbuilder-data-*.tar.gz")
    with tarfile.open(archive) as members:
        assert "./.env" not in members.getnames()

    (data / "FrenchVocab.tex").write_text(archived + "% a save after the archive\n", encoding="utf-8")
    (data / ".env").write_text("GEMINI_API_KEY=rotated\n", encoding="utf-8")
    result = _run(RESTORE, data, bin_dir, str(archive))

    assert result.returncode == 0, result.stderr
    assert (data / "FrenchVocab.tex").read_text(encoding="utf-8") == archived
    assert _collection(data).get_all_latex_entries() == entries == {"agaçante"}
    assert (data / "history" / "fr_translations.jsonl").read_text(encoding="utf-8") == '{"word": "flâner"}\n'
    assert (data / ".env").read_text(encoding="utf-8") == "GEMINI_API_KEY=rotated\n"
    (aside,) = (data / "backups").glob("pre-restore-*")
    assert (aside / "FrenchVocab.tex").read_text(encoding="utf-8").endswith("% a save after the archive\n")
    assert calls.read_text(encoding="utf-8").split("\n")[:2] == [
        "stop vocabbuilder-mobile.service",
        "start vocabbuilder-mobile.service",
    ]


def test_a_corrupt_archive_is_refused_before_the_service_stops(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    bin_dir, calls = _fake_bin(tmp_path)
    (data / "FrenchVocab.tex").write_text("current", encoding="utf-8")
    broken = tmp_path / "vocabbuilder-data-20260101T000000Z.tar.gz"
    broken.write_bytes(b"\x1f\x8b\x08\x00truncated")

    result = _run(RESTORE, data, bin_dir, str(broken))

    assert result.returncode != 0
    assert not calls.exists()
    assert (data / "FrenchVocab.tex").read_text(encoding="utf-8") == "current"


def test_only_key_free_archives_are_downloadable(tmp_path):
    backups = tmp_path / "backups"
    backups.mkdir()
    (backups / "vocabbuilder-data-20260928T000000Z.tar.gz").write_bytes(b"archive")
    (backups / "vocabbuilder-20260927T000000Z.tar.gz").write_bytes(b"may hold .env")
    builder = MagicMock(
        latex_file=tmp_path / "FrenchVocab.tex",
        eng_to_target_latex_file=None,
        target_to_eng_latex_file=None,
        exported_words_file=tmp_path / "exported_words_fr.json",
    )
    storage = MobileStorage(builder, state_lock=MagicMock())

    assert [item["filename"] for item in storage.describe()["archives"]] == [
        "vocabbuilder-data-20260928T000000Z.tar.gz"
    ]
    assert storage.resolve_download("vocabbuilder-data-20260928T000000Z.tar.gz").read_bytes() == b"archive"
    with pytest.raises(FileNotFoundError):
        storage.resolve_download("vocabbuilder-20260927T000000Z.tar.gz")


def _archive_bytes(member: str = "FrenchVocab.tex") -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        info = tarfile.TarInfo(f"./{member}")
        info.size = 4
        archive.addfile(info, io.BytesIO(b"data"))
    return buffer.getvalue()


class _API:
    def __init__(self, names: list[str], payload: bytes):
        self.names = names
        self.payload = payload
        self.downloads = 0

    def request(self, path):
        assert path == "/api/storage"
        return {"archives": [{"filename": name, "download_url": f"/api/storage/download/{name}"} for name in self.names]}

    def download(self, path, destination):
        self.downloads += 1
        destination.write_bytes(self.payload)
        return destination


def test_the_mac_keeps_the_newest_archive_once_and_prunes_old_copies(tmp_path):
    for day in ("01", "02", "03"):
        (tmp_path / f"vocabbuilder-data-202609{day}T000000Z.tar.gz").write_bytes(b"old")
    api = _API(["vocabbuilder-data-20260927T000000Z.tar.gz", "vocabbuilder-data-20260928T000000Z.tar.gz"], _archive_bytes())

    pulled = pull_latest(api, tmp_path, keep=2)

    assert pulled == tmp_path / "vocabbuilder-data-20260928T000000Z.tar.gz"
    assert sorted(path.name for path in tmp_path.glob("vocabbuilder-data-*")) == [
        "vocabbuilder-data-20260903T000000Z.tar.gz",
        "vocabbuilder-data-20260928T000000Z.tar.gz",
    ]
    assert pull_latest(api, tmp_path, keep=2) is None
    assert api.downloads == 1


def test_the_mac_refuses_an_archive_that_does_not_read_whole(tmp_path):
    api = _API(["vocabbuilder-data-20260928T000000Z.tar.gz"], _archive_bytes()[:-12])

    with pytest.raises((OSError, EOFError, tarfile.TarError, RemoteAPIError)):
        pull_latest(api, tmp_path)

    assert list(tmp_path.iterdir()) == []
