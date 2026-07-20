import logging
from pathlib import Path
import cv2

from app.core.paths import ROOT_DIR, SNAPSHOT_DIR


class SnapshotService:
    def __init__(self, root: Path=SNAPSHOT_DIR): self.root=Path(root); self.log=logging.getLogger(__name__)
    def save(self,frame,camera_code,session_code,event_name,when):
        folder=self.root/when.strftime("%Y-%m-%d")/camera_code/session_code; folder.mkdir(parents=True,exist_ok=True)
        target=folder/f"{event_name}.jpg"
        if target.exists(): return str(target.relative_to(ROOT_DIR))
        try:
            if not cv2.imwrite(str(target),frame): raise OSError("cv2.imwrite trả về False")
            return str(target.relative_to(ROOT_DIR))
        except Exception: self.log.exception("Không thể lưu snapshot %s",target); return None

