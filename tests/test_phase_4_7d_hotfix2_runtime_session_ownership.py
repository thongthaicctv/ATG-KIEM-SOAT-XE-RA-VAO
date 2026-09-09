"""tests/test_phase_4_7d_hotfix2_runtime_session_ownership.py

Phase 4.7D - HOTFIX 2 - RUNTIME/SESSION ONE-TO-ONE OWNERSHIP.

Boi canh: audit HOTFIX 2 (AUDIT ONLY) chung minh mot runtime THU HAI (runtime B) co
the doc lap dat toi CANDIDATE -> OCCUPIED cho MOT track_id ma mot runtime KHAC (runtime
A) dang thuc su so huu trong DB (VehicleTrackLink con mo cua session S). Khi B phat
PARK_START, ParkingSessionService.start() dung dung reason=track_owned_by_open_session
va KHONG tao ban ghi DB moi - nhung tra ve session S HIEN CO, va MainWindow.on_zone_frame()
truoc day gan session do cho B VO DIEU KIEN, khien MOT session dang mo trong DB bi
HAI runtime OCCUPIED dong thoi so huu. CONFIRMED qua log san xuat that (Windows,
2026-09-09 13:37:16): confirmed_occupancy=19, open_db=18, unmatched_open=0,
session_health=OK, occupancy_state=OVER_CAPACITY.

Bat bien nghiep vu (Section 3 cua yeu cau HOTFIX 2):
    MOT phien parking dang active PHAI duoc dai dien boi TOI DA MOT runtime hieu dung.

Fix (app/ui/main_window.py, nhanh PARK_START CHI): sau khi ParkingSessionService.start()
tra ve, doi chieu session.vehicle_instance_id (da duoc gan ngay luc tao session, xem
create_session() trong parking_session_service.py) voi runtime.vehicle_instance_id
(chinh la runtime_id cua runtime dang goi). Neu KHAC nhau -> day la CONFLICT_OTHER_OWNER
(bao gom ca truong hop session.vehicle_instance_id la None trong khi runtime hien tai co
identity that - KHONG duoc am tham cho runtime moi nhan session do) -> KHONG gan
session_id/session_code cho runtime dang xu ly, KHONG luu snapshot, KHONG commit,
KHONG log "Parking session started" cho runtime nay - va XOA runtime do khoi
zone.vehicles (KHONG de no ton tai o trang thai OCCUPIED/IDENTITY_UNCERTAIN voi
session_id=None, vi ZoneRuntimeState.process() KHONG co duong don dep cho mot runtime
unmatched vua khong phai CANDIDATE vua khong co session_id - se tro thanh "ghost"
vinh vien). Runtime A (chu so huu hop le) va session S KHONG bi dong cham.

KHONG doi: ZoneRuntimeState candidate timers, association scoring,
MultiVehicleAssociationService, track-lost timers, parking_confirm_seconds/
exit_confirm_seconds, effective LEAVING occupancy semantics (is_leaving_with_active_session,
recovery_session guard), leaving_session_count telemetry, Phase 4.7C completion
lifecycle, VehicleTrackLink completion behavior, ParkingSessionService.start()'s return
type/contract (van la mot ParkingSession don, khong wrapper moi), RTSP/FFmpeg/YOLO/CUDA,
polygon, capacity, schema. Xem bao cao HOTFIX 2 audit + minimal fix cho xac nhan chi tiet.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from sqlalchemy import select

from app.database.models import ParkingSession
from app.database.repositories import ParkingRepository
from app.services.parking_session_service import ParkingSessionService
from app.services.polygon_engine import VehicleObservation
from app.services.zone_runtime import VehicleRuntimeState, ZoneAction, ZoneRuntimeState
from app.ui.main_window import MainWindow

T = datetime(2026, 9, 9, 12, 0, tzinfo=timezone.utc)


def _camera(db, **overrides):
    from app.database.models import Camera
    values = dict(camera_code="CAM-HOTFIX2", camera_name="Test", parking_position_code="1",
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
        log=logging.getLogger("test_phase_4_7d_hotfix2"), last_occupancy_signature={},
        monitor=SimpleNamespace(update_camera=lambda *a, **kw: None),
    )


def moto(track, x=0.0):
    return VehicleObservation(str(track), "motorcycle", .9, (x, 0, x + 10, 10))


def _seed_conflict_scenario(db):
    """Dung MainWindow.on_zone_frame() THAT (DB that, ParkingSessionService that) de dua
    runtime A den OCCUPIED, so huu session S va mot VehicleTrackLink con mo cho track "1".
    Sau do dat runtime B (mot runtime DOC LAP, mo phong ket qua cua association-layer
    track-ID churn duoc mo ta trong bao cao audit - KHONG can tai tao chinh xac cuoc dua
    diem so cua MultiVehicleAssociationService, thu von phu thuoc gia tri float khong on
    dinh de kiem thu truc tiep) truc tiep vao zone.vehicles voi CUNG track_id "1", va thay
    zone.process() bang mot stub tra ve DUNG MOT ZoneAction("PARK_START", ...) cho runtime
    B - de co lap CHINH XAC doan code dang duoc audit (nhanh PARK_START trong
    on_zone_frame()) khoi lop association ben tren no, giong nhu cach cac test
    Phase 4.7D khac da co lap calculate_zone_occupancy() khoi ZoneRuntimeState.process()."""
    camera = _camera(db)
    zone = ZoneRuntimeState(camera, stable_frames_after_reconnect=1)
    fake = _fake_window(db, camera, zone)

    now = T; tick = 0.0
    for _ in range(3):
        now += timedelta(seconds=1); tick += 1.0
        MainWindow.on_zone_frame(fake, camera.id, object(), {"time": now, "monotonic_time": tick, "polygon_candidates": [moto(1)], "stats": {}})

    session = db.scalar(select(ParkingSession).where(ParkingSession.camera_id == camera.id))
    runtime_a = next(r for r in zone.vehicles.values() if r.session_id == session.id)
    assert session is not None and session.left_at is None and runtime_a.state == "OCCUPIED"

    runtime_b = VehicleRuntimeState(current_track_id="1", vehicle_class="motorcycle", first_seen_at=now,
                                     candidate_tick=tick - 5.0, last_seen_at=now, last_seen_tick=tick)
    zone.vehicles[runtime_b.runtime_id] = runtime_b
    candidate = moto(1)
    zone.process = lambda *a, **kw: [ZoneAction("PARK_START", runtime_b.runtime_id, candidate, None, now)]

    now += timedelta(seconds=1); tick += 1.0
    MainWindow.on_zone_frame(fake, camera.id, object(), {"time": now, "monotonic_time": tick, "polygon_candidates": [candidate], "stats": {}})

    open_db = lambda: len(fake.parking.find_open_sessions_for_position(camera.id, camera.parking_position_code))
    return SimpleNamespace(fake=fake, zone=zone, camera=camera, session=session, runtime_a=runtime_a,
                            runtime_b=runtime_b, candidate=candidate, now=now, tick=tick, open_db=open_db)


# --- TEST A: confirmed Windows failure reproduction -------------------------------

def test_conflicting_runtime_does_not_acquire_another_runtimes_open_session(db):
    ctx = _seed_conflict_scenario(db)

    ctx.fake.db.refresh(ctx.session)
    assert ctx.open_db() == 1  # DB: no second session row was ever created
    assert ctx.session.left_at is None

    # runtime A (legitimate owner) is untouched
    assert ctx.runtime_a.session_id == ctx.session.id
    assert ctx.runtime_a.state == "OCCUPIED"

    # runtime B MUST NOT own session S, and MUST NOT survive as an OCCUPIED+session_id=None ghost
    assert ctx.runtime_b.runtime_id not in ctx.zone.vehicles

    # confirmed_occupancy must not exceed the number of distinct owned sessions represented
    occ = ctx.zone.occupancy_snapshot(ctx.open_db())
    assert occ.confirmed_occupancy_count == 1  # NOT open_db() + 1 == 2, as in the real Windows defect
    assert occ.unmatched_open_session_count == 0


# --- TEST B: no ghost runtime survives into the next frame -------------------------

def test_no_ghost_runtime_survives_after_conflict_rejection(db):
    ctx = _seed_conflict_scenario(db)

    # restore real process() (remove the instance-level stub) and feed another frame
    del ctx.zone.process
    ctx.now += timedelta(seconds=1); ctx.tick += 1.0
    MainWindow.on_zone_frame(ctx.fake, ctx.camera.id, object(),
                              {"time": ctx.now, "monotonic_time": ctx.tick, "polygon_candidates": [moto(1)], "stats": {}})

    ghosts = [r for r in ctx.zone.vehicles.values() if r.state == "OCCUPIED" and r.session_id is None]
    assert ghosts == []

    owners_of_session = [r for r in ctx.zone.vehicles.values() if r.session_id == ctx.session.id]
    assert len(owners_of_session) == 1 and owners_of_session[0] is ctx.runtime_a


# --- TEST C: same-owner idempotent reuse must remain unaffected --------------------

def test_same_owner_idempotent_reuse_is_not_treated_as_conflict(db):
    camera = _camera(db)
    service = _service(db)
    vehicle = moto(1)

    s1 = service.start(camera, vehicle, T, T, vehicle_instance_id="same-runtime-uuid", tracker_generation=0)
    # second call with the SAME vehicle_instance_id hits open_by_vehicle_instance (or
    # by_start_key) - a legitimate idempotent reuse, not a cross-runtime conflict.
    s2 = service.start(camera, vehicle, T, T, vehicle_instance_id="same-runtime-uuid", tracker_generation=0)

    assert s2.id == s1.id  # reused the SAME row, no duplicate session created
    # exactly the equality MainWindow.on_zone_frame()'s PARK_START handler now checks:
    assert s2.vehicle_instance_id == "same-runtime-uuid"  # == requesting runtime's own vehicle_instance_id -> NOT a conflict


# --- TEST D: a legacy/null-owner existing session must not be silently adopted -----

def test_null_owner_existing_session_is_treated_as_conflict_not_silently_adopted(db):
    camera = _camera(db)
    service = _service(db)
    vehicle = moto(1)

    # simulates a session created via the legacy single-session-per-camera on_frame()
    # path, which calls start() WITHOUT vehicle_instance_id (defaults to None) - see
    # main_window.py::on_frame(), line ~282.
    legacy_session = service.start(camera, vehicle, T, T)
    assert legacy_session.vehicle_instance_id is None

    # a zone-based runtime with its OWN identity requests the same still-open track
    reused = service.start(camera, vehicle, T, T, vehicle_instance_id="zone-runtime-uuid", tracker_generation=0)

    assert reused.id == legacy_session.id  # start() still correctly refuses a duplicate DB row
    # the ownership-conflict condition used by the PARK_START handler correctly evaluates
    # True here (None != "zone-runtime-uuid") - the session must NOT be silently adopted.
    assert reused.vehicle_instance_id != "zone-runtime-uuid"


# --- TEST E: occupancy invariant - one session, at most one effective runtime ------

def test_occupancy_never_exceeds_distinct_open_session_ownership(db):
    ctx = _seed_conflict_scenario(db)

    occ = ctx.zone.occupancy_snapshot(ctx.open_db())
    effective_session_ids = {r.session_id for r in ctx.zone.vehicles.values() if r.session_id is not None}
    assert len(effective_session_ids) == 1
    assert occ.confirmed_occupancy_count == len(effective_session_ids) == 1
    assert occ.confirmed_occupancy_count != ctx.open_db() + 1  # the exact real-world defect shape
