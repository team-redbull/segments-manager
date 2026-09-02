"""
Cache Management

TTL-based in-memory cache with in-flight request deduplication.
Used to reduce MongoDB round-trips for frequently read segment lists.
"""

import logging
import time
from typing import Optional, Any, Dict
import asyncio

logger = logging.getLogger(__name__)

CACHE_KEY_SEGMENTS = "segments"
CACHE_TTL_SHORT = 60       # 1 minute — segments list
CACHE_TTL_LONG = 3600      # 1 hour  — static data

_cache: Dict[str, Dict[str, Any]] = {
    CACHE_KEY_SEGMENTS: {"data": None, "timestamp": 0, "ttl": CACHE_TTL_SHORT},
}

_default_ttl = CACHE_TTL_SHORT

_inflight_requests: Dict[str, asyncio.Task] = {}


def get_cached(key: str) -> Optional[Any]:
    """Return cached data if still valid, else None."""
    entry = _cache.get(key)
    if entry and entry["data"] is not None:
        age = time.time() - entry["timestamp"]
        if age < entry["ttl"]:
            logger.debug(f"Cache HIT for {key} (age: {age:.1f}s)")
            return entry["data"]
        logger.debug(f"Cache EXPIRED for {key} (age: {age:.1f}s, TTL: {entry['ttl']}s)")
    return None


def set_cache(key: str, data: Any, ttl: Optional[int] = None) -> None:
    """Store data in cache."""
    if key not in _cache:
        effective_ttl = ttl if ttl is not None else _default_ttl
        _cache[key] = {"data": None, "timestamp": 0, "ttl": effective_ttl}
    _cache[key]["data"] = data
    _cache[key]["timestamp"] = time.time()
    logger.debug(f"Cache SET for {key} ({len(data) if isinstance(data, list) else 'N/A'} items)")


def invalidate_cache(key: Optional[str] = None) -> None:
    """Invalidate one cache key or all if key is None."""
    if key:
        if key in _cache:
            _cache[key]["data"] = None
            _cache[key]["timestamp"] = 0
            logger.info(f"Cache INVALIDATED for {key}")
    else:
        for k in _cache:
            _cache[k]["data"] = None
            _cache[k]["timestamp"] = 0
        logger.info("Cache INVALIDATED (all)")


def get_inflight_request(key: str) -> Optional[asyncio.Task]:
    return _inflight_requests.get(key)


def set_inflight_request(key: str, task: asyncio.Task) -> None:
    _inflight_requests[key] = task


def remove_inflight_request(key: str) -> None:
    _inflight_requests.pop(key, None)
