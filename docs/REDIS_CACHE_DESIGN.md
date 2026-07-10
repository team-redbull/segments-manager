# Redis Cache Implementation Design

**Purpose**: Add Redis support for multi-instance deployments while maintaining backward compatibility with in-memory cache

**Effort Estimate**: 4-6 hours (Small to Medium)
**Complexity**: Low to Medium
**Risk**: Low (backward compatible)

---

## Current State vs. Target State

### Current (In-Memory Cache)

```python
# src/database/netbox_cache.py
_cache: Dict[str, Dict[str, Any]] = {
    "prefixes": {"data": None, "timestamp": 0, "ttl": 600},
    "vlans": {"data": None, "timestamp": 0, "ttl": 600},
    # ... etc
}

def get_cached(key: str) -> Optional[Any]:
    cache_entry = _cache.get(key)
    if cache_entry and cache_entry["data"] is not None:
        age = time.time() - cache_entry["timestamp"]
        if age < cache_entry["ttl"]:
            return cache_entry["data"]
    return None
```

**Limitations**:
- ❌ Cache lost on restart
- ❌ Each instance has separate cache
- ❌ No cache sharing across pods/containers
- ❌ Warm-up required after deployment

### Target (Redis Cache)

```python
# src/database/netbox_cache.py (new implementation)
class CacheBackend:
    """Abstract cache backend"""
    async def get(self, key: str) -> Optional[Any]
    async def set(self, key: str, value: Any, ttl: int) -> None
    async def delete(self, key: str) -> None
    async def clear(self) -> None

class InMemoryCache(CacheBackend):
    """Current in-memory implementation"""
    # Same as current _cache

class RedisCache(CacheBackend):
    """Redis-backed cache"""
    def __init__(self, redis_url: str):
        self.redis = aioredis.from_url(redis_url)

    async def get(self, key: str) -> Optional[Any]:
        data = await self.redis.get(key)
        return pickle.loads(data) if data else None

    async def set(self, key: str, value: Any, ttl: int) -> None:
        await self.redis.setex(key, ttl, pickle.dumps(value))

# Auto-select backend based on env var
_cache_backend = RedisCache(REDIS_URL) if REDIS_URL else InMemoryCache()
```

**Benefits**:
- ✅ Shared cache across all instances
- ✅ Survives restarts
- ✅ No warm-up needed
- ✅ Backward compatible (falls back to in-memory)

---

## Implementation Plan

### Phase 1: Add Dependencies (15 minutes)

**1. Update requirements.txt**
```diff
+ redis[hiredis]==5.0.1  # Async Redis client with hiredis parser
+ pickle-mixin==1.0.2    # Safe pickling for cache serialization
```

**2. Update .env.example**
```diff
+ # Redis Cache (optional - falls back to in-memory if not configured)
+ REDIS_URL=redis://localhost:6379/0
+ # REDIS_URL=redis://:password@redis-host:6379/0  # With password
+ # REDIS_URL=rediss://redis-host:6379/0  # SSL/TLS
```

---

### Phase 2: Create Cache Abstraction (1-2 hours)

**File**: `src/database/cache_backends.py` (NEW - ~200 lines)

