"""tests/test_phase_4_2_hotfix.py

Phase 4.2 - HOTFIX POWERSHELL... khong, day la hotfix CASE A FULL RUNTIME AUDIT.
Regression test cho 2 root cause CONFIRMED va da fix trong phase nay:

  (1) GUI "AI: cpu" du CUDA that su duoc dung (app/ui/main_window.py):
      status bar duoc build 1 lan duy nhat trong MainWindow.__init__, TRUOC KHI bat ky
      camera nao xu ly frame dau tien - tai thoi diem do YoloDetector.actual_device van
      con la gia tri "cpu" tu luc load model (Ultralytics chi move model len GPU that su
      o lan predict() dau tien, khong phai luc YOLO(model_path) construct). self.device
      (duoc resolve/validate ngay tai __init__, KHONG phu thuoc lazy-load cua Ultralytics)
      moi la nguon su that dung. Test o tests/test_main_window_startup.py (da bo sung 1
      assertion, khong sua test cu).

  (2) "Track ownership conflict" GIA do stale VehicleTrackLink (app/database/repositories.py):
      get_open_session_for_track() coi MOI track_id ma 1 session TUNG duoc lien ket qua
      (ke ca da chuyen sang track_id khac tu lau) la "cua" session do VINH VIEN, vi cot
      ended_at (da co san trong schema) chua bao gio duoc ghi o dau ca. Khi track_id nho
      (so nguyen bi tracker tai su dung sau reconnect/track churn - xac nhan qua audit
      Case A: RTSP reconnect xay ra ~15-20 lan trong 1 lan chay Case A ~20 phut) trung
      voi lich su cu cua 1 session KHAC (van con "open" trong DB nhung khong con runtime
      nao dang theo doi no nua), main_window.py bao "Track ownership conflict" LAP LAI
      MOI FRAME, khong bao gio tu giai quyet.

      Fix: (a) get_open_session_for_track() them dieu kien VehicleTrackLink.ended_at IS
      NULL; (b) try_add_track_link() danh dau ended_at cho cac track link CU (track_id
      KHAC, CUNG session, CUNG generation) khi tao link MOI - giai phong quyen so huu
      track_id cu dung luc, khong can cho session do tu dong "het han".

Test cac ham nay TRUC TIEP qua ParkingRepository/ParkingSessionService voi sqlite in-memory
(fixture `db` tu conftest.py) - khong RTSP that, khong GPU that, giong dung pattern cua
tests/test_phase_1_4_track_session_conflict.py (da co san, KHONG bi sua trong phase nay).
"""
from datetime import datetime, timezone

from app.database.models import Camera, VehicleTrackLink
from app.database.repositories import ParkingRepository
from app.services.parking_session_service import ParkingSessionService
from app.services.polygon_engine import VehicleObservation

NOW = datetime(2026, 8, 30, tzinfo=timezone.utc)


def setup(db):
    camera = Camera(camera_code="HOTFIX42", camera_name="Hotfix42", parking_position_code="H1", rtsp_url="mock", enabled=True)
    db.add(camera)
    db.commit()
    repo = ParkingRepository(db)
    service = ParkingSessionService(repo)
    return camera, repo, service


def vehicle(track, x=0):
    return VehicleObservation(str(track), "car", .9, (x, 0, x + 100, 100))


# --- (2a) get_open_session_for_track bo qua track link da ended_at ------------------

def test_ended_track_link_is_not_reported_as_owner(db):
    camera, repo, service = setup(db)
    session = service.start(camera, vehicle(1), NOW, NOW, vehicle_instance_id="a", tracker_generation=1)
    link = repo.db.query(VehicleTrackLink).filter_by(session_id=session.id, tracker_track_id="1").one()
    link.ended_at = NOW
    repo.db.commit()
    owner = repo.get_open_session_for_track(camera.id, "1", tracker_generation=1)
    assert owner is None


def test_active_track_link_still_reported_as_owner(db):
    camera, repo, service = setup(db)
    session = service.start(camera, vehicle(1), NOW, NOW, vehicle_instance_id="a", tracker_generation=1)
    owner = repo.get_open_session_for_track(camera.id, "1", tracker_generation=1)
    assert owner is not None and owner.id == session.id


# --- (2b) try_add_track_link giai phong track_id cu cua CHINH session khi chuyen track --

