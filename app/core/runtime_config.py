from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class RuntimeConfig:
    mode: str = "normal"
    device: str = "auto"
    max_cameras: int = 10
    cameras: tuple[str, ...] = field(default_factory=tuple)
    database_path: Path | None = None
    fallback_min_cameras: int = 1
    auto_scale: bool = False
    benchmark_duration: int = 180
    startup_dialog: bool = True

    @property
    def database_mode(self) -> str:
        return "PRODUCTION" if self.mode == "normal" else "DEBUG"

    def apply_environment(self, root: Path) -> None:
        import os
        mode_profile = "production_10cam" if self.mode == "normal" else ("debug_1cam" if self.max_cameras == 1 else "debug_2zones")
        db = self.database_path or (root / "data" / "parking.db" if self.mode == "normal" else root / "data" / "runtime_debug" / ("benchmark.db" if self.mode == "benchmark" else f"debug_{self.max_cameras}cams.db"))
        db.parent.mkdir(parents=True, exist_ok=True)
        scope = "production" if self.mode == "normal" else ("benchmark" if self.mode == "benchmark" else f"debug_{self.max_cameras}cams")
        values = {
            "PARKING_RUNTIME_PROFILE": mode_profile,
            "PARKING_RUNTIME_MODE": self.mode,
            "PARKING_DATABASE_MODE": self.database_mode,
            "PARKING_DETECTOR_DEVICE": self.device,
            "PARKING_DETECTOR_MODEL": str(root / "models" / "yolo11n.pt"),
            "PARKING_MAX_CAMERAS": str(self.max_cameras),
            "PARKING_SELECTED_CAMERAS": ",".join(self.cameras),
            "PARKING_DATABASE_URL": f"sqlite:///{db.as_posix()}",
            "PARKING_LOG_DIR": str(root / "logs" / scope),
            "PARKING_SNAPSHOT_DIR": str(root / "snapshots" / scope),
            "PARKING_AUTO_SCALE": "1" if self.auto_scale else "0",
            "PARKING_FALLBACK_MIN_CAMERAS": str(self.fallback_min_cameras),
            "PARKING_BENCHMARK_DURATION": str(self.benchmark_duration),
        }
        for key, value in values.items(): os.environ[key] = value
