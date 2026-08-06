from .base import Base
from sqlalchemy import inspect, text
import json
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
        "occupancy_observation_grace_seconds":"FLOAT NOT NULL DEFAULT 2.0",
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
        "physical_zone_id":"INTEGER REFERENCES physical_zones(id)",
        "vehicle_identity_id":"INTEGER REFERENCES vehicle_identities(id)",
        "primary_camera_id":"INTEGER REFERENCES cameras(id)",
        "dominant_color":"VARCHAR(32)",
        "plate_number":"VARCHAR(32)",
        "virtual_slot_id":"VARCHAR(64)",
        "latest_zone_x":"FLOAT",
        "latest_zone_y":"FLOAT",
        "geometry_version_started":"INTEGER",
        "geometry_version_latest":"INTEGER",
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
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_parking_sessions_physical_zone ON parking_sessions(physical_zone_id,left_at)"))
        # Tương thích database cũ: mỗi camera chưa được cấu hình zone sẽ nhận một
        # INDEPENDENT_ZONE. Không sửa polygon camera và không đụng lịch sử session.
        cameras=connection.execute(text("SELECT id,camera_code,camera_name,zone_type,capacity,polygon_points FROM cameras")).mappings().all()
        for camera in cameras:
            linked=connection.execute(text("SELECT 1 FROM zone_cameras WHERE camera_id=:id AND removed_at IS NULL"),{"id":camera["id"]}).first()
            if linked: continue
            zone_code=f"ZONE_{camera['camera_code']}"
            connection.execute(text("INSERT OR IGNORE INTO physical_zones(zone_code,zone_name,zone_mode,zone_type,capacity,coordinate_mode,coordinate_unit,enabled,created_at,updated_at) VALUES(:code,:name,'INDEPENDENT_ZONE',:type,:capacity,'NORMALIZED','normalized',1,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"),{"code":zone_code,"name":camera["camera_name"],"type":camera["zone_type"],"capacity":camera["capacity"]})
            zone_id=connection.execute(text("SELECT id FROM physical_zones WHERE zone_code=:code"),{"code":zone_code}).scalar_one()
            polygon=camera["polygon_points"] or "[]"; polygon=polygon if isinstance(polygon,str) else json.dumps(polygon)
            connection.execute(text("INSERT OR IGNORE INTO zone_geometry_versions(physical_zone_id,version_number,canonical_polygon_json,change_type,created_at,activated_at,is_active) VALUES(:zone,1,:polygon,'INITIAL',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP,1)"),{"zone":zone_id,"polygon":polygon})
            geometry_id=connection.execute(text("SELECT id FROM zone_geometry_versions WHERE physical_zone_id=:zone AND version_number=1"),{"zone":zone_id}).scalar_one()
            connection.execute(text("UPDATE physical_zones SET active_geometry_version_id=:geometry WHERE id=:zone"),{"geometry":geometry_id,"zone":zone_id})
            connection.execute(text("INSERT OR IGNORE INTO zone_cameras(physical_zone_id,camera_id,camera_role,enabled,priority,added_at) VALUES(:zone,:camera,'PRIMARY',1,1,CURRENT_TIMESTAMP)"),{"zone":zone_id,"camera":camera["id"]})
            zone_camera_id=connection.execute(text("SELECT id FROM zone_cameras WHERE physical_zone_id=:zone AND camera_id=:camera"),{"zone":zone_id,"camera":camera["id"]}).scalar_one()
            connection.execute(text("INSERT INTO camera_zone_calibrations(zone_camera_id,geometry_version_id,calibration_type,visible_polygon_image_json,visible_polygon_zone_json,reprojection_error,calibration_status,created_at,activated_at) SELECT :zc,:geometry,'LOCAL_NORMALIZED',:polygon,:polygon,0,'VALID',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP WHERE NOT EXISTS(SELECT 1 FROM camera_zone_calibrations WHERE zone_camera_id=:zc AND geometry_version_id=:geometry)"),{"zc":zone_camera_id,"geometry":geometry_id,"polygon":polygon})
            connection.execute(text("UPDATE parking_sessions SET physical_zone_id=:zone,primary_camera_id=COALESCE(primary_camera_id,camera_id) WHERE camera_id=:camera AND physical_zone_id IS NULL"),{"zone":zone_id,"camera":camera["id"]})
    repair_session_durations(engine)
