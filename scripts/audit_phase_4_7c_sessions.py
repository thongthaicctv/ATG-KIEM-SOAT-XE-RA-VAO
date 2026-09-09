"""scripts/audit_phase_4_7c_sessions.py

Phase 4.7C - SESSION RUNTIME RECONCILIATION (muc 6: audit doc-lap, CHI DOC).

Script DOC-LAP, CHI-DOC (read-only): mo mot file SQLite parking.db (production
HOAC mot test-DB snapshot) qua URI "file:<path>?mode=ro" (SQLite se TU CHOI moi
lenh ghi - khong phu thuoc vao viec code Python co "co gang" ghi hay khong), roi
in ra bao cao con nguoi doc duoc (--format text, mac dinh) va/hoac JSON may doc
duoc (--format json hoac --json-out <path>) ve trang thai vong doi parking_sessions/
vehicle_track_links/vehicle_identities/vehicle_observations/parking_events.

KHONG:
- UPDATE / DELETE / INSERT / VACUUM / migration / repair / reconciliation write
  vao BAT KY database nao no mo (production hay test).
- Sua chua (repair) bat ky du lieu nao - CHI phan loai/bao cao.
- Chua RTSP credential (script nay khong doc rtsp_url tru khi --show-rtsp-url
  duoc truyen tuong minh, va ke ca khi do se bi mask qua mask_rtsp_url-style).
- Phu thuoc PySide6/SQLAlchemy/CUDA - CHI dung sqlite3 chuan cua Python, de co
  the chay doc lap tren BAT KY may nao co Python 3, khong can moi truong .venv
  day du cua ung dung (huu ich khi kiem tra production tu xa/read-only).

Cach chay (vi du - LUON truyen duong dan CHINH XAC, KHONG co gia tri mac dinh
ngam dinh tro toi production, de tranh vo tinh audit nham file):

    python3 scripts/audit_phase_4_7c_sessions.py --db data/parking.db
    python3 scripts/audit_phase_4_7c_sessions.py --db data/parking.db --json-out reports/session_audit/phase47c_before.json
    python3 scripts/audit_phase_4_7c_sessions.py --db data/runtime_session_audit/<ts>/repro/phase47c_repro.db

An toan production: --db LUON duoc mo qua "file:<path>?mode=ro" (SQLite read-only
URI) - BAT KY lenh ghi nao (kie ca vo tinh trong mot ban vas cua script tuong lai)
se bi chinh SQLite tu choi voi loi "attempt to write a readonly database", KHONG
phu thuoc vao ky luat cua nguoi viet code. Script nay khong bao gio tu goi
sqlite3.connect() o che do khac ngoai mode=ro.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path


# ---------------------------------------------------------------------------
# Ket noi CHI-DOC - noi DUY NHAT trong file nay mo ket noi SQLite.
# ---------------------------------------------------------------------------

def open_readonly(db_path: str) -> sqlite3.Connection:
    path = Path(db_path)
    if not path.exists():
        raise FileNotFoundError(f"Khong tim thay database: {db_path}")
    uri = f"file:{path.resolve().as_posix()}?mode=ro"
    con = sqlite3.connect(uri, uri=True)
    con.row_factory = sqlite3.Row
    # Xac nhan THAT SU khong ghi duoc - thu 1 lenh ghi vo hai (se bi tu choi).
    try:
        con.execute("CREATE TABLE __phase47c_write_probe__ (x INTEGER)")
        con.rollback()
        raise RuntimeError(
            "CANH BAO AN TOAN: ket noi toi database nay KHONG o che do read-only "
            "nhu mong doi - dung lai ngay, khong audit tiep."
        )
    except sqlite3.OperationalError:
        pass  # DUNG nhu mong doi: "attempt to write a readonly database"
    return con


def fetch_all(con, query, params=()):
    return [dict(row) for row in con.execute(query, params).fetchall()]


# ---------------------------------------------------------------------------
# Muc 7: phan loai parking_sessions theo A..I
# ---------------------------------------------------------------------------

def classify_sessions(sessions: list[dict], now_iso: str) -> dict:
    categories = defaultdict(list)
    for s in sessions:
        sid = s["id"]
        left_at = s["left_at"]
        status = s["status"]
        entered_at = s["entered_at"]
        parked_at = s["parked_at"]
        if left_at is None:
            categories["A_ACTIVE_left_at_null"].append(sid)
        else:
            categories["B_COMPLETED_left_at_set"].append(sid)
        if status == "RECOVERED":
            categories["C_RECOVERED"].append(sid)
        if left_at is None and entered_at and parked_at:
            try:
                entered_dt = datetime.fromisoformat(entered_at)
                if entered_dt.tzinfo is None:
                    entered_dt = entered_dt.replace(tzinfo=timezone.utc)
                now_dt = datetime.fromisoformat(now_iso)
                age_seconds = (now_dt - entered_dt).total_seconds()
                if age_seconds > 3600:
                    categories["D_ACTIVE_extremely_old"].append({"id": sid, "age_seconds": age_seconds})
            except ValueError:
                pass
        if entered_at and parked_at and entered_at > parked_at:
            categories["I_entered_after_parked"].append(sid)
        if left_at and parked_at and parked_at > left_at:
            categories["I_parked_after_left"].append(sid)
        if left_at is not None and status == "ACTIVE":
            categories["I_left_at_set_but_status_ACTIVE"].append(sid)
        if status == "COMPLETED" and left_at is None:
            categories["I_status_COMPLETED_but_left_at_null"].append(sid)
    return {k: v for k, v in categories.items()}


def annotate_track_link_ownership(sessions: list[dict], track_links: list[dict]) -> dict:
    links_by_session = defaultdict(list)
    for tl in track_links:
        links_by_session[tl["session_id"]].append(tl)
    open_sessions = {s["id"]: s for s in sessions if s["left_at"] is None}

    result = {
        "E_open_no_track_link_at_all": [],
        "F_open_no_active_track_link": [],
        "G_open_all_links_ended": [],
        "H_open_multiple_simultaneous_active_links": [],
        "stale_link_on_completed_session": [],
        "duplicate_link_same_track_same_session": [],
    }
    for sid, s in open_sessions.items():
        links = links_by_session.get(sid, [])
        if not links:
            result["E_open_no_track_link_at_all"].append(sid)
            continue
        active = [l for l in links if l["ended_at"] is None]
        if not active:
            result["F_open_no_active_track_link"].append(sid)
            result["G_open_all_links_ended"].append(sid)
        elif len(active) > 1:
            result["H_open_multiple_simultaneous_active_links"].append(
                {"session_id": sid, "active_link_count": len(active),
                 "active_track_ids": [l["tracker_track_id"] for l in active]}
            )

    for tl in track_links:
        s = next((s for s in sessions if s["id"] == tl["session_id"]), None)
        if s is not None and s["left_at"] is not None and tl["ended_at"] is None:
            result["stale_link_on_completed_session"].append(
                {"link_id": tl["id"], "session_id": tl["session_id"], "session_status": s["status"]}
            )

    seen = defaultdict(list)
    for tl in track_links:
        key = (tl["session_id"], tl["tracker_track_id"], tl["tracker_generation"])
        seen[key].append(tl["id"])
    for key, ids in seen.items():
        if len(ids) > 1:
            result["duplicate_link_same_track_same_session"].append(
                {"session_id": key[0], "tracker_track_id": key[1], "tracker_generation": key[2], "link_ids": ids}
            )
    return result


def track_ownership_conflicts(track_links: list[dict], sessions_by_id: dict) -> list[dict]:
    """Cung 1 (camera, tracker_track_id, tracker_generation) duoc >1 session CON MO
    so huu dong thoi qua mot track link CON active (ended_at IS NULL)."""
    by_key = defaultdict(set)
    for tl in track_links:
        session = sessions_by_id.get(tl["session_id"])
        if session is None or session["left_at"] is not None or tl["ended_at"] is not None:
            continue
        key = (session["camera_id"], tl["tracker_track_id"], tl["tracker_generation"])
        by_key[key].add(tl["session_id"])
    return [
        {"camera_id": k[0], "tracker_track_id": k[1], "tracker_generation": k[2], "session_ids": sorted(v)}
        for k, v in by_key.items() if len(v) > 1
    ]


def vehicle_instance_anomalies(sessions: list[dict]) -> dict:
    open_sessions = [s for s in sessions if s["left_at"] is None and s["vehicle_instance_id"]]
    by_instance = defaultdict(list)
    for s in open_sessions:
        by_instance[(s["camera_id"], s["vehicle_instance_id"])].append(s["id"])
    duplicates = [
        {"camera_id": k[0], "vehicle_instance_id": k[1], "session_ids": v}
        for k, v in by_instance.items() if len(v) > 1
    ]
    no_instance = [s["id"] for s in sessions if s["left_at"] is None and not s["vehicle_instance_id"]]
    return {"duplicate_open_sessions_same_vehicle_instance": duplicates,
            "open_sessions_without_vehicle_instance_id": no_instance}


def short_sessions(sessions: list[dict], threshold_seconds: int = 60) -> list[dict]:
    out = []
    for s in sessions:
        if s["left_at"] is not None and s["parking_duration_seconds"] is not None:
            if s["parking_duration_seconds"] <= threshold_seconds:
                out.append({"id": s["id"], "session_code": s["session_code"],
                             "duration_seconds": s["parking_duration_seconds"],
                             "camera_id": s["camera_id"], "vehicle_class": s["vehicle_class"],
                             "entered_at": s["entered_at"], "left_at": s["left_at"]})
    out.sort(key=lambda r: r["duration_seconds"])
    return out


def oldest_active(sessions: list[dict], now_iso: str) -> list[dict]:
    now_dt = datetime.fromisoformat(now_iso)
    out = []
    for s in sessions:
        if s["left_at"] is None:
            try:
                entered_dt = datetime.fromisoformat(s["entered_at"])
                if entered_dt.tzinfo is None:
                    entered_dt = entered_dt.replace(tzinfo=timezone.utc)
                age = (now_dt - entered_dt).total_seconds()
            except (ValueError, TypeError):
                age = None
            out.append({"id": s["id"], "session_code": s["session_code"], "camera_id": s["camera_id"],
                         "status": s["status"], "entered_at": s["entered_at"], "age_seconds": age})
    out.sort(key=lambda r: (r["age_seconds"] is None, -(r["age_seconds"] or 0)))
    return out


# ---------------------------------------------------------------------------
# Muc 12: phan biet LEGACY (truoc --new-since) vs MOI (tu --new-since tro di).
# --new-since mac dinh la THOI DIEM CHAY SCRIPT - lan chay dau tien tren mot DB
# se coi TOAN BO du lieu hien co la LEGACY (dung nhu ban chat that: du lieu do
# duoc tao TRUOC lan audit nay). Truyen --new-since tuong minh (vd thoi diem bat
# dau mot phien tai hien co kiem soat) de phan tach chinh xac session MOI duoc
# tao trong qua trinh tai hien Phase 4.7C.
# ---------------------------------------------------------------------------

def split_legacy_vs_new(sessions: list[dict], new_since_iso: str | None) -> dict:
    if not new_since_iso:
        return {"legacy_count": len(sessions), "new_count": 0, "new_since": None}
    legacy = [s for s in sessions if not s["created_at"] or s["created_at"] < new_since_iso]
    new = [s for s in sessions if s["created_at"] and s["created_at"] >= new_since_iso]
    return {"legacy_count": len(legacy), "new_count": len(new), "new_since": new_since_iso,
            "new_session_ids": [s["id"] for s in new]}


def build_report(con: sqlite3.Connection, db_path: str, new_since_iso: str | None) -> dict:
    now_dt = datetime.now(timezone.utc)
    now_iso = now_dt.isoformat()

    cameras = fetch_all(con, "SELECT id, camera_code, parking_position_code, zone_type, capacity, status FROM cameras")
    sessions = fetch_all(con, """SELECT id, session_code, camera_id, parking_position_code, vehicle_class,
        vehicle_identity_id, vehicle_instance_id, current_track_id, entered_at, parked_at, left_at,
        parking_duration_seconds, status, recovery_status, first_confirmed_empty_after_reconnect,
        departure_time_uncertain, last_confirmed_seen_at, last_seen_at, created_at, updated_at, event_source
        FROM parking_sessions ORDER BY id""")
    track_links = fetch_all(con, """SELECT id, session_id, tracker_track_id, tracker_generation, started_at, ended_at
        FROM vehicle_track_links ORDER BY id""")
    try:
        vehicle_identities = fetch_all(con, "SELECT * FROM vehicle_identities")
    except sqlite3.OperationalError:
        vehicle_identities = []
    try:
        vehicle_observations = fetch_all(con, """SELECT id, vehicle_identity_id, parking_session_id, camera_id,
            tracker_generation, track_id, observed_at, raw_class, stabilized_class, observation_quality,
            is_ignored, ignore_reason FROM vehicle_observations ORDER BY id DESC LIMIT 500""")
    except sqlite3.OperationalError:
        vehicle_observations = []
    parking_events = fetch_all(con, """SELECT id, session_id, camera_id, event_type, event_time
        FROM parking_events ORDER BY event_time DESC LIMIT 500""")

    sessions_by_id = {s["id"]: s for s in sessions}
    status_counts = defaultdict(int)
    for s in sessions:
        status_counts[s["status"]] += 1
    open_by_camera = defaultdict(int)
    for s in sessions:
        if s["left_at"] is None:
            open_by_camera[s["camera_id"]] += 1

    lifecycle = classify_sessions(sessions, now_iso)
    track_link_report = annotate_track_link_ownership(sessions, track_links)
    ownership_conflicts = track_ownership_conflicts(track_links, sessions_by_id)
    identity_report = vehicle_instance_anomalies(sessions)
    shortest = short_sessions(sessions)[:10]
    oldest = oldest_active(sessions, now_iso)[:10]
    legacy_split = split_legacy_vs_new(sessions, new_since_iso)

    open_links_total = sum(1 for tl in track_links if tl["ended_at"] is None)

    report = {
        "generated_at": now_iso,
        "db_path": str(Path(db_path).resolve()),
        "read_only": True,
        "table_counts": {
            "cameras": len(cameras), "parking_sessions": len(sessions),
            "vehicle_track_links": len(track_links), "vehicle_identities": len(vehicle_identities),
            "vehicle_observations_sampled": len(vehicle_observations), "parking_events_sampled": len(parking_events),
        },
        "cameras": cameras,
        "session_status_counts": dict(status_counts),
        "open_sessions_by_camera": dict(open_by_camera),
        "lifecycle_categories": {k: (v if len(v) <= 50 else v[:50] + [f"... +{len(v)-50} more"]) for k, v in lifecycle.items()},
        "vehicle_track_link_report": track_link_report,
        "track_link_open_count": open_links_total,
        "track_link_open_pct": round(100.0 * open_links_total / len(track_links), 1) if track_links else 0.0,
        "track_ownership_conflicts_open_sessions": ownership_conflicts,
        "vehicle_identity_report": identity_report,
        "shortest_completed_sessions": shortest,
        "oldest_open_sessions": oldest,
        "legacy_vs_new": legacy_split,
    }
    return report


def render_text(report: dict) -> str:
    lines = []
    a = lines.append
    a("=== Phase 4.7C session audit report (READ ONLY) ===")
    a(f"db_path: {report['db_path']}")
    a(f"generated_at: {report['generated_at']}")
    a("READ ONLY: co - ket noi mo qua file:...?mode=ro, da xac nhan tu choi ghi.")
    a("")
    a("-- table_counts --")
    for k, v in report["table_counts"].items():
        a(f"  {k}: {v}")
    a("")
    a("-- session_status_counts --")
    for k, v in report["session_status_counts"].items():
        a(f"  {k}: {v}")
    a("")
    a("-- open_sessions_by_camera (left_at IS NULL) --")
    for k, v in report["open_sessions_by_camera"].items():
        a(f"  camera_id={k}: {v} open")
    a("")
    a("-- lifecycle_categories (muc 7 A..I) --")
    for k, v in report["lifecycle_categories"].items():
        a(f"  {k}: count={len(v) if isinstance(v, list) else v}")
    a("")
    a("-- vehicle_track_link_report (muc 8) --")
    for k, v in report["vehicle_track_link_report"].items():
        a(f"  {k}: count={len(v)}")
    a(f"  track_link_open_count: {report['track_link_open_count']} ({report['track_link_open_pct']}% of all links)")
    a("")
    a("-- track_ownership_conflicts_open_sessions (muc 8) --")
    a(f"  count={len(report['track_ownership_conflicts_open_sessions'])}")
    for row in report["track_ownership_conflicts_open_sessions"][:10]:
        a(f"    {row}")
    a("")
    a("-- vehicle_identity_report (muc 9) --")
    for k, v in report["vehicle_identity_report"].items():
        a(f"  {k}: count={len(v) if isinstance(v, list) else v}")
    a("")
    a("-- 10 shortest completed sessions --")
    for row in report["shortest_completed_sessions"]:
        a(f"  {row}")
    a("")
    a("-- 10 oldest open sessions --")
    for row in report["oldest_open_sessions"]:
        a(f"  {row}")
    a("")
    a("-- legacy_vs_new (muc 12) --")
    a(f"  {report['legacy_vs_new']}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Phase 4.7C read-only session audit (KHONG BAO GIO ghi vao DB).")
    parser.add_argument("--db", required=True, help="Duong dan file SQLite can audit (LUON mo qua mode=ro).")
    parser.add_argument("--json-out", default=None, help="Neu co, ghi JSON report ra file nay (khong phai vao DB).")
    parser.add_argument("--new-since", default=None, help="ISO timestamp (UTC) - session created_at >= gia tri nay duoc coi la MOI (muc 12); mac dinh: khong phan biet (tat ca la LEGACY).")
    parser.add_argument("--quiet", action="store_true", help="Khong in text report ra stdout (chi dung khi ket hop --json-out).")
    args = parser.parse_args()

    print(f"READ ONLY AUDIT - opening {args.db!r} via file:...?mode=ro (write attempts will be rejected by SQLite).", file=sys.stderr)
    con = open_readonly(args.db)
    try:
        report = build_report(con, args.db, args.new_since)
    finally:
        con.close()

    if not args.quiet:
        print(render_text(report))

    if args.json_out:
        out_path = Path(args.json_out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
        print(f"\nJSON report written to: {out_path}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