```python
"""
Cache Backend Abstraction

Supports multiple cache backends:
- InMemoryCache: Fast, local, lost on restart (default)
- RedisCache: Shared, persistent, multi-instance support
"""

import logging
import pickle
import time
from abc import ABC, abstractmethod
from typing import Optional, Any, Dict
import asyncio

logger = logging.getLogger(__name__)


class CacheBackend(ABC):
    """Abstract base class for cache backends"""

    @abstractmethod
    async def get(self, key: str) -> Optional[Any]:
        """Get value from cache"""
        pass

    @abstractmethod
    async def set(self, key: str, value: Any, ttl: int) -> None:
        """Set value in cache with TTL (seconds)"""
        pass

    @abstractmethod
    async def delete(self, key: str) -> None:
        """Delete key from cache"""
        pass

    @abstractmethod
    async def clear(self) -> None:
        """Clear all cache entries"""
        pass

    @abstractmethod
    async def close(self) -> None:
        """Close connections and cleanup"""
        pass


class InMemoryCache(CacheBackend):
    """In-memory cache backend (current implementation)"""

    def __init__(self):
        self._cache: Dict[str, Dict[str, Any]] = {}
        logger.info("Initialized InMemoryCache backend")

    async def get(self, key: str) -> Optional[Any]:
        entry = self._cache.get(key)
        if not entry:
            return None

        # Check TTL
        age = time.time() - entry["timestamp"]
        if age >= entry["ttl"]:
            logger.debug(f"Cache EXPIRED for {key} (age: {age:.1f}s)")
            del self._cache[key]
            return None

        logger.debug(f"Cache HIT for {key} (age: {age:.1f}s)")
        return entry["data"]

    async def set(self, key: str, value: Any, ttl: int) -> None:
        self._cache[key] = {
            "data": value,
            "timestamp": time.time(),
            "ttl": ttl
        }
        logger.debug(f"Cache SET for {key} (TTL: {ttl}s)")

    async def delete(self, key: str) -> None:
        if key in self._cache:
            del self._cache[key]
            logger.debug(f"Cache DELETE for {key}")

    async def clear(self) -> None:
        self._cache.clear()
        logger.info("Cache CLEARED (all entries)")

    async def close(self) -> None:
        """No cleanup needed for in-memory cache"""
        pass


class RedisCache(CacheBackend):
    """Redis cache backend for multi-instance deployments"""

    def __init__(self, redis_url: str, key_prefix: str = "vlan_mgr:"):
        self.redis_url = redis_url
        self.key_prefix = key_prefix
        self._redis = None
        self._closed = False

    async def _get_redis(self):
        """Lazy connection to Redis"""
        if self._redis is None:
            try:
                import redis.asyncio as aioredis
                self._redis = await aioredis.from_url(
                    self.redis_url,
                    encoding="utf-8",
                    decode_responses=False  # We handle pickling ourselves
                )
                logger.info(f"Connected to Redis: {self.redis_url}")
            except Exception as e:
                logger.error(f"Failed to connect to Redis: {e}")
                raise

        return self._redis

    def _make_key(self, key: str) -> str:
        """Add prefix to avoid key collisions"""
        return f"{self.key_prefix}{key}"

    async def get(self, key: str) -> Optional[Any]:
        try:
            redis = await self._get_redis()
            full_key = self._make_key(key)

            data = await redis.get(full_key)
            if data is None:
                return None

            # Deserialize
            value = pickle.loads(data)
            logger.debug(f"Redis HIT for {key}")
            return value

        except Exception as e:
            logger.error(f"Redis GET failed for {key}: {e}")
            return None

    async def set(self, key: str, value: Any, ttl: int) -> None:
        try:
            redis = await self._get_redis()
            full_key = self._make_key(key)

            # Serialize
            data = pickle.dumps(value)

            # Set with TTL
            await redis.setex(full_key, ttl, data)
            logger.debug(f"Redis SET for {key} (TTL: {ttl}s)")

        except Exception as e:
            logger.error(f"Redis SET failed for {key}: {e}")

    async def delete(self, key: str) -> None:
        try:
            redis = await self._get_redis()
            full_key = self._make_key(key)
            await redis.delete(full_key)
            logger.debug(f"Redis DELETE for {key}")

        except Exception as e:
            logger.error(f"Redis DELETE failed for {key}: {e}")

    async def clear(self) -> None:
        """Clear all keys with our prefix"""
        try:
            redis = await self._get_redis()
            pattern = f"{self.key_prefix}*"

            # Scan and delete in batches (safer than FLUSHDB)
            cursor = 0
            deleted = 0
            while True:
                cursor, keys = await redis.scan(cursor, match=pattern, count=100)
                if keys:
                    await redis.delete(*keys)
                    deleted += len(keys)
                if cursor == 0:
                    break

            logger.info(f"Redis CLEARED {deleted} keys with prefix {self.key_prefix}")

        except Exception as e:
            logger.error(f"Redis CLEAR failed: {e}")

    async def close(self) -> None:
        """Close Redis connection"""
        if self._redis and not self._closed:
            await self._redis.close()
            self._closed = True
            logger.info("Redis connection closed")


def create_cache_backend(redis_url: Optional[str] = None) -> CacheBackend:
    """
    Factory function to create cache backend

    Args:
        redis_url: Redis connection URL (e.g., redis://localhost:6379/0)
                   If None, uses in-memory cache

    Returns:
        CacheBackend instance
    """
    if redis_url:
        logger.info("Using Redis cache backend")
        return RedisCache(redis_url)
    else:
        logger.info("Using in-memory cache backend")
        return InMemoryCache()
```

