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
    rotation_degrees: Mapped[int] = mapped_column(Integer, default=0)
    polygon_points: Mapped[list[list[float]] | None] = mapped_column(JSON, nullable=True)
    ignore_zones: Mapped[list[dict[str,Any]] | None] = mapped_column(JSON, nullable=True)
    ignore_zone_overlap_threshold: Mapped[float] = mapped_column(Float, default=0.30)
    min_bbox_area_ratio: Mapped[float] = mapped_column(Float, default=0.0)
    max_bbox_area_ratio: Mapped[float] = mapped_column(Float, default=1.0)
    status: Mapped[str] = mapped_column(String(32), default="OFFLINE")
    last_online_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ParkingSession(Base, TimestampMixin):
    __tablename__ = "parking_sessions"
    __table_args__ = (UniqueConstraint("session_code"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    session_code: Mapped[str] = mapped_column(String(96), unique=True, index=True)
    camera_id: Mapped[int] = mapped_column(ForeignKey("cameras.id"), index=True)
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
    camera: Mapped[Camera] = relationship()
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
