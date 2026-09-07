"""tests/test_phase_4_4_naive_aware_datetime.py

Phase 4.4 - CASE A OFFICIAL RUN AUDIT - regression test cho bug da CONFIRMED qua bang
chung Case A official that (reports/runtime_ab/case_A_20260831_064901):

  Root cause CONFIRMED (tai hien truc tiep bang cac lop ORM that
  app.database.models.Camera/ParkingSession trong sandbox, khong chi suy dien tu log):
  cot entered_at/parked_at/last_seen_at khai bao DateTime(timezone=True) nhung SQLite
  KHONG co kieu du lieu timezone native - SQLAlchemy tra ve datetime NAIVE (tzinfo=None)
  sau khi doc lai tu DB. ZoneRuntimeState.restore_session() (app/services/zone_runtime.py)
  truoc patch gan truc tiep session.entered_at/parked_at/last_seen_at (NAIVE) vao
  VehicleRuntimeState.first_seen_at/parked_at/last_seen_at ma KHONG bang qua ensure_utc()
  - khac voi quy uoc chuan da co san o app/services/session_vehicle_matcher.py va
  app/utils/time_utils.py. Khi zone.vehicles chua dong thoi 1 runtime duoc restore_session()
  (NAIVE) va 1 runtime moi tao song (AWARE, tu payload["time"]=datetime.now(timezone.utc)
  trong app/services/camera_worker.py), dong sort trong
  app/ui/main_window.py::on_zone_frame():
    sorted(zone.vehicles.values(), key=lambda v:(v.session_id is None, v.first_seen_at or now))
  crash TypeError: can't compare offset-naive and offset-aware datetimes.

  Hau qua da do duoc tu log that Case A official (~20 phut, camera GIAM_SAT_XE_MAY):
  38 lan crash (~moi 32s), moi lan bi on_zone_frame_safe() bat va goi _reconcile_zone()
  - ham nay XOA TOAN BO zone.vehicles trong bo nho va restore_session() lai TU DAU cho
  MOI phien dang mo trong DB cho camera do (ke ca cac phien dang duoc theo doi song binh
  thuong, khong he "mat ket noi that su") - tai gan recovery_session cho chung, dan toi:
  135 canh bao "Track ownership conflict", cac phien dang duoc theo doi lien tuc (nhieu
  track link lien tiep, khong dut quang) bi gan nham status=RECOVERED/departure_time_uncertain=True,
  va cac episode "Session runtime mismatch" keo dai toi 79 giay (vuot xa nguong 2-7s
  chuyen tiep hop le nhu quy dinh Section 8).

  Fix (minimal, dung dung quy uoc ensure_utc() da co san, KHONG doi timer/grace-period/
  threshold/RTSP/DB schema nao): restore_session() bang first_seen_at/parked_at/last_seen_at
  qua ensure_utc() truoc khi gan vao VehicleRuntimeState.
"""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.services.polygon_engine import VehicleObservation
from app.services.zone_runtime import ZoneRuntimeState

NOW_AWARE = datetime(2026, 8, 31, 6, 29, 6, tzinfo=timezone.utc)
NAIVE_ENTERED_AT = datetime(2026, 8, 30, 23, 29, 0, 484992)  # tzinfo=None - dung nhu SQLite tra ve


def camera(zone_type="MOTORCYCLE_ZONE", capacity=15):
    return SimpleNamespace(id=3, zone_type=zone_type, capacity=capacity, parking_confirm_seconds=5,
                            exit_confirm_seconds=2, detection_miss_grace_seconds=5, track_lost_grace_seconds=3)


def moto(track, x=0):
    return VehicleObservation(str(track), "motorcycle", .9, (x, 0, x + 10, 10))


def legacy_open_session(session_id=185, track_id="164", entered_at=NAIVE_ENTERED_AT):
    """Phien dang mo, duoc doc lai qua ORM that tu SQLite -> entered_at/parked_at/last_seen_at
    la NAIVE datetime (tzinfo=None) - dung nhu 10+ phien dang mo trong Case A official that."""
    return SimpleNamespace(vehicle_instance_id=None, id=session_id, session_code=f"TEST-{session_id}",
                            current_track_id=track_id, stabilized_vehicle_class="motorcycle",
                            vehicle_class="motorcycle", entered_at=entered_at, parked_at=entered_at,
                            last_seen_at=entered_at, last_confirmed_seen_at=entered_at,
                            confirmed_bbox=(0, 0, 10, 10), confirmed_anchor=(5, 10),
                            confirmed_bbox_size=(10, 10), vehicle_histogram=None, vehicle_perceptual_hash=None)


