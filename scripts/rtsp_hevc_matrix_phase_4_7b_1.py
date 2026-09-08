"""scripts/rtsp_hevc_matrix_phase_4_7b_1.py

Phase 4.7B.1 - HEVC RTSP DECODER CONTINUITY HOTFIX (muc 12: test matrix bat buoc
TRUOC khi chon flag production).

Script DOC-LAP, CHI-DOC (read-only): chay lien tiep CUNG MOT camera RTSP that qua
2 bien the RtspCapture khac nhau (BASELINE = argv Phase 4.7B goc, CANDIDATE 1 =
argv Phase 4.7B.1 moi + -use_wallclock_as_timestamps 1), moi bien the trong mot
khoang thoi gian NGAN hon 10 phut (mac dinh 120s/bien the - du de lo van de da
quan sat duoc tren camera that: hard_restarts=6/600s ~ trung binh 1 lan/100s) -
roi in bang so sanh frames/soft_stalls/hard_restarts/longest_frame_gap/
stderr_error_counts giua 2 bien the.

MUC DICH: cho phep quyet dinh bang SO LIEU THAT tren CHINH camera dang co van de,
thay vi doan mo hoac chi tin vao ly luan/tai lieu FFmpeg. Day la buoc "automated
short matrix" theo yeu cau muc 12 - CHAY TRUOC, roi moi chay 10-phut acceptance
rieng (scripts/diagnose_rtsp_capture_phase_4_7b.py) cho CANDIDATE thang cuoc.

KHONG ghi database. KHONG doi cau hinh camera/model/polygon/timer. KHONG hardcode
RTSP URL/credential - URL PHAI duoc truyen qua bien moi truong ATG_DIAG_RTSP_URL.

Cach chay (PowerShell, tu thu muc goc du an, dung Python trong .venv):

    $env:ATG_DIAG_RTSP_URL = "rtsp://<user>:<pass>@<ip>:554/<path>"
    .venv\\Scripts\\python.exe scripts\\rtsp_hevc_matrix_phase_4_7b_1.py

Mac dinh moi bien the chay 120s (co the doi qua ATG_MATRIX_VARIANT_SECONDS neu can
dai hon de lo van de ro hon - vi du camera co GOP/keyframe interval rat dai).
"""
from __future__ import annotations

import os
import sys
import time
from datetime import datetime, timezone

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from app.services.rtsp_capture import RtspCapture, _sanitize_diagnostic_text  # noqa: E402

VARIANT_SECONDS = float(os.environ.get("ATG_MATRIX_VARIANT_SECONDS", "120"))
_RECONNECT_BACKOFF_SECONDS = 2.0

# Phase 4.7B.1 muc 12: BASELINE = argv Phase 4.7B goc (khong wallclock timestamps).
# CANDIDATE 1 = argv Phase 4.7B.1 moi (mac dinh cua RtspCapture - co wallclock).
# Them CANDIDATE khac vao day (vi du hard_restart_timeout dai hon) neu Candidate 1
# khong dat tieu chi hard_restarts<=1/10 phut va can thu nghiem them mot bien the
# duoc chung minh co co so (KHONG doan mo - xem bao cao muc 7).
VARIANTS = (
    ("BASELINE (Phase 4.7B, khong wallclock timestamps)", {"use_wallclock_timestamps": False}),
    ("CANDIDATE 1 (Phase 4.7B.1, +use_wallclock_as_timestamps 1)", {"use_wallclock_timestamps": True}),
)


