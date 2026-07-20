from datetime import datetime, timezone
import os
from zoneinfo import ZoneInfo

APP_TIMEZONE_NAME=os.getenv("PARKING_APP_TIMEZONE","Asia/Ho_Chi_Minh")
APP_TIMEZONE=ZoneInfo(APP_TIMEZONE_NAME)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def ensure_utc(value: datetime | None) -> datetime | None:
    if value is None: return None
    if value.tzinfo is None: return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def to_local_time(value: datetime | None) -> datetime | None:
    normalized=ensure_utc(value)
    return normalized.astimezone(APP_TIMEZONE) if normalized else None


def format_local_datetime(value: datetime | None,fmt="%d/%m/%Y %H:%M:%S") -> str:
    local=to_local_time(value)
    return local.strftime(fmt) if local else "-"


def seconds_between(start: datetime | None, end: datetime | None) -> int | None:
    start_utc=ensure_utc(start); end_utc=ensure_utc(end)
    return None if not start_utc or not end_utc else max(0,int((end_utc-start_utc).total_seconds()))
