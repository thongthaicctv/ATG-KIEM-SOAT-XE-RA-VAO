from __future__ import annotations

from datetime import datetime
from typing import Any
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.utils.time_utils import utc_now
from .base import Base


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class Camera(Base, TimestampMixin):
    __tablename__ = "cameras"
    id: Mapped[int] = mapped_column(primary_key=True)
    camera_code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    camera_name: Mapped[str] = mapped_column(String(160))
    parking_position_code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    rtsp_url: Mapped[str] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    processing_fps: Mapped[float] = mapped_column(Float, default=8.0)
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
