"""Read-only audit of open parking sessions. This script never mutates the database."""
import argparse,json,sqlite3
from pathlib import Path


def iou(a,b):
    if not a or not b: return 0.0
    left=max(a[0],b[0]); top=max(a[1],b[1]); right=min(a[2],b[2]); bottom=min(a[3],b[3]); inter=max(0,right-left)*max(0,bottom-top); aa=max(0,a[2]-a[0])*max(0,a[3]-a[1]); bb=max(0,b[2]-b[0])*max(0,b[3]-b[1]); return inter/(aa+bb-inter) if aa+bb-inter else 0.0


def audit(database,camera_code,runtime_count=None):
    connection=sqlite3.connect(f"file:{Path(database).resolve().as_posix()}?mode=ro",uri=True); connection.row_factory=sqlite3.Row
    camera=connection.execute("SELECT * FROM cameras WHERE camera_code=?",(camera_code,)).fetchone()
    if not camera: raise SystemExit(f"Camera not found: {camera_code}")
    rows=connection.execute("SELECT * FROM parking_sessions WHERE camera_id=? AND left_at IS NULL ORDER BY parked_at,id",(camera["id"],)).fetchall(); links=connection.execute("SELECT ps.session_code,vt.tracker_track_id FROM vehicle_track_links vt JOIN parking_sessions ps ON ps.id=vt.session_id WHERE ps.camera_id=? AND ps.left_at IS NULL",(camera["id"],)).fetchall()
    by_track={}; conflicts=[]
    for link in links: by_track.setdefault(link["tracker_track_id"],[]).append(link["session_code"])
    for track,sessions in by_track.items():
        if len(sessions)>1: conflicts.append({"track":track,"sessions":sessions})
    overlaps=[]
    for index,left in enumerate(rows):
        for right in rows[index+1:]:
            score=iou(json.loads(left["confirmed_bbox"]) if left["confirmed_bbox"] else None,json.loads(right["confirmed_bbox"]) if right["confirmed_bbox"] else None)
            if score>=.55: overlaps.append({"sessions":[left["session_code"],right["session_code"]],"bbox_iou":round(score,3)})
    physical=runtime_count if runtime_count is not None else min(len(rows),int(camera["capacity"] or 1)); phantom=max(0,len(rows)-physical)
    report={"mode":"READ_ONLY_PREVIEW","camera":camera_code,"position":camera["parking_position_code"],"expected_physical_vehicles":physical,"open_sessions":len(rows),"potential_phantom_sessions":phantom,"session_runtime_mismatch":runtime_count is not None and len(rows)!=runtime_count,"session_codes":[row["session_code"] for row in rows],"linked_track_conflicts":conflicts,"overlapping_open_session_bboxes":overlaps,"session_start_key_conflicts":[]}
    connection.close(); return report


if __name__=="__main__":
    parser=argparse.ArgumentParser(); parser.add_argument("--camera",required=True); parser.add_argument("--database",default="data/parking.db"); parser.add_argument("--runtime-count",type=int); args=parser.parse_args(); print(json.dumps(audit(args.database,args.camera,args.runtime_count),ensure_ascii=False,indent=2))
