from __future__ import annotations

from datetime import datetime
from typing import Any
from sqlalchemy import Boolean, CheckConstraint, DateTime, Float, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.utils.time_utils import utc_now
from .base import Base


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class Camera(Base, TimestampMixin):
    __tablename__ = "cameras"
    __table_args__ = (CheckConstraint("preview_fps >= 1 AND preview_fps <= 15", name="ck_cameras_preview_fps"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    camera_code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    camera_name: Mapped[str] = mapped_column(String(160))
    parking_position_code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    rtsp_url: Mapped[str] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    processing_fps: Mapped[float] = mapped_column(Float, default=8.0)
    preview_fps: Mapped[float] = mapped_column(Float, default=5.0)
    zone_type: Mapped[str] = mapped_column(String(32), default="LEGACY_UNSET")
    capacity: Mapped[int] = mapped_column(Integer, default=1)
    vehicle_confidence: Mapped[float] = mapped_column(Float, default=0.40)
    enable_motorcycles: Mapped[bool] = mapped_column(Boolean, default=True)
    detector_image_size: Mapped[int] = mapped_column(Integer, default=960)
    use_polygon_roi: Mapped[bool] = mapped_column(Boolean, default=True)
    vehicle_polygon_overlap_threshold: Mapped[float] = mapped_column(Float, default=0.20)
    ai_debug_overlay: Mapped[bool] = mapped_column(Boolean, default=True)
    parking_confirm_seconds: Mapped[float] = mapped_column(Float, default=15.0)
    exit_confirm_seconds: Mapped[float] = mapped_column(Float, default=3.0)
    track_lost_grace_seconds: Mapped[float] = mapped_column(Float, default=5.0)
    detection_miss_grace_seconds: Mapped[float] = mapped_column(Float, default=5.0)
    occupancy_observation_grace_seconds: Mapped[float] = mapped_column(Float, default=2.0)
    rotation_degrees: Mapped[int] = mapped_column(Integer, default=0)
    polygon_points: Mapped[list[list[float]] | None] = mapped_column(JSON, nullable=True)
    ignore_zones: Mapped[list[dict[str,Any]] | None] = mapped_column(JSON, nullable=True)
    ignore_zone_overlap_threshold: Mapped[float] = mapped_column(Float, default=0.30)
    min_bbox_area_ratio: Mapped[float] = mapped_column(Float, default=0.0)
    max_bbox_area_ratio: Mapped[float] = mapped_column(Float, default=1.0)
    status: Mapped[str] = mapped_column(String(32), default="OFFLINE")
    last_online_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PhysicalZone(Base, TimestampMixin):
    __tablename__="physical_zones"
    id: Mapped[int]=mapped_column(primary_key=True); zone_code: Mapped[str]=mapped_column(String(64),unique=True,index=True); zone_name: Mapped[str]=mapped_column(String(160))
    zone_mode: Mapped[str]=mapped_column(String(32)); zone_type: Mapped[str]=mapped_column(String(32)); capacity: Mapped[int]=mapped_column(Integer,default=1)
    coordinate_mode: Mapped[str]=mapped_column(String(32),default="NORMALIZED"); canonical_width: Mapped[float|None]=mapped_column(Float); canonical_height: Mapped[float|None]=mapped_column(Float); coordinate_unit: Mapped[str]=mapped_column(String(16),default="normalized")
    active_geometry_version_id: Mapped[int|None]=mapped_column(Integer,nullable=True); enabled: Mapped[bool]=mapped_column(Boolean,default=True)


class ZoneGeometryVersion(Base):
    __tablename__="zone_geometry_versions"
    id: Mapped[int]=mapped_column(primary_key=True); physical_zone_id: Mapped[int]=mapped_column(ForeignKey("physical_zones.id"),index=True); version_number: Mapped[int]=mapped_column(Integer)
    canonical_polygon_json: Mapped[list[list[float]]]=mapped_column(JSON); previous_version_id: Mapped[int|None]=mapped_column(ForeignKey("zone_geometry_versions.id")); change_type: Mapped[str]=mapped_column(String(32),default="INITIAL"); change_reason: Mapped[str|None]=mapped_column(Text)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=utc_now); created_by: Mapped[str|None]=mapped_column(String(96)); activated_at: Mapped[datetime|None]=mapped_column(DateTime(timezone=True)); is_active: Mapped[bool]=mapped_column(Boolean,default=False)
    __table_args__=(UniqueConstraint("physical_zone_id","version_number"),)


class ZoneCamera(Base):
    __tablename__="zone_cameras"
    id: Mapped[int]=mapped_column(primary_key=True); physical_zone_id: Mapped[int]=mapped_column(ForeignKey("physical_zones.id"),index=True); camera_id: Mapped[int]=mapped_column(ForeignKey("cameras.id"),index=True)
    camera_role: Mapped[str]=mapped_column(String(32),default="PRIMARY"); enabled: Mapped[bool]=mapped_column(Boolean,default=True); priority: Mapped[int]=mapped_column(Integer,default=1); added_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=utc_now); removed_at: Mapped[datetime|None]=mapped_column(DateTime(timezone=True))
    __table_args__=(UniqueConstraint("physical_zone_id","camera_id"),)


