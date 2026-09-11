from __future__ import annotations

import logging, time,threading
from datetime import datetime, timezone
from types import SimpleNamespace
from PySide6.QtCore import QObject, Signal, Slot

from app.utils.geometry import denormalize_points
from app.utils.image_utils import crop_polygon_roi,rotate_frame
from .detector import Detection
from app.core.config import settings
from .tracker import calculate_track_buffer
from .polygon_engine import PolygonEngine
from .session_vehicle_matcher import attach_vehicle_signature
from .rtsp_capture import RtspCapture


# Phase 4.7B: khong reset reconnect backoff chi vi DUY NHAT mot frame vua den sau
# khi mo lai FFmpeg - neu ket noi that su khong on dinh (vd RTSP flap lien tuc),
# reset backoff qua som se gay "reconnect flapping" (backoff quay ve 1s ngay lap
# tuc, khong con tac dung giam tai spawn FFmpeg lien tuc). Chi reset ve 1.0 sau khi
# co mot khoang thoi gian NHAN DUOC FRAME LIEN TUC on dinh (3s) ke tu luc ket noi
# lai - khong phai vo han, khong doi cach RtspCapture tu phan biet SOFT/HARD stall.
_BACKOFF_STABLE_RESET_SECONDS=3.0


# Phase 4.5: cac truong cau hinh camera ma CameraWorker.run()/set_preview_fps() can doc/ghi.
# CHI danh sach nay duoc sao chep sang snapshot thuan (xem _snapshot_camera) - KHONG duoc
# giu lai doi tuong ORM Camera song (gan voi SQLAlchemy Session cua MainWindow.self.db).
_CAMERA_WORKER_FIELDS=("id","camera_code","rtsp_url","rotation_degrees","processing_fps","preview_fps",
    "zone_type","capacity","parking_confirm_seconds","exit_confirm_seconds","detection_miss_grace_seconds",
    "track_lost_grace_seconds","use_polygon_roi","polygon_points","vehicle_confidence","enable_motorcycles",
    "detector_image_size","vehicle_polygon_overlap_threshold","ai_debug_overlay")


def _snapshot_camera(camera):
    """Phase 4.5 - THREAD SAFETY FIX (CONFIRMED root cause cua loi SQLAlchemy
    "This session is in 'prepared' state; no further SQL can be emitted within this
    transaction" quan sat duoc tren Windows/RTSP that, reports/runtime_ab/case_A_LINK_ERROR_*):
    CameraWorker.run() chay tren MOT QThread rieng cho moi camera
    (xem CameraManager.start_camera: worker.moveToThread(thread)) va lien tuc doc
    self.camera.<attr> (bao gom cot JSON polygon_points) trong SUOT vong doi cua no.
    Truoc patch, self.camera la doi tuong ORM Camera SONG, van con gan voi
    MainWindow.self.db (mot SQLAlchemy Session DUY NHAT dung chung cho CA 3 camera).
    Main thread lien tuc goi self.db.commit()/rollback() tren CHINH Session do (vd
    ParkingSessionService.link_track()/complete_session()/recover(), dac biet lap lai
    rat nhanh moi khi co canh bao 'Track ownership conflict ... reason=session_closed').
    SQLAlchemy Session KHONG an toan da luong - tai lieu chinh thuc cua SQLAlchemy
    khang dinh dieu nay. Da CONFIRMED qua tai hien truc tiep (script doc lap, cung
    engine/Session that): 1 luong doc lien tuc thuoc tinh ORM trong khi luong chinh
    commit/rollback lien tuc tren CUNG Session gay TREO (deadlock-like hang) - cung
    mot vi pham nen tang voi loi 'prepared state' quan sat duoc tren Windows.
    Fix: cat dut hoan toan lien he voi Session TRUOC KHI dua camera vao CameraWorker -
    sao chep cac gia tri cau hinh can thiet sang mot SimpleNamespace THUAN, khong
    thuoc Session nao, an toan doc/ghi tu bat ky luong nao. KHONG doi gia tri nao,
    KHONG doi RTSP/tracker/timer/model/CUDA nao - chi cat dut tham chieu ORM.
    """
    return SimpleNamespace(**{field: getattr(camera, field) for field in _CAMERA_WORKER_FIELDS})


