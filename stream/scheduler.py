"""
Determines streaming mode based on time of day.
"""
from datetime import datetime


DAYTIME_START = 6   # 06:00
DAYTIME_END = 23    # 23:00


def get_stream_mode() -> str:
    """Return "live" during the day, "replay" at night."""
    hour = datetime.now().hour
    return "live" if DAYTIME_START <= hour < DAYTIME_END else "replay"


def is_daytime() -> bool:
    return get_stream_mode() == "live"
