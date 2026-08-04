from datetime import datetime,timezone

from app.database.models import Camera
from app.database.repositories import ParkingRepository
from app.services.parking_session_service import ParkingSessionService
from app.services.polygon_engine import VehicleObservation

NOW=datetime(2026,8,4,tzinfo=timezone.utc)

def setup(db):
    camera=Camera(camera_code="CONFLICT",camera_name="Conflict",parking_position_code="C1",rtsp_url="mock",enabled=True); db.add(camera); db.commit(); repo=ParkingRepository(db); service=ParkingSessionService(repo); return camera,repo,service

def vehicle(track,x=0): return VehicleObservation(str(track),"car",.9,(x,0,x+100,100))

def test_same_track_same_session_is_idempotent(db):
    camera,repo,service=setup(db); session=service.start(camera,vehicle(1),NOW,NOW,vehicle_instance_id="a",tracker_generation=1); result=repo.try_add_track_link(session.id,"1",NOW,tracker_generation=1)
    assert result.success and result.status=="ALREADY_LINKED_TO_SAME_SESSION"

def test_track_owned_by_other_session_returns_conflict_not_exception(db):
    camera,repo,service=setup(db); owner=service.start(camera,vehicle(1),NOW,NOW,vehicle_instance_id="owner",tracker_generation=1); requested=service.start(camera,vehicle(2,200),NOW,NOW,vehicle_instance_id="requested",tracker_generation=1); before=requested.current_track_id; result=repo.try_add_track_link(requested.id,"1",NOW,tracker_generation=1)
    assert not result.success and result.status=="CONFLICT_WITH_OTHER_OPEN_SESSION" and result.existing_session_id==owner.id
    assert requested.current_track_id==before

def test_tracker_generation_scopes_reused_track_id(db):
    camera,repo,service=setup(db); service.start(camera,vehicle(1),NOW,NOW,vehicle_instance_id="old",tracker_generation=1); requested=service.start(camera,vehicle(2,200),NOW,NOW,vehicle_instance_id="new",tracker_generation=2); result=repo.try_add_track_link(requested.id,"1",NOW,tracker_generation=2)
    assert result.success and result.status=="LINKED"

def test_service_conflict_rolls_back_runtime_visible_track_change(db):
    camera,repo,service=setup(db); service.start(camera,vehicle(1),NOW,NOW,vehicle_instance_id="owner",tracker_generation=1); requested=service.start(camera,vehicle(2,200),NOW,NOW,vehicle_instance_id="requested",tracker_generation=1); assert not service.ensure_track(requested,vehicle(1),NOW,tracker_generation=1); assert requested.current_track_id=="2"
