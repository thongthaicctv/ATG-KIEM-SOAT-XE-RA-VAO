"""tests/test_phase_4_7e_b1_2_common_4cam_debug_db.py

Phase 4.7E-B1.2 - "common 4-camera debug DB" (3 DDNS + 1 LAN) + tach topology (bo cau
hinh camera se chay that) khoi muc tieu dong bang preview (freeze target) trong launcher
chan doan Windows.

Boi canh: scripts/prepare_debug_2zones.py (KHONG con gioi han o dung 2 camera) gio ho
tro --source-database (mac dinh VAN la production DB de tuong thich nguoc tuyet doi)
de tai su dung cau hinh camera THAT (rtsp_url/polygon_points/...) da co san trong mot DB
debug/smoke khac (vd data/runtime_debug/phase47a_4cam_smoke.db) thay vi luon phai doc
tu production. scripts/phase_4_7e_b1_1_windows_preview_freeze_diagnostic.py gio phan
biet ro --include-camera (tap camera se duoc dua vao DB debug va khoi dong that) voi
--freeze-camera (CHINH XAC MOT camera trong tap do se bi dong bang preview timer).

QUAN TRONG VE MOI TRUONG KIEM THU: app/database/session.py rang buoc mot SQLAlchemy
`engine` o CAP MODULE, duoc tao MOT LAN duy nhat khi module duoc import lan dau (dua
tren PARKING_DATABASE_URL tai thoi diem do) - vi vay KHONG THE goi init_database()/
prepare_debug_2zones.main() truc tiep (import) nhieu lan trong CUNG mot tien trinh
pytest voi cac PARKING_DATABASE_URL khac nhau va mong doi no ghi dung file. Moi bai
test trong file nay vi vay chay prepare_debug_2zones.py (va script dung de dung san DB
nguon gia lap) nhu MOT TIEN TRINH con (subprocess) rieng biet, giong het cach
run_app.py/launcher B1.1 that su goi no trong san xuat.

KHONG dung DB san xuat that trong bat ky test nao o day - moi DB nguon/dich deu la file
tam (tmp_path) hoac duong dan gia (cho cac test tu choi an toan).
"""
from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PREPARE_SCRIPT = PROJECT_ROOT / "scripts" / "prepare_debug_2zones.py"
LAUNCHER_SCRIPT = PROJECT_ROOT / "scripts" / "phase_4_7e_b1_1_windows_preview_freeze_diagnostic.py"

# Camera specs mo phong dung topology thuc te: 3 "DDNS" (hostname, khong phai IP LAN) +
# 1 "LAN" (192.168.23.23, camera_code=GIAM_SAT_XE_MAY_LOCAL, MOTORCYCLE_ZONE) - dung
# camera_code trung voi vi du trong dac ta B1.2 de bai test co y nghia thuc te.
FOUR_CAMERA_SPECS = [
    {"camera_code": "GIAM_SAT_O_TO_1", "camera_name": "O to 1 (DDNS)", "parking_position_code": "2",
     "rtsp_url": "rtsp://user:pass@ddns-cam-1.example.invalid:554/stream1", "zone_type": "CAR_ZONE",
     "polygon_points": [[0.1, 0.1], [0.9, 0.1], [0.9, 0.9], [0.1, 0.9]]},
    {"camera_code": "GIAM_SAT_O_TO_2", "camera_name": "O to 2 (DDNS)", "parking_position_code": "3",
     "rtsp_url": "rtsp://user:pass@ddns-cam-2.example.invalid:554/stream1", "zone_type": "CAR_ZONE",
     "polygon_points": [[0.1, 0.1], [0.9, 0.1], [0.9, 0.9], [0.1, 0.9]]},
    {"camera_code": "GIAM_SAT_XE_MAY", "camera_name": "Xe may (DDNS)", "parking_position_code": "1",
     "rtsp_url": "rtsp://user:pass@ddns-cam-3.example.invalid:554/stream1", "zone_type": "MOTORCYCLE_ZONE",
     "polygon_points": [[0.1, 0.1], [0.9, 0.1], [0.9, 0.9], [0.1, 0.9]]},
    {"camera_code": "GIAM_SAT_XE_MAY_LOCAL", "camera_name": "Xe may LAN", "parking_position_code": "LOCAL_XE_MAY_TEST",
     "rtsp_url": "rtsp://user:pass@192.168.23.23:554/stream1", "zone_type": "MOTORCYCLE_ZONE",
     "polygon_points": [[0.1, 0.1], [0.9, 0.1], [0.9, 0.9], [0.1, 0.9]]},
]
FOUR_CAMERA_CODES = [spec["camera_code"] for spec in FOUR_CAMERA_SPECS]

