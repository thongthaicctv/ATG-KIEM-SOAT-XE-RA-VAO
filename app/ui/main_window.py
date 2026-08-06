from __future__ import annotations

import logging,time
from datetime import datetime
from pathlib import Path
from sqlalchemy.exc import IntegrityError
from PySide6.QtCore import Qt,QTimer
from PySide6.QtWidgets import QAbstractItemView,QApplication,QFileDialog,QHBoxLayout,QInputDialog,QMainWindow,QMessageBox,QPushButton,QSplitter,QStatusBar,QTabWidget,QTableWidget,QTableWidgetItem,QVBoxLayout,QWidget

from app.core.constants import CameraStatus,EventType,ParkingState,SessionStatus
from app.database.repositories import CameraRepository,ParkingRepository
from app.database.session import SessionLocal
from app.services.camera_manager import CameraManager
from app.services.detector import build_detector
from app.services.parking_session_service import ParkingSessionService
from app.services.parking_state_engine import ParkingStateEngine
from app.services.snapshot_service import SnapshotService
from app.services.session_vehicle_matcher import is_same_session_vehicle
from app.services.zone_runtime import ZoneRuntimeState
from app.ui.camera_dialog import CameraDialog
from app.ui.event_log_widget import EventLogWidget
from app.ui.debug_guide_dialog import DebugGuideDialog
from app.ui.monitor_widget import MonitorWidget
from app.ui.polygon_editor import PolygonEditor
from app.ui.preview_dialog import PreviewDialog
from app.utils.image_utils import annotate_frame,mask_rtsp_url,rotate_frame,rotate_normalized_polygon
from app.utils.time_utils import format_local_datetime,seconds_between,utc_now


def format_duration_minutes(duration_seconds):
    return f"{max(0,float(duration_seconds or 0))/60:.2f} phút"


