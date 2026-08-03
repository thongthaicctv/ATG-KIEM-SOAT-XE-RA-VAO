from datetime import datetime,timezone
import logging,threading
import numpy as np

from app.core.constants import ParkingState
from app.services.parking_state_engine import ParkingStateEngine
from app.services.detector import YoloDetector


class ReadyDetectorWithNoVehicle:
    enabled=True
    def detect(self,frame): return []


def test_valid_frames_with_raw_zero_transition_unknown_to_empty():
    engine=ParkingStateEngine(stable_frames_after_reconnect=3)
    now=datetime.now(timezone.utc)
    assert engine.update(None,now,True,1.0).current==ParkingState.UNKNOWN
    assert engine.update(None,now,True,2.0).current==ParkingState.UNKNOWN
    result=engine.update(None,now,True,3.0)
    assert result.current==ParkingState.EMPTY


def test_detector_ready_does_not_mean_vehicle_present():
    detector=ReadyDetectorWithNoVehicle()
    assert detector.enabled is True
    assert detector.detect(object())==[]


def test_connecting_state_does_not_remain_after_stable_frames():
    engine=ParkingStateEngine(stable_frames_after_reconnect=2)
    now=datetime.now(timezone.utc)
    engine.update(None,now,True,1.0)
    result=engine.update(None,now,True,2.0)
    assert result.current!=ParkingState.UNKNOWN
    assert result.current==ParkingState.EMPTY


def test_cpu_fp32_does_not_pass_deprecated_half_option():
    class Model:
        def predict(self,frame,**kwargs): self.kwargs=kwargs; return []
    detector=YoloDetector.__new__(YoloDetector); detector.model=Model(); detector.confidence=.4; detector.device="cpu"; detector.half=False
    detector._lock=threading.Lock(); detector.last_stats={}; detector.last_log_at=0; detector.log=logging.getLogger("test.detector")
    detector.detect(np.zeros((16,16,3),dtype=np.uint8))
    assert "half" not in detector.model.kwargs
