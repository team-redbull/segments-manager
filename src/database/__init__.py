"""
Database module — MongoDB storage implementation.
"""

from .mongo_storage import init_storage, close_storage
from .mongo_segments import (
    STATUS_LOCKED,
    STATUS_AVAILABLE,
    STATUS_ALLOCATED,
    get_segments,
    get_segment_by_id,
    get_segment_by_segment,
    create_segment,
    update_segment,
    delete_segment,
    allocate_segment,
)

__all__ = [
    "init_storage",
    "close_storage",
    "STATUS_LOCKED",
    "STATUS_AVAILABLE",
    "STATUS_ALLOCATED",
    "get_segments",
    "get_segment_by_id",
    "get_segment_by_segment",
    "create_segment",
    "update_segment",
    "delete_segment",
    "allocate_segment",
]
