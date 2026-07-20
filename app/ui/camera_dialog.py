from PySide6.QtWidgets import QCheckBox,QComboBox,QDialog,QDialogButtonBox,QDoubleSpinBox,QFormLayout,QLineEdit,QMessageBox,QSpinBox


class CameraDialog(QDialog):
    def __init__(self,camera=None,parent=None):
        super().__init__(parent); self.setWindowTitle("Thêm camera" if camera is None else "Sửa camera")
        self.resize(600, 680)
        self.setMinimumWidth(520)
        form=QFormLayout(self)
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        self.code=QLineEdit(); self.name=QLineEdit(); self.position=QLineEdit(); self.url=QLineEdit()
        for field in (self.code, self.name, self.position, self.url):
            field.setMinimumWidth(340)
        self.url.setPlaceholderText("rtsp://user:password@host:port/path")
        self.fps=QDoubleSpinBox(); self.fps.setRange(.1,60); self.conf=QDoubleSpinBox(); self.conf.setRange(.01,1); self.conf.setSingleStep(.05)
        self.park=QSpinBox(); self.park.setRange(1,3600); self.exit=QSpinBox(); self.exit.setRange(1,600); self.grace=QSpinBox(); self.grace.setRange(1,600); self.miss_grace=QSpinBox(); self.miss_grace.setRange(1,60); self.imgsz=QComboBox(); [self.imgsz.addItem(str(v),v) for v in (640,768,960,1280)]; self.overlap=QDoubleSpinBox(); self.overlap.setRange(.01,1); self.overlap.setSingleStep(.05); self.motorcycles=QCheckBox("Nhận diện xe máy"); self.roi=QCheckBox("Crop ROI polygon (+10%)"); self.debug_overlay=QCheckBox("Hiện AI debug overlay"); self.rotation=QComboBox(); self.rotation.addItem("Không xoay",0); self.rotation.addItem("90° theo chiều kim đồng hồ",90); self.rotation.addItem("180°",180); self.rotation.addItem("90° ngược chiều kim đồng hồ",270); self.enabled=QCheckBox("Bật camera")
        for label,w in [("Mã camera*",self.code),("Tên camera*",self.name),("Mã vị trí*",self.position),("RTSP URL*",self.url),("FPS AI",self.fps),("Confidence",self.conf),("Detector image size",self.imgsz),("Ngưỡng giao polygon",self.overlap),("",self.motorcycles),("",self.roi),("",self.debug_overlay),("Xác nhận đỗ (giây)",self.park),("Xác nhận rời (giây)",self.exit),("Giữ track mất (giây)",self.grace),("Grace mất detection (giây)",self.miss_grace),("Xoay hình",self.rotation),("",self.enabled)]: form.addRow(label,w)
        buttons=QDialogButtonBox(QDialogButtonBox.Save|QDialogButtonBox.Cancel); buttons.accepted.connect(self.accept); buttons.rejected.connect(self.reject); form.addRow(buttons)
        self.fps.setValue(8); self.conf.setValue(.20); self.imgsz.setCurrentIndex(self.imgsz.findData(960)); self.overlap.setValue(.20); self.motorcycles.setChecked(True); self.roi.setChecked(True); self.debug_overlay.setChecked(True); self.park.setValue(5); self.exit.setValue(2); self.grace.setValue(3); self.miss_grace.setValue(5); self.enabled.setChecked(True)
        if camera:
            self.code.setText(camera.camera_code); self.name.setText(camera.camera_name); self.position.setText(camera.parking_position_code); self.url.setText(camera.rtsp_url); self.fps.setValue(camera.processing_fps); self.conf.setValue(camera.vehicle_confidence); self.imgsz.setCurrentIndex(max(0,self.imgsz.findData(camera.detector_image_size))); self.overlap.setValue(camera.vehicle_polygon_overlap_threshold); self.motorcycles.setChecked(camera.enable_motorcycles); self.roi.setChecked(camera.use_polygon_roi); self.debug_overlay.setChecked(camera.ai_debug_overlay); self.park.setValue(int(camera.parking_confirm_seconds)); self.exit.setValue(int(camera.exit_confirm_seconds)); self.grace.setValue(int(camera.track_lost_grace_seconds)); self.miss_grace.setValue(int(camera.detection_miss_grace_seconds)); self.rotation.setCurrentIndex(max(0,self.rotation.findData(camera.rotation_degrees))); self.enabled.setChecked(camera.enabled)
    def accept(self):
        if not all(x.text().strip() for x in (self.code,self.name,self.position,self.url)): QMessageBox.warning(self,"Thiếu dữ liệu","Vui lòng nhập đủ các trường bắt buộc."); return
        super().accept()
    def values(self):
        return dict(camera_code=self.code.text().strip(),camera_name=self.name.text().strip(),parking_position_code=self.position.text().strip(),rtsp_url=self.url.text().strip(),enabled=self.enabled.isChecked(),processing_fps=self.fps.value(),vehicle_confidence=self.conf.value(),enable_motorcycles=self.motorcycles.isChecked(),detector_image_size=int(self.imgsz.currentData()),use_polygon_roi=self.roi.isChecked(),vehicle_polygon_overlap_threshold=self.overlap.value(),ai_debug_overlay=self.debug_overlay.isChecked(),parking_confirm_seconds=self.park.value(),exit_confirm_seconds=self.exit.value(),track_lost_grace_seconds=self.grace.value(),detection_miss_grace_seconds=self.miss_grace.value(),rotation_degrees=int(self.rotation.currentData()))
