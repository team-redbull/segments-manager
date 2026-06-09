"""Allocation utilities for VLAN segment management.

Handles all allocation-related operations including finding allocations,
atomic allocation, releasing segments, and supporting shared segments.
"""

import re
import logging
import time
from typing import Optional, Dict, Any

from ...database import (
    get_segments,
    update_segment as _update_segment,
    allocate_segment as _allocate_segment,
)
from ..time_utils import get_current_utc

logger = logging.getLogger(__name__)


class AllocationUtils:
    """Utilities for segment allocation operations"""

    @staticmethod
    async def find_existing_allocation(cluster_name: str, site: str) -> Optional[Dict[str, Any]]:
        """Find existing allocation for a cluster at a site.
        Supports both single clusters and shared segments (comma-separated).
        """
        # Exact match first
        candidates = await get_segments(site=site, cluster_name=cluster_name, released=False)
        if candidates:
            return candidates[0]

        # Shared-segment regex search (cluster may be part of "cluster1,cluster2")
        all_site_segs = await get_segments(site=site, released=False)
        pattern = re.compile(rf"(^|,){re.escape(cluster_name)}(,|$)")
        return next(
            (s for s in all_site_segs if s.get("cluster_name") and pattern.search(s["cluster_name"])),
            None
        )

    @staticmethod
    async def find_and_allocate_segment(site: str, cluster_name: str) -> Optional[Dict[str, Any]]:
        """Atomically find and allocate an available segment for a site."""
        logger.info(f"Allocating from site={site}")
        t1 = time.time()
        result = await _allocate_segment(site=site, cluster_name=cluster_name, sort_by_vlan_id=True)
        logger.info(f"allocate_segment took {(time.time() - t1)*1000:.0f}ms")
        return result

    @staticmethod
    async def find_available_segment(site: str) -> Optional[Dict[str, Any]]:
        """Find an available segment for a site (kept for backward compatibility)."""
        segments = await get_segments(site=site, allocated=False)
        return segments[0] if segments else None

    @staticmethod
    async def allocate_segment(segment_id: str, cluster_name: str) -> bool:
        """Allocate a segment to a cluster (kept for backward compatibility)."""
        allocation_time = get_current_utc()
        return await _update_segment(segment_id, {
            "cluster_name": cluster_name,
            "allocated_at": allocation_time,
            "released": False,
            "released_at": None
        })

    @staticmethod
    async def release_segment(cluster_name: str, site: str) -> bool:
        """Release a segment allocation.
        For shared segments, removes only the specified cluster from the list.
        """
        all_segments = await get_segments(site=site, released=False)

        pattern = re.compile(rf"(^|,){re.escape(cluster_name)}(,|$)")
        segment = next(
            (s for s in all_segments if s.get("cluster_name") and pattern.search(s["cluster_name"])),
            None
        )
        if not segment:
            return False

        current_clusters = segment["cluster_name"]

        if current_clusters == cluster_name:
            # Single cluster — release fully
            return await _update_segment(segment["_id"], {
                "cluster_name": None,
                "released": True,
                "released_at": get_current_utc()
            })

        # Shared cluster — remove only this cluster
        cluster_list = [c.strip() for c in current_clusters.split(",")]
        if cluster_name in cluster_list:
            cluster_list.remove(cluster_name)
            if len(cluster_list) == 0:
                return await _update_segment(segment["_id"], {
                    "cluster_name": None,
                    "released": True,
                    "released_at": get_current_utc()
                })
            else:
                return await _update_segment(segment["_id"], {
                    "cluster_name": ",".join(cluster_list)
                })

        return False
