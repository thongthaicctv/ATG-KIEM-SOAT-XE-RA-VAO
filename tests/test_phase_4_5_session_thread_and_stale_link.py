"""tests/test_phase_4_5_session_thread_and_stale_link.py

Phase 4.5 - SESSION LINK / SQLALCHEMY TRANSACTION FAILURE - regression tests cho
2 root cause da CONFIRMED qua bang chung Case A LINK_ERROR that
(reports/runtime_ab/case_A_LINK_ERROR_20260831_072320):

  (1) CameraWorker (app/services/camera_worker.py) giu mot doi tuong ORM Camera SONG
      (van gan voi SQLAlchemy Session cua MainWindow.self.db) va doc thuoc tinh cua no
      lien tuc tu MOT QThread rieng (worker.moveToThread(thread)), trong khi main thread
      lien tuc commit()/rollback() tren CHINH Session do (ParkingSessionService.link_track()
      /complete_session()/recover()). SQLAlchemy Session KHONG an toan da luong - da
      CONFIRMED qua tai hien truc tiep (thread doc thuoc tinh ORM + thread khac
      commit/rollback lien tuc tren cung Session gay TREO) - cung mot vi pham nen tang
      voi loi that tren Windows: "This session is in 'prepared' state; no further SQL
      can be emitted within this transaction". Fix: _snapshot_camera() cat dut hoan
      toan lien he Session truoc khi dua camera vao CameraWorker.

  (2) app/ui/main_window.py::on_zone_frame() goi ensure_track()/recover() vao mot
      session DA COMPLETED (session.left_at khong con None) ma KHONG kiem tra truoc -
      CONFIRMED qua log that: "Track ownership conflict ... requested_session=102
      requested_state=COMPLETED ... reason=session_closed" lap lai hang tram lan/phut,
      dan toi self.repo.db.rollback() bi goi voi tan suat cuc cao tren Session dung
      chung, lam trung tam hoa xac suat va bien "prepared state" race o (1) thanh hien
      thuc. Fix: kiem tra session.left_at truoc, xoa runtime.session_id/session_code/
      recovery_session de runtime co the bat dau vong doi MOI hop le, KHONG lam yeu
      guard SESSION_CLOSED o app/database/repositories.py::try_add_track_link().

KHONG doi RTSP/model/imgsz/CUDA/timer/polygon/capacity/schema nao.
"""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from sqlalchemy import select

from app.core.constants import EventType, SessionStatus
from app.database.models import Camera, ParkingEvent, ParkingSession
from app.database.repositories import ParkingRepository
from app.services.parking_session_service import ParkingSessionService
from app.services.polygon_engine import VehicleObservation
from app.services.zone_runtime import ZoneRuntimeState
from app.ui.main_window import MainWindow

T = datetime(2026, 8, 31, 7, 17, 0, tzinfo=timezone.utc)


# ============================================================================
# (1) CameraWorker phai KHONG BAO GIO giu doi tuong ORM Camera song
# ============================================================================

