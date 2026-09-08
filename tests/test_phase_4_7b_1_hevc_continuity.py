"""tests/test_phase_4_7b_1_hevc_continuity.py

Phase 4.7B.1 - HEVC RTSP DECODER CONTINUITY HOTFIX.

Field data thuc te (Windows, camera LAN that, sau Phase 4.7B): kien truc soft/hard
stall cua Phase 4.7B hoat dong dung (khong con chet vinh vien, luon hoi phuc), nhung
hard_restarts=6/10 phut la qua nhieu cho san xuat 24/7 (yeu cau <=1/10 phut). Stderr
FFmpeg trong cac dot hard-stall la loi HEVC decoder CO THE PHUC HOI (mat tham chieu
POC/RPS, NALU khong giai ma duoc, DTS khong tang don dieu) - KHONG phai mat ket noi
TCP that.

File test nay tap trung vao CAC THAY DOI THUC SU cua Phase 4.7B.1 (xem doc dau file
app/services/rtsp_capture.py):
  1) -use_wallclock_as_timestamps 1 duoc them vao argv FFmpeg mac dinh (dat truoc -i,
     dung INPUT option), co the tat qua use_wallclock_timestamps=False de tai hien
     argv Phase 4.7B goc (dung cho test matrix BASELINE/CANDIDATE - xem
     scripts/rtsp_hevc_matrix_phase_4_7b_1.py).
  2) longest_frame_gap: do luong THUC TE khoang cach lon nhat giua 2 frame hop le
     lien tiep trong CUNG mot phien open() - KHONG doan mo nguong hard_restart_timeout
     (DEFAULT_HARD_RESTART_SECONDS van giu nguyen 18.0s trong phase nay).
  3) Dem/rate-limit stderr theo nhom loi HEVC da biet (POC ref/RPS/NALU/DTS) de tranh
     tran tail bang hang tram dong lap lai giong het nhau, van giu tom tat tong so lan
     qua get_stderr_error_counts()/get_stderr_summary().

KHONG dong cham parking session/tracker/polygon/timer/DB/YOLO - test nay CHI danh cho
app/services/rtsp_capture.py (RTSP/FFmpeg HEVC continuity).
"""
from __future__ import annotations

import os
import shutil
import subprocess

import cv2
import numpy as np
import pytest

from app.services.rtsp_capture import (
    DEFAULT_HARD_RESTART_SECONDS,
    RtspCapture,
    _STDERR_KNOWN_ERROR_PATTERNS,
)


def _make_jpeg_bytes(seed: int = 0) -> bytes:
    """JPEG that (dung cv2.imencode) voi noise ngau nhien de frame_is_valid() luon dung."""
    rng = np.random.default_rng(seed)
    image = rng.integers(0, 255, size=(24, 24, 3), dtype=np.uint8)
    ok, encoded = cv2.imencode(".jpg", image)
    assert ok
    return encoded.tobytes()


class _FakeProcess:
    def __init__(self, alive=True):
        self._alive = alive
    def poll(self):
        return None if self._alive else 0
    def terminate(self):
        self._alive = False
    def wait(self, timeout=None):
        return 0
    def kill(self):
        self._alive = False


def _bare_capture(**kwargs) -> RtspCapture:
    """RtspCapture chi qua __init__ (KHONG goi open()) - an toan de gan
    self.process = _FakeProcess() va kiem tra logic thuan Python, khong spawn FFmpeg."""
    return RtspCapture("rtsp://user:pass@example.invalid/stream", **kwargs)


def _captured_open_argv(monkeypatch, **capture_kwargs):
    """Goi RtspCapture.open() that (logic that, khong FFmpeg that) qua subprocess.Popen
    da monkeypatch TAM THOI (chi trong pham vi ham nay - dung MonkeyPatch.context() rieng
    de KHONG con anh huong subprocess.Popen thuc su sau khi ham nay return, vi
    app.services.rtsp_capture.subprocess LA CUNG mot module object voi `subprocess` da
    import truc tiep trong file test nay), tra ve chinh xac argv list ma production se dung."""
    captured = {}

    class _Recorder:
        def __init__(self, command, **kwargs):
            captured["command"] = command
            captured["kwargs"] = kwargs
            self.stdout = None
            self.stderr = None
        def poll(self):
            return None

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("app.services.rtsp_capture.shutil.which", lambda name: "/usr/bin/ffmpeg")
        mp.setattr("app.services.rtsp_capture.subprocess.Popen", _Recorder)
        capture = RtspCapture("rtsp://user:pass@example.invalid/stream", **capture_kwargs)
        assert capture.open() is True
        capture.reader.join(timeout=2)
        capture.stderr_reader.join(timeout=2)
    return captured["command"]


