import logging
from logging.handlers import RotatingFileHandler

from .paths import LOG_DIR, ensure_directories


def configure_logging() -> None:
    ensure_directories()
    handler = RotatingFileHandler(LOG_DIR / "parking_monitor.log", maxBytes=5_000_000, backupCount=5, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    if not any(isinstance(h, RotatingFileHandler) for h in root.handlers):
        root.addHandler(handler)
        root.addHandler(logging.StreamHandler())
