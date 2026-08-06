from PySide6.QtCore import Qt,Signal
from PySide6.QtGui import QImage,QPixmap
from PySide6.QtWidgets import QGridLayout,QGroupBox,QLabel,QPushButton,QScrollArea,QSizePolicy,QVBoxLayout,QWidget

COLORS={"FULL":"#d84315","OVER_CAPACITY":"#b71c1c","EMPTY":"#78909c","VEHICLE_CANDIDATE":"#fb8c00","OCCUPIED":"#2e7d32","LEAVING":"#fbc02d","CAMERA_OFFLINE":"#c62828","RECOVERY_PENDING":"#1565c0","IDENTITY_UNCERTAIN":"#ef6c00","UNKNOWN":"#5e35b1","CAMERA_DISABLED":"#616161","DETECTOR_ERROR":"#b71c1c"}
COLORS.update({"RTSP_CONNECTING":"#5e35b1","AI_INITIALIZING":"#1565c0","AI_SESSION_ERROR":"#b71c1c","AI_SESSION_RECOVERY":"#ef6c00","ONLINE":"#2e7d32"})
STATE_LABELS={"CAMERA_DISABLED":"TẮT","CAMERA_OFFLINE":"MẤT KẾT NỐI","RECOVERY_PENDING":"ĐANG ĐỐI CHIẾU XE","IDENTITY_UNCERTAIN":"KHÔNG CHẮC DANH TÍNH XE","DETECTOR_ERROR":"LỖI DETECTOR","UNKNOWN":"ĐANG KẾT NỐI","EMPTY":"EMPTY","VEHICLE_CANDIDATE":"CANDIDATE","OCCUPIED":"OCCUPIED","LEAVING":"LEAVING"}

STATE_LABELS.update({"FULL":"FULL","OVER_CAPACITY":"VƯỢT SỨC CHỨA"})
STATE_LABELS.update({"RTSP_CONNECTING":"ĐANG KẾT NỐI RTSP","AI_INITIALIZING":"ĐANG KHỞI TẠO AI","AI_SESSION_ERROR":"LỖI LIÊN KẾT PHIÊN","AI_SESSION_RECOVERY":"ĐANG KHÔI PHỤC PHIÊN","ONLINE":"ONLINE"})