def test_camera_worker_snapshots_camera_and_never_holds_live_orm_instance(db):
    """CameraWorker.__init__ phai cat dut lien he voi SQLAlchemy Session ngay lap tuc:
    self.camera khong duoc la doi tuong ORM Camera goc (khong co _sa_instance_state)."""
    from app.services.camera_worker import CameraWorker

    camera = Camera(camera_code="CAM-1", camera_name="Test", parking_position_code="1",
                     rtsp_url="rtsp://mock", enabled=True, zone_type="MOTORCYCLE_ZONE",
                     capacity=15, parking_confirm_seconds=5, exit_confirm_seconds=2,
                     track_lost_grace_seconds=3, detection_miss_grace_seconds=5,
                     processing_fps=4, preview_fps=5, rotation_degrees=0,
                     use_polygon_roi=False, polygon_points=[[0, 0], [1, 0], [1, 1], [0, 1]],
                     vehicle_confidence=0.5, enable_motorcycles=True,
                     detector_image_size=640, vehicle_polygon_overlap_threshold=0.3,
                     ai_debug_overlay=True)
    db.add(camera)
    db.commit()
    assert hasattr(camera, "_sa_instance_state")  # tien dieu kien: day la ORM song that

    detector = Mock()
    worker = CameraWorker(camera, detector, lambda **kw: Mock())

    assert not hasattr(worker.camera, "_sa_instance_state"), (
        "CameraWorker.camera phai la snapshot THUAN, khong con gan voi SQLAlchemy "
        "Session - neu khong, doc thuoc tinh tu worker thread se dua den TypeError/"
        "'prepared state' khi main thread dong thoi commit/rollback tren cung Session "
        "(CONFIRMED qua tai hien that trong Case A LINK_ERROR)."
    )
    # Gia tri phai duoc sao chep dung, khong doi hanh vi runtime hien co.
    assert worker.camera.rtsp_url == "rtsp://mock"
    assert worker.camera.processing_fps == 4
    assert worker.camera.polygon_points == [[0, 0], [1, 0], [1, 1], [0, 1]]
    assert worker.camera.track_lost_grace_seconds == 3


def test_camera_worker_snapshot_is_independent_of_original_orm_object(db):
    """Ghi vao snapshot (vd set_preview_fps) khong duoc anh huong nguoc lai doi tuong
    ORM goc (va nguoc lai) - xac nhan cat dut hoan toan, khong chi 1 chieu."""
    from app.services.camera_worker import CameraWorker

    camera = Camera(camera_code="CAM-2", camera_name="Test2", parking_position_code="2",
                     rtsp_url="rtsp://mock2", enabled=True, zone_type="CAR_ZONE",
                     capacity=2, parking_confirm_seconds=5, exit_confirm_seconds=2,
                     track_lost_grace_seconds=3, detection_miss_grace_seconds=5,
                     processing_fps=3, preview_fps=5, rotation_degrees=0,
                     use_polygon_roi=False, polygon_points=None, vehicle_confidence=0.5,
                     enable_motorcycles=False, detector_image_size=640,
                     vehicle_polygon_overlap_threshold=0.3, ai_debug_overlay=False)
    db.add(camera)
    db.commit()

    worker = CameraWorker(camera, Mock(), lambda **kw: Mock())
    worker.set_preview_fps(9.0)

    assert worker.camera.preview_fps == 9.0
    assert camera.preview_fps == 5, "Ghi vao snapshot khong duoc lam thay doi ORM goc"


def test_camera_worker_snapshot_thread_safe_under_concurrent_session_commits(db):
    """Tai hien truc tiep tinh huong that: 1 thread lien tuc doc snapshot.camera trong
    khi thread chinh lien tuc commit()/rollback() tren self.db - phai KHONG BAO GIO nem
    loi va KHONG treo (khac han truoc patch, khi doi tuong ORM song bi doc dong thoi)."""
    import threading

    from app.services.camera_worker import CameraWorker

    camera = Camera(camera_code="CAM-3", camera_name="Test3", parking_position_code="3",
                     rtsp_url="rtsp://mock3", enabled=True, zone_type="MOTORCYCLE_ZONE",
                     capacity=15, parking_confirm_seconds=5, exit_confirm_seconds=2,
                     track_lost_grace_seconds=3, detection_miss_grace_seconds=5,
                     processing_fps=4, preview_fps=5, rotation_degrees=0,
                     use_polygon_roi=True, polygon_points=[[0, 0], [1, 0], [1, 1], [0, 1]],
                     vehicle_confidence=0.5, enable_motorcycles=True,
                     detector_image_size=640, vehicle_polygon_overlap_threshold=0.3,
                     ai_debug_overlay=True)
    db.add(camera)
    db.commit()
    worker = CameraWorker(camera, Mock(), lambda **kw: Mock())

    errors = []
    stop = threading.Event()

    def reader_loop():
        n = 0
        while not stop.is_set() and n < 2000:
            _ = worker.camera.rtsp_url; _ = worker.camera.polygon_points; _ = list(worker.camera.polygon_points)
            n += 1

    t = threading.Thread(target=reader_loop, daemon=True)
    t.start()
    try:
        for i in range(200):
            camera.preview_fps = float(i % 5 + 1)
            db.commit()
            db.rollback()
    except Exception as exc:  # pragma: no cover - phai khong bao gio xay ra
        errors.append(exc)
    finally:
        stop.set()
        t.join(timeout=5)

    assert not errors, f"Session commit/rollback bi loi khi worker doc snapshot: {errors}"
    assert not t.is_alive(), "Reader thread khong duoc treo (deadlock) - CONFIRMED bug truoc patch"


