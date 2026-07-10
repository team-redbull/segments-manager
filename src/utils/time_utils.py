"""Time utility functions for Segments Manager"""

from datetime import datetime, timezone


def get_current_utc() -> datetime:
    """Get current UTC timestamp

    Returns:
        datetime: Current datetime in UTC timezone

    Usage:
        >>> from src.utils.time_utils import get_current_utc
        >>> timestamp = get_current_utc()
    """
    return datetime.now(timezone.utc)
