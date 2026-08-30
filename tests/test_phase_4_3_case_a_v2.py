"""tests/test_phase_4_3_case_a_v2.py

Phase 4.3 - CASE A V2 POST-HOTFIX AUDIT - regression tests cho patch da xac nhan qua
bang chung Case A v2 that (reports/runtime_ab/case_A_20260830_224931):

  Root cause CONFIRMED: 10/10 phien "legacy" duoc phuc hoi tu snapshot production
  (VehicleRuntimeState.restore_session(), state=RECOVERY_PENDING, recovery_session=session)
  ma KHONG BAO GIO duoc mot detection song nao khop lai trong lan chay nay, khi het han
  grace-period (unmatched loop trong ZoneRuntimeState.process()) se PARK_END binh thuong -
  day la co che timeout DUNG, dang hoat dong - nhung complete_session() duoc goi voi
  departure_time_uncertain=False (mac dinh), lam mat di tin hieu "khong biet chinh xac xe
  roi luc nao", tao ra parking_duration_seconds sai lech hang trieu giay (vd session id=150
  trong Case A v2 that: parking_duration_seconds=1043185s = 289:46:25 = "17386.42 phut" -
  dung 1 trong cac vi du duoc neu trong yeu cau Phase 4.3 Section 10). Cung 10 phien nay
  VAN DANG mo trong data\\parking.db PRODUCTION THAT (da xac nhan qua audit, KHONG sua),
  nen se lap lai chinh xac loi nay o he thong that vao lan khoi dong ke tiep neu khong vá.

  Fix (minimal, theo dung pattern da co san o app/services/parking_state_engine.py:
  action="PARK_END_RECOVERY" if self.recovery_active else "PARK_END", va
  app/ui/main_window.py dong on_frame() da dung transition.action=="PARK_END_RECOVERY"
  de tinh departure_time_uncertain - chi la duong INDEPENDENT_ZONE/on_zone_frame() (duong
  THAT SU duoc 3 camera Case A v2 dung, xac nhan qua log "mode=INDEPENDENT_ZONE") CHUA CO
  co che tuong duong):
    (a) app/services/zone_runtime.py: ZoneAction them field departure_uncertain:bool=False;
        khi phat sinh action PARK_END trong process(), gan
        departure_uncertain=runtime.recovery_session is not None - True CHI KHI runtime nay
        la mot phien duoc KHOI PHUC tu DB (restore_session) va CHUA BAO GIO duoc match lai
        boi mot detection song nao trong lan chay nay (recovery_session chi bi xoa ve None
        khi thuc su match - xem process() dong "matches" loop).
    (b) app/ui/main_window.py: on_zone_frame() dong PARK_END truyen
        departure_time_uncertain=getattr(action,"departure_uncertain",False) vao
        complete_session() - truoc day KHONG truyen gi (mac dinh False cho MOI truong hop).

  KHONG doi timer/grace-period/threshold nao. KHONG doi cach tinh missing_tick/exit_confirm.
  KHONG anh huong toi phien duoc match du chi 1 lan (recovery_session da ve None truoc khi
  PARK_END, nen departure_uncertain=False nhu cu - hanh vi hien tai KHONG doi).

Cung trong file nay: test cho "empty scene khong tu sinh session" (Section 7 - xac nhan qua
Case A v2 that: detector tiep tuc chay va phat hien person/stop sign o cuoi lan chay nhung
bi loc boi accepts_vehicle(), khong co "Vehicle runtime created"/PARK_START nao sau do).
"""
from datetime import datetime, timezone
from types import SimpleNamespace

from app.services.polygon_engine import VehicleObservation
from app.services.zone_runtime import ZoneRuntimeState

NOW = datetime(2026, 8, 30, tzinfo=timezone.utc)


def camera(zone_type="CAR_ZONE", capacity=2, track_lost_grace_seconds=0, detection_miss_grace_seconds=1, exit_confirm_seconds=1, parking_confirm_seconds=1):
    return SimpleNamespace(id=1, zone_type=zone_type, capacity=capacity, parking_confirm_seconds=parking_confirm_seconds, exit_confirm_seconds=exit_confirm_seconds, detection_miss_grace_seconds=detection_miss_grace_seconds, track_lost_grace_seconds=track_lost_grace_seconds)


