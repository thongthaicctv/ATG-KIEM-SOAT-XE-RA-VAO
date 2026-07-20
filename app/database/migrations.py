from .base import Base
from sqlalchemy import inspect, text
from .session import engine
from . import models  # noqa: F401
from .repair import repair_session_durations


def init_database() -> None:
    Base.metadata.create_all(engine)
    # Migration nhỏ, an toàn cho database Phase 1 đã tạo trước đây.
    columns={column["name"] for column in inspect(engine).get_columns("cameras")}
    if "rotation_degrees" not in columns:
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE cameras ADD COLUMN rotation_degrees INTEGER NOT NULL DEFAULT 0"))
    additions={
        "enable_motorcycles":"BOOLEAN NOT NULL DEFAULT 1",
        "vehicle_polygon_overlap_threshold":"FLOAT NOT NULL DEFAULT 0.20",
        "ai_debug_overlay":"BOOLEAN NOT NULL DEFAULT 1",
        "detector_image_size":"INTEGER NOT NULL DEFAULT 960",
        "use_polygon_roi":"BOOLEAN NOT NULL DEFAULT 1",
        "detection_miss_grace_seconds":"FLOAT NOT NULL DEFAULT 5.0",
    }
    for name,definition in additions.items():
        if name not in columns:
            with engine.begin() as connection:
                connection.execute(text(f"ALTER TABLE cameras ADD COLUMN {name} {definition}"))
    repair_session_durations(engine)
