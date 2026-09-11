"""tests/test_phase_4_7e_b2_preview_downstream_recovery.py

Phase 4.7E-B2 - SAFE PREVIEW DOWNSTREAM RECOVERY (MINIMAL PRODUCTION HOTFIX).

Boi canh: Windows LAN da chung minh PREVIEW_DOWNSTREAM_STALE la mot che do loi doc lap,
that (RAW/AI/WORKER PREVIEW van LIVE, CHI manager/UI preview bi dung) - xem bao cao
B1/B1.1. Phase nay them dung MOT hanh dong khoi phuc AN TOAN, TOI THIEU: khoi dong lai
(neu can) CHI QTimer preview cua camera do - xem
MainWindow._maybe_recover_preview_downstream()/CameraManager.recover_preview_timer().

Cac test o day dung LAI dung mot ky thuat da thiet lap tu B1 (vd
test_check_pipeline_health_logs_diagnostic_and_gui_event_loop_delay): goi CAC HAM
KHONG-BOUND cua MainWindow voi mot doi tuong SimpleNamespace "fake" lam self, thay vi
dung mot MainWindow that (qua nang - can QApplication/DB/detector that). Dieu nay CHUNG
MINH ro rang (bang AttributeError neu sai) rang cac ham nay khong tham chieu bat ky
doi tuong nghiep vu/session nao ma fake khong co (xem TEST J).
"""
from __future__ import annotations

import logging
import time
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import QTimer

from app.services.camera_manager import CameraManager
from app.services.pipeline_diagnostics import (
    DEFAULT_PREVIEW_RECOVERY_CONFIRM_TIMEOUT_SECONDS,
    DEFAULT_PREVIEW_RECOVERY_COOLDOWN_SECONDS,
    PipelineDiagnosticSnapshot,
)
from app.ui.main_window import MainWindow


def _snapshot(classification, camera_id=1, **overrides) -> PipelineDiagnosticSnapshot:
    values = dict(camera_id=camera_id, raw_capture_age=0.05, ai_result_age=0.1, worker_preview_sequence=239,
                  worker_preview_age=0.03, manager_preview_emit_age=0.1, ui_preview_age=0.1,
                  configured_preview_fps=5.0, actual_preview_fps=4.9, dropped_capture_frames=0,
                  dropped_preview_frames=0, classification=classification)
    values.update(overrides)
    return PipelineDiagnosticSnapshot(**values)


def _fake_window(**overrides) -> SimpleNamespace:
    """Doi tuong 'self' toi thieu can de goi _maybe_recover_preview_downstream() - CHI
    gom dung nhung gi ham do thuc su dung (log, manager, 3 dict so sach B2). KHONG co
    session_service/active/parking/cameras/monitor/zones - neu ham vo tinh dong den bat
    ky thu nao trong so do, test se that bai voi AttributeError (xem TEST J)."""
    fake = SimpleNamespace(
        log=logging.getLogger("test_phase_4_7e_b2"),
        manager=SimpleNamespace(recover_preview_timer=MagicMock(return_value=True)),
        last_preview_recovery_monotonic={},
        preview_recovery_attempts={},
        _preview_recovery_pending_since={},
    )
    for key, value in overrides.items():
        setattr(fake, key, value)
    return fake


# =====================================================================================
# TEST A - healthy pipeline (LIVE) => no recovery attempt
# =====================================================================================

def test_b2_test_a_healthy_pipeline_no_recovery_attempt():
    fake = _fake_window()
    MainWindow._maybe_recover_preview_downstream(fake, 1, _snapshot("LIVE"), 1000.0)
    fake.manager.recover_preview_timer.assert_not_called()
    assert fake.last_preview_recovery_monotonic == {}
    assert fake.preview_recovery_attempts == {}
    assert fake._preview_recovery_pending_since == {}


# =====================================================================================
# TEST B - PREVIEW_DOWNSTREAM_STALE with RAW/AI/worker healthy => timer-only recovery
# =====================================================================================

