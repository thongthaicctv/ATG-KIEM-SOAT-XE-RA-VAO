from datetime import datetime,timedelta,timezone

from app.database.models import Camera,ParkingSession
from app.database.repair import repair_session_durations
from app.database.repositories import ParkingRepository
from app.services.parking_session_service import ParkingSessionService
from app.services.polygon_engine import VehicleObservation
from app.services.tracker import calculate_track_buffer
from app.utils.id_generator import make_session_code
from app.utils.time_utils import ensure_utc,format_local_datetime,to_local_time


def test_utc_is_displayed_in_vietnam_timezone():
    utc=datetime(2026,7,20,10,44,tzinfo=timezone.utc)
    assert format_local_datetime(utc)=="20/07/2026 17:44:00"


def test_legacy_naive_datetime_is_treated_as_utc():
    legacy=datetime(2026,7,20,10,44)
    assert ensure_utc(legacy).tzinfo==timezone.utc
    assert to_local_time(legacy).hour==17


def test_session_code_uses_local_date_near_midnight():
    utc=datetime(2026,7,19,18,30,tzinfo=timezone.utc)  # 01:30 ngày hôm sau tại Việt Nam
    assert make_session_code("A01",1,utc)=="A01-20260720-000001"


def _camera(db,code="DUR"):
    camera=Camera(camera_code=code,camera_name=code,parking_position_code=code,rtsp_url="mock",enabled=True); db.add(camera); db.commit(); return camera


def test_complete_session_calculates_duration_before_completed(db):
    camera=_camera(db); service=ParkingSessionService(ParkingRepository(db)); vehicle=VehicleObservation("1","car",.9,(0,0,10,10)); parked=datetime(2026,7,20,10,0,tzinfo=timezone.utc)
    session=service.start(camera,vehicle,parked,parked); service.complete_session(session,camera.id,vehicle,parked+timedelta(seconds=182))
    assert session.status=="COMPLETED" and session.parking_duration_seconds==182 and session.left_at is not None


def test_repair_old_zero_duration(db):
    camera=_camera(db,"FIX"); parked=datetime(2026,7,20,10,0); session=ParkingSession(session_code="FIX-20260720-000001",camera_id=camera.id,parking_position_code="FIX",vehicle_class="car",entered_at=parked,parked_at=parked,left_at=parked+timedelta(seconds=300),parking_duration_seconds=0,status="COMPLETED",event_source="AI"); db.add(session); db.commit()
    assert repair_session_durations(db.get_bind())==1; db.refresh(session); assert session.parking_duration_seconds==300


def test_track_buffer_uses_full_configured_duration():
    assert calculate_track_buffer(8,3)==24


def test_one_vehicle_five_minutes_has_one_session(db):
    camera=_camera(db,"STABLE"); service=ParkingSessionService(ParkingRepository(db)); vehicle=VehicleObservation("1","motorcycle",.8,(0,0,10,10)); start=datetime(2026,7,20,10,0,tzinfo=timezone.utc)
    first=service.start(camera,vehicle,start,start); same=service.start(camera,VehicleObservation("2","motorcycle",.8,(0,0,10,10)),start,start+timedelta(minutes=5))
    assert first.id==same.id and len(service.repo.recent_sessions())==1
