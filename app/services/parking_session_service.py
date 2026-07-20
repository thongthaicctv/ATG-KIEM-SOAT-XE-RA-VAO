from datetime import datetime

from app.core.constants import EventType, SessionStatus
from app.database.repositories import ParkingRepository
from app.utils.id_generator import make_session_code
from app.utils.time_utils import seconds_between,to_local_time


class ParkingSessionService:
    def __init__(self, repository: ParkingRepository): self.repo=repository

    def start(self, camera, vehicle, entered_at: datetime, parked_at: datetime, enter_path=None, parked_path=None,event_source="AI"):
        existing=self.repo.active_for_camera(camera.id)
        if existing:
            self.link_track(existing,vehicle,parked_at,EventType.TRACK_RECOVERED); return existing
        local_day=to_local_time(parked_at).strftime("%Y%m%d"); seq=self.repo.sequence_for_day(camera.parking_position_code,local_day)
        session=self.repo.create_session(session_code=make_session_code(camera.parking_position_code,seq,parked_at),camera_id=camera.id,
            parking_position_code=camera.parking_position_code,vehicle_class=vehicle.vehicle_class,entered_at=entered_at,parked_at=parked_at,
            status=SessionStatus.ACTIVE,event_source=event_source,enter_snapshot_path=enter_path,parked_snapshot_path=parked_path)
        self.repo.add_track(session.id,vehicle.track_id,parked_at)
        self._event(camera.id,session.id,EventType.SYSTEM_RECOVERY if event_source=="SYSTEM_RECOVERY" else EventType.PARK_START,parked_at,vehicle,parked_path)
        return session

    def link_track(self,session,vehicle,when,event_type=EventType.TRACK_RECOVERED):
        if self.repo.has_track(session.id,vehicle.track_id): return False
        self.repo.add_track(session.id,vehicle.track_id,when); self._event(session.camera_id,session.id,event_type,when,vehicle); return True

    def ensure_track(self,session,vehicle,when) -> bool:
        return self.link_track(session,vehicle,when,EventType.TRACK_RECOVERED)

    def complete_session(self,session,camera_id,vehicle,left_at,exit_path=None,status=SessionStatus.COMPLETED):
        session.left_at=left_at; session.exit_snapshot_path=exit_path; session.parking_duration_seconds=seconds_between(session.parked_at,left_at); session.status=status
        self.repo.db.commit(); self._event(camera_id,session.id,EventType.PARK_END,left_at,vehicle,exit_path); return session

    end=complete_session

    def recover(self,session,vehicle,when):
        session.status=SessionStatus.RECOVERED; self.link_track(session,vehicle,when,EventType.SYSTEM_RECOVERY); return session

    def _event(self,camera_id,session_id,event_type,when,vehicle=None,snapshot=None):
        return self.repo.add_event(session_id=session_id,camera_id=camera_id,event_type=str(event_type),event_time=when,
            vehicle_class=getattr(vehicle,"vehicle_class",None),tracker_track_id=getattr(vehicle,"track_id",None),
            confidence=getattr(vehicle,"confidence",None),bbox_json=list(vehicle.bbox) if vehicle else None,
            anchor_point_json=None,snapshot_path=snapshot,metadata_json=None)
