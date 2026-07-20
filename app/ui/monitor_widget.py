from PySide6.QtCore import Qt,Signal
from PySide6.QtGui import QImage,QPixmap
from PySide6.QtWidgets import QGridLayout,QGroupBox,QLabel,QPushButton,QScrollArea,QSizePolicy,QVBoxLayout,QWidget

COLORS={"EMPTY":"#78909c","VEHICLE_CANDIDATE":"#fb8c00","OCCUPIED":"#2e7d32","LEAVING":"#fbc02d","CAMERA_OFFLINE":"#c62828","UNKNOWN":"#5e35b1","CAMERA_DISABLED":"#616161","DETECTOR_ERROR":"#b71c1c"}
STATE_LABELS={"CAMERA_DISABLED":"TẮT","CAMERA_OFFLINE":"MẤT KẾT NỐI","DETECTOR_ERROR":"LỖI DETECTOR","UNKNOWN":"ĐANG KẾT NỐI","EMPTY":"EMPTY","VEHICLE_CANDIDATE":"CANDIDATE","OCCUPIED":"OCCUPIED","LEAVING":"LEAVING"}


class CameraCard(QGroupBox):
    preview_requested = Signal(int)
    def __init__(self,camera,parent=None):
        super().__init__(camera.camera_code,parent); self.camera_id=camera.id; self.started=None
        layout=QVBoxLayout(self); self.position=QLabel(f"Vị trí: {camera.parking_position_code}"); self.state=QLabel("UNKNOWN")
        self.image=QLabel("Đang chờ frame..."); self.image.setAlignment(Qt.AlignCenter); self.image.setMinimumHeight(190); self.image.setMaximumHeight(300); self.image.setSizePolicy(QSizePolicy.Expanding,QSizePolicy.Expanding); self.image.setStyleSheet("background:#101418;color:#b0bec5;border:1px solid #455a64")
        self.details=QLabel("Track: -\nSession: -\nLoại xe: -\nFPS AI: -\nPreview: 5 FPS"); self.debug=QLabel("Raw: 0 | Vehicle: 0 | Trong polygon: 0\nInference: - ms | Tracker: IDLE"); self.debug.setStyleSheet("color:#455a64;font-family:Consolas"); self.elapsed=QLabel("Thời gian đỗ: -"); self.preview=QPushButton("Mở preview"); self.preview.clicked.connect(lambda:self.preview_requested.emit(self.camera_id))
        for w in (self.position,self.state,self.image,self.details,self.debug,self.elapsed,self.preview): layout.addWidget(w)
        if camera.enabled: self.set_state("UNKNOWN")
        else: self.set_disabled()
    def set_state(self,state):
        self.state.setText(STATE_LABELS.get(state,state)); color=COLORS.get(state,"#777")
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
    def update_data(self,state,track="-",session="-",vehicle="-",fps="-",raw=0,detected=0,inside=0,inference="-",tracker="IDLE"):
        self.set_state(state); self.details.setText(f"Track: {track}\nSession: {session}\nLoại xe: {vehicle}\nFPS AI: {fps}\nPreview: 5 FPS"); warning="FRAME_DELAY | " if tracker=="FRAME_DELAY" else ""; self.debug.setText(f"{warning}Raw: {raw} | Vehicle: {detected} | Trong polygon: {inside}\nInference: {inference} ms | Tracker: {tracker}"); self.debug.setStyleSheet("color:#d50000;font-weight:800;font-family:Consolas" if tracker=="FRAME_DELAY" else "color:#455a64;font-family:Consolas")
    def update_frame(self,frame):
        if frame is None or not self.preview.isEnabled(): return
        h,w=frame.shape[:2]; image=QImage(frame.data,w,h,frame.strides[0],QImage.Format_BGR888).copy()
        self.image.setPixmap(QPixmap.fromImage(image).scaled(self.image.size(),Qt.KeepAspectRatio,Qt.SmoothTransformation))


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
