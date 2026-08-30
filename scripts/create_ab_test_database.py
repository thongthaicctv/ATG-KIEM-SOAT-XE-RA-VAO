"""scripts/create_ab_test_database.py

Utility tao va quan ly DATABASE COPY RIENG cho A/B/C RTSP test (Phase 4 / Phase 4.1).
KHONG BAO GIO ghi truc tiep vao data/parking.db (DATABASE SAN XUAT DANG SONG).

KIEN TRUC (Phase 4.1 - moi): production DB chi duoc DOC qua sqlite3 backup API dung 1
lan de tao ra 1 PRISTINE SNAPSHOT (data/runtime_ab/<timestamp>/base/pristine.db). Sau khi
backup hoan tat va CA 2 connection da dong hoan toan, pristine duoc dung lam nguon (khong
phai production nua) de tao RIENG BIET 3 database doc lap:
  data/runtime_ab/<timestamp>/A/ab_test_A.db
  data/runtime_ab/<timestamp>/B/ab_test_B.db
  data/runtime_ab/<timestamp>/C/ab_test_C.db
Ca 4 file (pristine + A + B + C) deu bat dau giong het nhau ve du lieu. Tu do, Case A/B/C
chay RTSP that su doc lap - session/event Case A ghi vao KHONG bao gio lan sang B/C, vi
day la 3 file SQLite vat ly hoan toan tach biet (khong phai 1 file dung chung nhu Phase 4
ban dau - do la loi Phase 4.1 sua).

Ly do TRUOC DAY (Phase 4) dung 1 file dung chung cho ca A/B/C la khong cong bang: Case A
chay truoc co the tao parking_sessions/parking_events/track state, roi Case B/C ke thua
lai trang thai runtime cua Case A thay vi bat dau tu 1 snapshot nguyen ban.

Subcommand:
  prepare   - [MOI, KHUYEN NGHI DUNG] Tao pristine snapshot + 3 database doc lap A/B/C tu
              production, stamp sidecar metadata (*.meta.json, KHONG credential) cho ca 4
              file ngay luc tao. Day la entrypoint chinh cho Phase 4.1.
  backup    - [primitive cap thap, van giu de tuong thich] Tao 1 ban copy nhat quan cua 1
              source bat ky (mac dinh production DB) bang sqlite3 Connection.backup().
  describe  - Chi in ra model/imgsz/half cua 1 config (A/B/C) - KHONG dong cham DB nao.
  configure - Tren DUNG 1 DATABASE cua DUNG 1 CASE (khong bao gio la production DB, khong
              bao gio la pristine.db, khong bao gio la database da duoc dung cho case
              KHAC): bat (enabled=1) dung cac camera_code duoc chi dinh, tat (enabled=0)
              cac camera con lai, va set detector_image_size theo config A/B/C cho CAC
              CAMERA DO. Xac thuc "dung case" qua sidecar metadata (*.meta.json) do
              'prepare' da stamp san - neu metadata khong khop config duoc yeu cau ->
              AB_DATABASE_REUSE_FORBIDDEN.

              Ly do buoc set detector_image_size bat buoc: image_size thuc te dung khi
              predict() duoc doc TU CAMERA ROW trong DB (app/services/camera_worker.py:
              self.detector.detect(..., self.camera.detector_image_size)), KHONG phai tu
              Settings/env toan cuc. MODEL/DEVICE/HALF nguoc lai LA settings toan cuc (doc
              qua PARKING_DETECTOR_MODEL/_DEVICE/_HALF), nen duoc set qua environment
              variable boi run_rtsp_ab_test.ps1, KHONG can sua trong DB.

An toan:
  - Production DB CHI duoc doc 1 lan duy nhat (mode=ro qua URI) de tao pristine - khong
    bao gio duoc dung lam source truc tiep cho A/B/C (A/B/C luon copy tu pristine).
  - backup/prepare dung sqlite3 Connection.backup() (Python stdlib) - an toan voi WAL,
    khong dung Copy-Item/shutil.copy tren file co the dang mo.
  - Khong in RTSP URL/mat khau ra console hay vao sidecar metadata - chi in duong dan
    file, config, model, imgsz, camera_code.
  - configure KHONG dong cham cot nao khac ngoai enabled/detector_image_size (giu nguyen
    rtsp_url, polygon_points, vehicle_confidence, cac timer, zone_type, capacity, ignore
    zones, ...).
  - configure TU CHOI: production DB, pristine.db, va bat ky DB nao metadata cho thay da
    duoc gan cho 1 config KHAC - khong co unsafe override cho bat ky truong hop nao.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
PRODUCTION_DB_RELATIVE = Path("data") / "parking.db"

# Nguon su that DUY NHAT cho 3 cau hinh A/B/C - dung chung boi describe/prepare/configure
# va boi tests/test_phase_4_precision_ab.py. Precision CA 3 deu FP32 (half=False) - da xac
# nhan bang benchmark thuc te tren NVIDIA T600 4GB (Phase 3/3.1): FP16 cham hon FP32 tren
# GPU nay o ca 2 model/2 kich thuoc anh da do.
AB_TEST_CONFIGS = {
    "A": {"model": "yolo11n.pt", "imgsz": 640, "half": False},
    "B": {"model": "yolo11n.pt", "imgsz": 960, "half": False},
    "C": {"model": "yolo11s.pt", "imgsz": 640, "half": False},
}


class SourceNotFoundError(RuntimeError):
    """Source DB khong ton tai tren dia."""


class DestinationExistsError(RuntimeError):
    """Khong ghi de len 1 database dich da ton tai."""


class DatabaseNotFoundError(RuntimeError):
    """DB duoc chi dinh cho 'configure' chua ton tai - phai chay 'prepare' truoc."""


class ProductionDatabaseRefusedError(RuntimeError):
    """DB duoc chi dinh trung voi data/parking.db - TU CHOI de tranh ghi nham vao production."""


class PristineDatabaseRefusedError(RuntimeError):
    """DB duoc chi dinh la pristine.db (snapshot goc) - khong bao gio duoc configure truc tiep."""


class DatabaseReuseForbiddenError(RuntimeError):
    """DB duoc chi dinh da duoc 'prepare' gan cho 1 config KHAC (theo sidecar metadata)."""


class CameraNotFoundError(RuntimeError):
    """camera_code duoc chi dinh khong ton tai trong bang cameras cua DB dich."""


class ModelNotFoundError(RuntimeError):
    """File model .pt cho 1 config A/B/C khong ton tai duoi thu muc models/."""


class CudaUnavailableError(RuntimeError):
    """A/B test chi chay cuda:0 - khong fallback CPU."""


# scripts/run_rtsp_ab_test.ps1 thuc thi CUNG cac guard nay TRUC TIEP bang PowerShell
# (Test-Path cho model, mot lenh `python -c "import torch..."` cho CUDA) truoc khi goi
# subprocess Python nao khac - cac ham thuan duoi day phan anh CHINH XAC logic do de co
# the unit test duoc bang pytest, vi ban than 1 script .ps1 khong the pytest truc tiep.
MAX_AB_CAMERAS = 3


def resolve_model_path(models_dir: Path, config_key: str) -> Path:
    if config_key not in AB_TEST_CONFIGS:
        raise ValueError(f"AB_TEST_UNKNOWN_CONFIG: {config_key} (hop le: {sorted(AB_TEST_CONFIGS)})")
    return Path(models_dir) / AB_TEST_CONFIGS[config_key]["model"]


def ensure_model_present(models_dir: Path, config_key: str) -> Path:
    """Fail-fast neu file model .pt cua config chua ton tai tren dia - khong bao gio de
    Ultralytics tu tai (dung logic voi scripts/benchmark_yolo_models.py::validate_model_path,
    duoc viet rieng o day de create_ab_test_database.py khong phu thuoc module benchmark)."""
    path = resolve_model_path(models_dir, config_key)
    if not path.is_file():
        raise ModelNotFoundError(f"AB_MODEL_NOT_FOUND: {path}")
    return path


def ensure_cuda_available(cuda_available: bool) -> None:
    """A/B test chi chay cuda:0 - khong fallback CPU im lang. `cuda_available` do caller
    truyen vao (vd ket qua cua torch.cuda.is_available()) de ham nay khong phu thuoc
    torch that, giup unit test duoc ma khong can GPU/torch cai san."""
    if not cuda_available:
        raise CudaUnavailableError("AB_CUDA_UNAVAILABLE: CUDA khong kha dung - A/B test khong fallback CPU.")


def validate_camera_selection(camera_codes: list[str], max_cameras: int) -> None:
    """Phase 4 chi cho phep toi da 3 camera, va so camera duoc chon phai KHOP CHINH XAC
    voi max_cameras (tranh truong hop -MaxCameras va -Cameras lech nhau gay nham lan ve
    so camera thuc su chay)."""
    if max_cameras > MAX_AB_CAMERAS:
        raise ValueError(f"AB_TEST_MAX_CAMERAS_EXCEEDS_LIMIT: {max_cameras} > {MAX_AB_CAMERAS}")
    if len(camera_codes) != max_cameras:
        raise ValueError(
            f"AB_TEST_CAMERA_COUNT_MISMATCH: {len(camera_codes)} camera duoc chon nhung max_cameras={max_cameras}"
        )


def resolve_production_db_path(root: Path = ROOT_DIR) -> Path:
    return (root / PRODUCTION_DB_RELATIVE).resolve()


def _normalized(path: Path) -> str:
    try:
        candidate = Path(path).resolve()
    except OSError:
        candidate = Path(path).absolute()
    # os.path.normcase: Windows filesystem khong phan biet hoa/thuong (vd D:\... vs
    # d:\...) trong khi Path.resolve() khong dam bao chuan hoa case tren moi truong hop.
    return os.path.normcase(str(candidate))


def is_production_database(database: Path, root: Path = ROOT_DIR) -> bool:
    """So sanh duong dan da resolve (tuyet doi, khong phan biet hoa/thuong) - khong so
    sanh chuoi tho, de khong bi qua mat boi duong dan tuong doi."""
    return _normalized(database) == _normalized(resolve_production_db_path(root))


# --- Sidecar metadata (*.meta.json) --------------------------------------------------
#
# KHONG them schema/cot moi vao DB (theo yeu cau Phase 4.1) - moi provenance (config nao
# so huu database nao, tao tu snapshot nao, luc nao) duoc luu trong 1 file JSON canh file
# .db (vd ab_test_A.db -> ab_test_A.meta.json). File nay la nguon su that de 'configure'
# tu choi tai su dung nham 1 database cho config khac (AB_DATABASE_REUSE_FORBIDDEN) va de
# tu choi configure truc tiep len pristine.db. KHONG bao gio ghi RTSP URL/mat khau vao day
# - chi ghi config/model/imgsz/precision/duong dan/thoi diem tao.

def metadata_path_for(db_path: Path) -> Path:
    db_path = Path(db_path)
    return db_path.with_name(db_path.stem + ".meta.json")


def read_metadata(db_path: Path) -> dict | None:
    meta_path = metadata_path_for(db_path)
    if not meta_path.is_file():
        return None
    return json.loads(meta_path.read_text(encoding="utf-8"))


def write_metadata(db_path: Path, metadata: dict) -> Path:
    meta_path = metadata_path_for(db_path)
    meta_path.write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")
    return meta_path


# --- Backup primitive ------------------------------------------------------------------

def backup_sqlite_database(source: Path, target: Path) -> Path:
    """Primitive cap thap: 1 ban copy NHAT QUAN cua source -> target bang sqlite3
    Connection.backup() (an toan voi WAL/dang mo). KHONG sua doi source. Fail neu source
    khong ton tai. KHONG ghi de 1 target da ton tai. Ca 2 connection duoc dong HOAN TOAN
    truoc khi ham tra ve - dam bao goi lai ham nay voi target lam source moi (vd pristine
    -> A/B/C) luon doc duoc trang thai da flush day du, khong bao gio doc mot file dang
    con connection mo."""
    source = Path(source)
    if not source.is_file():
        raise SourceNotFoundError(f"AB_TEST_SOURCE_NOT_FOUND: {source}")
    target = Path(target)
    if target.exists():
        raise DestinationExistsError(f"AB_TEST_DESTINATION_EXISTS: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)

    # mode=ro: mo source CHI DOC qua URI - khong co nguy co ghi nham vao source (production
    # hoac pristine) du code sau nay co thay doi. backup() tu xu ly dung WAL/snapshot nhat quan.
    source_conn = sqlite3.connect(f"file:{source.as_posix()}?mode=ro", uri=True)
    try:
        dest_conn = sqlite3.connect(target)
        try:
            source_conn.backup(dest_conn)
        finally:
            dest_conn.close()
    finally:
        source_conn.close()
    return target


def backup_database(source: Path, dest_dir: Path, timestamp: str | None = None) -> Path:
    """[primitive cap thap, van giu de tuong thich nguoc] Tao 1 ban copy don le tai
    <dest_dir>/<timestamp>/ab_test.db. Cho A/B/C isolation THUC SU, dung 'prepare' thay
    vi ham nay - ham nay chi tao 1 file duy nhat, khong tu tach 3 case doc lap."""
    ts = timestamp or datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    target = Path(dest_dir) / ts / "ab_test.db"
    backup_sqlite_database(source, target)
    print(f"AB_DB_BACKUP_READY source={source} target={target}")
    return target


def prepare_ab_test_databases(source: Path, dest_dir: Path, timestamp: str | None = None) -> dict:
    """[MOI - Phase 4.1] Entrypoint chinh: production (source) CHI duoc doc 1 lan de tao
    pristine snapshot; sau khi pristine dong HOAN TOAN, tao RIENG BIET 3 database A/B/C tu
    pristine (khong bao gio tu source/production truc tiep). Stamp sidecar metadata cho ca
    4 file ngay khi tao - day la co so de 'configure' xac thuc chong tai su dung nham sau
    nay. Tra ve {"pristine": Path, "cases": {"A": Path, "B": Path, "C": Path}}."""
    ts = timestamp or datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    run_dir = Path(dest_dir) / ts
    created_at = datetime.now().isoformat()

    pristine_path = run_dir / "base" / "pristine.db"
    backup_sqlite_database(source, pristine_path)
    write_metadata(pristine_path, {"role": "pristine", "source": str(source), "created_at": created_at})
    print(f"AB_PRISTINE_READY source={source} pristine={pristine_path}")

    cases: dict[str, Path] = {}
    for key in sorted(AB_TEST_CONFIGS):
        cfg = AB_TEST_CONFIGS[key]
        case_path = run_dir / key / f"ab_test_{key}.db"
        # Nguon la PRISTINE (da dong hoan toan o buoc tren), KHONG bao gio la `source`
        # (production) lan thu 2 - moi case doc lap voi nhau va voi production tu day.
        backup_sqlite_database(pristine_path, case_path)
        write_metadata(
            case_path,
            {
                "config": key,
                "model": cfg["model"],
                "imgsz": cfg["imgsz"],
                "precision": "FP16" if cfg["half"] else "FP32",
                "source_snapshot": str(pristine_path),
                "created_at": created_at,
            },
        )
        print(f"AB_CASE_DB_READY config={key} database={case_path}")
        cases[key] = case_path

    return {"pristine": pristine_path, "cases": cases}


def describe_config(config_key: str) -> dict:
    """In ra (va tra ve) model/imgsz/half cua 1 config A/B/C - KHONG dong cham DB nao.
    Dinh dang key=value moi dong de PowerShell parse de dang."""
    if config_key not in AB_TEST_CONFIGS:
        raise ValueError(f"AB_TEST_UNKNOWN_CONFIG: {config_key} (hop le: {sorted(AB_TEST_CONFIGS)})")
    cfg = AB_TEST_CONFIGS[config_key]
    print(f"CONFIG={config_key}")
    print(f"MODEL={cfg['model']}")
    print(f"IMGSZ={cfg['imgsz']}")
    print(f"HALF={'true' if cfg['half'] else 'false'}")
    return cfg


def configure_database(
    database: Path,
    config_key: str,
    camera_codes: list[str],
    root: Path = ROOT_DIR,
) -> dict:
    """Tren DUNG 1 database cua DUNG 1 case (chua qua 'prepare', metadata phai khop
    config_key): bat cac camera_code duoc chi dinh, tat cac camera con lai, va set
    detector_image_size theo config. CHI dong cham 2 cot: enabled, detector_image_size -
    moi thu khac (rtsp_url, polygon_points, vehicle_confidence, timers, zone_type,
    capacity, ignore_zones, ...) giu nguyen tu pristine."""
    database = Path(database)
    if is_production_database(database, root):
        raise ProductionDatabaseRefusedError(
            f"AB_TEST_REFUSES_PRODUCTION_DB: {database} trung voi database production "
            f"({resolve_production_db_path(root)}). A/B test PHAI dung 1 database rieng "
            "cho tung case (xem subcommand 'prepare')."
        )
    if not database.is_file():
        raise DatabaseNotFoundError(f"AB_TEST_DATABASE_NOT_FOUND: {database} (hay chay 'prepare' truoc)")
    if config_key not in AB_TEST_CONFIGS:
        raise ValueError(f"AB_TEST_UNKNOWN_CONFIG: {config_key} (hop le: {sorted(AB_TEST_CONFIGS)})")

    # Metadata=None nghia la database nay CHUA TUNG duoc 'prepare' stamp (vd tao qua
    # 'backup' primitive cap thap cho tuong thich nguoc, hoac test tu tao DB truc tiep) -
    # trong truong hop do KHONG co co so de biet no "thuoc ve" config nao, nen bo qua guard
    # nay (giu tuong thich nguoc). Guard CHI kich hoat khi sidecar metadata THUC SU ton tai
    # va NEU no co field "config" thi field do PHAI khop config_key dang yeu cau - day la
    # truong hop cua moi database do 'prepare' tao (luon duoc stamp ngay khi tao).
    metadata = read_metadata(database)
    if metadata is not None and metadata.get("role") == "pristine":
        raise PristineDatabaseRefusedError(
            f"AB_TEST_REFUSES_PRISTINE_DB: {database} la pristine snapshot - khong duoc "
            "configure truc tiep. Dung database rieng cua tung case (ab_test_<config>.db) "
            "duoc 'prepare' tao tu snapshot nay."
        )
    if metadata is not None:
        existing_config = metadata.get("config")
        if existing_config is not None and existing_config != config_key:
            raise DatabaseReuseForbiddenError(
                f"AB_DATABASE_REUSE_FORBIDDEN: {database} duoc gan cho config={existing_config!r} "
                f"(theo {metadata_path_for(database).name}), nhung dang duoc yeu cau chay nhu "
                f"config={config_key!r}. Moi case A/B/C PHAI dung database rieng do 'prepare' tao "
                "- khong dung chung 1 database cho 2 config khac nhau."
            )

    codes = list(camera_codes)
    if not codes:
        raise ValueError("AB_TEST_NO_CAMERAS_SPECIFIED: can it nhat 1 --camera")
    if len(set(codes)) != len(codes):
        raise ValueError("AB_TEST_DUPLICATE_CAMERA: danh sach --camera co ma trung lap")

    imgsz = AB_TEST_CONFIGS[config_key]["imgsz"]
    conn = sqlite3.connect(database)
    try:
        marks = ",".join("?" for _ in codes)
        existing = {
            row[0]
            for row in conn.execute(f"SELECT camera_code FROM cameras WHERE camera_code IN ({marks})", codes)
        }
        missing = [code for code in codes if code not in existing]
        if missing:
            raise CameraNotFoundError(f"AB_TEST_CAMERA_NOT_FOUND: {missing} khong co trong {database}")

        conn.execute(
            f"UPDATE cameras SET enabled=1, detector_image_size=? WHERE camera_code IN ({marks})",
            (imgsz, *codes),
        )
        conn.execute(f"UPDATE cameras SET enabled=0 WHERE camera_code NOT IN ({marks})", codes)
        conn.commit()
    finally:
        conn.close()

    result = {"database": str(database), "config": config_key, "imgsz": imgsz, "cameras": sorted(codes)}
    print(
        f"AB_DB_CONFIGURED database={database} config={config_key} "
        f"model={AB_TEST_CONFIGS[config_key]['model']} imgsz={imgsz} half=false cameras={sorted(codes)}"
    )
    return result


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Tao/quan ly database rieng cho A/B/C RTSP test (Phase 4 / 4.1).")
    sub = p.add_subparsers(dest="command", required=True)

    prepare_p = sub.add_parser("prepare", help="[Khuyen nghi] Tao pristine snapshot + 3 DB doc lap A/B/C.")
    prepare_p.add_argument("--source", type=Path, default=ROOT_DIR / PRODUCTION_DB_RELATIVE)
    prepare_p.add_argument("--dest-dir", type=Path, default=ROOT_DIR / "data" / "runtime_ab")

    backup_p = sub.add_parser("backup", help="[Primitive cap thap] Tao 1 ban copy don le cua 1 source.")
    backup_p.add_argument("--source", type=Path, default=ROOT_DIR / PRODUCTION_DB_RELATIVE)
    backup_p.add_argument("--dest-dir", type=Path, default=ROOT_DIR / "data" / "runtime_ab")

    describe_p = sub.add_parser("describe", help="In model/imgsz/half cua 1 config - khong dong DB.")
    describe_p.add_argument("--config", required=True, choices=sorted(AB_TEST_CONFIGS))

    configure_p = sub.add_parser("configure", help="Chon camera + set imgsz tren DUNG 1 database cua DUNG 1 case.")
    configure_p.add_argument("--database", type=Path, required=True)
    configure_p.add_argument("--config", required=True, choices=sorted(AB_TEST_CONFIGS))
    configure_p.add_argument("--camera", action="append", default=[], dest="cameras")

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "prepare":
            prepare_ab_test_databases(args.source, args.dest_dir)
            return 0
        if args.command == "backup":
            backup_database(args.source, args.dest_dir)
            return 0
        if args.command == "describe":
            describe_config(args.config)
            return 0
        if args.command == "configure":
            configure_database(args.database, args.config, args.cameras)
            return 0
    except (
        SourceNotFoundError,
        DestinationExistsError,
        DatabaseNotFoundError,
        ProductionDatabaseRefusedError,
        PristineDatabaseRefusedError,
        DatabaseReuseForbiddenError,
        CameraNotFoundError,
        ValueError,
    ) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