class CameraZoneCalibration(Base):
    __tablename__="camera_zone_calibrations"
    id: Mapped[int]=mapped_column(primary_key=True); zone_camera_id: Mapped[int]=mapped_column(ForeignKey("zone_cameras.id"),index=True); geometry_version_id: Mapped[int]=mapped_column(ForeignKey("zone_geometry_versions.id"),index=True)
    calibration_type: Mapped[str]=mapped_column(String(32)); control_points_image_json: Mapped[list|None]=mapped_column(JSON); control_points_zone_json: Mapped[list|None]=mapped_column(JSON); homography_matrix_json: Mapped[list|None]=mapped_column(JSON); inverse_homography_matrix_json: Mapped[list|None]=mapped_column(JSON)
    visible_polygon_image_json: Mapped[list|None]=mapped_column(JSON); visible_polygon_zone_json: Mapped[list|None]=mapped_column(JSON); reprojection_error: Mapped[float|None]=mapped_column(Float); calibration_status: Mapped[str]=mapped_column(String(32),default="NEEDS_REVIEW"); created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=utc_now); activated_at: Mapped[datetime|None]=mapped_column(DateTime(timezone=True))


class VirtualSlot(Base):
    __tablename__="virtual_slots"
    id: Mapped[int]=mapped_column(primary_key=True); slot_id: Mapped[str]=mapped_column(String(64)); physical_zone_id: Mapped[int]=mapped_column(ForeignKey("physical_zones.id"),index=True); geometry_version_id: Mapped[int]=mapped_column(ForeignKey("zone_geometry_versions.id")); slot_polygon: Mapped[list]=mapped_column(JSON); slot_anchor: Mapped[list]=mapped_column(JSON); vehicle_family: Mapped[str|None]=mapped_column(String(32)); capacity: Mapped[int]=mapped_column(Integer,default=1); enabled: Mapped[bool]=mapped_column(Boolean,default=True)
    __table_args__=(UniqueConstraint("physical_zone_id","geometry_version_id","slot_id"),)


class VehicleIdentity(Base):
    __tablename__="vehicle_identities"
    id: Mapped[int]=mapped_column(primary_key=True); vehicle_instance_id: Mapped[str]=mapped_column(String(36),unique=True,index=True); physical_zone_id: Mapped[int]=mapped_column(ForeignKey("physical_zones.id"),index=True)
    vehicle_family: Mapped[str|None]=mapped_column(String(32)); stabilized_vehicle_class: Mapped[str|None]=mapped_column(String(32)); stabilized_color: Mapped[str|None]=mapped_column(String(32)); color_confidence: Mapped[float|None]=mapped_column(Float); appearance_signature: Mapped[dict|None]=mapped_column(JSON); plate_number: Mapped[str|None]=mapped_column(String(32)); plate_confidence: Mapped[float|None]=mapped_column(Float); identity_confidence: Mapped[float|None]=mapped_column(Float); identity_state: Mapped[str]=mapped_column(String(32),default="ACTIVE"); created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=utc_now); last_seen_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=utc_now)


class VehicleObservationRecord(Base):
    __tablename__="vehicle_observations"
    id: Mapped[int]=mapped_column(primary_key=True); vehicle_identity_id: Mapped[int|None]=mapped_column(ForeignKey("vehicle_identities.id"),index=True); parking_session_id: Mapped[int|None]=mapped_column(ForeignKey("parking_sessions.id"),index=True); physical_zone_id: Mapped[int]=mapped_column(ForeignKey("physical_zones.id"),index=True); camera_id: Mapped[int]=mapped_column(ForeignKey("cameras.id"),index=True)
    tracker_generation: Mapped[int]=mapped_column(Integer,default=0); track_id: Mapped[str]=mapped_column(String(64)); observed_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=utc_now); raw_class: Mapped[str|None]=mapped_column(String(32)); stabilized_class: Mapped[str|None]=mapped_column(String(32)); class_confidence: Mapped[float|None]=mapped_column(Float)
    bbox_image_json: Mapped[list|None]=mapped_column(JSON); anchor_image_json: Mapped[list|None]=mapped_column(JSON); bbox_normalized_json: Mapped[list|None]=mapped_column(JSON); anchor_normalized_json: Mapped[list|None]=mapped_column(JSON); zone_x: Mapped[float|None]=mapped_column(Float); zone_y: Mapped[float|None]=mapped_column(Float); virtual_u: Mapped[float|None]=mapped_column(Float); virtual_v: Mapped[float|None]=mapped_column(Float); virtual_slot_id: Mapped[str|None]=mapped_column(String(64)); geometry_version_id: Mapped[int|None]=mapped_column(ForeignKey("zone_geometry_versions.id"))
    color: Mapped[str|None]=mapped_column(String(32)); color_confidence: Mapped[float|None]=mapped_column(Float); appearance_signature: Mapped[dict|None]=mapped_column(JSON); plate_number_observed: Mapped[str|None]=mapped_column(String(32)); plate_confidence_observed: Mapped[float|None]=mapped_column(Float); observation_quality: Mapped[float|None]=mapped_column(Float); is_ignored: Mapped[bool]=mapped_column(Boolean,default=False); ignore_reason: Mapped[str|None]=mapped_column(String(64)); remap_status: Mapped[str|None]=mapped_column(String(32))
    __table_args__=(UniqueConstraint("camera_id","tracker_generation","track_id","observed_at",name="uq_observation_track_time"),)