class CameraWorker(QObject):
    frame_ready=Signal(int,object,object); preview_frame=Signal(int,object); status_changed=Signal(int,bool,str); detector_error=Signal(int,str); stopped=Signal(int); error=Signal(int,str)
    def __init__(self,camera,detector,tracker_factory):
        camera=_snapshot_camera(camera)
        buffer_frames=calculate_track_buffer(camera.processing_fps,camera.track_lost_grace_seconds)
        try: tracker=tracker_factory(max_missed=buffer_frames)
        except TypeError: tracker=tracker_factory()
        super().__init__(); self.camera=camera; self.detector=detector; self.tracker=tracker; self.tracker_buffer_frames=buffer_frames; self.running=False; self.capture=None; self.primary_track_id=None; self.last_tracker_telemetry=0.0; self.preview_lock=threading.Lock(); self.latest_preview=None; self.preview_sequence=0; self.dropped_preview_frames=0; self.log=logging.getLogger(f"camera.{camera.camera_code}")
        # Phase 4.7E-B1: STAGE W heartbeat (worker preview production) - RECORDED
        # SEPARATELY from the raw RtspCapture capture_timestamp passed into
        # _emit_preview(), per audit correction "Do NOT incorrectly name raw
        # capture_timestamp as worker-preview time". Read via preview_heartbeat()
        # below, which is NON-DESTRUCTIVE (unlike take_latest_preview(), it never
        # clears latest_preview) so diagnostic polling never interferes with real
        # preview delivery/consumption.
        self.last_preview_produced_monotonic=None

    @Slot()
    def run(self):
        self.running=True; backoff=1.0; cap=None; next_process=0.0; online_announced=False; detector_error_sent=False; frame_index=0
        connected_since=None; backoff_reset_done=True  # Phase 4.7B: xem _BACKOFF_STABLE_RESET_SECONDS
        self.log.info("Worker config camera=%s parking_confirm_seconds=%s exit_confirm_seconds=%s detection_grace_seconds=%s track_lost_seconds=%s zone_type=%s capacity=%s",self.camera.camera_code,self.camera.parking_confirm_seconds,self.camera.exit_confirm_seconds,self.camera.detection_miss_grace_seconds,self.camera.track_lost_grace_seconds,self.camera.zone_type,self.camera.capacity)
        if self.detector.enabled: self.log.info("Detector ready model=%s device=%s half=%s",self.detector.name,getattr(self.detector,"device","-"),getattr(self.detector,"half",False))
        while self.running:
            try:
                if cap is None or not cap.is_opened():
                    cap=RtspCapture(self.camera.rtsp_url,read_timeout=8.0,frame_callback=self._emit_preview,preview_fps=self.camera.preview_fps); self.capture=cap
                    if not cap.open(): raise ConnectionError("Không mở được FFmpeg để đọc RTSP")
                    connected_since=time.monotonic(); backoff_reset_done=False
                ok,frame=cap.read()
                if not ok: raise ConnectionError("Không đọc được frame")
                frame=rotate_frame(frame,self.camera.rotation_degrees)
                if not online_announced:
                    self.log.info("First frame received shape=%s",tuple(frame.shape))
                    self.status_changed.emit(self.camera.id,True,"ONLINE"); online_announced=True
                # Phase 4.7B: reset backoff chi sau khoang on dinh, khong phai ngay frame dau tien.
                if not backoff_reset_done and connected_since is not None and time.monotonic()-connected_since>=_BACKOFF_STABLE_RESET_SECONDS:
                    backoff=1.0; backoff_reset_done=True
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
                for tracked_vehicle in tracks: attach_vehicle_signature(tracked_vehicle,frame)
                primary=None; candidates=[]
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
                self.frame_ready.emit(self.camera.id,frame,{"primary":primary,"polygon_candidates":candidates,"tracks":tracks,"detections":detections,"stats":stats,"time":datetime.now(timezone.utc),"monotonic_time":inference_end})
            except Exception as exc:
                if not self.running:
                    break
                self.log.warning("Worker lỗi: %s; sẽ kết nối lại sau %.0f giây",exc,backoff); self.status_changed.emit(self.camera.id,False,"OFFLINE"); self.error.emit(self.camera.id,f"{exc} - reconnect sau {backoff:.0f}s")
                # Phase 4.7B: log vai dong stderr FFmpeg gan nhat (da loai credential boi
                # RtspCapture._stderr_reader_loop) de ho tro chan doan production - truoc day
                # stderr=DEVNULL nen khong the biet FFmpeg thuc su bao loi gi khi that bai.
                # Phase 4.7B.1: dung get_stderr_summary() (tail rate-limited + tom tat so
                # lan xuat hien tung nhom loi HEVC da biet) thay vi get_stderr_tail() thuan -
                # van 1 dong log duy nhat, khong doi cach log duoc phat ra hay muc do (van chi
                # log khi co du lieu, van sanitize credential nhu cu).
                stderr_summary=cap.get_stderr_summary() if cap else ""
                if stderr_summary: self.log.warning("FFmpeg stderr tail camera=%s:\n%s",self.camera.camera_code,stderr_summary)
                if cap: cap.release(); cap=None; self.capture=None
                online_announced=False; connected_since=None; backoff_reset_done=True
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
                # Phase 4.7E-B1: STAGE W heartbeat - the moment THIS worker actually
                # produced a preview frame, independent of the raw capture_timestamp
                # (RtspCapture-side) and independent of whether CameraManager ever
                # flushes/consumes it (take_latest_preview() is pull-based and can
                # stall downstream without this heartbeat ever stopping).
                self.last_preview_produced_monotonic=time.monotonic()

    def take_latest_preview(self,last_sequence=0):
        with self.preview_lock:
            if self.latest_preview is None or self.latest_preview[0]==last_sequence: return None
            item=self.latest_preview; self.latest_preview=None; return item

    def preview_heartbeat(self):
        """Phase 4.7E-B1: NON-DESTRUCTIVE diagnostic read of STAGE W (worker preview
        production) - returns (preview_sequence, last_preview_produced_monotonic)
        WITHOUT touching latest_preview, so polling this for telemetry can never cause
        a real preview frame to be lost/skipped (unlike take_latest_preview())."""
        with self.preview_lock:
            return self.preview_sequence,self.last_preview_produced_monotonic

    def raw_capture_monotonic(self):
        """Phase 4.7E-B1: STAGE R heartbeat (raw RTSP frame production), read directly
        from RtspCapture.last_valid_frame_monotonic - updated continuously by the
        RtspCapture reader thread in _drain_buffer(), completely independent of whether
        this worker's own run() loop ever reaches detector.detect()/frame_ready.emit()
        (audit correction: a hung detector/tracker must not be observable as
        CAPTURE_STALE). Cross-thread attribute read, no lock - a single float/None
        rebind is atomic under the GIL and this value is diagnostic-only (never used
        for a business/recovery decision in this phase), so no new locking is
        introduced; self.capture itself may be reassigned by run() during reconnect,
        but the local reference taken here is always internally consistent."""
        cap=self.capture
        return cap.last_valid_frame_monotonic if cap is not None else None

    def raw_dropped_capture_frames(self):
        cap=self.capture
        return cap.dropped_capture_frames if cap is not None else 0

    def set_preview_fps(self,preview_fps):
        value=float(preview_fps)
        if not 1 <= value <= 15: raise ValueError("preview_fps phải nằm trong khoảng 1–15 FPS")
        self.camera.preview_fps=value
        if self.capture: self.capture.set_preview_fps(value)

    @Slot()
    def stop(self):
        self.running=False
        if self.capture: self.capture.release()
