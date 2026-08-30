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


def format_duration_hhmmss(total_seconds) -> str:
    # Phase 4.3: hien thi thoi luong do xe dang HH:mm:ss thay cho phut thap phan
    # (vd "17386.42 phut" - kho doc va de nham). KHONG dung datetime.strftime("%H:%M:%S")
    # vi ham do WRAP lai ve 0 sau moi 24 gio - phien do xe co the keo dai nhieu ngay
    # (vd phien bi dong sau khi khoi phuc tu DB ma khong co detection song nao xac nhan
    # lai), nen gio phai duoc tinh TUYET DOI (co the vuot qua 23), khong wrap theo dong ho.
    # Chi thay doi CACH HIEN THI - khong dong cham gia tri parking_duration_seconds trong DB.
    try:
        total=int(total_seconds or 0)
    except (TypeError,ValueError):
        total=0
    if total<0: total=0
    hours,remainder=divmod(total,3600); minutes,seconds=divmod(remainder,60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
