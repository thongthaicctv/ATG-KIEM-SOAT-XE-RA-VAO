import logging
from datetime import datetime

from PySide6.QtCore import QObject, Signal

from app.core.constants import EventType, SessionStatus
from app.database.repositories import ParkingRepository
from app.utils.geometry import bbox_anchor
from app.utils.id_generator import make_session_code
from app.utils.time_utils import seconds_between,to_local_time
from app.services.session_vehicle_matcher import vehicle_class_family


class ParkingSessionSignals(QObject):
    session_started = Signal(int)
    session_recovered = Signal(int)
    session_completed = Signal(int)


class ParkingSessionService:
    def __init__(self, repository: ParkingRepository, signals=None):
        self.repo=repository; self.signals=signals or ParkingSessionSignals(); self.log=logging.getLogger(__name__)

    def start(self, camera, vehicle, entered_at: datetime, parked_at: datetime, enter_path=None, parked_path=None,event_source="AI",vehicle_instance_id=None,tracker_generation=0):
        session_start_key=f"{camera.id}:{vehicle_instance_id}" if vehicle_instance_id else None
        existing=self.repo.by_start_key(session_start_key) if session_start_key else None
        if existing:
            self.log.warning("Duplicate session start prevented vehicle_instance_id=%s existing_session=%s requested_track=%s reason=idempotency_key",vehicle_instance_id,existing.session_code,vehicle.track_id); return existing
        if vehicle_instance_id:
            existing=self.repo.open_by_vehicle_instance(camera.id,vehicle_instance_id)
            if existing:
                self.log.warning("Duplicate session start prevented vehicle_instance_id=%s existing_session=%s requested_track=%s reason=open_vehicle_instance",vehicle_instance_id,existing.session_code,vehicle.track_id); return existing
        owner=self.repo.get_open_session_for_track(camera.id,vehicle.track_id,tracker_generation)
        if owner:
            self.log.warning("Duplicate session start prevented vehicle_instance_id=%s existing_session=%s requested_track=%s reason=track_owned_by_open_session generation=%s",vehicle_instance_id,owner.session_code,vehicle.track_id,tracker_generation); return owner
        local_day=to_local_time(parked_at).strftime("%Y%m%d"); seq=self.repo.sequence_for_day(camera.parking_position_code,local_day)
        session=self.repo.create_session(session_code=make_session_code(camera.parking_position_code,seq,parked_at),camera_id=camera.id,
            parking_position_code=camera.parking_position_code,vehicle_class=vehicle.vehicle_class,entered_at=entered_at,parked_at=parked_at,
            status=SessionStatus.ACTIVE,event_source=event_source,vehicle_instance_id=vehicle_instance_id,session_start_key=session_start_key,current_track_id=str(vehicle.track_id),confirmed_bbox=list(vehicle.bbox),confirmed_anchor=list(bbox_anchor(vehicle.bbox)),confirmed_bbox_size=[max(1.0,vehicle.bbox[2]-vehicle.bbox[0]),max(1.0,vehicle.bbox[3]-vehicle.bbox[1])],last_confirmed_seen_at=parked_at,last_seen_at=parked_at,vehicle_family=vehicle_class_family(vehicle.vehicle_class).upper(),detector_raw_class=vehicle.vehicle_class,stabilized_vehicle_class=vehicle.vehicle_class,last_bbox_normalized=list(vehicle.bbox_normalized) if vehicle.bbox_normalized else None,last_anchor_normalized=list(vehicle.anchor_normalized) if vehicle.anchor_normalized else None,last_bbox_area=max(1.0,(vehicle.bbox[2]-vehicle.bbox[0])*(vehicle.bbox[3]-vehicle.bbox[1])),bbox_aspect_ratio=max(1.0,vehicle.bbox[2]-vehicle.bbox[0])/max(1.0,vehicle.bbox[3]-vehicle.bbox[1]),vehicle_histogram=vehicle.appearance_histogram,vehicle_perceptual_hash=vehicle.perceptual_hash,appearance_signature_json={"histogram":vehicle.appearance_histogram,"phash":vehicle.perceptual_hash},enter_snapshot_path=enter_path,parked_snapshot_path=parked_path)
        result=self.repo.try_add_track_link(session.id,vehicle.track_id,parked_at,tracker_generation)
        if not result.success:
            self.log.warning("Track ownership conflict camera=%s track_id=%s requested_session=%s existing_session=%s requested_vehicle_instance=%s existing_vehicle_instance=%s requested_state=ACTIVE existing_state=OPEN connection_generation=%s reason=%s",camera.id,vehicle.track_id,session.id,result.existing_session_id,vehicle_instance_id,None,tracker_generation,result.reason)
        self._event(camera.id,session.id,EventType.SYSTEM_RECOVERY if event_source=="SYSTEM_RECOVERY" else EventType.PARK_START,parked_at,vehicle,parked_path)
        self.signals.session_started.emit(session.id); self.log.info("Session started and committed session=%s vehicle_instance_id=%s track=%s idempotency_key=%s",session.session_code,vehicle_instance_id,vehicle.track_id,session_start_key)
        return session

    def link_track(self,session,vehicle,when,event_type=EventType.TRACK_RECOVERED,tracker_generation=0):
        track_id=str(vehicle.track_id)
        if vehicle_class_family(session.vehicle_class)!=vehicle_class_family(vehicle.vehicle_class): return False
        if self.repo.has_track(session.id,track_id,tracker_generation):
            if session.current_track_id!=track_id:
                session.current_track_id=track_id; self.repo.db.commit(); self.repo.db.refresh(session)
            return False
        result=self.repo.try_add_track_link(session.id,track_id,when,tracker_generation,commit=False)
        if not result.success:
            self.repo.db.rollback(); self.log.warning("Track ownership conflict camera=%s track_id=%s requested_session=%s existing_session=%s requested_vehicle_instance=%s existing_vehicle_instance=%s requested_state=%s existing_state=OPEN connection_generation=%s reason=%s",session.camera_id,track_id,session.id,result.existing_session_id,session.vehicle_instance_id,None,session.status,tracker_generation,result.reason); return False
        # Update memory/DB only after ownership preflight succeeds.
        session.current_track_id=track_id
        self._event(session.camera_id,session.id,event_type,when,vehicle,commit=False)
        self.repo.db.commit(); self.repo.db.refresh(session); return True

    def ensure_track(self,session,vehicle,when,tracker_generation=0) -> bool:
        return self.link_track(session,vehicle,when,EventType.TRACK_RECOVERED,tracker_generation)

    def update_confirmed_observation(self,session,vehicle,when):
        session.current_track_id=str(vehicle.track_id); session.detector_raw_class=vehicle.vehicle_class; session.confirmed_bbox=list(vehicle.bbox); session.confirmed_anchor=list(bbox_anchor(vehicle.bbox)); session.confirmed_bbox_size=[max(1.0,vehicle.bbox[2]-vehicle.bbox[0]),max(1.0,vehicle.bbox[3]-vehicle.bbox[1])]; session.last_confirmed_seen_at=when; session.last_seen_at=when; session.last_bbox_normalized=list(vehicle.bbox_normalized) if vehicle.bbox_normalized else session.last_bbox_normalized; session.last_anchor_normalized=list(vehicle.anchor_normalized) if vehicle.anchor_normalized else session.last_anchor_normalized; session.last_bbox_area=max(1.0,(vehicle.bbox[2]-vehicle.bbox[0])*(vehicle.bbox[3]-vehicle.bbox[1])); session.bbox_aspect_ratio=max(1.0,vehicle.bbox[2]-vehicle.bbox[0])/max(1.0,vehicle.bbox[3]-vehicle.bbox[1]); session.vehicle_histogram=vehicle.appearance_histogram or session.vehicle_histogram; session.vehicle_perceptual_hash=vehicle.perceptual_hash or session.vehicle_perceptual_hash

    def complete_session(self,session,camera_id,vehicle,left_at,exit_path=None,status=SessionStatus.COMPLETED,departure_time_uncertain=False):
        if session is None: raise ValueError("Session does not exist")
        self.repo.db.refresh(session)
        if session.left_at is not None or session.status in (SessionStatus.COMPLETED,SessionStatus.INTERRUPTED): return session
        current=self.repo.get_session(session.id)
        if current is None or current.camera_id!=camera_id or current.left_at is not None: raise ValueError("Session is not open for camera")
        previous_status=str(session.status)
        try:
            session.left_at=left_at; session.exit_snapshot_path=exit_path; session.departure_time_uncertain=bool(departure_time_uncertain)
            if departure_time_uncertain: session.event_source="CAMERA_RECOVERY"; session.first_confirmed_empty_after_reconnect=left_at
            session.parking_duration_seconds=seconds_between(session.parked_at,left_at); session.status=status
            self._event(camera_id,session.id,EventType.PARK_END,left_at,vehicle,exit_path,commit=False)
            self.repo.db.commit(); self.repo.db.refresh(session)
        except Exception:
            self.repo.db.rollback()
            self.log.exception("Session completion transaction failed session=%s",session.session_code)
            raise
        self.log.info("Session completed and committed session=%s previous_status=%s new_status=%s left_at=%s duration_seconds=%s",session.session_code,previous_status,session.status,session.left_at,session.parking_duration_seconds)
        self.signals.session_completed.emit(session.id)
        return session

    end=complete_session

    def recover(self,session,vehicle,when,tracker_generation=0):
        try:
            session.status=SessionStatus.RECOVERED; session.event_source="SYSTEM_RECOVERY"; self.update_confirmed_observation(session,vehicle,when)
            if not self.repo.has_track(session.id,vehicle.track_id,tracker_generation):
                result=self.repo.try_add_track_link(session.id,vehicle.track_id,when,tracker_generation,commit=False)
                if not result.success: self.repo.db.rollback(); self.log.warning("Recovery track conflict session=%s track=%s existing_session=%s generation=%s",session.session_code,vehicle.track_id,result.existing_session_id,tracker_generation); return session
            self._event(session.camera_id,session.id,EventType.TRACK_RECOVERED,when,vehicle,commit=False)
            self._event(session.camera_id,session.id,EventType.CAMERA_RECOVERED,when,vehicle,commit=False)
            self.repo.db.commit(); self.repo.db.refresh(session)
        except Exception:
            self.repo.db.rollback(); self.log.exception("Session recovery transaction failed session=%s",session.session_code); raise
        self.signals.session_recovered.emit(session.id); return session

    def _event(self,camera_id,session_id,event_type,when,vehicle=None,snapshot=None,commit=True):
        return self.repo.add_event(commit=commit,session_id=session_id,camera_id=camera_id,event_type=str(event_type),event_time=when,
            vehicle_class=getattr(vehicle,"vehicle_class",None),tracker_track_id=getattr(vehicle,"track_id",None),
            confidence=getattr(vehicle,"confidence",None),bbox_json=list(vehicle.bbox) if vehicle else None,
            anchor_point_json=None,snapshot_path=snapshot,metadata_json=None)
