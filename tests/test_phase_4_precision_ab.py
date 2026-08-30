"""tests/test_phase_4_precision_ab.py

Phase 4 - test cho:
  (1) production precision fix (RUNTIME_PROFILES["production_10cam"].detector_half=False,
      YoloDetector dung "quantize" thay vi "half" da deprecated khi self.half=True).
  (2) scripts/create_ab_test_database.py (config A/B/C, backup khong mutate source, tu
      choi production DB, guard model/CUDA/camera-count, configure chi doi
      enabled/detector_image_size).

Khong mo RTSP that, khong chay GPU benchmark dai - toan bo test dung sqlite tam thoi
(tmp_path) va fake model/torch, chay duoc trong sandbox khong co GPU/Ultralytics.
"""
from __future__ import annotations

import hashlib
import logging
import sqlite3
import threading
from pathlib import Path

import numpy as np
import pytest

from app.core.config import RUNTIME_PROFILES
from app.services.detector import YoloDetector
from scripts.create_ab_test_database import (
    AB_TEST_CONFIGS,
    CameraNotFoundError,
    CudaUnavailableError,
    DatabaseNotFoundError,
    DatabaseReuseForbiddenError,
    ModelNotFoundError,
    PristineDatabaseRefusedError,
    ProductionDatabaseRefusedError,
    SourceNotFoundError,
    backup_database,
    configure_database,
    describe_config,
    ensure_cuda_available,
    ensure_model_present,
    is_production_database,
    metadata_path_for,
    prepare_ab_test_databases,
    read_metadata,
    validate_camera_selection,
)


# --- N.1: production_10cam detector_half=False -------------------------------

def test_production_10cam_precision_is_fp32():
    profile = RUNTIME_PROFILES["production_10cam"]
    assert profile.detector_half is False
    # Phase 4 CHI doi precision - model/imgsz/device/max_cameras phai giu nguyen.
    assert profile.model_filename == "yolo11s.pt"
    assert profile.detector_image_size == 960
    assert profile.detector_device == "cuda"
    assert profile.max_cameras == 10


# --- N.2/N.3: YoloDetector predict kwargs (FP32 va FP16 tuong lai) ------------

class _RecordingModel:
    def predict(self, frame, **kwargs):
        self.kwargs = kwargs
        return []


def _fake_detector(half: bool) -> YoloDetector:
    detector = YoloDetector.__new__(YoloDetector)
    detector.model = _RecordingModel()
    detector.confidence = 0.4
    detector.device = "cuda:0" if half else "cpu"
    detector.half = half
    detector._lock = threading.Lock()
    detector.last_stats = {}
    detector.last_log_at = 0
    detector.log = logging.getLogger("test.phase4.detector")
    # first_inference_logged=True: bo qua nhanh FIRST_INFERENCE/GPU_DEVICE_MISMATCH cua
    # detect() (kiem tra device cua tensor ket qua that tu Ultralytics) - khong lien quan
    # gi den precision kwarg dang test o day, va _RecordingModel fake khong tra ve tensor
    # CUDA that nen se tu kich hoat nham neu de first_inference_logged=False.
    detector.first_inference_logged = True
    return detector


def test_yolodetector_fp32_sends_neither_half_nor_quantize():
    detector = _fake_detector(half=False)
    detector.detect(np.zeros((16, 16, 3), dtype=np.uint8))
    assert "half" not in detector.model.kwargs
    assert "quantize" not in detector.model.kwargs


def test_yolodetector_half_true_uses_quantize_not_half():
    detector = _fake_detector(half=True)
    detector.detect(np.zeros((16, 16, 3), dtype=np.uint8))
    assert "half" not in detector.model.kwargs
    assert detector.model.kwargs.get("quantize") == 16


def test_yolodetector_precision_change_does_not_touch_other_kwargs():
    # Yeu cau Phase 4: khong doi confidence/imgsz/device/verbose khi doi precision kwarg.
    detector = _fake_detector(half=True)
    detector.detect(np.zeros((16, 16, 3), dtype=np.uint8), confidence=0.55, image_size=960)
    kwargs = detector.model.kwargs
    assert kwargs["conf"] == 0.55
    assert kwargs["imgsz"] == 960
    assert kwargs["device"] == detector.device
    assert kwargs["verbose"] is False


