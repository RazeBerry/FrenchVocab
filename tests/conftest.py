import os
import sys
import tempfile
from pathlib import Path

# Ensure project root is importable as a module root
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Install global stubs for optional deps to make imports deterministic
try:
    from tests._stubs import install_basic_stubs  # when run from repo root
except ModuleNotFoundError:
    from _stubs import install_basic_stubs  # fallback if pytest adjusts sys.path

install_basic_stubs()

_HISTORY_TMP = tempfile.mkdtemp(prefix="vocabbuilder_history_")
os.environ.setdefault("VOCABBUILDER_HISTORY_DIR", _HISTORY_TMP)
