import json
from pathlib import Path

from app.core.environment_check import resolve_model_path
from app.core.paths import ROOT_DIR
from app.ui.debug_guide_dialog import COMMANDS


def test_entrypoint_imports_app_main_without_hardcoded_drive():
    text=(ROOT_DIR / "run_app.py").read_text(encoding="utf-8")
    assert "from app.main import main" in text
    assert "D:\\" not in text


def test_debug_script_resolves_root_and_never_runs_app_main():
    text=(ROOT_DIR / "config" / "debug-1cam.ps1").read_text(encoding="utf-8")
    assert "Split-Path -Parent $PSScriptRoot" in text
    assert "Chưa tìm thấy môi trường .venv" in text
    assert "app\\main.py" not in text


def test_relative_model_is_resolved_from_project_root():
    assert resolve_model_path("models/yolo11n.pt") == (ROOT_DIR / "models" / "yolo11n.pt").resolve()


def test_modal_commands_use_official_entrypoint():
    joined="\n".join(COMMANDS.values())
    assert "app\\main.py" not in joined
    assert "run_app.py" in joined


def test_vscode_launch_uses_official_entrypoint():
    config=json.loads((ROOT_DIR / ".vscode" / "launch.json").read_text(encoding="utf-8"))
    assert all(item["program"] == "${workspaceFolder}/run_app.py" for item in config["configurations"])
