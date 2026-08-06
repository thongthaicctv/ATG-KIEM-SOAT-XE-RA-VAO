"""Copy exactly one car-zone and one motorcycle-zone camera into the isolated debug DB."""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--car", help="camera_code của CAR_ZONE (tương thích script cũ)")
    parser.add_argument("--motorcycle", help="camera_code của MOTORCYCLE_ZONE (tương thích script cũ)")
    parser.add_argument("--camera", action="append", default=[])
    parser.add_argument("--target", default=str(ROOT / "data" / "runtime_debug" / "debug_2cams.db"))
    args = parser.parse_args()
    codes = list(args.camera) or [code for code in (args.car, args.motorcycle) if code]
    if not codes: raise SystemExit("DEBUG_CAMERA_REQUIRED")
    if len(set(codes)) != len(codes):
        raise SystemExit("DEBUG_DUPLICATE_CAMERA: hai khu vực phải dùng hai camera khác nhau")
    source_path = ROOT / "data" / "parking.db"
    target_path = Path(args.target).resolve(); target_path.parent.mkdir(parents=True, exist_ok=True)
    if not source_path.is_file(): raise SystemExit(f"MAIN_DATABASE_NOT_FOUND: {source_path}")
    source = sqlite3.connect(source_path); source.row_factory = sqlite3.Row
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
    print(f"DEBUG_DB_READY path={target_path} cameras={sorted(selected)} sessions_copied=0 main_db_untouched=true")
    return 0


if __name__ == "__main__": raise SystemExit(main())
