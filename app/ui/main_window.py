from __future__ import annotations

import logging,time
from datetime import datetime
from pathlib import Path
from sqlalchemy.exc import IntegrityError
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QAbstractItemView,QApplication,QFileDialog,QHBoxLayout,QInputDialog,QMainWindow,QMessageBox,QPushButton,QSplitter,QStatusBar,QTabWidget,QTableWidget,QTableWidgetItem,QVBoxLayout,QWidget

from app.core.constants import CameraStatus,EventType,ParkingState,SessionStatus
from app.database.repositories import CameraRepository,ParkingRepository
from app.database.session import SessionLocal
from app.services.camera_manager import CameraManager
from app.services.detector import build_detector
from app.services.parking_session_service import ParkingSessionService
from app.services.parking_state_engine import ParkingStateEngine
from app.services.snapshot_service import SnapshotService
from app.ui.camera_dialog import CameraDialog
from app.ui.event_log_widget import EventLogWidget
from app.ui.monitor_widget import MonitorWidget
from app.ui.polygon_editor import PolygonEditor
from app.ui.preview_dialog import PreviewDialog
from app.utils.image_utils import annotate_frame,mask_rtsp_url,rotate_frame,rotate_normalized_polygon
from app.utils.time_utils import format_local_datetime,seconds_between,utc_now


