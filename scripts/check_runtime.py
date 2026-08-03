from __future__ import annotations

import platform
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.core.config import settings


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    errors: list[str] = []
    warnings: list[str] = []
    model = Path(settings.detector_model)
    print(f"Python: {sys.version.split()[0]} ({platform.machine()})")
    print(f"Profile: {settings.runtime_profile}")
    print(f"Camera limit: {settings.max_cameras}")
    print(f"Model: {model}")
    print(f"AI: device={settings.detector_device}, half={settings.detector_half}, imgsz={settings.detector_image_size}, fps/camera={settings.processing_fps}")
    if not model.is_file():
        errors.append(f"Không tìm thấy model: {model}")
    try:
        import torch
        cuda = torch.cuda.is_available()
        print(f"PyTorch: {torch.__version__}; CUDA available: {cuda}")
        if cuda:
            props = torch.cuda.get_device_properties(0)
            print(f"GPU: {props.name}; VRAM: {props.total_memory / 1024**3:.1f} GB")
        if settings.detector_device.startswith("cuda") and not cuda:
            errors.append("Profile yêu cầu CUDA nhưng PyTorch không nhận GPU")
        if settings.runtime_profile == "production_10cam" and cuda and props.total_memory < 10 * 1024**3:
            warnings.append("VRAM dưới 10 GB; cần benchmark kỹ 10 camera hoặc giảm imgsz/FPS")
    except ImportError:
        errors.append("Chưa cài PyTorch/Ultralytics; chạy pip install -r requirements-ai.txt")
    for item in warnings:
        print(f"WARNING: {item}")
    for item in errors:
        print(f"ERROR: {item}")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
