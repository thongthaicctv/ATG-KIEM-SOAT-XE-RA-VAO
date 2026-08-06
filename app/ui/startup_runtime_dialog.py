from __future__ import annotations

import platform, sqlite3, sys
from pathlib import Path
from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout,
    QLabel, QMessageBox, QPushButton, QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout)

from app.core.runtime_config import RuntimeConfig


def hardware_summary() -> dict[str, str]:
    result={"Python":f"{sys.executable} ({platform.python_version()})","Torch":"-","CUDA build":"-","CUDA available":"False","GPU":"-","VRAM":"-"}
    try:
        import torch
        result.update({"Torch":str(torch.__version__),"CUDA build":str(torch.version.cuda),"CUDA available":str(torch.cuda.is_available())})
        if torch.cuda.is_available():
            p=torch.cuda.get_device_properties(0); result.update(GPU=p.name,VRAM=f"{p.total_memory/1073741824:.1f} GB")
    except Exception: pass
    return result


class StartupRuntimeDialog(QDialog):
    def __init__(self,root: Path,parent=None):
        super().__init__(parent); self.root=root; self.result_config=None; self.settings=QSettings("ParkingMonitoring","StartupRuntime")
        self.setWindowTitle("CẤU HÌNH KHỞI ĐỘNG PARKING MONITOR"); self.resize(1050,720); layout=QVBoxLayout(self)
        info=QLabel(" | ".join(f"{k}: {v}" for k,v in hardware_summary().items())); info.setWordWrap(True); layout.addWidget(info)
        form=QFormLayout(); self.mode=QComboBox(); self.mode.addItems(["normal","debug","benchmark"]); self.mode.setCurrentText(self.settings.value("mode","debug")); self.device=QComboBox(); self.device.addItems(["auto","cpu","cuda:0"]); self.device.setCurrentText(self.settings.value("device","auto")); self.maximum=QSpinBox(); self.maximum.setRange(1,99); self.maximum.setValue(int(self.settings.value("max_cameras",2))); self.fallback=QComboBox(); self.fallback.addItems(["1","2"])
        form.addRow("Chế độ",self.mode); form.addRow("Device",self.device); form.addRow("Số camera tối đa",self.maximum); form.addRow("Fallback tối thiểu",self.fallback); layout.addLayout(form)
        filters=QHBoxLayout(); self.filter=QComboBox(); self.filter.addItems(["Tất cả","CAR_ZONE","MOTORCYCLE_ZONE","Camera đang bật","Có polygon hợp lệ"]); self.filter.currentTextChanged.connect(self.load_cameras); filters.addWidget(QLabel("Lọc:")); filters.addWidget(self.filter); filters.addStretch(); layout.addLayout(filters)
        headers=["Chọn","Mã camera","Tên","Vị trí","Khu vực","Sức chứa","Enabled","AI FPS","Preview FPS","Image size","Polygon","Ignore Zone","RTSP"]
        self.table=QTableWidget(0,len(headers)); self.table.setHorizontalHeaderLabels(headers); layout.addWidget(self.table); self.load_cameras()
        quick=QHBoxLayout()
        for label,count in [("Chạy 1 camera",1),("Chạy 2 camera",2),("Chọn nhiều camera",0)]:
            b=QPushButton(label); b.clicked.connect(lambda _=False,n=count:self.quick(n)); quick.addWidget(b)
        benchmark=QPushButton("Benchmark tự động"); benchmark.clicked.connect(self.quick_benchmark); quick.addWidget(benchmark)
        normal=QPushButton("Chạy cấu hình bình thường"); normal.clicked.connect(self.quick_normal); quick.addWidget(normal); layout.addLayout(quick)
        buttons=QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel); buttons.accepted.connect(self.accept_config); buttons.rejected.connect(self.reject); layout.addWidget(buttons)

    def load_cameras(self):
        selected={self.table.item(r,1).text() for r in range(self.table.rowCount()) if self.table.item(r,0) and self.table.item(r,0).checkState()==Qt.Checked}
        db=self.root/"data"/"parking.db"; rows=[]
        if db.exists():
            con=sqlite3.connect(db); con.row_factory=sqlite3.Row
            try: rows=con.execute("SELECT * FROM cameras ORDER BY camera_code").fetchall()
            finally: con.close()
        mode=self.filter.currentText(); filtered=[]
        for c in rows:
            valid=c["zone_type"] in ("CAR_ZONE","MOTORCYCLE_ZONE") and bool(c["rtsp_url"]) and bool(c["polygon_points"])
            if mode in ("CAR_ZONE","MOTORCYCLE_ZONE") and c["zone_type"]!=mode: continue
            if mode=="Camera đang bật" and not c["enabled"]: continue
            if mode=="Có polygon hợp lệ" and not valid: continue
            filtered.append((c,valid))
        self.table.setRowCount(len(filtered))
        for r,(c,valid) in enumerate(filtered):
            check=QTableWidgetItem(); check.setFlags(Qt.ItemIsEnabled|Qt.ItemIsUserCheckable); check.setCheckState(Qt.Checked if c["camera_code"] in selected else Qt.Unchecked); check.setToolTip("Camera thiếu RTSP/polygon/zone_type" if not valid else "")
            if not valid: check.setFlags(Qt.NoItemFlags)
            self.table.setItem(r,0,check)
            vals=[c["camera_code"],c["camera_name"],c["parking_position_code"],c["zone_type"],c["capacity"],bool(c["enabled"]),c["processing_fps"],c["preview_fps"],c["detector_image_size"],"Có" if c["polygon_points"] else "Không","Có" if c["ignore_zones"] else "Không",c["status"]]
            for col,val in enumerate(vals,1): self.table.setItem(r,col,QTableWidgetItem(str(val)))

    def selected_codes(self): return [self.table.item(r,1).text() for r in range(self.table.rowCount()) if self.table.item(r,0).checkState()==Qt.Checked]
    def quick(self,count): self.mode.setCurrentText("debug"); self.maximum.setValue(count or max(1,len(self.selected_codes()))); self.accept_config()
    def quick_benchmark(self): self.mode.setCurrentText("benchmark"); self.accept_config(auto_scale=True)
    def quick_normal(self): self.mode.setCurrentText("normal"); self.accept_config()
    def accept_config(self,auto_scale=False):
        codes=tuple(self.selected_codes()); mode=self.mode.currentText()
        if mode!="normal" and not codes: QMessageBox.warning(self,"Chưa chọn camera","Hãy chọn ít nhất một camera hợp lệ."); return
        if mode!="normal" and len(codes)>self.maximum.value(): QMessageBox.warning(self,"Quá số lượng",f"Đã chọn {len(codes)} camera nhưng giới hạn là {self.maximum.value()}."); return
        self.settings.setValue("mode",mode); self.settings.setValue("device",self.device.currentText()); self.settings.setValue("max_cameras",self.maximum.value())
        self.result_config=RuntimeConfig(mode,self.device.currentText(),self.maximum.value(),codes,None,int(self.fallback.currentText()),auto_scale or mode=="benchmark",180,True); self.accept()
