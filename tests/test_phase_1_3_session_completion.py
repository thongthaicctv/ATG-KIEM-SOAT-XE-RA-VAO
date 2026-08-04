from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QTableWidget
from sqlalchemy import func, select

from app.core.constants import EventType, SessionStatus
from app.database.models import Camera, ParkingEvent, ParkingSession
from app.database.repositories import ParkingRepository
from app.services.parking_session_service import ParkingSessionService
from app.services.polygon_engine import VehicleObservation
from app.ui.main_window import MainWindow
from app.utils.time_utils import ensure_utc


T = datetime(2026, 8, 4, 1, 0, tzinfo=timezone.utc)


def _setup(db, vehicle_class="motorcycle"):
    camera = Camera(camera_code="CAM-S", camera_name="Session", parking_position_code="2", rtsp_url="mock", enabled=True)
    db.add(camera); db.commit()
    service = ParkingSessionService(ParkingRepository(db))
    vehicle = VehicleObservation("10", vehicle_class, .9, (1, 1, 5, 5))
    session = service.start(camera, vehicle, T, T)
    return camera, service, session, vehicle


@pytest.mark.parametrize("initial_status", [SessionStatus.ACTIVE, SessionStatus.RECOVERED])
def test_open_session_statuses_complete_to_completed(db, initial_status):
    camera, service, session, vehicle = _setup(db)
    session.status = initial_status
    if initial_status == SessionStatus.RECOVERED: session.event_source = "SYSTEM_RECOVERY"
    db.commit()

    completed = []
    service.signals.session_completed.connect(completed.append)
    service.complete_session(session, camera.id, vehicle, T + timedelta(seconds=61))

    assert session.status == SessionStatus.COMPLETED
    assert ensure_utc(session.left_at) == T + timedelta(seconds=61)
    assert session.parking_duration_seconds == 61
    assert completed == [session.id]
    if initial_status == SessionStatus.RECOVERED: assert session.event_source == "SYSTEM_RECOVERY"


def test_park_end_is_idempotent_and_updates_one_row(db):
    camera, service, session, vehicle = _setup(db)
    service.complete_session(session, camera.id, vehicle, T + timedelta(seconds=30))
    service.complete_session(session, camera.id, vehicle, T + timedelta(seconds=45))

    assert len(service.repo.recent_sessions()) == 1
    park_end_count = db.scalar(select(func.count(ParkingEvent.id)).where(ParkingEvent.session_id == session.id, ParkingEvent.event_type == str(EventType.PARK_END)))
    assert park_end_count == 1
    assert session.parking_duration_seconds == 30


def test_track_change_updates_current_track_without_changing_vehicle_class(db):
    _camera, service, session, _vehicle = _setup(db, "motorcycle")
    changed = service.ensure_track(session, VehicleObservation("11", "car", .95, (2, 2, 6, 6)), T + timedelta(seconds=5))

    assert changed is False
    assert session.current_track_id == "10"
    assert session.vehicle_class == "motorcycle"
    assert len(service.repo.recent_sessions()) == 1


def test_failed_completion_rolls_back_without_false_signal(db, monkeypatch):
    camera, service, session, vehicle = _setup(db)
    completed = []
    service.signals.session_completed.connect(completed.append)
    monkeypatch.setattr(db, "commit", Mock(side_effect=RuntimeError("disk failure")))

    with pytest.raises(RuntimeError, match="disk failure"):
        service.complete_session(session, camera.id, vehicle, T + timedelta(seconds=20))

    assert completed == []
    db.refresh(session)
    assert session.status == SessionStatus.ACTIVE
    assert session.left_at is None


def test_session_signal_refreshes_existing_history_row_without_duplicate(db, qtbot):
    camera, service, session, vehicle = _setup(db)
    fake = SimpleNamespace(history=QTableWidget(0, 9), parking=service.repo, dt=MainWindow.dt)
    fake._set_history_row = lambda row, value: MainWindow._set_history_row(fake, row, value)
    service.signals.session_started.connect(lambda sid: MainWindow.refresh_history_session(fake, sid))
    service.signals.session_completed.connect(lambda sid: MainWindow.refresh_history_session(fake, sid))
    MainWindow.refresh_history_session(fake, session.id)

    service.complete_session(session, camera.id, vehicle, T + timedelta(seconds=25))

    assert fake.history.rowCount() == 1
    assert fake.history.item(0, 0).data(Qt.UserRole) == session.id
    assert fake.history.item(0, 6).text() != "-"
    assert fake.history.item(0, 7).text() == "0.42 phút"
    assert fake.history.item(0, 8).text() == "COMPLETED"


def test_switching_to_history_tab_reloads_latest_data():
    reload_history = Mock()
    fake = SimpleNamespace(history_tab_index=2, reload_history=reload_history)
    MainWindow._on_tab_changed(fake, 1)
    MainWindow._on_tab_changed(fake, 2)
    reload_history.assert_called_once_with()
