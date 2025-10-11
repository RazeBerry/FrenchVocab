"""Legacy entry point for the vocabulary CLI."""

from cli.bootstrap import build_app, run_cli
from core import FrenchVocabBuilder

__all__ = ["FrenchVocabBuilder", "build_app", "run_cli", "main"]


def main() -> None:
    """Command-line entry point."""
    run_cli()


if __name__ == "__main__":
    main()
