"""scripts/diagnose_rtsp_capture_phase_4_7b.py

Phase 4.7B - HOTFIX RTSP CAPTURE STABILITY (muc M: script chan doan Windows).
Cap nhat Phase 4.7B.1 (muc 14): them longest_frame_gap va stderr_error_counts
(nhom loi HEVC da biet) vao bao cao dinh ky - KHONG doi cach chay/tham so cu.

Script DOC-LAP, CHI-DOC (read-only): dung THANG class RtspCapture that (khong
YOLO/tracker/DB/UI, khong CameraWorker) de chay lien tuc 10 phut tren MOT camera
RTSP that va in bao cao moi 10 giay. Muc dich la xac nhan tren may Windows that
(voi camera LAN that) rang fix Phase 4.7B (stdout.read1(), soft/hard stall,
stderr diagnostics, JPEG buffer draining, reconnect backoff) va Phase 4.7B.1
(-use_wallclock_as_timestamps, do luong longest_frame_gap, dem loi HEVC theo
nhom) giai quyet duoc RTSP_CAPTURE_FAIL / hard_restarts qua nhieu quan sat duoc
truoc do (xem Phase 4.7B report muc A, Phase 4.7B.1 report muc 1-2).

KHONG ghi vao database. KHONG doi bat ky cau hinh camera/model/polygon/timer nao.
KHONG hardcode RTSP URL/credential o bat ky dau trong file nay - URL PHAI duoc
truyen vao luc chay qua bien moi truong ATG_DIAG_RTSP_URL (xem huong dan --help
va vi du PowerShell trong bao cao). Neu ban vo tinh dan URL that vao dong lenh,
no se KHONG bi script nay ghi ra log/report - chi phan sanitize (rtsp://<redacted>)
duoc in ra.

Cach chay (PowerShell, tu thu muc goc du an, dung Python trong .venv):

    $env:ATG_DIAG_RTSP_URL = "rtsp://<user>:<pass>@<ip>:554/<path>"
    .venv\\Scripts\\python.exe scripts\\diagnose_rtsp_capture_phase_4_7b.py

Hoac dung wrapper scripts\\diagnose-rtsp-capture.ps1 (xem file do).

Tieu chi PASS (xem bao cao Phase 4.7B muc M): chay lien tuc 10 phut, khong co
"unrecovered stall" (tuc la neu co hard_restart thi phai tu hoi phuc va tiep tuc
nhan frame trong lan thu lai ke tiep, khong bi ket mai o trang thai loi).
"""
from __future__ import annotations

import os
import sys
import time
from datetime import datetime, timezone

# Cho phep chay truc tiep "python scripts/diagnose_rtsp_capture_phase_4_7b.py"
# tu thu muc goc du an ma khong can cai dat package - them thu muc goc vao sys.path.
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from app.services.rtsp_capture import RtspCapture, _sanitize_diagnostic_text  # noqa: E402

# Cho phep override qua bien moi truong CHI de phuc vu smoke-test tu dong (vi du
# chay 5s thay vi 600s) - gia tri mac dinh dung dung yeu cau 10 phut / 10 giay.
RUN_SECONDS = float(os.environ.get("ATG_DIAG_RUN_SECONDS", "600"))
REPORT_INTERVAL_SECONDS = float(os.environ.get("ATG_DIAG_REPORT_INTERVAL_SECONDS", "10"))
# Backoff co dinh, ngan, gioi han khi thu ket noi lai sau HARD FAILURE - script nay
# CHI la cong cu chan doan doc lap, khong dung lai logic backoff-tang-dan cua
# CameraWorker (xem app/services/camera_worker.py - KHONG bi thay doi trong file nay).
_RECONNECT_BACKOFF_SECONDS = 2.0


def _fmt_shape(shape):
    if shape is None:
        return "-"
    return "x".join(str(v) for v in shape)


