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


async def _drop_released_fields(col) -> None:
    """One-time migration: remove the legacy `released` / `released_at` fields.

    Both predate the `status` lifecycle field and are fully derivable from it
    (`released` == "Available and previously allocated"), so nothing reads
    them any more. Must run AFTER _migrate_locked_to_status, which still
    consults `released` to derive a status for pre-`status` documents.
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

    await _migrate_locked_to_status(col)
    await _drop_released_fields(col)
    await _backfill_segment_type(col)

    logger.info(
        "MongoDB storage initialised — indexes ensured on '%s' collection", col.name
    )


async def close_storage() -> None:
    """Shut down the MongoDB client gracefully."""
    await close_mongo_client()