---

### Phase 3: Update netbox_cache.py (30 minutes)

**File**: `src/database/netbox_cache.py` (MODIFY - ~120 lines, was 101)

```python
"""
NetBox Cache Management

Supports multiple cache backends (in-memory or Redis).
Backend is selected via REDIS_URL environment variable.
"""

import logging
from typing import Optional, Any, Dict
import asyncio
from .cache_backends import CacheBackend, create_cache_backend
from .netbox_constants import (
    CACHE_KEY_REDBULL_TENANT_ID, CACHE_KEY_PREFIXES,
    CACHE_KEY_VLANS, CACHE_KEY_VRFS
)

logger = logging.getLogger(__name__)

# Cache TTL configuration
_cache_ttls = {
    CACHE_KEY_PREFIXES: 600,           # 10 minutes
    CACHE_KEY_VLANS: 600,              # 10 minutes
    CACHE_KEY_REDBULL_TENANT_ID: 3600, # 1 hour
    CACHE_KEY_VRFS: 3600,              # 1 hour
    "site_groups": 3600,               # 1 hour
    "roles": 3600,                     # 1 hour
}
_default_ttl = 600  # 10 minutes

# Cache backend (initialized in init_cache())
_cache_backend: Optional[CacheBackend] = None

# In-flight request tracking (still needed to prevent duplicate fetches)
_inflight_requests: Dict[str, asyncio.Task] = {}


async def init_cache(redis_url: Optional[str] = None):
    """Initialize cache backend"""
    global _cache_backend
    _cache_backend = create_cache_backend(redis_url)


async def close_cache():
    """Close cache backend"""
    if _cache_backend:
        await _cache_backend.close()


async def get_cached(key: str) -> Optional[Any]:
    """Get cached data if still valid"""
    if not _cache_backend:
        return None

    return await _cache_backend.get(key)


async def set_cache(key: str, data: Any, ttl: Optional[int] = None) -> None:
    """Store data in cache with TTL

    Args:
        key: Cache key
        data: Data to cache
        ttl: Optional TTL in seconds (uses default if not specified)
    """
    if not _cache_backend:
        return

    effective_ttl = ttl if ttl is not None else _cache_ttls.get(key, _default_ttl)
    await _cache_backend.set(key, data, effective_ttl)


async def invalidate_cache(key: Optional[str] = None) -> None:
    """
    Invalidate cache entries

    Args:
        key: Specific cache key to invalidate, or None to clear all
    """
    if not _cache_backend:
        return

    if key:
        await _cache_backend.delete(key)
        logger.info(f"Cache INVALIDATED for {key}")
    else:
        await _cache_backend.clear()
        logger.info("Cache INVALIDATED (all)")


def get_inflight_request(key: str) -> Optional[asyncio.Task]:
    """Get an in-flight request task if it exists"""
    return _inflight_requests.get(key)


def set_inflight_request(key: str, task: asyncio.Task) -> None:
    """Set an in-flight request task"""
    _inflight_requests[key] = task


def remove_inflight_request(key: str) -> None:
    """Remove an in-flight request task"""
    _inflight_requests.pop(key, None)
```

**Key Changes**:
1. Replace `_cache` dict with `_cache_backend` abstraction
2. Add `init_cache()` and `close_cache()` functions
3. Make all cache functions async (await backend calls)
4. Keep in-flight request tracking (still useful to prevent duplicate fetches)

---

### Phase 4: Update Settings (10 minutes)

**File**: `src/config/settings.py` (ADD)

```python
# Redis Configuration (optional)
REDIS_URL = os.getenv("REDIS_URL", None)  # e.g., redis://localhost:6379/0

# Log cache backend
if REDIS_URL:
    logger.info(f"Redis cache enabled: {REDIS_URL}")
else:
    logger.info("Using in-memory cache (no REDIS_URL configured)")
```

---

### Phase 5: Update Initialization (15 minutes)

**File**: `src/database/netbox_storage.py` (MODIFY)

