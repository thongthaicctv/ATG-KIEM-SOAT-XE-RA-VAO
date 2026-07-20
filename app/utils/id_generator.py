from datetime import datetime
from .time_utils import to_local_time


def make_session_code(position: str, sequence: int, when: datetime) -> str:
    local=to_local_time(when)
    return f"{position}-{local:%Y%m%d}-{sequence:06d}"