def car(track, x=0):
    return VehicleObservation(str(track), "car", .9, (x, 0, x + 10, 10))


def person(track, x=0):
    return VehicleObservation(str(track), "person", .9, (x, 0, x + 10, 10))


def legacy_open_session(session_id=501, track_id="7"):
    """Mo phong 1 ParkingSession dang mo (left_at=None), duoc phuc hoi qua restore_session()
    - dung nhu 10 phien legacy trong Case A v2 that (sao chep tu production snapshot Aug 18,
    van con mo trong data\\parking.db THAT den nay). Bao gom du cac truong confirmed_* de
    is_same_session_vehicle() (dung boi MultiVehicleAssociationService khi runtime.recovery_session
    con ton tai) co the so khop mot candidate that su khop (bbox=(0,0,10,10) trung voi car(_,0))."""
    return SimpleNamespace(vehicle_instance_id=None, id=session_id, session_code=f"TEST-{session_id}", current_track_id=track_id, stabilized_vehicle_class="car", vehicle_class="car", entered_at=NOW, parked_at=NOW, last_seen_at=NOW, last_confirmed_seen_at=NOW, confirmed_bbox=(0, 0, 10, 10), confirmed_anchor=(5, 10), confirmed_bbox_size=(10, 10), vehicle_histogram=None, vehicle_perceptual_hash=None)


# --- (a) departure_uncertain=True cho phien khoi phuc CHUA BAO GIO duoc match lai --------

def test_park_end_from_never_rematched_recovered_session_is_departure_uncertain():
    zone = ZoneRuntimeState(camera(), 1)
    session = legacy_open_session()
    runtime = zone.restore_session(session)
    runtime.session_id = session.id
    assert runtime.recovery_session is session  # tien dieu kien: chua duoc match lai

    # Khong co candidate nao khop trong suot qua trinh - dung 1 tinh huong "xe da roi tu
    # lau, DB van con mo" - dung tinh huong CONFIRMED tu Case A v2 that.
    actions = zone.process([], NOW, 0)
    assert any(a.kind == "VEHICLE_LEAVING" for a in actions)
    # exit_confirm(1)+max(track_lost(0),detection_miss(1))=2 -> can tick>=2 de PARK_END
    actions = zone.process([], NOW, 1)
    assert not any(a.kind == "PARK_END" for a in actions)
    actions = zone.process([], NOW, 2)
    park_end = [a for a in actions if a.kind == "PARK_END"]
    assert len(park_end) == 1
    assert park_end[0].departure_uncertain is True, (
        "Phien duoc khoi phuc tu DB (restore_session) va CHUA BAO GIO duoc mot detection "
        "song nao xac nhan lai phai duoc dong voi departure_uncertain=True - neu khong "
        "parking_duration_seconds se la mot con so vo nghia (vi du that trong Case A v2: "
        "1043185s ~ 289:46:25 ~ 12 ngay) ma khong co tin hieu nao bao rang thoi diem roi bai "
        "la KHONG CHAC CHAN."
    )
    assert runtime.runtime_id not in zone.vehicles


# --- (b) departure_uncertain=False khi phien duoc match lai it nhat 1 lan truoc khi roi ---

def test_park_end_after_at_least_one_real_match_is_not_departure_uncertain():
    zone = ZoneRuntimeState(camera(), 1)
    session = legacy_open_session(session_id=502, track_id="9")
    runtime = zone.restore_session(session)
    runtime.session_id = session.id

    # Frame dau tien: detection THAT khop lai voi phien duoc khoi phuc -> recovery_session
    # phai duoc xoa (RECOVER_SESSION), giong dung hanh vi hien tai (khong doi).
    actions = zone.process([car(9, 0)], NOW, 0)
    assert any(a.kind == "RECOVER_SESSION" for a in actions)
    assert runtime.recovery_session is None
    assert runtime.state == "OCCUPIED"

    # Sau do xe roi that (khong con detection nao khop) - phai het han binh thuong.
    zone.process([], NOW, 1)
    actions = zone.process([], NOW, 3)
    park_end = [a for a in actions if a.kind == "PARK_END"]
    assert len(park_end) == 1
    assert park_end[0].departure_uncertain is False, (
        "Mot khi phien da duoc mot detection song xac nhan lai (recovery_session=None), "
        "PARK_END sau do la mot lan roi bai THAT duoc quan sat - KHONG duoc danh dau "
        "departure_time_uncertain (hanh vi hien tai phai duoc giu nguyen, khong duoc lam "
        "qua tay boi patch nay)."
    )


