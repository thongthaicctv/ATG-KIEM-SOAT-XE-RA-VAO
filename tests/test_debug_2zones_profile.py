from app.core.config import RUNTIME_PROFILES


def test_debug_2zones_has_safe_limits_and_requires_cuda():
    profile = RUNTIME_PROFILES["debug_2zones"]
    assert profile.max_cameras == 2
    assert profile.processing_fps <= 4
    assert profile.preview_fps <= 5
    assert profile.detector_image_size == 640
    assert profile.detector_device == "cuda:0"
    assert profile.detector_half is False


def test_debug_profile_script_uses_isolated_storage():
    text = open("config/debug-2zones.ps1", encoding="utf-8").read()
    assert "run_app.py" in text
    assert "--mode debug" in text
    assert "--max-cameras 2" in text
    assert "PARKING_" not in text
