"""Copy one or more camera configurations (car-zone/motorcycle-zone) into an isolated
debug DB. Historically copied exactly one CAR_ZONE + one MOTORCYCLE_ZONE camera (hence
the filename) - Phase 4.7E-B1.2 extends this to an arbitrary number of --camera codes
(e.g. the real 4-camera field topology: 3 DDNS + 1 LAN) while keeping the original
--car/--motorcycle two-camera invocation fully backward compatible.

Phase 4.7E-B1.2 also adds --source-database: by default the source is STILL the real
production DB (data/parking.db, read-only, SELECT-only - never modified), preserving
every existing caller's behavior unchanged. Passing --source-database lets a caller
reuse camera configuration (rtsp_url, polygon_points, capacity, ...) already captured
in a PREVIOUS debug/smoke DB (e.g. data/runtime_debug/phase47a_4cam_smoke.db) instead
of the live production DB - useful when the production DB no longer has (or never had)
a convenient combination of camera rows, but an earlier debug DB already does. The
source DB - production or otherwise - is ALWAYS opened strictly read-only (SQLite URI
mode=ro) and is never written to. No parking_sessions/history/observation data is ever
read from the source or copied to the target - only cameras.* configuration.
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

PRODUCTION_DATABASE_PATH = (ROOT / "data" / "parking.db").resolve()


def parse_args(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--car", help="camera_code của CAR_ZONE (tương thích script cũ)")
    parser.add_argument("--motorcycle", help="camera_code của MOTORCYCLE_ZONE (tương thích script cũ)")
    parser.add_argument("--camera", action="append", default=[], help="camera_code, có thể lặp lại nhiều lần (không giới hạn ở 2 camera).")
    parser.add_argument("--source-database", default=str(PRODUCTION_DATABASE_PATH),
                         help="DB nguồn (CHỈ ĐỌC, SELECT-only) để sao chép cấu hình camera - MẶC ĐỊNH là "
                              "production DB (data/parking.db) để tương thích ngược tuyệt đối với mọi lệnh gọi "
                              "cũ. Phase 4.7E-B1.2: có thể trỏ tới một DB debug/smoke khác (vd đã có sẵn đúng "
                              "cấu hình 3 DDNS + 1 LAN) để tái sử dụng cấu hình camera THẬT đã lưu ở đó thay vì "
                              "luôn phải đọc lại từ production.")
    parser.add_argument("--target", default=str(ROOT / "data" / "runtime_debug" / "debug_2cams.db"))
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    codes = list(args.camera) or [code for code in (args.car, args.motorcycle) if code]
    if not codes: raise SystemExit("DEBUG_CAMERA_REQUIRED")
    if len(set(codes)) != len(codes):
        raise SystemExit("DEBUG_DUPLICATE_CAMERA: các camera phải khác nhau")

    source_path = Path(args.source_database).resolve()
    target_path = Path(args.target).resolve()

    # Phase 4.7E-B1.2 muc 8 - cac bao ve AN TOAN NGUON/DICH, kiem tra TRUOC bat ky ghi
    # nao (ke ca truoc target_path.parent.mkdir()) va TRUOC khi mo bat ky ket noi nao:
    if not source_path.is_file():
        raise SystemExit(f"DEBUG_SOURCE_DATABASE_NOT_FOUND: {source_path}")
    if target_path == PRODUCTION_DATABASE_PATH:
        raise SystemExit(f"DEBUG_TARGET_IS_PRODUCTION_DATABASE: {target_path}")
    if source_path == target_path:
        raise SystemExit(f"DEBUG_SOURCE_TARGET_SAME_PATH: {source_path}")

    target_path.parent.mkdir(parents=True, exist_ok=True)
    # CHI DOC: mo nguon bang SQLite URI mode=ro - bat ky no luc UPDATE/DELETE/INSERT vao
    # nguon (production hay khong) se that bai ngay tai tang driver, khong chi la quy uoc.
    source = sqlite3.connect(f"file:{source_path}?mode=ro", uri=True)
    source.row_factory = sqlite3.Row
    rows = []
    for code in codes:
        row = source.execute("SELECT * FROM cameras WHERE camera_code=?", (code,)).fetchone()
        if row is None or row["zone_type"] not in ("CAR_ZONE", "MOTORCYCLE_ZONE") or not row["rtsp_url"] or not row["polygon_points"]:
            raise SystemExit(f"DEBUG_CAMERA_INVALID: {code}")
        rows.append(row)
    os.environ["PARKING_DATABASE_URL"] = f"sqlite:///{target_path}"
    from app.database.migrations import init_database
    init_database()
    target = sqlite3.connect(target_path)
    columns = [r[1] for r in target.execute("PRAGMA table_info(cameras)") if r[1] != "id"]
    for row in rows:
        values = {key: row[key] for key in columns if key in row.keys()}
        values.update(enabled=1, processing_fps=min(4.0, float(values.get("processing_fps") or 4)), preview_fps=min(5.0, float(values.get("preview_fps") or 5)), detector_image_size=640, ai_debug_overlay=1)
        existing = target.execute("SELECT id FROM cameras WHERE camera_code=?", (values["camera_code"],)).fetchone()
        if existing:
            assignments = ",".join(f"{key}=?" for key in values)
            target.execute(f"UPDATE cameras SET {assignments} WHERE id=?", (*values.values(), existing[0]))
        else:
            names = ",".join(values); marks = ",".join("?" for _ in values)
            target.execute(f"INSERT INTO cameras ({names}) VALUES ({marks})", tuple(values.values()))
    selected = {r["camera_code"] for r in rows}
    marks=",".join("?" for _ in selected); target.execute(f"UPDATE cameras SET enabled=0 WHERE camera_code NOT IN ({marks})", tuple(selected))
    target.commit(); target.close(); source.close()
    print(f"DEBUG_DB_READY path={target_path} source={source_path} cameras={sorted(selected)} sessions_copied=0 main_db_untouched=true")
    return 0


if __name__ == "__main__": raise SystemExit(main())
