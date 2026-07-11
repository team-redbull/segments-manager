"""Statistics and aggregation utilities for VLAN segments.

Handles calculation of site statistics and utilization metrics.
"""

import logging
from typing import Dict, Any, List

from ...database import get_segments, STATUS_LOCKED, STATUS_AVAILABLE, STATUS_ALLOCATED
from ...config.settings import SITES

logger = logging.getLogger(__name__)


class StatisticsUtils:
    """Statistics and aggregation for segments"""

    @staticmethod
    async def get_site_statistics(site: str) -> Dict[str, Any]:
        """Get statistics for a specific site

        Optimized to use a single query instead of multiple count calls.
        This is more efficient because:
        1. Fetches data from cache (segments cached briefly)
        2. Calculates counts in Python instead of additional queries
        3. Reduces load on the database
        """
        # Single query instead of two separate count calls
        segments = await get_segments(site=site)

        total_segments = len(segments)
        allocated = sum(1 for s in segments if s.get("status") == STATUS_ALLOCATED)
        available = sum(1 for s in segments if s.get("status") == STATUS_AVAILABLE)
        locked = sum(1 for s in segments if s.get("status") == STATUS_LOCKED)

        return {
            "site": site,
            "total_segments": total_segments,
            "allocated": allocated,
            "available": available,
            "locked": locked,
            "utilization": round((allocated / total_segments * 100) if total_segments > 0 else 0, 1)
        }

    @staticmethod
    async def get_all_sites_statistics() -> List[Dict[str, Any]]:
        """Get statistics for all sites with a single database query

        This is much more efficient than calling get_site_statistics() for each site.
        Instead of N queries (one per site), this makes 1 query and groups in Python.

        Returns:
            List of statistics dictionaries, one per site
        """
        # Single query for ALL segments (uses 10-minute cache)
        all_segments = await get_segments()

        # Group by site and calculate stats in Python
        stats = []
        for site in SITES:
            site_segments = [s for s in all_segments if s.get("site") == site]
            total_segments = len(site_segments)
            allocated = sum(1 for s in site_segments if s.get("status") == STATUS_ALLOCATED)
            available = sum(1 for s in site_segments if s.get("status") == STATUS_AVAILABLE)
            locked = sum(1 for s in site_segments if s.get("status") == STATUS_LOCKED)

            stats.append({
                "site": site,
                "total_segments": total_segments,
                "allocated": allocated,
                "available": available,
                "locked": locked,
                "utilization": round((allocated / total_segments * 100) if total_segments > 0 else 0, 1)
            })

        return stats
