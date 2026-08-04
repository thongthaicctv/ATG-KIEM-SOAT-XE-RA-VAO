from datetime import datetime,timedelta,timezone
from sqlalchemy import func,select
import numpy as np

from app.core.constants import EventType,ParkingState
from app.database.models import Camera,ParkingEvent,ParkingSession
from app.database.repositories import ParkingRepository
from app.services.parking_session_service import ParkingSessionService
from app.services.parking_state_engine import ParkingStateEngine
from app.services.polygon_engine import VehicleObservation
from app.services.session_vehicle_matcher import attach_vehicle_signature,is_same_session_vehicle
from app.ui.monitor_widget import STATE_LABELS
from app.utils.time_utils import ensure_utc

T=datetime(2026,8,4,3,0,tzinfo=timezone.utc)
CAR=VehicleObservation("1","car",.9,(100,100,300,300))


def setup(db):
    camera=Camera(camera_code="REC",camera_name="Recovery",parking_position_code="R1",rtsp_url="mock",enabled=True); db.add(camera); db.commit()
    service=ParkingSessionService(ParkingRepository(db)); session=service.start(camera,CAR,T,T)
    return camera,service,session


def test_occupied_offline_never_completes_or_sets_left_at(db):
    _camera,_service,session=setup(db); engine=ParkingStateEngine(1,2,1); engine.restore_active_session(); engine.update(CAR,T,monotonic_now=0)
    transition=engine.camera_offline(T+timedelta(seconds=5),5)
    assert transition.current==ParkingState.CAMERA_OFFLINE and session.left_at is None and session.status=="ACTIVE"


def test_reconnect_new_track_and_car_to_truck_keeps_session(db):
    camera,service,session=setup(db); parked=session.parked_at
    truck=VehicleObservation("99","truck",.85,(105,105,305,305))
    match=is_same_session_vehicle(session,truck,T+timedelta(seconds=30),track_lost_grace_seconds=3,allow_stale_reconnect=True)
    assert match.matched and match.class_family_match
    recovered=service.recover(session,truck,T+timedelta(seconds=30))
    assert recovered.id==session.id and recovered.session_code==session.session_code and recovered.vehicle_class=="car" and ensure_utc(recovered.parked_at)==ensure_utc(parked)
    assert service.repo.has_track(session.id,"99")
    assert db.scalar(select(func.count(ParkingEvent.id)).where(ParkingEvent.session_id==session.id,ParkingEvent.event_type==str(EventType.PARK_START)))==1
    assert db.scalar(select(func.count(ParkingEvent.id)).where(ParkingEvent.session_id==session.id,ParkingEvent.event_type==str(EventType.CAMERA_RECOVERED)))==1


def test_reconnect_many_times_keeps_one_history_row(db):
    _camera,service,session=setup(db)
    for index in range(2,6): service.recover(session,VehicleObservation(str(index),"truck" if index%2 else "car",.8,(101,101,301,301)),T+timedelta(seconds=index*10))
    assert db.scalar(select(func.count(ParkingSession.id)).where(ParkingSession.left_at.is_(None)))==1
    assert service.repo.recent_sessions()[0].session_code==session.session_code


def test_uncertain_vehicle_does_not_create_new_session(db):
    _camera,service,session=setup(db); engine=ParkingStateEngine(1,2,1); engine.restore_active_session()
    transition=engine.update(None,T+timedelta(seconds=20),True,20,identity_uncertain=True)
    assert transition.current==ParkingState.IDENTITY_UNCERTAIN
    assert len(service.repo.recent_sessions())==1 and session.left_at is None


def test_no_vehicle_after_reconnect_completes_with_uncertain_departure(db):
    camera,service,session=setup(db); engine=ParkingStateEngine(1,2,1); engine.restore_active_session()
    engine.update(CAR,T,True,0); engine.camera_offline(T+timedelta(seconds=10),10)
    first=engine.update(None,T+timedelta(seconds=20),True,20); assert first.current==ParkingState.LEAVING
    end=engine.update(None,T+timedelta(seconds=22),True,22); assert end.action=="PARK_END_RECOVERY"
    service.complete_session(session,camera.id,None,T+timedelta(seconds=22),departure_time_uncertain=True)
    assert session.departure_time_uncertain is True and session.event_source=="CAMERA_RECOVERY" and session.parking_duration_seconds==22


def test_repository_allows_multiple_open_sessions_in_same_zone(db):
    camera,service,session=setup(db)
    second=service.start(camera,VehicleObservation("2","truck",.8,(102,102,302,302)),T+timedelta(seconds=5),T+timedelta(seconds=5))
    assert second.id!=session.id
    assert db.scalar(select(func.count(ParkingSession.id)).where(ParkingSession.camera_id==camera.id,ParkingSession.left_at.is_(None)))==2


def test_recovery_ui_labels_are_explicit():
    assert STATE_LABELS["RECOVERY_PENDING"]=="ĐANG ĐỐI CHIẾU XE"
    assert STATE_LABELS["IDENTITY_UNCERTAIN"]=="KHÔNG CHẮC DANH TÍNH XE"


def test_lightweight_appearance_signature_is_available_for_recovery(db):
    camera,service,_session=setup(db); frame=np.zeros((400,400,3),dtype=np.uint8); frame[100:300,100:300]=(0,0,220)
    vehicle=attach_vehicle_signature(VehicleObservation("7","truck",.9,(100,100,300,300)),frame)
    assert vehicle.bbox_normalized==(0.25,0.25,0.75,0.75) and len(vehicle.appearance_histogram)==64 and len(vehicle.perceptual_hash)==16
