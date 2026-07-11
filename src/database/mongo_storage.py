"""
MongoDB Storage Lifecycle

Initialisation, index creation, migration, and shutdown.
"""

import logging
from .mongo_client import init_mongo_client, close_mongo_client, get_segments_collection
from .mongo_segments import STATUS_LOCKED, STATUS_AVAILABLE, STATUS_ALLOCATED

logger = logging.getLogger(__name__)


async def _migrate_locked_to_status(col) -> None:
    """One-time migration: boolean `locked` field -> string `status` lifecycle field.

    Statuses: Locked -> Available -> Allocated -> Available. Documents that
    already carry a `status` are left untouched; the legacy `locked` flag is
    removed. Derivation for legacy documents:
      locked == true                       -> "Locked"
      cluster_name set and not released    -> "Allocated"
      otherwise                            -> "Available"
    """
    no_status = {"status": {"$exists": False}}

    locked = await col.update_many(
        {**no_status, "locked": True},
        {"$set": {"status": STATUS_LOCKED}, "$unset": {"locked": ""}},
    )
    allocated = await col.update_many(
        {**no_status, "cluster_name": {"$nin": [None, ""]}, "released": {"$ne": True}},
        {"$set": {"status": STATUS_ALLOCATED}, "$unset": {"locked": ""}},
    )
    available = await col.update_many(
        no_status,
        {"$set": {"status": STATUS_AVAILABLE}, "$unset": {"locked": ""}},
    )
    # Docs migrated earlier may still carry the legacy flag alongside status.
    leftover = await col.update_many(
        {"locked": {"$exists": True}},
        {"$unset": {"locked": ""}},
    )

    migrated = locked.modified_count + allocated.modified_count + available.modified_count
    if migrated or leftover.modified_count:
        logger.info(
            "Migrated %d segment(s) from `locked` to `status` "
            "(%d Locked, %d Allocated, %d Available); cleaned %d leftover flag(s)",
            migrated,
            locked.modified_count,
            allocated.modified_count,
            available.modified_count,
            leftover.modified_count,
        )


async def init_storage() -> None:
    """Connect to MongoDB, ensure all required indexes exist, run migrations."""
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
    # The atomic allocator selects by (site, status="Available").
    await col.create_index([("site", 1), ("status", 1)], name="site_status_idx")

    await _migrate_locked_to_status(col)

    logger.info("MongoDB storage initialised — indexes ensured on 'segments' collection")


async def close_storage() -> None:
    """Shut down the MongoDB client gracefully."""
    await close_mongo_client()
