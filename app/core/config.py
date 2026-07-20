from dataclasses import dataclass
import os

from .paths import DATA_DIR, ROOT_DIR, SNAPSHOT_DIR


@dataclass(frozen=True)
class Settings:
    app_timezone: str = os.getenv("PARKING_APP_TIMEZONE", "Asia/Ho_Chi_Minh")
    telemetry_interval_seconds: float = float(os.getenv("PARKING_TELEMETRY_INTERVAL_SECONDS", "30"))
    database_url: str = os.getenv("PARKING_DATABASE_URL", f"sqlite:///{DATA_DIR / 'parking.db'}")
    snapshot_dir: str = os.getenv("PARKING_SNAPSHOT_DIR", str(SNAPSHOT_DIR))
    processing_fps: float = 8.0
    vehicle_confidence: float = 0.40
    parking_confirm_seconds: float = 15.0
    exit_confirm_seconds: float = 3.0
    track_lost_grace_seconds: float = 5.0
    vehicle_polygon_overlap_threshold: float = 0.30
    stable_frames_after_reconnect: int = 20
    enable_motorcycles: bool = False
    detector_model: str = os.getenv("PARKING_DETECTOR_MODEL", str(ROOT_DIR / "models" / "yolo11n.pt"))


settings = Settings()
