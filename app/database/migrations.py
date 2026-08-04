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
        "preview_fps":"FLOAT NOT NULL DEFAULT 5.0",
        "zone_type":"VARCHAR(32) NOT NULL DEFAULT 'LEGACY_UNSET'",
        "capacity":"INTEGER NOT NULL DEFAULT 1",
        "ignore_zones":"JSON",
        "ignore_zone_overlap_threshold":"FLOAT NOT NULL DEFAULT 0.30",
        "min_bbox_area_ratio":"FLOAT NOT NULL DEFAULT 0.0",
        "max_bbox_area_ratio":"FLOAT NOT NULL DEFAULT 1.0",
    }
    for name,definition in additions.items():
        if name not in columns:
            with engine.begin() as connection:
                connection.execute(text(f"ALTER TABLE cameras ADD COLUMN {name} {definition}"))
    session_columns={column["name"] for column in inspect(engine).get_columns("parking_sessions")}
    session_additions={
        "current_track_id":"VARCHAR(64)",
        "confirmed_bbox":"JSON",
        "confirmed_anchor":"JSON",
        "confirmed_bbox_size":"JSON",
        "last_confirmed_seen_at":"DATETIME",
        "offline_started_at":"DATETIME",
        "first_confirmed_empty_after_reconnect":"DATETIME",
        "departure_time_uncertain":"BOOLEAN NOT NULL DEFAULT 0",
        "last_bbox_normalized":"JSON",
        "last_anchor_normalized":"JSON",
        "last_bbox_area":"FLOAT",
        "bbox_aspect_ratio":"FLOAT",
        "vehicle_histogram":"JSON",
        "vehicle_perceptual_hash":"VARCHAR(32)",
        "vehicle_family":"VARCHAR(32)",
        "detector_raw_class":"VARCHAR(32)",
        "stabilized_vehicle_class":"VARCHAR(32)",
        "last_seen_at":"DATETIME",
        "recovery_status":"VARCHAR(32)",
        "identity_confidence":"FLOAT",
        "appearance_signature_json":"JSON",
        "entered_time_uncertain":"BOOLEAN NOT NULL DEFAULT 0",
        "vehicle_instance_id":"VARCHAR(36)",
        "session_start_key":"VARCHAR(96)",
    }
    for name,definition in session_additions.items():
        if name not in session_columns:
            with engine.begin() as connection:
                connection.execute(text(f"ALTER TABLE parking_sessions ADD COLUMN {name} {definition}"))
    track_columns={column["name"] for column in inspect(engine).get_columns("vehicle_track_links")}
    if "tracker_generation" not in track_columns:
        with engine.begin() as connection: connection.execute(text("ALTER TABLE vehicle_track_links ADD COLUMN tracker_generation INTEGER NOT NULL DEFAULT 0"))
    with engine.begin() as connection:
        connection.execute(text("DROP INDEX IF EXISTS uq_open_session_camera_position"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_open_sessions_camera_position ON parking_sessions(camera_id, parking_position_code, left_at)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_parking_sessions_current_track ON parking_sessions(current_track_id)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_parking_sessions_parked_at ON parking_sessions(parked_at)"))
        connection.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_parking_sessions_start_key ON parking_sessions(session_start_key) WHERE session_start_key IS NOT NULL"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_parking_sessions_vehicle_instance ON parking_sessions(vehicle_instance_id)"))
    repair_session_durations(engine)
