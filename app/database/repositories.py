from __future__ import annotations

from datetime import datetime
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from dataclasses import dataclass

from app.core.constants import SessionStatus
from .models import Camera, ParkingEvent, ParkingSession, VehicleTrackLink


@dataclass(slots=True)
class TrackLinkResult:
    success: bool
    status: str
    track_id: str
    requested_session_id: int | None
    existing_session_id: int | None=None
    reason: str | None=None
    link: VehicleTrackLink | None=None


class CameraRepository:
    def __init__(self, db: Session): self.db = db
    def list(self): return list(self.db.scalars(select(Camera).order_by(Camera.camera_code)))
    def get(self, camera_id: int): return self.db.get(Camera, camera_id)
    def add(self, **values):
        self._validate(values)
        obj=Camera(**values); self.db.add(obj); self.db.commit(); return obj
    def update(self, camera_id: int, **values):
        self._validate(values)
        obj=self.get(camera_id)
        if not obj: raise KeyError(camera_id)
        for k,v in values.items(): setattr(obj,k,v)
        self.db.commit(); return obj
    @staticmethod
    def _validate(values):
        if "preview_fps" in values and not 1 <= float(values["preview_fps"]) <= 15:
            raise ValueError("preview_fps phải nằm trong khoảng 1–15 FPS")
        if "capacity" in values and int(values["capacity"])<1: raise ValueError("capacity phải lớn hơn hoặc bằng 1")
        if values.get("enabled") and values.get("zone_type")=="LEGACY_UNSET": raise ValueError("Phải chọn loại khu vực trước khi bật camera")
    def delete(self, camera_id: int):
        obj=self.get(camera_id)
        if obj: self.db.delete(obj); self.db.commit()


class ParkingRepository:
    def __init__(self, db: Session): self.db = db
    def active_for_camera(self, camera_id: int):
        return self.db.scalar(select(ParkingSession).where(ParkingSession.camera_id==camera_id, ParkingSession.left_at.is_(None)).order_by(ParkingSession.id.desc()))
    def find_open_session_for_position(self,camera_id: int,position_code: str):
        return self.db.scalar(select(ParkingSession).where(ParkingSession.camera_id==camera_id,ParkingSession.parking_position_code==position_code,ParkingSession.left_at.is_(None)).order_by(ParkingSession.id.desc()))
    def find_open_sessions_for_position(self,camera_id: int,position_code: str):
        return list(self.db.scalars(select(ParkingSession).where(ParkingSession.camera_id==camera_id,ParkingSession.parking_position_code==position_code,ParkingSession.left_at.is_(None)).order_by(ParkingSession.id)))
    def get_session(self, session_id: int): return self.db.get(ParkingSession, session_id)
    def open_by_vehicle_instance(self,camera_id: int,vehicle_instance_id: str):
        return self.db.scalar(select(ParkingSession).where(ParkingSession.camera_id==camera_id,ParkingSession.vehicle_instance_id==vehicle_instance_id,ParkingSession.left_at.is_(None)).limit(1))
    def by_start_key(self,session_start_key: str):
        return self.db.scalar(select(ParkingSession).where(ParkingSession.session_start_key==session_start_key).limit(1))
    def sequence_for_day(self, position: str, day_prefix: str) -> int:
        return int(self.db.scalar(select(func.count(ParkingSession.id)).where(ParkingSession.parking_position_code==position, ParkingSession.session_code.like(f"{position}-{day_prefix}-%"))) or 0)+1
    def create_session(self, **values):
        obj=ParkingSession(**values); self.db.add(obj)
        self.db.commit(); return obj
    def get_open_session_for_track(self,camera_id: int,track_id: str,tracker_generation: int=0):
        return self.db.scalar(select(ParkingSession).join(VehicleTrackLink,VehicleTrackLink.session_id==ParkingSession.id).where(ParkingSession.camera_id==camera_id,ParkingSession.left_at.is_(None),VehicleTrackLink.tracker_track_id==str(track_id),VehicleTrackLink.tracker_generation==int(tracker_generation)).limit(1))
    def get_open_session_for_vehicle_instance(self,camera_id: int,vehicle_instance_id: str): return self.open_by_vehicle_instance(camera_id,vehicle_instance_id)
    def try_add_track_link(self,session_id: int,track_id: str,started_at: datetime,tracker_generation: int=0,commit: bool=True):
        target=self.db.get(ParkingSession,session_id)
        if target is None: return TrackLinkResult(False,"INVALID_ARGUMENT",str(track_id),session_id,reason="session_not_found")
        if target.left_at is not None: return TrackLinkResult(False,"SESSION_CLOSED",str(track_id),session_id,reason="session_closed")
        existing=self.db.scalar(select(VehicleTrackLink).where(VehicleTrackLink.session_id==session_id,VehicleTrackLink.tracker_track_id==str(track_id),VehicleTrackLink.tracker_generation==int(tracker_generation),VehicleTrackLink.ended_at.is_(None)))
        if existing: return TrackLinkResult(True,"ALREADY_LINKED_TO_SAME_SESSION",str(track_id),session_id,session_id,link=existing)
        owner=self.get_open_session_for_track(target.camera_id,track_id,tracker_generation)
        if owner and owner.id!=session_id: return TrackLinkResult(False,"CONFLICT_WITH_OTHER_OPEN_SESSION",str(track_id),session_id,owner.id,reason="track_owned_by_other_open_session")
        try:
            link=VehicleTrackLink(session_id=session_id,tracker_track_id=str(track_id),tracker_generation=int(tracker_generation),started_at=started_at); self.db.add(link)
            if commit: self.db.commit()
            return TrackLinkResult(True,"LINKED",str(track_id),session_id,session_id,link=link)
        except Exception as exc:
            self.db.rollback(); return TrackLinkResult(False,"DATABASE_ERROR",str(track_id),session_id,reason=type(exc).__name__)
    def add_track(self,session_id: int,track_id: str,started_at: datetime,commit: bool=True,tracker_generation: int=0):
        return self.try_add_track_link(session_id,track_id,started_at,tracker_generation,commit)
    def has_track(self,session_id: int,track_id: str,tracker_generation: int | None=None) -> bool:
        query=select(VehicleTrackLink.id).where(VehicleTrackLink.session_id==session_id,VehicleTrackLink.tracker_track_id==str(track_id))
        if tracker_generation is not None: query=query.where(VehicleTrackLink.tracker_generation==int(tracker_generation))
        return self.db.scalar(query.limit(1)) is not None
    def add_event(self, commit: bool=True, **values):
        e=ParkingEvent(**values); self.db.add(e)
        if commit: self.db.commit()
        return e
    def close_session(self, session: ParkingSession, left_at: datetime, status: str, exit_path: str | None=None):
        session.left_at=left_at; session.status=status; session.exit_snapshot_path=exit_path
        session.parking_duration_seconds=max(0,int((left_at-session.parked_at).total_seconds()))
        self.db.commit(); return session
    def recent_sessions(self, limit=500):
        return list(self.db.scalars(select(ParkingSession).order_by(ParkingSession.entered_at.desc()).limit(limit)))
    def active_sessions(self):
        return list(self.db.scalars(select(ParkingSession).where(ParkingSession.left_at.is_(None))))