def test_b2_test_b_preview_downstream_stale_triggers_timer_only_recovery(caplog):
    fake = _fake_window()
    snap = _snapshot("PREVIEW_DOWNSTREAM_STALE", manager_preview_emit_age=32.203, ui_preview_age=32.172,
                      worker_preview_age=0.031, ai_result_age=0.109, raw_capture_age=0.031)
    with caplog.at_level(logging.WARNING):
        MainWindow._maybe_recover_preview_downstream(fake, 1, snap, 1000.0)
    fake.manager.recover_preview_timer.assert_called_once_with(1)
    assert fake.last_preview_recovery_monotonic[1] == 1000.0
    assert fake.preview_recovery_attempts[1] == 1
    assert fake._preview_recovery_pending_since[1] == 1000.0
    attempt_logs = [r.message for r in caplog.records if "PREVIEW_RECOVERY_ATTEMPT" in r.message]
    assert len(attempt_logs) == 1
    assert "camera=1" in attempt_logs[0] and "classification=PREVIEW_DOWNSTREAM_STALE" in attempt_logs[0]


# =====================================================================================
# TEST C - no CameraWorker restart: worker object/generation identity unchanged
# =====================================================================================

def test_b2_test_c_no_camera_worker_restart(qtbot):
    manager = CameraManager(detector=SimpleNamespace(), max_cameras=5)
    sentinel_thread = SimpleNamespace(name="thread-1")
    sentinel_worker = SimpleNamespace(name="worker-1")
    manager.items[1] = (sentinel_thread, sentinel_worker)
    timer = QTimer(); timer.setInterval(200)  # deliberately NOT started -> inactive, like a frozen preview timer
    manager.preview_timers[1] = timer
    manager.stop_camera = MagicMock(side_effect=AssertionError("stop_camera must not be called by recover_preview_timer"))
    manager.start_camera = MagicMock(side_effect=AssertionError("start_camera must not be called by recover_preview_timer"))

    result = manager.recover_preview_timer(1)

    assert result is True
    assert timer.isActive() is True
    assert manager.items[1][0] is sentinel_thread  # same worker/thread generation - no restart
    assert manager.items[1][1] is sentinel_worker
    manager.stop_camera.assert_not_called()
    manager.start_camera.assert_not_called()


# =====================================================================================
# TEST D - no RTSP reconnect path invoked (worker/capture never touched at all)
# =====================================================================================

def test_b2_test_d_no_rtsp_reconnect_path_invoked(qtbot):
    manager = CameraManager(detector=SimpleNamespace(), max_cameras=5)
    worker_mock = MagicMock()  # any attribute access/call on this would show up in mock_calls
    manager.items[1] = (SimpleNamespace(), worker_mock)
    timer = QTimer(); timer.setInterval(200)
    manager.preview_timers[1] = timer

    manager.recover_preview_timer(1)

    assert worker_mock.mock_calls == []  # recover_preview_timer never touches the worker at all


def test_b2_recover_preview_timer_is_noop_when_already_active(qtbot):
    manager = CameraManager(detector=SimpleNamespace(), max_cameras=5)
    timer = QTimer(); timer.setInterval(200); timer.start()
    manager.preview_timers[1] = timer
    assert manager.recover_preview_timer(1) is False  # already running - nothing to recover
    assert timer.isActive() is True


def test_b2_recover_preview_timer_unknown_camera_returns_false(qtbot):
    manager = CameraManager(detector=SimpleNamespace(), max_cameras=5)
    assert manager.recover_preview_timer(999) is False


# =====================================================================================
# TEST E - recovery confirmation: heartbeat resumes -> LIVE -> PREVIEW_RECOVERY_CONFIRMED
# =====================================================================================

def test_b2_test_e_recovery_confirmation_logs_confirmed_and_clears_pending(caplog):
    fake = _fake_window()
    with caplog.at_level(logging.WARNING):
        MainWindow._maybe_recover_preview_downstream(fake, 1, _snapshot("PREVIEW_DOWNSTREAM_STALE"), 1000.0)
    assert 1 in fake._preview_recovery_pending_since
    caplog.clear()

    with caplog.at_level(logging.WARNING):
        MainWindow._maybe_recover_preview_downstream(fake, 1, _snapshot("LIVE"), 1003.5)

    confirmed = [r.message for r in caplog.records if "PREVIEW_RECOVERY_CONFIRMED" in r.message]
    assert len(confirmed) == 1
    assert "camera=1" in confirmed[0] and "elapsed_seconds=3.50" in confirmed[0]
    assert 1 not in fake._preview_recovery_pending_since
    fake.manager.recover_preview_timer.assert_called_once()  # only the ORIGINAL attempt - confirmation itself does not re-trigger recovery


