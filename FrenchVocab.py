"""Legacy entry point for the vocabulary CLI with modern argument parsing."""

from __future__ import annotations

import argparse
import os
from typing import Sequence

__all__ = ["FrenchVocabBuilder", "build_app", "run_cli", "main"]  # noqa: F822


def _load_core_builder():
    from core import FrenchVocabBuilder as _builder

    globals()["FrenchVocabBuilder"] = _builder
    return _builder


def _load_bootstrap():
    from cli.bootstrap import build_app as _build_app, run_cli as _run_cli

    globals()["build_app"] = _build_app
    globals()["run_cli"] = _run_cli
    return _build_app, _run_cli


def __getattr__(name: str):
    if name == "FrenchVocabBuilder":
        return _load_core_builder()
    if name == "build_app":
        return _load_bootstrap()[0]
    if name == "run_cli":
        return _load_bootstrap()[1]
    raise AttributeError(name)


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="FrenchVocab CLI")
    parser.add_argument(
        "--language",
        "-l",
        help="Language code to launch immediately (e.g., 'fr', 'de').",
    )
    parser.add_argument(
        "--provider",
        "-p",
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
        help="Enable ESC latency tracing (same as setting FRENCHVOCAB_ESC_DEBUG=1).",
    )
    parser.add_argument(
        "--esc-debug-log",
        help="Custom log file for ESC latency tracing (defaults to ~/.frenchvocab/esc_latency.log).",
    )
    parser.add_argument(
        "--eager-llm",
        action="store_true",
        help="Initialize the AI provider at startup (default is lazy, first-use setup).",
    )
    return parser.parse_args(argv)


def _apply_esc_debug_flags(args: argparse.Namespace) -> None:
    if args.esc_debug:
        os.environ.setdefault("FRENCHVOCAB_ESC_DEBUG", "1")
    if args.esc_debug_log:
        os.environ["FRENCHVOCAB_ESC_DEBUG_LOG"] = os.path.expanduser(args.esc_debug_log)


def main(argv: Sequence[str] | None = None) -> None:
    args = _parse_args(argv)
    _apply_esc_debug_flags(args)

    build_app, run_cli = _load_bootstrap()
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


if __name__ == "__main__":
    main()
