from __future__ import annotations

import argparse,json,sqlite3
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def audit(path):
    db=sqlite3.connect(path); db.row_factory=sqlite3.Row; columns={r[1] for r in db.execute("PRAGMA table_info(parking_sessions)")}; zone="COALESCE(physical_zone_id,camera_id)" if "physical_zone_id" in columns else "camera_id"
    rows=db.execute(f"SELECT id,session_code,{zone} zone_key,parking_position_code,vehicle_family,vehicle_class,parked_at,left_at,offline_started_at,dominant_color FROM parking_sessions ORDER BY parked_at" if "dominant_color" in columns else f"SELECT id,session_code,{zone} zone_key,parking_position_code,vehicle_family,vehicle_class,parked_at,left_at,offline_started_at,NULL dominant_color FROM parking_sessions ORDER BY parked_at").fetchall(); findings=[]
    for i,a in enumerate(rows):
        for b in rows[i+1:]:
            if a["zone_key"]!=b["zone_key"]: continue
            overlap=(a["left_at"] is None or b["parked_at"]<=a["left_at"]) and (b["left_at"] is None or a["parked_at"]<=b["left_at"])
            same_family=(a["vehicle_family"] or a["vehicle_class"])==(b["vehicle_family"] or b["vehicle_class"])
            if overlap and same_family:
                classification="CROSS_CAMERA_DUPLICATE" if a["parking_position_code"]!=b["parking_position_code"] else "DUPLICATE_SUSPECTED"
                findings.append({"classification":classification,"session_ids":[a["id"],b["id"]],"session_codes":[a["session_code"],b["session_code"]],"reason":"overlapping_time_same_zone_and_vehicle_family"})
    db.close(); return findings


if __name__=="__main__":
    p=argparse.ArgumentParser(); p.add_argument("--database",type=Path,default=ROOT/"data"/"parking.db"); p.add_argument("--output",type=Path); args=p.parse_args(); result={"mode":"PREVIEW","database_changed":False,"findings":audit(args.database),"note":"No session was merged or deleted."}; text=json.dumps(result,ensure_ascii=False,indent=2); print(text); args.output.write_text(text,encoding="utf-8") if args.output else None
