import logging,sys
from datetime import datetime
from PySide6.QtWidgets import QApplication
from app.core.config import settings
from app.core.logging_config import configure_logging
from app.core.paths import ensure_directories
from app.database.migrations import init_database
from app.ui.main_window import MainWindow
from app.utils.time_utils import utc_now


def main():
    ensure_directories(); configure_logging(); logging.info("Khởi động ứng dụng"); logging.info("Application timezone: %s",settings.app_timezone); logging.info("System local time: %s",datetime.now().astimezone().isoformat()); logging.info("Current UTC time: %s",utc_now().isoformat()); init_database(); logging.info("Database init")
    app=QApplication(sys.argv); app.setApplicationName("Parking Monitoring System"); window=MainWindow(settings); window.show(); return app.exec()
