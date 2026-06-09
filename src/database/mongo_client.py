"""
MongoDB Client

Async Motor client initialisation and collection accessors.
"""

import logging
from typing import Optional
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase, AsyncIOMotorCollection
from fastapi import HTTPException

from ..config.settings import MONGODB_URL, MONGODB_DB_NAME

logger = logging.getLogger(__name__)

_motor_client: Optional[AsyncIOMotorClient] = None
_db: Optional[AsyncIOMotorDatabase] = None


async def init_mongo_client() -> None:
    """Connect to MongoDB and verify the connection with a ping."""
    global _motor_client, _db
    _motor_client = AsyncIOMotorClient(MONGODB_URL)
    # Ping verifies the connection is reachable before we proceed
    await _motor_client.admin.command("ping")
    _db = _motor_client[MONGODB_DB_NAME]
    logger.info(f"MongoDB connected — database: {MONGODB_DB_NAME}")


async def close_mongo_client() -> None:
    """Close the Motor client."""
    global _motor_client, _db
    if _motor_client:
        _motor_client.close()
        _motor_client = None
        _db = None
        logger.info("MongoDB client closed")


def get_db() -> AsyncIOMotorDatabase:
    """Return the active database. Raises RuntimeError if not initialised."""
    if _db is None:
        raise RuntimeError("MongoDB client not initialised — call init_mongo_client() first")
    return _db


def get_segments_collection() -> AsyncIOMotorCollection:
    """Return the segments collection."""
    return get_db()["segments"]