def test_try_add_track_link_ends_previous_link_of_same_session_same_generation(db):
    camera, repo, service = setup(db)
    session = service.start(camera, vehicle(1), NOW, NOW, vehicle_instance_id="a", tracker_generation=1)
    old_link = repo.db.query(VehicleTrackLink).filter_by(session_id=session.id, tracker_track_id="1").one()
    assert old_link.ended_at is None
    result = repo.try_add_track_link(session.id, "2", NOW, tracker_generation=1)
    assert result.success and result.status == "LINKED"
    repo.db.refresh(old_link)
    assert old_link.ended_at is not None
    new_link = repo.db.query(VehicleTrackLink).filter_by(session_id=session.id, tracker_track_id="2").one()
    assert new_link.ended_at is None


def test_session_moving_to_new_track_releases_old_track_for_other_session(db):
    """Tai hien chinh xac bug da fix: session A giu track '1', chuyen sang track '2'
    (vd sau reconnect/track churn). Truoc fix, track '1' van vinh vien bi coi la "cua"
    session A, nen 1 session B (xe KHAC) khong bao gio duoc phep dung track_id '1' nua du
    session A da khong con dung no - gay AB_DATABASE... khong, gay "Track ownership
    conflict" gia. Sau fix: track '1' phai duoc giai phong ngay khi session A chuyen sang
    track '2', cho phep session B dung lai track_id '1' binh thuong."""
    camera, repo, service = setup(db)
    session_a = service.start(camera, vehicle(1), NOW, NOW, vehicle_instance_id="a", tracker_generation=1)
    result = repo.try_add_track_link(session_a.id, "2", NOW, tracker_generation=1)
    assert result.success

    session_b = service.start(camera, vehicle(99, 500), NOW, NOW, vehicle_instance_id="b", tracker_generation=1)
    result_b = repo.try_add_track_link(session_b.id, "1", NOW, tracker_generation=1)
    assert result_b.success and result_b.status == "LINKED", (
        "track_id '1' phai duoc giai phong sau khi session A chuyen sang track '2' - "
        "khong con la 'Track ownership conflict' gia nua"
    )


def test_try_add_track_link_does_not_end_other_sessions_links(db):
    """An toan pham vi: giai phong track_id cu CHI ap dung cho CHINH session dang tao
    link moi - khong duoc dong cham track link cua session KHAC (du cung generation)."""
    camera, repo, service = setup(db)
    session_a = service.start(camera, vehicle(1), NOW, NOW, vehicle_instance_id="a", tracker_generation=1)
    session_b = service.start(camera, vehicle(2, 500), NOW, NOW, vehicle_instance_id="b", tracker_generation=1)
    link_b = repo.db.query(VehicleTrackLink).filter_by(session_id=session_b.id, tracker_track_id="2").one()
    assert link_b.ended_at is None

    result = repo.try_add_track_link(session_a.id, "3", NOW, tracker_generation=1)
    assert result.success

    repo.db.refresh(link_b)
    assert link_b.ended_at is None, "track link cua session KHAC khong duoc bi dong"


def test_try_add_track_link_does_not_end_links_across_generations(db):
    """An toan pham vi: giai phong track_id cu CHI ap dung trong CUNG tracker_generation -
    khong duoc dong track link cua 1 generation khac (vd truoc lan reconnect truoc do)."""
    camera, repo, service = setup(db)
    session = service.start(camera, vehicle(1), NOW, NOW, vehicle_instance_id="a", tracker_generation=1)
    link_gen1 = repo.db.query(VehicleTrackLink).filter_by(session_id=session.id, tracker_track_id="1").one()

    result = repo.try_add_track_link(session.id, "1", NOW, tracker_generation=2)
    assert result.success and result.status == "LINKED"

    repo.db.refresh(link_gen1)
    assert link_gen1.ended_at is None, "track link cua generation KHAC khong duoc bi dong"


def test_conflict_check_still_fires_for_genuinely_active_owner(db):
    """Guard KHONG bi pha: 1 session dang thuc su giu (active, ended_at IS NULL) 1
    track_id van phai chan session khac tranh chap track_id do - guard nay dung, chi du
    lieu (ended_at chua bao gio duoc ghi) la sai, da duoc fix o day."""
    camera, repo, service = setup(db)
    owner = service.start(camera, vehicle(1), NOW, NOW, vehicle_instance_id="owner", tracker_generation=1)
    requested = service.start(camera, vehicle(2, 500), NOW, NOW, vehicle_instance_id="requested", tracker_generation=1)
    result = repo.try_add_track_link(requested.id, "1", NOW, tracker_generation=1)
    assert not result.success
    assert result.status == "CONFLICT_WITH_OTHER_OPEN_SESSION"
    assert result.existing_session_id == owner.id
