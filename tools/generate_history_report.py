"""Standalone checkout launcher; the shared implementation needs only Python and Git."""

import runpy
from pathlib import Path

if __name__ == "__main__":
    runpy.run_path(str(Path(__file__).resolve().parents[1] / "src" / "bcbench" / "history_report.py"), run_name="__main__")
