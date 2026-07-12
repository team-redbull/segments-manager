"""Query and search operations for VLAN segments.

Handles filtering, searching, and checking VLAN existence.
"""

import re
import logging
from typing import Optional, List, Dict, Any

from ...database import get_segments

logger = logging.getLogger(__name__)


class SegmentQueries:
    """Query and search operations for segments"""

    @staticmethod
    async def get_segments_with_filters(
        site: Optional[str] = None,
        status: Optional[str] = None,
        type: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Get segments with optional filters"""
        segments = await get_segments(site=site, status=status, type=type)
        segments.sort(key=lambda x: x.get("vlan_id", 0))
        return segments

    @staticmethod
    async def check_vlan_exists(site: str, vlan_id: int) -> bool:
        """Check if VLAN ID already exists for this site."""
        results = await get_segments(site=site, vlan_id=vlan_id)
        return len(results) > 0

    @staticmethod
    async def search_segments(
        search_query: str,
        site: Optional[str] = None,
        status: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Search segments by cluster name, EPG name, or VLAN ID"""
        segments = await get_segments(site=site, status=status)

        try:
            vlan_id_search = int(search_query)
        except ValueError:
            vlan_id_search = None

        pattern = re.compile(re.escape(search_query), re.IGNORECASE)

        def _matches_search(s: dict) -> bool:
            if vlan_id_search is not None and s.get("vlan_id") == vlan_id_search:
                return True
            for field in ("cluster_name", "epg_name", "segment"):
                if pattern.search(str(s.get(field) or "")):
                    return True
            return False

        results = [s for s in segments if _matches_search(s)]
        results.sort(key=lambda x: x.get("vlan_id", 0))
        return results
