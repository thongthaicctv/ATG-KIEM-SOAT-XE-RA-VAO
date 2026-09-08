"""tests/test_phase_4_7b_rtsp_stability.py

Phase 4.7B - HOTFIX RTSP CAPTURE STABILITY.

Tai hien va kiem chung cac fix cho loi RTSP_CAPTURE_FAIL quan sat duoc tren camera
LAN that: FFmpeg subprocess VAN CON SONG (process.poll() is None), queue rong,
dropped_capture_frames=0, nhung RtspCapture khong tao ra frame nao trong >8s.

CONFIRMED root cause #1 (xem app/services/rtsp_capture.py, doc comment dau file va
bao cao Phase 4.7B): stdout.read(65536) (io.BufferedReader) co the block cho toi khi
du 65536 byte hoac EOF, ke ca khi it byte da san sang trong OS pipe buffer. Thuc
nghiem doc lap (khong dung file nay) da xac nhan: read(65536) tre 9.033s trong khi
read1(65536) tra ve sau 0.013s voi cung mot subprocess ghi cham. File test nay tap
trung vao cac hanh vi CO THE kiem chung nhanh, xac dinh (deterministic) trong
sandbox khong co GPU/RTSP that - khong spawn FFmpeg that, dung fake process/
subprocess Python don gian de mo phong cac dieu kien bien.

KHONG dong cham parking session/tracker/polygon/timer/DB - test nay CHI danh cho
app/services/rtsp_capture.py va phan reconnect-backoff lien quan trong
app/services/camera_worker.py.
"""
from __future__ import annotations

import subprocess
import sys
import threading
import time

import cv2
import numpy as np

from app.services.rtsp_capture import (
    RtspCapture,
    _MAX_JPEG_BUFFER_BYTES,
    _STDERR_TAIL_LINES,
    _sanitize_diagnostic_text,
)


def _make_jpeg_bytes(seed: int = 0) -> bytes:
    """JPEG that (dung cv2.imencode) voi noise ngau nhien de frame_is_valid() (yeu cau
    std>=2.0) luon dung - tranh phai mock cv2.imdecode."""
    rng = np.random.default_rng(seed)
    image = rng.integers(0, 255, size=(24, 24, 3), dtype=np.uint8)
    ok, encoded = cv2.imencode(".jpg", image)
    assert ok
    return encoded.tobytes()


class _FakeProcess:
    """Mo phong subprocess.Popen toi thieu can cho RtspCapture.is_opened()/release():
    poll() tra ve None khi con 'song', mot ma thoat khi 'chet'."""
    def __init__(self, alive=True):
        self._alive = alive
        self.terminated = False
        self.killed = False
    def poll(self):
        return None if self._alive else 0
    def die(self):
        self._alive = False
    def terminate(self):
        self.terminated = True; self._alive = False
    def wait(self, timeout=None):
        return 0
    def kill(self):
        self.killed = True; self._alive = False


def _bare_capture(**kwargs) -> RtspCapture:
    """RtspCapture chi qua __init__ (KHONG goi open()) - khong spawn FFmpeg/thread nao,
    an toan de gan self.process = _FakeProcess() va kiem tra logic thuan Python."""
    return RtspCapture("rtsp://user:pass@example.invalid/stream", **kwargs)


# --- 1. Partial JPEG across multiple stdout chunks -----------------------------

def test_partial_jpeg_across_multiple_chunks_is_not_published_until_complete():
    capture = _bare_capture()
    jpeg = _make_jpeg_bytes(1)
    half = len(jpeg) // 2
    capture.buffer.extend(jpeg[:half])
    capture._drain_buffer()
    assert capture.queue_size == 0, "JPEG chưa đầy đủ không được publish"
    assert capture.last_valid_frame_monotonic is None
    capture.buffer.extend(jpeg[half:])
    capture._drain_buffer()
    assert capture.queue_size == 1
    assert capture.last_valid_frame_monotonic is not None


# --- 2. Multiple JPEG frames inside one available buffer are drained -----------

