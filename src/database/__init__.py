"""
Database module — MongoDB storage implementation.
"""

from .mongo_storage import init_storage, close_storage
from .mongo_segments import (
    get_segments,
    get_segment_by_id,
    create_segment,
    update_segment,
    delete_segment,
    allocate_segment,
)

__all__ = [
    "init_storage",
    "close_storage",
    "get_segments",
    "get_segment_by_id",
    "create_segment",
    "update_segment",
    "delete_segment",
    "allocate_segment",
]
