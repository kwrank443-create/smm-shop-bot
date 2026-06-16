"""Retry with exponential backoff — for external API calls (tipzy, platepay, etc.)."""
import asyncio
import logging
from functools import wraps
from typing import Any, Callable, Optional, Tuple, Type

logger = logging.getLogger(__name__)


def retry_async(
    max_attempts: int = 3,
    delay: float = 1.0,
    backoff: float = 2.0,
    exceptions: Optional[Tuple[Type[Exception], ...]] = None,
):
    """Decorator: retry an async function with exponential backoff.
    
    Args:
        max_attempts: Total attempts (1 = no retry, 3 = try + 2 retries)
        delay: Initial delay in seconds
        backoff: Multiplier for delay after each attempt
        exceptions: Tuple of exception types to catch (default: all)
    """
    if exceptions is None:
        exceptions = (Exception,)

    def decorator(fn: Callable) -> Callable:
        @wraps(fn)
        async def wrapper(*args, **kwargs) -> Any:
            last_exc = None
            current_delay = delay
            for attempt in range(1, max_attempts + 1):
                try:
                    return await fn(*args, **kwargs)
                except exceptions as exc:
                    last_exc = exc
                    if attempt >= max_attempts:
                        logger.error(
                            "%s failed after %d attempts: %s",
                            fn.__name__, max_attempts, exc,
                        )
                        raise
                    logger.warning(
                        "%s attempt %d/%d failed (%s), retrying in %.1fs...",
                        fn.__name__, attempt, max_attempts, exc, current_delay,
                    )
                    await asyncio.sleep(current_delay)
                    current_delay *= backoff
            raise last_exc  # unreachable but keeps type checker happy
        return wrapper
    return decorator