def test_multiple_jpegs_in_one_chunk_are_all_drained_not_just_first():
    capture = _bare_capture()
    jpeg_a = _make_jpeg_bytes(2)
    jpeg_b = _make_jpeg_bytes(3)
    capture.buffer.extend(jpeg_a + jpeg_b)
    capture._drain_buffer()
    # Queue maxsize=1 nên chỉ còn frame MỚI NHẤT, nhưng dropped_capture_frames phải
    # tăng đúng 1 lần (chứng minh JPEG đầu tiên ĐÃ được xử lý/publish rồi mới bị JPEG
    # thứ hai ghi đè, thay vì bị bỏ qua hoàn toàn vì chỉ đọc 1 JPEG/lần).
    assert capture.queue_size == 1
    assert capture.dropped_capture_frames == 1
    assert len(capture.buffer) == 0, "Cả hai JPEG phải được tiêu thụ khỏi buffer"


# --- 3. Garbage prefix before JPEG does not grow buffer forever ----------------

def test_garbage_without_any_soi_does_not_grow_buffer_unboundedly():
    capture = _bare_capture()
    for _ in range(200):
        capture.buffer.extend(b"\x00\x01garbage-no-marker-here")
        capture._drain_buffer()
    # Không có FFD8 nào -> buffer luôn được cắt về tối đa 1 byte (phòng FFD8 bị cắt
    # đôi giữa 2 lần đọc), tuyệt đối không phình to theo số vòng lặp.
    assert len(capture.buffer) <= 1


def test_garbage_prefix_before_real_jpeg_is_discarded():
    capture = _bare_capture()
    jpeg = _make_jpeg_bytes(4)
    capture.buffer.extend(b"garbage-before-soi-marker" + jpeg)
    capture._drain_buffer()
    assert capture.queue_size == 1
    assert len(capture.buffer) == 0


# --- 4. Bounded buffer for a never-terminated (corrupt) JPEG -------------------

def test_incomplete_jpeg_exceeding_max_buffer_is_dropped_not_grown_forever():
    capture = _bare_capture()
    # SOI hợp lệ nhưng KHÔNG BAO GIỜ có FFD9 - mô phỏng frame hỏng/không bao giờ kết
    # thúc (ví dụ do NALU không giải mã được giữa chừng).
    capture.buffer.extend(b"\xff\xd8" + b"\x00" * (_MAX_JPEG_BUFFER_BYTES + 1000))
    capture._drain_buffer()
    assert len(capture.buffer) < _MAX_JPEG_BUFFER_BYTES, (
        "Buffer phải được cắt bớt khi vượt _MAX_JPEG_BUFFER_BYTES, khong được phình vô hạn"
    )


# --- 5. Soft stall: process alive + temporary no-frame does NOT hard-fail ------

def test_soft_stall_does_not_hard_fail_when_process_alive_and_frame_arrives_late():
    # read_timeout rat nho (0.05s) va do tre publish (0.65s) co chu y lon hon HAN 1 lan
    # poll interval (_READ_POLL_INTERVAL_SECONDS=0.5s) de tranh race o ranh gioi (nghia
    # la chac chan CO IT NHAT mot vong poll timeout truoc khi frame den, khong phu thuoc
    # vao do tre lich trinh luong).
    capture = _bare_capture(read_timeout=0.05, hard_restart_timeout=3.0)
    capture.process = _FakeProcess(alive=True)
    jpeg_frame = np.zeros((4, 4, 3), dtype=np.uint8) + 7

    def _late_publish():
        time.sleep(0.65)
        capture._publish((jpeg_frame, time.monotonic(), None))

    threading.Thread(target=_late_publish, daemon=True).start()
    ok, frame = capture.read()
    assert ok is True
    assert frame is jpeg_frame
    assert capture.consecutive_soft_stalls >= 1, "Phải ghi nhận đã đi qua ngư`ỡng soft stall"
    assert capture.hard_restarts == 0, "KHÔNG được tính là hard restart"


# --- 6. Hard prolonged stall DOES eventually trigger recovery/restart ----------

def test_hard_prolonged_stall_eventually_returns_hard_failure():
    capture = _bare_capture(read_timeout=0.1, hard_restart_timeout=0.4)
    capture.process = _FakeProcess(alive=True)  # tiến trình vẫn "sống" suốt
    started = time.monotonic()
    ok, frame = capture.read()  # không bao giờ publish gì cả
    elapsed = time.monotonic() - started
    assert ok is False and frame is None
    assert capture.hard_restarts == 1
    assert capture.consecutive_soft_stalls >= 1
    # Không phải vô hạn: phải kết thúc quanh hard_restart_timeout, không phải chờ mãi.
    assert elapsed < 1.0


# --- 7. Process exit is a hard failure (and reacts fast, not waiting full hard) -

