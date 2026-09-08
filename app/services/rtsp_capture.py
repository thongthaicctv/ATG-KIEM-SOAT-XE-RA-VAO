from __future__ import annotations

import collections, queue, re, shutil, subprocess, threading, time
from datetime import datetime,timezone
import cv2
import numpy as np


def frame_is_valid(frame) -> bool:
    """Loại frame rỗng/đồng màu thường xuất hiện khi HEVC chưa có keyframe."""
    return frame is not None and frame.size > 0 and float(frame.std()) >= 2.0


# Phase 4.7B - HOTFIX RTSP CAPTURE STABILITY. Bo sung boi phan ung voi bao cao thuc
# te tren camera LAN that: VLC/ffmpeg CLI truc tiep xem lien tuc on dinh, nhung
# RtspCapture (dung mot minh, khong YOLO/tracker/DB/UI) bi RTSP_CAPTURE_FAIL sau
# ~71.66s du FFmpeg subprocess VAN CON SONG (process.poll() is None), queue rong,
# dropped_capture_frames=0 - tuc la reader thread don gian khong tao ra JPEG nao
# trong >8s, khong phai loi YOLO/DB/tracker/CUDA/UI.
#
# ROOT CAUSE #1 (CONFIRMED, thuc nghiem doc lap - xem bao cao Phase 4.7B):
# self.process.stdout la mot io.BufferedReader (subprocess.Popen mac dinh bufsize=-1).
# BufferedReader.read(n) CO THE goi lai raw read() nhieu lan de co gang lap DAY du n
# byte truoc khi tra ve - chi tra ve som hon neu gap EOF. Voi pipe (khong phai TTY),
# day la hanh vi duoc tai lieu hoa chinh thuc cua io module. MJPEG tung frame o q:v=5
# thuong nho hon 65536 byte/lan ghi, nen read(65536) GAN NHU LUON phai cho nhieu hon
# mot "burst" ghi cua FFmpeg moi tra ve - neu HEVC decode/network chi khua nhe (dung
# voi "invalid undecodable NALU"/"non monotonically increasing dts" quan sat duoc
# tren camera that), read(65536) co the block hang chuc giay dù byte DA san sang
# trong OS pipe buffer va JPEG hoan chinh dang cho trong self.buffer.
# Thuc nghiem tai hien (subprocess ghi 2000 byte/300ms, doc toi 4000 byte):
#   read(65536)  -> chunk dau tien sau 9.033s (cho den khi tien trinh ket thuc/EOF)
#   read1(65536) -> chunk dau tien sau 0.013s (tra ve ngay khi CO byte, <= 65536)
# => Fix: dung stdout.read1(n) (io.BufferedIOBase.read1 - toi da MOT lan goi raw
# read(), tra ve ngay khi co du lieu) thay vi stdout.read(n).
#
# ROOT CAUSE #2 (dong gop, khong tu no gay stall >8s nhung lam cham phuc hoi):
# Parser cu chi trich xuat TOI DA 1 JPEG moi lan doc stdout roi quay lai doc tiep,
# du buffer co the da chua san nhieu JPEG hoan chinh (vi du sau khi mot dot stall
# ket thuc, FFmpeg xa mot cum du lieu lon). Fix: rut can (drain) TOAN BO JPEG hoan
# chinh dang co san trong buffer truoc khi thuc hien mot lan doc stdout moi.
#
# Malformed HEVC NAL/non-monotonic DTS (camera-side, KHONG duoc thay doi hanh vi
# camera trong phase nay) la NGUYEN NHAN GOC upstream tao ra cac khoang gian doan
# ghi du lieu nho, binh thuong o muc FFmpeg/VLC co the dung nap; ROOT CAUSE #1/#2 la
# ly do ung dung KHONG dung nap duoc cung mot gian doan do. Ba flag FFmpeg them vao
# (-fflags +discardcorrupt+genpts, -err_detect ignore_err) giup decoder/demuxer ben
# bi hon voi chinh cac loi da quan sat duoc (NALU khong giai ma duoc, DTS khong tang
# don dieu) MA KHONG doi hanh vi camera - da kiem tra flag hop le voi FFmpeg cai dat
# (xem bao cao Phase 4.7B).
#
# PHASE 4.7B.1 - HEVC RTSP DECODER CONTINUITY HOTFIX. Field data thuc te (10 phut,
# camera LAN that, sau Phase 4.7B) cho thay kien truc soft/hard-stall HOAT DONG DUNG
# (khong con chet vinh vien o nguong 8s cu, moi lan deu hoi phuc), nhung hard_restarts=6
# trong 10 phut la qua nhieu cho he thong 24/7 (yeu cau <=1/10 phut). Stderr FFmpeg
# trong cac dot hard-stall cho thay loi HEVC decoder CO THE PHUC HOI duoc (khong phai
# mat ket noi TCP that): "Could not find ref with POC", "Error constructing the frame
# RPS", "Skipping invalid undecodable NALU" - decoder mat tham chieu (reference frame)
# tam thoi, se tu phuc hoi khi gap keyframe/IDR ke tiep. Test rieng bang FFmpeg CLI
# truc tiep cung tung thay "non monotonically increasing dts".
#
# Thay doi Phase 4.7B.1 (CHI RTSP/FFmpeg, KHONG doi YOLO/tracker/session/DB):
# 1) Them tuy chon -use_wallclock_as_timestamps 1 (mac dinh BAT, co the tat qua
#    use_wallclock_timestamps=False de tai hien argv Phase 4.7B goc phuc vu so sanh
#    BASELINE/CANDIDATE trong test matrix - xem scripts/rtsp_hevc_matrix_phase_4_7b_1.py).
#    Day la INPUT option (dat truoc -i): gan pts/dts theo dong ho he thong luc frame
#    den thay vi dua vao pts/dts tu chinh luong HEVC - triet tieu tan goc canh bao
#    "non monotonically increasing dts" thay vi chi vá bang genpts (van giu +genpts
#    de an toan nguoc, tro thanh gan nhu vo hai/du thua khi wallclock da bat).
#    Rui ro: KHONG dang ke cho pipeline nay - chung ta khong dong bo A/V (co -an),
#    khong mux vao container can pts chinh xac, chi rut JPEG tuan tu qua image2pipe;
#    do tre them (neu co) la khong dang ke so voi cac buoc doc/giai ma khac.
# 2) KHONG doi DEFAULT_HARD_RESTART_SECONDS (van 18.0s, bounded, da field-validate
#    o Phase 4.7B) - thay vao do THEM do luong longest_frame_gap (khoang cach lon
#    nhat giua 2 frame hop le lien tiep trong CUNG mot phien open()) de LAY SO LIEU
#    THAT truoc khi quyet dinh chinh nguong (yeu cau: "base it on observed timings",
#    khong doan mo). Muc M/14 script chan doan da duoc cap nhat de in gia tri nay.
# 3) Phan loai/rate-limit stderr theo nhom loi HEVC da biet (POC ref/RPS/NALU/DTS)
#    de tranh stderr tail bi tran boi hang tram dong lap lai giong het nhau, van
#    giu duoc bang tom tat so lan xuat hien tung loai (get_stderr_error_counts()).
DEFAULT_SOFT_STALL_SECONDS = 8.0
DEFAULT_HARD_RESTART_SECONDS = 18.0
_READ_POLL_INTERVAL_SECONDS = 0.5
_MAX_JPEG_BUFFER_BYTES = 3_000_000
_STDERR_TAIL_LINES = 40
_STDERR_MAX_LINE_LENGTH = 500
_STDOUT_CHUNK_SIZE = 65536

