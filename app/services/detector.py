from __future__ import annotations

import logging,time,threading
from dataclasses import dataclass
from app.core.constants import ALLOWED_VEHICLE_CLASSES
from app.core.config import settings


@dataclass(slots=True)
class Detection:
    bbox: tuple[float,float,float,float]
    confidence: float
    vehicle_class: str


def is_allowed_vehicle_class(class_name: str,enable_motorcycles=True) -> bool:
    name=str(class_name).strip().lower()
    return name in ALLOWED_VEHICLE_CLASSES and (enable_motorcycles or name!="motorcycle")


class NullDetector:
    enabled = False
    name = "Chưa cấu hình"
    def __init__(self,error="Chưa cấu hình model"):
        self.error=error; self.last_stats={"raw_detections":0,"vehicle_detections":0,"inference_ms":0.0,"filtered":[]}
    def detect(self,frame,confidence=None,enable_motorcycles=True,image_size=640): return []


class YoloDetector:
    def __init__(self,model_path: str,confidence=.4,enable_motorcycles=False,device="auto",half=False):
        from ultralytics import YOLO
        import torch
        from pathlib import Path
        self.log=logging.getLogger(__name__); self.model=YOLO(model_path); self.confidence=confidence; self.enabled=True; self.name=str(Path(model_path).resolve()); self.error=None; self.last_stats={}; self.last_log_at=0.0
        self.device=("cuda" if torch.cuda.is_available() else "cpu") if device=="auto" else device
        if self.device.startswith("cuda") and not torch.cuda.is_available(): raise RuntimeError("Profile yêu cầu CUDA nhưng PyTorch không nhận GPU")
        self.half=bool(half and self.device.startswith("cuda")); self._lock=threading.Lock(); self.names={int(k):str(v).lower() for k,v in self.model.names.items()}
        self.log.info("Detector loaded model=%s exists=%s device=%s imgsz=per-camera confidence=%.2f names=%s allowed=%s",self.name,Path(model_path).exists(),self.device,self.confidence,self.names,sorted(ALLOWED_VEHICLE_CLASSES))
    def detect(self,frame,confidence=None,enable_motorcycles=True,image_size=640):
        started=time.perf_counter(); output=[]; raw=0; filtered=[]; threshold=float(confidence if confidence is not None else self.confidence); allowed=set(ALLOWED_VEHICLE_CLASSES)
        if not enable_motorcycles: allowed.discard("motorcycle")
        # Một model được dùng chung cho các camera. Ultralytics không bảo đảm một
        # model instance có thể predict đồng thời từ nhiều QThread.
        predict_options={"conf":threshold,"imgsz":int(image_size),"device":self.device,"verbose":False}
        if self.half: predict_options["half"]=True
        with self._lock:
            results=self.model.predict(frame,**predict_options)
        for result in results:
            for box in result.boxes:
                raw+=1; class_id=int(box.cls.item()); name=str(result.names[class_id]).strip().lower()
                if is_allowed_vehicle_class(name,enable_motorcycles): output.append(Detection(tuple(map(float,box.xyxy[0].tolist())),float(box.conf.item()),name))
                else: filtered.append({"class_id":class_id,"class_name":name,"reason":"class_not_allowed"})
        elapsed=(time.perf_counter()-started)*1000; self.last_stats={"raw_detections":raw,"vehicle_detections":len(output),"inference_ms":elapsed,"filtered":filtered,"frame_size":tuple(frame.shape[:2]),"confidence":threshold,"image_size":int(image_size),"allowed":sorted(allowed),"vehicle_results":[{"class":d.vehicle_class,"confidence":d.confidence,"bbox":d.bbox} for d in output]}
        now=time.monotonic()
        if now-self.last_log_at>=settings.telemetry_interval_seconds:
            self.last_log_at=now; self.log.info("Detector telemetry original=%sx%s inference=%sx%s duration_ms=%.1f raw=%d vehicles=%d",frame.shape[1],frame.shape[0],frame.shape[1],frame.shape[0],elapsed,raw,len(output),extra={"telemetry":True})
            if filtered: self.log.info("Vehicle filtered details=%s",filtered,extra={"telemetry":True})
        return output


def build_detector(model_path: str,confidence=.4,enable_motorcycles=False,device="auto",half=False):
    from pathlib import Path
    log=logging.getLogger(__name__); log.info("Detector config model=%s exists=%s confidence=%.2f",str(Path(model_path).resolve()) if model_path else "",bool(model_path and Path(model_path).exists()),confidence)
    if not model_path or not Path(model_path).exists(): log.error("DETECTOR_MODEL_NOT_FOUND: %s",model_path); return NullDetector(f"DETECTOR_MODEL_NOT_FOUND: {model_path}")
    try: return YoloDetector(model_path,confidence,enable_motorcycles,device=device,half=half)
    except Exception as exc: log.exception("Detector error: không tải được model"); return NullDetector(str(exc))