_BUILD_SOURCE_DB_SCRIPT = """
import json, os, sys
from datetime import datetime
sys.path.insert(0, sys.argv[1])
os.environ["PARKING_DATABASE_URL"] = f"sqlite:///{sys.argv[2]}"
from app.database.migrations import init_database
init_database()
from app.database.session import SessionLocal
from app.database.models import Camera, ParkingSession
with open(sys.argv[3]) as f:
    payload = json.load(f)
db = SessionLocal()
cameras_by_code = {}
for spec in payload["cameras"]:
    camera = Camera(**spec)
    db.add(camera)
    db.flush()
    cameras_by_code[spec["camera_code"]] = camera.id
DATETIME_FIELDS = ("entered_at", "parked_at", "left_at")
for session_spec in payload.get("sessions", []):
    session_spec = dict(session_spec)
    session_spec["camera_id"] = cameras_by_code[session_spec.pop("camera_code")]
    for field in DATETIME_FIELDS:
        if session_spec.get(field):
            session_spec[field] = datetime.fromisoformat(session_spec[field])
    db.add(ParkingSession(**session_spec))
db.commit()
db.close()
print("SOURCE_BUILT")
"""


def _build_source_db(tmp_path: Path, db_path: Path, camera_specs, session_specs=None) -> None:
    """Dung mot DB nguon GIA LAP (chua cac ban ghi cameras chi dinh, cong voi
    parking_sessions tuy chon de kiem tra TEST C) bang MOT TIEN TRINH RIENG - xem ghi
    chu o dau file ve ly do khong the goi init_database() truc tiep trong tien trinh
    pytest hien tai."""
    script_path = tmp_path / f"_build_source_{db_path.stem}.py"
    script_path.write_text(_BUILD_SOURCE_DB_SCRIPT, encoding="utf-8")
    payload_path = tmp_path / f"_payload_{db_path.stem}.json"
    payload_path.write_text(json.dumps({"cameras": camera_specs, "sessions": session_specs or []}), encoding="utf-8")
    result = subprocess.run([sys.executable, str(script_path), str(PROJECT_ROOT), str(db_path), str(payload_path)],
                             cwd=PROJECT_ROOT, capture_output=True, text=True)
    assert result.returncode == 0, f"failed to build fixture source DB: stdout={result.stdout!r} stderr={result.stderr!r}"


def _run_prepare(*, source_database=None, target: Path, cameras) -> subprocess.CompletedProcess:
    cmd = [sys.executable, str(PREPARE_SCRIPT), "--target", str(target)]
    for code in cameras:
        cmd += ["--camera", code]
    if source_database is not None:
        cmd += ["--source-database", str(source_database)]
    return subprocess.run(cmd, cwd=PROJECT_ROOT, capture_output=True, text=True)


def _sha256(path: Path) -> str:
    import hashlib
    return hashlib.sha256(path.read_bytes()).hexdigest()


# =====================================================================================
# TEST A / B - custom source DB with 4 camera records -> all 4 selected cameras copied,
# target has EXACTLY the intended 4 cameras enabled/configured.
# =====================================================================================

def test_b1_2_test_a_and_b_all_four_selected_cameras_copied_and_enabled(tmp_path):
    source_db = tmp_path / "source_4cam.db"
    target_db = tmp_path / "target_4cam.db"
    _build_source_db(tmp_path, source_db, FOUR_CAMERA_SPECS)

    result = _run_prepare(source_database=source_db, target=target_db, cameras=FOUR_CAMERA_CODES)
    assert result.returncode == 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"
    assert "DEBUG_DB_READY" in result.stdout

    conn = sqlite3.connect(target_db)
    rows = conn.execute("SELECT camera_code, zone_type, enabled FROM cameras ORDER BY camera_code").fetchall()
    conn.close()
    assert len(rows) == 4  # CAMERAS COPIED = 4 (TEST A)
    codes = {row[0] for row in rows}
    assert codes == set(FOUR_CAMERA_CODES)  # TEST B: exactly the intended 4 cameras
    assert all(row[2] == 1 for row in rows)  # TEST B: all enabled
    zone_types = {row[0]: row[1] for row in rows}
    assert zone_types["GIAM_SAT_O_TO_1"] == "CAR_ZONE"
    assert zone_types["GIAM_SAT_O_TO_2"] == "CAR_ZONE"
    assert zone_types["GIAM_SAT_XE_MAY"] == "MOTORCYCLE_ZONE"
    assert zone_types["GIAM_SAT_XE_MAY_LOCAL"] == "MOTORCYCLE_ZONE"


# =====================================================================================
# TEST C - no parking_sessions/history copied (SESSIONS COPIED = 0)
# =====================================================================================

