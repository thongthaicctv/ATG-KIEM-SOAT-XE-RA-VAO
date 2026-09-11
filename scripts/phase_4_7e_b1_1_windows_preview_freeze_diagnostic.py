"""scripts/phase_4_7e_b1_1_windows_preview_freeze_diagnostic.py

Phase 4.7E-B1.1 muc 4 - WINDOWS REAL-APP FREEZE DIAGNOSTIC (DEBUG/TEST-ONLY).

Boi canh: Phase 4.7E-B1 da them CameraManager.debug_freeze_preview_timer(camera_id,
frozen) - dung/tiep tuc CHI QTimer preview cua MOT camera de tai hien co kiem soat,
xac dinh truong hop preview downstream (manager/UI) bi dung trong khi RAW capture/AI/
worker preview van tiep tuc tien trien (Case D, audit Phase 4.7E-A). Nhung hook do CHI
la mot method noi bo tren CameraManager - khong co cach thuc te nao de mot operator
tren Windows, dang chay tu MOT tien trinh PowerShell KHAC, goi no tren tien trinh GUI
DANG CHAY. Script nay la co che NHO NHAT (Option A trong dac ta) de giai quyet dung
khoang trong do: no KHOI DONG chinh ung dung that (that RTSP, that AI, that
MainWindow/CameraManager) va LICH SAN (qua QTimer.singleShot, TRONG CUNG mot tien
trinh QApplication - khong subprocess, khong IPC, khong socket) mot chu ky
normal -> freeze -> resume cho DUY NHAT MOT camera.

AN TOAN CO SO DU LIEU (yeu cau muc 4 - bat buoc): script nay CHI DUOC PHEP chay voi
mot co so du lieu TEST/DEBUG rieng biet, KHONG BAO GIO voi data/parking.db san xuat.
Co che: RuntimeConfig(mode="debug", ...) (dung HET co che co san cua run_app.py -
KHONG phat minh lai) + --database bat buoc phai duoc chi dinh tuong minh, va bi TU
CHOI (SystemExit, khong chay gi them) neu no trung khop (sau khi .resolve()) voi
data/parking.db. scripts/prepare_debug_2zones.py (chinh script da co san, KHONG viet
lai) sau do CHI DOC (SELECT, khong UPDATE/DELETE) cau hinh camera (rtsp_url,
polygon_points, capacity...) tu mot DB nguon (mac dinh production, xem --source-database
o Phase 4.7E-B1.2) de sao chep SANG ban ghi MOI trong DB debug muc tieu - ban than DB
nguon khong bao gio duoc mo lai sau buoc chuan bi nay; toan bo phien chay GUI chi
doc/ghi vao DB debug.

Phase 4.7E-B1.2 (BO SUNG - "common 4-camera debug DB"): thuc te trien khai co 4 camera
(3 DDNS + 1 LAN, cung mot DB debug), nhung CHI MOT camera duoc dong bang preview co
chu dich. Hai khai niem nay TRUOC DAY bi gop lam mot (--camera vua la topology vua la
muc tieu dong bang khi chi co 1 camera) - B1.2 tach ro:
    --include-camera CODE   (co the lap lai nhieu lan) - TAP HOP camera se duoc sao
                             chep vao DB debug va duoc CameraManager khoi dong that.
    --freeze-camera CODE    - CHINH XAC MOT camera (PHAI thuoc tap --include-camera)
                             se bi dong bang preview timer co chu dich.
    --source-database PATH  - chuyen tiep nguyen ven cho prepare_debug_2zones.py (vd
                             data/runtime_debug/phase47a_4cam_smoke.db, DB da co san
                             dung 3 DDNS + 1 LAN - xem bao cao audit Phase 4.7E-B1.2).
--camera (dang cu, MOT camera) VAN duoc giu nguyen cho tuong thich nguoc tuyet doi: khi
duoc truyen, no vua la topology (1 camera duy nhat) vua la muc tieu dong bang, giong
het hanh vi Phase 4.7E-B1.1 ban dau. KHONG duoc tron lan --camera voi --include-camera/
--freeze-camera trong cung mot lan goi - xem _resolve_camera_selection().

Cac camera DDNS ngoai --freeze-camera co the o trang thai CAMERA_OFFLINE/dang ket noi
lai (chua duoc khoi phuc) - day KHONG phai loi cua bai chan doan preview-freeze, von
CHI quan tam toi MOT camera duoc chi dinh qua --freeze-camera; ket qua cua no duoc quan
sat DOC LAP, khong phu thuoc cac camera khac co ket noi duoc hay khong.

KHONG PHAI production code path: khong co nut/menu san xuat nao goi script nay, khong
co kien truc remote-control/IPC tong quat nao duoc them - day CHI la mot script chan
doan/kiem thu Windows, chay thu cong tu dong lenh, dung mot lan.

Vi du 1 - CHE DO CU, 1 camera (tuong thich nguoc, hanh vi khong doi tu B1.1):
    .\\.venv\\Scripts\\python.exe .\\scripts\\phase_4_7e_b1_1_windows_preview_freeze_diagnostic.py ^
        --camera CAM-01 --database .\\data\\runtime_debug\\phase_4_7e_b1_1_diag.db

Vi du 2 - CHE DO MOI, 4 camera (3 DDNS + 1 LAN), dong bang CHI camera LAN:
    .\\.venv\\Scripts\\python.exe .\\scripts\\phase_4_7e_b1_1_windows_preview_freeze_diagnostic.py ^
        --include-camera GIAM_SAT_O_TO_1 --include-camera GIAM_SAT_O_TO_2 ^
        --include-camera GIAM_SAT_XE_MAY --include-camera GIAM_SAT_XE_MAY_LOCAL ^
        --freeze-camera GIAM_SAT_XE_MAY_LOCAL ^
        --source-database .\\data\\runtime_debug\\phase47a_4cam_smoke.db ^
        --database .\\data\\runtime_debug\\phase47e_4cam_common.db

Trinh tu ky vong cho camera --freeze-camera (mac dinh 30s/15s/30s, xem --normal-seconds/
--freeze-seconds/--after-seconds): T0-T30 binh thuong (RAW/AI/WORKER/MANAGER/UI deu
tien trien, classify_pipeline_health() -> LIVE); T30 dong bang QTimer preview CUA
CAMERA --freeze-camera (KHONG dung worker/RTSP/AI, KHONG dong den bat ky camera nao
khac trong --include-camera) -> T30-T45 RAW/AI/WORKER PREVIEW tiep tuc tien trien
nhung MANAGER khong con emit -> classify_pipeline_health() ky vong
PREVIEW_DOWNSTREAM_STALE (KHONG phai CAPTURE_STALE/AI_STALE/WORKER_PREVIEW_STALE); T45
tiep tuc timer -> tro lai LIVE. KHONG co camera restart, KHONG RTSP reconnect, KHONG
PARK_END, KHONG thao tac session/track/occupancy nao trong toan bo qua trinh nay -
script CHI goi CameraManager.debug_freeze_preview_timer(), dung nguyen ham da co san
tu Phase 4.7E-B1.
"""
from __future__ import annotations

