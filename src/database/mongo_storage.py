"""
MongoDB Storage Lifecycle

Initialisation, index creation, migration, and shutdown.
"""

import logging
from .mongo_client import init_mongo_client, close_mongo_client, get_segments_collection

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


async def _backfill_segment_type(col) -> None:
    """One-time migration: give documents predating the `type` field the default.

    `create_segment` has always defaulted `type` to "HC", but documents written
    before the field existed have none. The allocator now filters on `type`, so
    a missing field would silently make those segments unallocatable — backfill
    them with the same default the model uses.
    """
    result = await col.update_many(
        {"type": {"$exists": False}},
        {"$set": {"type": "HC"}},
    )
    if result.modified_count:
        logger.info(
            "Backfilled `type`=HC on %d segment(s) that predate the field",
            result.modified_count,
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
    # The atomic allocator selects by (site, type, status="Available").
    await col.create_index(
        [("site", 1), ("type", 1), ("status", 1)], name="site_type_status_idx"
    )

    # Superseded by site_type_status_idx now that the allocator always filters
    # on type; ignore if it was never created (fresh database).
    try:
        await col.drop_index("site_status_idx")
        logger.info("Dropped superseded index site_status_idx")
    except Exception:
        pass

    await _drop_released_fields(col)
    await _backfill_segment_type(col)

    logger.info(
        "MongoDB storage initialised — indexes ensured on '%s' collection", col.name
    )


async def close_storage() -> None:
    """Shut down the MongoDB client gracefully."""
    await close_mongo_client()
