import os
import subprocess
import sys
from pathlib import Path


def _restart_with_project_venv() -> None:
    """Đảm bảo `python run_app.py` dùng đúng môi trường đã cài AI."""
    if os.name != "nt":
        return
    project_python = Path(__file__).resolve().parent / ".venv" / "Scripts" / "python.exe"
    if not project_python.exists():
        return
    if Path(sys.executable).resolve() == project_python.resolve():
        return
    result = subprocess.call([str(project_python), str(Path(__file__).resolve()), *sys.argv[1:]])
    raise SystemExit(result)


if __name__ == "__main__":
    _restart_with_project_venv()
    if "--check-runtime" in sys.argv:
        import ultralytics
        print(f"Python: {sys.executable}")
        print(f"Ultralytics: {ultralytics.__version__}")
        print(f"Model: {(Path(__file__).resolve().parent / 'models' / 'yolo11n.pt')}")
        raise SystemExit(0)

from app.main import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
