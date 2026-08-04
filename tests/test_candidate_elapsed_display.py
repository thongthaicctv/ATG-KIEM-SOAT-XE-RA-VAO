from types import SimpleNamespace

from app.ui.monitor_widget import CameraCard,format_elapsed_seconds


def camera():
    return SimpleNamespace(id=1,camera_code="P1",parking_position_code="P1",enabled=True,preview_fps=5)


def test_elapsed_formatter_supports_long_parking():
    assert format_elapsed_seconds(0)=="00:00:00"
    assert format_elapsed_seconds(3661)=="01:01:01"


def test_candidate_starts_visible_stop_timer(qtbot):
    card=CameraCard(camera()); qtbot.addWidget(card); card.update_elapsed("VEHICLE_CANDIDATE",7)
    assert card.elapsed.text()=="Thời gian dừng: 00:00:07 (đang xác nhận)"


def test_occupied_continues_with_parking_timer(qtbot):
    card=CameraCard(camera()); qtbot.addWidget(card); card.update_elapsed("OCCUPIED",65)
    assert card.elapsed.text()=="Thời gian đỗ: 00:01:05"
