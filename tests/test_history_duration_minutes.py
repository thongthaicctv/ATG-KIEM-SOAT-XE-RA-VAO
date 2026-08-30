# Phase 4.3: format_duration_minutes() (phut thap phan, vd "17386.42 phut") da bi
# XOA khoi app/ui/main_window.py theo yeu cau Section 10 cua Phase 4.3 - day la thay doi
# HANH VI HIEN THI duoc yeu cau tuong minh (khong phai suy dien/vo tinh lam yeu test), nen
# test nay duoc CAP NHAT de kiem tra ham thay the format_duration_hhmmss() (app/utils/time_utils.py)
# thay vi bi xoa hoac lam yeu di. Cac gia tri kiem tra lay dung tu vi du trong yeu cau Phase 4.3:
# 0->00:00:00, 9->00:00:09, 59->00:00:59, 60->00:01:00, 3661->01:01:01, 90061->25:01:01 (KHONG wrap 24h),
# va am->00:00:00 (guard).
from app.utils.time_utils import format_duration_hhmmss


def test_format_duration_hhmmss_matches_phase_4_3_spec_examples():
    assert format_duration_hhmmss(0)=="00:00:00"
    assert format_duration_hhmmss(9)=="00:00:09"
    assert format_duration_hhmmss(59)=="00:00:59"
    assert format_duration_hhmmss(60)=="00:01:00"
    assert format_duration_hhmmss(3661)=="01:01:01"
    assert format_duration_hhmmss(90061)=="25:01:01"


def test_format_duration_hhmmss_does_not_wrap_at_24_hours():
    # Phien co the keo dai nhieu ngay (vd phien bi dong sau khi khoi phuc tu DB ma khong
    # co detection song nao xac nhan lai - xem Section 5/10). datetime.strftime("%%H:%%M:%%S")
    # se WRAP lai ve 0 sau 24 gio - day la ly do KHONG duoc dung no.
    assert format_duration_hhmmss(90061)=="25:01:01"
    assert format_duration_hhmmss(1043185)=="289:46:25"  # ~12.07 ngay - vi du that tu Case A v2


def test_format_duration_hhmmss_guards_negative_seconds_to_zero():
    assert format_duration_hhmmss(-5)=="00:00:00"
    assert format_duration_hhmmss(-1043185)=="00:00:00"


def test_format_duration_hhmmss_handles_none_like_missing_duration():
    assert format_duration_hhmmss(None)=="00:00:00"
