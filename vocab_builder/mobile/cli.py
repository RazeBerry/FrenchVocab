"""Command-line entry point for the private mobile server."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Optional, Sequence

from rich.console import Console

from vocab_builder.languages import get_language_config
from vocab_builder.ui_helper import UIHelper


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="vocabbuilder-mobile",
        description="Run VocabBuilder's private phone-friendly web interface.",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument(
        "--languages",
        default="fr,de,en",
        help="Comma-separated language collections to expose (default: fr,de,en).",
    )
    parser.add_argument(
        "--language",
        choices=("fr", "de", "en"),
        help="Expose one collection; retained for single-language deployments.",
    )
    parser.add_argument("--default-language", default="fr")
    parser.add_argument("--provider", default="gemini", choices=("gemini", "claude"))
    parser.add_argument("--latex-file", type=Path)
    parser.add_argument("--config-dir", type=Path)
    parser.add_argument(
        "--allowed-tailscale-user",
        default=None,
        help="Only accept requests from this Tailscale login.",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    config_dir = args.config_dir or Path(
        os.environ.get("VOCABBUILDER_CONFIG_DIR", "~/.vocabbuilder")
    ).expanduser()
    os.environ["VOCABBUILDER_CONFIG_DIR"] = str(config_dir)
    os.environ.setdefault("VOCABBUILDER_HISTORY_DIR", str(config_dir / "history"))
    languages = [args.language] if args.language else _parse_languages(args.languages, parser)
    if args.latex_file and len(languages) != 1:
        parser.error("--latex-file can only be used with --language")

    from uvicorn import run

    from .app import create_app
    from .factory import build_mobile_catalog, build_mobile_service

    if args.latex_file:
        mobile_backend = build_mobile_service(
            latex_file=args.latex_file,
            language=languages[0],
            provider=args.provider,
            config_dir=config_dir,
        )
    else:
        mobile_backend = build_mobile_catalog(
            languages=languages,
            provider=args.provider,
            config_dir=config_dir,
            default_language=args.language or args.default_language,
        )
    app = create_app(
        mobile_backend,
        allowed_tailscale_user=args.allowed_tailscale_user,
    )
    configured_user = (
        args.allowed_tailscale_user
        if args.allowed_tailscale_user is not None
        else os.environ.get("VOCABBUILDER_ALLOWED_TAILSCALE_USER", "")
    ).strip()
    ui = UIHelper(Console(), interactive=False)
    if configured_user:
        ui.info(f"Tailscale identity check accepts only {configured_user}.")
    else:
        ui.warning(
            "Requests are not identity-checked. Configure "
            "--allowed-tailscale-user or "
            "VOCABBUILDER_ALLOWED_TAILSCALE_USER to restrict access."
        )
    run(app, host=args.host, port=args.port, proxy_headers=True, forwarded_allow_ips="127.0.0.1")


def _parse_languages(raw: str, parser: argparse.ArgumentParser) -> list[str]:
    requested = [value.strip() for value in raw.split(",") if value.strip()]
    if not requested:
        parser.error("--languages must contain at least one language code")
    languages: list[str] = []
    for value in requested:
        try:
            languages.append(get_language_config(value).code)
        except ValueError as exc:
            parser.error(str(exc))
    if len(set(languages)) != len(languages):
        parser.error("--languages cannot contain duplicates")
    return languages


if __name__ == "__main__":
    main()
