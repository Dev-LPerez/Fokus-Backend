from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

try:
    COLOMBIA_TZ = ZoneInfo("America/Bogota")
except Exception:
    COLOMBIA_TZ = timezone(timedelta(hours=-5), name="America/Bogota")


def get_colombia_now() -> datetime:
    """Returns current datetime with Colombia timezone (UTC-5 / America/Bogota)."""
    return datetime.now(COLOMBIA_TZ)