def test_b2_recovery_failure_after_confirm_timeout_then_retries_after_cooldown(caplog):
    fake = _fake_window()
    with caplog.at_level(logging.WARNING):
        MainWindow._maybe_recover_preview_downstream(fake, 1, _snapshot("PREVIEW_DOWNSTREAM_STALE"), 1000.0)
    assert fake.manager.recover_preview_timer.call_count == 1

    # still stale, but past the confirm timeout -> FAILED, and NO immediate re-attempt in the same tick
    still_stale_t = 1000.0 + DEFAULT_PREVIEW_RECOVERY_CONFIRM_TIMEOUT_SECONDS + 0.5
    caplog.clear()
    with caplog.at_level(logging.WARNING):
        MainWindow._maybe_recover_preview_downstream(fake, 1, _snapshot("PREVIEW_DOWNSTREAM_STALE"), still_stale_t)
    failed_logs = [r.message for r in caplog.records if "PREVIEW_RECOVERY_FAILED" in r.message]
    assert len(failed_logs) == 1
    assert fake.manager.recover_preview_timer.call_count == 1  # NOT retried within the same tick as the failure

    # a LATER tick, past cooldown too, is allowed to retry
    later_t = still_stale_t + DEFAULT_PREVIEW_RECOVERY_COOLDOWN_SECONDS + 1.0
    MainWindow._maybe_recover_preview_downstream(fake, 1, _snapshot("PREVIEW_DOWNSTREAM_STALE"), later_t)
    assert fake.manager.recover_preview_timer.call_count == 2
    assert fake.preview_recovery_attempts[1] == 2


# =====================================================================================
# TEST F - recovery cooldown: multiple watchdog ticks during the same stale episode
# must not spam recover_preview_timer()
# =====================================================================================

def test_b2_test_f_recovery_cooldown_prevents_spam_across_many_ticks():
    fake = _fake_window()
    snap = _snapshot("PREVIEW_DOWNSTREAM_STALE")
    for tick_time in (1000.0, 1000.5, 1001.0, 1002.0, 1004.0, 1006.0, 1008.0):  # many ticks, still within confirm timeout
        MainWindow._maybe_recover_preview_downstream(fake, 1, snap, tick_time)
    assert fake.manager.recover_preview_timer.call_count == 1
    assert fake.preview_recovery_attempts[1] == 1


# =====================================================================================
# TEST G / H / I - other classifications must NEVER trigger preview-only recovery
# =====================================================================================

@pytest.mark.parametrize("classification", [
    "CAPTURE_STALE",            # TEST G
    "AI_STALE",                 # TEST H
    "WORKER_PREVIEW_STALE",     # TEST I
    "RAW_NOT_OBSERVED",
    "AI_NOT_OBSERVED",
    "WORKER_PREVIEW_NOT_OBSERVED",
])
def test_b2_test_g_h_i_other_classifications_never_trigger_recovery(classification):
    fake = _fake_window()
    MainWindow._maybe_recover_preview_downstream(fake, 1, _snapshot(classification), 1000.0)
    fake.manager.recover_preview_timer.assert_not_called()
    assert fake.last_preview_recovery_monotonic == {}
    assert fake._preview_recovery_pending_since == {}


# =====================================================================================
# TEST J - OCCUPIED active session: recovery must never touch session/business state
# =====================================================================================

def test_b2_test_j_recovery_never_touches_session_or_business_state():
    """fake CO Y KHONG co session_service/active/parking/cameras/monitor/zones - neu
    _maybe_recover_preview_downstream() vo tinh tham chieu bat ky thu gi trong so do
    (vd de doc/ghi session, business_state, track ownership), loi se la AttributeError
    ngay lap tuc, khong phai mot assertion co the bi bo sot."""
    fake = _fake_window()  # deliberately minimal - see docstring
    MainWindow._maybe_recover_preview_downstream(fake, 42, _snapshot("PREVIEW_DOWNSTREAM_STALE", camera_id=42), 1000.0)
    fake.manager.recover_preview_timer.assert_called_once_with(42)
    # confirm a subsequent LIVE snapshot still needs nothing business-related to process
    MainWindow._maybe_recover_preview_downstream(fake, 42, _snapshot("LIVE", camera_id=42), 1002.0)
    assert 42 not in fake._preview_recovery_pending_since


