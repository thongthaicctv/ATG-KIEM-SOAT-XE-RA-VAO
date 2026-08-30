import os
from types import SimpleNamespace

from app.core.config import RUNTIME_PROFILES, get_runtime_profile
from app.core.runtime_config import RuntimeConfig
from run_app import ensure_detector_model, from_args, parser


def _clear_parking_env(monkeypatch):
    """Xoá mọi PARKING_* trước mỗi test để apply_environment() không bị nhiễu bởi biến
    môi trường còn sót lại từ test khác hoặc từ shell đã chạy trước đó."""
    for key in list(os.environ):
        if key.startswith("PARKING_"):
            monkeypatch.delenv(key, raising=False)


def test_normal_mode_resolves_production_10cam_profile(tmp_path, monkeypatch):
    _clear_parking_env(monkeypatch)
    config = RuntimeConfig("normal", "cuda:0", 10)
    config.apply_environment(tmp_path)
    assert os.environ["PARKING_RUNTIME_PROFILE"] == "production_10cam"


def test_normal_mode_model_resolves_via_profile_to_yolo11s(tmp_path, monkeypatch):
    _clear_parking_env(monkeypatch)
    config = RuntimeConfig("normal", "cuda:0", 10)
    config.apply_environment(tmp_path)
    # RuntimeConfig KHONG con set PARKING_DETECTOR_MODEL: RUNTIME_PROFILES la nguon su
    # that duy nhat cho model mac dinh, khong duplicate mapping profile/model o day.
    assert "PARKING_DETECTOR_MODEL" not in os.environ
    profile_name = os.environ["PARKING_RUNTIME_PROFILE"]
    assert get_runtime_profile(profile_name).model_filename == "yolo11s.pt"


def test_debug_one_camera_model_is_yolo11n(tmp_path, monkeypatch):
    _clear_parking_env(monkeypatch)
    config = RuntimeConfig("debug", "auto", 1)
    config.apply_environment(tmp_path)
    assert os.environ["PARKING_RUNTIME_PROFILE"] == "debug_1cam"
    assert RUNTIME_PROFILES["debug_1cam"].model_filename == "yolo11n.pt"


def test_debug_two_cameras_model_is_yolo11n(tmp_path, monkeypatch):
    _clear_parking_env(monkeypatch)
    config = RuntimeConfig("debug", "auto", 2)
    config.apply_environment(tmp_path)
    assert os.environ["PARKING_RUNTIME_PROFILE"] == "debug_2zones"
    assert RUNTIME_PROFILES["debug_2zones"].model_filename == "yolo11n.pt"


def test_cli_device_cuda0_preserved_through_apply_environment(tmp_path, monkeypatch):
    _clear_parking_env(monkeypatch)
    args = parser().parse_args(
        ["--mode", "normal", "--device", "cuda:0", "--max-cameras", "10", "--no-startup-dialog"]
    )
    config = from_args(args)
    assert config.device == "cuda:0"
    config.apply_environment(tmp_path)
    assert os.environ["PARKING_DETECTOR_DEVICE"] == "cuda:0"


def test_normal_mode_database_still_defaults_to_parking_db(tmp_path, monkeypatch):
    _clear_parking_env(monkeypatch)
    config = RuntimeConfig("normal", "cuda:0", 10)
    config.apply_environment(tmp_path)
    expected = (tmp_path / "data" / "parking.db").as_posix()
    assert os.environ["PARKING_DATABASE_URL"] == f"sqlite:///{expected}"
    assert "runtime_debug" not in os.environ["PARKING_DATABASE_URL"]


def test_production_script_invokes_run_app_without_startup_dialog():
    text = open("config/production-10cam.ps1", encoding="utf-8-sig").read()
    assert "run_app.py" in text
    assert "--mode normal" in text
    assert "--device cuda:0" in text
    assert "--max-cameras 10" in text
    assert "--no-startup-dialog" in text
    # Single source of truth: production script khong tu set model/half, de
    # RUNTIME_PROFILES["production_10cam"] qua RuntimeConfig/Settings resolve.
    assert "PARKING_DETECTOR_MODEL" not in text
    assert "PARKING_DETECTOR_HALF" not in text

    # --no-startup-dialog dung nghia: voi dung cac tham so script truyen, run_app.py se
    # khong mo StartupRuntimeDialog (show_dialog = not args.no_startup_dialog and ...).
    args = parser().parse_args(
        ["--mode", "normal", "--device", "cuda:0", "--max-cameras", "10", "--no-startup-dialog"]
    )
    assert args.no_startup_dialog is True


def test_missing_production_model_fails_fast_without_touching_ultralytics(tmp_path):
    missing = tmp_path / "models" / "yolo11s.pt"
    settings = SimpleNamespace(detector_model=str(missing))
    error = ensure_detector_model(settings)
    assert error == f"DETECTOR_MODEL_NOT_FOUND: {missing}"
    # Thong bao loi khong duoc lo RTSP/credential.
    assert "rtsp" not in error.lower()


def test_existing_model_passes_ensure_detector_model_check(tmp_path):
    present = tmp_path / "yolo11n.pt"
    present.write_bytes(b"fake-weights")
    settings = SimpleNamespace(detector_model=str(present))
    assert ensure_detector_model(settings) is None
