from __future__ import annotations

import logging, time,threading
from datetime import datetime, timezone
from PySide6.QtCore import QObject, Signal, Slot

from app.utils.geometry import denormalize_points
from app.utils.image_utils import crop_polygon_roi,rotate_frame
from .detector import Detection
from app.core.config import settings
from .tracker import calculate_track_buffer
from .polygon_engine import PolygonEngine
from .rtsp_capture import RtspCapture


class CameraWorker(QObject):
    frame_ready=Signal(int,object,object); preview_frame=Signal(int,object); status_changed=Signal(int,bool,str); detector_error=Signal(int,str); stopped=Signal(int); error=Signal(int,str)
    def __init__(self,camera,detector,tracker_factory):
        buffer_frames=calculate_track_buffer(camera.processing_fps,camera.track_lost_grace_seconds)
        try: tracker=tracker_factory(max_missed=buffer_frames)
        except TypeError: tracker=tracker_factory()
        super().__init__(); self.camera=camera; self.detector=detector; self.tracker=tracker; self.tracker_buffer_frames=buffer_frames; self.running=False; self.capture=None; self.primary_track_id=None; self.last_tracker_telemetry=0.0; self.preview_lock=threading.Lock(); self.latest_preview=None; self.preview_sequence=0; self.dropped_preview_frames=0; self.log=logging.getLogger(f"camera.{camera.camera_code}")

    @Slot()
    def run(self):
        self.running=True; backoff=1.0; cap=None; next_process=0.0; online_announced=False; detector_error_sent=False; frame_index=0
        if self.detector.enabled: self.log.info("Detector ready model=%s device=%s half=%s",self.detector.name,getattr(self.detector,"device","-"),getattr(self.detector,"half",False))
        while self.running:
            try:
                if cap is None or not cap.is_opened():
                    cap=RtspCapture(self.camera.rtsp_url,read_timeout=8.0,frame_callback=self._emit_preview,preview_fps=settings.preview_fps); self.capture=cap
                    if not cap.open(): raise ConnectionError("Không mở được FFmpeg để đọc RTSP")
                ok,frame=cap.read()
                if not ok: raise ConnectionError("Không đọc được frame")
                frame=rotate_frame(frame,self.camera.rotation_degrees)
                if not online_announced:
                    self.log.info("First frame received shape=%s",tuple(frame.shape))
                    self.status_changed.emit(self.camera.id,True,"ONLINE"); online_announced=True
                backoff=1.0
                now=time.monotonic()
                if now<next_process: continue
                next_process=now+1/max(.1,self.camera.processing_fps)
                frame_index+=1
                if not self.detector.enabled:
                    if not detector_error_sent: self.detector_error.emit(self.camera.id,self.detector.error); detector_error_sent=True
                    continue
                inference_frame,roi_offset=(frame,(0,0))
                if self.camera.use_polygon_roi and self.camera.polygon_points: inference_frame,roi_offset=crop_polygon_roi(frame,self.camera.polygon_points,.10)
                inference_start=time.monotonic(); detections=self.detector.detect(inference_frame,self.camera.vehicle_confidence,self.camera.enable_motorcycles,self.camera.detector_image_size); inference_end=time.monotonic()
                if roi_offset!=(0,0):
                    ox,oy=roi_offset; detections=[Detection((d.bbox[0]+ox,d.bbox[1]+oy,d.bbox[2]+ox,d.bbox[3]+oy),d.confidence,d.vehicle_class) for d in detections]
                tracks=self.tracker.update(detections,frame_index=frame_index,now=datetime.now(timezone.utc))
                primary=None
                if self.camera.polygon_points:
                    h,w=frame.shape[:2]; polygon=denormalize_points([tuple(p) for p in self.camera.polygon_points],w,h)
                    candidates=PolygonEngine(polygon,self.camera.vehicle_polygon_overlap_threshold).evaluate(tracks)
                    primary=next((item for item in candidates if str(item.track_id)==str(self.primary_track_id)),None) or (candidates[0] if candidates else None)
                    new_primary=getattr(primary,"track_id",None)
                    if new_primary!=self.primary_track_id and new_primary is not None: self.log.info("Primary track selected track=%s overlap=%.3f inside=%s",new_primary,primary.overlap,primary.anchor_inside)
                    self.primary_track_id=new_primary
                ai_age_ms=max(0,(inference_start-(cap.last_capture_timestamp or inference_start))*1000); stats=dict(self.detector.last_stats); stats.update({"vehicle_results":[{"class":d.vehicle_class,"confidence":d.confidence,"bbox":d.bbox} for d in detections],"original_frame_size":tuple(frame.shape[:2]),"inference_frame_size":tuple(inference_frame.shape[:2]),"roi_offset":roi_offset,"vehicles_in_polygon":sum(1 for t in tracks if t.anchor_inside or t.overlap>=self.camera.vehicle_polygon_overlap_threshold),"tracker_status":"FRAME_DELAY" if ai_age_ms>1500 else ("OK" if tracks else ("NO_TRACK" if detections else "IDLE")),"frame_index":frame_index,"capture_timestamp":cap.last_capture_wall_time.isoformat() if cap.last_capture_wall_time else None,"capture_monotonic":cap.last_capture_timestamp,"inference_start":inference_start,"inference_end":inference_end,"ai_frame_age_ms":ai_age_ms,"dropped_capture_frames":cap.dropped_capture_frames,"dropped_preview_frames":self.dropped_preview_frames,"queue_size":cap.queue_size,"frame_delay":ai_age_ms>1500})
                self.log.debug("tracker frame=%d detections=%d inputs=%s outputs=%s buffer=%d",frame_index,len(detections),[(round(d.confidence,3),tuple(round(v) for v in d.bbox)) for d in detections],[(t.track_id,t.track_age,t.time_since_update) for t in tracks],self.tracker_buffer_frames)
                telemetry_now=time.monotonic()
                if self.camera.ai_debug_overlay and telemetry_now-self.last_tracker_telemetry>=settings.telemetry_interval_seconds:
                    self.last_tracker_telemetry=telemetry_now; inference_ms=float(stats.get("inference_ms",0)); actual_fps=1000/inference_ms if inference_ms>0 else 0
                    self.log.info("Tracker telemetry frame=%d detections=%d inputs=%s outputs=%s configured_fps=%.2f actual_ai_fps=%.2f track_lost_seconds=%.2f calculated_track_buffer=%d",frame_index,len(detections),[(round(d.confidence,3),tuple(round(v) for v in d.bbox)) for d in detections],[(t.track_id,t.track_age,t.time_since_update) for t in tracks],self.camera.processing_fps,actual_fps,self.camera.track_lost_grace_seconds,self.tracker_buffer_frames,extra={"telemetry":True})
                self.frame_ready.emit(self.camera.id,frame,{"primary":primary,"tracks":tracks,"detections":detections,"stats":stats,"time":datetime.now(timezone.utc),"monotonic_time":inference_end})
            except Exception as exc:
                if not self.running:
                    break
                self.log.warning("Worker lỗi: %s; sẽ kết nối lại sau %.0f giây",exc,backoff); self.status_changed.emit(self.camera.id,False,"OFFLINE"); self.error.emit(self.camera.id,f"{exc} - reconnect sau {backoff:.0f}s")
                if cap: cap.release(); cap=None; self.capture=None
                online_announced=False
                end=time.monotonic()+backoff
                while self.running and time.monotonic()<end: time.sleep(.1)
                backoff=min(30.0,backoff*2)
        if cap: cap.release()
        self.stopped.emit(self.camera.id)

    def _emit_preview(self,frame,capture_timestamp,capture_wall_time):
        if self.running:
            rotated=rotate_frame(frame,self.camera.rotation_degrees)
            with self.preview_lock:
                if self.latest_preview is not None: self.dropped_preview_frames+=1
                self.preview_sequence+=1; self.latest_preview=(self.preview_sequence,rotated,capture_timestamp,capture_wall_time)

    def take_latest_preview(self,last_sequence=0):
        with self.preview_lock:
            if self.latest_preview is None or self.latest_preview[0]==last_sequence: return None
            item=self.latest_preview; self.latest_preview=None; return item

    @Slot()
    def stop(self):
        self.running=False
        if self.capture: self.capture.release()
