import logging
from PySide6.QtCore import Signal,QObject
from PySide6.QtWidgets import QPlainTextEdit


class QtLogEmitter(QObject): message=Signal(str)
class QtLogHandler(logging.Handler):
    def __init__(self): super().__init__(); self.emitter=QtLogEmitter()
    def emit(self,record):
        if getattr(record,"telemetry",False): return
        self.emitter.message.emit(self.format(record))


class EventLogWidget(QPlainTextEdit):
    def __init__(self,parent=None):
        super().__init__(parent); self.setReadOnly(True); self.setMaximumBlockCount(1000); self.handler=QtLogHandler(); self.handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s: %(message)s")); self.handler.emitter.message.connect(self.appendPlainText); logging.getLogger().addHandler(self.handler)
