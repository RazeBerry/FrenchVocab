"""Command-line entry helpers."""

__all__ = ["build_app", "run_cli"]


def __getattr__(name: str):
    if name in {"build_app", "run_cli"}:
        from .bootstrap import build_app, run_cli

        return {"build_app": build_app, "run_cli": run_cli}[name]
    raise AttributeError(name)