```python
async def init_storage():
    """Initialize NetBox storage - verify connection and sync existing data"""
    try:
        # Initialize cache backend FIRST
        from ..config.settings import REDIS_URL
        await init_cache(redis_url=REDIS_URL)

        nb = get_netbox_client()
        status = await run_netbox_get(lambda: nb.status(), "get NetBox status")
        logger.info(f"NetBox connection successful - Version: {status.get('netbox-version')}")

        await prefetch_reference_data()
        await sync_netbox_vlans()

    except Exception as e:
        logger.error(f"Failed to connect to NetBox: {e}", exc_info=True)
        raise


async def close_storage():
    """Close NetBox storage - cleanup if needed"""
    from .netbox_cache import close_cache
    await close_cache()
    close_netbox_client()
```

---

### Phase 6: Fix Async Cache Calls (1-2 hours)

**Problem**: Current code uses synchronous `get_cached()` - need to convert to async

**Files to Update**:

#### 1. `netbox_helpers.py` (~10 locations)

**Before**:
```python
def get_vrf(self, vrf_name: str):
    cached = get_cached(cache_key)  # Sync call
    if cached:
        return cached
```

**After**:
```python
async def get_vrf(self, vrf_name: str):
    cached = await get_cached(cache_key)  # Async call
    if cached:
        return cached
```

#### 2. `netbox_storage.py` (~3 locations)

Similar changes for `prefetch_reference_data()` and `sync_netbox_vlans()`

#### 3. Update all callers

Ensure all calls to cache functions use `await`

---

### Phase 7: Docker Compose (30 minutes)

**File**: `docker-compose.yml` (NEW - optional for local testing)

```yaml
version: '3.8'

services:
  segments-manager:
    build: .
    ports:
      - "9000:9000"
    environment:
      - REDIS_URL=redis://redis:6379/0
      - NETBOX_URL=${NETBOX_URL}
      - NETBOX_TOKEN=${NETBOX_TOKEN}
    depends_on:
      - redis
    env_file:
      - .env

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    volumes:
      - redis-data:/data
    command: redis-server --appendonly yes

volumes:
  redis-data:
```

**Usage**:
```bash
# Start with Redis
docker-compose up

# Scale to multiple instances (shares cache!)
docker-compose up --scale segments-manager=3
```

---

### Phase 8: Update CLAUDE.md (15 minutes)

**File**: `CLAUDE.md` (ADD section)

```markdown
## Redis Cache (Multi-Instance Support)

### Configuration

**Optional**: Enable Redis for multi-instance deployments

**Environment Variable**:
```bash
REDIS_URL=redis://localhost:6379/0
# Or with password: redis://:password@host:6379/0
# Or with SSL: rediss://host:6379/0
```

**Benefits**:
- ✅ Shared cache across all instances
- ✅ Survives restarts (persistent cache)
- ✅ No warm-up needed after deployment
- ✅ Better performance in Kubernetes/OpenShift

**Fallback**: If `REDIS_URL` not set, uses in-memory cache (single-instance mode)

### Cache Backends

| Backend | Use Case | TTL Persistence | Shared |
|---------|----------|-----------------|--------|
| In-Memory | Single instance, dev, testing | No (lost on restart) | No |
| Redis | Production, multi-instance, K8s | Yes (survives restart) | Yes |

### Redis Deployment

**Docker Compose**:
```bash
docker-compose up  # Includes Redis
```

**Kubernetes**:
```yaml
# Use external Redis service
env:
  - name: REDIS_URL
    value: "redis://redis-service:6379/0"
```
```

---

## Effort Breakdown

### Time Estimate (Total: 4-6 hours)

| Phase | Task | Time | Complexity |
|-------|------|------|------------|
| 1 | Add dependencies | 15 min | Low |
| 2 | Create cache abstraction | 1-2 hours | Medium |
| 3 | Update netbox_cache.py | 30 min | Low |
| 4 | Update settings | 10 min | Low |
| 5 | Update initialization | 15 min | Low |
| 6 | Fix async cache calls | 1-2 hours | Medium |
| 7 | Docker Compose | 30 min | Low |
| 8 | Update docs | 15 min | Low |
| **Total** | | **4-6 hours** | **Low-Medium** |

### Testing Time (Additional 1-2 hours)

