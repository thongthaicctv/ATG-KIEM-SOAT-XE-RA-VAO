from datetime import datetime,timedelta,timezone
import numpy as np

from app.database.models import Camera
from app.database.repositories import ParkingRepository
from app.services.detector import Detection,build_detector,is_allowed_vehicle_class
from app.services.parking_session_service import ParkingSessionService
from app.services.parking_state_engine import ParkingStateEngine
from app.services.polygon_engine import PolygonEngine,VehicleObservation
from app.utils.geometry import denormalize_points
from app.utils.image_utils import annotate_frame

T=datetime(2026,7,20,tzinfo=timezone.utc)
MOTORCYCLE=VehicleObservation("7","motorcycle",.8,(200,100,400,500))


def test_motorcycle_allowed_and_person_filtered():
    assert is_allowed_vehicle_class("Motorcycle")
    assert not is_allowed_vehicle_class("person")
    assert not is_allowed_vehicle_class("motorcycle",enable_motorcycles=False)


def test_detection_without_track_has_debug_overlay():
    frame=np.zeros((300,500,3),dtype=np.uint8)
    detection=Detection((50,50,200,250),.75,"motorcycle")
    result=annotate_frame(frame,detections=[detection],debug={"state":"EMPTY"})
    assert np.any(result!=frame)


def test_normalized_polygon_matches_detector_frame_not_widget():
    normalized=[(.1,.1),(.9,.1),(.9,.9),(.1,.9)]
    assert denormalize_points(normalized,1920,1080)==[(192,108),(1728,108),(1728,972),(192,972)]


def test_anchor_or_overlap_accepts_motorcycle():
    polygon=[(100,100),(500,100),(500,600),(100,600)]
    candidate=PolygonEngine(polygon,.20).primary([MOTORCYCLE])
    assert candidate and candidate.anchor_inside and candidate.overlap>0.20


def test_startup_motorcycle_creates_recovery_action():
    engine=ParkingStateEngine(5,2,1,3)
    assert engine.update(MOTORCYCLE,T).current.value=="VEHICLE_CANDIDATE"
    result=engine.update(MOTORCYCLE,T+timedelta(seconds=5))
    assert result.action=="PARK_START_RECOVERY"


def test_track_lost_grace_prevents_early_leaving():
    engine=ParkingStateEngine(5,2,1,3); engine.update(MOTORCYCLE,T); engine.update(MOTORCYCLE,T+timedelta(seconds=5))
    assert engine.update(None,T+timedelta(seconds=6)).action=="TRACK_LOST"
    assert engine.update(None,T+timedelta(seconds=8)).current.value=="OCCUPIED"
    assert engine.update(None,T+timedelta(seconds=9)).current.value=="OCCUPIED"
    assert engine.update(None,T+timedelta(seconds=12)).current.value=="LEAVING"


def test_system_recovery_session_source(db):
    camera=Camera(camera_code="REC",camera_name="Recovery",parking_position_code="R01",rtsp_url="mock",enabled=True)
    db.add(camera); db.commit(); service=ParkingSessionService(ParkingRepository(db))
    session=service.start(camera,MOTORCYCLE,T,T+timedelta(seconds=5),event_source="SYSTEM_RECOVERY")
    assert session.event_source=="SYSTEM_RECOVERY"


def test_missing_model_disables_detector():
    detector=build_detector("missing-phase-1-1-model.pt",.30,True)
    assert not detector.enabled and detector.error
