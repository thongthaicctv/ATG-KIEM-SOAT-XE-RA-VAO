from PySide6.QtCore import QPointF,Qt,Signal
from PySide6.QtGui import QColor,QImage,QPainter,QPen,QPixmap
from PySide6.QtWidgets import QDialog,QHBoxLayout,QLabel,QMessageBox,QPushButton,QVBoxLayout
from app.utils.geometry import normalize_points,polygon_is_valid


class PolygonCanvas(QLabel):
    changed=Signal()
    def __init__(self,frame,parent=None):
        super().__init__(parent); self.frame=frame; self.points=[]; self.drag=-1; h,w=frame.shape[:2]; image=QImage(frame.data,w,h,frame.strides[0],QImage.Format_BGR888); self.source=QPixmap.fromImage(image.copy()); self.setMinimumSize(640,360); self.setAlignment(Qt.AlignCenter)
    def _transform(self):
        pix=self.source.scaled(self.size(),Qt.KeepAspectRatio,Qt.SmoothTransformation); ox=(self.width()-pix.width())/2; oy=(self.height()-pix.height())/2; return pix,ox,oy
    def paintEvent(self,e):
        super().paintEvent(e); p=QPainter(self); pix,ox,oy=self._transform(); p.drawPixmap(int(ox),int(oy),pix); sx=pix.width()/self.source.width(); sy=pix.height()/self.source.height(); pts=[QPointF(ox+x*sx,oy+y*sy) for x,y in self.points]
        p.setPen(QPen(QColor("#00e676"),3));
        if len(pts)>1:
            for i in range(len(pts)-1): p.drawLine(pts[i],pts[i+1])
            if len(pts)>2: p.drawLine(pts[-1],pts[0])
        p.setBrush(QColor("#ffca28"));
        for q in pts: p.drawEllipse(q,6,6)
    def _source_pos(self,pos):
        pix,ox,oy=self._transform(); return ((pos.x()-ox)*self.source.width()/pix.width(),(pos.y()-oy)*self.source.height()/pix.height())
    def mousePressEvent(self,e):
        x,y=self._source_pos(e.position()); self.drag=next((i for i,(px,py) in enumerate(self.points) if (px-x)**2+(py-y)**2<200),-1)
        if self.drag<0: self.points.append((x,y)); self.drag=len(self.points)-1
        self.changed.emit(); self.update()
    def mouseMoveEvent(self,e):
        if self.drag>=0:
            x,y=self._source_pos(e.position()); self.points[self.drag]=(max(0,min(self.source.width(),x)),max(0,min(self.source.height(),y))); self.changed.emit(); self.update()
    def mouseReleaseEvent(self,e): self.drag=-1


class PolygonEditor(QDialog):
    def __init__(self,frame,normalized=None,parent=None):
        super().__init__(parent); self.setWindowTitle("Chỉnh sửa polygon"); self.resize(900,650); layout=QVBoxLayout(self); self.canvas=PolygonCanvas(frame); layout.addWidget(self.canvas,1); self.info=QLabel(); layout.addWidget(self.info); buttons=QHBoxLayout(); clear=QPushButton("Xóa / Vẽ lại"); save=QPushButton("Lưu"); cancel=QPushButton("Hủy"); buttons.addWidget(clear); buttons.addStretch(); buttons.addWidget(save); buttons.addWidget(cancel); layout.addLayout(buttons)
        h,w=frame.shape[:2]
        if normalized: self.canvas.points=[(x*w,y*h) for x,y in normalized]
        self.canvas.changed.connect(self.refresh); clear.clicked.connect(lambda:(self.canvas.points.clear(),self.canvas.update(),self.refresh())); save.clicked.connect(self.accept); cancel.clicked.connect(self.reject); self.refresh()
    def refresh(self): self.info.setText(f"Số điểm: {len(self.canvas.points)} | "+"Polygon hợp lệ" if polygon_is_valid(self.canvas.points) else f"Số điểm: {len(self.canvas.points)} | Chưa hợp lệ")
    def accept(self):
        if not polygon_is_valid(self.canvas.points): QMessageBox.warning(self,"Polygon không hợp lệ","Polygon cần ít nhất 3 điểm, có diện tích và không tự cắt."); return
        super().accept()
    def normalized_points(self):
        h,w=self.canvas.frame.shape[:2]; return [list(p) for p in normalize_points(self.canvas.points,w,h)]

