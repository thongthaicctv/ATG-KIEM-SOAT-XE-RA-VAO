import os
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = Path(os.getenv("PARKING_DATA_DIR", str(ROOT_DIR / "data"))).resolve()
LOG_DIR = Path(os.getenv("PARKING_LOG_DIR", str(ROOT_DIR / "logs"))).resolve()
SNAPSHOT_DIR = Path(os.getenv("PARKING_SNAPSHOT_DIR", str(ROOT_DIR / "snapshots"))).resolve()
CONFIG_DIR = ROOT_DIR / "config"


def ensure_directories() -> None:
    for path in (DATA_DIR, LOG_DIR, SNAPSHOT_DIR, CONFIG_DIR):
        path.mkdir(parents=True, exist_ok=True)

