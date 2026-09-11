"""tests/test_phase_4_7e_b1_1_windows_diagnostic_script.py

Phase 4.7E-B1.1 muc 4/9 - kiem tra PHAN THUAN (khong Qt, khong RTSP, khong GUI) cua
scripts/phase_4_7e_b1_1_windows_preview_freeze_diagnostic.py: bao ve tuyet doi khong
duoc chay voi production DB, va cau hinh CLI mac dinh dung "mode=debug" (khong bao gio
"normal") + dung 1 camera duoc chi dinh. KHONG khoi dong QApplication/MainWindow that -
day KHONG phai bai test tai hien tren Windows (bai do can chay thu cong, xem docstring
cua script), chi la bai test don vi cho phan logic an toan/CLI cua no.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "phase_4_7e_b1_1_windows_preview_freeze_diagnostic.py"


def _load_script_module():
    spec = importlib.util.spec_from_file_location("phase_4_7e_b1_1_windows_preview_freeze_diagnostic", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def diagnostic_module():
    return _load_script_module()


def test_rejects_exact_production_database_path(diagnostic_module):
    with pytest.raises(SystemExit, match="REFUSED"):
        diagnostic_module._reject_production_database(diagnostic_module.PRODUCTION_DATABASE_PATH)


def test_rejects_production_database_via_relative_or_differently_spelled_path(diagnostic_module, monkeypatch):
    """.resolve() phai bat duoc mot duong dan KHAC ve mat chuoi ky tu nhung tro toi
    CUNG mot file production DB (vd duong dan tuong doi, hoac co './'/'../' du thua)."""
    monkeypatch.chdir(diagnostic_module.PROJECT_ROOT)
    relative_alias = Path("data") / ".." / "data" / "parking.db"
    with pytest.raises(SystemExit, match="REFUSED"):
        diagnostic_module._reject_production_database(relative_alias)


def test_accepts_any_non_production_database_path(diagnostic_module, tmp_path):
    debug_db = tmp_path / "phase_4_7e_b1_1_diag.db"
    diagnostic_module._reject_production_database(debug_db)  # must not raise


def test_parse_args_defaults_and_required_flags(diagnostic_module):
    args = diagnostic_module.parse_args(["--camera", "CAM-01", "--database", "data/runtime_debug/diag.db"])
    assert args.camera == "CAM-01"
    assert str(args.database) == "data/runtime_debug/diag.db"
    assert args.device == "auto"
    assert args.normal_seconds == 30.0 and args.freeze_seconds == 15.0 and args.after_seconds == 30.0


def test_parse_args_requires_camera_and_database(diagnostic_module):
    with pytest.raises(SystemExit):
        diagnostic_module.parse_args([])  # missing --camera/--database
    with pytest.raises(SystemExit):
        diagnostic_module.parse_args(["--camera", "CAM-01"])  # missing --database


def test_main_refuses_production_database_end_to_end(diagnostic_module):
    """main() (khong chi ham guard don le) phai TU CHOI (SystemExit, "REFUSED") ngay khi
    --database la production DB - kiem tra nay goi dung ham main() cong khai, dam bao
    guard thuc su duoc noi day vao luong thuc thi that (khong chi ton tai nhu mot ham
    khong duoc goi toi)."""
    with pytest.raises(SystemExit, match="REFUSED"):
        diagnostic_module.main(["--camera", "CAM-01", "--database", str(diagnostic_module.PRODUCTION_DATABASE_PATH)])
