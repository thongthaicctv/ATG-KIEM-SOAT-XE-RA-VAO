"""app/services/pipeline_diagnostics.py

Phase 4.7E-B1 - PREVIEW/LIVE TELEMETRY (DIAGNOSTIC ONLY, NO RECOVERY).

Boi canh: audit Phase 4.7E-A chung minh MainWindow.last_capture_frame KHONG phai raw
capture liveness - no CHI duoc cap nhat ben trong on_preview_frame(), tuc la no do
"lan cuoi preview den duoc MainWindow", khong phai "lan cuoi RTSP nhan duoc frame".
He qua truc tiep: _check_pipeline_health() hien tai KHONG THE phat hien truong hop
RTSP/AI van song nhung rieng preview bi dung (dung chinh trieu chung nguoi dung bao
cao). Phase nay CHI bo sung telemetry/chan doan (KHONG suy doan trang thai nghiep vu,
KHONG phuc hoi tu dong - xem yeu cau muc 8: "NO HEALTH-STATE RECOVERY YET").

Module nay CHU DICH thuan (khong phu thuoc Qt/thread/DB) de co the kiem thu truc tiep,
giong quy uoc da co cua zone_occupancy.py. main_window.py/camera_manager.py chi thu
thap cac gia tri monotonic tho (raw_capture_monotonic, worker_preview_monotonic,
manager_preview_emit_monotonic, ui_preview_monotonic, ai_result_monotonic - da co san
hoac duoc them o day) va goi build_diagnostic_snapshot()/classify_pipeline_health() o
day de tinh tuoi (age) va phan loai chan doan.

QUAN TRONG - day KHONG phai mot business/UI state moi. business_state (OCCUPIED,
LEAVING, RECOVERY_PENDING...) VAN hoan toan tach biet va KHONG bi thay the - xem yeu
cau Correction #3. classification tra ve boi classify_pipeline_health() CHI dung cho
log chan doan/test o Phase B1 nay, KHONG duoc dung de goi camera_offline(), khong tao
PARK_END, khong restart worker/RTSP/timer - bat ky hanh dong phuc hoi nao deu CHUA duoc
phep trong Phase 4.7E-B1 (se can bang chung Windows that truoc, xem yeu cau muc 8).

Nguong mac dinh: capture_stale_seconds tai su dung DUNG gia tri RtspCapture.
hard_restart_timeout (18.0s, da field-validate Phase 4.7B/4.7B.1) va ai_stale_seconds
tai su dung DUNG nguong 10s da co san/da duoc chap nhan trong _check_pipeline_health()
cu - KHONG bia so moi cho hai truc nay. worker/manager/ui preview stale deu la truc
MOI (chua co nguong truoc do) - chon 6.0s (~lon hon nhieu so voi chu ky preview thong
thuong o 5 FPS = 0.2s/frame, du nhay de bat stall that trong pham vi vai giay ma van
khong bao dong gia trong cac khoang idle/soft-stall binh thuong da duoc Phase 4.7B ghi
nhan) - co the tinh chinh sau khi co bang chung Windows that (xem yeu cau muc 13/K).
"""
from __future__ import annotations

from dataclasses import dataclass

DEFAULT_CAPTURE_STALE_SECONDS = 18.0
DEFAULT_AI_STALE_SECONDS = 10.0
DEFAULT_WORKER_PREVIEW_STALE_SECONDS = 6.0
DEFAULT_MANAGER_PREVIEW_STALE_SECONDS = 6.0
DEFAULT_UI_PREVIEW_STALE_SECONDS = 6.0
DEFAULT_GUI_DELAY_TOLERANCE_SECONDS = 1.0


@dataclass(frozen=True, slots=True)
class PipelineDiagnosticSnapshot:
    camera_id: object
    raw_capture_age: float | None
    ai_result_age: float | None
    worker_preview_sequence: int | None
    worker_preview_age: float | None
    manager_preview_emit_age: float | None
    ui_preview_age: float | None
    configured_preview_fps: float | None
    actual_preview_fps: float | None
    dropped_capture_frames: int
    dropped_preview_frames: int
    classification: str