def test_b1_2_test_c_no_sessions_or_history_copied(tmp_path):
    source_db = tmp_path / "source_with_history.db"
    target_db = tmp_path / "target_no_history.db"
    session_specs = [{
        "camera_code": "GIAM_SAT_XE_MAY_LOCAL", "parking_position_code": "LOCAL_XE_MAY_TEST",
        "session_code": "SESS-0001", "vehicle_class": "MOTORCYCLE", "status": "COMPLETED",
        "entered_at": "2026-01-01T00:00:00+00:00", "parked_at": "2026-01-01T00:00:05+00:00",
        "left_at": "2026-01-01T00:10:00+00:00",
    }]
    _build_source_db(tmp_path, source_db, FOUR_CAMERA_SPECS, session_specs=session_specs)

    # sanity: the fixture source DB really does contain history (otherwise this test proves nothing)
    conn = sqlite3.connect(source_db)
    assert conn.execute("SELECT COUNT(*) FROM parking_sessions").fetchone()[0] == 1
    conn.close()

    result = _run_prepare(source_database=source_db, target=target_db, cameras=FOUR_CAMERA_CODES)
    assert result.returncode == 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"
    assert "sessions_copied=0" in result.stdout

    conn = sqlite3.connect(target_db)
    assert conn.execute("SELECT COUNT(*) FROM parking_sessions").fetchone()[0] == 0  # TEST C
    conn.close()


# =====================================================================================
# TEST D - source SHA before == after (source truly read-only)
# =====================================================================================

def test_b1_2_test_d_source_sha256_unchanged_after_run(tmp_path):
    source_db = tmp_path / "source_readonly_check.db"
    target_db = tmp_path / "target_readonly_check.db"
    _build_source_db(tmp_path, source_db, FOUR_CAMERA_SPECS)

    sha_before = _sha256(source_db)
    result = _run_prepare(source_database=source_db, target=target_db, cameras=FOUR_CAMERA_CODES)
    assert result.returncode == 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"
    sha_after = _sha256(source_db)
    assert sha_before == sha_after


# =====================================================================================
# TEST E - source == target rejected
# =====================================================================================

def test_b1_2_test_e_source_equals_target_rejected(tmp_path):
    same_path = tmp_path / "same.db"
    _build_source_db(tmp_path, same_path, FOUR_CAMERA_SPECS)
    result = _run_prepare(source_database=same_path, target=same_path, cameras=FOUR_CAMERA_CODES)
    assert result.returncode != 0
    assert "DEBUG_SOURCE_TARGET_SAME_PATH" in (result.stdout + result.stderr)


# =====================================================================================
# TEST F - target == data/parking.db (production) rejected, before any write
# =====================================================================================

def test_b1_2_test_f_target_production_database_rejected(tmp_path):
    source_db = tmp_path / "source_for_prod_target_check.db"
    _build_source_db(tmp_path, source_db, FOUR_CAMERA_SPECS)
    production_path = PROJECT_ROOT / "data" / "parking.db"
    production_existed_before = production_path.is_file()
    sha_before = _sha256(production_path) if production_existed_before else None

    result = _run_prepare(source_database=source_db, target=production_path, cameras=[FOUR_CAMERA_CODES[0]])
    assert result.returncode != 0
    assert "DEBUG_TARGET_IS_PRODUCTION_DATABASE" in (result.stdout + result.stderr)

    # "reject before any write": production DB must not have been created/modified
    assert production_path.is_file() == production_existed_before
    if production_existed_before:
        assert _sha256(production_path) == sha_before


# =====================================================================================
# TEST G - missing source rejected
# =====================================================================================

def test_b1_2_test_g_missing_source_database_rejected(tmp_path):
    missing_source = tmp_path / "does_not_exist.db"
    target_db = tmp_path / "target_for_missing_source.db"
    assert not missing_source.exists()
    result = _run_prepare(source_database=missing_source, target=target_db, cameras=["ANY_CODE"])
    assert result.returncode != 0
    assert "DEBUG_SOURCE_DATABASE_NOT_FOUND" in (result.stdout + result.stderr)
    assert not target_db.exists()  # no partial target created on failure


# =====================================================================================
# Backward compatibility: default --source-database (no flag) still means production DB
# =====================================================================================

