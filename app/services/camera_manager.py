import time
from PySide6.QtCore import QObject, QThread, QTimer, Signal

from .camera_worker import CameraWorker
from .tracker import CentroidTracker


def preview_interval_ms(preview_fps):
    value=float(preview_fps)
    if not 1 <= value <= 15: raise ValueError("preview_fps phải nằm trong khoảng 1–15 FPS")
    return round(1000/value)


class CameraManager(QObject):
    frame_ready=Signal(int,object,object); preview_frame=Signal(int,object,object); status_changed=Signal(int,bool,str); detector_error=Signal(int,str); error=Signal(int,str)
    def __init__(self,detector,parent=None,max_cameras=10,preview_fps=5.0):
        super().__init__(parent); self.detector=detector; self.max_cameras=max(1,int(max_cameras)); self.items={}; self.preview_sequences={}; self.preview_timers={}; self.last_preview_emit={}
    def start_camera(self,camera):
        self.stop_camera(camera.id)
        if len(self.items)>=self.max_cameras:
            self.error.emit(camera.id,f"Profile chỉ cho phép tối đa {self.max_cameras} camera đang chạy")
            return False
        thread=QThread(self); worker=CameraWorker(camera,self.detector,CentroidTracker); worker.moveToThread(thread)
        thread.started.connect(worker.run); worker.frame_ready.connect(self.frame_ready); worker.status_changed.connect(self.status_changed); worker.detector_error.connect(self.detector_error); worker.error.connect(self.error)
        worker.stopped.connect(thread.quit); thread.finished.connect(worker.deleteLater); thread.finished.connect(thread.deleteLater)
        self.items[camera.id]=(thread,worker)
        timer=QTimer(self); timer.setInterval(preview_interval_ms(camera.preview_fps)); timer.timeout.connect(lambda cid=camera.id:self._flush_preview(cid)); self.preview_timers[camera.id]=timer; timer.start()
        thread.start(); return True
    def stop_camera(self,camera_id):
        timer=self.preview_timers.pop(camera_id,None)
        if timer: timer.stop(); timer.deleteLater()
        self.preview_sequences.pop(camera_id,None); self.last_preview_emit.pop(camera_id,None)
        item=self.items.pop(camera_id,None)
        if item:
            thread,worker=item; worker.stop(); thread.quit(); thread.wait(3000)
    def stop_all(self):
        for camera_id in list(self.items): self.stop_camera(camera_id)
    def update_preview_fps(self,camera_id,preview_fps):
        interval=preview_interval_ms(preview_fps)
        item=self.items.get(camera_id)
        if item: item[1].set_preview_fps(preview_fps)
        timer=self.preview_timers.get(camera_id)
        if timer: timer.setInterval(interval)
        return interval
    def _flush_preview(self,camera_id):
        now=time.monotonic()
        worker_item=self.items.get(camera_id)
        if not worker_item: return
        worker=worker_item[1]; item=worker.take_latest_preview(self.preview_sequences.get(camera_id,0))
        if not item: return
        sequence,frame,capture_timestamp,capture_wall_time=item; self.preview_sequences[camera_id]=sequence
        previous=self.last_preview_emit.get(camera_id); actual_fps=1/(now-previous) if previous is not None and now>previous else 0.0; self.last_preview_emit[camera_id]=now
        self.preview_frame.emit(camera_id,frame,{"capture_timestamp":capture_wall_time.isoformat(),"capture_monotonic":capture_timestamp,"preview_display_timestamp":now,"preview_frame_age_ms":max(0,(now-capture_timestamp)*1000),"dropped_preview_frames":worker.dropped_preview_frames,"configured_preview_fps":float(worker.camera.preview_fps),"actual_preview_fps":actual_fps})
    @staticmethod
    def grab_frame(rtsp_url,timeout_ms=5000):
        from .rtsp_capture import grab_rtsp_frame
        return grab_rtsp_frame(rtsp_url,max(5,timeout_ms/1000))