# =====================================================================================
# TEST K - multiple cameras: only the stale camera's preview timer is recovered
# =====================================================================================

def test_b2_test_k_multiple_cameras_only_stale_ones_preview_timer_recovered():
    fake = _fake_window()
    MainWindow._maybe_recover_preview_downstream(fake, 1, _snapshot("PREVIEW_DOWNSTREAM_STALE", camera_id=1), 1000.0)
    MainWindow._maybe_recover_preview_downstream(fake, 2, _snapshot("LIVE", camera_id=2), 1000.0)
    MainWindow._maybe_recover_preview_downstream(fake, 3, _snapshot("CAPTURE_STALE", camera_id=3), 1000.0)

    fake.manager.recover_preview_timer.assert_called_once_with(1)
    assert 1 in fake.last_preview_recovery_monotonic
    assert 2 not in fake.last_preview_recovery_monotonic
    assert 3 not in fake.last_preview_recovery_monotonic


def test_b2_camera_manager_recover_preview_timer_only_touches_selected_camera(qtbot):
    """Nhan manh o cap CameraManager: dong bang 2 camera, khoi phuc CHI camera 1 - camera
    2 phai giu nguyen trang thai bi dong (khong bi 'vo tinh' khoi dong lai theo)."""
    manager = CameraManager(detector=SimpleNamespace(), max_cameras=5)
    timer_1 = QTimer(); timer_1.setInterval(200)
    timer_2 = QTimer(); timer_2.setInterval(200)
    manager.preview_timers[1] = timer_1
    manager.preview_timers[2] = timer_2
    assert manager.recover_preview_timer(1) is True
    assert timer_1.isActive() is True
    assert timer_2.isActive() is False  # untouched


# =====================================================================================
# Generation-safety: a fresh worker generation must not inherit stale B2 bookkeeping
# =====================================================================================

def test_b2_reset_generation_diagnostics_clears_recovery_bookkeeping():
    fake = SimpleNamespace(
        last_ai_result={1: 1.0}, last_ui_preview_monotonic={1: 1.0}, last_raw_capture_monotonic={1: 1.0},
        last_pipeline_diagnostic_log={1: 1.0}, last_capture_frame={1: 1.0},
        last_preview_recovery_monotonic={1: 500.0, 2: 600.0},
        preview_recovery_attempts={1: 3, 2: 1},
        _preview_recovery_pending_since={1: 500.5, 2: 600.5},
    )
    MainWindow._reset_generation_diagnostics(fake, 1)
    assert 1 not in fake.last_preview_recovery_monotonic and fake.last_preview_recovery_monotonic[2] == 600.0
    assert 1 not in fake.preview_recovery_attempts and fake.preview_recovery_attempts[2] == 1
    assert 1 not in fake._preview_recovery_pending_since and fake._preview_recovery_pending_since[2] == 600.5


# =====================================================================================
# Windows acceptance-test launcher support: --disable-manual-resume
# =====================================================================================

def _load_launcher_module():
    import importlib.util
    from pathlib import Path
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "phase_4_7e_b1_1_windows_preview_freeze_diagnostic.py"
    spec = importlib.util.spec_from_file_location("phase_4_7e_b1_1_windows_preview_freeze_diagnostic_b2", script_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def launcher():
    return _load_launcher_module()


def test_b2_launcher_disable_manual_resume_flag_parses(launcher):
    args = launcher.parse_args(["--camera", "GIAM_SAT_XE_MAY_LOCAL", "--database", "x.db", "--disable-manual-resume"])
    assert args.disable_manual_resume is True

    args_default = launcher.parse_args(["--camera", "GIAM_SAT_XE_MAY_LOCAL", "--database", "x.db"])
    assert args_default.disable_manual_resume is False


def test_b2_launcher_skips_manual_resume_scheduling_when_disabled(launcher):
    """Kiem tra source-level: nhanh 'if args.disable_manual_resume' phai bao quanh dung
    lenh QTimer.singleShot(...,_resume) - neu khong, --disable-manual-resume se khong co
    tac dung gi va bai kiem tra Windows B2 se khong con y nghia (van la resume thu cong)."""
    import inspect
    source = inspect.getsource(launcher.main)
    assert "if args.disable_manual_resume" in source
    assert "QTimer.singleShot(int((args.normal_seconds + args.freeze_seconds) * 1000), _resume)" in source
