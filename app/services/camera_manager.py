import time
from PySide6.QtCore import QObject, QThread, QTimer, Signal

from .camera_worker import CameraWorker
from .tracker import CentroidTracker


class CameraManager(QObject):
    frame_ready=Signal(int,object,object); preview_frame=Signal(int,object,object); status_changed=Signal(int,bool,str); detector_error=Signal(int,str); error=Signal(int,str)
    def __init__(self,detector,parent=None):
        super().__init__(parent); self.detector=detector; self.items={}; self.preview_sequences={}; self.preview_timer=QTimer(self); self.preview_timer.setInterval(200); self.preview_timer.timeout.connect(self._flush_previews); self.preview_timer.start()
    def start_camera(self,camera):
        self.stop_camera(camera.id)
        thread=QThread(self); worker=CameraWorker(camera,self.detector,CentroidTracker); worker.moveToThread(thread)
        thread.started.connect(worker.run); worker.frame_ready.connect(self.frame_ready); worker.status_changed.connect(self.status_changed); worker.detector_error.connect(self.detector_error); worker.error.connect(self.error)
        worker.stopped.connect(thread.quit); thread.finished.connect(worker.deleteLater); thread.finished.connect(thread.deleteLater)
        self.items[camera.id]=(thread,worker); thread.start()
    def stop_camera(self,camera_id):
        item=self.items.pop(camera_id,None)
        if item:
            thread,worker=item; worker.stop(); thread.quit(); thread.wait(3000)
    def stop_all(self):
        for camera_id in list(self.items): self.stop_camera(camera_id)
    def _flush_previews(self):
        now=time.monotonic()
        for camera_id,(_,worker) in list(self.items.items()):
            item=worker.take_latest_preview(self.preview_sequences.get(camera_id,0))
            if not item: continue
            sequence,frame,capture_timestamp,capture_wall_time=item; self.preview_sequences[camera_id]=sequence
            self.preview_frame.emit(camera_id,frame,{"capture_timestamp":capture_wall_time.isoformat(),"capture_monotonic":capture_timestamp,"preview_display_timestamp":now,"preview_frame_age_ms":max(0,(now-capture_timestamp)*1000),"dropped_preview_frames":worker.dropped_preview_frames})
    @staticmethod
    def grab_frame(rtsp_url,timeout_ms=5000):
        from .rtsp_capture import grab_rtsp_frame
        return grab_rtsp_frame(rtsp_url,max(5,timeout_ms/1000))
