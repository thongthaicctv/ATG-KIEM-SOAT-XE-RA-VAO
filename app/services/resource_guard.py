from __future__ import annotations

import csv, json, re, time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path


@dataclass(slots=True)
class ResourceThresholds:
    cpu_percent: float=85; ram_percent: float=85; vram_percent: float=85
    ai_frame_age_ms: float=1000; actual_fps_ratio: float=.70; queue_size: int=1
    overload_confirm_seconds: float=30; cooldown_seconds: float=60


class ResourceGuard:
    def __init__(self,thresholds=None,production=False):
        self.t=thresholds or ResourceThresholds(); self.production=production; self.since={}; self.last_fallback_at=-1e20
    def evaluate(self,sample: dict,now=None):
        now=time.monotonic() if now is None else float(now); conditions=[]
        checks={"CPU_HIGH":sample.get("cpu_percent",0)>self.t.cpu_percent,"RAM_HIGH":sample.get("ram_percent",0)>self.t.ram_percent,"VRAM_HIGH":sample.get("vram_percent",0)>self.t.vram_percent,"AI_FRAME_STALE":sample.get("ai_frame_age_ms",0)>self.t.ai_frame_age_ms,"QUEUE_BACKLOG":sample.get("queue_size",0)>self.t.queue_size,"AI_FPS_LOW":sample.get("configured_ai_fps",0)>0 and sample.get("actual_ai_fps",0)<sample.get("configured_ai_fps",0)*self.t.actual_fps_ratio}
        fatal=bool(sample.get("gpu_oom") or sample.get("fatal"))
        for name,active in checks.items():
            if active: self.since.setdefault(name,now)
            else: self.since.pop(name,None)
            if active and now-self.since[name]>=self.t.overload_confirm_seconds: conditions.append(name)
        overloaded=fatal or len(conditions)>=2 or any(c in conditions for c in ("AI_FRAME_STALE","QUEUE_BACKLOG"))
        can_fallback=overloaded and not self.production and now-self.last_fallback_at>=self.t.cooldown_seconds
        return {"overloaded":overloaded,"conditions":["GPU_OOM"] if fatal else conditions,"action":"WARN_ONLY" if self.production and overloaded else ("FALLBACK" if can_fallback else "NONE")}
    def mark_fallback(self,now=None): self.last_fallback_at=time.monotonic() if now is None else float(now)


class CapacityBenchmark:
    def __init__(self,manager,cameras,fallback_min=1):
        self.manager=manager; self.cameras=list(cameras); self.fallback_min=max(1,int(fallback_min)); self.active=[]; self.last_stable_count=0; self.maximum_attempted=0; self.telemetry=[]; self.errors=[]; self.state="READY"
    def add_next(self):
        if len(self.active)>=len(self.cameras): self.state="COMPLETED"; return False
        camera=self.cameras[len(self.active)]; ok=self.manager.start_camera(camera)
        if ok: self.active.append(camera); self.maximum_attempted=max(self.maximum_attempted,len(self.active)); self.state="WARMUP"
        return bool(ok)
    def mark_stable(self): self.last_stable_count=len(self.active); self.state="STABLE"
    def fallback(self):
        target=max(self.fallback_min,self.last_stable_count)
        while len(self.active)>target:
            camera=self.active.pop(); self.manager.suspend_camera(camera)
        self.state="FALLING_BACK"; return len(self.active)
    def report(self,root: Path,hardware: dict,settings: dict):
        out=root/"reports"/"capacity_benchmark"; out.mkdir(parents=True,exist_ok=True); stamp=datetime.now().strftime("%Y%m%d_%H%M%S")
        safe=min(self.last_stable_count,self.last_stable_count); clean=lambda s:re.sub(r"(?i)(rtsp://[^:/@]+:)[^@]+@",r"\1***@",str(s))
        payload={"hardware":hardware,"runtime_settings":settings,"cameras":[{"camera_code":c.camera_code,"zone_type":c.zone_type,"rtsp_url":clean(c.rtsp_url)} for c in self.cameras],"telemetry":self.telemetry,"maximum_attempted_cameras":self.maximum_attempted,"maximum_stable_cameras":self.last_stable_count,"recommended_safe_cameras":safe,"errors":self.errors,"warning":"Kết quả này dựa trên thời gian benchmark hiện tại và cần kiểm tra dài hạn trước khi triển khai chính thức."}
        jp=out/f"benchmark_{stamp}.json"; cp=out/f"benchmark_{stamp}.csv"; jp.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding="utf-8")
        with cp.open("w",newline="",encoding="utf-8-sig") as f:
            writer=csv.DictWriter(f,fieldnames=sorted({k for row in self.telemetry for k in row})); writer.writeheader(); writer.writerows(self.telemetry)
        return jp,cp
