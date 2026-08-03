if __name__ == "__main__" and not __package__:
    raise SystemExit("Không chạy trực tiếp app/main.py.\nHãy chạy từ project root:\n.\\.venv\\Scripts\\python.exe .\\run_app.py")

import logging,sys,platform
from datetime import datetime
from pathlib import Path
from PySide6.QtWidgets import QApplication,QMessageBox
from app.core.config import settings
from app.core.logging_config import configure_logging
from app.core.paths import LOG_DIR,ROOT_DIR,SNAPSHOT_DIR,ensure_directories
from app.database.migrations import init_database
from app.ui.main_window import MainWindow
from app.utils.time_utils import utc_now


def main():
    app=QApplication.instance() or QApplication(sys.argv); app.setApplicationName("Parking Monitoring System")
    try:
        ensure_directories(); configure_logging()
        try:
            import torch
            cuda_available=torch.cuda.is_available()
        except Exception: cuda_available=False
        logging.info("Startup project_root=%s executable=%s python=%s cwd=%s entry_point=%s",ROOT_DIR,sys.executable,platform.python_version(),Path.cwd(),ROOT_DIR / "run_app.py")
        logging.info("Startup profile=%s max_cameras=%d model=%s device=%s half=%s cuda=%s database=%s timezone=%s logs=%s snapshots=%s",settings.runtime_profile,settings.max_cameras,settings.detector_model,settings.detector_device,settings.detector_half,cuda_available,settings.database_url,settings.app_timezone,LOG_DIR,SNAPSHOT_DIR)
        logging.info("System local time: %s; current UTC time: %s",datetime.now().astimezone().isoformat(),utc_now().isoformat())
        init_database(); logging.info("Database init")
        window=MainWindow(settings); window.show(); return app.exec()
    except Exception as exc:
        logging.exception("Startup failed")
        QMessageBox.critical(None,"Không thể khởi động",f"Ứng dụng không thể khởi động.\n\n{exc}\n\nXem log: {LOG_DIR / 'parking_monitor.log'}")
        return 1