def classify_pipeline_health(raw_capture_age, ai_result_age, worker_preview_age, manager_preview_emit_age, ui_preview_age,
                              capture_stale_seconds=DEFAULT_CAPTURE_STALE_SECONDS, ai_stale_seconds=DEFAULT_AI_STALE_SECONDS,
                              worker_preview_stale_seconds=DEFAULT_WORKER_PREVIEW_STALE_SECONDS,
                              manager_preview_stale_seconds=DEFAULT_MANAGER_PREVIEW_STALE_SECONDS,
                              ui_preview_stale_seconds=DEFAULT_UI_PREVIEW_STALE_SECONDS) -> str:
    """Tra ve NHAN CHAN DOAN don (mot chuoi) dai dien cho cong doan CHUA STALE xa nhat
    ve phia thuong nguon (raw capture -> AI -> worker preview -> manager preview ->
    UI preview) - vi mot cong doan thuong nguon bi stale se giai thich duoc moi trieu
    chung ha nguon, nen uu tien bao cao no truoc. AI la mot truc DOC LAP voi chuoi
    preview (co the cung ton tai dong thoi voi mot preview-stage stale khac trong thuc
    te - ham nay CHI tra ve MOT nhan don gian phuc vu log/test, KHONG phai mot tap co
    the co nhieu co bao cung luc).

    Phase 4.7E-B1.1 CORRECTION (muc 1/2): None cho bat ky tuoi (age) nao nghia la
    "cong doan nay CHUA TUNG duoc quan sat" (khoi dong / vua ket noi lai / worker vua
    restart / chua co ket qua AI dau tien / chua co preview flush dau tien) - day KHONG
    phai la STALE (STALE nghia la "DA TUNG quan sat duoc mot heartbeat, va tuoi cua no
    vuot nguong"). Nham lan hai khai niem nay tao ra chan doan STALE GIA trong dung
    trieu chung khoi dong/reconnect binh thuong. Vi vay None duoc bao cao bang mot nhan
    rieng ket thuc bang "_NOT_OBSERVED" (KHONG bao gio la "*_STALE"), va thu tu uu tien
    thuong-nguon-truoc duoc GIU NGUYEN y het truoc day mot khi heartbeat DA duoc quan
    sat (tuc la khac None)."""
    if raw_capture_age is None:
        return "RAW_NOT_OBSERVED"
    if raw_capture_age > capture_stale_seconds:
        return "CAPTURE_STALE"
    if ai_result_age is None:
        return "AI_NOT_OBSERVED"
    if ai_result_age > ai_stale_seconds:
        return "AI_STALE"
    if worker_preview_age is None:
        return "WORKER_PREVIEW_NOT_OBSERVED"
    if worker_preview_age > worker_preview_stale_seconds:
        return "WORKER_PREVIEW_STALE"
    if manager_preview_emit_age is None:
        return "MANAGER_PREVIEW_NOT_OBSERVED"
    if manager_preview_emit_age > manager_preview_stale_seconds:
        return "PREVIEW_DOWNSTREAM_STALE"
    if ui_preview_age is None:
        return "UI_PREVIEW_NOT_OBSERVED"
    if ui_preview_age > ui_preview_stale_seconds:
        return "UI_PREVIEW_STALE"
    return "LIVE"


def build_diagnostic_snapshot(camera_id, now, *, raw_capture_monotonic=None, ai_result_monotonic=None,
                               worker_preview_sequence=None, worker_preview_monotonic=None,
                               manager_preview_emit_monotonic=None, ui_preview_monotonic=None,
                               configured_preview_fps=None, actual_preview_fps=None,
                               dropped_capture_frames=0, dropped_preview_frames=0,
                               **threshold_overrides) -> PipelineDiagnosticSnapshot:
    """Ghep cac gia tri monotonic tho (co the None neu chua tung quan sat) thanh mot
    PipelineDiagnosticSnapshot day du - tinh tuoi (age = now - monotonic, KHONG am) va
    goi classify_pipeline_health(). threshold_overrides duoc chuyen tiep nguyen ven cho
    classify_pipeline_health() (vd de test tuy chinh nguong)."""
    def age(monotonic_value):
        return None if monotonic_value is None else max(0.0, now - monotonic_value)
    raw_capture_age = age(raw_capture_monotonic)
    ai_result_age = age(ai_result_monotonic)
    worker_preview_age = age(worker_preview_monotonic)
    manager_preview_emit_age = age(manager_preview_emit_monotonic)
    ui_preview_age = age(ui_preview_monotonic)
    classification = classify_pipeline_health(raw_capture_age, ai_result_age, worker_preview_age,
                                               manager_preview_emit_age, ui_preview_age, **threshold_overrides)
    return PipelineDiagnosticSnapshot(camera_id, raw_capture_age, ai_result_age, worker_preview_sequence,
                                       worker_preview_age, manager_preview_emit_age, ui_preview_age,
                                       configured_preview_fps, actual_preview_fps, dropped_capture_frames,
                                       dropped_preview_frames, classification)


def detect_gui_event_loop_delay(expected_interval_seconds, actual_gap_seconds,
                                 tolerance_seconds=DEFAULT_GUI_DELAY_TOLERANCE_SECONDS) -> bool:
    """Phase 4.7E-B1 muc 7: THUAN CHAN DOAN - KHONG duoc dung cho logic nghiep vu hay
    de restart camera (yeu cau muc 7/8). True nghia la khoang cach giua 2 lan
    _check_pipeline_health() tick lien tiep lon hon nhieu so voi chinh interval cua
    QTimer do - bang chung GIAN TIEP rang main/GUI event loop da bi block/tre trong
    khoang do (phat hien SAU KHI phuc hoi, khong phai trong luc dang bi dong bang -
    dung nhu yeu cau da neu ro)."""
    if expected_interval_seconds is None or expected_interval_seconds <= 0:
        return False
    return actual_gap_seconds > (expected_interval_seconds + max(0.0, tolerance_seconds))
