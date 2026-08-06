from pathlib import Path
from types import SimpleNamespace

from app.core.runtime_config import RuntimeConfig
from app.services.resource_guard import CapacityBenchmark,ResourceGuard,ResourceThresholds
from run_app import from_args,parser


def test_cli_builds_runtime_selection_without_database_enabled_mutation():
    args=parser().parse_args(["--mode","debug","--device","auto","--max-cameras","2","--camera","CAR","--camera","MOTO","--no-startup-dialog"])
    config=from_args(args)
    assert config.cameras==("CAR","MOTO") and config.database_mode=="DEBUG"


def test_runtime_debug_uses_isolated_paths(tmp_path,monkeypatch):
    config=RuntimeConfig("debug","cpu",2,("A","B"))
    config.apply_environment(tmp_path)
    import os
    assert "runtime_debug" in os.environ["PARKING_DATABASE_URL"]
    assert os.environ["PARKING_DATABASE_MODE"]=="DEBUG"


def test_overload_requires_duration_not_one_sample():
    guard=ResourceGuard(ResourceThresholds(overload_confirm_seconds=30,cooldown_seconds=60))
    sample={"cpu_percent":99,"ram_percent":99}
    assert not guard.evaluate(sample,0)["overloaded"]
    assert not guard.evaluate(sample,29)["overloaded"]
    assert guard.evaluate(sample,30)["action"]=="FALLBACK"


def test_production_guard_warns_and_never_falls_back():
    guard=ResourceGuard(ResourceThresholds(overload_confirm_seconds=0),production=True)
    assert guard.evaluate({"gpu_oom":True},0)["action"]=="WARN_ONLY"


def test_benchmark_adds_one_at_a_time_and_falls_back_without_business_event():
    class Manager:
        def __init__(self): self.started=[]; self.suspended=[]
        def start_camera(self,c): self.started.append(c.camera_code); return True
        def suspend_camera(self,c): self.suspended.append(c.camera_code)
    cameras=[SimpleNamespace(camera_code=str(i),zone_type="CAR_ZONE",rtsp_url="rtsp://u:secret@host/x") for i in range(3)]
    manager=Manager(); bench=CapacityBenchmark(manager,cameras)
    bench.add_next(); bench.mark_stable(); bench.add_next(); assert manager.started==["0","1"]
    assert bench.fallback()==1 and manager.suspended==["1"]


def test_benchmark_report_masks_rtsp_password(tmp_path):
    manager=SimpleNamespace(); camera=SimpleNamespace(camera_code="A",zone_type="CAR_ZONE",rtsp_url="rtsp://admin:secret@10.0.0.1/x")
    bench=CapacityBenchmark(manager,[camera]); bench.maximum_attempted=1; bench.last_stable_count=1
    json_path,_=bench.report(tmp_path,{},{}); text=json_path.read_text(encoding="utf-8")
    assert "secret" not in text and "***" in text
