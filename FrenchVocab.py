"""Legacy entry point for the vocabulary CLI."""

from cli.bootstrap import build_app, parse_args, run_cli
from core import FrenchVocabBuilder

__all__ = ["FrenchVocabBuilder", "build_app", "parse_args", "run_cli", "main"]


def main() -> None:
    """Command-line entry point."""
    run_cli()


if __name__ == "__main__":
    main()