def test_b1_2_default_source_database_is_still_production_for_backward_compat():
    import importlib.util
    spec = importlib.util.spec_from_file_location("prepare_debug_2zones_bc_check", PREPARE_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    args = module.parse_args(["--camera", "SOME_CODE", "--target", "does/not/matter.db"])
    assert Path(args.source_database).resolve() == (PROJECT_ROOT / "data" / "parking.db").resolve()


# =====================================================================================
# TEST H / I / J - launcher: include-camera vs freeze-camera, and legacy backward compat
# =====================================================================================

def _load_launcher_module():
    import importlib.util
    spec = importlib.util.spec_from_file_location("phase_4_7e_b1_1_windows_preview_freeze_diagnostic_b1_2", LAUNCHER_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def launcher():
    return _load_launcher_module()


def test_b1_2_test_h_new_mode_distinguishes_include_from_freeze(launcher):
    args = launcher.parse_args([
        "--include-camera", "GIAM_SAT_O_TO_1", "--include-camera", "GIAM_SAT_O_TO_2",
        "--include-camera", "GIAM_SAT_XE_MAY", "--include-camera", "GIAM_SAT_XE_MAY_LOCAL",
        "--freeze-camera", "GIAM_SAT_XE_MAY_LOCAL",
        "--database", "data/runtime_debug/phase47e_4cam_common.db",
    ])
    include_cameras, freeze_camera = launcher.resolve_camera_selection(args)
    assert include_cameras == ("GIAM_SAT_O_TO_1", "GIAM_SAT_O_TO_2", "GIAM_SAT_XE_MAY", "GIAM_SAT_XE_MAY_LOCAL")
    assert freeze_camera == "GIAM_SAT_XE_MAY_LOCAL"
    assert freeze_camera in include_cameras  # freeze target is a member of the topology, not a 5th thing


def test_b1_2_test_h_mixing_legacy_and_new_mode_is_rejected(launcher):
    args = launcher.parse_args([
        "--camera", "CAM-01", "--include-camera", "CAM-02", "--freeze-camera", "CAM-02",
        "--database", "x.db",
    ])
    with pytest.raises(SystemExit, match="CAMERA_SELECTION_AMBIGUOUS"):
        launcher.resolve_camera_selection(args)


def test_b1_2_new_mode_requires_freeze_camera(launcher):
    args = launcher.parse_args(["--include-camera", "CAM-01", "--database", "x.db"])
    with pytest.raises(SystemExit, match="FREEZE_CAMERA_REQUIRED"):
        launcher.resolve_camera_selection(args)


def test_b1_2_no_selection_at_all_is_rejected(launcher):
    args = launcher.parse_args(["--database", "x.db"])
    with pytest.raises(SystemExit, match="CAMERA_SELECTION_REQUIRED"):
        launcher.resolve_camera_selection(args)


def test_b1_2_test_i_freeze_target_must_belong_to_included_set(launcher):
    args = launcher.parse_args([
        "--include-camera", "GIAM_SAT_O_TO_1", "--include-camera", "GIAM_SAT_O_TO_2",
        "--freeze-camera", "GIAM_SAT_XE_MAY_LOCAL",  # NOT in the included set
        "--database", "x.db",
    ])
    with pytest.raises(SystemExit, match="FREEZE_CAMERA_NOT_IN_INCLUDED_SET"):
        launcher.resolve_camera_selection(args)


def test_b1_2_test_j_legacy_single_camera_invocation_still_works(launcher):
    args = launcher.parse_args(["--camera", "GIAM_SAT_XE_MAY_LOCAL", "--database", "x.db"])
    include_cameras, freeze_camera = launcher.resolve_camera_selection(args)
    assert include_cameras == ("GIAM_SAT_XE_MAY_LOCAL",)
    assert freeze_camera == "GIAM_SAT_XE_MAY_LOCAL"


def test_b1_2_prepare_debug_database_forwards_all_include_cameras_and_source(launcher, monkeypatch):
    """_prepare_debug_database() phai truyen MOI camera trong include_cameras (khong chi
    camera dau tien) va --source-database (khi duoc chi dinh) toi prepare_debug_2zones.py."""
    captured = {}

    def _fake_run(command, cwd=None, check=None):
        captured["command"] = command
        captured["cwd"] = cwd
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(launcher.subprocess, "run", _fake_run)
    launcher._prepare_debug_database(Path("data/runtime_debug/phase47e_4cam_common.db"),
                                      ("A", "B", "C", "D"), Path("data/runtime_debug/phase47a_4cam_smoke.db"))
    command = captured["command"]
    assert command.count("--camera") == 4
    for code in ("A", "B", "C", "D"):
        assert code in command
    assert "--source-database" in command
    assert str(Path("data/runtime_debug/phase47a_4cam_smoke.db")) in command


def test_b1_2_prepare_debug_database_omits_source_flag_when_not_given(launcher, monkeypatch):
    """Khi khong truyen source_database (None), lenh subprocess KHONG duoc chua
    --source-database - giu nguyen hanh vi B1.1 (prepare_debug_2zones.py tu dung mac
    dinh production cua no)."""
    captured = {}

    def _fake_run(command, cwd=None, check=None):
        captured["command"] = command
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(launcher.subprocess, "run", _fake_run)
    launcher._prepare_debug_database(Path("data/runtime_debug/diag.db"), ("CAM-01",), None)
    assert "--source-database" not in captured["command"]
