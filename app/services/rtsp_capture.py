from __future__ import annotations

import queue, shutil, subprocess, threading, time
from datetime import datetime,timezone
import cv2
import numpy as np


def frame_is_valid(frame) -> bool:
    """Loại frame rỗng/đồng màu thường xuất hiện khi HEVC chưa có keyframe."""
    return frame is not None and frame.size > 0 and float(frame.std()) >= 2.0


class RtspCapture:
    """Đọc RTSP qua FFmpeg/TCP và nhận MJPEG frame; ổn định hơn VideoCapture với HEVC."""
    def __init__(self,url: str,read_timeout=8.0,frame_callback=None,preview_fps=5.0):
        self.url=url; self.process=None; self.buffer=bytearray(); self.read_timeout=read_timeout; self.frames=queue.Queue(maxsize=1); self.reader=None; self.closed=False
        self.frame_callback=frame_callback; self.preview_interval=1/max(.1,float(preview_fps)); self.last_preview_at=0.0; self.dropped_capture_frames=0; self.last_capture_timestamp=None; self.last_capture_wall_time=None
    def open(self) -> bool:
        if not shutil.which("ffmpeg"): return False
        command=["ffmpeg","-hide_banner","-loglevel","error","-rtsp_transport","tcp","-i",self.url,"-an","-f","image2pipe","-vcodec","mjpeg","-q:v","5","pipe:1"]
        self.closed=False; self.process=subprocess.Popen(command,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,stdin=subprocess.DEVNULL,creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
        self.reader=threading.Thread(target=self._reader_loop,name="rtsp-ffmpeg-reader",daemon=True); self.reader.start()
        return True
    def is_opened(self): return self.process is not None and self.process.poll() is None
    def _publish(self,item):
        try: self.frames.get_nowait(); self.dropped_capture_frames+=1
        except queue.Empty: pass
        try: self.frames.put_nowait(item)
        except queue.Full: pass
    def _reader_loop(self):
        if not self.process or self.process.stdout is None: return
        while not self.closed and self.is_opened():
            chunk=self.process.stdout.read(65536)
            if not chunk: break
            self.buffer.extend(chunk); start=self.buffer.find(b"\xff\xd8"); end=self.buffer.find(b"\xff\xd9",start+2) if start>=0 else -1
            if start>=0 and end>=0:
                jpg=bytes(self.buffer[start:end+2]); del self.buffer[:end+2]
                frame=cv2.imdecode(np.frombuffer(jpg,np.uint8),cv2.IMREAD_COLOR)
                if frame_is_valid(frame):
                    capture_timestamp=time.monotonic(); capture_wall_time=datetime.now(timezone.utc); self._publish((frame,capture_timestamp,capture_wall_time))
                    now=time.monotonic()
                    if self.frame_callback and now-self.last_preview_at>=self.preview_interval:
                        self.last_preview_at=now
                        try: self.frame_callback(frame,capture_timestamp,capture_wall_time)
                        except Exception: pass
        self._publish(None)
    def read(self):
        if not self.is_opened(): return False,None
        try: item=self.frames.get(timeout=self.read_timeout)
        except queue.Empty: return False,None
        if item is None: return False,None
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
        self.reader=None


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
