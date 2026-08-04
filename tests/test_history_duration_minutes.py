from app.ui.main_window import format_duration_minutes


def test_history_duration_is_displayed_in_minutes():
    assert format_duration_minutes(2188)=="36.47 phút"
    assert format_duration_minutes(153)=="2.55 phút"
    assert format_duration_minutes(2)=="0.03 phút"
