from __future__ import annotations

from PySide6.QtCore import Qt,QSize
from PySide6.QtGui import QImage,QKeyEvent,QMouseEvent,QPixmap
from PySide6.QtWidgets import QApplication,QDialog,QLabel,QSizePolicy,QVBoxLayout


class VideoCanvas(QLabel):
    """Canvas co giãn, chỉ giữ frame gốc mới nhất và không tạo queue ảnh."""

    def __init__(self,parent=None):
        super().__init__("Đang chờ frame từ camera...",parent)
        self._latest_image: QImage | None=None
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setSizePolicy(QSizePolicy.Policy.Expanding,QSizePolicy.Policy.Expanding)
        self.setMinimumSize(640,360)
        self.setStyleSheet("background-color:black;color:white")

    def sizeHint(self): return QSize(960,540)

    def set_frame(self,frame):
        if frame is None: return
        height,width=frame.shape[:2]
        self._latest_image=QImage(frame.data,width,height,frame.strides[0],QImage.Format.Format_BGR888).copy()
        self.render_latest_frame()

    def render_latest_frame(self):
        if self._latest_image is None or self.width()<=0 or self.height()<=0: return
        pixmap=QPixmap.fromImage(self._latest_image).scaled(self.size(),Qt.AspectRatioMode.KeepAspectRatio,Qt.TransformationMode.SmoothTransformation)
        self.setPixmap(pixmap)

    def resizeEvent(self,event):
        super().resizeEvent(event); self.render_latest_frame()

    @property
    def latest_image(self): return self._latest_image


class PreviewDialog(QDialog):
    def __init__(self,camera,parent=None):
        super().__init__(parent); self.camera_id=camera.id; self.setWindowTitle(f"Preview - {camera.camera_code} / {camera.parking_position_code}"); self.setMinimumSize(900,600)
        screen=QApplication.primaryScreen()
        if screen:
            available=screen.availableGeometry(); self.resize(min(available.width(),max(900,round(available.width()*.85))),min(available.height(),max(600,round(available.height()*.85))))
        else: self.resize(1100,700)
        layout=QVBoxLayout(self); layout.setContentsMargins(8,8,8,8); layout.setSpacing(6)
        self.video_canvas=VideoCanvas(self); self.image=self.video_canvas
        self.info=QLabel("Polygon: xanh lá | Candidate: vàng | Session đã xác nhận: đỏ | Identity uncertain: cam")
        self.info.setSizePolicy(QSizePolicy.Policy.Preferred,QSizePolicy.Policy.Fixed)
        layout.addWidget(self.video_canvas,1); layout.addWidget(self.info,0)

    def update_frame(self,frame):
        if frame is None: return
        self.video_canvas.set_frame(frame)

    def mouseDoubleClickEvent(self,event: QMouseEvent):
        if event.button()==Qt.MouseButton.LeftButton:
            self.showNormal() if self.isFullScreen() else self.showFullScreen(); event.accept(); return
        super().mouseDoubleClickEvent(event)

    def keyPressEvent(self,event: QKeyEvent):
        if event.key()==Qt.Key.Key_Escape and self.isFullScreen(): self.showNormal(); event.accept(); return
        super().keyPressEvent(event)