def test_restore_session_normalizes_naive_db_datetimes_to_aware_utc():
    """Xac nhan truc tiep hanh vi da patch: first_seen_at/parked_at/last_seen_at cua runtime
    duoc khoi phuc PHAI la tzinfo=utc, du session.entered_at tu DB la NAIVE (tzinfo=None) -
    day chinh la nguyen nhan goc da CONFIRMED cua crash trong Case A official."""
    zone = ZoneRuntimeState(camera(), 1)
    session = legacy_open_session()
    assert session.entered_at.tzinfo is None  # tien dieu kien: dung NAIVE nhu SQLite that

    runtime = zone.restore_session(session)

    assert runtime.first_seen_at.tzinfo is not None, "first_seen_at phai la AWARE sau restore_session"
    assert runtime.first_seen_at.utcoffset() == timedelta(0)
    assert runtime.parked_at.tzinfo is not None
    assert runtime.last_seen_at.tzinfo is not None


def test_mixed_restored_and_fresh_runtimes_do_not_crash_on_sort():
    """Tai hien CHINH XAC dong crash that trong app/ui/main_window.py::on_zone_frame():
    sorted(zone.vehicles.values(), key=lambda v:(v.session_id is None, v.first_seen_at or now))
    khi zone.vehicles co DONG THOI 1 runtime duoc restore_session() (tu DB) va 1 runtime
    moi tao qua process() (candidate/matched song, first_seen_at luon AWARE). Truoc patch,
    dong sort nay nem TypeError: can't compare offset-naive and offset-aware datetimes -
    CONFIRMED 38 lan trong Case A official (2026-08-31, camera GIAM_SAT_XE_MAY)."""
    zone = ZoneRuntimeState(camera(), 1)
    restored_session = legacy_open_session(session_id=185, track_id="164")
    restored_runtime = zone.restore_session(restored_session)
    restored_runtime.session_id = restored_session.id

    # Runtime thu hai: mot phien khac DA CO session_id (dung nhu 1 phien vua PARK_START
    # song trong lan chay nay) - trong sort key (v.session_id is None, v.first_seen_at),
    # ca hai runtime co session_id is None == False, nen Python SE so sanh tiep
    # first_seen_at giua chung (khong short-circuit o phan tu dau tien cua tuple) -
    # dung CHINH XAC tinh huong gay crash that trong Case A official.
    fresh_runtime = zone.restore_session(legacy_open_session(
        session_id=199, track_id="999", entered_at=NOW_AWARE))
    fresh_runtime.first_seen_at = NOW_AWARE  # gia lap 1 runtime vua tao song (AWARE that)
    fresh_runtime.recovery_session = None  # da duoc match lai - khong con la "recovery"

    assert len(zone.vehicles) == 2  # 1 restored (NAIVE truoc patch) + 1 song (AWARE)
    for v in zone.vehicles.values():
        assert v.session_id is not None  # tien dieu kien: ca hai deu KHONG bi short-circuit

    # Day chinh la dong code that trong on_zone_frame() - phai KHONG raise TypeError.
    visible = sorted(zone.vehicles.values(), key=lambda v: (v.session_id is None, v.first_seen_at or NOW_AWARE))
    assert len(visible) == 2


def test_reconcile_style_repeated_restore_stays_stable_and_matchable():
    """Mo phong _reconcile_zone(): goi restore_session() lai NHIEU LAN cho CUNG mot phien
    dang mo (dung nhu moi lan crash-storm rebuild lai toan bo zone) - runtime duoc tao lai
    van phai co datetime AWARE moi lan, va van phai match lai binh thuong voi mot detection
    song thuc su khop (khong bi ket o trang thai IDENTITY_UNCERTAIN/RECOVERED vinh vien chi
    vi bi rebuild nhieu lan)."""
    zone = ZoneRuntimeState(camera(), 1)
    session = legacy_open_session(session_id=198, track_id="164")

    for _ in range(5):  # mo phong 5 lan rebuild lien tiep (nhu 38 lan crash that)
        runtime = zone.restore_session(session)
        runtime.session_id = session.id
        assert runtime.first_seen_at.tzinfo is not None

    # Sau nhieu lan rebuild, mot detection song THAT SU khop track_id=164 van phai
    # RECOVER_SESSION binh thuong (khong bi loi so sanh datetime chan lai).
    actions = zone.process([moto(164, x=0)], NOW_AWARE, 0)
    assert any(a.kind == "RECOVER_SESSION" for a in actions)
