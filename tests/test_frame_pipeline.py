from datetime import datetime,timedelta,timezone
import numpy as np

from app.database.models import Camera
from app.services.camera_worker import CameraWorker
from app.services.detector import NullDetector
from app.services.parking_state_engine import ParkingStateEngine
from app.services.polygon_engine import VehicleObservation
from app.services.rtsp_capture import RtspCapture
from app.services.tracker import CentroidTracker
from app.utils.image_utils import crop_polygon_roi


def test_capture_queue_keeps_only_latest_frame():
    capture=RtspCapture("mock")
    for index in range(10): capture._publish((index,float(index),None))
    assert capture.frames.maxsize==1 and capture.queue_size==1 and capture.dropped_capture_frames==9
    assert capture.frames.get_nowait()[0]==9


def test_slow_preview_consumer_drops_old_preview_without_touching_ai_tracker():
    camera=Camera(id=1,camera_code="PIPE",camera_name="Pipeline",parking_position_code="P1",rtsp_url="mock",enabled=True,processing_fps=7,track_lost_grace_seconds=3,rotation_degrees=0)
    worker=CameraWorker(camera,NullDetector(),CentroidTracker); frame=np.zeros((20,30,3),dtype=np.uint8)
    worker.running=True
    for index in range(12):
        frame[:]=index; worker._emit_preview(frame.copy(),float(index),datetime.now(timezone.utc))
        # AI tracker vẫn được update độc lập trong khi UI chưa lấy preview.
        worker.tracker.update([],frame_index=index)
    latest=worker.take_latest_preview()
    assert latest[0]==12 and int(latest[1][0,0,0])==11
    assert worker.dropped_preview_frames==11 and worker.tracker.update_calls==12


def test_parking_timer_uses_monotonic_not_wall_clock():
    vehicle=VehicleObservation("1","car",.9,(0,0,10,10)); engine=ParkingStateEngine(5,2,1,0)
    wall=datetime(2026,7,20,10,0,tzinfo=timezone.utc)
    engine.update(vehicle,wall,monotonic_now=100.0)
    # Wall clock lùi một giờ nhưng monotonic tăng đủ 5 giây.
    result=engine.update(vehicle,wall-timedelta(hours=1),monotonic_now=105.0)
    assert result.action=="PARK_START_RECOVERY"


def test_polygon_roi_expands_ten_percent_and_keeps_original_offset():
    frame=np.zeros((1000,2000,3),dtype=np.uint8); polygon=[[.25,.20],[.75,.20],[.75,.80],[.25,.80]]
    crop,offset=crop_polygon_roi(frame,polygon,.10)
    assert offset==(400,140) and crop.shape[:2]==(720,1200)
    # Bbox ROI (100,100,300,300) được worker trả về frame gốc bằng cách cộng offset.
    assert (100+offset[0],100+offset[1],300+offset[0],300+offset[1])==(500,240,700,440)
