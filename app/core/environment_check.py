from __future__ import annotations

import importlib
import os
import platform
import subprocess
import sys
from pathlib import Path

from .config import settings
from .paths import DATA_DIR, LOG_DIR, ROOT_DIR, SNAPSHOT_DIR


def resolve_model_path(value: str) -> Path:
    path = Path(value).expanduser()
    return (ROOT_DIR / path).resolve() if not path.is_absolute() else path.resolve()


def _writable(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".environment-write-test.tmp"
        probe.write_text("ok", encoding="utf-8"); probe.unlink()
        return True
    except OSError:
        return False


def collect_environment(load_model: bool = False) -> tuple[dict[str, object], list[str]]:
    errors: list[str] = []
    modules = {}
    for label, name in {"PySide6":"PySide6", "cv2":"cv2", "sqlalchemy":"sqlalchemy", "numpy":"numpy", "torch":"torch", "ultralytics":"ultralytics", "pytest":"pytest", "pytestqt":"pytestqt"}.items():
        try: modules[label] = importlib.import_module(name)
        except Exception as exc: errors.append(f"IMPORT_{label}_FAILED: {exc}")
    version = platform.python_version()
    if not version.startswith("3.10."): errors.append(f"PYTHON_VERSION_UNSUPPORTED: {version}")
    model = resolve_model_path(settings.detector_model)
    if not settings.detector_model: errors.append("DETECTOR_MODEL_NOT_CONFIGURED")
    elif model.suffix.lower() != ".pt": errors.append(f"DETECTOR_MODEL_EXTENSION_INVALID: {model.suffix}")
    elif not model.is_file(): errors.append(f"DETECTOR_MODEL_NOT_FOUND: {model}")
    elif load_model and "ultralytics" in modules:
        try: modules["ultralytics"].YOLO(str(model))
        except Exception as exc: errors.append(f"DETECTOR_MODEL_LOAD_FAILED: {exc}")
    for path in (DATA_DIR, LOG_DIR, SNAPSHOT_DIR):
        if not _writable(path): errors.append(f"PATH_NOT_WRITABLE: {path}")
    torch = modules.get("torch")
    torch_cuda_build = getattr(getattr(torch, "version", None), "cuda", None)
    cuda = bool(torch and torch.cuda.is_available())
    cuda_count = int(torch.cuda.device_count()) if torch else 0
    gpu_name = torch.cuda.get_device_name(0) if cuda else "-"
    capability = ".".join(map(str, torch.cuda.get_device_capability(0))) if cuda else "-"
    gpu_total_mib = gpu_free_mib = driver_version = "-"
    nvidia_smi_status = "NVIDIA_DRIVER_ERROR"
    try:
        query = subprocess.run(["nvidia-smi", "--query-gpu=name,driver_version,memory.total,memory.free", "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=5, check=True)
        fields = [item.strip() for item in query.stdout.splitlines()[0].split(",")]
        gpu_name, driver_version, gpu_total_mib, gpu_free_mib = fields[:4]
        nvidia_smi_status = "GPU_FOUND"
    except (OSError, subprocess.SubprocessError, IndexError, ValueError):
        pass
    if not torch: cuda_status = "TORCH_NOT_INSTALLED"
    elif torch_cuda_build is None: cuda_status = "PYTORCH_CPU_ONLY"
    elif not cuda: cuda_status = "CUDA_RUNTIME_UNAVAILABLE"
    else: cuda_status = "CUDA_READY"
    if settings.detector_device.startswith("cuda") and cuda_status != "CUDA_READY":
        errors.append(cuda_status)
    database_path = settings.database_url.removeprefix("sqlite:///") if settings.database_url.startswith("sqlite:///") else settings.database_url
    info = {
        "project_root": str(ROOT_DIR), "system_python": str(Path(sys.base_prefix) / "python.exe"), "venv_python": sys.executable,
        "python_version": version, "venv": sys.prefix != sys.base_prefix,
        "runtime_dependencies": not any(e.startswith(("IMPORT_PySide6", "IMPORT_cv2", "IMPORT_sqlalchemy", "IMPORT_numpy")) for e in errors),
        "ai_dependencies": not any(e.startswith(("IMPORT_torch", "IMPORT_ultralytics")) for e in errors),
        "test_dependencies": not any(e.startswith(("IMPORT_pytest", "IMPORT_pytestqt")) for e in errors),
        "torch_version": getattr(torch, "__version__", "-"), "torch_cuda_build": torch_cuda_build,
        "cuda_status": cuda_status, "cuda_available": cuda, "cuda_device_count": cuda_count,
        "cuda_device_name": gpu_name, "cuda_capability": capability, "nvidia_smi_status": nvidia_smi_status,
        "nvidia_driver": driver_version, "gpu_total_mib": gpu_total_mib, "gpu_free_mib": gpu_free_mib,
        "ultralytics_version": getattr(modules.get("ultralytics"), "__version__", "-"),
        "model_path": str(model), "model_exists": model.is_file(), "device": settings.detector_device,
        "half": settings.detector_half, "max_cameras": settings.max_cameras, "database_path": database_path,
        "logs_path": str(LOG_DIR), "snapshots_path": str(SNAPSHOT_DIR), "app_timezone": settings.app_timezone,
        "profile": settings.runtime_profile, "entry_point": str(ROOT_DIR / "run_app.py"),
    }
    return info, errors


def format_environment(info: dict[str, object], errors: list[str]) -> str:
    lines = [f"{key}: {value}" for key, value in info.items()]
    lines.extend(f"ERROR: {item}" for item in errors)
    lines.append(f"ENVIRONMENT CHECK: {'PASS' if not errors else 'FAIL'}")
    return "\n".join(lines)