_CREDENTIAL_RE = re.compile(r"rtsp://[^\s@/]+@")

# Phase 4.7B.1 - nhom loi HEVC decoder DA BIET LA CO THE PHUC HOI (khong phai mat
# ket noi TCP) - dung de dem/rate-limit stderr thay vi luu lap lai tung dong giong
# het nhau (xem _stderr_reader_loop). Danh sach CO CHU DICH gon - chi cac mau thuc
# te da quan sat duoc tren camera that (xem bao cao Phase 4.7B.1 muc 2), KHONG co
# tham vong bat het moi loai loi FFmpeg co the co.
_STDERR_KNOWN_ERROR_PATTERNS = (
    ("hevc_ref_poc_missing", re.compile(r"Could not find ref with POC")),
    ("hevc_rps_error", re.compile(r"Error constructing the frame RPS")),
    ("hevc_invalid_nalu", re.compile(r"Skipping invalid undecodable NALU")),
    ("dts_non_monotonic", re.compile(r"non monotonically increasing dts")),
)


def _sanitize_diagnostic_text(text: str, url: str | None) -> str:
    """Loai bo credential/URL RTSP khoi text chan doan (stderr FFmpeg, exception...).
    KHONG duoc de lot username/password/URL vao log/report/exception (yeu cau Phase 4.7B)."""
    if not text: return text
    sanitized = text
    if url: sanitized = sanitized.replace(url, "rtsp://<redacted>")
    sanitized = _CREDENTIAL_RE.sub("rtsp://<redacted>@", sanitized)
    return sanitized


