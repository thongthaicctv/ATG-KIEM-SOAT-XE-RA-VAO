from datetime import datetime,timedelta,timezone

from app.database.models import Camera
from app.database.repositories import ParkingRepository
from app.services.camera_worker import CameraWorker
from app.services.detector import Detection,NullDetector
from app.services.parking_session_service import ParkingSessionService
from app.services.polygon_engine import VehicleObservation
from app.services.tracker import CentroidTracker

T=datetime(2026,7,20,tzinfo=timezone.utc)


def detection(x=100): return Detection((x,100,x+120,300),.8,"motorcycle")


def test_continuous_detection_keeps_track_id():
    tracker=CentroidTracker(max_missed=10); ids=[]
    for frame in range(20): ids.append(tracker.update([detection(100+frame*2)],frame_index=frame)[0].track_id)
    assert len(set(ids))==1 and tracker.update_calls==20


def test_short_detection_loss_reuses_track_id():
    tracker=CentroidTracker(max_missed=10); first=tracker.update([detection()],0)[0].track_id
    for frame in range(1,7): assert tracker.update([],frame)==[]
    recovered=tracker.update([detection(108)],7)[0]
    assert recovered.track_id==first and recovered.track_age==8


def test_new_track_is_linked_without_new_session(db):
    camera=Camera(camera_code="T12",camera_name="Tracker",parking_position_code="T12",rtsp_url="mock",enabled=True); db.add(camera); db.commit()
    service=ParkingSessionService(ParkingRepository(db)); first=VehicleObservation("1","motorcycle",.8,(1,1,5,5)); session=service.start(camera,first,T,T)
    changed=VehicleObservation("2","motorcycle",.8,(1,1,5,5)); assert service.ensure_track(session,changed,T+timedelta(seconds=2))
    assert service.repo.active_for_camera(camera.id).id==session.id and len(session.track_links)==2


def test_worker_creates_tracker_exactly_once():
    calls=[]
    def factory(**kwargs): calls.append(kwargs); return CentroidTracker(**kwargs)
    camera=Camera(id=99,camera_code="ONE",camera_name="One",parking_position_code="ONE",rtsp_url="mock",enabled=True,processing_fps=2.35,track_lost_grace_seconds=5)
    worker=CameraWorker(camera,NullDetector(),factory)
    assert len(calls)==1 and worker.tracker_buffer_frames==12

