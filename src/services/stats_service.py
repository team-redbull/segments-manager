import logging
from typing import List, Dict, Any
from datetime import datetime
from fastapi import HTTPException

from ..utils.database_utils import DatabaseUtils
from ..utils.database.statistics_utils import StatisticsUtils
from ..config.settings import SITES
from ..utils.error_handlers import handle_db_errors, retry_on_network_error
from ..utils.logging_decorators import log_operation_timing

logger = logging.getLogger(__name__)

class StatsService:
    """Service class for statistics operations"""

    @staticmethod
    async def get_sites() -> Dict[str, List[str]]:
        """Get configured sites"""
        return {"sites": SITES}

    @staticmethod
    @handle_db_errors
    @retry_on_network_error(max_retries=3)
    @log_operation_timing("get_stats", threshold_ms=1000)
    async def get_stats() -> List[Dict[str, Any]]:
        """Get statistics per site — single query for all sites."""
        return await StatisticsUtils.get_all_sites_statistics()

    @staticmethod
    @handle_db_errors
    @log_operation_timing("health_check", threshold_ms=2000)
    async def health_check() -> Dict[str, Any]:
        """Health check endpoint with comprehensive system validation."""
        from ..database.mongo_client import get_db

        health_data = {
            "status": "healthy",
            "timestamp": datetime.now().isoformat(),
            "sites": SITES,
            "storage_type": "mongodb",
        }

        # Check MongoDB connectivity
        db = get_db()
        await db.command("ping")
        health_data["storage"] = "accessible"

        # Get all sites statistics with single query
        try:
            all_stats = await StatisticsUtils.get_all_sites_statistics()

            total_segments = 0
            site_counts = {}

            for site_stats in all_stats:
                site = site_stats["site"]
                site_total = site_stats.get("total_segments", 0)
                total_segments += site_total

                site_counts[site] = {
                    "total": site_total,
                    "allocated": site_stats.get("allocated", 0),
                    "available": site_stats.get("available", 0),
                    "utilization": site_stats.get("utilization", 0)
                }

            health_data["total_segments"] = total_segments
            health_data["sites_summary"] = site_counts
            health_data["storage_operations"] = "working"
            health_data["sample_query_success"] = True

        except Exception as stats_error:
            logger.warning(f"Error getting stats: {stats_error}")
            health_data["storage_operations"] = "limited"
            health_data["sample_query_success"] = False
            health_data["stats_error"] = str(stats_error)
            total_segments = 0

        total_sites = len(SITES)
        health_data["system_summary"] = {
            "configured_sites": total_sites,
            "total_segments": total_segments,
            "average_segments_per_site": round(total_segments / total_sites, 2) if total_sites > 0 else 0
        }

        return health_data
