from PySide6.QtCore import Qt
from PySide6.QtGui import QImage,QPixmap
from PySide6.QtWidgets import QDialog,QLabel,QVBoxLayout


class PreviewDialog(QDialog):
    def __init__(self,camera,parent=None):
        super().__init__(parent); self.camera_id=camera.id; self.setWindowTitle(f"Preview - {camera.camera_code} / {camera.parking_position_code}"); self.resize(1100,700)
        layout=QVBoxLayout(self); self.image=QLabel("Đang chờ frame từ camera..."); self.image.setAlignment(Qt.AlignCenter); self.image.setStyleSheet("background:#0b0f12;color:white"); layout.addWidget(self.image)
        self.info=QLabel("Polygon: xanh lá | Xe: vàng | Xe chính: đỏ"); layout.addWidget(self.info)
    def update_frame(self,frame):
        if frame is None or not self.isVisible(): return
        h,w=frame.shape[:2]; image=QImage(frame.data,w,h,frame.strides[0],QImage.Format_BGR888).copy()
        self.image.setPixmap(QPixmap.fromImage(image).scaled(self.image.size(),Qt.KeepAspectRatio,Qt.SmoothTransformation))