class RtspCapture:
    """Đọc RTSP qua FFmpeg/TCP và nhận MJPEG frame; ổn định hơn VideoCapture với HEVC.

    Phase 4.7B: phan biet SOFT FRAME STALL (FFmpeg con song, tam thoi chua co frame
    moi - khong lam gi ca, tiep tuc cho) voi HARD CAPTURE FAILURE (FFmpeg da chet,
    hoac khong co frame nao trong hard_restart_timeout giay) - chi truong hop sau
    moi khien read() tra ve False (CameraWorker coi day la ConnectionError -> OFFLINE
    -> reconnect, hanh vi cong khai nay GIU NGUYEN, khong doi CameraWorker)."""
    def __init__(self,url: str,read_timeout=DEFAULT_SOFT_STALL_SECONDS,frame_callback=None,preview_fps=5.0,hard_restart_timeout=DEFAULT_HARD_RESTART_SECONDS,use_wallclock_timestamps=True):
        self.url=url; self.process=None; self.buffer=bytearray(); self.read_timeout=read_timeout; self.hard_restart_timeout=max(read_timeout,hard_restart_timeout); self.frames=queue.Queue(maxsize=1); self.reader=None; self.stderr_reader=None; self.closed=False
        self.frame_callback=frame_callback; self.preview_interval=1/max(.1,float(preview_fps)); self.last_preview_at=0.0; self.dropped_capture_frames=0; self.last_capture_timestamp=None; self.last_capture_wall_time=None
        # Phase 4.7B - capture-health tracking (muc D yeu cau toi thieu).
        self.last_valid_frame_monotonic=None; self.last_stdout_activity_monotonic=None
        self.consecutive_soft_stalls=0; self.hard_restarts=0
        self._stderr_tail=collections.deque(maxlen=_STDERR_TAIL_LINES)
        # Phase 4.7B.1 - HEVC continuity: co the tat use_wallclock_timestamps de tai
        # hien argv Phase 4.7B goc (dung cho test matrix BASELINE, xem muc dau file).
        self.use_wallclock_timestamps=bool(use_wallclock_timestamps)
        # longest_frame_gap: khoang cach LON NHAT (giay) giua 2 frame hop le lien tiep
        # trong CUNG mot phien open() nay - do luong thuc te de co co so chinh nguong
        # hard_restart_timeout trong tuong lai (KHONG doan mo - xem doc dau file).
        self.longest_frame_gap=None
        # Dem loi HEVC decoder theo nhom (xem _STDERR_KNOWN_ERROR_PATTERNS) de rate-
        # limit stderr tail ma khong mat thong tin chan doan tong hop.
        self._stderr_error_counts={}
        self._stderr_seen_classes=set()
    def open(self) -> bool:
        if not shutil.which("ffmpeg"): return False
        command=["ffmpeg","-hide_banner","-loglevel","warning",
            # Phase 4.7B: cac flag nay giup FFmpeg ben bi hon voi HEVC NALU khong giai
            # ma duoc / DTS khong tang don dieu da quan sat tren camera that (xem audit
            # muc C.3) - KHONG doi hanh vi camera, chi anh huong cach FFmpeg dung nap loi.
            "-fflags","+discardcorrupt+genpts","-err_detect","ignore_err"]
        if self.use_wallclock_timestamps:
            # Phase 4.7B.1: gan pts/dts theo dong ho he thong luc frame den thay vi
            # tin vao pts/dts cua chinh luong HEVC - triet tieu tan goc canh bao "non
            # monotonically increasing dts" (xem doc dau file). INPUT option - PHAI
            # dat truoc -i. Co the tat (use_wallclock_timestamps=False) de tai hien
            # argv Phase 4.7B goc phuc vu so sanh BASELINE trong test matrix.
            command += ["-use_wallclock_as_timestamps","1"]
        command += ["-rtsp_transport","tcp","-i",self.url,"-an","-f","image2pipe","-vcodec","mjpeg","-q:v","5","pipe:1"]
        self.closed=False; self.process=subprocess.Popen(command,stdout=subprocess.PIPE,stderr=subprocess.PIPE,stdin=subprocess.DEVNULL,creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
        self.reader=threading.Thread(target=self._reader_loop,name="rtsp-ffmpeg-reader",daemon=True); self.reader.start()
        # Phase 4.7B: doc stderr trong luong RIENG - bat buoc, vi neu chi doc stdout,
        # stderr co the day OS pipe buffer va lam FFmpeg treo (classic 2-pipe deadlock).
        self.stderr_reader=threading.Thread(target=self._stderr_reader_loop,name="rtsp-ffmpeg-stderr",daemon=True); self.stderr_reader.start()
        return True
    def is_opened(self): return self.process is not None and self.process.poll() is None
    def _publish(self,item):
        try: self.frames.get_nowait(); self.dropped_capture_frames+=1
        except queue.Empty: pass
        try: self.frames.put_nowait(item)
        except queue.Full: pass
    def _drain_buffer(self):
        """Phase 4.7B: rut can TOAN BO JPEG hoan chinh dang co san trong self.buffer
        (khong chi 1 cai) truoc khi quay lai doc stdout - tranh lang phi mot lan doc
        stdout (co the block) trong khi frame moi hon da san sang cho xu ly."""
        while True:
            start=self.buffer.find(b"\xff\xd8")
            if start<0:
                # Khong co SOI nao trong buffer: bo rac nhung giu lai 1 byte cuoi phong
                # truong hop 0xFF bi cat doi giua 2 lan doc (SOI = FFD8 nam vat qua ranh
                # gioi chunk).
                if len(self.buffer)>1: del self.buffer[:-1]
                return
            if start>0: del self.buffer[:start]  # bo rac truoc SOI - buffer GIO bat dau tai SOI (index 0)
            end=self.buffer.find(b"\xff\xd9",2)
            if end<0:
                # JPEG chua hoan chinh - gioi han buffer de tranh phinh to vo han neu
                # stream loi khong bao gio co EOI hop le cho frame nay.
                if len(self.buffer)>_MAX_JPEG_BUFFER_BYTES:
                    del self.buffer[:2]  # bo qua SOI hong nay, tim SOI ke tiep o vong sau
                    continue
                return
            # QUAN TRONG: dung self.buffer[:end+2] (KHONG phai [start:end+2]) - "start"
            # da LAC HAU sau lenh del self.buffer[:start] o tren (buffer da dich chuyen,
            # SOI gio o index 0). Dung lai "start" o day se cat sai vi tri, tao JPEG
            # hong (da tim thay va sua qua test_garbage_prefix_before_real_jpeg_is_discarded).
            jpg=bytes(self.buffer[:end+2]); del self.buffer[:end+2]
            frame=cv2.imdecode(np.frombuffer(jpg,np.uint8),cv2.IMREAD_COLOR)
            if frame_is_valid(frame):
                now=time.monotonic()
                # Phase 4.7B.1: do khoang cach thuc te toi frame hop le TRUOC do (neu co)
                # truoc khi ghi de last_valid_frame_monotonic - day la "longest recoverable
                # frame gap" thuc do duoc, khong doan mo (yeu cau muc 7 cua bao cao).
                if self.last_valid_frame_monotonic is not None:
                    gap=now-self.last_valid_frame_monotonic
                    self.longest_frame_gap=gap if self.longest_frame_gap is None else max(self.longest_frame_gap,gap)
                self.last_valid_frame_monotonic=now
                capture_wall_time=datetime.now(timezone.utc); self._publish((frame,now,capture_wall_time))
                if self.frame_callback and now-self.last_preview_at>=self.preview_interval:
                    self.last_preview_at=now
                    try: self.frame_callback(frame,now,capture_wall_time)
                    except Exception: pass
            # Tiep tuc vong lap: co the con JPEG khac da san sang trong buffer.
    def _reader_loop(self):
        if not self.process or self.process.stdout is None: return
        stdout=self.process.stdout
        while not self.closed and self.is_opened():
            try:
                # Phase 4.7B: read1() (toi da MOT lan goi raw read cua he dieu hanh) thay
                # vi read() (co the goi lai nhieu lan de co lap day du _STDOUT_CHUNK_SIZE
                # byte) - xem giai thich CONFIRMED root cause #1 o dau file.
                chunk=stdout.read1(_STDOUT_CHUNK_SIZE)
            except (ValueError,OSError):
                break
            if not chunk: break
            self.last_stdout_activity_monotonic=time.monotonic()
            self.buffer.extend(chunk)
            self._drain_buffer()
        self._publish(None)
    def _stderr_reader_loop(self):
        """Phase 4.7B: doc stderr FFmpeg khong chan (bounded, khong deadlock stdout),
        chi giu lai vai dong gan nhat de chan doan - KHONG BAO GIO ghi credential/URL.

        Phase 4.7B.1: cac dong khop mot nhom loi HEVC DA BIET (POC ref/RPS/NALU/DTS -
        xem _STDERR_KNOWN_ERROR_PATTERNS) duoc DEM theo nhom thay vi luu lap lai tung
        dong giong het nhau vao tail (tranh stderr tail bi tran boi hang tram dong lap
        - yeu cau muc 9). Lan XUAT HIEN DAU TIEN cua moi nhom van duoc giu lai trong tail
        de co vi du cu the phuc vu chan doan - "khong duoc lam mat di tail chan doan
        cuoi cung huu ich". Dong KHONG khop nhom nao van luu vao tail nhu cu (khong loc
        bo thong tin moi/bat ngo)."""
        process=self.process
        if not process or process.stderr is None: return
        stream=process.stderr
        try:
            for raw_line in iter(stream.readline,b""):
                if self.closed: break
                try: text=raw_line.decode("utf-8","replace").rstrip("\r\n")
                except Exception: continue
                if not text: continue
                sanitized=_sanitize_diagnostic_text(text,self.url)[:_STDERR_MAX_LINE_LENGTH]
                matched_label=None
                for label,pattern in _STDERR_KNOWN_ERROR_PATTERNS:
                    if pattern.search(sanitized): matched_label=label; break
                if matched_label is not None:
                    self._stderr_error_counts[matched_label]=self._stderr_error_counts.get(matched_label,0)+1
                    if matched_label not in self._stderr_seen_classes:
                        self._stderr_seen_classes.add(matched_label)
                        self._stderr_tail.append(sanitized)
                else:
                    self._stderr_tail.append(sanitized)
        except (ValueError,OSError):
            pass
    def get_stderr_tail(self) -> str:
        """Tra ve vai dong stderr FFmpeg gan nhat (da loai credential) de chan doan khi
        capture that bai - san sang cho production log tai thoi diem reconnect."""
        return "\n".join(self._stderr_tail)
    def get_stderr_error_counts(self) -> dict:
        """Phase 4.7B.1: tra ve BAN SAO dict {nhom_loi_HEVC: so_lan_xuat_hien} tich luy
        tu luc open() - dung cho log/report/test matrix, KHONG bao gio chua credential
        (chi chua ten nhom loi co dinh, khong chua noi dung dong stderr goc)."""
        return dict(self._stderr_error_counts)
    def get_stderr_summary(self) -> str:
        """Phase 4.7B.1: ghep tail chan doan (get_stderr_tail) voi mot dong tom tat so
        lan xuat hien tung nhom loi HEVC da biet - dung cho log CameraWorker/script chan
        doan de van thay duoc quy mo that su cua van de dai da bi rate-limit khoi tail."""
        tail=self.get_stderr_tail()
        counts=self.get_stderr_error_counts()
        if not counts: return tail
        counts_line="stderr_error_counts: "+", ".join(f"{label}={count}" for label,count in sorted(counts.items()))
        return f"{tail}\n{counts_line}" if tail else counts_line
    @property
    def last_frame_age(self):
        if self.last_valid_frame_monotonic is None: return None
        return time.monotonic()-self.last_valid_frame_monotonic
    def read(self):
        """Phase 4.7B: phan biet SOFT STALL (tiep tuc cho, KHONG that bai) va HARD
        FAILURE (tra ve False - CameraWorker se coi la ConnectionError). Vong lap
        polling voi khoang cho nho (_READ_POLL_INTERVAL_SECONDS) thay vi mot lan cho
        chan cung read_timeout - cho phep phat hien tien trinh chet SOM (khong phai
        cho het hard_restart_timeout) trong khi van cho hoi phuc neu tien trinh con
        song va chi tam thoi chua co frame."""
        if not self.is_opened(): return False,None
        started=time.monotonic(); soft_deadline=started+self.read_timeout; hard_deadline=started+self.hard_restart_timeout; soft_flagged=False
        while True:
            if not self.is_opened():
                # HARD FAILURE tuc thi: tien trinh FFmpeg da chet, khong can cho them.
                return False,None
            now=time.monotonic()
            remaining_to_hard=hard_deadline-now
            if remaining_to_hard<=0:
                self.hard_restarts+=1
                return False,None
            wait=min(_READ_POLL_INTERVAL_SECONDS,remaining_to_hard)
            try:
                item=self.frames.get(timeout=wait)
            except queue.Empty:
                if not soft_flagged and time.monotonic()>=soft_deadline:
                    soft_flagged=True; self.consecutive_soft_stalls+=1
                continue
            if item is None:
                # Reader thread ket thuc (EOF/tien trinh thoat) - HARD FAILURE.
                return False,None
            frame,self.last_capture_timestamp,self.last_capture_wall_time=item
            return True,frame

    def set_preview_fps(self,preview_fps):
        value=float(preview_fps)
        if not 1 <= value <= 15: raise ValueError("preview_fps phải nằm trong khoảng 1–15 FPS")
        self.preview_interval=1/value

    @property
    def queue_size(self): return self.frames.qsize()
    def release(self):
        self.closed=True; process=self.process; self.process=None
        if process:
            try: process.terminate(); process.wait(timeout=2)
            except Exception:
                try: process.kill()
                except Exception: pass
        if self.reader and self.reader is not threading.current_thread(): self.reader.join(timeout=2)
        if self.stderr_reader and self.stderr_reader is not threading.current_thread(): self.stderr_reader.join(timeout=2)
        self.reader=None; self.stderr_reader=None


def grab_rtsp_frame(url: str,timeout_seconds=15):
    """Lấy một frame hợp lệ bằng FFmpeg; không dùng shell để bảo vệ credential."""
    if shutil.which("ffmpeg"):
        command=["ffmpeg","-hide_banner","-loglevel","error","-rtsp_transport","tcp","-i",url,"-frames:v","1","-f","image2pipe","-vcodec","mjpeg","pipe:1"]
        try:
            result=subprocess.run(command,capture_output=True,timeout=timeout_seconds,creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
            frame=cv2.imdecode(np.frombuffer(result.stdout,np.uint8),cv2.IMREAD_COLOR) if result.stdout else None
            if frame_is_valid(frame): return frame
        except Exception: pass
    cap=cv2.VideoCapture(url,cv2.CAP_FFMPEG); ok,frame=cap.read(); cap.release()
    return frame if ok and frame_is_valid(frame) else None
