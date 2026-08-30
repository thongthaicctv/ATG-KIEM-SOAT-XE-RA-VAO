import pytest

from app.core.config import RUNTIME_PROFILES, get_runtime_profile


def test_debug_profile_is_bounded_to_one_camera():
    profile = RUNTIME_PROFILES["debug_1cam"]
    assert profile.max_cameras == 1
    assert profile.model_filename == "yolo11n.pt"
    assert profile.ai_debug_overlay is True


def test_production_profile_targets_ten_cameras_and_cuda():
    profile = RUNTIME_PROFILES["production_10cam"]
    assert profile.max_cameras == 10
    assert profile.detector_device == "cuda"
    # Phase 4: FP32 tren NVIDIA T600 4GB nhanh hon FP16 that su (benchmark thuc te,
    # xem reports/benchmark/ va app/core/config.py comment tai RUNTIME_PROFILES) - nen
    # production_10cam duoc doi mac dinh sang detector_half=False (FP32).
    assert profile.detector_half is False
    assert profile.model_filename == "yolo11s.pt"
    assert profile.preview_fps < RUNTIME_PROFILES["debug_1cam"].preview_fps


def test_unknown_profile_is_rejected():
    with pytest.raises(ValueError):
        get_runtime_profile("not-a-profile")