def _print_status(elapsed, frame_count, last_shape, cap, total_dropped, total_soft_stalls, total_hard_restarts, longest_frame_gap_overall):
    age = cap.last_frame_age
    age_str = f"{age:.1f}s" if age is not None else "-"
    # Phase 4.7B.1: longest_frame_gap TONG (qua ca cac lan reconnect, khong chi phien
    # open() hien tai) - lay MAX giua gia tri da tich luy va gia tri cua cap hien tai.
    current_gap = cap.longest_frame_gap
    if current_gap is not None:
        longest_frame_gap_overall = current_gap if longest_frame_gap_overall is None else max(longest_frame_gap_overall, current_gap)
    gap_str = f"{longest_frame_gap_overall:.1f}s" if longest_frame_gap_overall is not None else "-"
    print(
        "[{ts}] elapsed={elapsed:6.1f}s frame_count={fc:6d} frame_shape={shape:<12} "
        "queue_size={qs} dropped_capture_frames={dropped} last_frame_age={age} "
        "longest_frame_gap={gap} ffmpeg_alive={alive} soft_stalls={soft} hard_restarts={hard}".format(
            ts=datetime.now(timezone.utc).strftime("%H:%M:%S"),
            elapsed=elapsed,
            fc=frame_count,
            shape=_fmt_shape(last_shape),
            qs=cap.queue_size,
            dropped=total_dropped + cap.dropped_capture_frames,
            age=age_str,
            gap=gap_str,
            alive=cap.is_opened(),
            soft=total_soft_stalls + cap.consecutive_soft_stalls,
            hard=total_hard_restarts + cap.hard_restarts,
        ),
        flush=True,
    )
    return longest_frame_gap_overall