# --- N.4/N.5/N.6: config A/B/C -------------------------------------------------

def test_config_a_is_yolo11n_640_fp32():
    assert AB_TEST_CONFIGS["A"] == {"model": "yolo11n.pt", "imgsz": 640, "half": False}


def test_config_b_is_yolo11n_960_fp32():
    assert AB_TEST_CONFIGS["B"] == {"model": "yolo11n.pt", "imgsz": 960, "half": False}


def test_config_c_is_yolo11s_640_fp32():
    assert AB_TEST_CONFIGS["C"] == {"model": "yolo11s.pt", "imgsz": 640, "half": False}


def test_describe_config_prints_parseable_lines(capsys):
    result = describe_config("B")
    assert result == AB_TEST_CONFIGS["B"]
    out = capsys.readouterr().out
    assert "MODEL=yolo11n.pt" in out
    assert "IMGSZ=960" in out
    assert "HALF=false" in out


def test_describe_config_unknown_raises():
    with pytest.raises(ValueError):
        describe_config("Z")


# --- N.7: AB model missing fail-fast -------------------------------------------

def test_ensure_model_present_raises_when_missing(tmp_path):
    with pytest.raises(ModelNotFoundError) as exc_info:
        ensure_model_present(tmp_path, "A")
    assert "AB_MODEL_NOT_FOUND" in str(exc_info.value)


def test_ensure_model_present_ok_when_file_exists(tmp_path):
    (tmp_path / "yolo11n.pt").write_bytes(b"fake-weights")
    path = ensure_model_present(tmp_path, "A")
    assert path == tmp_path / "yolo11n.pt"


# --- N.8: AB CUDA unavailable fail-fast -----------------------------------------

def test_ensure_cuda_available_raises_when_false():
    with pytest.raises(CudaUnavailableError):
        ensure_cuda_available(False)


def test_ensure_cuda_available_ok_when_true():
    ensure_cuda_available(True)  # khong duoc raise


# --- N.9: AB tu choi production DB ----------------------------------------------

def test_is_production_database_true_for_exact_path(tmp_path):
    root = tmp_path
    (root / "data").mkdir()
    prod = root / "data" / "parking.db"
    prod.write_bytes(b"")
    assert is_production_database(prod, root=root) is True


def test_is_production_database_false_for_copy_path(tmp_path):
    root = tmp_path
    (root / "data" / "runtime_ab").mkdir(parents=True)
    copy_path = root / "data" / "runtime_ab" / "ab_test.db"
    copy_path.write_bytes(b"")
    assert is_production_database(copy_path, root=root) is False


def test_configure_database_refuses_production_db(tmp_path):
    root = tmp_path
    (root / "data").mkdir()
    prod = root / "data" / "parking.db"
    _make_cameras_db(prod, [("CAM01", 1, 640)])
    with pytest.raises(ProductionDatabaseRefusedError) as exc_info:
        configure_database(prod, "A", ["CAM01"], root=root)
    assert "AB_TEST_REFUSES_PRODUCTION_DB" in str(exc_info.value)
    # phai KHONG mutate production db du bi tu choi truoc khi cham vao no
    conn = sqlite3.connect(prod)
    row = conn.execute("SELECT enabled, detector_image_size FROM cameras WHERE camera_code='CAM01'").fetchone()
    conn.close()
    assert row == (1, 640)


def test_configure_database_fails_if_not_yet_created(tmp_path):
    root = tmp_path
    missing = tmp_path / "data" / "runtime_ab" / "nope.db"
    with pytest.raises(DatabaseNotFoundError):
        configure_database(missing, "A", ["CAM01"], root=root)


# --- N.10: consistent DB backup, khong mutate source ----------------------------

