import os
import subprocess
import sys


def test_main_window_builds_with_injected_settings(tmp_path):
    code = """
from PySide6.QtWidgets import QApplication
from app.core.config import settings
from app.database.migrations import init_database
from app.ui.main_window import MainWindow
app=QApplication([]); init_database(); window=MainWindow(settings)
assert settings.runtime_profile in window.statusBar().currentMessage()
assert str(settings.max_cameras) in window.statusBar().currentMessage()
# Phase 4.2 hotfix: status bar phai hien thi CUNG gia tri voi window.detector.device -
# KHONG duoc doc actual_device (field nay chi chinh xac SAU khi co it nhat 1 lan detect()
# thanh cong; ngay sau __init__, actual_device cua YoloDetector con phan anh trang thai
# CPU-truoc-khi-move-len-GPU cua Ultralytics, gay hien thi "AI: cpu" gia du device that su
# da duoc resolve dung cuda:0 - xem audit Case A thuc te, reports/session_audit/).
assert f"AI: {window.detector.device}" in window.statusBar().currentMessage()
window.close()
"""
    env=os.environ.copy(); env["QT_QPA_PLATFORM"]="offscreen"; env["PARKING_DATABASE_URL"]=f"sqlite:///{tmp_path / 'startup.db'}"
    result=subprocess.run([sys.executable,"-c",code],env=env,capture_output=True,text=True)
    assert result.returncode == 0, result.stderr
