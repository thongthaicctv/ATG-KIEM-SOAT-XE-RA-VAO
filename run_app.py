from __future__ import annotations

import argparse, os, subprocess, sys
from pathlib import Path

PROJECT_ROOT=Path(__file__).resolve().parent
os.chdir(PROJECT_ROOT); sys.path.insert(0,str(PROJECT_ROOT))

from app.core.runtime_config import RuntimeConfig


def parser():
    p=argparse.ArgumentParser(description="Parking Monitoring System runtime entry point")
    p.add_argument("--mode",choices=("normal","debug","benchmark")); p.add_argument("--device",choices=("auto","cpu","cuda:0"),default="auto")
    p.add_argument("--max-cameras",type=int); p.add_argument("--camera",action="append",default=[]); p.add_argument("--database",type=Path)
    p.add_argument("--fallback-min-cameras",type=int,choices=(1,2),default=1); scale=p.add_mutually_exclusive_group(); scale.add_argument("--auto-scale",action="store_true"); scale.add_argument("--no-auto-scale",action="store_true")
    p.add_argument("--benchmark-duration",type=int,default=180); p.add_argument("--no-startup-dialog",action="store_true"); return p


def from_args(args) -> RuntimeConfig:
    mode=args.mode or "normal"; maximum=args.max_cameras or (len(args.camera) if args.camera else (10 if mode=="normal" else 1))
    return RuntimeConfig(mode,args.device,maximum,tuple(args.camera),args.database,args.fallback_min_cameras,args.auto_scale and not args.no_auto_scale,args.benchmark_duration,not args.no_startup_dialog)


def cuda_available():
    try:
        import torch
        return bool(torch.cuda.is_available())
    except Exception: return False


def choose_runtime(args,show_dialog):
    if not show_dialog: return from_args(args)
    from PySide6.QtWidgets import QApplication
    from app.ui.startup_runtime_dialog import StartupRuntimeDialog
    app=QApplication.instance() or QApplication(sys.argv); dialog=StartupRuntimeDialog(PROJECT_ROOT)
    return dialog.result_config if dialog.exec() else None


def prepare_debug_database(config: RuntimeConfig):
    if config.mode=="normal": return
    target=config.database_path or PROJECT_ROOT/"data"/"runtime_debug"/("benchmark.db" if config.mode=="benchmark" else f"debug_{config.max_cameras}cams.db")
    command=[sys.executable,str(PROJECT_ROOT/"scripts"/"prepare_debug_2zones.py"),"--target",str(target)]
    for code in config.cameras: command.extend(["--camera",code])
    subprocess.run(command,cwd=PROJECT_ROOT,check=True)


def main(argv=None):
    raw=list(sys.argv[1:] if argv is None else argv); args=parser().parse_args(raw); incomplete_selection=args.mode in ("debug","benchmark") and not args.camera
    show_dialog=not args.no_startup_dialog and (not raw or args.mode is None or incomplete_selection)
    config=choose_runtime(args,show_dialog)
    if config is None: return 0
    if config.device=="cuda:0" and not cuda_available():
        print("DETECTOR_CUDA_UNAVAILABLE: CUDA không khả dụng; hãy chọn auto/cpu hoặc cài PyTorch CUDA thủ công.",file=sys.stderr); return 2
    config.apply_environment(PROJECT_ROOT); prepare_debug_database(config)
    from app.core.config import Settings
    from app.main import main as app_main
    settings=Settings(); return app_main(settings)


if __name__=="__main__": raise SystemExit(main())
