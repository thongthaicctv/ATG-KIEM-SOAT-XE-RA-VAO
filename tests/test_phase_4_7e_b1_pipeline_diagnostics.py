"""tests/test_phase_4_7e_b1_pipeline_diagnostics.py

Phase 4.7E-B1 - PREVIEW/LIVE TELEMETRY (DIAGNOSTIC ONLY).

Kiem tra ngu nghia cua cac "stage heartbeat" moi (RAW/AI/WORKER PREVIEW/MANAGER
PREVIEW/UI PREVIEW) va ham phan loai chan doan thuan (classify_pipeline_health) +
telemetry do tre GUI event loop (detect_gui_event_loop_delay) - xem
app/services/pipeline_diagnostics.py. KHONG kiem tra bat ky hanh vi phuc hoi nao
(chua duoc phep trong Phase 4.7E-B1 - xem yeu cau muc 8) va KHONG dung DB san xuat.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from types import SimpleNamespace

import numpy as np
from PySide6.QtCore import QTimer

from app.services.camera_manager import CameraManager
from app.services.camera_worker import CameraWorker
from app.services.pipeline_diagnostics import (
    build_diagnostic_snapshot,
    classify_pipeline_health,
    detect_gui_event_loop_delay,
)
from app.ui.main_window import MainWindow

NOW = datetime(2026, 9, 10, tzinfo=timezone.utc)


def _worker_camera(**overrides):
    values = dict(id=1, camera_code="CAM-B1", rtsp_url="rtsp://user:pass@example.invalid/s", rotation_degrees=0,
                  processing_fps=5.0, preview_fps=5.0, zone_type="CAR_ZONE", capacity=5,
                  parking_confirm_seconds=1.0, exit_confirm_seconds=1.0, detection_miss_grace_seconds=1.0,
                  track_lost_grace_seconds=1.0, use_polygon_roi=False, polygon_points=None,
                  vehicle_confidence=0.5, enable_motorcycles=True, detector_image_size=640,
                  vehicle_polygon_overlap_threshold=0.3, ai_debug_overlay=False)
    values.update(overrides)
    return SimpleNamespace(**values)


def _make_worker():
    return CameraWorker(_worker_camera(), detector=SimpleNamespace(enabled=False), tracker_factory=lambda **kw: SimpleNamespace())


# --- TEST A: raw capture independent of AI ----------------------------------------

def test_raw_live_ai_stale_is_classified_ai_stale_not_capture_stale():
    label = classify_pipeline_health(raw_capture_age=0.1, ai_result_age=15.0, worker_preview_age=0.1,
                                      manager_preview_emit_age=0.1, ui_preview_age=0.1)
    assert label == "AI_STALE"


def test_raw_capture_monotonic_is_readable_without_ai_ever_completing():
    """Correction #1: CameraWorker.raw_capture_monotonic() must reflect RtspCapture's
    OWN reader-thread state directly, with no dependency on run() ever reaching
    detector.detect()/frame_ready.emit() - a hung detector must not masquerade as
    CAPTURE_STALE."""
    worker = _make_worker()
    assert worker.raw_capture_monotonic() is None  # no RtspCapture opened yet
    worker.capture = SimpleNamespace(last_valid_frame_monotonic=555.0, dropped_capture_frames=1)
    assert worker.raw_capture_monotonic() == 555.0
    assert worker.raw_dropped_capture_frames() == 1


# --- TEST B: worker preview advances, manager/UI do not ---------------------------

def test_worker_preview_advances_manager_and_ui_do_not_is_preview_downstream_stale():
    label = classify_pipeline_health(raw_capture_age=0.1, ai_result_age=0.1, worker_preview_age=0.2,
                                      manager_preview_emit_age=25.0, ui_preview_age=25.0)
    assert label == "PREVIEW_DOWNSTREAM_STALE"


def test_preview_heartbeat_is_non_destructive_unlike_take_latest_preview():
    """Correction #1/#2 plumbing: a diagnostic read of STAGE W must never disturb real
    preview delivery/consumption (take_latest_preview() is destructive by design)."""
    worker = _make_worker()
    worker.running = True
    frame = np.zeros((4, 4, 3), dtype=np.uint8)
    worker._emit_preview(frame, capture_timestamp=10.0, capture_wall_time=NOW)

    seq1, ts1 = worker.preview_heartbeat()
    seq2, ts2 = worker.preview_heartbeat()  # calling twice must not change anything
    assert seq1 == seq2 == 1 and ts1 == ts2 and ts1 is not None

    item = worker.take_latest_preview(0)  # the REAL consumption path is untouched by our reads
    assert item is not None and item[0] == seq1

    seq3, ts3 = worker.preview_heartbeat()  # heartbeat itself is NOT cleared by consumption
    assert seq3 == seq1 and ts3 == ts1


def test_camera_manager_pipeline_diagnostics_reads_worker_without_consuming_preview():
    manager = CameraManager(detector=SimpleNamespace(), max_cameras=5)
    fake_worker = SimpleNamespace(
        preview_heartbeat=lambda: (7, 900.0),
        raw_capture_monotonic=lambda: 901.0,
        raw_dropped_capture_frames=lambda: 2,
        dropped_preview_frames=3,
        camera=SimpleNamespace(preview_fps=5.0),
    )
    manager.items[42] = (None, fake_worker)
    manager.last_preview_emit[42] = 899.5
    manager.last_actual_preview_fps[42] = 4.8

    diag = manager.pipeline_diagnostics(42)
    assert diag == {"raw_capture_monotonic": 901.0, "worker_preview_sequence": 7, "worker_preview_monotonic": 900.0,
                     "manager_preview_emit_monotonic": 899.5, "configured_preview_fps": 5.0, "actual_preview_fps": 4.8,
                     "dropped_capture_frames": 2, "dropped_preview_frames": 3}
    assert manager.pipeline_diagnostics(999) is None  # unknown/not-running camera


# --- TEST C: manager emits, UI timestamp does not advance -------------------------

def test_manager_emits_ui_does_not_advance_is_ui_preview_stale():
    label = classify_pipeline_health(raw_capture_age=0.1, ai_result_age=0.1, worker_preview_age=0.2,
                                      manager_preview_emit_age=0.3, ui_preview_age=20.0)
    assert label == "UI_PREVIEW_STALE"


# --- TEST D: normal pipeline -------------------------------------------------------

def test_all_stages_fresh_is_live():
    assert classify_pipeline_health(0.1, 0.1, 0.1, 0.1, 0.1) == "LIVE"


def test_build_diagnostic_snapshot_computes_ages_and_classification():
    snap = build_diagnostic_snapshot(7, 1000.0, raw_capture_monotonic=999.9, ai_result_monotonic=980.0,
                                      worker_preview_sequence=42, worker_preview_monotonic=999.8,
                                      manager_preview_emit_monotonic=999.7, ui_preview_monotonic=999.6,
                                      configured_preview_fps=5.0, actual_preview_fps=4.9,
                                      dropped_capture_frames=0, dropped_preview_frames=2)
    assert snap.camera_id == 7 and round(snap.raw_capture_age, 2) == 0.1 and round(snap.ai_result_age, 2) == 20.0
    assert snap.worker_preview_sequence == 42 and snap.classification == "AI_STALE"


def test_build_diagnostic_snapshot_treats_never_observed_as_not_observed():
    """Phase 4.7E-B1.1 correction: None (chua tung quan sat) KHONG con duoc bao cao la
    CAPTURE_STALE nua - startup/reconnect/worker-restart truoc khi co heartbeat dau
    tien khong duoc phep trong nhan '_STALE' (xem test_phase_4_7e_b1_1_* ben duoi)."""
    snap = build_diagnostic_snapshot(7, 1000.0)  # nothing ever observed
    assert snap.raw_capture_age is None and snap.classification == "RAW_NOT_OBSERVED"


# --- TEST E: GUI event-loop delay ---------------------------------------------------

def test_gui_event_loop_delay_detected_only_beyond_tolerance():
    assert detect_gui_event_loop_delay(2.0, 2.3) is False  # within 2.0+1.0 tolerance
    assert detect_gui_event_loop_delay(2.0, 5.0) is True
    assert detect_gui_event_loop_delay(0, 100.0) is False  # guarded, no crash on non-positive interval


# --- Section 10: deterministic reproduction hook (debug-only) ----------------------

def test_debug_freeze_preview_timer_stops_and_resumes_only_that_camera(qtbot):
    manager = CameraManager(detector=SimpleNamespace(), max_cameras=5)
    timer_a = QTimer(); timer_a.setInterval(200); timer_a.start()
    timer_b = QTimer(); timer_b.setInterval(200); timer_b.start()
    manager.preview_timers[1] = timer_a; manager.preview_timers[2] = timer_b

    assert manager.debug_freeze_preview_timer(1, True) is True
    assert timer_a.isActive() is False
    assert timer_b.isActive() is True  # untouched - only camera 1's timer is frozen

    assert manager.debug_freeze_preview_timer(1, False) is True
    assert timer_a.isActive() is True
    assert manager.debug_freeze_preview_timer(999, True) is False  # unknown camera: no crash


# --- Integration: MainWindow._check_pipeline_health wiring -------------------------

def test_check_pipeline_health_logs_diagnostic_and_gui_event_loop_delay(qtbot, caplog):
    watchdog = QTimer(); watchdog.setInterval(2000)
    diag_value = {"raw_capture_monotonic": 100.0, "worker_preview_sequence": 3, "worker_preview_monotonic": 99.9,
                  "manager_preview_emit_monotonic": 99.8, "configured_preview_fps": 5.0, "actual_preview_fps": 4.9,
                  "dropped_capture_frames": 0, "dropped_preview_frames": 0}
    fake = SimpleNamespace(
        pipeline_watchdog=watchdog, last_capture_frame={}, last_ai_result={1: 99.5},
        last_raw_capture_monotonic={}, last_ui_preview_monotonic={1: 99.6}, last_pipeline_diagnostic_log={},
        _last_watchdog_tick_monotonic=None,
        # Phase 4.7E-B2: so sach khoi phuc preview downstream - can co de
        # _maybe_recover_preview_downstream() (goi tu _check_pipeline_health()) khong loi.
        last_preview_recovery_monotonic={}, preview_recovery_attempts={}, _preview_recovery_pending_since={},
        manager=SimpleNamespace(items={1: (None, None)}, pipeline_diagnostics=lambda cid: diag_value if cid == 1 else None,
                                 recover_preview_timer=lambda cid: False),
        cameras=SimpleNamespace(get=lambda cid: SimpleNamespace(camera_code="CAM-B1")),
        settings=SimpleNamespace(telemetry_interval_seconds=0.0),
        monitor=SimpleNamespace(update_camera=lambda *a, **kw: None),
        log=logging.getLogger("test_phase_4_7e_b1"),
    )
    # _check_pipeline_health() calls self._maybe_recover_preview_downstream(...) - bind the
    # real (unbound) MainWindow method against this fake `self` so the B2 guard/cooldown
    # logic actually runs against fake's dicts, same as real B2 tests do elsewhere.
    fake._maybe_recover_preview_downstream = lambda camera_id, snapshot, now: MainWindow._maybe_recover_preview_downstream(fake, camera_id, snapshot, now)
    with caplog.at_level(logging.INFO):
        MainWindow._check_pipeline_health(fake)
    assert any("Pipeline diagnostic" in r.message and "classification=" in r.message for r in caplog.records)
    assert not any("GUI_EVENT_LOOP_DELAY" in r.message for r in caplog.records)  # no prior tick yet - nothing to compare

    caplog.clear()
    fake._last_watchdog_tick_monotonic = time.monotonic() - 10.0  # simulate a stalled GUI event loop
    with caplog.at_level(logging.WARNING):
        MainWindow._check_pipeline_health(fake)
    assert any("GUI_EVENT_LOOP_DELAY" in r.message for r in caplog.records)


# =====================================================================================
# Phase 4.7E-B1.1 - "None is not stale" correction (startup / reconnect semantics)
# =====================================================================================
# Muc 1/2/3 cua dac ta B1.1: mot cong doan CHUA TUNG duoc quan sat (age=None) phai duoc
# bao cao bang mot nhan "*_NOT_OBSERVED" rieng biet, KHONG BAO GIO la "*_STALE" - va thu
# tu uu tien thuong-nguon-truoc phai duoc GIU NGUYEN mot khi heartbeat DA duoc quan sat.

def test_b1_1_test_a_all_ages_none_is_not_observed_not_stale():
    """TEST A: tat ca tuoi (age) deu None (khoi dong lan dau/vua ket noi lai, chua co
    heartbeat nao) -> nhan chan doan phai la RAW_NOT_OBSERVED, KHONG duoc la
    CAPTURE_STALE hay bat ky '*_STALE' nao."""
    label = classify_pipeline_health(None, None, None, None, None)
    assert label == "RAW_NOT_OBSERVED"
    assert "STALE" not in label


def test_b1_1_test_b_raw_live_ai_none_is_not_observed_not_ai_stale():
    """TEST B: raw capture song (age nho), AI chua tung co ket qua (age=None, vd truoc
    khi CameraWorker.run() hoan thanh detect() lan dau) -> phai la AI_NOT_OBSERVED,
    KHONG duoc la AI_STALE."""
    label = classify_pipeline_health(raw_capture_age=0.1, ai_result_age=None, worker_preview_age=None,
                                      manager_preview_emit_age=None, ui_preview_age=None)
    assert label == "AI_NOT_OBSERVED"
    assert "STALE" not in label


def test_b1_1_test_c_raw_and_ai_live_worker_preview_none_is_not_observed():
    """TEST C: raw + AI song, worker preview chua tung duoc san xuat (age=None, vd
    worker vua khoi dong lai, _emit_preview() chua chay lan nao) -> phai la
    WORKER_PREVIEW_NOT_OBSERVED, KHONG duoc la WORKER_PREVIEW_STALE."""
    label = classify_pipeline_health(raw_capture_age=0.1, ai_result_age=0.1, worker_preview_age=None,
                                      manager_preview_emit_age=None, ui_preview_age=None)
    assert label == "WORKER_PREVIEW_NOT_OBSERVED"
    assert "STALE" not in label


def test_b1_1_test_d_raw_ai_worker_live_manager_none_is_not_observed():
    """TEST D: raw + AI + worker preview song, manager (_flush_preview) chua tung emit
    (age=None, vd QTimer preview chua tick lan nao ke tu khi camera khoi dong) -> phai
    la MANAGER_PREVIEW_NOT_OBSERVED, KHONG duoc la PREVIEW_DOWNSTREAM_STALE."""
    label = classify_pipeline_health(raw_capture_age=0.1, ai_result_age=0.1, worker_preview_age=0.1,
                                      manager_preview_emit_age=None, ui_preview_age=None)
    assert label == "MANAGER_PREVIEW_NOT_OBSERVED"
    assert "STALE" not in label


def test_b1_1_test_e_raw_ai_worker_manager_live_ui_none_is_not_observed():
    """TEST E: raw + AI + worker preview + manager emit deu song, UI chua tung ap dung
    frame (age=None, vd on_preview_frame() chua tung chay xong lan nao) -> phai la
    UI_PREVIEW_NOT_OBSERVED, KHONG duoc la UI_PREVIEW_STALE."""
    label = classify_pipeline_health(raw_capture_age=0.1, ai_result_age=0.1, worker_preview_age=0.1,
                                      manager_preview_emit_age=0.1, ui_preview_age=None)
    assert label == "UI_PREVIEW_NOT_OBSERVED"
    assert "STALE" not in label


def test_b1_1_test_f_observed_then_old_is_still_correctly_classified_stale():
    """TEST F: hoi quy - mot khi heartbeat DA TUNG duoc quan sat (age la mot so, KHONG
    phai None) va tuoi cua no vuot nguong, hanh vi '*_STALE' cu (truoc B1.1) phai VAN
    dung nguyen nhu truoc - correction chi thay doi ngu nghia cua None, khong thay doi
    nguong hay thu tu uu tien khi da co quan sat."""
    # raw da tung quan sat nhung qua cu -> CAPTURE_STALE (khong phai RAW_NOT_OBSERVED)
    assert classify_pipeline_health(30.0, 0.1, 0.1, 0.1, 0.1) == "CAPTURE_STALE"
    # AI da tung quan sat nhung qua cu -> AI_STALE
    assert classify_pipeline_health(0.1, 15.0, 0.1, 0.1, 0.1) == "AI_STALE"
    # worker preview da tung quan sat nhung qua cu -> WORKER_PREVIEW_STALE
    assert classify_pipeline_health(0.1, 0.1, 8.0, 0.1, 0.1) == "WORKER_PREVIEW_STALE"
    # manager emit da tung quan sat nhung qua cu -> PREVIEW_DOWNSTREAM_STALE
    assert classify_pipeline_health(0.1, 0.1, 0.1, 8.0, 0.1) == "PREVIEW_DOWNSTREAM_STALE"
    # UI da tung quan sat nhung qua cu -> UI_PREVIEW_STALE
    assert classify_pipeline_health(0.1, 0.1, 0.1, 0.1, 8.0) == "UI_PREVIEW_STALE"
    # tat ca deu song -> LIVE (khong doi)
    assert classify_pipeline_health(0.1, 0.1, 0.1, 0.1, 0.1) == "LIVE"


def test_b1_1_build_diagnostic_snapshot_startup_all_none_is_not_observed():
    """Kiem tra qua build_diagnostic_snapshot() (khong chi ham classify_pipeline_health
    thuan) - dam bao duong dan thuc te (main_window.py goi build_diagnostic_snapshot())
    cung nhan duoc ngu nghia moi, khong chi ham noi bo."""
    snap = build_diagnostic_snapshot(1, 1000.0)  # camera vua khoi dong, chua co gi ca
    assert snap.classification == "RAW_NOT_OBSERVED"
    assert snap.raw_capture_age is None
    assert snap.ai_result_age is None


# =====================================================================================
# Phase 4.7E-B1.1 muc 7 - worker-generation timestamp leak (stop_camera()/start_camera())
# =====================================================================================

def test_b1_1_reset_generation_diagnostics_clears_only_that_camera_diagnostic_dicts():
    """MainWindow._reset_generation_diagnostics(camera_id) phai xoa heartbeat CHAN DOAN
    (last_ai_result/last_ui_preview_monotonic/last_raw_capture_monotonic/
    last_pipeline_diagnostic_log) CHI cho camera vua bi stop_camera(), KHONG dong den
    camera khac, va KHONG dong den last_capture_frame (van dieu khien AI_RESULT_STALE
    hien co - business behavior khong doi, xem yeu cau muc 7: 'Do NOT reset any
    business/session state')."""
    fake = SimpleNamespace(
        last_ai_result={1: 100.0, 2: 200.0},
        last_ui_preview_monotonic={1: 101.0, 2: 201.0},
        last_raw_capture_monotonic={1: 102.0, 2: 202.0},
        last_pipeline_diagnostic_log={1: 103.0, 2: 203.0},
        last_capture_frame={1: 104.0, 2: 204.0},
        # Phase 4.7E-B2: so sach khoi phuc preview downstream - cung phai duoc xoa theo camera.
        last_preview_recovery_monotonic={1: 105.0, 2: 205.0},
        preview_recovery_attempts={1: 1, 2: 2},
        _preview_recovery_pending_since={1: 106.0, 2: 206.0},
    )
    MainWindow._reset_generation_diagnostics(fake, 1)
    assert 1 not in fake.last_ai_result and fake.last_ai_result[2] == 200.0
    assert 1 not in fake.last_ui_preview_monotonic and fake.last_ui_preview_monotonic[2] == 201.0
    assert 1 not in fake.last_raw_capture_monotonic and fake.last_raw_capture_monotonic[2] == 202.0
    assert 1 not in fake.last_pipeline_diagnostic_log and fake.last_pipeline_diagnostic_log[2] == 203.0
    assert 1 not in fake.last_preview_recovery_monotonic and fake.last_preview_recovery_monotonic[2] == 205.0
    assert 1 not in fake.preview_recovery_attempts and fake.preview_recovery_attempts[2] == 2
    assert 1 not in fake._preview_recovery_pending_since and fake._preview_recovery_pending_since[2] == 206.0
    assert fake.last_capture_frame == {1: 104.0, 2: 204.0}  # business dict - untouched


def test_b1_1_reset_generation_diagnostics_is_a_noop_for_unknown_camera():
    """Goi voi mot camera_id chua tung co trong bat ky dict nao khong duoc gay loi
    (vd delete_camera() tren mot camera chua tung ket noi thanh cong lan nao)."""
    fake = SimpleNamespace(last_ai_result={}, last_ui_preview_monotonic={}, last_raw_capture_monotonic={},
                            last_pipeline_diagnostic_log={}, last_preview_recovery_monotonic={},
                            preview_recovery_attempts={}, _preview_recovery_pending_since={})
    MainWindow._reset_generation_diagnostics(fake, 999)  # must not raise
    assert fake.last_ai_result == {} and fake.last_ui_preview_monotonic == {}


def test_b1_1_stop_camera_call_sites_reset_generation_diagnostics(monkeypatch):
    """Nguon goc thuc te cua muc 7: edit_camera()/delete_camera()/test_rtsp()/
    edit_polygon() la 4 diem goi manager.stop_camera() duy nhat trong MainWindow - moi
    diem PHAI goi self._reset_generation_diagnostics(camera.id) ngay sau do (bang chung
    tinh (source-level) rang sua doi da duoc noi day vao ca 4 noi, khong chi mot phan
    trong so do)."""
    import inspect

    from app.ui import main_window as mw

    source = inspect.getsource(mw.MainWindow)
    call_sites = ["edit_camera", "delete_camera", "test_rtsp", "edit_polygon"]
    for name in call_sites:
        method_source = inspect.getsource(getattr(mw.MainWindow, name))
        assert "manager.stop_camera(camera.id)" in method_source, f"{name} no longer calls manager.stop_camera"
        assert "_reset_generation_diagnostics(camera.id)" in method_source, (
            f"{name} calls manager.stop_camera() but does not reset per-camera diagnostic "
            "heartbeats afterwards (Phase 4.7E-B1.1 muc 7)"
        )