- Test in-memory fallback (no Redis)
- Test Redis connection
- Test cache sharing across instances
- Test Redis failover
- Load testing with multiple instances

**Total Effort: 5-8 hours including testing**

---

## Implementation Strategy

### Option 1: All at Once (Recommended)
- Implement all phases in one PR
- Test thoroughly before merge
- **Pros**: Clean, complete feature
- **Cons**: Larger PR to review

### Option 2: Incremental
1. **PR #1**: Add abstraction (in-memory only)
2. **PR #2**: Add Redis backend
3. **PR #3**: Documentation and Docker Compose
- **Pros**: Easier to review
- **Cons**: More overhead, longer timeline

---

## Risks & Mitigation

### Risk 1: Breaking Changes
**Mitigation**: Backward compatible - falls back to in-memory if no Redis

### Risk 2: Redis Connection Failures
**Mitigation**: Graceful degradation - log errors, continue with stale cache

### Risk 3: Pickle Security
**Mitigation**: Redis is internal only (not exposed to users), pickle only our own data

### Risk 4: Performance Regression
**Mitigation**: Redis is typically <5ms for get/set (vs <1ms in-memory)
- Network call adds ~1-4ms latency
- Still faster than NetBox API (~50-200ms)
- Worth the tradeoff for multi-instance support

---

## Alternative Approaches

### Alternative 1: Message Queue (PubSub)
Keep in-memory cache, use Redis PubSub to invalidate across instances

**Pros**:
- Faster reads (in-memory)
- No serialization overhead

**Cons**:
- More complex
- Still need warm-up after restart
- Cache inconsistency during network partitions

### Alternative 2: Distributed Cache (Memcached)
Use Memcached instead of Redis

**Pros**:
- Simpler (only caching, no persistence features)
- Slightly faster

**Cons**:
- No persistence (lost on restart)
- Less common in modern deployments
- Redis is more versatile

**Recommendation**: Stick with Redis (industry standard, widely deployed)

---

## Performance Comparison

### Latency

| Operation | In-Memory | Redis (Local) | Redis (Network) |
|-----------|-----------|---------------|-----------------|
| Cache GET | <1ms | ~2ms | ~5ms |
| Cache SET | <1ms | ~2ms | ~5ms |
| NetBox API | ~50-200ms | ~50-200ms | ~50-200ms |

**Conclusion**: Redis adds 1-4ms overhead, negligible compared to NetBox API (50-200ms)

### Throughput

| Metric | In-Memory | Redis |
|--------|-----------|-------|
| Reads/sec | ~100,000+ | ~10,000-50,000 |
| Writes/sec | ~100,000+ | ~10,000-50,000 |

**Conclusion**: Redis is fast enough for our use case (low volume compared to limits)

---

## Deployment Scenarios

### Scenario 1: Single Instance (Current)
**Config**: No REDIS_URL
**Cache**: In-memory (fast, simple)
**Use Case**: Dev, testing, small deployments

### Scenario 2: Kubernetes (3 replicas)
**Config**: REDIS_URL=redis://redis-service:6379/0
**Cache**: Shared Redis (all pods share cache)
**Use Case**: Production, HA deployments

### Scenario 3: Docker Compose (Local Multi-Instance)
**Config**: REDIS_URL=redis://redis:6379/0
**Cache**: Shared Redis (all containers share cache)
**Use Case**: Local testing, development

---

## Recommendation

**Yes, implement Redis cache support**

### Why?
1. **Small effort** (4-6 hours total)
2. **Low risk** (backward compatible, fallback to in-memory)
3. **High value** for production deployments:
   - Shared cache across instances
   - Survives restarts
   - No warm-up needed
4. **Industry standard** (Redis is everywhere)
5. **Future-proof** (enables other features like rate limiting, sessions)

### When?
- **Now**: If planning multi-instance deployments soon
- **Later**: If single-instance is sufficient for 6+ months

### Quick Win
Start with **Phase 1-3** (abstraction + Redis backend) first (2-3 hours).
This gives you 80% of the value with minimal effort. Add Docker Compose later.

---

## Conclusion

Redis cache support is a **low-effort, high-value** enhancement that makes the application production-ready for multi-instance deployments.

**Effort**: 4-6 hours
**Risk**: Low
**Value**: High (for production)
**Recommendation**: Implement when planning to scale beyond single instance