import argparse
import logging
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

PRODUCTION_DATABASE_PATH = (PROJECT_ROOT / "data" / "parking.db").resolve()


def _reject_production_database(database_path: Path) -> None:
    """Bao ve tuyet doi: TU CHOI chay neu --database trung voi production DB (sau khi
    resolve() de bat ca duong dan tuong doi/khac nhau tro toi cung mot file). Khong
    thuc hien bat ky hanh dong nao khac truoc khi kiem tra nay (khong apply_environment,
    khong subprocess, khong QApplication) - day la dong kiem tra DAU TIEN trong main()."""
    resolved = database_path.resolve()
    if resolved == PRODUCTION_DATABASE_PATH:
        raise SystemExit(
            "REFUSED: script chan doan Phase 4.7E-B1.1/B1.2 nay khong duoc phep chay voi co "
            f"so du lieu san xuat ({PRODUCTION_DATABASE_PATH}). Hay truyen --database tro toi mot "
            "file DB TEST/DEBUG rieng biet (vd .\\data\\runtime_debug\\phase47e_4cam_common.db)."
        )


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Phase 4.7E-B1.1/B1.2 - Windows real-app preview-freeze diagnostic (DEBUG/TEST-ONLY, "
                    "khong phai production code path)."
    )
    parser.add_argument("--camera", default=None,
                         help="CHE DO CU (tuong thich nguoc): DUNG MOT camera_code lam CA topology LAN muc "
                              "tieu dong bang. KHONG duoc dung cung luc voi --include-camera/--freeze-camera.")
    parser.add_argument("--include-camera", action="append", default=[], dest="include_camera",
                         help="CHE DO MOI: camera_code se duoc dua vao DB debug va khoi dong that (co the lap "
                              "lai nhieu lan, vd 3 DDNS + 1 LAN). Phai di kem --freeze-camera.")
    parser.add_argument("--freeze-camera", default=None, dest="freeze_camera",
                         help="CHE DO MOI: CHINH XAC MOT camera_code (phai nam trong tap --include-camera) se "
                              "bi dong bang preview timer co chu dich - cac camera --include-camera khac KHONG "
                              "bi dong cham.")
    parser.add_argument("--source-database", default=None, dest="source_database", type=Path,
                         help="Chuyen tiep nguyen ven cho scripts/prepare_debug_2zones.py --source-database "
                              "(mac dinh: khong truyen gi ca, de prepare_debug_2zones.py tu dung mac dinh cua "
                              "no la production DB - giu nguyen hanh vi B1.1). Vi du: mot DB smoke/debug da co "
                              "san dung cau hinh camera that (data/runtime_debug/phase47a_4cam_smoke.db).")
    parser.add_argument("--database", required=True, type=Path, help="Duong dan DB TEST/DEBUG (BAT BUOC, khong duoc la data/parking.db).")
    parser.add_argument("--device", choices=("auto", "cpu", "cuda:0"), default="auto")
    parser.add_argument("--normal-seconds", type=float, default=30.0, help="Thoi gian chay binh thuong truoc khi dong bang preview timer.")
    parser.add_argument("--freeze-seconds", type=float, default=15.0, help="Thoi gian giu preview timer bi dong bang.")
    parser.add_argument("--after-seconds", type=float, default=30.0, help="Thoi gian quan sat sau khi tiep tuc (resume) preview timer.")
    return parser.parse_args(argv)


