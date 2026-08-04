from datetime import datetime,timezone

import numpy as np
import pytest
from sqlalchemy import create_engine,text

from app.database.models import Camera
from app.database.repositories import CameraRepository
from app.services.camera_manager import preview_interval_ms
from app.services.camera_worker import CameraWorker
from app.services.detector import NullDetector
from app.services.tracker import CentroidTracker


def test_old_camera_migration_gets_default_preview_fps(monkeypatch,tmp_path):
    import app.database.migrations as migrations
    target=create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    with target.begin() as connection:
        connection.execute(text("CREATE TABLE cameras (id INTEGER PRIMARY KEY, camera_code TEXT, camera_name TEXT, parking_position_code TEXT, rtsp_url TEXT, enabled BOOLEAN, processing_fps FLOAT, vehicle_confidence FLOAT, parking_confirm_seconds FLOAT, exit_confirm_seconds FLOAT, track_lost_grace_seconds FLOAT, polygon_points JSON, status TEXT, last_online_at DATETIME, created_at DATETIME, updated_at DATETIME)"))
        connection.execute(text("INSERT INTO cameras (id,camera_code,camera_name,parking_position_code,rtsp_url,enabled,processing_fps) VALUES (1,'OLD','Old','P1','mock',1,8)"))
    monkeypatch.setattr(migrations,"engine",target); migrations.init_database()
    with target.connect() as connection: assert connection.execute(text("SELECT preview_fps FROM cameras WHERE id=1")).scalar_one()==5


def test_preview_fps_10_has_100ms_interval(): assert preview_interval_ms(10)==100


def test_hot_preview_change_keeps_ai_fps_tracker_and_worker():
    camera=Camera(id=1,camera_code="P13",camera_name="P13",parking_position_code="P13",rtsp_url="mock",enabled=True,processing_fps=7,preview_fps=5,track_lost_grace_seconds=3)
    worker=CameraWorker(camera,NullDetector(),CentroidTracker); tracker=worker.tracker
    worker.set_preview_fps(12)
    assert worker.camera.preview_fps==12 and worker.camera.processing_fps==7 and worker.tracker is tracker


def test_slow_ui_overwrites_old_preview_without_queue_growth():
    camera=Camera(id=2,camera_code="SLOW",camera_name="SLOW",parking_position_code="SLOW",rtsp_url="mock",enabled=True,processing_fps=4,preview_fps=10,track_lost_grace_seconds=3)
    worker=CameraWorker(camera,NullDetector(),CentroidTracker); worker.running=True
    for index in range(20):
        frame=np.full((8,8,3),index,dtype=np.uint8); worker._emit_preview(frame,float(index),datetime.now(timezone.utc))
    latest=worker.take_latest_preview()
    assert latest[0]==20 and int(latest[1][0,0,0])==19 and worker.dropped_preview_frames==19 and not hasattr(worker,"preview_queue")


def test_preview_consumption_does_not_stop_ai_tracker():
    camera=Camera(id=3,camera_code="AI",camera_name="AI",parking_position_code="AI",rtsp_url="mock",enabled=True,processing_fps=6,preview_fps=5,track_lost_grace_seconds=3)
    worker=CameraWorker(camera,NullDetector(),CentroidTracker); tracker=worker.tracker; worker.take_latest_preview()
    tracker.update([],frame_index=1)
    assert worker.tracker is tracker and tracker.update_calls==1 and camera.processing_fps==6


@pytest.mark.parametrize("value",[0,16])
def test_preview_fps_outside_range_is_not_saved(db,value):
    repo=CameraRepository(db)
    with pytest.raises(ValueError): repo.add(camera_code=f"BAD{value}",camera_name="Bad",parking_position_code=f"BAD{value}",rtsp_url="mock",preview_fps=value)
