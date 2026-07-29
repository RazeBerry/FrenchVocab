"""CLI entry point for VocabBuilder with modern argument parsing."""

from __future__ import annotations

import argparse
import os
from typing import Sequence

__all__ = ["main"]


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="VocabBuilder CLI")
    parser.add_argument(
        "--language",
        "-l",
        type=str.lower,
        help="Language code to launch immediately (e.g., 'fr', 'de', 'en').",
    )
    parser.add_argument(
        "--provider",
        "-p",
        type=str.lower,
        help="LLM provider identifier to prefer for this session (e.g., 'gemini', 'claude').",
    )
    parser.add_argument(
        "--latex-file",
        help="Optional path to a custom LaTeX vocabulary file.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose logging during initialization.",
    )
    parser.add_argument(
        "--esc-debug",
        action="store_true",
        help="Enable ESC latency tracing (same as setting VOCABBUILDER_ESC_DEBUG=1).",
    )
    parser.add_argument(
        "--esc-debug-log",
        help="Custom log file for ESC latency tracing (defaults to ~/.vocabbuilder/esc_latency.log).",
    )
    parser.add_argument(
        "--eager-llm",
        action="store_true",
        help="Initialize the AI provider at startup (default is lazy, first-use setup).",
    )
    return parser.parse_args(argv)


def _validate_args(args: argparse.Namespace) -> None:
    from vocab_builder.core.providers.manager import _get_provider_metadata
    from vocab_builder.languages import get_language_config

    if args.language:
        args.language = get_language_config(args.language).code
    if args.provider:
        args.provider = _get_provider_metadata(args.provider).identifier


def _apply_esc_debug_flags(args: argparse.Namespace) -> None:
    if args.esc_debug:
        os.environ.setdefault("VOCABBUILDER_ESC_DEBUG", "1")
        # Legacy fallback so existing code still picks it up during transition
        os.environ.setdefault("FRENCHVOCAB_ESC_DEBUG", "1")
    if args.esc_debug_log:
        expanded = os.path.expanduser(args.esc_debug_log)
        os.environ["VOCABBUILDER_ESC_DEBUG_LOG"] = expanded
        os.environ["FRENCHVOCAB_ESC_DEBUG_LOG"] = expanded


def main(argv: Sequence[str] | None = None) -> None:
    try:
        args = _parse_args(argv)
        _apply_esc_debug_flags(args)
        _validate_args(args)

        from vocab_builder.cli.bootstrap import build_app, run_cli

        builder_kwargs = {
            "latex_file": args.latex_file,
            "provider": args.provider,
            "verbose": args.verbose,
            "eager_provider": args.eager_llm,
        }

        if args.language:
            builder = build_app(args.language, **builder_kwargs)
            builder.run()
            return

        run_cli(argv=argv, **builder_kwargs)
    except ValueError as exc:
        raise SystemExit(f"Error: {exc}") from None


if __name__ == "__main__":
    main()
