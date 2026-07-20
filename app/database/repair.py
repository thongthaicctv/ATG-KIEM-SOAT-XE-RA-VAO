from datetime import datetime
from sqlalchemy import text

from app.utils.time_utils import seconds_between


def repair_session_durations(engine) -> int:
    """Backfill session cũ COMPLETED có duration thiếu/sai bằng parked_at -> left_at."""
    repaired=0
    with engine.begin() as connection:
        rows=connection.execute(text("SELECT id, parked_at, left_at, parking_duration_seconds FROM parking_sessions WHERE status='COMPLETED' AND parked_at IS NOT NULL AND left_at IS NOT NULL AND (parking_duration_seconds IS NULL OR parking_duration_seconds=0)")).mappings().all()
        for row in rows:
            parked=row["parked_at"]; left=row["left_at"]
            if isinstance(parked,str): parked=datetime.fromisoformat(parked)
            if isinstance(left,str): left=datetime.fromisoformat(left)
            duration=seconds_between(parked,left)
            if duration is not None and duration>0:
                connection.execute(text("UPDATE parking_sessions SET parking_duration_seconds=:duration WHERE id=:id"),{"duration":duration,"id":row["id"]}); repaired+=1
    return repaired

