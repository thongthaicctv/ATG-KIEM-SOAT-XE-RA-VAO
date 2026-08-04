from PySide6.QtCore import QPointF,Qt,Signal
from PySide6.QtGui import QColor,QImage,QPainter,QPen,QPixmap
from PySide6.QtWidgets import QComboBox,QDialog,QHBoxLayout,QLabel,QMessageBox,QPushButton,QVBoxLayout
from app.utils.geometry import normalize_points,polygon_is_valid


class PolygonCanvas(QLabel):
    changed=Signal()
    def __init__(self,frame,parent=None):
        super().__init__(parent); self.frame=frame; self.main_points=[]; self.ignore_zones=[]; self.mode="MAIN"; self.selected_ignore=-1; self.drag=-1; h,w=frame.shape[:2]; self.source=QPixmap.fromImage(QImage(frame.data,w,h,frame.strides[0],QImage.Format_BGR888).copy()); self.setMinimumSize(640,360); self.setAlignment(Qt.AlignCenter)
    @property
    def points(self):
        if self.mode=="IGNORE" and self.selected_ignore>=0: return self.ignore_zones[self.selected_ignore]["points"]
        return self.main_points
    def _transform(self):
        pix=self.source.scaled(self.size(),Qt.KeepAspectRatio,Qt.SmoothTransformation); return pix,(self.width()-pix.width())/2,(self.height()-pix.height())/2
    def _draw_polygon(self,painter,points,color,pix,ox,oy):
        sx=pix.width()/self.source.width(); sy=pix.height()/self.source.height(); mapped=[QPointF(ox+x*sx,oy+y*sy) for x,y in points]; painter.setPen(QPen(QColor(color),3))
        if len(mapped)>1:
            for index in range(len(mapped)-1): painter.drawLine(mapped[index],mapped[index+1])
            if len(mapped)>2: painter.drawLine(mapped[-1],mapped[0])
        painter.setBrush(QColor(color))
        for point in mapped: painter.drawEllipse(point,5,5)
    def paintEvent(self,event):
        super().paintEvent(event); painter=QPainter(self); pix,ox,oy=self._transform(); painter.drawPixmap(int(ox),int(oy),pix); self._draw_polygon(painter,self.main_points,"#00e676",pix,ox,oy)
        for zone in self.ignore_zones:
            if zone.get("enabled",True): self._draw_polygon(painter,zone["points"],"#9c27b0",pix,ox,oy)
    def _source_pos(self,pos):
        pix,ox,oy=self._transform(); return ((pos.x()-ox)*self.source.width()/pix.width(),(pos.y()-oy)*self.source.height()/pix.height())
    def mousePressEvent(self,event):
        points=self.points; x,y=self._source_pos(event.position()); self.drag=next((i for i,(px,py) in enumerate(points) if (px-x)**2+(py-y)**2<200),-1)
        if self.drag<0: points.append((x,y)); self.drag=len(points)-1
        self.changed.emit(); self.update()
    def mouseMoveEvent(self,event):
        if self.drag>=0:
            x,y=self._source_pos(event.position()); self.points[self.drag]=(max(0,min(self.source.width(),x)),max(0,min(self.source.height(),y))); self.changed.emit(); self.update()
    def mouseReleaseEvent(self,event): self.drag=-1


class PolygonEditor(QDialog):
    def __init__(self,frame,normalized=None,parent=None,ignore_zones=None):
        super().__init__(parent); self.setWindowTitle("Vùng giám sát và Ignore Zone"); self.resize(1000,700); layout=QVBoxLayout(self); self.canvas=PolygonCanvas(frame); layout.addWidget(self.canvas,1); controls=QHBoxLayout(); self.mode=QComboBox(); self.mode.addItem("Vùng giám sát chính","MAIN"); self.mode.addItem("Vùng loại trừ","IGNORE"); add_ignore=QPushButton("Thêm Ignore Zone"); delete_ignore=QPushButton("Xóa Ignore Zone"); toggle_ignore=QPushButton("Bật/tắt Ignore Zone"); clear=QPushButton("Xóa vùng đang vẽ"); [controls.addWidget(w) for w in (self.mode,add_ignore,delete_ignore,toggle_ignore,clear)]; layout.addLayout(controls); self.info=QLabel(); layout.addWidget(self.info); buttons=QHBoxLayout(); save=QPushButton("Lưu"); cancel=QPushButton("Hủy"); buttons.addStretch(); buttons.addWidget(save); buttons.addWidget(cancel); layout.addLayout(buttons)
        h,w=frame.shape[:2]; self.canvas.main_points=[(x*w,y*h) for x,y in normalized or []]; self.canvas.ignore_zones=[{"points":[(x*w,y*h) for x,y in z.get("points",[])],"enabled":z.get("enabled",True)} for z in ignore_zones or []]
        self.mode.currentIndexChanged.connect(self._mode_changed); add_ignore.clicked.connect(self._add_ignore); delete_ignore.clicked.connect(self._delete_ignore); toggle_ignore.clicked.connect(self._toggle_ignore); clear.clicked.connect(self._clear); self.canvas.changed.connect(self.refresh); save.clicked.connect(self.accept); cancel.clicked.connect(self.reject); self.refresh()
    def _mode_changed(self): self.canvas.mode=self.mode.currentData(); self.canvas.selected_ignore=len(self.canvas.ignore_zones)-1 if self.canvas.mode=="IGNORE" and self.canvas.ignore_zones else -1; self.canvas.update(); self.refresh()
    def _add_ignore(self): self.canvas.ignore_zones.append({"points":[],"enabled":True}); self.canvas.mode="IGNORE"; self.canvas.selected_ignore=len(self.canvas.ignore_zones)-1; self.mode.setCurrentIndex(1); self.refresh()
    def _delete_ignore(self):
        if self.canvas.selected_ignore>=0: self.canvas.ignore_zones.pop(self.canvas.selected_ignore); self.canvas.selected_ignore=len(self.canvas.ignore_zones)-1; self.canvas.update(); self.refresh()
    def _toggle_ignore(self):
        if self.canvas.selected_ignore>=0: zone=self.canvas.ignore_zones[self.canvas.selected_ignore]; zone["enabled"]=not zone.get("enabled",True); self.canvas.update(); self.refresh()
    def _clear(self): self.canvas.points.clear(); self.canvas.update(); self.refresh()
    def refresh(self): self.info.setText(f"Vùng chính: {len(self.canvas.main_points)} điểm | Ignore Zones: {len(self.canvas.ignore_zones)} | Chế độ: {self.canvas.mode}")
    def accept(self):
        if not polygon_is_valid(self.canvas.main_points): QMessageBox.warning(self,"Polygon không hợp lệ","Vùng giám sát chính cần ít nhất 3 điểm và không tự cắt."); return
        if any(zone.get("enabled",True) and not polygon_is_valid(zone["points"]) for zone in self.canvas.ignore_zones): QMessageBox.warning(self,"Ignore Zone không hợp lệ","Mỗi Ignore Zone đang bật cần ít nhất 3 điểm."); return
        super().accept()
    def normalized_points(self):
        h,w=self.canvas.frame.shape[:2]; return [list(p) for p in normalize_points(self.canvas.main_points,w,h)]
    def normalized_ignore_zones(self):
        h,w=self.canvas.frame.shape[:2]; return [{"points":[list(p) for p in normalize_points(zone["points"],w,h)],"enabled":zone.get("enabled",True)} for zone in self.canvas.ignore_zones]
