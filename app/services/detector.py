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
        self.error=error; self.device="unavailable"; self.actual_device="unavailable"; self.half=False; self.last_stats={"raw_detections":0,"vehicle_detections":0,"inference_ms":0.0,"filtered":[]}
    def detect(self,frame,confidence=None,enable_motorcycles=True,image_size=640): return []


class YoloDetector:
    def __init__(self,model_path: str,confidence=.4,enable_motorcycles=False,device="auto",half=False):
        from ultralytics import YOLO
        import torch
        from pathlib import Path
        configured=str(device).lower(); self._torch=torch; self.log=logging.getLogger(__name__); self.model=YOLO(model_path); self.confidence=confidence; self.enabled=True; self.name=str(Path(model_path).resolve()); self.error=None; self.last_stats={}; self.last_log_at=0.0; self.first_inference_logged=False
        self.device=("cuda:0" if torch.cuda.is_available() else "cpu") if configured=="auto" else configured
        if self.device.startswith("cuda") and not torch.cuda.is_available():
            reason="PYTORCH_CPU_ONLY" if torch.version.cuda is None else "CUDA_RUNTIME_UNAVAILABLE"
            self.log.error("DETECTOR_CUDA_UNAVAILABLE configured=%s reason=%s torch=%s torch_cuda_build=%s",configured,reason,torch.__version__,torch.version.cuda)
            raise RuntimeError(f"DETECTOR_CUDA_UNAVAILABLE: {reason}")
        selection=("AUTO_SELECTED_CUDA" if self.device.startswith("cuda") else "AUTO_SELECTED_CPU") if configured=="auto" else ("CUDA_SELECTED" if self.device.startswith("cuda") else "CPU_SELECTED")
        self.log.info("%s configured=%s resolved=%s cuda_available=%s",selection,configured,self.device,torch.cuda.is_available())
        self.half=bool(half and self.device.startswith("cuda")); self._lock=threading.Lock(); self.names={int(k):str(v).lower() for k,v in self.model.names.items()}
        gpu=torch.cuda.get_device_name(0) if self.device.startswith("cuda") else "-"; allocated=torch.cuda.memory_allocated(0)/1048576 if self.device.startswith("cuda") else 0; reserved=torch.cuda.memory_reserved(0)/1048576 if self.device.startswith("cuda") else 0
        parameter=next(self.model.model.parameters(),None); parameter_device=str(parameter.device) if parameter is not None else "unknown"; parameter_dtype=str(parameter.dtype) if parameter is not None else "unknown"; self.actual_device=parameter_device
        self.log.info("Detector loaded model=%s exists=%s configured_device=%s resolved_device=%s gpu=%s model_parameter_device=%s model_parameter_dtype=%s model_instances=1 allocated_mib=%.1f reserved_mib=%.1f confidence=%.2f",self.name,Path(model_path).exists(),configured,self.device,gpu,parameter_device,parameter_dtype,allocated,reserved,self.confidence)
    def detect(self,frame,confidence=None,enable_motorcycles=True,image_size=640):
        started=time.perf_counter(); output=[]; raw=0; filtered=[]; threshold=float(confidence if confidence is not None else self.confidence); allowed=set(ALLOWED_VEHICLE_CLASSES)
        if not enable_motorcycles: allowed.discard("motorcycle")
        # Một model được dùng chung cho các camera. Ultralytics không bảo đảm một
        # model instance có thể predict đồng thời từ nhiều QThread.
        predict_options={"conf":threshold,"imgsz":int(image_size),"device":self.device,"verbose":False}
        if self.half: predict_options["half"]=True
        with self._lock:
            results=self.model.predict(frame,**predict_options)
        tensor=getattr(getattr(results[0],"boxes",None),"xyxy",None) if results else None; result_device=str(tensor.device) if tensor is not None else "unknown"; self.actual_device=result_device
        if not getattr(self,"first_inference_logged",False):
            torch=getattr(self,"_torch",None); self.first_inference_logged=True; allocated=torch.cuda.memory_allocated(0)/1048576 if torch and self.device.startswith("cuda") else 0; reserved=torch.cuda.memory_reserved(0)/1048576 if torch and self.device.startswith("cuda") else 0; peak=torch.cuda.max_memory_allocated(0)/1048576 if torch and self.device.startswith("cuda") else 0
            self.log.info("FIRST_INFERENCE configured_device=%s resolved_device=%s result_device=%s duration_ms=%.1f allocated_mib=%.1f reserved_mib=%.1f peak_mib=%.1f",self.device,self.device,result_device,(time.perf_counter()-started)*1000,allocated,reserved,peak)
            if self.device.startswith("cuda") and not result_device.startswith("cuda"): raise RuntimeError(f"GPU_DEVICE_MISMATCH: result_device={result_device}")
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