class ParkingSession(Base, TimestampMixin):
    __tablename__ = "parking_sessions"
    __table_args__ = (UniqueConstraint("session_code"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    session_code: Mapped[str] = mapped_column(String(96), unique=True, index=True)
    camera_id: Mapped[int] = mapped_column(ForeignKey("cameras.id"), index=True)
    physical_zone_id: Mapped[int | None] = mapped_column(ForeignKey("physical_zones.id"), nullable=True, index=True)
    vehicle_identity_id: Mapped[int | None] = mapped_column(ForeignKey("vehicle_identities.id"), nullable=True, index=True)
    primary_camera_id: Mapped[int | None] = mapped_column(ForeignKey("cameras.id"), nullable=True)
    dominant_color: Mapped[str | None] = mapped_column(String(32), nullable=True)
    plate_number: Mapped[str | None] = mapped_column(String(32), nullable=True)
    virtual_slot_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    latest_zone_x: Mapped[float | None] = mapped_column(Float, nullable=True)
    latest_zone_y: Mapped[float | None] = mapped_column(Float, nullable=True)
    geometry_version_started: Mapped[int | None] = mapped_column(Integer, nullable=True)
    geometry_version_latest: Mapped[int | None] = mapped_column(Integer, nullable=True)
    parking_position_code: Mapped[str] = mapped_column(String(64), index=True)
    vehicle_class: Mapped[str | None] = mapped_column(String(32))
    current_track_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    confirmed_bbox: Mapped[list[float] | None] = mapped_column(JSON, nullable=True)
    confirmed_anchor: Mapped[list[float] | None] = mapped_column(JSON, nullable=True)
    confirmed_bbox_size: Mapped[list[float] | None] = mapped_column(JSON, nullable=True)
    last_confirmed_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    offline_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    first_confirmed_empty_after_reconnect: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    departure_time_uncertain: Mapped[bool] = mapped_column(Boolean, default=False)
    last_bbox_normalized: Mapped[list[float] | None] = mapped_column(JSON, nullable=True)
    last_anchor_normalized: Mapped[list[float] | None] = mapped_column(JSON, nullable=True)
    last_bbox_area: Mapped[float | None] = mapped_column(Float, nullable=True)
    bbox_aspect_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)
    vehicle_histogram: Mapped[list[float] | None] = mapped_column(JSON, nullable=True)
    vehicle_perceptual_hash: Mapped[str | None] = mapped_column(String(32), nullable=True)
    vehicle_family: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    detector_raw_class: Mapped[str | None] = mapped_column(String(32), nullable=True)
    stabilized_vehicle_class: Mapped[str | None] = mapped_column(String(32), nullable=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    recovery_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    identity_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    appearance_signature_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    entered_time_uncertain: Mapped[bool] = mapped_column(Boolean, default=False)
    vehicle_instance_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    session_start_key: Mapped[str | None] = mapped_column(String(96), nullable=True, unique=True)
    entered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    parked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    left_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    parking_duration_seconds: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(32), index=True)
    event_source: Mapped[str] = mapped_column(String(32), default="AI")
    enter_snapshot_path: Mapped[str | None] = mapped_column(Text)
    parked_snapshot_path: Mapped[str | None] = mapped_column(Text)
    exit_snapshot_path: Mapped[str | None] = mapped_column(Text)
    camera: Mapped[Camera] = relationship(foreign_keys=[camera_id])
    track_links: Mapped[list[VehicleTrackLink]] = relationship(back_populates="session", cascade="all, delete-orphan")


class VehicleTrackLink(Base):
    __tablename__ = "vehicle_track_links"
    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("parking_sessions.id", ondelete="CASCADE"), index=True)
    tracker_track_id: Mapped[str] = mapped_column(String(64))
    tracker_generation: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    session: Mapped[ParkingSession] = relationship(back_populates="track_links")


class ParkingEvent(Base):
    __tablename__ = "parking_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int | None] = mapped_column(ForeignKey("parking_sessions.id", ondelete="SET NULL"), index=True)
    camera_id: Mapped[int] = mapped_column(ForeignKey("cameras.id"), index=True)
    event_type: Mapped[str] = mapped_column(String(48), index=True)
    event_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    vehicle_class: Mapped[str | None] = mapped_column(String(32))
    tracker_track_id: Mapped[str | None] = mapped_column(String(64))
    confidence: Mapped[float | None] = mapped_column(Float)
    bbox_json: Mapped[list[float] | None] = mapped_column(JSON)
    anchor_point_json: Mapped[list[float] | None] = mapped_column(JSON)
    snapshot_path: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