# ============================================================================
# (2) Session da COMPLETED khong duoc tiep tuc nhan track-link attempt
# ============================================================================

def _setup(db, vehicle_class="motorcycle"):
    camera = Camera(camera_code="CAM-S", camera_name="Session", parking_position_code="3",
                     rtsp_url="mock", enabled=True)
    db.add(camera); db.commit()
    service = ParkingSessionService(ParkingRepository(db))
    vehicle = VehicleObservation("9", vehicle_class, .9, (1, 1, 5, 5))
    session = service.start(camera, vehicle, T, T)
    return camera, service, session, vehicle


def test_ensure_track_on_completed_session_is_rejected_and_leaves_db_usable(db):
    """Guard SESSION_CLOSED o repositories.py phai TIEP TUC hoat dong (KHONG lam yeu) -
    goi ensure_track() vao 1 session da COMPLETED phai bi tu choi, va quan trong hon:
    Session phai VAN CON DUNG DUOC cho thao tac tiep theo (khong bi 'prepared'/loi)."""
    camera, service, session, vehicle = _setup(db)
    service.complete_session(session, camera.id, vehicle, T + timedelta(seconds=30))
    assert session.status == SessionStatus.COMPLETED and session.left_at is not None

    new_vehicle = VehicleObservation("9", "motorcycle", .9, (1, 1, 5, 5))
    result = service.ensure_track(session, new_vehicle, T + timedelta(seconds=31))
    assert result is False

    # DB Session phai con dung duoc ngay sau do cho MOT thao tac khac (khong con 'prepared').
    other_vehicle = VehicleObservation("55", "motorcycle", .9, (10, 10, 20, 20))
    new_session = service.start(camera, other_vehicle, T + timedelta(seconds=32), T + timedelta(seconds=32))
    assert new_session.id != session.id
    assert len(service.repo.recent_sessions()) == 2


def test_on_zone_frame_clears_stale_reference_to_completed_session(db):
    """Tai hien CHINH XAC tinh huong that (session=102 that): runtime van giu
    action.session_id tro toi mot session DA COMPLETED. on_zone_frame() khong duoc
    goi ensure_track()/recover() lap lai vao no - phai xoa runtime.session_id va
    KHONG tao ra canh bao 'Track ownership conflict' lap lai vo han."""
    camera = Camera(camera_code="CAM-STALE", camera_name="Stale", parking_position_code="3",
                     rtsp_url="mock", enabled=True, zone_type="MOTORCYCLE_ZONE", capacity=15,
                     parking_confirm_seconds=5, exit_confirm_seconds=2, track_lost_grace_seconds=3,
                     detection_miss_grace_seconds=5, processing_fps=4, preview_fps=5)
    db.add(camera); db.commit()
    parking = ParkingRepository(db)
    session_service = ParkingSessionService(parking)
    vehicle = VehicleObservation("9", "motorcycle", .9, (1, 1, 5, 5))
    session = session_service.start(camera, vehicle, T, T)
    session_service.complete_session(session, camera.id, vehicle, T + timedelta(seconds=10))
    assert session.left_at is not None  # da COMPLETED - dung nhu session=102 that

    from app.services.zone_runtime import VehicleRuntimeState
    runtime = VehicleRuntimeState(runtime_id="stale-runtime", session_id=session.id,
                                   session_code=session.session_code, vehicle_class="motorcycle",
                                   first_seen_at=T)
    fake = SimpleNamespace(
        cameras=SimpleNamespace(get=lambda cid: camera),
        zones={camera.id: SimpleNamespace(process=lambda *a, **kw: [
            SimpleNamespace(kind="OBSERVED", runtime_id="stale-runtime", vehicle=vehicle,
                             session_id=session.id, occurred_at=T + timedelta(seconds=11)),
        ], vehicles={"stale-runtime": runtime}, ignored=[], ignored_track_ids_logged=set(),
            reconnect_generation=0, occupancy_snapshot=lambda open_db: SimpleNamespace(
                unmatched_open_session_count=0, observed_vehicle_count=1, candidate_count=0,
                confirmed_occupancy_count=0, leaving_session_count=0, recovery_pending_count=0,
                zone_state="OK", session_health_state="OK"), capacity=15),
        },
        last_payload={}, parking=parking, session_service=session_service, db=db,
        snapshots=SimpleNamespace(save=lambda *a, **kw: None),
        log=__import__("logging").getLogger("test"), last_occupancy_signature={},
        monitor=SimpleNamespace(update_camera=lambda *a, **kw: None),
    )

    MainWindow.on_zone_frame(fake, camera.id, object(), {"time": T + timedelta(seconds=11), "stats": {}})

    assert runtime.session_id is None, "Runtime phai duoc xoa tham chieu toi session da dong"
    assert runtime.session_code is None
    assert runtime.recovery_session is None


