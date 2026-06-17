"""Application entry point."""

from __future__ import annotations

import sys
from pathlib import Path


if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from propeller_lab.ui.main_window import run_app  # noqa: E402


def main() -> int:
    """Launch the PropellerLab UI."""

    return run_app()


if __name__ == "__main__":
    raise SystemExit(main())