class MainWindow(QMainWindow):
    def __init__(self,settings):
        super().__init__(); self.settings=settings; self.db=SessionLocal(); self.cameras=CameraRepository(self.db); self.parking=ParkingRepository(self.db); self.session_service=ParkingSessionService(self.parking); self.snapshots=SnapshotService(); self.log=logging.getLogger(__name__)
        self.session_service.signals.session_started.connect(self.refresh_history_session); self.session_service.signals.session_recovered.connect(self.refresh_history_session); self.session_service.signals.session_completed.connect(self.refresh_history_session)
        self.detector=build_detector(settings.detector_model,settings.vehicle_confidence,settings.enable_motorcycles,settings.detector_device,settings.detector_half)
        self.manager=CameraManager(self.detector,self,max_cameras=settings.max_cameras,preview_fps=settings.preview_fps); self.manager.frame_ready.connect(self.on_zone_frame_safe); self.manager.preview_frame.connect(self.on_preview_frame); self.manager.status_changed.connect(self.on_camera_status); self.manager.detector_error.connect(self.on_detector_error); self.manager.error.connect(lambda cid,msg:self.log.warning("Camera %s: %s",cid,msg))
        self.pipeline_errors={}; self.last_capture_frame={}; self.last_ai_result={}; self.zones={}; self.engines={}; self.frames={}; self.raw_frames={}; self.last_payload={}; self.last_preview_telemetry={}; self.last_occupancy_signature={}; self.active={}; self.preview_dialogs={}; self.setWindowTitle("Parking Monitoring System - Phase 1.4"); self.resize(1280,800); self._build_ui(); self.reload(start_workers=False); self._recover(); self.reload(start_workers=True); self.pipeline_watchdog=QTimer(self); self.pipeline_watchdog.setInterval(2000); self.pipeline_watchdog.timeout.connect(self._check_pipeline_health); self.pipeline_watchdog.start()
    def _build_ui(self):
        splitter=QSplitter(Qt.Vertical); self.tabs=QTabWidget(); tabs=self.tabs; self.camera_page=QWidget(); lay=QVBoxLayout(self.camera_page); bar=QHBoxLayout();
        for text,handler in [("Thêm",self.add_camera),("Sửa",self.edit_camera),("Xóa",self.delete_camera),("Kiểm tra RTSP",self.test_rtsp),("Mở preview",self.open_preview),("Vẽ polygon",self.edit_polygon),("Hướng dẫn debug",self.open_debug_guide),("Làm mới",self.reload)]:
            b=QPushButton(text); b.clicked.connect(lambda _checked=False,h=handler:h()); bar.addWidget(b)
        bar.addStretch(); lay.addLayout(bar); self.camera_table=QTableWidget(0,7); self.camera_table.setHorizontalHeaderLabels(["Mã","Tên","Vị trí","RTSP","Trạng thái","FPS","Polygon"]); self.camera_table.setSelectionBehavior(QAbstractItemView.SelectRows); self.camera_table.setEditTriggers(QAbstractItemView.NoEditTriggers); lay.addWidget(self.camera_table)
        self.monitor=MonitorWidget(); self.monitor.preview_requested.connect(self.open_preview); self.history=QTableWidget(0,9); self.history.setHorizontalHeaderLabels(["Session","Camera","Vị trí","Loại xe","Phát hiện","Xác nhận","Rời","Thời lượng (phút)","Trạng thái"]); self.history.setEditTriggers(QAbstractItemView.NoEditTriggers)
        tabs.addTab(self.camera_page,"Camera"); tabs.addTab(self.monitor,"Giám sát"); self.history_tab_index=tabs.addTab(self.history,"Lịch sử phiên đỗ"); tabs.currentChanged.connect(self._on_tab_changed); splitter.addWidget(tabs); self.event_log=EventLogWidget(); splitter.addWidget(self.event_log); splitter.setSizes([620,180]); self.setCentralWidget(splitter); self.setStatusBar(QStatusBar()); db_mode=getattr(self.settings,"database_mode","PRODUCTION"); runtime_mode=getattr(self.settings,"runtime_mode",self.settings.runtime_profile); self.statusBar().showMessage(f"DB MODE: {db_mode} | Mode: {runtime_mode} | Profile: {self.settings.runtime_profile} | camera: 0/{self.settings.max_cameras} | AI: {getattr(self.detector,'actual_device',self.detector.device)} | model instances: {1 if self.detector.enabled else 0}")
    def selected_camera(self):
        row=self.camera_table.currentRow()
        return self.cameras.get(int(self.camera_table.item(row,0).data(Qt.UserRole))) if row>=0 else None
    def open_debug_guide(self): DebugGuideDialog(self.settings,self).exec()
    def reload(self,start_workers=True):
        cameras=self.cameras.list(); self.camera_table.setRowCount(len(cameras))
        for r,c in enumerate(cameras):
            display_status=c.status if c.enabled else "TẮT"
            values=[c.camera_code,c.camera_name,c.parking_position_code,mask_rtsp_url(c.rtsp_url),display_status,f"{c.processing_fps:g}","Có" if c.polygon_points else "Chưa"]
            for col,value in enumerate(values): item=QTableWidgetItem(str(value)); item.setData(Qt.UserRole,c.id); self.camera_table.setItem(r,col,item)
            if c.id not in self.engines: self.engines[c.id]=ParkingStateEngine(c.parking_confirm_seconds,c.exit_confirm_seconds,self.settings.stable_frames_after_reconnect,c.track_lost_grace_seconds,c.detection_miss_grace_seconds)
            if c.id not in self.zones: self.zones[c.id]=ZoneRuntimeState(c,self.settings.stable_frames_after_reconnect)
            configured=c.zone_type!="LEGACY_UNSET"
            if not configured: self.camera_table.item(r,4).setText("CHƯA CẤU HÌNH")
            database_mode=getattr(self.settings,"database_mode","PRODUCTION"); selected_codes=getattr(self.settings,"selected_camera_codes",())
            runtime_selected=(database_mode=="DEBUG" and c.camera_code in selected_codes) or (database_mode=="PRODUCTION" and c.enabled)
            if start_workers and runtime_selected and configured and self.detector.enabled and c.id not in self.manager.items: self.manager.start_camera(c)
        self.monitor.set_cameras(cameras); self.reload_history()
    def reload_history(self):
        rows=self.parking.recent_sessions(); self.history.setRowCount(len(rows))
        for r,s in enumerate(rows):
            self._set_history_row(r,s)
    def _set_history_row(self,row,s):
        duration=s.parking_duration_seconds
        if s.status==SessionStatus.COMPLETED and s.parked_at and s.left_at and (duration is None or duration==0): duration=seconds_between(s.parked_at,s.left_at)
        vals=[s.session_code,s.camera.camera_code,s.parking_position_code,s.vehicle_class or "-",self.dt(s.entered_at),self.dt(s.parked_at),self.dt(s.left_at),format_duration_minutes(duration),s.status]
        for column,value in enumerate(vals):
            item=QTableWidgetItem(str(value)); item.setData(Qt.UserRole,s.id); self.history.setItem(row,column,item)
    def refresh_history_session(self,session_id):
        session=self.parking.get_session(int(session_id))
        if session is None: return
        row=next((r for r in range(self.history.rowCount()) if self.history.item(r,0) and self.history.item(r,0).data(Qt.UserRole)==session.id),-1)
        if row<0: self.history.insertRow(0); row=0
        self._set_history_row(row,session)
    def _on_tab_changed(self,index):
        if index==self.history_tab_index: self.reload_history()
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
                changed={key for key,value in values.items() if key!="status" and getattr(camera,key)!=value}
                if changed=={"preview_fps"}:
                    preview_fps=values["preview_fps"]; self.cameras.update(camera.id,preview_fps=preview_fps); self.manager.update_preview_fps(camera.id,preview_fps); self.monitor.set_preview_fps(camera.id,preview_fps); self.log.info("Preview FPS updated camera=%s configured_preview_fps=%s without_worker_restart=true",camera.camera_code,preview_fps); return
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
        dlg=PolygonEditor(frame,camera.polygon_points,self,ignore_zones=camera.ignore_zones)
        if dlg.exec(): self.cameras.update(camera.id,polygon_points=dlg.normalized_points(),ignore_zones=dlg.normalized_ignore_zones()); self.manager.stop_camera(camera.id); self.zones.pop(camera.id,None); self.engines.pop(camera.id,None); self.reload()
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
        for session in self.parking.active_sessions():
            camera=self.cameras.get(session.camera_id)
            if camera:
                self.zones.setdefault(session.camera_id,ZoneRuntimeState(camera,self.settings.stable_frames_after_reconnect)).restore_session(session)
    def on_camera_status(self,camera_id,online,status):
        camera=self.cameras.get(camera_id)
        if not camera: return
        self.cameras.update(camera_id,status=CameraStatus.ONLINE if online else CameraStatus.OFFLINE,last_online_at=utc_now() if online else camera.last_online_at)
        for row in range(self.camera_table.rowCount()):
            item=self.camera_table.item(row,0)
            if item and int(item.data(Qt.UserRole))==camera_id:
                self.camera_table.item(row,4).setText("ONLINE" if online else "OFFLINE"); break
        engine=self.engines.get(camera_id)
        if online:
            self.log.info("Camera online camera=%s first_frame=true detector_ready=%s",camera.camera_code,self.detector.enabled)
            self.monitor.update_camera(camera_id,state="RECOVERY_PENDING" if camera_id in self.active else "UNKNOWN",session=getattr(self.active.get(camera_id),"session_code","-"),tracker="IDLE")
        elif engine:
            if camera_id in self.zones: self.zones[camera_id].camera_offline()
            now=utc_now(); transition=engine.camera_offline(now,time.monotonic()); session=self.active.get(camera_id)
            if session:
                if transition.previous!=ParkingState.CAMERA_OFFLINE: session.offline_started_at=now; self.db.commit()
                self.log.warning("Camera offline with active session camera=%s session=%s last_track=%s last_seen=%s",camera.camera_code,session.session_code,session.current_track_id,session.last_confirmed_seen_at)
            self.log.info("State transition camera=%s %s -> %s action=%s",camera.camera_code,transition.previous,transition.current,transition.action); self.monitor.update_camera(camera_id,state="CAMERA_OFFLINE",session=getattr(session,"session_code","-"),vehicle=getattr(session,"vehicle_class","-"))
    def on_detector_error(self,camera_id,message):
        self.log.error("Camera %s detector error: %s",camera_id,message); self.monitor.update_camera(camera_id,state="DETECTOR_ERROR",tracker="ERROR")
    def on_zone_frame_safe(self,camera_id,frame,payload):
        try:
            self.on_zone_frame(camera_id,frame,payload); self.pipeline_errors[camera_id]=0; self.last_ai_result[camera_id]=time.monotonic()
        except Exception as exc:
            self.db.rollback(); count=self.pipeline_errors.get(camera_id,0)+1; self.pipeline_errors[camera_id]=count
            if count==1 or count%30==0: self.log.exception("Recoverable AI/session pipeline error camera=%s consecutive=%s error=%s",camera_id,count,exc)
            self.monitor.update_camera(camera_id,state="AI_SESSION_RECOVERY" if count<3 else "AI_SESSION_ERROR",track="STALE",session="Giữ nguyên phiên",vehicle="-",fps="STALE",tracker="TRACK_SESSION_CONFLICT")
            if count<=3: self._reconcile_zone(camera_id)
    def _check_pipeline_health(self):
        now=time.monotonic()
        for camera_id,captured_at in list(self.last_capture_frame.items()):
            capture_age=now-captured_at; ai_age=now-self.last_ai_result.get(camera_id,0)
            if capture_age<3 and camera_id in self.last_ai_result and ai_age>10:
                self.monitor.update_camera(camera_id,state="AI_SESSION_ERROR",track="STALE",session="Giữ nguyên phiên",vehicle="-",fps="STALE",tracker="AI_RESULT_STALE")
    def _reconcile_zone(self,camera_id):
        camera=self.cameras.get(camera_id)
        if not camera: return
        previous=self.zones.get(camera_id); rebuilt=ZoneRuntimeState(camera,self.settings.stable_frames_after_reconnect)
        if previous: rebuilt.reconnect_generation=previous.reconnect_generation
        for session in self.parking.find_open_sessions_for_position(camera.id,camera.parking_position_code): rebuilt.restore_session(session)
        self.zones[camera_id]=rebuilt; self.log.info("AI session recovery map rebuilt camera=%s open_sessions=%s generation=%s",camera.camera_code,len(rebuilt.vehicles),rebuilt.reconnect_generation)
    def on_zone_frame(self,camera_id,frame,payload):
        camera=self.cameras.get(camera_id); zone=self.zones[camera_id]; now=payload["time"]; tick=payload.get("monotonic_time",time.monotonic()); candidates=payload.get("polygon_candidates",[]); self.last_payload[camera_id]=payload
        actions=zone.process(candidates,now,tick)
        for ignored in zone.ignored:
            track_id=str(ignored.track_id)
            if track_id not in zone.ignored_track_ids_logged:
                zone.ignored_track_ids_logged.add(track_id); self.log.info("Detection ignored camera=%s track=%s raw_class=%s reason=IGNORE_ZONE bbox=%s anchor=%s",camera.camera_code,track_id,ignored.vehicle_class,ignored.bbox,ignored.anchor_normalized)
        payload.setdefault("stats",{})["ignored_detections"]=len(zone.ignored); candidates=[candidate for candidate in candidates if not candidate.ignored]
        for action in actions:
            runtime=zone.vehicles.get(action.runtime_id)
            if action.kind=="PARK_START" and runtime and action.vehicle:
                if runtime.session_id is not None:
                    self.log.warning("Duplicate session start prevented vehicle_instance_id=%s existing_session=%s requested_track=%s reason=runtime_has_session",runtime.vehicle_instance_id,runtime.session_code,action.vehicle.track_id); continue
                session=self.session_service.start(camera,action.vehicle,runtime.first_seen_at or now,now,vehicle_instance_id=runtime.vehicle_instance_id,tracker_generation=zone.reconnect_generation)
                runtime.session_id=session.id; runtime.session_code=session.session_code
                enter=self.snapshots.save(frame,camera.camera_code,session.session_code,"enter",runtime.first_seen_at or now); parked=self.snapshots.save(frame,camera.camera_code,session.session_code,"parked",now); session.enter_snapshot_path=enter; session.parked_snapshot_path=parked; self.db.commit()
                self.log.info("Parking session started camera=%s session=%s runtime=%s track=%s",camera.camera_code,session.session_code,runtime.runtime_id,action.vehicle.track_id)
            elif action.kind in ("RECOVER_SESSION","TRACK_RECOVERED","OBSERVED") and runtime and action.vehicle and action.session_id:
                session=self.parking.get_session(action.session_id)
                if session:
                    owner=self.parking.get_open_session_for_track(camera.id,action.vehicle.track_id,zone.reconnect_generation)
                    if owner and owner.id!=session.id:
                        runtime.state="IDENTITY_UNCERTAIN"; self.log.warning("Track ownership conflict camera=%s track_id=%s requested_session=%s existing_session=%s requested_vehicle_instance=%s existing_vehicle_instance=%s requested_state=%s existing_state=%s connection_generation=%s association_cycle_id=%s",camera.camera_code,action.vehicle.track_id,session.session_code,owner.session_code,runtime.vehicle_instance_id,owner.vehicle_instance_id,runtime.state,owner.status,zone.reconnect_generation,payload.get("stats",{}).get("frame_index")); continue
                    self.session_service.update_confirmed_observation(session,action.vehicle,now)
                    if action.kind=="RECOVER_SESSION": self.session_service.recover(session,action.vehicle,now,zone.reconnect_generation)
                    else: self.session_service.ensure_track(session,action.vehicle,now,zone.reconnect_generation); self.db.commit()
            elif action.kind=="PARK_END" and action.session_id:
                session=self.parking.get_session(action.session_id)
                if session:
                    exit_path=self.snapshots.save(frame,camera.camera_code,session.session_code,"exit",now); self.session_service.complete_session(session,camera_id,action.vehicle,now,exit_path)
            if action.kind=="VEHICLE_CANDIDATE" and runtime: self.log.info("Vehicle runtime created vehicle_instance_id=%s track_id=%s reason=unmatched_stable_track",runtime.vehicle_instance_id,action.vehicle.track_id)
            if action.kind=="TRACK_ASSOCIATED" and runtime: self.log.info("Track associated to existing runtime vehicle_instance_id=%s new_track=%s session=%s",runtime.vehicle_instance_id,action.vehicle.track_id,runtime.session_code)
            if action.kind=="STATE_TRANSITION" and runtime: self.log.info("Vehicle state transition camera=%s runtime=%s state=%s session=%s",camera.camera_code,runtime.runtime_id,runtime.state,runtime.session_code)
        stats=payload.get("stats",{}); open_db=len(self.parking.find_open_sessions_for_position(camera.id,camera.parking_position_code)); active_runtime=len(zone.vehicles); occupancy=zone.occupancy_snapshot(open_db); unmatched_db=occupancy.unmatched_open_session_count; stats.update({"current_track_count":sum(c.time_since_update==0 for c in candidates),"observed_vehicle_count":occupancy.observed_vehicle_count,"candidate_runtime_count":occupancy.candidate_count,"parked_runtime_count":occupancy.confirmed_occupancy_count,"leaving_runtime_count":occupancy.leaving_session_count,"recovery_pending_runtime_count":occupancy.recovery_pending_count,"open_session_count_database":open_db,"unmatched_open_session_count":unmatched_db}); inference_ms=float(stats.get("inference_ms",0)); actual_fps=1000/inference_ms if inference_ms>0 else 0; visible=sorted(zone.vehicles.values(),key=lambda v:(v.session_id is None,v.first_seen_at or now))[:3]; summary=" | ".join(f"{v.stabilized_class}:{v.state}:{v.session_code or '-'}" for v in visible) or "-"
        if unmatched_db: self.log.warning("Session runtime mismatch camera=%s tracks_in_polygon=%s active_runtime=%s open_sessions=%s unmatched_sessions=%s",camera.camera_code,len(candidates),active_runtime,open_db,unmatched_db)
        signature=(occupancy.observed_vehicle_count,occupancy.confirmed_occupancy_count,occupancy.candidate_count,occupancy.leaving_session_count,occupancy.recovery_pending_count,open_db,unmatched_db,occupancy.zone_state,occupancy.session_health_state)
        if self.last_occupancy_signature.get(camera_id)!=signature:
            self.last_occupancy_signature[camera_id]=signature; self.log.info("Zone occupancy calculated zone=%s mode=INDEPENDENT_ZONE observed=%s confirmed_occupancy=%s candidate=%s leaving=%s recovery=%s open_db=%s unmatched_open=%s capacity=%s occupancy_state=%s session_health=%s",camera.camera_code,*signature[:7],zone.capacity,occupancy.zone_state,occupancy.session_health_state)
        self.monitor.update_camera(camera_id,state=occupancy.zone_state,track=stats["current_track_count"],session=summary,vehicle=f"{occupancy.confirmed_occupancy_count}/{zone.capacity}",fps=f"{actual_fps:.2f}",raw=stats.get("raw_detections",0),detected=stats.get("vehicle_detections",0),inside=len(candidates),inference=f"{inference_ms:.1f}",tracker=stats.get("tracker_status","IDLE"),configured_preview_fps=camera.preview_fps,candidates=occupancy.candidate_count,parked=occupancy.confirmed_occupancy_count,leaving=occupancy.leaving_session_count,recovery_pending=occupancy.recovery_pending_count,open_db=open_db,observed=occupancy.observed_vehicle_count,unmatched_open=unmatched_db,session_health=occupancy.session_health_state,session_runtime_mismatch=bool(unmatched_db))
        self.log.debug("Zone aggregate camera=%s occupancy_state=%s confirmed_occupancy=%s capacity=%s candidates=%s",camera.camera_code,occupancy.zone_state,occupancy.confirmed_occupancy_count,zone.capacity,occupancy.candidate_count)
    def on_frame(self,camera_id,frame,payload):
        camera=self.cameras.get(camera_id); engine=self.engines[camera_id]; now=payload["time"]; session=self.active.get(camera_id); vehicle=payload["primary"]
        if session:
            vehicle=None
            for candidate in payload.get("polygon_candidates",[]):
                result=is_same_session_vehicle(session,candidate,now,max_anchor_distance=self.settings.session_track_match_max_anchor_distance,min_iou=self.settings.session_track_match_min_iou,min_size_ratio=self.settings.session_track_match_min_size_ratio,max_size_ratio=self.settings.session_track_match_max_size_ratio,track_lost_grace_seconds=camera.track_lost_grace_seconds,allow_stale_reconnect=engine.state in (ParkingState.CAMERA_OFFLINE,ParkingState.RECOVERY_PENDING,ParkingState.IDENTITY_UNCERTAIN))
                self.log.info("Recovery candidate evaluated session=%s candidate_track=%s match_confidence=%.3f matched=%s reason=%s class_before=%s class_after=%s class_family_match=%s anchor_distance=%.2f bbox_iou=%.3f size_ratio=%.3f appearance_similarity=%.3f",session.session_code,candidate.track_id,result.confidence,result.matched,result.reason,session.vehicle_class,candidate.vehicle_class,result.class_family_match,result.anchor_distance,result.bbox_iou,result.size_ratio,result.appearance_similarity)
                if result.matched:
                    vehicle=candidate; self.session_service.update_confirmed_observation(session,candidate,now)
                    if self.session_service.ensure_track(session,candidate,now): self.log.info("Track changed but session retained session=%s new_track=%s",session.session_code,candidate.track_id)
                    break
                self.log.info("Unrelated vehicle ignored for active session session=%s track=%s class=%s reason=%s",session.session_code,candidate.track_id,candidate.vehicle_class,result.reason)
            payload["primary"]=vehicle
        self.last_payload[camera_id]=payload
        identity_uncertain=bool(session and payload.get("polygon_candidates") and vehicle is None)
        transition=engine.update(vehicle,now,True,payload.get("monotonic_time"),identity_uncertain=identity_uncertain)
        if transition.previous!=transition.current:
            self.log.info("State transition camera=%s %s -> %s action=%s raw=%s vehicle=%s",camera.camera_code,transition.previous,transition.current,transition.action,payload.get("stats",{}).get("raw_detections",0),vehicle is not None)
        event_vehicle=transition.vehicle or vehicle
        if transition.action in ("PARK_START","PARK_START_RECOVERY") and event_vehicle:
            # entered_at is the candidate start retained by the engine.
            source="SYSTEM_RECOVERY" if transition.action=="PARK_START_RECOVERY" else "AI"; session=self.session_service.start(camera,event_vehicle,engine.candidate_since or now,now,None,None,event_source=source)
            # Phase 1 giữ frame xác nhận làm ảnh enter khi không có bộ đệm frame ứng viên.
            enter=self.snapshots.save(frame,camera.camera_code,session.session_code,"enter",engine.candidate_since or now)
            parked=self.snapshots.save(frame,camera.camera_code,session.session_code,"parked",now)
            session.enter_snapshot_path=enter; session.parked_snapshot_path=parked; self.db.commit(); self.active[camera_id]=session; self.log.info("Parking session started code=%s source=%s track=%s",session.session_code,source,event_vehicle.track_id); self.reload_history()
        elif transition.action=="RECOVER_SESSION" and session and vehicle:
            old_track=session.current_track_id; offline_seconds=max(0,(now-session.offline_started_at).total_seconds()) if session.offline_started_at else 0; self.session_service.recover(session,vehicle,now); self.log.info("Session recovered after reconnect session=%s old_track=%s new_track=%s offline_duration_seconds=%.1f",session.session_code,old_track,vehicle.track_id,offline_seconds)
        elif transition.action=="TRACK_RECOVERED" and session and vehicle:
            self.log.info("Track recovered session=%s track=%s",session.session_code,vehicle.track_id)
        elif transition.action=="TRACK_LOST" and session:
            self.log.info("Track lost session=%s",session.session_code)
        elif transition.action=="VEHICLE_CANDIDATE": self.log.info("Candidate started camera=%s track=%s",camera.camera_code,getattr(vehicle,"track_id","-"))
        elif transition.action=="CANDIDATE_CANCELLED": self.log.info("Candidate cancelled camera=%s reason=%s miss_elapsed=%.1f presence_ratio=%.2f",camera.camera_code,engine.cancel_reason,engine.candidate_miss_elapsed,engine.presence_ratio)
        elif transition.action=="VEHICLE_LEAVING" and session: self.log.info("Leaving started session=%s",session.session_code)
        elif transition.action in ("PARK_END","PARK_END_RECOVERY") and session:
            exit_path=self.snapshots.save(frame,camera.camera_code,session.session_code,"exit",now); self.session_service.complete_session(session,camera_id,transition.vehicle,now,exit_path,departure_time_uncertain=transition.action=="PARK_END_RECOVERY"); self.active.pop(camera_id,None)
        stats=payload.get("stats",{}); stats.update({"presence_ratio":engine.presence_ratio,"candidate_miss_elapsed":engine.candidate_miss_elapsed,"candidate_cancel_reason":engine.cancel_reason}); inference_ms=float(stats.get("inference_ms",0)); actual_fps=(1000/inference_ms) if inference_ms>0 else 0; state=str(transition.current); display_vehicle=vehicle or (engine.primary if engine.state in (ParkingState.VEHICLE_CANDIDATE,ParkingState.OCCUPIED,ParkingState.LEAVING,ParkingState.RECOVERY_PENDING,ParkingState.IDENTITY_UNCERTAIN) else None); self.monitor.update_camera(camera_id,state=state,track=getattr(display_vehicle,"track_id","-"),session=getattr(session,"session_code","-"),vehicle=getattr(session,"vehicle_class",getattr(display_vehicle,"vehicle_class","-")),fps=f"{actual_fps:.2f}",raw=stats.get("raw_detections",0),detected=stats.get("vehicle_detections",0),inside=stats.get("vehicles_in_polygon",0),inference=f"{inference_ms:.1f}",tracker=stats.get("tracker_status","IDLE"),configured_preview_fps=camera.preview_fps)
    def on_preview_frame(self,camera_id,frame,preview_stats):
        camera=self.cameras.get(camera_id)
        if not camera: return
        self.last_capture_frame[camera_id]=time.monotonic()
        self.raw_frames[camera_id]=frame.copy(); payload=self.last_payload.get(camera_id,{"tracks":[],"primary":None,"stats":{}}); stats=dict(payload.get("stats",{})); stats.update(preview_stats); engine=self.engines.get(camera_id)
        if engine:
            tick=time.monotonic(); stats.update({"state":str(engine.state),"candidate_elapsed":max(0,tick-engine.candidate_tick) if engine.candidate_tick is not None else 0,"candidate_miss_elapsed":engine.candidate_miss_elapsed,"presence_ratio":engine.presence_ratio,"leaving_elapsed":max(0,tick-engine.empty_tick) if engine.empty_tick is not None else 0})
            session=self.active.get(camera_id); elapsed=stats["candidate_elapsed"] if engine.state==ParkingState.VEHICLE_CANDIDATE else (seconds_between(session.parked_at,utc_now()) if session and session.parked_at else 0); self.monitor.update_elapsed(camera_id,str(engine.state),elapsed or 0)
        annotated=annotate_frame(frame,camera.polygon_points,payload.get("tracks",[]),payload.get("primary"),stats if camera.ai_debug_overlay else None,payload.get("detections",[]),camera.ignore_zones); self.frames[camera_id]=annotated
        self.monitor.update_frame(camera_id,annotated)
        dialog=self.preview_dialogs.get(camera_id)
        if dialog: dialog.update_frame(annotated)
        tick=time.monotonic()
        if camera.ai_debug_overlay and tick-self.last_preview_telemetry.get(camera_id,0)>=self.settings.telemetry_interval_seconds:
            self.last_preview_telemetry[camera_id]=tick; last_seen=max(0,tick-engine.last_vehicle_seen_tick) if engine and engine.last_vehicle_seen_tick is not None else -1; self.log.info("Pipeline telemetry camera=%s capture_timestamp=%s inference_start=%s inference_end=%s preview_display_timestamp=%.6f ai_frame_age_ms=%.1f preview_frame_age_ms=%.1f configured_preview_fps=%.2f actual_preview_fps=%.2f dropped_capture_frames=%s dropped_preview_frames=%s queue_size=%s motorcycle=%s time_since_last_detection=%.1f presence_ratio=%.2f candidate_elapsed=%.1f candidate_miss_elapsed=%.1f",camera.camera_code,stats.get("capture_timestamp"),stats.get("inference_start"),stats.get("inference_end"),preview_stats.get("preview_display_timestamp",0),float(stats.get("ai_frame_age_ms",0)),float(preview_stats.get("preview_frame_age_ms",0)),float(preview_stats.get("configured_preview_fps",camera.preview_fps)),float(preview_stats.get("actual_preview_fps",0)),stats.get("dropped_capture_frames",0),preview_stats.get("dropped_preview_frames",0),stats.get("queue_size",0),[r for r in stats.get("vehicle_results",[]) if r.get("class")=="motorcycle"],last_seen,float(stats.get("presence_ratio",0)),float(stats.get("candidate_elapsed",0)),float(stats.get("candidate_miss_elapsed",0)),extra={"telemetry":True})
    def closeEvent(self,event): self.manager.stop_all(); self.db.close(); event.accept()
