from dataclasses import dataclass
import os

from .paths import DATA_DIR, ROOT_DIR, SNAPSHOT_DIR


@dataclass(frozen=True)
class RuntimeProfile:
    name: str
    max_cameras: int
    processing_fps: float
    detector_image_size: int
    preview_fps: float
    model_filename: str
    detector_device: str
    detector_half: bool
    ai_debug_overlay: bool


RUNTIME_PROFILES = {
    "debug_1cam": RuntimeProfile("debug_1cam", 1, 4.0, 640, 5.0, "yolo11n.pt", "cpu", False, True),
    "debug_2zones": RuntimeProfile("debug_2zones", 2, 4.0, 640, 5.0, "yolo11n.pt", "cuda:0", False, True),
    "production_10cam": RuntimeProfile("production_10cam", 10, 5.0, 960, 2.0, "yolo11s.pt", "cuda", True, False),
}


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    return default if value is None else value.strip().lower() in {"1", "true", "yes", "on"}


def get_runtime_profile(name: str | None = None) -> RuntimeProfile:
    selected = name or os.getenv("PARKING_RUNTIME_PROFILE", "debug_1cam")
    if selected not in RUNTIME_PROFILES:
        choices = ", ".join(sorted(RUNTIME_PROFILES))
        raise ValueError(f"PARKING_RUNTIME_PROFILE không hợp lệ: {selected!r}. Chọn: {choices}")
    return RUNTIME_PROFILES[selected]


active_runtime_profile = get_runtime_profile()


@dataclass(frozen=True)
class Settings:
    runtime_profile: str = active_runtime_profile.name
    max_cameras: int = int(os.getenv("PARKING_MAX_CAMERAS", str(active_runtime_profile.max_cameras)))
    app_timezone: str = os.getenv("PARKING_APP_TIMEZONE", "Asia/Ho_Chi_Minh")
    telemetry_interval_seconds: float = float(os.getenv("PARKING_TELEMETRY_INTERVAL_SECONDS", "30"))
    database_url: str = os.getenv("PARKING_DATABASE_URL", f"sqlite:///{DATA_DIR / 'parking.db'}")
    snapshot_dir: str = os.getenv("PARKING_SNAPSHOT_DIR", str(SNAPSHOT_DIR))
    processing_fps: float = float(os.getenv("PARKING_PROCESSING_FPS", str(active_runtime_profile.processing_fps)))
    detector_image_size: int = int(os.getenv("PARKING_DETECTOR_IMAGE_SIZE", str(active_runtime_profile.detector_image_size)))
    preview_fps: float = float(os.getenv("PARKING_PREVIEW_FPS", str(active_runtime_profile.preview_fps)))
    vehicle_confidence: float = 0.40
    parking_confirm_seconds: float = 15.0
    exit_confirm_seconds: float = 3.0
    track_lost_grace_seconds: float = 5.0
    occupancy_observation_grace_seconds: float = float(os.getenv("PARKING_OCCUPANCY_OBSERVATION_GRACE_SECONDS", "2"))
    vehicle_polygon_overlap_threshold: float = 0.30
    stable_frames_after_reconnect: int = 20
    session_track_match_max_anchor_distance: float = float(os.getenv("PARKING_SESSION_MATCH_MAX_ANCHOR_DISTANCE", "120"))
    session_track_match_min_iou: float = float(os.getenv("PARKING_SESSION_MATCH_MIN_IOU", "0.10"))
    session_track_match_min_size_ratio: float = float(os.getenv("PARKING_SESSION_MATCH_MIN_SIZE_RATIO", "0.60"))
    session_track_match_max_size_ratio: float = float(os.getenv("PARKING_SESSION_MATCH_MAX_SIZE_RATIO", "1.67"))
    enable_motorcycles: bool = False
    detector_model: str = os.getenv("PARKING_DETECTOR_MODEL", str(ROOT_DIR / "models" / active_runtime_profile.model_filename))
    detector_device: str = os.getenv("PARKING_DETECTOR_DEVICE", active_runtime_profile.detector_device)
    detector_half: bool = _env_bool("PARKING_DETECTOR_HALF", active_runtime_profile.detector_half)
    ai_debug_overlay: bool = _env_bool("PARKING_AI_DEBUG_OVERLAY", active_runtime_profile.ai_debug_overlay)
    runtime_mode: str = os.getenv("PARKING_RUNTIME_MODE", "normal")
    database_mode: str = os.getenv("PARKING_DATABASE_MODE", "PRODUCTION")
    selected_camera_codes: tuple[str, ...] = tuple(filter(None, os.getenv("PARKING_SELECTED_CAMERAS", "").split(",")))
    auto_scale: bool = _env_bool("PARKING_AUTO_SCALE", False)
    fallback_min_cameras: int = int(os.getenv("PARKING_FALLBACK_MIN_CAMERAS", "1"))
    benchmark_duration: int = int(os.getenv("PARKING_BENCHMARK_DURATION", "180"))


settings = Settings()
