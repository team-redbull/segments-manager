"""
MongoDB Storage Lifecycle

Initialisation, index creation, and shutdown.
"""

import logging
from .mongo_client import init_mongo_client, close_mongo_client, get_segments_collection

logger = logging.getLogger(__name__)


async def init_storage() -> None:
    """Connect to MongoDB and ensure all required indexes exist."""
    await init_mongo_client()

    col = get_segments_collection()
    await col.create_index(
        [("site", 1), ("vlan_id", 1)],
        unique=True,
        name="site_vlan_unique",
    )
    await col.create_index("segment", unique=True, name="segment_unique")
    await col.create_index("cluster_name", name="cluster_name_idx")
    await col.create_index("site", name="site_idx")

    logger.info("MongoDB storage initialised — indexes ensured on 'segments' collection")


async def close_storage() -> None:
    """Shut down the MongoDB client gracefully."""
    await close_mongo_client()