def _run_variant(url: str, label: str, capture_kwargs: dict, duration_seconds: float) -> dict:
    print(f"\n=== {label} ({duration_seconds:.0f}s) ===", flush=True)
    frame_count = 0
    total_dropped = 0
    total_soft_stalls = 0
    total_hard_restarts = 0
    longest_frame_gap = None
    stderr_error_counts: dict = {}
    ffmpeg_exit_without_recovery = False

    start = time.monotonic()
    cap = RtspCapture(url, **capture_kwargs)
    if not cap.open():
        print("  LOI: khong mo duoc FFmpeg cho bien the nay.")
        return {
            "label": label, "frames": 0, "soft_stalls": 0, "hard_restarts": 0,
            "longest_frame_gap": None, "stderr_error_counts": {}, "open_failed": True,
        }

    try:
        while time.monotonic() - start < duration_seconds:
            ok, _frame = cap.read()
            if ok:
                frame_count += 1
                continue
            elapsed = time.monotonic() - start
            print(f"  [{datetime.now(timezone.utc).strftime('%H:%M:%S')}] HARD FAILURE elapsed={elapsed:.1f}s", flush=True)
            summary = cap.get_stderr_summary()
            if summary:
                for line in summary.splitlines():
                    print(f"    {line}")
            current_gap = cap.longest_frame_gap
            if current_gap is not None:
                longest_frame_gap = current_gap if longest_frame_gap is None else max(longest_frame_gap, current_gap)
            for lbl, cnt in cap.get_stderr_error_counts().items():
                stderr_error_counts[lbl] = stderr_error_counts.get(lbl, 0) + cnt
            total_dropped += cap.dropped_capture_frames
            total_soft_stalls += cap.consecutive_soft_stalls
            total_hard_restarts += cap.hard_restarts
            cap.release()

            if time.monotonic() - start >= duration_seconds:
                break
            time.sleep(_RECONNECT_BACKOFF_SECONDS)
            cap = RtspCapture(url, **capture_kwargs)
            if not cap.open():
                print("  LOI: khong mo lai duoc FFmpeg sau HARD FAILURE trong bien the nay.")
                ffmpeg_exit_without_recovery = True
                break
    finally:
        current_gap = cap.longest_frame_gap
        if current_gap is not None:
            longest_frame_gap = current_gap if longest_frame_gap is None else max(longest_frame_gap, current_gap)
        for lbl, cnt in cap.get_stderr_error_counts().items():
            stderr_error_counts[lbl] = stderr_error_counts.get(lbl, 0) + cnt
        cap.release()

    result = {
        "label": label,
        "frames": frame_count,
        "soft_stalls": total_soft_stalls,
        "hard_restarts": total_hard_restarts,
        "longest_frame_gap": longest_frame_gap,
        "stderr_error_counts": stderr_error_counts,
        "open_failed": False,
        "unrecovered": ffmpeg_exit_without_recovery,
    }
    gap_str = f"{longest_frame_gap:.1f}s" if longest_frame_gap is not None else "-"
    print(
        f"  KET QUA bien the: frames={frame_count} soft_stalls={total_soft_stalls} "
        f"hard_restarts={total_hard_restarts} longest_frame_gap={gap_str} dropped={total_dropped}",
        flush=True,
    )
    if stderr_error_counts:
        print("  stderr_error_counts: " + ", ".join(f"{k}={v}" for k, v in sorted(stderr_error_counts.items())))
    return result


def main() -> int:
    url = os.environ.get("ATG_DIAG_RTSP_URL", "").strip()
    if not url:
        print("LOI: chua thiet lap bien moi truong ATG_DIAG_RTSP_URL.")
        print('  $env:ATG_DIAG_RTSP_URL = "rtsp://<user>:<pass>@<ip>:554/<path>"')
        print("  .venv\\Scripts\\python.exe scripts\\rtsp_hevc_matrix_phase_4_7b_1.py")
        return 2

    sanitized_url = _sanitize_diagnostic_text(url, url)
    print("=== Phase 4.7B.1: RTSP HEVC continuity - test matrix BASELINE vs CANDIDATE ===")
    print(f"URL (sanitized): {sanitized_url}")
    print(f"Moi bien the chay {VARIANT_SECONDS:.0f}s tren CUNG mot camera, lan luot (khong dong thoi).")
    print("Script nay CHI DOC (khong ghi database, khong doi cau hinh camera/model/polygon/timer).")

    results = [_run_variant(url, label, kwargs, VARIANT_SECONDS) for label, kwargs in VARIANTS]

    print("\n=== BANG SO SANH ===")
    header = f"{'Bien the':<55} {'frames':>8} {'soft':>6} {'hard':>6} {'longest_gap':>12}"
    print(header)
    print("-" * len(header))
    for r in results:
        gap_str = f"{r['longest_frame_gap']:.1f}s" if r["longest_frame_gap"] is not None else "-"
        print(f"{r['label']:<55} {r['frames']:>8} {r['soft_stalls']:>6} {r['hard_restarts']:>6} {gap_str:>12}")

    print("")
    baseline, candidate1 = results[0], results[1]
    if candidate1["hard_restarts"] < baseline["hard_restarts"]:
        print(
            f"=> CANDIDATE 1 giam hard_restarts ({baseline['hard_restarts']} -> {candidate1['hard_restarts']}) "
            f"trong {VARIANT_SECONDS:.0f}s tren cung camera nay - de xuat chay 10-phut acceptance rieng "
            "(scripts/diagnose_rtsp_capture_phase_4_7b.py) de xac nhan chinh thuc."
        )
    elif candidate1["hard_restarts"] == baseline["hard_restarts"]:
        print(
            "=> CANDIDATE 1 KHONG thay doi so hard_restarts so voi BASELINE trong lan chay ngan nay - "
            "co the can chay lau hon (tang ATG_MATRIX_VARIANT_SECONDS) hoac xem xet them CANDIDATE 2 "
            "(vi du dieu chinh hard_restart_timeout co co so tu longest_frame_gap quan sat duoc o tren)."
        )
    else:
        print(
            "=> CANDIDATE 1 CO NHIEU hard_restarts hon BASELINE trong lan chay ngan nay - KHONG de xuat "
            "ap dung wallclock timestamps cho camera nay ma khong dieu tra them."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