def test_process_exit_is_hard_failure_and_reacts_quickly():
    capture = _bare_capture(read_timeout=0.2, hard_restart_timeout=5.0)
    fake = _FakeProcess(alive=True)
    capture.process = fake

    def _die_soon():
        time.sleep(0.15)
        fake.die()

    threading.Thread(target=_die_soon, daemon=True).start()
    started = time.monotonic()
    ok, frame = capture.read()
    elapsed = time.monotonic() - started
    assert ok is False and frame is None
    # Phải phản ứng gần với thời điểm tiến trình chết (~0.15s), KHÔNG chờ hết
    # hard_restart_timeout=5.0s - is_opened() được kiểm tra mỗi vòng poll.
    assert elapsed < 1.0


# --- 8. stderr tail is bounded --------------------------------------------------

def test_stderr_tail_is_bounded_to_configured_line_count():
    capture = _bare_capture()
    lines = [f"warning line {i}\n".encode("utf-8") for i in range(_STDERR_TAIL_LINES + 25)]

    class _FakeStderr:
        def __init__(self, chunks):
            self._chunks = iter(chunks)
        def readline(self):
            return next(self._chunks, b"")

    fake_process = _FakeProcess(alive=True)
    fake_process.stderr = _FakeStderr(lines)
    capture.process = fake_process
    capture._stderr_reader_loop()
    assert len(capture._stderr_tail) <= _STDERR_TAIL_LINES
    tail = capture.get_stderr_tail()
    assert "warning line" in tail
    # Phải giữ lại các dòng GẦN NHẤT, khong phải các dòng đầu tiên.
    assert f"warning line {_STDERR_TAIL_LINES + 24}" in tail


# --- 9. stderr collector cannot deadlock stdout processing ---------------------

