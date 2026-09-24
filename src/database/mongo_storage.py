"""
MongoDB Storage Lifecycle

Initialisation, index creation, migration, and shutdown.
"""

import logging
from .mongo_client import init_mongo_client, close_mongo_client, get_segments_collection
from .mongo_segments import STATUS_ALLOCATED

logger = logging.getLogger(__name__)


async def _drop_released_fields(col) -> None:
    """One-time migration: remove the legacy `released` / `released_at` fields.

    Both predate the `status` lifecycle field and are fully derivable from it
    (`released` == "Available and previously allocated"), so nothing reads
    them any more.
    """
    result = await col.update_many(
        {"$or": [{"released": {"$exists": True}}, {"released_at": {"$exists": True}}]},
        {"$unset": {"released": "", "released_at": ""}},
    )
    if result.modified_count:
        logger.info(
            "Dropped legacy `released`/`released_at` from %d segment(s)",
            result.modified_count,
        )


async def _clear_available_segment_types(col) -> None:
    """One-time migration: an Available segment carries no type.

    Type used to be fixed at creation (defaulting to "HC") and the allocator
    filtered on it. It is now ALLOCATION state, like cluster_name: stamped on
    by allocate, cleared by release. Segments that were Available before that
    change still hold their old creation-time type, which would show in the UI
    and make `?type=` filters count them as something they are not.
    Allocated segments keep theirs — it is the type they were allocated as.
    """
    result = await col.update_many(
        {"status": {"$ne": STATUS_ALLOCATED}, "type": {"$ne": None}},
        {"$set": {"type": None}},
    )
    if result.modified_count:
        logger.info(
            "Cleared `type` from %d unallocated segment(s)", result.modified_count
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
    # The atomic allocator selects by (site, status="Available") — Available
    # segments have no type to filter on.
    await col.create_index([("site", 1), ("status", 1)], name="site_status_idx")

    # Superseded by site_status_idx now that the allocator no longer filters on
    # type; ignore if it was never created (fresh database).
    try:
        await col.drop_index("site_type_status_idx")
        logger.info("Dropped superseded index site_type_status_idx")
    except Exception:
        pass

    await _drop_released_fields(col)
    await _clear_available_segment_types(col)

    logger.info(
        "MongoDB storage initialised — indexes ensured on '%s' collection", col.name
    )


async def close_storage() -> None:
    """Shut down the MongoDB client gracefully."""
    await close_mongo_client()
