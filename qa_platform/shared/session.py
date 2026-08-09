from __future__ import annotations

from collections.abc import Callable
from datetime import datetime


SESSION_ID_FORMAT = "%y%m%d_%H%M%S"


def build_session_id(clock: Callable[[], datetime] | None = None) -> str:
    now = (clock or (lambda: datetime.now().astimezone()))()
    return now.strftime(SESSION_ID_FORMAT)