def resolve_camera_selection(args) -> tuple[tuple[str, ...], str]:
    """Phase 4.7E-B1.2 muc 5 - tach TOPOLOGY (--include-camera, cameras se chay that)
    khoi MUC TIEU DONG BANG (--freeze-camera, CHINH XAC MOT camera trong tap do). Tra
    ve (include_cameras: tuple, freeze_camera: str). Khong bao gio suy doan mot cach am
    tham - moi truong hop mo ho deu bi TU CHOI ro rang (SystemExit) thay vi doan y dinh
    nguoi dung."""
    legacy_given = args.camera is not None
    new_mode_given = bool(args.include_camera) or args.freeze_camera is not None
    if legacy_given and new_mode_given:
        raise SystemExit(
            "CAMERA_SELECTION_AMBIGUOUS: khong duoc dung dong thoi --camera (che do cu, 1 camera) va "
            "--include-camera/--freeze-camera (che do moi, nhieu camera) trong cung mot lan goi - chon MOT trong hai."
        )
    if legacy_given:
        # Che do cu B1.1: 1 camera duy nhat vua la topology vua la muc tieu dong bang.
        return (args.camera,), args.camera
    if not args.include_camera:
        raise SystemExit(
            "CAMERA_SELECTION_REQUIRED: phai truyen --camera CODE (che do cu, 1 camera) HOAC it nhat mot "
            "--include-camera CODE cung --freeze-camera CODE (che do moi, nhieu camera)."
        )
    if args.freeze_camera is None:
        raise SystemExit(
            "FREEZE_CAMERA_REQUIRED: che do nhieu camera (--include-camera) bat buoc phai chi dinh ro "
            "--freeze-camera CODE - script se KHONG tu doan camera nao la muc tieu dong bang."
        )
    include_cameras = tuple(args.include_camera)
    if len(set(include_cameras)) != len(include_cameras):
        raise SystemExit(f"DUPLICATE_INCLUDE_CAMERA: {include_cameras}")
    if args.freeze_camera not in include_cameras:
        raise SystemExit(
            f"FREEZE_CAMERA_NOT_IN_INCLUDED_SET: freeze_camera={args.freeze_camera!r} khong nam trong "
            f"include_cameras={include_cameras!r} - camera muc tieu dong bang PHAI thuoc tap camera duoc dua "
            "vao DB debug va khoi dong that."
        )
    return include_cameras, args.freeze_camera


def _prepare_debug_database(database_path: Path, include_cameras, source_database=None) -> None:
    """Goi NGUYEN VEN scripts/prepare_debug_2zones.py da co san (khong viet lai logic
    sao chep camera) - dung dung cach run_app.py::prepare_debug_database() da goi no,
    de dam bao hanh vi giong het duong dan debug binh thuong da duoc kiem chung truoc
    day, mo rong sang N camera (Phase 4.7E-B1.2) thay vi 1. Script con nay CHI DOC DB
    nguon (SELECT, mac dinh production neu khong truyen --source-database), KHONG BAO
    GIO UPDATE/DELETE no, va thoat truoc khi tien trinh GUI chinh duoc khoi dong."""
    command = [sys.executable, str(PROJECT_ROOT / "scripts" / "prepare_debug_2zones.py"),
               "--target", str(database_path)]
    for code in include_cameras:
        command.extend(["--camera", code])
    if source_database is not None:
        command.extend(["--source-database", str(source_database)])
    subprocess.run(command, cwd=PROJECT_ROOT, check=True)


