from __future__ import annotations

import os
import subprocess
from pathlib import Path

from PySide6.QtWidgets import QApplication,QDialog,QHBoxLayout,QMessageBox,QPlainTextEdit,QPushButton,QVBoxLayout

from app.core.environment_check import collect_environment,format_environment
from app.core.paths import LOG_DIR,ROOT_DIR,SNAPSHOT_DIR


COMMANDS = {
    "setup": "powershell -ExecutionPolicy Bypass -File .\\scripts\\setup-dev.ps1",
    "check": "powershell -ExecutionPolicy Bypass -File .\\scripts\\check-environment.ps1",
    "debug": "powershell -ExecutionPolicy Bypass -File .\\config\\debug-1cam.ps1",
    "normal": ".\\.venv\\Scripts\\python.exe .\\run_app.py",
    "test": ".\\.venv\\Scripts\\python.exe -m pytest -v",
}


class DebugGuideDialog(QDialog):
    def __init__(self,settings,parent=None):
        super().__init__(parent); self.settings=settings; self.setWindowTitle("Môi trường và Debug 1 Camera"); self.resize(880,680)
        layout=QVBoxLayout(self); self.text=QPlainTextEdit(); self.text.setReadOnly(True); layout.addWidget(self.text)
        row=QHBoxLayout()
        for label,key in [("Sao chép setup","setup"),("Sao chép check","check"),("Sao chép debug","debug"),("Sao chép test","test")]:
            button=QPushButton(label); button.clicked.connect(lambda _=False,k=key:self.copy_command(k)); row.addWidget(button)
        layout.addLayout(row); row2=QHBoxLayout()
        for label,path in [("Mở project root",ROOT_DIR),("Mở logs",LOG_DIR),("Mở snapshots",SNAPSHOT_DIR)]:
            button=QPushButton(label); button.clicked.connect(lambda _=False,p=path:os.startfile(str(p))); row2.addWidget(button)
        check=QPushButton("Chạy kiểm tra môi trường"); check.clicked.connect(self.run_check); row2.addWidget(check); layout.addLayout(row2)
        self.refresh()

    def refresh(self,extra=""):
        info,errors=collect_environment(load_model=False)
        commands="\n\nLỆNH CHÍNH THỨC\n"+"\n".join(f"{k}: {v}" for k,v in COMMANDS.items())
        self.text.setPlainText(format_environment(info,errors)+commands+("\n\n"+extra if extra else ""))

    def copy_command(self,key): QApplication.clipboard().setText(COMMANDS[key])

    def run_check(self):
        script=ROOT_DIR / "scripts" / "check-environment.ps1"
        result=subprocess.run(["powershell","-ExecutionPolicy","Bypass","-File",str(script)],cwd=ROOT_DIR,capture_output=True,text=True,encoding="utf-8",errors="replace")
        self.refresh((result.stdout+"\n"+result.stderr).strip())
        if result.returncode: QMessageBox.warning(self,"Environment check","Kiểm tra chưa đạt. Xem chi tiết trong cửa sổ.")
