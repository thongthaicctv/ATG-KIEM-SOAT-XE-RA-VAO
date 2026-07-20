from __future__ import annotations

from datetime import datetime
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.constants import SessionStatus
from .models import Camera, ParkingEvent, ParkingSession, VehicleTrackLink


class CameraRepository:
    def __init__(self, db: Session): self.db = db
    def list(self): return list(self.db.scalars(select(Camera).order_by(Camera.camera_code)))
    def get(self, camera_id: int): return self.db.get(Camera, camera_id)
    def add(self, **values):
        obj=Camera(**values); self.db.add(obj); self.db.commit(); return obj
    def update(self, camera_id: int, **values):
        obj=self.get(camera_id)
        if not obj: raise KeyError(camera_id)
        for k,v in values.items(): setattr(obj,k,v)
        self.db.commit(); return obj
    def delete(self, camera_id: int):
        obj=self.get(camera_id)
        if obj: self.db.delete(obj); self.db.commit()


class ParkingRepository:
    def __init__(self, db: Session): self.db = db
    def active_for_camera(self, camera_id: int):
        return self.db.scalar(select(ParkingSession).where(ParkingSession.camera_id==camera_id, ParkingSession.status.in_([SessionStatus.ACTIVE, SessionStatus.RECOVERED])))
    def sequence_for_day(self, position: str, day_prefix: str) -> int:
        return int(self.db.scalar(select(func.count(ParkingSession.id)).where(ParkingSession.parking_position_code==position, ParkingSession.session_code.like(f"{position}-{day_prefix}-%"))) or 0)+1
    def create_session(self, **values):
        if self.active_for_camera(values["camera_id"]): raise ValueError("Camera đã có phiên đỗ đang hoạt động")
        obj=ParkingSession(**values); self.db.add(obj); self.db.commit(); return obj
    def add_track(self, session_id: int, track_id: str, started_at: datetime):
        existing=self.db.scalar(select(VehicleTrackLink).where(VehicleTrackLink.session_id==session_id, VehicleTrackLink.tracker_track_id==str(track_id), VehicleTrackLink.ended_at.is_(None)))
        if existing: return existing
        link=VehicleTrackLink(session_id=session_id,tracker_track_id=str(track_id),started_at=started_at); self.db.add(link); self.db.commit(); return link
    def has_track(self,session_id: int,track_id: str) -> bool:
        return self.db.scalar(select(VehicleTrackLink.id).where(VehicleTrackLink.session_id==session_id,VehicleTrackLink.tracker_track_id==str(track_id)).limit(1)) is not None
    def add_event(self, **values):
        e=ParkingEvent(**values); self.db.add(e); self.db.commit(); return e
    def close_session(self, session: ParkingSession, left_at: datetime, status: str, exit_path: str | None=None):
        session.left_at=left_at; session.status=status; session.exit_snapshot_path=exit_path
        session.parking_duration_seconds=max(0,int((left_at-session.parked_at).total_seconds()))
        self.db.commit(); return session
    def recent_sessions(self, limit=500):
        return list(self.db.scalars(select(ParkingSession).order_by(ParkingSession.entered_at.desc()).limit(limit)))
    def active_sessions(self):
        return list(self.db.scalars(select(ParkingSession).where(ParkingSession.status.in_([SessionStatus.ACTIVE, SessionStatus.RECOVERED]))))
