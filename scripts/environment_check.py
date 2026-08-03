from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

from app.core.environment_check import collect_environment, format_environment

if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"): sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    info, errors = collect_environment(load_model=True)
    print(format_environment(info, errors))
    raise SystemExit(1 if errors else 0)
