"""tests/test_phase_4_7c_session_reconciliation.py

Phase 4.7C - SESSION RUNTIME RECONCILIATION.

Boi canh (xem reports/session_audit/phase47c_before.md cho bang chung day du):
audit read-only tren production data/parking.db (khong ghi, khong doi) phat hien
10 phien "mo" (left_at IS NULL) tu 2026-08-18 - toan bo database dong bang tai
thoi diem 13:45:18 cung ngay (khong co hoat dong nao sau do). Day la du lieu
LEGACY (tao TRUOC ca commit 07b9748 "stabilize runtime sessions" 2026-08-30, la
commit dau tien ghi vehicle_track_links.ended_at) - KHONG phai bang chung loi
dang song trong code hien tai (c4e01ca).

Tai hien co kiem soat (CASE R1/R3/R4/R5, xem than file nay) tren CHINH code hien
tai, dung DUNG hinh dang du lieu quan sat duoc trong production (nhieu phien mo
tu SYSTEM_RECOVERY, tracker_track_id thay doi nhieu lan trong 1 phien, camera
reconnect lien tuc trong luc dang hoi phuc), CHUNG MINH: viec dong phien khi
polygon xac nhan trong, dong track-link cu khi track_id doi, va tranh nhan doi
phien khi mat tracker tam thoi hoac camera flap - deu dang hoat dong DUNG trong
code hien tai. KHONG tim thay loi logic nghiep vu phien dang song.

Root cause THAT SU CHUNG MINH duoc (muc 38 cua yeu cau): dong log CANH BAO
"Session runtime mismatch" o app/ui/main_window.py::on_zone_frame() truoc day
duoc phat MOI FRAME rieng biet voi co che dedup-theo-signature da co san cho
dong log "Zone occupancy calculated" ben duoi no - gay log-flood keo dai suot
ca cua so hoi phuc (~10s+ moi lan reconnect/restart co phien can hoi phuc). Fix
DUY NHAT trong Phase 4.7C: gop dieu kien log CANH BAO do vao CUNG mot bien
occupancy_changed voi dong INFO ben canh (signature-based dedup da co san,
KHONG phai logic moi) - CHI giu lan dau tien va moi khi trang thai THAT SU doi,
KHONG lam yeu ban than dieu kien mismatch/unmatched_db.

KHONG doi RTSP/FFmpeg/YOLO/model/CUDA/imgsz/confidence/polygon/capacity/timer/
schema DB nao trong phase nay - xem test_phase_4_7c_no_unrelated_settings_changed
o cuoi file.

HOTFIX 1 (bo sung sau khi audit Phase 4.7C tren Windows CASE_CLEAN, DB sach tu
dau - parking_sessions=0/vehicle_track_links=0 truoc khi chay): 12 open track
links con lai dung bang 6 session COMPLETED x 1 link con mo/session - CONFIRMED
day la mot vi pham bat bien lifecycle THAT SU (khong phai du lieu legacy nhu
phat hien truoc do): complete_session() (app/services/parking_session_service.py)
chua bao gio dong track link "hien tai" con mo cua chinh no khi session hoan
tat - try_add_track_link() (app/database/repositories.py) chi dong link CU khi
CO link MOI thay the, khong bao gio duoc goi luc completion. Fix: them
ParkingRepository.end_open_track_links() va goi no trong complete_session()
TRUOC commit cuoi cung, dung left_at lam ended_at - xem nhom test "HOTFIX 1"
gan cuoi file nay.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from app.database.models import Camera, ParkingEvent, ParkingSession, VehicleTrackLink
from app.database.repositories import ParkingRepository
from app.services.parking_session_service import ParkingSessionService
from app.services.polygon_engine import VehicleObservation
from app.services.zone_occupancy import calculate_zone_occupancy
from app.services.zone_runtime import VehicleRuntimeState, ZoneRuntimeState
from app.ui.main_window import MainWindow
from app.utils.time_utils import ensure_utc

T = datetime(2026, 8, 18, 12, 59, tzinfo=timezone.utc)


def _camera(db, **overrides):
    values = dict(camera_code="CAM-47C", camera_name="Test", parking_position_code="1",
                  rtsp_url="rtsp://user:pass@example.invalid/s", zone_type="MOTORCYCLE_ZONE", capacity=15,
                  parking_confirm_seconds=15.0, exit_confirm_seconds=3.0, track_lost_grace_seconds=5.0,
                  detection_miss_grace_seconds=5.0, occupancy_observation_grace_seconds=2.0)
    values.update(overrides)
    camera = Camera(**values)
    db.add(camera); db.commit()
    return camera


def _service(db):
    return ParkingSessionService(ParkingRepository(db))


def _fake_window(db, camera, zone, log=None):
    """SimpleNamespace 'self' de goi truc tiep MainWindow.on_zone_frame(fake, ...) -
    cung idiom da dung trong tests/test_phase_4_5_session_thread_and_stale_link.py."""
    return SimpleNamespace(
        cameras=SimpleNamespace(get=lambda cid: camera),
        zones={camera.id: zone},
        last_payload={}, parking=ParkingRepository(db), session_service=_service(db), db=db,
        snapshots=SimpleNamespace(save=lambda *a, **kw: None),
        log=log or logging.getLogger("test_phase_4_7c"), last_occupancy_signature={},
        monitor=SimpleNamespace(update_camera=lambda *a, **kw: None),
    )


def moto(track, x=0.0, class_="motorcycle"):
    return VehicleObservation(str(track), class_, .9, (x, 0, x + 10, 10))


# ============================================================================
# 1. Normal enter/park/leave = mot phien duy nhat
# ============================================================================

def test_normal_enter_park_leave_is_one_session(db):
    camera = _camera(db); service = _service(db)
    v = moto(1)
    session = service.start(camera, v, T, T)
    assert session.status == "ACTIVE" and session.left_at is None
    service.complete_session(session, camera.id, v, T + timedelta(minutes=5))
    assert session.status == "COMPLETED" and session.left_at is not None
    assert len(service.repo.recent_sessions()) == 1


# ============================================================================
# 2. Session creation idempotent cho cung vehicle_instance
# ============================================================================

def test_session_creation_idempotent_for_same_vehicle_instance(db):
    camera = _camera(db); service = _service(db)
    first = service.start(camera, moto(1), T, T, vehicle_instance_id="veh-A")
    second = service.start(camera, moto(2, 50), T, T + timedelta(seconds=1), vehicle_instance_id="veh-A")
    assert first.id == second.id
    assert len(service.repo.active_sessions()) == 1


# ============================================================================
# 3. Track ID thay doi tai su dung CUNG session khi hop ly (CASE R3)
# ============================================================================

def test_track_id_replacement_reuses_same_session(db):
    camera = _camera(db); service = _service(db)
    session = service.start(camera, moto(100), T, T, vehicle_instance_id="veh-B")
    for i in range(1, 6):
        changed = service.ensure_track(session, moto(100 + i), T + timedelta(seconds=i * 10))
        assert changed is True
    assert session.current_track_id == "105"
    assert len(service.repo.active_sessions()) == 1, "khong duoc tao session moi cho MOI lan doi track_id"


# ============================================================================
# 4. Mat detection tam thoi KHONG nhan doi session (CASE R4)
# ============================================================================

def test_temporary_detection_loss_does_not_duplicate_session():
    camera = SimpleNamespace(id=1, zone_type="MOTORCYCLE_ZONE", capacity=15, parking_confirm_seconds=1,
                              exit_confirm_seconds=1, detection_miss_grace_seconds=5, track_lost_grace_seconds=5)
    zone = ZoneRuntimeState(camera, stable_frames_after_reconnect=1, minimum_candidate_frames=3)
    zone.process([moto(1)], T, 0); zone.process([moto(1)], T, 1)
    actions = zone.process([moto(1)], T, 2)
    starts = [a for a in actions if a.kind == "PARK_START"]
    assert len(starts) == 1
    runtime = zone.vehicles[starts[0].runtime_id]; runtime.session_id = 999
    # mat 2 frame - ngan hon nhieu so voi track_lost_grace(5)+exit_confirm(1)=6s
    zone.process([], T, 3); zone.process([], T, 4)
    assert runtime.session_id == 999, "session khong duoc xoa trong luc mat tam thoi"
    assert len(zone.vehicles) == 1, "khong duoc tao runtime/session thu hai"
    zone.process([moto(1)], T, 5)
    assert len(zone.vehicles) == 1 and runtime.state == "OCCUPIED"


# ============================================================================
# 5. Hoi phuc hop le tai su dung session da co (recover())
# ============================================================================

def test_legitimate_recovery_reuses_existing_session(db):
    camera = _camera(db); service = _service(db)
    session = service.start(camera, moto(1), T, T)
    recovered = service.recover(session, moto(1), T + timedelta(seconds=30))
    assert recovered.id == session.id
    assert recovered.status == "RECOVERED"
    assert len(service.repo.active_sessions()) == 1


# ============================================================================
# 6. Session da COMPLETED KHONG duoc tiep tuc "so huu" mot track dang active
# ============================================================================

def test_completed_session_cannot_own_active_track(db):
    camera = _camera(db); service = _service(db)
    session = service.start(camera, moto(1), T, T)
    service.complete_session(session, camera.id, moto(1), T + timedelta(seconds=10))
    assert session.left_at is not None
    result = service.repo.try_add_track_link(session.id, "1", T + timedelta(seconds=11))
    assert result.success is False and result.reason == "session_closed"
    ensured = service.ensure_track(session, moto(1), T + timedelta(seconds=12))
    assert ensured is False


# ============================================================================
# 7. Track link CU phai duoc dong (ended_at) khi track link MOI cua CUNG
#    session tro thanh active (regression cho fix 07b9748 - xac nhan van hoat
#    dong dung tren code hien tai, dung hinh dang du lieu tim thay trong audit
#    production: nhieu lan doi track_id trong 1 session).
# ============================================================================

def test_old_active_track_link_is_ended_when_replacement_becomes_active(db):
    camera = _camera(db); service = _service(db)
    session = service.start(camera, moto(100), T, T)
    for i in range(1, 4):
        service.ensure_track(session, moto(100 + i), T + timedelta(seconds=i * 10))
    db.expire_all()
    links = db.execute(select(VehicleTrackLink).where(VehicleTrackLink.session_id == session.id)).scalars().all()
    open_links = [l for l in links if l.ended_at is None]
    assert len(links) == 4, "1 link ban dau + 3 lan doi track_id"
    assert len(open_links) == 1, (
        "CHI duoc co DUNG 1 track link dang active tai mot thoi diem cho 1 session - "
        "day chinh la mo hinh tim thay trong audit production (67 session co >1 link "
        "dang mo dong thoi) nhung da duoc xac nhan la du lieu LEGACY tu TRUOC fix 07b9748"
    )
    assert open_links[0].tracker_track_id == "103"


# ============================================================================
# 8. Cung 1 track khong duoc thuoc ve 2 session dang mo
# ============================================================================

def test_same_track_cannot_belong_to_two_open_sessions(db):
    camera = _camera(db); service = _service(db)
    session_a = service.start(camera, moto(1), T, T)
    session_b = service.start(camera, moto(2, 50), T + timedelta(seconds=1), T + timedelta(seconds=1))
    result = service.repo.try_add_track_link(session_b.id, "1", T + timedelta(seconds=2))
    assert result.success is False
    assert result.reason == "track_owned_by_other_open_session"
    assert result.existing_session_id == session_a.id


# ============================================================================
# 9/10/15. Stale ACTIVE/RECOVERED session (dung hinh dang production that) khong
#    con mai unmatched sau khi polygon xac nhan trong - hoi tu ve dung invariant
#    muc 37 (tracks_in_polygon=0/active_runtime=0/open_sessions=0/unmatched=0,
#    occupancy_state=EMPTY, session_health=OK), va KHONG bia gio roi chinh xac
#    (departure_time_uncertain=True, khong danh dau la thoi gian do dac that).
# ============================================================================

def test_stale_sessions_reconcile_to_empty_after_restart_with_confirmed_empty_polygon(db):
    """CASE R1 - tai hien CHINH XAC hinh dang production: 9 phien RECOVERED + 1 ACTIVE,
    tat ca duoc restore_session() (mo phong MainWindow._recover() khi khoi dong lai),
    sau do camera online nhung polygon THAT SU trong (khong co candidate nao) trong
    nhieu frame lien tiep - dung con duong that qua MainWindow.on_zone_frame()."""
    camera = _camera(db, camera_code="GIAM_SAT_XE_MAY", zone_type="MOTORCYCLE_ZONE", capacity=15)
    service = _service(db)
    seeded = []
    for i in range(10):
        parked_at = T + timedelta(minutes=i * 3)
        v = moto(100 + i, x=i * 10)
        s = service.start(camera, v, parked_at, parked_at, vehicle_instance_id=f"vehicle-{i}")
        if i < 9:
            service.recover(s, v, parked_at + timedelta(seconds=1))
        seeded.append(s)
    assert len(service.repo.active_sessions()) == 10

    zone = ZoneRuntimeState(camera, stable_frames_after_reconnect=20)
    for s in service.repo.active_sessions():
        zone.restore_session(s)
    assert len(zone.vehicles) == 10
    assert {v.state for v in zone.vehicles.values()} == {"RECOVERY_PENDING"}

    fake = _fake_window(db, camera, zone)
    now = T + timedelta(hours=1); tick = 0.0; frame_interval = 1.0 / 8.0
    open_db = 10; unmatched = 10; zone_state = None; health = None
    for _ in range(500):
        now += timedelta(seconds=frame_interval); tick += frame_interval
        MainWindow.on_zone_frame(fake, camera.id, object(), {"time": now, "monotonic_time": tick, "polygon_candidates": [], "stats": {}})
        open_db = len(fake.parking.find_open_sessions_for_position(camera.id, camera.parking_position_code))
        occ = zone.occupancy_snapshot(open_db)
        unmatched, zone_state, health = occ.unmatched_open_session_count, occ.zone_state, occ.session_health_state
        if open_db == 0 and unmatched == 0:
            break

    assert open_db == 0, "muc 37: open_sessions phai ve 0 sau khi polygon xac nhan trong"
    assert unmatched == 0, "muc 37: unmatched_sessions phai ve 0"
    assert zone_state == "EMPTY" and health == "OK", "muc 37: occupancy_state=EMPTY, session_health=OK"
    assert len(zone.vehicles) == 0, "tracks/active_runtime phai ve 0"

    db.expire_all()
    closed = db.execute(select(ParkingSession).where(ParkingSession.id.in_([s.id for s in seeded]))).scalars().all()
    assert all(s.status == "COMPLETED" for s in closed)
    assert all(s.departure_time_uncertain is True for s in closed), (
        "muc 27/28: khong duoc bia gio roi CHINH XAC - phai danh dau departure_time_uncertain=True "
        "vi thoi diem roi bai THAT SU khong the biet duoc sau downtime"
    )
    assert all(s.first_confirmed_empty_after_reconnect is not None for s in closed)
    # muc 30: khong dong o-at trong 1 frame - phai mat >= 1 chu ky grace (khong phai tuc thi).
    assert tick >= (camera.track_lost_grace_seconds + camera.exit_confirm_seconds)
    # HOTFIX 1: sau khi 10 session nay COMPLETED, KHONG duoc con track link nao con mo
    # (ended_at IS NULL) - xac nhan fix o complete_session() ap dung dung cho ca con
    # duong hoi phuc/dong hang loat nay, khong chi con duong "1 xe roi don le".
    remaining_open = db.execute(select(VehicleTrackLink).where(VehicleTrackLink.session_id.in_([s.id for s in seeded]), VehicleTrackLink.ended_at.is_(None))).scalars().all()
    assert remaining_open == [], f"HOTFIX 1: khong duoc con track link nao mo sau khi session COMPLETED; con lai: {[l.id for l in remaining_open]}"


def test_reconnect_flapping_during_reconciliation_does_not_duplicate_or_close_early(db):
    """CASE R5 - camera_offline() lien tuc (nhanh hon ca so hoi tu ~10s cua test tren)
    trong luc dang hoi phuc: khong duoc tao session trung lap, khong duoc dong som,
    cuoi cung van hoi tu dung khi flapping dung lai."""
    camera = _camera(db, camera_code="GIAM_SAT_XE_MAY"); service = _service(db)
    session = service.start(camera, moto(100), T, T, vehicle_instance_id="veh-flap")
    zone = ZoneRuntimeState(camera, stable_frames_after_reconnect=20)
    zone.restore_session(session)
    fake = _fake_window(db, camera, zone)

    now = T + timedelta(hours=1); tick = 0.0; frame_interval = 1.0 / 8.0
    next_flap = 5.0; stop_flapping_after = 40.0; max_seconds = 90.0
    while tick < max_seconds:
        now += timedelta(seconds=frame_interval); tick += frame_interval
        if tick < stop_flapping_after and tick >= next_flap:
            zone.camera_offline(); next_flap += 5.0
        MainWindow.on_zone_frame(fake, camera.id, object(), {"time": now, "monotonic_time": tick, "polygon_candidates": [], "stats": {}})
        open_db = len(fake.parking.find_open_sessions_for_position(camera.id, camera.parking_position_code))
        if open_db == 0:
            break

    db.expire_all()
    all_sessions = db.execute(select(ParkingSession)).scalars().all()
    assert len(all_sessions) == 1, f"flapping khong duoc tao session trung lap, got {len(all_sessions)}"
    assert all_sessions[0].status == "COMPLETED"
    assert all_sessions[0].departure_time_uncertain is True
    open_links = db.execute(select(VehicleTrackLink).where(VehicleTrackLink.session_id == all_sessions[0].id, VehicleTrackLink.ended_at.is_(None))).scalars().all()
    assert open_links == [], f"HOTFIX 1: session COMPLETED sau flapping khong duoc con track link mo; con lai: {[l.id for l in open_links]}"


# ============================================================================
# 11/12. Hai xe trong CUNG polygon duy tri 2 session doc lap; 1 xe roi chi dong
#    dung session cua no.
# ============================================================================

def test_two_vehicles_same_polygon_two_independent_sessions_only_one_completes(db):
    camera = _camera(db, zone_type="CAR_ZONE", capacity=2, parking_confirm_seconds=1.0); service = _service(db)
    zone = ZoneRuntimeState(camera, stable_frames_after_reconnect=1)
    car_a = VehicleObservation("1", "car", .9, (0, 0, 10, 10))
    car_b = VehicleObservation("2", "car", .9, (100, 0, 110, 10))
    actions = []
    for tick in range(3):
        actions += zone.process([car_a, car_b], T, tick)
    starts = {a.vehicle.track_id: a for a in actions if a.kind == "PARK_START"}
    assert len(starts) == 2
    sessions = {}
    for track_id, action in starts.items():
        s = service.start(camera, action.vehicle, T, T, vehicle_instance_id=f"veh-{track_id}")
        zone.vehicles[action.runtime_id].session_id = s.id
        sessions[track_id] = s
    assert len(service.repo.active_sessions()) == 2

    fake = _fake_window(db, camera, zone)
    # xe "1" roi (khong con trong candidate list); xe "2" van con.
    now = T; tick = 3.0
    for step in range(20):
        tick += 1.0; now = now + timedelta(seconds=1)
        MainWindow.on_zone_frame(fake, camera.id, object(), {"time": now, "monotonic_time": tick, "polygon_candidates": [car_b], "stats": {}})
        db.expire_all()
        s1 = db.get(ParkingSession, sessions["1"].id); s2 = db.get(ParkingSession, sessions["2"].id)
        if s1.left_at is not None:
            break
    assert s1.left_at is not None and s1.status == "COMPLETED", "xe roi phai duoc dong session"
    assert s2.left_at is None and s2.status == "ACTIVE", "xe con lai KHONG duoc dong theo"
    # HOTFIX 1 (muc 8.F): dong session_1 phai dong link cua NO, KHONG dung cham toi link
    # cua session_2 (van phai con mo vi session_2 van ACTIVE).
    s1_open_links = db.execute(select(VehicleTrackLink).where(VehicleTrackLink.session_id == s1.id, VehicleTrackLink.ended_at.is_(None))).scalars().all()
    s2_open_links = db.execute(select(VehicleTrackLink).where(VehicleTrackLink.session_id == s2.id, VehicleTrackLink.ended_at.is_(None))).scalars().all()
    assert s1_open_links == [], "HOTFIX 1: session da COMPLETED khong duoc con link mo"
    assert len(s2_open_links) == 1, "session con ACTIVE phai VAN CON dung 1 link mo (khong bi dong nham)"


# ============================================================================
# 13. Nhieu xe may van doc lap (khong gop chung thanh 1 session)
# ============================================================================

def test_multiple_motorcycles_remain_independent():
    camera = SimpleNamespace(id=1, zone_type="MOTORCYCLE_ZONE", capacity=15, parking_confirm_seconds=1,
                              exit_confirm_seconds=1, detection_miss_grace_seconds=1, track_lost_grace_seconds=0)
    zone = ZoneRuntimeState(camera, stable_frames_after_reconnect=1)
    bikes = [moto(i, x=i * 15) for i in range(1, 6)]
    actions = []
    for tick in range(3):
        actions += zone.process(bikes, T, tick)
    starts = [a for a in actions if a.kind == "PARK_START"]
    assert len(starts) == 5, "5 xe may doc lap phai tao 5 candidate->PARK_START rieng biet"
    for a in starts:
        zone.vehicles[a.runtime_id].session_id = int(a.vehicle.track_id)
    assert zone.parked_count == 5
    # 1 xe roi - chi 1 session dong
    remaining = bikes[1:]
    zone.process(remaining, T, 4); actions = zone.process(remaining, T, 7)
    ends = [a for a in actions if a.kind == "PARK_END"]
    assert len(ends) == 1 and ends[0].vehicle.track_id == "1" or int(ends[0].session_id) == 1
    assert zone.parked_count == 4


# ============================================================================
# 14. Dem bang nhau KHONG duoc coi la bang chung mapping dung (muc 26) -
#    calculate_zone_occupancy() phai identity-aware (dung set cua session_id),
#    khong phai chi so sanh 2 so nguyen.
# ============================================================================

def test_count_equality_alone_is_not_proof_of_mapping_correctness():
    r1 = VehicleRuntimeState(state="OCCUPIED", session_id=42, vehicle_class="motorcycle",
                              observation=moto(1), last_seen_tick=10.0)
    r2 = VehicleRuntimeState(state="OCCUPIED", session_id=42, vehicle_class="motorcycle",  # TRUNG session_id voi r1 - kich ban loi gia dinh
                              observation=moto(2, 50), last_seen_tick=10.0)
    occ = calculate_zone_occupancy([r1, r2], now_monotonic=10.0, capacity=15, zone_type="MOTORCYCLE_ZONE",
                                    occupancy_observation_grace_seconds=2.0, open_database_session_count=2)
    assert occ.confirmed_occupancy_count == 2, "2 runtime dang OCCUPIED (dem tho)"
    assert occ.unmatched_open_session_count == 1, (
        "open_database_session_count=2 va co 2 runtime OCCUPIED se KHOP neu chi dem so "
        "nguyen - nhung CHI co 1 session_id PHAN BIET trong so do, nen mismatch DUNG phai "
        "la 1, khong phai 0: xac nhan logic la identity-aware, khong phai count-only"
    )
    assert occ.session_health_state == "RUNTIME_MISMATCH"


# ============================================================================
# 16. Cong cu audit PHAI khong the ghi vao database no mo, du co co gang.
# ============================================================================

def test_audit_script_refuses_to_write_to_the_database(db, tmp_path):
    import subprocess
    import sys as _sys

    db_path = tmp_path / "audit_probe.db"
    from sqlalchemy import create_engine
    from app.database.base import Base
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)

    script_path = "scripts/audit_phase_4_7c_sessions.py"
    result = subprocess.run([_sys.executable, script_path, "--db", str(db_path), "--quiet"],
                             capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr

    sys_path_snippet = (
        "import sqlite3,sys\n"
        f"con=sqlite3.connect('file:{db_path.as_posix()}?mode=ro',uri=True)\n"
        "try:\n"
        "    con.execute(\"INSERT INTO cameras (camera_code) VALUES ('should_never_work')\")\n"
        "    con.commit()\n"
        "    print('WROTE')\n"
        "except sqlite3.OperationalError as e:\n"
        "    print('REJECTED:',e)\n"
    )
    probe = subprocess.run([_sys.executable, "-c", sys_path_snippet], capture_output=True, text=True, timeout=15)
    assert "REJECTED" in probe.stdout, f"read-only URI must reject writes, got: {probe.stdout} {probe.stderr}"
    assert "WROTE" not in probe.stdout


def test_audit_open_readonly_helper_rejects_writes_directly(tmp_path):
    """Goi truc tiep ham open_readonly() cua script audit - phai nem loi khi thu ghi,
    khong phu thuoc vao viec goi tu subprocess."""
    import sys
    sys.path.insert(0, "scripts")
    from audit_phase_4_7c_sessions import open_readonly
    from sqlalchemy import create_engine
    from app.database.base import Base

    db_path = tmp_path / "audit_probe2.db"
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)

    con = open_readonly(str(db_path))
    try:
        with pytest.raises(Exception):
            con.execute("INSERT INTO cameras (camera_code) VALUES ('x')")
            con.commit()
    finally:
        con.close()


# ============================================================================
# Log rate-limiting (muc 38): canh bao "Session runtime mismatch" phai CHI xuat
# hien lan dau + khi trang thai THAT SU doi - khong duoc lap lai moi frame khi
# unmatched_db khong doi giua 2 frame lien tiep. Day la MINIMAL PATCH cua Phase
# 4.7C (KHONG phai fix logic nghiep vu - xem doc dau file).
# ============================================================================

def test_session_runtime_mismatch_warning_is_not_repeated_every_unchanged_frame(db, caplog):
    camera = _camera(db, camera_code="GIAM_SAT_XE_MAY"); service = _service(db)
    session = service.start(camera, moto(1), T, T, vehicle_instance_id="veh-log")
    zone = ZoneRuntimeState(camera, stable_frames_after_reconnect=999)  # giu RECOVERY_PENDING lau de quan sat log
    zone.restore_session(session)
    fake = _fake_window(db, camera, zone)

    caplog.set_level(logging.WARNING, logger="test_phase_4_7c")
    now = T + timedelta(hours=1); tick = 0.0
    for _ in range(30):
        now += timedelta(seconds=0.1); tick += 0.1
        MainWindow.on_zone_frame(fake, camera.id, object(), {"time": now, "monotonic_time": tick, "polygon_candidates": [], "stats": {}})

    mismatch_lines = [r for r in caplog.records if "Session runtime mismatch" in r.getMessage()]
    assert len(mismatch_lines) == 1, (
        f"unmatched_db khong doi qua 30 frame lien tiep (van la RECOVERY_PENDING, chua "
        f"toi nguong stable_frames_after_reconnect=999) - canh bao CHI duoc xuat hien 1 lan "
        f"(lan dau), khong phai 30 lan; got {len(mismatch_lines)}"
    )


def test_session_runtime_mismatch_warning_reappears_on_real_state_change(db, caplog):
    """Khi trang thai mismatch THAT SU doi (vd unmatched_sessions giam dan qua tung
    buoc hoi phuc that), canh bao PHAI xuat hien lai - khong duoc bi cham dut hoan toan."""
    camera = _camera(db, camera_code="GIAM_SAT_XE_MAY"); service = _service(db)
    s1 = service.start(camera, moto(1), T, T, vehicle_instance_id="veh-1")
    s2 = service.start(camera, moto(2, 50), T, T, vehicle_instance_id="veh-2")
    zone = ZoneRuntimeState(camera, stable_frames_after_reconnect=1)
    zone.restore_session(s1); zone.restore_session(s2)
    fake = _fake_window(db, camera, zone)

    caplog.set_level(logging.WARNING, logger="test_phase_4_7c")
    now = T + timedelta(hours=1); tick = 0.0
    # dan 1 xe quay lai (khop lai voi runtime cua s1) de unmatched_db giam tu 2 -> 1.
    for step in range(30):
        now += timedelta(seconds=1); tick += 1.0
        candidates = [moto(1)] if step >= 5 else []
        MainWindow.on_zone_frame(fake, camera.id, object(), {"time": now, "monotonic_time": tick, "polygon_candidates": candidates, "stats": {}})

    mismatch_lines = [r for r in caplog.records if "Session runtime mismatch" in r.getMessage()]
    assert len(mismatch_lines) >= 2, (
        "phai co IT NHAT 1 lan log ban dau (unmatched=2) va 1 lan log MOI khi trang thai "
        f"that su doi (vd unmatched giam xuong 1 sau khi 1 xe khop lai); got {len(mismatch_lines)}"
    )


def test_zone_occupancy_calculated_info_log_dedup_behavior_unchanged(db, caplog):
    """Xac nhan patch KHONG doi hanh vi dedup cua dong INFO 'Zone occupancy calculated'
    da co san - no van CHI duoc log khi signature doi, dung nhu truoc patch."""
    camera = _camera(db); service = _service(db)
    session = service.start(camera, moto(1), T, T)
    zone = ZoneRuntimeState(camera, stable_frames_after_reconnect=999)
    zone.restore_session(session)
    fake = _fake_window(db, camera, zone)

    caplog.set_level(logging.INFO, logger="test_phase_4_7c")
    now = T + timedelta(hours=1); tick = 0.0
    for _ in range(10):
        now += timedelta(seconds=0.1); tick += 0.1
        MainWindow.on_zone_frame(fake, camera.id, object(), {"time": now, "monotonic_time": tick, "polygon_candidates": [], "stats": {}})

    occ_lines = [r for r in caplog.records if "Zone occupancy calculated" in r.getMessage()]
    assert len(occ_lines) == 1, f"hanh vi dedup cua dong INFO nay khong duoc thay doi boi patch; got {len(occ_lines)}"


# ============================================================================
# HOTFIX 1 (muc 8 A-H) - "COMPLETED session khong duoc con track link mo".
#
# Root cause: try_add_track_link() CHI dong (ended_at) mot track link CU khi co
# mot track link MOI thay the trong CUNG session con dang ACTIVE - no KHONG BAO
# GIO duoc goi luc complete_session() chay, nen track link "hien tai" (link mo
# duy nhat cua session) van con ended_at IS NULL vinh vien sau khi session da
# COMPLETED. CONFIRMED qua audit CASE_CLEAN Windows that: 12 open track links
# luc audit = dung bang 6 session COMPLETED x 1 link con mo/session (moi session
# ACTIVE deu dung co 1 link mo tai bat ky thoi diem nao - dung nhu thiet ke).
#
# Fix: ParkingRepository.end_open_track_links(session_id, ended_at, commit) -
# 1 UPDATE hang loat dong TAT CA link con mo (ended_at IS NULL) cua 1 session,
# duoc goi tu complete_session() TRUOC commit cuoi cung (commit=False, cung 1
# transaction voi viec dong session) - dung CHINH left_at lam ended_at (khong
# bia gio khac). Guard idempotent da co san o dau complete_session()
# (session.left_at is not None or status in (COMPLETED,INTERRUPTED): return)
# dam bao goi complete_session() lan 2 la no-op hoan toan - khong goi lai
# end_open_track_links() lan nua.
# ============================================================================

def test_completing_session_closes_its_open_track_link(db):
    """8.A - ACTIVE session + 1 link mo -> complete_session() -> COMPLETED,
    left_at dat, VA track link duoc dong (ended_at dat, KHONG con NULL)."""
    camera = _camera(db); service = _service(db)
    session = service.start(camera, moto(1), T, T)
    db.expire_all()
    links_before = db.execute(select(VehicleTrackLink).where(VehicleTrackLink.session_id == session.id)).scalars().all()
    assert len(links_before) == 1 and links_before[0].ended_at is None

    left_at = T + timedelta(minutes=5)
    service.complete_session(session, camera.id, moto(1), left_at)
    assert session.status == "COMPLETED" and ensure_utc(session.left_at) == ensure_utc(left_at)

    db.expire_all()
    link = db.execute(select(VehicleTrackLink).where(VehicleTrackLink.session_id == session.id)).scalars().one()
    assert ensure_utc(link.ended_at) is not None, "HOTFIX 1: track link cuoi cung phai duoc dong khi session COMPLETED"


def test_completing_session_with_history_closes_all_links_not_just_current(db):
    """8.B - session co link lich su DA dong + 1 link hien tai dang mo -> complete_session()
    -> TAT CA link (ke ca cac link lich su da dong tu truoc) van phai ended_at NOT NULL
    (khong bi mo lai/ghi de sai), va link hien tai cung phai duoc dong."""
    camera = _camera(db); service = _service(db)
    session = service.start(camera, moto(100), T, T)
    for i in range(1, 4):
        service.ensure_track(session, moto(100 + i), T + timedelta(seconds=i * 10))
    db.expire_all()
    links_before = db.execute(select(VehicleTrackLink).where(VehicleTrackLink.session_id == session.id)).scalars().all()
    assert len(links_before) == 4
    historical_ended_at = {l.id: l.ended_at for l in links_before if l.tracker_track_id != "103"}
    assert all(v is not None for v in historical_ended_at.values()), "tien dieu kien: 3 link cu da duoc dong tu truoc (fix 07b9748)"

    left_at = T + timedelta(minutes=5)
    service.complete_session(session, camera.id, moto(103), left_at)

    db.expire_all()
    links_after = db.execute(select(VehicleTrackLink).where(VehicleTrackLink.session_id == session.id)).scalars().all()
    assert len(links_after) == 4, "khong duoc tao/xoa link nao them"
    for l in links_after:
        assert l.ended_at is not None, f"HOTFIX 1: link {l.id} (track={l.tracker_track_id}) khong duoc con mo sau khi session COMPLETED"
        if l.id in historical_ended_at:
            assert l.ended_at == historical_ended_at[l.id], "khong duoc ghi de ended_at cua link LICH SU da dong tu truoc"


def test_completion_timestamp_and_final_link_ended_at_are_consistent(db):
    """8.C - ended_at cua link cuoi cung phai DUNG BANG left_at cua session - khong phai
    mot thoi diem audit/ghi log khac muon hon, khong bia gio khac."""
    camera = _camera(db); service = _service(db)
    session = service.start(camera, moto(1), T, T)
    left_at = T + timedelta(minutes=7, seconds=13)
    service.complete_session(session, camera.id, moto(1), left_at)

    db.expire_all()
    link = db.execute(select(VehicleTrackLink).where(VehicleTrackLink.session_id == session.id)).scalars().one()
    assert ensure_utc(link.ended_at) == ensure_utc(left_at), f"HOTFIX 1 (muc 5): ended_at phai == left_at ({left_at}), got {link.ended_at}"


def test_complete_session_called_twice_is_idempotent(db):
    """8.D - goi complete_session() lan 2 tren session da COMPLETED: khong tao link moi,
    khong doi left_at/ended_at da co, khong loi, khong tao event trung lap."""
    camera = _camera(db); service = _service(db)
    session = service.start(camera, moto(1), T, T)
    left_at = T + timedelta(minutes=5)
    service.complete_session(session, camera.id, moto(1), left_at)

    db.expire_all()
    links_after_first = db.execute(select(VehicleTrackLink).where(VehicleTrackLink.session_id == session.id)).scalars().all()
    events_after_first = db.execute(select(ParkingEvent).where(ParkingEvent.session_id == session.id)).scalars().all()

    # Goi lai lan 2 voi mot left_at KHAC de xac nhan no thuc su la no-op (khong ghi de).
    later = left_at + timedelta(minutes=10)
    result = service.complete_session(session, camera.id, moto(1), later)
    assert ensure_utc(result.left_at) == ensure_utc(left_at), "HOTFIX 1 (muc 7): goi lan 2 KHONG duoc doi left_at da co"

    db.expire_all()
    links_after_second = db.execute(select(VehicleTrackLink).where(VehicleTrackLink.session_id == session.id)).scalars().all()
    events_after_second = db.execute(select(ParkingEvent).where(ParkingEvent.session_id == session.id)).scalars().all()
    assert len(links_after_second) == len(links_after_first) == 1, "khong duoc tao link moi khi goi lan 2"
    assert ensure_utc(links_after_second[0].ended_at) == ensure_utc(links_after_first[0].ended_at) == ensure_utc(left_at), "khong duoc doi ended_at da co"
    assert len(events_after_second) == len(events_after_first), "khong duoc tao event PARK_END trung lap"


def test_completed_session_can_never_have_open_link_property(db):
    """8.E - bat bien tong quat: ngay sau complete_session() thanh cong, TRUY VAN truc
    tiep DB (khong qua ORM identity map) phai cho thay 0 link mo cho session do."""
    camera = _camera(db); service = _service(db)
    session = service.start(camera, moto(1), T, T)
    for i in range(1, 4):
        service.ensure_track(session, moto(100 + i), T + timedelta(seconds=i * 10))
    service.complete_session(session, camera.id, moto(103), T + timedelta(minutes=5))

    db.expire_all()
    open_count = db.execute(select(func.count(VehicleTrackLink.id)).where(VehicleTrackLink.session_id == session.id, VehicleTrackLink.ended_at.is_(None))).scalar()
    assert open_count == 0, "HOTFIX 1: COMPLETED session khong bao gio duoc co open link"


def test_track_replacement_then_completion_closes_only_remaining_open_link(db):
    """8.G - link cu DA dong tu lan doi track_id, link hien tai dang mo -> completion
    CHI can dong link CON LAI (link cu giu nguyen ended_at cu, khong bi ghi de)."""
    camera = _camera(db); service = _service(db)
    session = service.start(camera, moto(1), T, T)
    service.ensure_track(session, moto(2), T + timedelta(seconds=10))
    db.expire_all()
    links = db.execute(select(VehicleTrackLink).where(VehicleTrackLink.session_id == session.id)).scalars().all()
    old_link = next(l for l in links if l.tracker_track_id == "1")
    current_link = next(l for l in links if l.tracker_track_id == "2")
    assert old_link.ended_at is not None and current_link.ended_at is None
    old_ended_at_before = old_link.ended_at

    left_at = T + timedelta(minutes=5)
    service.complete_session(session, camera.id, moto(2), left_at)

    db.expire_all()
    links_after = db.execute(select(VehicleTrackLink).where(VehicleTrackLink.session_id == session.id)).scalars().all()
    old_after = next(l for l in links_after if l.tracker_track_id == "1")
    current_after = next(l for l in links_after if l.tracker_track_id == "2")
    assert ensure_utc(old_after.ended_at) == ensure_utc(old_ended_at_before), "link cu KHONG duoc bi doi lai"
    assert ensure_utc(current_after.ended_at) == ensure_utc(left_at), "link con lai (hien tai) phai duoc dong == left_at"


def test_recovery_then_completion_leaves_zero_open_links(db):
    """8.H - session di qua recover() (RECOVERED, van con 1 link mo) roi sau do
    complete_session() -> phai ve 0 link mo, giong het con duong khong-qua-recovery."""
    camera = _camera(db); service = _service(db)
    session = service.start(camera, moto(1), T, T)
    service.recover(session, moto(1), T + timedelta(seconds=30))
    assert session.status == "RECOVERED"
    db.expire_all()
    open_before = db.execute(select(func.count(VehicleTrackLink.id)).where(VehicleTrackLink.session_id == session.id, VehicleTrackLink.ended_at.is_(None))).scalar()
    assert open_before == 1, "tien dieu kien: RECOVERED van la mot session ACTIVE-ve-mat-link, dung co 1 link mo"

    service.complete_session(session, camera.id, moto(1), T + timedelta(minutes=10))

    db.expire_all()
    open_after = db.execute(select(func.count(VehicleTrackLink.id)).where(VehicleTrackLink.session_id == session.id, VehicleTrackLink.ended_at.is_(None))).scalar()
    assert open_after == 0, "HOTFIX 1: con duong recovery->completion cung phai ve 0 link mo"


# ============================================================================
# 17. Phase 4.7C KHONG duoc dong cham RTSP/YOLO/timer - kiem tra nhe cac hang
#    so/mac dinh quan trong tu Phase 4.7B/4.7B.1/4.7A van giu nguyen.
# ============================================================================

def test_phase_4_7c_no_unrelated_settings_changed():
    from app.services.rtsp_capture import DEFAULT_HARD_RESTART_SECONDS
    assert DEFAULT_HARD_RESTART_SECONDS == 18.0, "Phase 4.7C khong duoc doi timeout RTSP"
    from app.core.config import Settings
    s = Settings()
    assert s.stable_frames_after_reconnect == 20, "Phase 4.7C khong duoc doi grace/timer mac dinh"
    assert s.track_lost_grace_seconds == 5.0
    assert s.exit_confirm_seconds == 3.0