def format_elapsed_seconds(value):
    total=max(0,int(value or 0)); hours,remainder=divmod(total,3600); minutes,seconds=divmod(remainder,60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


class CameraCard(QGroupBox):
    preview_requested = Signal(int)
    def __init__(self,camera,parent=None):
        super().__init__(camera.camera_code,parent); self.camera_id=camera.id; self.started=None
        self.setToolTip(f"{getattr(camera,'zone_type','LEGACY_UNSET')} | Sức chứa: {getattr(camera,'capacity',1)}")
        layout=QVBoxLayout(self); self.position=QLabel(f"Vị trí: {camera.parking_position_code}"); self.state=QLabel("UNKNOWN")
        self.image=QLabel("Đang chờ frame..."); self.image.setAlignment(Qt.AlignCenter); self.image.setMinimumHeight(190); self.image.setMaximumHeight(300); self.image.setSizePolicy(QSizePolicy.Expanding,QSizePolicy.Expanding); self.image.setStyleSheet("background:#101418;color:#b0bec5;border:1px solid #455a64"); self.recovery_note=QLabel(""); self.recovery_note.setStyleSheet("color:#ef6c00;font-weight:600")
        self.preview_fps=float(camera.preview_fps); self.details=QLabel(f"Track: -\nSession: -\nLoại xe: -\nFPS AI: -\nPreview: {self.preview_fps:g} FPS"); self.debug=QLabel("Raw: 0 | Vehicle: 0 | Trong polygon: 0\nInference: - ms | Tracker: IDLE"); self.debug.setStyleSheet("color:#455a64;font-family:Consolas"); self.elapsed=QLabel("Thời gian đỗ: -"); self.preview=QPushButton("Mở preview"); self.preview.clicked.connect(lambda:self.preview_requested.emit(self.camera_id))
        for w in (self.position,self.state,self.recovery_note,self.image,self.details,self.debug,self.elapsed,self.preview): layout.addWidget(w)
        if camera.enabled: self.set_state("UNKNOWN")
        else: self.set_disabled()
    def set_state(self,state):
        self.state.setText(STATE_LABELS.get(state,state)); color=COLORS.get(state,"#777")
        notes={"CAMERA_OFFLINE":"Phiên đang được tạm giữ","RECOVERY_PENDING":"Đang đối chiếu xe sau reconnect","IDENTITY_UNCERTAIN":"Cần tiếp tục đối chiếu; chưa tạo phiên mới","OCCUPIED":"Khôi phục/đang giữ phiên hiện tại"}; self.recovery_note.setText(notes.get(state,""))
        self.setStyleSheet(f"QGroupBox{{border:2px solid {color};border-radius:6px;margin-top:8px}} QGroupBox::title{{subcontrol-origin:margin;left:8px}}")
        if state in ("CAMERA_OFFLINE","DETECTOR_ERROR"):
            self.state.setStyleSheet("color:#d50000;font-size:22px;font-weight:800;padding:6px 0")
            if state=="CAMERA_OFFLINE":
                self.image.clear(); self.image.setText("MẤT KẾT NỐI CAMERA"); self.preview.setEnabled(False); self.preview.setToolTip("Camera đang mất kết nối; hệ thống đang tự kết nối lại")
            self.image.setStyleSheet("background:#fff5f5;color:#d50000;border:3px solid #d50000;font-size:24px;font-weight:800")
        elif state!="CAMERA_DISABLED":
            self.state.setStyleSheet("font-size:14px;font-weight:600;padding:2px 0")
            self.image.setStyleSheet("background:#101418;color:#b0bec5;border:1px solid #455a64")
            self.preview.setEnabled(True); self.preview.setToolTip("")
    def set_disabled(self):
        self.set_state("CAMERA_DISABLED"); self.image.clear(); self.image.setText("Camera đã tắt trong cấu hình"); self.details.setText("Track: -\nSession: -\nLoại xe: -\nFPS AI: -\nPreview: Tắt"); self.preview.setEnabled(False); self.preview.setToolTip("Hãy bật camera trong trang Camera để xem preview")
    def update_data(self,state,track="-",session="-",vehicle="-",fps="-",raw=0,detected=0,inside=0,inference="-",tracker="IDLE",configured_preview_fps=None,candidates=None,parked=None,leaving=None,recovery_pending=None,open_db=None,observed=None,unmatched_open=None,session_health="OK",session_runtime_mismatch=False):
        if configured_preview_fps is not None: self.preview_fps=float(configured_preview_fps)
        self.set_state(state); self.details.setText(f"Track hiện tại: {track}\nSession: {session}\nXe đang chiếm chỗ: {vehicle}\nFPS AI: {fps}\nPreview: {self.preview_fps:g} FPS"); warning="FRAME_DELAY | " if tracker=="FRAME_DELAY" else ""; runtime_line=f"\nQuan sát hiện tại: {observed} | Candidate: {candidates} | Đang xác nhận rời: {leaving}\nRecovery: {recovery_pending} | Open DB: {open_db} | Session chưa đối chiếu: {unmatched_open}" if candidates is not None else ""; mismatch=f"\nSession health: {session_health}" if session_runtime_mismatch or session_health!="OK" else ""; self.debug.setText(f"{warning}Raw: {raw} | Vehicle: {detected} | Trong polygon: {inside}\nInference: {inference} ms | Tracker: {tracker}{runtime_line}{mismatch}"); self.debug.setStyleSheet("color:#d50000;font-weight:800;font-family:Consolas" if tracker=="FRAME_DELAY" or session_runtime_mismatch else "color:#455a64;font-family:Consolas")
    def update_frame(self,frame):
        if frame is None or not self.preview.isEnabled(): return
        h,w=frame.shape[:2]; image=QImage(frame.data,w,h,frame.strides[0],QImage.Format_BGR888).copy()
        self.image.setPixmap(QPixmap.fromImage(image).scaled(self.image.size(),Qt.KeepAspectRatio,Qt.SmoothTransformation))
    def set_preview_fps(self,value):
        self.preview_fps=float(value); lines=self.details.text().splitlines()
        if lines: lines[-1]=f"Preview: {self.preview_fps:g} FPS"; self.details.setText("\n".join(lines))
    def update_elapsed(self,state,seconds):
        if state=="VEHICLE_CANDIDATE": self.elapsed.setText(f"Thời gian dừng: {format_elapsed_seconds(seconds)} (đang xác nhận)")
        elif state in ("OCCUPIED","LEAVING","CAMERA_OFFLINE","RECOVERY_PENDING","IDENTITY_UNCERTAIN"): self.elapsed.setText(f"Thời gian đỗ: {format_elapsed_seconds(seconds)}")
        else: self.elapsed.setText("Thời gian đỗ: -")


class MonitorWidget(QWidget):
    preview_requested=Signal(int)
    def __init__(self,parent=None):
        super().__init__(parent); outer=QVBoxLayout(self); scroll=QScrollArea(); scroll.setWidgetResizable(True); self.container=QWidget(); self.grid=QGridLayout(self.container); scroll.setWidget(self.container); outer.addWidget(scroll); self.cards={}
    def set_cameras(self,cameras):
        while self.grid.count():
            item=self.grid.takeAt(0)
            if item.widget(): item.widget().deleteLater()
        self.cards={}
        for i,camera in enumerate(cameras):
            card=CameraCard(camera); card.preview_requested.connect(self.preview_requested); self.cards[camera.id]=card; self.grid.addWidget(card,i//3,i%3)
    def update_camera(self,camera_id,**values):
        if camera_id in self.cards: self.cards[camera_id].update_data(**values)
    def update_frame(self,camera_id,frame):
        if camera_id in self.cards: self.cards[camera_id].update_frame(frame)
    def set_preview_fps(self,camera_id,value):
        if camera_id in self.cards: self.cards[camera_id].set_preview_fps(value)
    def update_elapsed(self,camera_id,state,seconds):
        if camera_id in self.cards: self.cards[camera_id].update_elapsed(state,seconds)
