"""
Database module — MongoDB storage implementation.
"""

from .mongo_storage import init_storage, close_storage
from .mongo_segments import (
    STATUS_AVAILABLE,
    STATUS_ALLOCATED,
    MULTI_CLUSTER_TYPE,
    segment_clusters,
    get_segments,
    get_segment_by_segment,
    create_segment,
    update_segment,
    delete_segment,
    allocate_segment,
    release_cluster,
)

__all__ = [
    "init_storage",
    "close_storage",
    "STATUS_AVAILABLE",
    "STATUS_ALLOCATED",
    "MULTI_CLUSTER_TYPE",
    "segment_clusters",
    "get_segments",
    "get_segment_by_segment",
    "create_segment",
    "update_segment",
    "delete_segment",
    "allocate_segment",
    "release_cluster",
]