def test_stderr_and_stdout_readers_do_not_deadlock_on_large_concurrent_output():
    """Tích hợp thật (subprocess Python, khong phải FFmpeg): ghi > 200KB ra CẢ HAI
    stdout và stderr - nếu chỉ đọc 1 trong 2 pipe, tiến trình con sẽ bị treo vì OS
    pipe buffer đầy (deadlock kinh điển). RtspCapture phải đọc SONG SONG cả hai."""
    script = (
        "import sys\n"
        "chunk = b'A' * 4096\n"
        "for _ in range(60):\n"
        "    sys.stdout.buffer.write(chunk); sys.stdout.buffer.flush()\n"
        "    sys.stderr.buffer.write(chunk); sys.stderr.buffer.flush()\n"
    )
    process = subprocess.Popen(
        [sys.executable, "-c", script], stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    capture = _bare_capture()
    capture.process = process
    reader = threading.Thread(target=capture._reader_loop, daemon=True)
    stderr_reader = threading.Thread(target=capture._stderr_reader_loop, daemon=True)
    reader.start(); stderr_reader.start()
    process.wait(timeout=10)  # nếu deadlock, sẽ timeout ở đây
    reader.join(timeout=5)
    stderr_reader.join(timeout=5)
    assert not reader.is_alive()
    assert not stderr_reader.is_alive()


# --- 10. Credentials are never present in diagnostic output --------------------

def test_credentials_never_appear_in_sanitized_diagnostic_text():
    url = "rtsp://admin:S3cretPass@192.168.1.50:554/cam/realmonitor"
    raw = f"Connection to {url} failed: [tcp @ 0x1234] error -110"
    sanitized = _sanitize_diagnostic_text(raw, url)
    assert "S3cretPass" not in sanitized
    assert "admin" not in sanitized
    assert "192.168.1.50" not in sanitized
    assert "rtsp://<redacted>" in sanitized


def test_stderr_reader_loop_sanitizes_credentials_from_ffmpeg_lines():
    url = "rtsp://admin:S3cretPass@192.168.1.50:554/cam/realmonitor"
    capture = RtspCapture(url)
    line = f"[tcp @ 0x1] Failed to connect to {url}\n".encode("utf-8")

    class _FakeStderr:
        def __init__(self, first_line):
            self._lines = [first_line, b""]
            self._i = 0
        def readline(self):
            item = self._lines[self._i]; self._i += 1; return item

    fake_process = _FakeProcess(alive=True)
    fake_process.stderr = _FakeStderr(line)
    capture.process = fake_process
    capture._stderr_reader_loop()
    tail = capture.get_stderr_tail()
    assert "S3cretPass" not in tail
    assert "admin" not in tail


# --- 11. release() safely terminates reader/stderr threads ---------------------

def test_release_terminates_reader_and_stderr_threads_without_hanging():
    script = (
        "import sys, time\n"
        "while True:\n"
        "    sys.stdout.buffer.write(b'x'); sys.stdout.buffer.flush()\n"
        "    time.sleep(0.05)\n"
    )
    process = subprocess.Popen(
        [sys.executable, "-c", script], stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    capture = _bare_capture()
    capture.process = process
    capture.reader = threading.Thread(target=capture._reader_loop, daemon=True)
    capture.stderr_reader = threading.Thread(target=capture._stderr_reader_loop, daemon=True)
    capture.reader.start(); capture.stderr_reader.start()
    time.sleep(0.2)
    started = time.monotonic()
    capture.release()
    elapsed = time.monotonic() - started
    assert elapsed < 5.0, "release() không được treo"
    assert capture.reader is None and capture.stderr_reader is None
    assert process.poll() is not None, "Tiến trình FFmpeg (mô phỏng) phải được chấm dứt"


# --- 12. Queue remains bounded (maxsize=1) -------------------------------------

def test_capture_queue_stays_bounded_after_many_publishes():
    capture = _bare_capture()
    for index in range(50):
        capture._publish((index, float(index), None))
    assert capture.frames.maxsize == 1
    assert capture.queue_size == 1
    assert capture.dropped_capture_frames == 49


# --- Bonus: exact ffmpeg command reflects the new resilience flags -------------

def test_open_invokes_ffmpeg_with_expected_resilience_flags_and_piped_stderr(monkeypatch):
    captured = {}

    class _Recorder:
        def __init__(self, command, **kwargs):
            captured["command"] = command
            captured["kwargs"] = kwargs
            self.stdout = None
            self.stderr = None
        def poll(self):
            return None

    monkeypatch.setattr("app.services.rtsp_capture.shutil.which", lambda name: "/usr/bin/ffmpeg")
    monkeypatch.setattr("app.services.rtsp_capture.subprocess.Popen", _Recorder)
    capture = _bare_capture()
    assert capture.open() is True
    command = captured["command"]
    assert "-fflags" in command
    assert "+discardcorrupt+genpts" in command
    assert "-err_detect" in command
    assert "ignore_err" in command
    assert "-rtsp_transport" in command and "tcp" in command
    assert captured["kwargs"]["stderr"] == subprocess.PIPE, "stderr KHÔNG được là DEVNULL nữa"
    capture.reader.join(timeout=2)
    capture.stderr_reader.join(timeout=2)


# --- Bonus: end-to-end reproduction that trickling data is not blocked ---------

def test_reader_loop_publishes_frame_from_slowly_trickling_real_subprocess():
    """Tái hiện gần đúng bản chất lỗi thật: một subprocess ghi JPEG THẬT theo từng
    mẩu nhỏ, chậm (mô phỏng FFmpeg output khi HEVC decode/network chỉ khẽ khựng lại).
    Với read1() (bản vá), frame phải được publish trong vòng ~1s dù dữ liệu đến rải
    rác - đây chính là hành vi mà read(65536) KHÔNG đảm bảo được (xem thực nghiệm độc
    lập trong báo cáo Phase 4.7B: read() trễ 9.033s voi cùng kiểu dữ liệu)."""
    jpeg = _make_jpeg_bytes(9)
    chunk_size = max(1, len(jpeg) // 8)
    pieces = [jpeg[i : i + chunk_size] for i in range(0, len(jpeg), chunk_size)]
    script_lines = ["import sys, time", "pieces = ["]
    for piece in pieces:
        script_lines.append(f"    {piece!r},")
    script_lines.append("]")
    script_lines.append("for p in pieces:")
    script_lines.append("    sys.stdout.buffer.write(p); sys.stdout.buffer.flush(); time.sleep(0.05)")
    script = "\n".join(script_lines)
    process = subprocess.Popen(
        [sys.executable, "-c", script], stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    capture = _bare_capture()
    capture.process = process
    reader = threading.Thread(target=capture._reader_loop, daemon=True)
    reader.start()
    started = time.monotonic()
    ok, frame = capture.read()
    elapsed = time.monotonic() - started
    reader.join(timeout=2)
    assert ok is True
    assert frame is not None
    assert elapsed < 2.0, "Frame trải rài rác vẫn phải được publish nhanh, khong bị 'giữ' đến khi đủ 65536 byte"