class MainWindow(QMainWindow):
    def __init__(self,settings):
        super().__init__(); self.settings=settings; self.db=SessionLocal(); self.cameras=CameraRepository(self.db); self.parking=ParkingRepository(self.db); self.session_service=ParkingSessionService(self.parking); self.snapshots=SnapshotService(); self.log=logging.getLogger(__name__)
        self.detector=build_detector(settings.detector_model,settings.vehicle_confidence,settings.enable_motorcycles)
        self.manager=CameraManager(self.detector,self); self.manager.frame_ready.connect(self.on_frame); self.manager.preview_frame.connect(self.on_preview_frame); self.manager.status_changed.connect(self.on_camera_status); self.manager.detector_error.connect(self.on_detector_error); self.manager.error.connect(lambda cid,msg:self.log.warning("Camera %s: %s",cid,msg))
        self.engines={}; self.frames={}; self.raw_frames={}; self.last_payload={}; self.last_preview_telemetry={}; self.active={}; self.preview_dialogs={}; self.setWindowTitle("Parking Monitoring System - Phase 1"); self.resize(1280,800); self._build_ui(); self.reload(); self._recover()
    def _build_ui(self):
        splitter=QSplitter(Qt.Vertical); tabs=QTabWidget(); self.camera_page=QWidget(); lay=QVBoxLayout(self.camera_page); bar=QHBoxLayout();
        for text,handler in [("Thêm",self.add_camera),("Sửa",self.edit_camera),("Xóa",self.delete_camera),("Kiểm tra RTSP",self.test_rtsp),("Mở preview",self.open_preview),("Vẽ polygon",self.edit_polygon),("Làm mới",self.reload)]:
            b=QPushButton(text); b.clicked.connect(lambda _checked=False,h=handler:h()); bar.addWidget(b)
        bar.addStretch(); lay.addLayout(bar); self.camera_table=QTableWidget(0,7); self.camera_table.setHorizontalHeaderLabels(["Mã","Tên","Vị trí","RTSP","Trạng thái","FPS","Polygon"]); self.camera_table.setSelectionBehavior(QAbstractItemView.SelectRows); self.camera_table.setEditTriggers(QAbstractItemView.NoEditTriggers); lay.addWidget(self.camera_table)
        self.monitor=MonitorWidget(); self.monitor.preview_requested.connect(self.open_preview); self.history=QTableWidget(0,9); self.history.setHorizontalHeaderLabels(["Session","Camera","Vị trí","Loại xe","Phát hiện","Xác nhận","Rời","Thời lượng","Trạng thái"]); self.history.setEditTriggers(QAbstractItemView.NoEditTriggers)
        tabs.addTab(self.camera_page,"Camera"); tabs.addTab(self.monitor,"Giám sát"); tabs.addTab(self.history,"Lịch sử phiên đỗ"); splitter.addWidget(tabs); self.event_log=EventLogWidget(); splitter.addWidget(self.event_log); splitter.setSizes([620,180]); self.setCentralWidget(splitter); self.setStatusBar(QStatusBar()); self.statusBar().showMessage(f"Database: sẵn sàng | AI: {self.detector.name}")
    def selected_camera(self):
        row=self.camera_table.currentRow()
        return self.cameras.get(int(self.camera_table.item(row,0).data(Qt.UserRole))) if row>=0 else None
    def reload(self):
        cameras=self.cameras.list(); self.camera_table.setRowCount(len(cameras))
        for r,c in enumerate(cameras):
            display_status=c.status if c.enabled else "TẮT"
            values=[c.camera_code,c.camera_name,c.parking_position_code,mask_rtsp_url(c.rtsp_url),display_status,f"{c.processing_fps:g}","Có" if c.polygon_points else "Chưa"]
            for col,value in enumerate(values): item=QTableWidgetItem(str(value)); item.setData(Qt.UserRole,c.id); self.camera_table.setItem(r,col,item)
            if c.id not in self.engines: self.engines[c.id]=ParkingStateEngine(c.parking_confirm_seconds,c.exit_confirm_seconds,self.settings.stable_frames_after_reconnect,c.track_lost_grace_seconds,c.detection_miss_grace_seconds)
            if c.enabled and c.id not in self.manager.items: self.manager.start_camera(c)
        self.monitor.set_cameras(cameras); self.reload_history()
    def reload_history(self):
        rows=self.parking.recent_sessions(); self.history.setRowCount(len(rows))
        for r,s in enumerate(rows):
            duration=s.parking_duration_seconds
            if s.status==SessionStatus.COMPLETED and s.parked_at and s.left_at and (duration is None or duration==0): duration=seconds_between(s.parked_at,s.left_at)
            vals=[s.session_code,s.camera.camera_code,s.parking_position_code,s.vehicle_class or "-",self.dt(s.entered_at),self.dt(s.parked_at),self.dt(s.left_at),f"{duration or 0}s",s.status]
            for c,v in enumerate(vals): self.history.setItem(r,c,QTableWidgetItem(str(v)))
    @staticmethod
    def dt(value): return format_local_datetime(value)
    def add_camera(self):
        dlg=CameraDialog(parent=self)
        if dlg.exec():
            try:
                values=dlg.values(); values["status"]="OFFLINE" if values["enabled"] else "DISABLED"
                self.cameras.add(**values); self.reload()
            except IntegrityError: self.db.rollback(); QMessageBox.warning(self,"Trùng dữ liệu","Mã camera hoặc mã vị trí đã tồn tại.")
    def edit_camera(self):
        camera=self.selected_camera()
        if not camera: return
        dlg=CameraDialog(camera,self)
        if dlg.exec():
            try:
                values=dlg.values()
                values["status"]="OFFLINE" if values["enabled"] else "DISABLED"
                if values["rotation_degrees"]!=camera.rotation_degrees and camera.polygon_points:
                    values["polygon_points"]=rotate_normalized_polygon(camera.polygon_points,camera.rotation_degrees,values["rotation_degrees"])
                self.manager.stop_camera(camera.id); self.cameras.update(camera.id,**values); self.engines.pop(camera.id,None); self.raw_frames.pop(camera.id,None); self.frames.pop(camera.id,None); self.reload()
            except IntegrityError: self.db.rollback(); QMessageBox.warning(self,"Trùng dữ liệu","Mã camera hoặc mã vị trí đã tồn tại.")
    def delete_camera(self):
        camera=self.selected_camera()
        if camera and QMessageBox.question(self,"Xác nhận",f"Xóa camera {camera.camera_code}?")==QMessageBox.Yes:
            if self.parking.active_for_camera(camera.id): QMessageBox.warning(self,"Không thể xóa","Camera có phiên đỗ đang hoạt động."); return
            self.manager.stop_camera(camera.id); self.cameras.delete(camera.id); self.reload()
    def test_rtsp(self):
        camera=self.selected_camera()
        if not camera: return
        frame=self.raw_frames.get(camera.id)
        if frame is None:
            frame=self.manager.grab_frame(camera.rtsp_url)
            if frame is not None: frame=rotate_frame(frame,camera.rotation_degrees)
        if frame is not None:
            if camera.enabled:
                self.manager.stop_camera(camera.id); self.manager.start_camera(self.cameras.get(camera.id))
            QMessageBox.information(self,"Kiểm tra RTSP","Kết nối thành công. Worker đã được khởi động lại.")
        else: QMessageBox.warning(self,"Kiểm tra RTSP","Không đọc được frame.")
    def edit_polygon(self):
        camera=self.selected_camera()
        if not camera: return
        frame=self.raw_frames.get(camera.id)
        if frame is None:
            frame=self.manager.grab_frame(camera.rtsp_url)
            if frame is not None: frame=rotate_frame(frame,camera.rotation_degrees)
        if frame is None: QMessageBox.warning(self,"Không có ảnh","Không lấy được frame hiện tại."); return
        dlg=PolygonEditor(frame,camera.polygon_points,self)
        if dlg.exec(): self.cameras.update(camera.id,polygon_points=dlg.normalized_points()); self.manager.stop_camera(camera.id); self.reload()
    def open_preview(self,camera_id=None):
        if camera_id is None:
            camera=self.selected_camera()
            if not camera: return
            camera_id=camera.id
        camera=self.cameras.get(camera_id)
        if not camera: return
        if not camera.enabled:
            QMessageBox.information(self,"Camera đang tắt","Camera đã tắt trong cấu hình. Hãy bật camera trước khi mở preview."); return
        dialog=self.preview_dialogs.get(camera_id)
        if dialog is None:
            dialog=PreviewDialog(camera,self); dialog.finished.connect(lambda _=0,cid=camera_id:self.preview_dialogs.pop(cid,None)); self.preview_dialogs[camera_id]=dialog
        if camera_id in self.frames: dialog.update_frame(self.frames[camera_id])
        dialog.show(); dialog.raise_(); dialog.activateWindow()
    def _recover(self):
        for session in self.parking.active_sessions(): self.active[session.camera_id]=session; self.engines.setdefault(session.camera_id,ParkingStateEngine()).restore_active_session()
    def on_camera_status(self,camera_id,online,status):
        camera=self.cameras.get(camera_id)
        if not camera: return
        self.cameras.update(camera_id,status=CameraStatus.ONLINE if online else CameraStatus.OFFLINE,last_online_at=utc_now() if online else camera.last_online_at)
        for row in range(self.camera_table.rowCount()):
            item=self.camera_table.item(row,0)
            if item and int(item.data(Qt.UserRole))==camera_id:
                self.camera_table.item(row,4).setText("ONLINE" if online else "OFFLINE"); break
        engine=self.engines.get(camera_id)
        if not online and engine: engine.camera_offline(); self.monitor.update_camera(camera_id,state="CAMERA_OFFLINE")
    def on_detector_error(self,camera_id,message):
        self.log.error("Camera %s detector error: %s",camera_id,message); self.monitor.update_camera(camera_id,state="DETECTOR_ERROR",tracker="ERROR")
    def on_frame(self,camera_id,frame,payload):
        camera=self.cameras.get(camera_id); vehicle=payload["primary"]; self.last_payload[camera_id]=payload
        engine=self.engines[camera_id]; now=payload["time"]; transition=engine.update(vehicle,now,True,payload.get("monotonic_time")); session=self.active.get(camera_id)
        if session and vehicle and self.session_service.ensure_track(session,vehicle,now):
            self.log.info("Track changed but session retained session=%s new_track=%s",session.session_code,vehicle.track_id)
        event_vehicle=transition.vehicle or vehicle
        if transition.action in ("PARK_START","PARK_START_RECOVERY") and event_vehicle:
            # entered_at is the candidate start retained by the engine.
            source="SYSTEM_RECOVERY" if transition.action=="PARK_START_RECOVERY" else "AI"; session=self.session_service.start(camera,event_vehicle,engine.candidate_since or now,now,None,None,event_source=source)
            # Phase 1 giữ frame xác nhận làm ảnh enter khi không có bộ đệm frame ứng viên.
            enter=self.snapshots.save(frame,camera.camera_code,session.session_code,"enter",engine.candidate_since or now)
            parked=self.snapshots.save(frame,camera.camera_code,session.session_code,"parked",now)
            session.enter_snapshot_path=enter; session.parked_snapshot_path=parked; self.db.commit(); self.active[camera_id]=session; self.log.info("Parking session started code=%s source=%s track=%s",session.session_code,source,event_vehicle.track_id); self.reload_history()
        elif transition.action in ("RECOVER_SESSION","TRACK_RECOVERED") and session and vehicle:
            self.session_service.recover(session,vehicle,now); self.log.info("Track recovered session=%s track=%s",session.session_code,vehicle.track_id)
        elif transition.action=="TRACK_LOST" and session:
            self.log.info("Track lost session=%s",session.session_code)
        elif transition.action=="VEHICLE_CANDIDATE": self.log.info("Candidate started camera=%s track=%s",camera.camera_code,getattr(vehicle,"track_id","-"))
        elif transition.action=="CANDIDATE_CANCELLED": self.log.info("Candidate cancelled camera=%s reason=%s miss_elapsed=%.1f presence_ratio=%.2f",camera.camera_code,engine.cancel_reason,engine.candidate_miss_elapsed,engine.presence_ratio)
        elif transition.action=="VEHICLE_LEAVING" and session: self.log.info("Leaving started session=%s",session.session_code)
        elif transition.action=="PARK_END" and session:
            exit_path=self.snapshots.save(frame,camera.camera_code,session.session_code,"exit",now); self.session_service.complete_session(session,camera_id,transition.vehicle,now,exit_path); self.active.pop(camera_id,None); self.log.info("Kết thúc session %s",session.session_code); self.reload_history()
        stats=payload.get("stats",{}); stats.update({"presence_ratio":engine.presence_ratio,"candidate_miss_elapsed":engine.candidate_miss_elapsed,"candidate_cancel_reason":engine.cancel_reason}); inference_ms=float(stats.get("inference_ms",0)); actual_fps=(1000/inference_ms) if inference_ms>0 else 0; state=str(transition.current); display_vehicle=vehicle or (engine.primary if engine.state in (ParkingState.VEHICLE_CANDIDATE,ParkingState.OCCUPIED,ParkingState.LEAVING) else None); self.monitor.update_camera(camera_id,state=state,track=getattr(display_vehicle,"track_id","-"),session=getattr(session,"session_code","-"),vehicle=getattr(display_vehicle,"vehicle_class","-"),fps=f"{actual_fps:.2f}",raw=stats.get("raw_detections",0),detected=stats.get("vehicle_detections",0),inside=stats.get("vehicles_in_polygon",0),inference=f"{inference_ms:.1f}",tracker=stats.get("tracker_status","IDLE"))
    def on_preview_frame(self,camera_id,frame,preview_stats):
        camera=self.cameras.get(camera_id)
        if not camera: return
        self.raw_frames[camera_id]=frame.copy(); payload=self.last_payload.get(camera_id,{"tracks":[],"primary":None,"stats":{}}); stats=dict(payload.get("stats",{})); stats.update(preview_stats); engine=self.engines.get(camera_id)
        if engine:
            tick=time.monotonic(); stats.update({"state":str(engine.state),"candidate_elapsed":max(0,tick-engine.candidate_tick) if engine.candidate_tick is not None else 0,"candidate_miss_elapsed":engine.candidate_miss_elapsed,"presence_ratio":engine.presence_ratio,"leaving_elapsed":max(0,tick-engine.empty_tick) if engine.empty_tick is not None else 0})
        annotated=annotate_frame(frame,camera.polygon_points,payload.get("tracks",[]),payload.get("primary"),stats if camera.ai_debug_overlay else None,payload.get("detections",[])); self.frames[camera_id]=annotated
        self.monitor.update_frame(camera_id,annotated)
        dialog=self.preview_dialogs.get(camera_id)
        if dialog: dialog.update_frame(annotated)
        tick=time.monotonic()
        if camera.ai_debug_overlay and tick-self.last_preview_telemetry.get(camera_id,0)>=self.settings.telemetry_interval_seconds:
            self.last_preview_telemetry[camera_id]=tick; last_seen=max(0,tick-engine.last_vehicle_seen_tick) if engine and engine.last_vehicle_seen_tick is not None else -1; self.log.info("Pipeline telemetry camera=%s capture_timestamp=%s inference_start=%s inference_end=%s preview_display_timestamp=%.6f ai_frame_age_ms=%.1f preview_frame_age_ms=%.1f dropped_capture_frames=%s dropped_preview_frames=%s queue_size=%s motorcycle=%s time_since_last_detection=%.1f presence_ratio=%.2f candidate_elapsed=%.1f candidate_miss_elapsed=%.1f",camera.camera_code,stats.get("capture_timestamp"),stats.get("inference_start"),stats.get("inference_end"),preview_stats.get("preview_display_timestamp",0),float(stats.get("ai_frame_age_ms",0)),float(preview_stats.get("preview_frame_age_ms",0)),stats.get("dropped_capture_frames",0),preview_stats.get("dropped_preview_frames",0),stats.get("queue_size",0),[r for r in stats.get("vehicle_results",[]) if r.get("class")=="motorcycle"],last_seen,float(stats.get("presence_ratio",0)),float(stats.get("candidate_elapsed",0)),float(stats.get("candidate_miss_elapsed",0)),extra={"telemetry":True})
    def closeEvent(self,event): self.manager.stop_all(); self.db.close(); event.accept()
