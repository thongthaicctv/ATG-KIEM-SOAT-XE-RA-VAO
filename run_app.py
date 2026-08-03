import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent

os.chdir(PROJECT_ROOT)

from app.main import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