def _make_cameras_db(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE cameras (id INTEGER PRIMARY KEY, camera_code TEXT UNIQUE, rtsp_url TEXT, "
        "enabled INTEGER, detector_image_size INTEGER, vehicle_confidence REAL, "
        "polygon_points TEXT, parking_confirm_seconds REAL)"
    )
    conn.executemany(
        "INSERT INTO cameras (camera_code, rtsp_url, enabled, detector_image_size, "
        "vehicle_confidence, polygon_points, parking_confirm_seconds) VALUES (?,?,?,?,?,?,?)",
        [(code, f"rtsp://user:pass@host/{code}", enabled, imgsz, 0.42, "[[1,2],[3,4]]", 15.0) for code, enabled, imgsz in rows],
    )
    conn.commit()
    conn.close()


def test_backup_database_fails_when_source_missing(tmp_path):
    with pytest.raises(SourceNotFoundError):
        backup_database(tmp_path / "no_such.db", tmp_path / "runtime_ab")


def test_backup_database_creates_copy_and_does_not_mutate_source(tmp_path):
    source = tmp_path / "data" / "parking.db"
    _make_cameras_db(source, [("CAM01", 1, 960), ("CAM02", 0, 960)])
    before = sqlite3.connect(source).execute("SELECT camera_code, enabled, detector_image_size FROM cameras ORDER BY camera_code").fetchall()

    target = backup_database(source, tmp_path / "data" / "runtime_ab")

    after = sqlite3.connect(source).execute("SELECT camera_code, enabled, detector_image_size FROM cameras ORDER BY camera_code").fetchall()
    assert before == after  # source hoan toan khong doi

    assert target.is_file()
    copied = sqlite3.connect(target).execute("SELECT camera_code, enabled, detector_image_size FROM cameras ORDER BY camera_code").fetchall()
    assert copied == before  # target giong het source luc backup


def test_backup_database_does_not_overwrite_existing_target(tmp_path):
    source = tmp_path / "data" / "parking.db"
    _make_cameras_db(source, [("CAM01", 1, 960)])
    dest_dir = tmp_path / "data" / "runtime_ab"
    fixed_ts = "20260101_000000_000000"
    backup_database(source, dest_dir, timestamp=fixed_ts)
    from scripts.create_ab_test_database import DestinationExistsError

    with pytest.raises(DestinationExistsError):
        backup_database(source, dest_dir, timestamp=fixed_ts)


# --- N.11: max cameras default/limit = 3 ----------------------------------------

def test_validate_camera_selection_accepts_exactly_three():
    validate_camera_selection(["CAM01", "CAM02", "CAM03"], max_cameras=3)  # khong raise


def test_validate_camera_selection_rejects_more_than_three():
    with pytest.raises(ValueError):
        validate_camera_selection(["CAM01", "CAM02", "CAM03", "CAM04"], max_cameras=4)


def test_validate_camera_selection_rejects_count_mismatch():
    with pytest.raises(ValueError):
        validate_camera_selection(["CAM01", "CAM02"], max_cameras=3)


# --- N.12: A/B runner khong doi confidence/polygon/business settings -----------

def test_configure_database_only_touches_enabled_and_image_size(tmp_path):
    root = tmp_path
    copy_path = root / "data" / "runtime_ab" / "20260101_000000" / "ab_test.db"
    _make_cameras_db(
        copy_path,
        [("CAM01", 1, 960), ("CAM02", 1, 960), ("CAM03", 1, 960), ("CAM04", 1, 960)],
    )

    result = configure_database(copy_path, "B", ["CAM01", "CAM02", "CAM03"], root=root)
    assert result == {"database": str(copy_path), "config": "B", "imgsz": 960, "cameras": ["CAM01", "CAM02", "CAM03"]}

    conn = sqlite3.connect(copy_path)
    rows = {
        row[0]: row
        for row in conn.execute(
            "SELECT camera_code, enabled, detector_image_size, rtsp_url, vehicle_confidence, "
            "polygon_points, parking_confirm_seconds FROM cameras ORDER BY camera_code"
        )
    }
    conn.close()

    for code in ("CAM01", "CAM02", "CAM03"):
        _, enabled, imgsz, rtsp_url, confidence, polygon, timer = rows[code]
        assert enabled == 1
        assert imgsz == 960
        assert rtsp_url == f"rtsp://user:pass@host/{code}"  # khong doi
        assert confidence == pytest.approx(0.42)  # khong doi
        assert polygon == "[[1,2],[3,4]]"  # khong doi
        assert timer == pytest.approx(15.0)  # khong doi

    assert rows["CAM04"][1] == 0  # bi tat vi khong nam trong danh sach chon


def test_configure_database_raises_for_unknown_camera_code(tmp_path):
    root = tmp_path
    copy_path = root / "data" / "runtime_ab" / "x" / "ab_test.db"
    _make_cameras_db(copy_path, [("CAM01", 1, 960)])
    with pytest.raises(CameraNotFoundError):
        configure_database(copy_path, "A", ["CAM99"], root=root)


def test_configure_database_rejects_duplicate_camera_codes(tmp_path):
    root = tmp_path
    copy_path = root / "data" / "runtime_ab" / "y" / "ab_test.db"
    _make_cameras_db(copy_path, [("CAM01", 1, 960)])
    with pytest.raises(ValueError):
        configure_database(copy_path, "A", ["CAM01", "CAM01"], root=root)


# =================================================================================
# Phase 4.1 - pristine snapshot + A/B/C database isolation (10 test yeu cau)
#
# Truoc Phase 4.1, Case A/B/C chay tuan tu tren CUNG 1 file database - Case A ghi
# parking_sessions/parking_events/track state se "lan" sang trang thai bat dau cua Case
# B/C, lam A/B test khong cong bang. Phase 4.1 sua bang kien truc: production chi duoc
# doc 1 lan de tao 1 pristine snapshot, roi A/B/C moi duoc tao RIENG BIET (backup rieng)
# tu pristine (khong bao gio tu production lan 2). Cac test duoi day xac nhan (bang
# sqlite that, KHONG RTSP that) 4 file la vat ly doc lap hoan toan - sua 1 file khong anh
# huong 3 file con lai, va production/pristine khong bao gio bi mutate qua toan bo flow.
# =================================================================================

def _make_production_like_db(path: Path, camera_rows) -> None:
    """DB gia production dung cho test Phase 4.1: bang cameras (giong _make_cameras_db)
    + 1 bang parking_sessions TOI GIAN chi de kiem tra tinh doc lap file-level giua A/B/C
    (KHONG phai schema that cua app/database/models.py - Phase 4.1 khong dong vao schema
    that hay migrations that, chi dung 1 bang gia toi thieu de chung minh session ghi vao
    1 file .db khong the "lan" sang file .db khac vi day la 3 file SQLite vat ly tach biet)."""
    _make_cameras_db(path, camera_rows)
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE parking_sessions (id INTEGER PRIMARY KEY, camera_code TEXT, note TEXT)")
    conn.commit()
    conn.close()


def _file_hash(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


# --- Test 1: prepare tao pristine + A/B/C rieng biet -----------------------------

def test_prepare_creates_pristine_and_three_independent_case_databases(tmp_path):
    source = tmp_path / "data" / "parking.db"
    _make_production_like_db(source, [("CAM01", 1, 960), ("CAM02", 1, 960), ("CAM03", 0, 960)])

    result = prepare_ab_test_databases(source, tmp_path / "data" / "runtime_ab", timestamp="TS")

    pristine = result["pristine"]
    cases = result["cases"]
    assert pristine.is_file()
    assert set(cases) == {"A", "B", "C"}
    for db_path in cases.values():
        assert db_path.is_file()
    # 4 file SQLite vat ly hoan toan khac nhau - khong phai 1 file dung chung (loi Phase 4 cu).
    all_paths = {pristine, *cases.values()}
    assert len(all_paths) == 4


# --- Test 2: A/B/C hash ban dau giong pristine truoc configure --------------------

def test_case_databases_initially_identical_to_pristine_before_configure(tmp_path):
    source = tmp_path / "data" / "parking.db"
    _make_production_like_db(source, [("CAM01", 1, 960), ("CAM02", 1, 960)])

    result = prepare_ab_test_databases(source, tmp_path / "data" / "runtime_ab", timestamp="TS")
    pristine_hash = _file_hash(result["pristine"])
    for db_path in result["cases"].values():
        assert _file_hash(db_path) == pristine_hash


# --- Test 3/4/5: configure 1 case khong dong den 2 case con lai -------------------

def test_configuring_case_a_does_not_change_case_b_or_c(tmp_path):
    source = tmp_path / "data" / "parking.db"
    _make_production_like_db(source, [("CAM01", 1, 960), ("CAM02", 1, 960), ("CAM03", 1, 960)])
    result = prepare_ab_test_databases(source, tmp_path / "data" / "runtime_ab", timestamp="TS")
    b_db, c_db = result["cases"]["B"], result["cases"]["C"]
    hash_b_before, hash_c_before = _file_hash(b_db), _file_hash(c_db)

    configure_database(result["cases"]["A"], "A", ["CAM01", "CAM02", "CAM03"], root=tmp_path)

    assert _file_hash(b_db) == hash_b_before
    assert _file_hash(c_db) == hash_c_before


def test_configuring_case_b_does_not_change_case_a_or_c(tmp_path):
    source = tmp_path / "data" / "parking.db"
    _make_production_like_db(source, [("CAM01", 1, 960), ("CAM02", 1, 960), ("CAM03", 1, 960)])
    result = prepare_ab_test_databases(source, tmp_path / "data" / "runtime_ab", timestamp="TS")
    a_db, c_db = result["cases"]["A"], result["cases"]["C"]
    hash_a_before, hash_c_before = _file_hash(a_db), _file_hash(c_db)

    configure_database(result["cases"]["B"], "B", ["CAM01", "CAM02", "CAM03"], root=tmp_path)

    assert _file_hash(a_db) == hash_a_before
    assert _file_hash(c_db) == hash_c_before


def test_configuring_case_c_does_not_change_case_a_or_b(tmp_path):
    source = tmp_path / "data" / "parking.db"
    _make_production_like_db(source, [("CAM01", 1, 960), ("CAM02", 1, 960), ("CAM03", 1, 960)])
    result = prepare_ab_test_databases(source, tmp_path / "data" / "runtime_ab", timestamp="TS")
    a_db, b_db = result["cases"]["A"], result["cases"]["B"]
    hash_a_before, hash_b_before = _file_hash(a_db), _file_hash(b_db)

    configure_database(result["cases"]["C"], "C", ["CAM01", "CAM02", "CAM03"], root=tmp_path)

    assert _file_hash(a_db) == hash_a_before
    assert _file_hash(b_db) == hash_b_before


# --- Test 6: production DB khong bi mutate qua toan bo flow prepare+configure -----

def test_production_db_not_mutated_through_full_prepare_and_configure_flow(tmp_path):
    source = tmp_path / "data" / "parking.db"
    _make_production_like_db(source, [("CAM01", 1, 960), ("CAM02", 1, 960), ("CAM03", 1, 960)])
    hash_before = _file_hash(source)

    result = prepare_ab_test_databases(source, tmp_path / "data" / "runtime_ab", timestamp="TS")
    for key, db_path in result["cases"].items():
        configure_database(db_path, key, ["CAM01", "CAM02", "CAM03"], root=tmp_path)

    assert _file_hash(source) == hash_before


# --- Test 7: pristine DB khong bi mutate sau khi A/B/C duoc tao + configure -------

def test_pristine_db_not_mutated_after_case_databases_created_and_configured(tmp_path):
    source = tmp_path / "data" / "parking.db"
    _make_production_like_db(source, [("CAM01", 1, 960), ("CAM02", 1, 960), ("CAM03", 1, 960)])

    result = prepare_ab_test_databases(source, tmp_path / "data" / "runtime_ab", timestamp="TS")
    pristine_hash = _file_hash(result["pristine"])

    for key, db_path in result["cases"].items():
        configure_database(db_path, key, ["CAM01", "CAM02", "CAM03"], root=tmp_path)

    assert _file_hash(result["pristine"]) == pristine_hash
    # pristine van bi tu choi configure truc tiep, du sau khi A/B/C da duoc configure xong.
    with pytest.raises(PristineDatabaseRefusedError) as exc_info:
        configure_database(result["pristine"], "A", ["CAM01"], root=tmp_path)
    assert "AB_TEST_REFUSES_PRISTINE_DB" in str(exc_info.value)


# --- Test 8: cung 1 database dung cho 2 config khac nhau -> tu choi ---------------

def test_reusing_same_case_database_for_a_different_config_is_forbidden(tmp_path):
    source = tmp_path / "data" / "parking.db"
    _make_production_like_db(source, [("CAM01", 1, 960), ("CAM02", 1, 960), ("CAM03", 1, 960)])
    result = prepare_ab_test_databases(source, tmp_path / "data" / "runtime_ab", timestamp="TS")

    with pytest.raises(DatabaseReuseForbiddenError) as exc_info:
        configure_database(result["cases"]["A"], "B", ["CAM01", "CAM02", "CAM03"], root=tmp_path)
    assert "AB_DATABASE_REUSE_FORBIDDEN" in str(exc_info.value)

    # khong co unsafe override - khong co tham so nao khac de bo qua guard nay.
    import inspect

    assert "force" not in inspect.signature(configure_database).parameters
    assert "unsafe" not in inspect.signature(configure_database).parameters


# --- Test 9: sidecar metadata khong bao gio chua RTSP URL/mat khau ---------------

def test_sidecar_metadata_never_contains_rtsp_url_or_credentials(tmp_path):
    source = tmp_path / "data" / "parking.db"
    secret_rtsp = "rtsp://admin:S3cretPass!@203.0.113.9:554/Streaming/Channels/101"
    _make_cameras_db(source, [("CAM01", 1, 960)])
    conn = sqlite3.connect(source)
    conn.execute("UPDATE cameras SET rtsp_url=?", (secret_rtsp,))
    conn.commit()
    conn.close()

    result = prepare_ab_test_databases(source, tmp_path / "data" / "runtime_ab", timestamp="TS")

    meta_files = [metadata_path_for(result["pristine"])] + [
        metadata_path_for(p) for p in result["cases"].values()
    ]
    for meta_path in meta_files:
        assert meta_path.is_file()
        content = meta_path.read_text(encoding="utf-8")
        assert secret_rtsp not in content
        assert "rtsp://" not in content
        assert "S3cretPass" not in content

    # cau truc metadata CHI co field cho phep (khong co field thua co the vo tinh chua credential).
    pristine_meta = read_metadata(result["pristine"])
    assert set(pristine_meta) == {"role", "source", "created_at"}
    case_meta = read_metadata(result["cases"]["A"])
    assert set(case_meta) == {"config", "model", "imgsz", "precision", "source_snapshot", "created_at"}


# --- Test 10: session ghi vao Case A khong xuat hien trong Case B/C ---------------

def test_session_written_to_case_a_does_not_appear_in_case_b_or_c(tmp_path):
    source = tmp_path / "data" / "parking.db"
    _make_production_like_db(source, [("CAM01", 1, 960), ("CAM02", 1, 960), ("CAM03", 1, 960)])
    result = prepare_ab_test_databases(source, tmp_path / "data" / "runtime_ab", timestamp="TS")
    a_db, b_db, c_db = result["cases"]["A"], result["cases"]["B"], result["cases"]["C"]

    conn = sqlite3.connect(a_db)
    conn.execute("INSERT INTO parking_sessions (camera_code, note) VALUES ('CAM01', 'ONLY_IN_CASE_A')")
    conn.commit()
    conn.close()

    for db_path in (b_db, c_db):
        conn = sqlite3.connect(db_path)
        rows = conn.execute("SELECT * FROM parking_sessions").fetchall()
        conn.close()
        assert rows == []
