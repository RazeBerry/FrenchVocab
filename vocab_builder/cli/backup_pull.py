"""Keep the VM's newest data archive on this Mac.

The VM writes its daily archive to the same disk as the data it protects, so a
lost disk would take both. This pulls the newest archive through the private
API, the same identity-checked path the terminal client uses, and keeps it
only after it reads end to end. ``scripts/macos/install_backup_pull.sh``
schedules it daily.
"""

from __future__ import annotations

import argparse
import gzip
import os
from pathlib import Path
import tarfile
from typing import Optional, Sequence
import zlib

from vocab_builder.cli.remote_client import (
    RemoteAPI,
    RemoteAPIError,
    _DEFAULT_HOST,
    resolve_base_url,
)
from vocab_builder.compat import config_home

ARCHIVE_PATTERN = "vocabbuilder-data-*.tar.gz"
KEEP = 30


def default_destination() -> Path:
    return config_home(create=True) / "vm-backups"


def verify_archive(path: Path) -> None:
    """Raise unless the archive decompresses whole and holds a collection."""
    with gzip.open(path, "rb") as stream:
        while stream.read(1 << 20):
            pass
    with tarfile.open(path, "r:gz") as archive:
        if not any(name.endswith(".tex") for name in archive.getnames()):
            raise RemoteAPIError(f"{path.name} holds no vocabulary collection.")


def pull_latest(api: RemoteAPI, destination: Path, keep: int = KEEP) -> Optional[Path]:
    """Download the newest archive unless it is already here; return it if new."""
    archives = api.request("/api/storage").get("archives") or []
    if not archives:
        raise RemoteAPIError("The VM has not written a data archive yet.")
    newest = max(archives, key=lambda item: item["filename"])
    target = destination / newest["filename"]
    if target.exists():
        return None
    partial = destination / f".{target.name}.part"
    try:
        api.download(newest["download_url"], partial)
        verify_archive(partial)
        os.replace(partial, target)
    finally:
        partial.unlink(missing_ok=True)
    for stale in sorted(destination.glob(ARCHIVE_PATTERN), reverse=True)[keep:]:
        stale.unlink()
    return target


def main(argv: Optional[Sequence[str]] = None) -> None:
    parser = argparse.ArgumentParser(description="Copy the VM's newest data archive to this Mac")
    parser.add_argument("--remote-host", default=os.environ.get("VOCABBUILDER_REMOTE_HOST", _DEFAULT_HOST))
    parser.add_argument("--remote-url", default=os.environ.get("VOCABBUILDER_REMOTE_URL"))
    parser.add_argument("--dest", type=Path, default=None)
    args = parser.parse_args(argv)
    destination = (args.dest or default_destination()).expanduser()
    destination.mkdir(parents=True, exist_ok=True)
    try:
        api = RemoteAPI(resolve_base_url(args.remote_host, explicit_url=args.remote_url))
        pulled = pull_latest(api, destination)
    except (RemoteAPIError, OSError, tarfile.TarError, EOFError, zlib.error) as exc:
        raise SystemExit(f"Backup pull failed: {exc}") from None
    newest = max(destination.glob(ARCHIVE_PATTERN), default=None)
    print(f"Pulled {pulled}" if pulled else f"Up to date: {newest}")


if __name__ == "__main__":
    main()
