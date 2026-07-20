from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT_DIR / "data"
LOG_DIR = ROOT_DIR / "logs"
SNAPSHOT_DIR = ROOT_DIR / "snapshots"
CONFIG_DIR = ROOT_DIR / "config"


def ensure_directories() -> None:
    for path in (DATA_DIR, LOG_DIR, SNAPSHOT_DIR, CONFIG_DIR):
        path.mkdir(parents=True, exist_ok=True)

