"""Compatibility shim for menu orchestration.

Primary menu orchestration now lives in ``core.menu_loop`` so the core layer
does not depend on ``cli`` modules.
"""

from __future__ import annotations

from vocab_builder.core.menu_loop import (
    _handle_main_choice,
    _handle_translation,
    _refresh_menu_counts,
    _run_auto_translation,
    _run_eng_to_target,
    _run_target_to_eng,
    main_menu_loop,
)

__all__ = [
    "main_menu_loop",
    "_refresh_menu_counts",
    "_handle_main_choice",
    "_handle_translation",
    "_run_auto_translation",
    "_run_eng_to_target",
    "_run_target_to_eng",
]
