"""
Error Handling Utilities and Resilience Patterns

Provides robust error handling for database calls,
network failures, and other edge cases.
"""

import logging
import asyncio
from typing import Callable, Any, Optional
from functools import wraps
from fastapi import HTTPException

logger = logging.getLogger(__name__)


class NetworkTimeoutError(Exception):
    """Custom exception for network timeouts"""
    pass


class ConcurrentModificationError(Exception):
    """Custom exception for concurrent modification conflicts"""
    pass


def retry_on_network_error(max_retries: int = 3, delay: float = 1.0, backoff: float = 2.0):
    """Decorator to retry function on network errors with exponential backoff."""
    def decorator(func: Callable):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            current_delay = delay
            last_exception = None

            for attempt in range(max_retries + 1):
                try:
                    return await func(*args, **kwargs)

                except (ConnectionError, TimeoutError, OSError, NetworkTimeoutError) as e:
                    last_exception = e

                    if attempt < max_retries:
                        logger.warning(
                            f"Network error in {func.__name__} (attempt {attempt + 1}/{max_retries}): {e}. "
                            f"Retrying in {current_delay:.1f}s..."
                        )
                        await asyncio.sleep(current_delay)
                        current_delay *= backoff
                    else:
                        logger.error(
                            f"Network error in {func.__name__} failed after {max_retries} retries: {e}"
                        )

                except HTTPException:
                    raise

                except Exception as e:
                    logger.error(f"Non-retryable error in {func.__name__}: {e}")
                    raise

            raise NetworkTimeoutError(
                f"Operation failed after {max_retries} retries: {str(last_exception)}"
            )

        return wrapper
    return decorator


def handle_db_errors(func: Callable):
    """Decorator to handle database errors and convert them to appropriate HTTP exceptions."""
    @wraps(func)
    async def wrapper(*args, **kwargs):
        try:
            return await func(*args, **kwargs)

        except (ConnectionError, TimeoutError, OSError, NetworkTimeoutError) as e:
            logger.error(f"Network error in {func.__name__}: {e}")
            raise HTTPException(
                status_code=503,
                detail="Unable to connect to database. Please check network connectivity."
            )

        except HTTPException:
            raise

        except Exception as e:
            logger.error(f"Unexpected error in {func.__name__}: {e}", exc_info=True)
            raise HTTPException(
                status_code=500,
                detail=f"Internal server error: {str(e)}"
            )

    return wrapper


# Alias for backward compatibility during migration
handle_netbox_errors = handle_db_errors


def handle_concurrent_modification():
    """Context manager to handle concurrent modification detection."""
    class ConcurrentModificationHandler:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            if exc_type == ConcurrentModificationError:
                logger.warning("Concurrent modification detected")
                raise HTTPException(
                    status_code=409,
                    detail="Resource was modified by another request. Please refresh and try again."
                )
            return False

    return ConcurrentModificationHandler()


def log_slow_operations(threshold_seconds: float = 2.0):
    """Decorator to log operations that take longer than threshold."""
    def decorator(func: Callable):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            import time
            start_time = time.time()
            try:
                result = await func(*args, **kwargs)
                return result
            finally:
                elapsed_time = time.time() - start_time
                if elapsed_time > threshold_seconds:
                    logger.warning(
                        f"Slow operation detected: {func.__name__} took {elapsed_time:.2f}s "
                        f"(threshold: {threshold_seconds}s)"
                    )

        return wrapper
    return decorator


def safe_int_conversion(value: Any, field_name: str = "value", min_val: int = None, max_val: int = None) -> int:
    """Safely convert value to integer with validation."""
    try:
        int_val = int(value)

        if min_val is not None and int_val < min_val:
            raise HTTPException(
                status_code=400,
                detail=f"{field_name} must be at least {min_val}, got {int_val}"
            )

        if max_val is not None and int_val > max_val:
            raise HTTPException(
                status_code=400,
                detail=f"{field_name} must be at most {max_val}, got {int_val}"
            )

        return int_val

    except (ValueError, TypeError):
        raise HTTPException(
            status_code=400,
            detail=f"{field_name} must be a valid integer, got '{value}'"
        )


def safe_list_access(lst: list, index: int, default: Any = None) -> Any:
    """Safely access list element with bounds checking."""
    try:
        return lst[index]
    except (IndexError, TypeError):
        return default


def safe_dict_access(dct: dict, key: str, default: Any = None, required: bool = False) -> Any:
    """Safely access dictionary key with optional requirement."""
    if key not in dct and required:
        raise HTTPException(
            status_code=400,
            detail=f"Required field '{key}' is missing"
        )
    return dct.get(key, default)


def chunk_list(lst: list, chunk_size: int):
    """Split list into chunks for batch processing."""
    for i in range(0, len(lst), chunk_size):
        yield lst[i:i + chunk_size]


async def batch_process_with_retry(
    items: list,
    process_func: Callable,
    batch_size: int = 10,
    max_retries: int = 3
) -> list:
    """Process items in batches with retry logic."""
    results = []

    for batch in chunk_list(items, batch_size):
        batch_results = []

        for item in batch:
            for attempt in range(max_retries + 1):
                try:
                    result = await process_func(item)
                    batch_results.append(result)
                    break

                except Exception as e:
                    if attempt < max_retries:
                        logger.warning(f"Batch processing error (attempt {attempt + 1}): {e}")
                        await asyncio.sleep(0.5 * (attempt + 1))
                    else:
                        logger.error(f"Batch processing failed for item after {max_retries} retries: {e}")
                        batch_results.append({"error": str(e), "item": item})

        results.extend(batch_results)

    return results


def db_operation(operation_name: str, threshold_ms: int = 1000, max_retries: int = 3):
    """Combined decorator for database operations: error handling + retry + timing."""
    from .logging_decorators import log_operation_timing

    def decorator(func: Callable) -> Callable:
        decorated_func = log_operation_timing(operation_name, threshold_ms=threshold_ms)(func)
        decorated_func = retry_on_network_error(max_retries=max_retries)(decorated_func)
        decorated_func = handle_db_errors(decorated_func)
        return decorated_func

    return decorator


# Alias for backward compatibility
netbox_operation = db_operation