# --- 1. FFmpeg argv generation: nhom flag/vi tri dung ---------------------------

def test_default_argv_includes_wallclock_flag_as_input_option_before_i(monkeypatch):
    """Muc 4/17: -use_wallclock_as_timestamps la INPUT option nen PHAI dung TRUOC -i,
    va la hanh vi MAC DINH (use_wallclock_timestamps=True) cua Phase 4.7B.1."""
    command = _captured_open_argv(monkeypatch)
    assert "-use_wallclock_as_timestamps" in command
    flag_index = command.index("-use_wallclock_as_timestamps")
    assert command[flag_index + 1] == "1"
    i_index = command.index("-i")
    assert flag_index < i_index, "phai la INPUT option (truoc -i), khong phai OUTPUT option"
    # Cac output-side flag (sau -i) van giu nguyen tu Phase 4.7B, khong bi xao tron vi tri.
    assert command.index("-an") > i_index
    assert command.index("-vcodec") > i_index


def test_use_wallclock_timestamps_false_reproduces_phase_4_7b_baseline_argv(monkeypatch):
    """Cho phep test matrix (muc 12) tai hien CHINH XAC argv Phase 4.7B goc (khong co
    wallclock) de so sanh BASELINE vs CANDIDATE tren CUNG mot RTSP URL that."""
    command = _captured_open_argv(monkeypatch, use_wallclock_timestamps=False)
    assert "-use_wallclock_as_timestamps" not in command
    # Cac flag HEVC-tolerance tu Phase 4.7B van phai con nguyen trong BASELINE.
    assert "-fflags" in command and "+discardcorrupt+genpts" in command
    assert "-err_detect" in command and "ignore_err" in command
    assert "-rtsp_transport" in command and "tcp" in command


def test_ffmpeg_argv_has_no_duplicated_or_conflicting_flags(monkeypatch):
    """Muc 13: khong duoc co flag lap/xung dot khi them wallclock timestamps."""
    for kwargs in ({}, {"use_wallclock_timestamps": False}):
        command = _captured_open_argv(monkeypatch, **kwargs)
        flag_tokens = [tok for tok in command if tok.startswith("-")]
        for flag in ("-fflags", "-err_detect", "-use_wallclock_as_timestamps", "-rtsp_transport", "-i", "-an", "-f", "-vcodec", "-q:v", "-loglevel", "-hide_banner"):
            count = flag_tokens.count(flag)
            assert count <= 1, f"flag {flag} xuat hien {count} lan trong argv={command}"


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="can FFmpeg that de kiem chung argv duoc chap nhan")
def test_real_ffmpeg_accepts_production_argv_with_wallclock_flag(monkeypatch):
    """Xac nhan FFmpeg CAI DAT THAT (khong mock) chap nhan dung argv production se dung,
    bang cach thay '-i <rtsp_url>' bang mot nguon lavfi testsrc cuc ngan (khong can
    mang/RTSP that) - chi kiem tra CU PHAP/THU TU option, khong kiem tra HEVC that."""
    command = _captured_open_argv(monkeypatch)
    i_index = command.index("-i")
    input_side = command[:i_index]
    # -rtsp_transport la option RIENG cua rtsp demuxer, khong hop le voi nguon lavfi -
    # bo cap nay khi thay the (rtsp_transport da la option chuan tai lieu hoa cua FFmpeg
    # cho giao thuc rtsp://, khong can kiem chung lai o day). Cac flag con lai (fflags,
    # err_detect, use_wallclock_as_timestamps) la nhung gi test nay muon xac nhan.
    if "-rtsp_transport" in input_side:
        idx = input_side.index("-rtsp_transport")
        input_side = input_side[:idx] + input_side[idx + 2:]
    output_side = command[i_index + 2:]
    # QUAN TRONG: GIU NGUYEN toan bo output-side flags (-f image2pipe -vcodec mjpeg -q:v 5)
    # dung nhu production - CHI doi dich "pipe:1" -> os.devnull (thay vi hardcode
    # "/dev/null") de khong can doc stdout that trong test VA de test nay chay duoc
    # tren ca Windows (nul) lan POSIX (/dev/null) - may Windows acceptance khong co
    # duong dan /dev/null nen truoc day loi "Error opening output /dev/null: No such
    # file or directory". (Ban dau tung thu doi thanh "-f null -" nhung do tao ra HAI
    # "-f" xung dot + mismatch codec/muxer, tu gay ra loi "Invalid pts <= last" GIA -
    # khong phai loi thuc su cua wallclock timestamps; giu dung -f image2pipe nhu
    # production moi phan anh dung hanh vi that.)
    if output_side and output_side[-1] == "pipe:1":
        output_side = output_side[:-1] + [os.devnull]
    real_command = ["ffmpeg", "-y"] + input_side[1:] + ["-f", "lavfi", "-i", "testsrc=duration=1:size=64x64:rate=5"] + output_side
    result = subprocess.run(real_command, capture_output=True, timeout=15)
    assert result.returncode == 0, f"FFmpeg tu choi argv production: {result.stderr.decode('utf-8','replace')}"