def test_phase_4_2_ownership_tests_remain_valid_guard_behavior(db):
    """Guard xung dot ownership giua 2 session CON MO (Phase 4.2) phai KHONG doi hanh
    vi - patch Phase 4.5 chi xu ly truong hop session DA DONG, khong dung cham toi
    nhanh xung dot giua 2 session dang mo."""
    camera, service, session_a, vehicle_a = _setup(db)
    # session_b bat dau voi mot track KHAC (khong bi guard "track_owned_by_open_session"
    # trong start() chan lai) roi moi thu chiem track "9" o cap repository - dung nhu
    # kich ban Phase 4.2 that (2 session dang mo tranh chap 1 track_id).
    vehicle_b = VehicleObservation("99", "motorcycle", .9, (50, 50, 60, 60))
    session_b = service.start(camera, vehicle_b, T + timedelta(seconds=1), T + timedelta(seconds=1))
    assert session_b.id != session_a.id

    result = service.repo.try_add_track_link(session_b.id, "9", T + timedelta(seconds=2))
    assert result.success is False
    assert result.reason == "track_owned_by_other_open_session"


def test_phase_4_4_naive_aware_still_pass_after_phase_4_5(db):
    """Xac nhan patch Phase 4.4 (ensure_utc trong restore_session) KHONG bi hoan lai."""
    from app.services.zone_runtime import ZoneRuntimeState

    zone = ZoneRuntimeState(SimpleNamespace(id=3, zone_type="MOTORCYCLE_ZONE", capacity=15,
                                             parking_confirm_seconds=5, exit_confirm_seconds=2,
                                             detection_miss_grace_seconds=5, track_lost_grace_seconds=3), 1)
    naive_session = SimpleNamespace(vehicle_instance_id=None, id=1, session_code="T-1",
                                     current_track_id="1", stabilized_vehicle_class="motorcycle",
                                     vehicle_class="motorcycle",
                                     entered_at=datetime(2026, 8, 31, 0, 0, 0),  # NAIVE
                                     parked_at=datetime(2026, 8, 31, 0, 0, 0),
                                     last_seen_at=datetime(2026, 8, 31, 0, 0, 0),
                                     last_confirmed_seen_at=None, confirmed_bbox=(0, 0, 1, 1),
                                     confirmed_anchor=(0, 1), confirmed_bbox_size=(1, 1),
                                     vehicle_histogram=None, vehicle_perceptual_hash=None)
    runtime = zone.restore_session(naive_session)
    assert runtime.first_seen_at.tzinfo is not None
