"""Test suite for Titan."""

import sys
from pathlib import Path

# Ensure src/ is discoverable when executing via python -m unittest
src_path = str(Path(__file__).resolve().parent.parent / "src")
if src_path not in sys.path:
    sys.path.insert(0, src_path)