def main() -> int:
    url = os.environ.get("ATG_DIAG_RTSP_URL", "").strip()
    if not url:
        print("LOI: chua thiet lap bien moi truong ATG_DIAG_RTSP_URL.")
        print("Vi du PowerShell (KHONG hardcode URL trong file nay hay bat ky script nao khac):")
        print('  $env:ATG_DIAG_RTSP_URL = "rtsp://<user>:<pass>@<ip>:554/<path>"')
        print("  .venv\\Scripts\\python.exe scripts\\diagnose_rtsp_capture_phase_4_7b.py")
        return 2

    sanitized_url = _sanitize_diagnostic_text(url, url)
    print("=== Phase 4.7B: RTSP capture stability diagnostic ===")
    print(f"URL (sanitized): {sanitized_url}")
    print(f"Thoi luong: {RUN_SECONDS:.0f}s, bao cao moi {REPORT_INTERVAL_SECONDS:.0f}s")
    print("Script nay CHI DOC (khong ghi database, khong doi cau hinh camera/model/polygon/timer).")
    print("")

    start = time.monotonic()
    next_report = start + REPORT_INTERVAL_SECONDS
    frame_count = 0
    last_shape = None
    total_dropped = 0
    total_soft_stalls = 0
    total_hard_restarts = 0
    longest_frame_gap_overall = None
    stderr_error_counts_overall = {}
    unrecovered = False

    cap = RtspCapture(url)
    if not cap.open():
        print("LOI: khong mo duoc FFmpeg (kiem tra ffmpeg co trong PATH va URL dung dinh dang).")
        return 1

    try:
        while True:
            now = time.monotonic()
            elapsed = now - start
            if elapsed >= RUN_SECONDS:
                break

            ok, frame = cap.read()
            now = time.monotonic()
            elapsed = now - start

            if ok:
                frame_count += 1
                last_shape = frame.shape
            else:
                # HARD FAILURE: process chet hoac khong co frame nao trong
                # hard_restart_timeout giay. In stderr summary (tail rate-limited +
                # tom tat so lan tung nhom loi HEVC - Phase 4.7B.1) de chan doan, roi
                # tu dong mo lai (mo phong CameraWorker reconnect o muc toi thieu can
                # thiet cho script chan doan doc lap nay).
                print(
                    f"[{datetime.now(timezone.utc).strftime('%H:%M:%S')}] HARD FAILURE luc elapsed={elapsed:.1f}s "
                    f"- se thu ket noi lai sau {_RECONNECT_BACKOFF_SECONDS:.0f}s. FFmpeg stderr summary (sanitized):",
                    flush=True,
                )
                summary = cap.get_stderr_summary()
                print(summary if summary else "  (khong co stderr)", flush=True)

                current_gap = cap.longest_frame_gap
                if current_gap is not None:
                    longest_frame_gap_overall = current_gap if longest_frame_gap_overall is None else max(longest_frame_gap_overall, current_gap)
                for label, count in cap.get_stderr_error_counts().items():
                    stderr_error_counts_overall[label] = stderr_error_counts_overall.get(label, 0) + count

                total_dropped += cap.dropped_capture_frames
                total_soft_stalls += cap.consecutive_soft_stalls
                total_hard_restarts += cap.hard_restarts
                cap.release()

                if elapsed >= RUN_SECONDS:
                    unrecovered = True
                    break

                time.sleep(_RECONNECT_BACKOFF_SECONDS)
                cap = RtspCapture(url)
                if not cap.open():
                    print("LOI: khong mo lai duoc FFmpeg sau HARD FAILURE - dung script.", flush=True)
                    unrecovered = True
                    break

            if now >= next_report:
                longest_frame_gap_overall = _print_status(elapsed, frame_count, last_shape, cap, total_dropped, total_soft_stalls, total_hard_restarts, longest_frame_gap_overall)
                next_report = now + REPORT_INTERVAL_SECONDS

        elapsed = time.monotonic() - start
        longest_frame_gap_overall = _print_status(elapsed, frame_count, last_shape, cap, total_dropped, total_soft_stalls, total_hard_restarts, longest_frame_gap_overall)
    finally:
        for label, count in cap.get_stderr_error_counts().items():
            stderr_error_counts_overall[label] = stderr_error_counts_overall.get(label, 0) + count
        cap.release()

    print("")
    gap_summary = f"{longest_frame_gap_overall:.1f}s" if longest_frame_gap_overall is not None else "-"
    print(f"longest_frame_gap (toan bo lan chay): {gap_summary}")
    if stderr_error_counts_overall:
        print("stderr_error_counts (toan bo lan chay): " + ", ".join(f"{label}={count}" for label, count in sorted(stderr_error_counts_overall.items())))
    print("")

    if unrecovered:
        print(f"KET QUA: FAIL - khong hoi phuc duoc trong {RUN_SECONDS:.0f}s (unrecovered stall/failure).")
        return 1

    if frame_count == 0:
        print(
            f"KET QUA: FAIL - chay du {RUN_SECONDS:.0f}s nhung KHONG nhan duoc frame hop le nao "
            f"(hard_restarts={total_hard_restarts}). Kiem tra URL/mang/camera - xem stderr o tren."
        )
        return 1

    if total_hard_restarts > 1:
        print(
            f"KET QUA: FAIL (Phase 4.7B.1 acceptance) - hard_restarts={total_hard_restarts} trong {RUN_SECONDS:.0f}s "
            "vuot qua nguong san xuat cho phep (<=1/10 phut). Xem longest_frame_gap/stderr_error_counts o tren de "
            "danh gia co can dieu chinh them khong (KHONG tu dong doi hard_restart_timeout - xem bao cao Phase 4.7B.1 muc 7)."
        )
        return 1

    print(
        f"KET QUA: PASS - chay lien tuc {RUN_SECONDS:.0f}s, nhan {frame_count} frame, "
        f"soft_stalls={total_soft_stalls}, hard_restarts={total_hard_restarts} (<=1, dat tieu chi Phase 4.7B.1), "
        f"longest_frame_gap={gap_summary}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
