"""tests/test_phase_4_7d_occupancy_counting.py

Phase 4.7D - OCCUPANCY COUNTING SEMANTICS MINIMAL HOTFIX.

Boi canh: mot kiem tra doi chieu Windows xac dinh (deterministic cross-check, KHONG
dung camera/DB that) chung minh mot lan mat detect/track TAM THOI tren mot xe DANG
DAU (session con ACTIVE, PARK_END CHUA xay ra) lam confirmed_occupancy roi tu 1 -> 0
-> 1 - day la loi ngu nghia DEM (counting semantics) trong calculate_zone_occupancy()
(app/services/zone_occupancy.py), KHONG phai loi vong doi session (Phase 4.7C/HOTFIX 1
da xac nhan vong doi session dang dung).

Bat bien nghiep vu (Section 2 cua yeu cau Phase 4.7D):
    OCCUPIED + session con active   => tinh la dang chiem cho
    LEAVING  + session con active   => VAN tinh la dang chiem cho (cho den khi PARK_END)
    PARK_END / session da hoan tat  => KHONG con tinh nua

Fix: them is_leaving_with_active_session() va tap "effective_parking_occupancy" =
freshly_observed_occupying (OCCUPIED, quan sat TUOI - khong doi, is_identity_currently_occupying()
GIU NGUYEN) HOP VOI cac runtime LEAVING con session_id VA recovery_session is None (tuc
la runtime TUNG duoc xac nhan song it nhat 1 lan, chi la vua tam thoi mat dau ra - PHAN
BIET voi mot session PHUC HOI tu DB (restore_session()) ma CHUA BAO GIO duoc xac nhan
lai, van phai tiep tuc bao mismatch that su, xem test_unconfirmed_recovery... ben duoi
va 2 test hoi quy da co: test_phase_4_3_case_a_v2.py::
test_runtime_mismatch_returns_to_zero_after_recovered_session_times_out va
test_phase_4_7c_session_reconciliation.py::test_session_runtime_mismatch_warning_reappears_on_real_state_change).

unmatched_open_session_count duoc tinh lai tren CUNG tap effective_parking_occupancy
do (khong con chi tren freshly_observed_occupying nhu truoc) de mot session LEAVING
hop le khong con bi dem la "unmatched" gia.

KHONG doi: ParkingSessionService.complete_session(), ParkingRepository.end_open_track_links(),
VehicleTrackLink lifecycle, session ownership, duplicate-session guard, MultiVehicleAssociationService,
RTSP/FFmpeg/YOLO/CUDA, polygon, capacity, parking_confirm_seconds/exit_confirm_seconds/
track_lost_grace_seconds/detection_miss_grace_seconds, schema DB. Xem bao cao hotfix
Phase 4.7D cho xac nhan chi tiet.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from sqlalchemy import select

from app.database.models import ParkingSession
from app.database.repositories import ParkingRepository
from app.services.parking_session_service import ParkingSessionService
from app.services.polygon_engine import VehicleObservation
from app.services.zone_runtime import ZoneRuntimeState
from app.ui.main_window import MainWindow

NOW = datetime(2026, 9, 9, tzinfo=timezone.utc)
T = datetime(2026, 9, 9, 12, 0, tzinfo=timezone.utc)


def _bare_camera(**overrides):
    values = dict(id=1, zone_type="CAR_ZONE", capacity=5, parking_confirm_seconds=1.0,
                  exit_confirm_seconds=1.0, detection_miss_grace_seconds=1.0, track_lost_grace_seconds=1.0)
    values.update(overrides)
    return SimpleNamespace(**values)


def _car(track, x=0.0):
    return VehicleObservation(str(track), "car", .9, (x, 0, x + 10, 10))


def _park_vehicle(zone, track, x=0.0):
    """Dan 1 candidate qua CANDIDATE -> OCCUPIED (PARK_START) bang 3 tick on dinh cach
    nhau >=parking_confirm_seconds (khop minimum_candidate_frames=3 mac dinh), roi gan
    session_id gia dung y het cach MainWindow.on_zone_frame() lam ngay sau khi
    ParkingSessionService.start() tra ve - de calculate_zone_occupancy() thay mot
    runtime co session that su ma khong can di qua toan bo DB/session-service."""
    actions = []
    for i in range(3):
        actions = zone.process([_car(track, x)], NOW, float(i))
    started = [a for a in actions if a.kind == "PARK_START"]
    assert started, f"expected PARK_START on 3rd tick, got kinds={[a.kind for a in actions]}"
    runtime = zone.vehicles[started[0].runtime_id]
    runtime.session_id = 1000 + int(track)
    return runtime


def _camera(db, **overrides):
    from app.database.models import Camera
    values = dict(camera_code="CAM-47D", camera_name="Test", parking_position_code="1",
                  rtsp_url="rtsp://user:pass@example.invalid/s", zone_type="MOTORCYCLE_ZONE", capacity=15,
                  parking_confirm_seconds=1.0, exit_confirm_seconds=1.0, track_lost_grace_seconds=1.0,
                  detection_miss_grace_seconds=1.0, occupancy_observation_grace_seconds=2.0)
    values.update(overrides)
    camera = Camera(**values)
    db.add(camera); db.commit()
    return camera


def _service(db):
    return ParkingSessionService(ParkingRepository(db))


def _fake_window(db, camera, zone):
    import logging
    return SimpleNamespace(
        cameras=SimpleNamespace(get=lambda cid: camera),
        zones={camera.id: zone},
        last_payload={}, parking=ParkingRepository(db), session_service=_service(db), db=db,
        snapshots=SimpleNamespace(save=lambda *a, **kw: None),
        log=logging.getLogger("test_phase_4_7d"), last_occupancy_signature={},
        monitor=SimpleNamespace(update_camera=lambda *a, **kw: None),
    )


def moto(track, x=0.0):
    return VehicleObservation(str(track), "motorcycle", .9, (x, 0, x + 10, 10))


# --- TEST A: one temporary miss must not drop confirmed occupancy ----------------

def test_temporary_detection_miss_does_not_drop_confirmed_occupancy():
    zone = ZoneRuntimeState(_bare_camera(capacity=5), stable_frames_after_reconnect=1)
    runtime = _park_vehicle(zone, track=1)
    open_db = 1

    occ = zone.occupancy_snapshot(open_db)
    assert occ.confirmed_occupancy_count == 1 and occ.unmatched_open_session_count == 0 and occ.session_health_state == "OK"

    # mot lan mat detect duy nhat -> LEAVING (session van con ACTIVE, PARK_END CHUA xay ra)
    zone.process([], NOW, 3.0)
    assert runtime.state == "LEAVING"
    occ_leaving = zone.occupancy_snapshot(open_db)
    assert occ_leaving.confirmed_occupancy_count == 1
    assert occ_leaving.leaving_session_count == 1
    assert occ_leaving.unmatched_open_session_count == 0
    assert occ_leaving.session_health_state == "OK"

    # detection quay lai TRUOC khi het han exit-confirm
    zone.process([_car(1)], NOW, 4.0)
    assert runtime.state == "OCCUPIED"
    occ_recovered = zone.occupancy_snapshot(open_db)
    assert occ_recovered.confirmed_occupancy_count == 1
    assert occ_recovered.unmatched_open_session_count == 0
    assert occ_recovered.session_health_state == "OK"


# --- TEST B: real confirmed departure still completes and zeroes occupancy -------

def test_confirmed_departure_still_zeroes_occupancy_and_closes_db_session(db):
    camera = _camera(db)
    zone = ZoneRuntimeState(camera, stable_frames_after_reconnect=1)
    fake = _fake_window(db, camera, zone)

    now = T; tick = 0.0
    for _ in range(3):
        now += timedelta(seconds=1); tick += 1.0
        MainWindow.on_zone_frame(fake, camera.id, object(), {"time": now, "monotonic_time": tick, "polygon_candidates": [moto(1)], "stats": {}})

    session = db.scalar(select(ParkingSession).where(ParkingSession.camera_id == camera.id))
    assert session is not None and session.left_at is None
    open_db = lambda: len(fake.parking.find_open_sessions_for_position(camera.id, camera.parking_position_code))
    assert zone.occupancy_snapshot(open_db()).confirmed_occupancy_count == 1

    # mot lan mat detect - TRUOC nguong PARK_END, occupancy KHONG duoc roi ve 0
    now += timedelta(seconds=1); tick += 1.0
    MainWindow.on_zone_frame(fake, camera.id, object(), {"time": now, "monotonic_time": tick, "polygon_candidates": [], "stats": {}})
    assert zone.occupancy_snapshot(open_db()).confirmed_occupancy_count == 1

    # het han max(track_lost_grace,detection_miss_grace)+exit_confirm (=2s o day) ma
    # KHONG co detection nao quay lai -> PARK_END phai xay ra qua duong MainWindow/
    # session-service binh thuong (KHONG doi gi trong Phase 4.7C/HOTFIX 1)
    for _ in range(4):
        now += timedelta(seconds=1); tick += 1.0
        MainWindow.on_zone_frame(fake, camera.id, object(), {"time": now, "monotonic_time": tick, "polygon_candidates": [], "stats": {}})

    db.refresh(session)
    assert session.left_at is not None and session.status == "COMPLETED"
    assert open_db() == 0
    occ_after = zone.occupancy_snapshot(open_db())
    assert occ_after.confirmed_occupancy_count == 0
    assert occ_after.unmatched_open_session_count == 0


# --- TEST C: two independent vehicles - one leaving must not affect the other ----

def test_two_independent_vehicles_leaving_one_does_not_affect_the_other(db):
    camera = _camera(db)
    zone = ZoneRuntimeState(camera, stable_frames_after_reconnect=1)
    fake = _fake_window(db, camera, zone)

    now = T; tick = 0.0
    for _ in range(3):
        now += timedelta(seconds=1); tick += 1.0
        MainWindow.on_zone_frame(fake, camera.id, object(), {"time": now, "monotonic_time": tick, "polygon_candidates": [moto(1, x=0), moto(2, x=100)], "stats": {}})

    sessions = list(db.scalars(select(ParkingSession).where(ParkingSession.camera_id == camera.id)))
    assert len(sessions) == 2
    session_a = next(s for s in sessions if s.current_track_id == "1")
    session_b = next(s for s in sessions if s.current_track_id == "2")
    open_db = lambda: len(fake.parking.find_open_sessions_for_position(camera.id, camera.parking_position_code))
    assert zone.occupancy_snapshot(open_db()).confirmed_occupancy_count == 2

    # xe A (track 1) tam thoi mat detect, xe B (track 2) van duoc quan sat binh thuong
    now += timedelta(seconds=1); tick += 1.0
    MainWindow.on_zone_frame(fake, camera.id, object(), {"time": now, "monotonic_time": tick, "polygon_candidates": [moto(2, x=100)], "stats": {}})
    occ_partial = zone.occupancy_snapshot(open_db())
    assert occ_partial.confirmed_occupancy_count == 2  # A van tinh (LEAVING+session active), B van OCCUPIED tuoi
    assert occ_partial.leaving_session_count == 1

    # A quay lai
    now += timedelta(seconds=1); tick += 1.0
    MainWindow.on_zone_frame(fake, camera.id, object(), {"time": now, "monotonic_time": tick, "polygon_candidates": [moto(1, x=0), moto(2, x=100)], "stats": {}})
    occ_back = zone.occupancy_snapshot(open_db())
    assert occ_back.confirmed_occupancy_count == 2
    assert occ_back.leaving_session_count == 0

    # A THAT SU roi di (khong con detect du lau de PARK_END), B van dau nguyen
    for _ in range(4):
        now += timedelta(seconds=1); tick += 1.0
        MainWindow.on_zone_frame(fake, camera.id, object(), {"time": now, "monotonic_time": tick, "polygon_candidates": [moto(2, x=100)], "stats": {}})

    db.refresh(session_a); db.refresh(session_b)
    assert session_a.left_at is not None and session_a.status == "COMPLETED"
    assert session_b.left_at is None  # session B KHONG bi anh huong, van ACTIVE
    occ_final = zone.occupancy_snapshot(open_db())
    assert occ_final.confirmed_occupancy_count == 1


# --- TEST D: a CANDIDATE must not be promoted into occupancy by this patch -------

def test_candidate_is_not_counted_as_occupancy():
    zone = ZoneRuntimeState(_bare_camera(capacity=5), stable_frames_after_reconnect=1)
    _park_vehicle(zone, track=1, x=0.0)
    # mot xe MOI, chua on dinh du de thanh session, xuat hien cung luc
    zone.process([_car(1, x=0.0), _car(2, x=100.0)], NOW, 3.0)
    candidate_runtimes = [r for r in zone.vehicles.values() if r.state == "CANDIDATE"]
    assert len(candidate_runtimes) == 1 and candidate_runtimes[0].session_id is None

    occ = zone.occupancy_snapshot(open_database_session_count=1)
    assert occ.confirmed_occupancy_count == 1  # chi xe da dau, KHONG tinh candidate
    assert occ.candidate_count == 1


# --- TEST E: a real orphan DB session must still be flagged, not hidden ----------

def test_real_orphan_db_session_still_flags_mismatch():
    zone = ZoneRuntimeState(_bare_camera(capacity=5), stable_frames_after_reconnect=1)
    _park_vehicle(zone, track=1)
    # open_database_session_count=2 nhung CHI co 1 runtime OCCUPIED/LEAVING hop le dai
    # dien - phien con lai la mot orphan THAT SU (khong co runtime nao dai dien no).
    occ = zone.occupancy_snapshot(open_database_session_count=2)
    assert occ.unmatched_open_session_count == 1
    assert occ.session_health_state == "RUNTIME_MISMATCH"


def test_unconfirmed_recovery_session_that_becomes_leaving_still_flags_mismatch():
    """Bao ve dieu kien 'recovery_session is None' trong is_leaving_with_active_session():
    mot session duoc PHUC HOI tu DB (restore_session(), vd sau khi khoi dong lai/reconnect)
    ma CHUA BAO GIO duoc mot detection that xac nhan lai se chuyen thang tu RECOVERY_PENDING
    sang LEAVING (xem nhanh 'unmatched' trong ZoneRuntimeState.process() - ap dung cho MOI
    runtime con session_id, khong phan biet tien than) - runtime nay KHONG duoc tinh la
    'dang chiem cho', neu khong se che giau mot mismatch that su (session mo sau restart
    nhung chua co xe nao xac nhan lai). Da co 2 test hoi quy bao ve dieu nay o cap do
    tich hop day du (test_phase_4_3_case_a_v2.py va test_phase_4_7c_session_reconciliation.py);
    test nay kiem tra truc tiep, doc lap, ngay tai module zone_occupancy.py.

    Phase 4.7D HOTFIX 1A: bo sung kiem tra leaving_session_count cho CA HAI truong hop -
    mot runtime dang LEAVING la LEAVING bat ke recovery_session (telemetry, doc lap voi
    dieu kien loc effective occupancy), trong khi confirmed_occupancy/unmatched_open/
    session_health van phan biet ro CASE 1 (chua xac nhan) voi CASE 2 (da tung xac nhan
    song, vua tam thoi mat dau ra) - xem test_temporary_detection_miss_does_not_drop_confirmed_occupancy
    o tren cho phien ban tich hop day du cua CASE 2."""
    # --- CASE 1: session PHUC HOI, CHUA BAO GIO duoc xac nhan lai -----------------
    zone = ZoneRuntimeState(_bare_camera(capacity=5), stable_frames_after_reconnect=1)
    session = SimpleNamespace(vehicle_instance_id=None, id=777, session_code="TEST-777",
                               current_track_id="9", stabilized_vehicle_class="car", vehicle_class="car",
                               entered_at=NOW, parked_at=NOW, last_seen_at=NOW, last_confirmed_seen_at=NOW,
                               confirmed_bbox=(0, 0, 10, 10), confirmed_anchor=(5, 10), confirmed_bbox_size=(10, 10),
                               vehicle_histogram=None, vehicle_perceptual_hash=None)
    runtime = zone.restore_session(session)

    zone.process([], NOW, 0.0)  # khong candidate nao khop -> RECOVERY_PENDING -> LEAVING ngay
    assert runtime.state == "LEAVING"
    assert runtime.recovery_session is not None  # CHUA BAO GIO duoc xac nhan lai

    occ = zone.occupancy_snapshot(open_database_session_count=1)
    assert occ.confirmed_occupancy_count == 0
    assert occ.leaving_session_count == 1  # HOTFIX 1A: van la LEAVING that su, telemetry phai bao dung
    assert occ.unmatched_open_session_count == 1
    assert occ.session_health_state == "RUNTIME_MISMATCH"

    # --- CASE 2: session DA TUNG duoc xac nhan song, vua tam thoi mat dau ra ------
    zone2 = ZoneRuntimeState(_bare_camera(capacity=5), stable_frames_after_reconnect=1)
    confirmed_runtime = _park_vehicle(zone2, track=42)
    zone2.process([], NOW, 3.0)  # 1 lan mat detect -> LEAVING, nhung recovery_session=None
    assert confirmed_runtime.state == "LEAVING"
    assert confirmed_runtime.recovery_session is None  # DA tung duoc xac nhan song

    occ2 = zone2.occupancy_snapshot(open_database_session_count=1)
    assert occ2.confirmed_occupancy_count == 1
    assert occ2.leaving_session_count == 1
    assert occ2.unmatched_open_session_count == 0
    assert occ2.session_health_state == "OK"