# --- 2. longest_frame_gap: do luong thuc te, khong doan mo ----------------------

def _publish_fake_valid_frame(capture: RtspCapture, monkeypatch, at_time: float, seed: int) -> None:
    monkeypatch.setattr("app.services.rtsp_capture.time.monotonic", lambda: at_time)
    capture.buffer.extend(_make_jpeg_bytes(seed))
    capture._drain_buffer()


def test_longest_frame_gap_is_none_after_first_frame_only(monkeypatch):
    capture = _bare_capture()
    assert capture.longest_frame_gap is None
    _publish_fake_valid_frame(capture, monkeypatch, at_time=100.0, seed=1)
    assert capture.longest_frame_gap is None, "chi 1 frame - chua co khoang cach nao de do"


def test_longest_frame_gap_tracks_maximum_not_most_recent(monkeypatch):
    """Frame 1 @ t=0, frame 2 @ t=5 (gap=5.0), frame 3 @ t=6.2 (gap=1.2) - longest_frame_gap
    phai la 5.0 (MAX), khong phai 1.2 (gap gan nhat)."""
    capture = _bare_capture()
    _publish_fake_valid_frame(capture, monkeypatch, at_time=0.0, seed=1)
    _publish_fake_valid_frame(capture, monkeypatch, at_time=5.0, seed=2)
    assert capture.longest_frame_gap == pytest.approx(5.0)
    _publish_fake_valid_frame(capture, monkeypatch, at_time=6.2, seed=3)
    assert capture.longest_frame_gap == pytest.approx(5.0), "khong duoc bi ghi de boi gap nho hon sau do"


def test_default_hard_restart_timeout_unchanged_in_this_phase():
    """Muc 7: KHONG doi nguong hard_restart_timeout trong Phase 4.7B.1 (them do luong
    longest_frame_gap truoc, chua co so lieu 'longest recoverable gap' that de dieu
    chinh nguong mot cach co can cu)."""
    assert DEFAULT_HARD_RESTART_SECONDS == 18.0
    assert _bare_capture().hard_restart_timeout == 18.0


# --- 3. Stderr dedup/rate-limit theo nhom loi HEVC da biet -----------------------

def _feed_stderr_lines(capture: RtspCapture, lines) -> None:
    """Mo phong _stderr_reader_loop ma khong can spawn FFmpeg that - goi truc tiep
    logic phan loai/dem (sao chep hanh vi cua vong lap that, dung API cong khai)."""
    from app.services.rtsp_capture import _sanitize_diagnostic_text, _STDERR_MAX_LINE_LENGTH
    for raw in lines:
        sanitized = _sanitize_diagnostic_text(raw, capture.url)[:_STDERR_MAX_LINE_LENGTH]
        matched_label = None
        for label, pattern in _STDERR_KNOWN_ERROR_PATTERNS:
            if pattern.search(sanitized):
                matched_label = label
                break
        if matched_label is not None:
            capture._stderr_error_counts[matched_label] = capture._stderr_error_counts.get(matched_label, 0) + 1
            if matched_label not in capture._stderr_seen_classes:
                capture._stderr_seen_classes.add(matched_label)
                capture._stderr_tail.append(sanitized)
        else:
            capture._stderr_tail.append(sanitized)