def main(argv=None) -> int:
    args = parse_args(argv)
    _reject_production_database(args.database)
    include_cameras, freeze_camera = resolve_camera_selection(args)

    from app.core.runtime_config import RuntimeConfig

    config = RuntimeConfig(mode="debug", device=args.device, max_cameras=len(include_cameras), cameras=include_cameras,
                            database_path=args.database, fallback_min_cameras=1, auto_scale=False,
                            benchmark_duration=180, startup_dialog=False)
    config.apply_environment(PROJECT_ROOT)
    _prepare_debug_database(args.database, include_cameras, args.source_database)

    from app.core.config import Settings
    settings = Settings()

    from run_app import ensure_detector_model
    model_error = ensure_detector_model(settings)
    if model_error:
        print(model_error, file=sys.stderr)
        return 3

    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    from app.core.logging_config import configure_logging
    from app.core.paths import ensure_directories
    from app.database.migrations import init_database
    from app.ui.main_window import MainWindow

    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("Parking Monitoring System - Phase 4.7E-B1.1/B1.2 diagnostic")
    ensure_directories()
    configure_logging()
    init_database()

    log = logging.getLogger("phase_4_7e_b1_1_diagnostic")
    # QUAN TRONG: MainWindow duoc tao TRONG CHINH tien trinh Python nay, dung QApplication
    # duy nhat vua duoc tao o tren - day la bang chung ("proof it executes inside the same
    # QApplication process", yeu cau muc E) rang khong co subprocess/IPC nao duoc dung cho
    # ban than buoc freeze/resume (subprocess DUY NHAT trong toan bo script la
    # prepare_debug_2zones.py o tren, va no da THOAT truoc khi dong code nay chay).
    window = MainWindow(settings)
    window.show()

    def _camera_id(camera_code):
        camera = next((c for c in window.cameras.list() if c.camera_code == camera_code), None)
        if camera is None:
            log.error("Phase 4.7E-B1.1/B1.2 diagnostic: khong tim thay camera_code=%s trong DB debug", camera_code)
            return None
        return camera.id

    def _freeze():
        camera_id = _camera_id(freeze_camera)
        if camera_id is None:
            return
        ok = window.manager.debug_freeze_preview_timer(camera_id, True)
        log.warning("Phase 4.7E-B1.1/B1.2 diagnostic: FREEZE preview timer camera=%s camera_id=%s ok=%s "
                    "include_cameras=%s - ky vong classify_pipeline_health() -> PREVIEW_DOWNSTREAM_STALE cho "
                    "camera=%s trong khi RAW/AI/WORKER PREVIEW van tien trien; cac camera khac trong "
                    "include_cameras KHONG bi dong cham.", freeze_camera, camera_id, ok, include_cameras, freeze_camera)

    def _resume():
        camera_id = _camera_id(freeze_camera)
        if camera_id is None:
            return
        ok = window.manager.debug_freeze_preview_timer(camera_id, False)
        log.warning("Phase 4.7E-B1.1/B1.2 diagnostic: RESUME preview timer camera=%s camera_id=%s ok=%s "
                    "- ky vong classify_pipeline_health() tro lai LIVE cho camera=%s. Cac camera DDNS khac (neu "
                    "co) van co the o trang thai CAMERA_OFFLINE/dang ket noi lai mot cach doc lap - day KHONG "
                    "phai loi cua bai chan doan preview-freeze nay.", freeze_camera, camera_id, ok, freeze_camera)

    def _finish():
        log.warning("Phase 4.7E-B1.1/B1.2 diagnostic: het khung thoi gian quan sat (normal=%.1fs freeze=%.1fs "
                    "after=%.1fs) cho freeze_camera=%s - ung dung TIEP TUC chay binh thuong, khong tu dong "
                    "dong/khong tu dong khoi dong lai camera nao.", args.normal_seconds, args.freeze_seconds,
                    args.after_seconds, freeze_camera)

    QTimer.singleShot(int(args.normal_seconds * 1000), _freeze)
    QTimer.singleShot(int((args.normal_seconds + args.freeze_seconds) * 1000), _resume)
    QTimer.singleShot(int((args.normal_seconds + args.freeze_seconds + args.after_seconds) * 1000), _finish)

    log.warning("Phase 4.7E-B1.1/B1.2 diagnostic scheduled include_cameras=%s freeze_camera=%s database=%s "
                "source_database=%s normal_seconds=%.1f freeze_seconds=%.1f after_seconds=%.1f - loc log theo "
                "camera=%s de danh gia rieng telemetry preview cua no; xem 'Pipeline diagnostic' va "
                "'GUI_EVENT_LOOP_DELAY' (neu co) tu _check_pipeline_health().",
                include_cameras, freeze_camera, args.database, args.source_database,
                args.normal_seconds, args.freeze_seconds, args.after_seconds, freeze_camera)

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