# --- (c) phien MOI (PARK_START binh thuong, khong tu restore_session) khong bao gio uncertain --

def test_park_end_from_freshly_created_session_is_not_departure_uncertain():
    zone = ZoneRuntimeState(camera(), 1)
    for tick in range(3):
        actions = zone.process([car(1, 0)], NOW, tick)
    starts = [a for a in actions if a.kind == "PARK_START"]
    assert len(starts) == 1
    zone.vehicles[starts[0].runtime_id].session_id = 999

    zone.process([], NOW, 4)
    actions = zone.process([], NOW, 6)
    park_end = [a for a in actions if a.kind == "PARK_END"]
    assert len(park_end) == 1
    assert park_end[0].departure_uncertain is False, (
        "Mot phien duoc tao MOI hoan toan trong lan chay nay (khong di qua restore_session) "
        "khong bao gio co recovery_session - PARK_END cua no phai luon la "
        "departure_uncertain=False, giong het hanh vi truoc patch."
    )


# --- (d) empty scene: khong tu sinh session khi khong co detection xe duoc chap nhan -----

def test_empty_scene_with_only_non_vehicle_class_never_spawns_session():
    """Xac nhan qua Case A v2 that: cuoi lan chay, detector tiep tuc phat hien person/stop
    sign nhung bi loc boi accepts_vehicle() (class_not_allowed) - khong co 'Vehicle runtime
    created'/PARK_START nao duoc tao ra. Mo phong dung tinh huong do: candidate co class
    khong thuoc zone_type (o day la 'person' trong CAR_ZONE)."""
    zone = ZoneRuntimeState(camera(zone_type="CAR_ZONE"), 1)
    for tick in range(10):
        actions = zone.process([person(1, 0)], NOW, tick)
        assert not any(a.kind in ("VEHICLE_CANDIDATE", "PARK_START") for a in actions)
    assert zone.vehicles == {}
    assert zone.parked_count == 0


def test_empty_scene_with_no_detections_at_all_never_spawns_session():
    zone = ZoneRuntimeState(camera(), 1)
    for tick in range(10):
        actions = zone.process([], NOW, tick)
        assert not any(a.kind in ("VEHICLE_CANDIDATE", "PARK_START") for a in actions)
    assert zone.vehicles == {}


# --- (e) runtime mismatch tra ve 0 sau khi xe roi + het han timeout ----------------------

def test_runtime_mismatch_returns_to_zero_after_recovered_session_times_out():
    """Tai hien dung mau hinh Section 4: tracks_in_polygon=0 active_runtime=1 open_sessions=1
    unmatched_sessions=1 -> roi ve 0 sau khi het han. Day la trang thai CHUYEN TIEP HOP LE
    (phan loai A) - KHONG phai runtime bi ket mai mai (van de bi hoan lai tu Phase 4.2)."""
    zone = ZoneRuntimeState(camera(), 1)
    session = legacy_open_session(session_id=503, track_id="21")
    runtime = zone.restore_session(session)
    runtime.session_id = session.id

    zone.process([], NOW, 0)
    open_db = 1
    occ = zone.occupancy_snapshot(open_db)
    assert occ.unmatched_open_session_count == 1  # dung mau hinh da quan sat trong log that

    zone.process([], NOW, 1)
    zone.process([], NOW, 2)  # PARK_END fires, runtime popped
    occ_after = zone.occupancy_snapshot(open_database_session_count=0)
    assert occ_after.unmatched_open_session_count == 0
    assert runtime.runtime_id not in zone.vehicles