def test_known_hevc_errors_are_counted_not_flooding_tail_with_duplicates():
    capture = _bare_capture()
    lines = ["[hevc] Could not find ref with POC 12345"] * 50
    _feed_stderr_lines(capture, lines)
    counts = capture.get_stderr_error_counts()
    assert counts.get("hevc_ref_poc_missing") == 50, "phai dem DUNG tong so lan, khong bi mat"
    tail_occurrences = capture.get_stderr_tail().count("Could not find ref with POC")
    assert tail_occurrences == 1, "tail CHI giu lai 1 vi du dau tien, khong duoc lap 50 lan"


def test_multiple_known_error_classes_each_get_first_occurrence_in_tail():
    capture = _bare_capture()
    lines = [
        "Could not find ref with POC 1",
        "Could not find ref with POC 2",
        "Error constructing the frame RPS",
        "Skipping invalid undecodable NALU: 39",
        "Application provided invalid, non monotonically increasing dts",
        "Skipping invalid undecodable NALU: 40",
    ]
    _feed_stderr_lines(capture, lines)
    counts = capture.get_stderr_error_counts()
    assert counts == {
        "hevc_ref_poc_missing": 2,
        "hevc_rps_error": 1,
        "hevc_invalid_nalu": 2,
        "dts_non_monotonic": 1,
    }
    tail = capture.get_stderr_tail()
    assert tail.count("\n") == 3, "4 dong (1 moi nhom) -> 3 newline"


def test_unrecognized_stderr_lines_still_appended_to_tail_unfiltered():
    """Muc 9: 'Do not suppress the final useful diagnostic tail' - dong LA (khong khop
    nhom loi HEVC da biet) van phai xuat hien binh thuong, khong bi loc bo."""
    capture = _bare_capture()
    _feed_stderr_lines(capture, ["Unexpected FFmpeg warning we have never seen before"])
    assert "Unexpected FFmpeg warning we have never seen before" in capture.get_stderr_tail()
    assert capture.get_stderr_error_counts() == {}


def test_get_stderr_summary_includes_counts_line_when_known_errors_present():
    capture = _bare_capture()
    _feed_stderr_lines(capture, ["Could not find ref with POC 1"] * 3 + ["Error constructing the frame RPS"])
    summary = capture.get_stderr_summary()
    assert "stderr_error_counts:" in summary
    assert "hevc_ref_poc_missing=3" in summary
    assert "hevc_rps_error=1" in summary


def test_get_stderr_summary_equals_tail_when_no_known_errors_present():
    capture = _bare_capture()
    _feed_stderr_lines(capture, ["some ordinary informational line"])
    assert capture.get_stderr_summary() == capture.get_stderr_tail()
    assert "stderr_error_counts:" not in capture.get_stderr_summary()


# --- 4. Khong ro ri credential qua cac ham chan doan moi -------------------------

def test_stderr_summary_and_error_counts_never_leak_credentials():
    capture = _bare_capture()  # url = rtsp://user:pass@example.invalid/stream
    lines = [
        f"[tcp] Connection to {capture.url} failed: Could not find ref with POC 7",
        "Error opening input file rtsp://user:pass@example.invalid/stream.",
    ]
    _feed_stderr_lines(capture, lines)
    summary = capture.get_stderr_summary()
    tail = capture.get_stderr_tail()
    counts = capture.get_stderr_error_counts()
    for blob in (summary, tail, repr(counts)):
        assert "user:pass" not in blob
        assert "example.invalid" not in blob or "rtsp://<redacted>" in blob
    assert "rtsp://<redacted>" in tail


def test_stderr_error_counts_keys_are_fixed_labels_never_raw_stderr_text():
    """get_stderr_error_counts() CHI duoc chua ten nhom co dinh (khong doi, khong chua
    credential/URL du raw stderr line co chua chung)."""
    capture = _bare_capture()
    _feed_stderr_lines(capture, [f"Could not find ref with POC near {capture.url}"])
    counts = capture.get_stderr_error_counts()
    assert list(counts.keys()) == ["hevc_ref_poc_missing"]
