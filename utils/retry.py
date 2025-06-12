import time
import functools
import requests
import http.client
import urllib3
import asyncio
import logging
from pybit.exceptions import InvalidRequestError

RETRYABLE = (
    requests.ReadTimeout,
    requests.ConnectionError,
    urllib3.exceptions.ProtocolError,
    http.client.RemoteDisconnected,
)

def retry_rest(max_tries: int = 3, backoff: float = 2.0):
    def outer(func):
        @functools.wraps(func)
        def inner(*a, **kw):
            last_exc = None
            for attempt in range(1, max_tries + 1):
                try:
                    return func(*a, **kw)
                except InvalidRequestError:
                    raise
                except RETRYABLE as exc:
                    last_exc = exc
                    wait = backoff * attempt
                    logging.warning("%s: %s → retry in %ss (%s/%s)", func.__name__, exc, wait, attempt, max_tries)
                    time.sleep(wait)
            raise RuntimeError(f"{func.__name__} failed after {max_tries} retries") from last_exc
        return inner
    return outer


def async_retry_rest(max_tries: int = 3, backoff: float = 2.0):
    """Asynchronous variant of :func:`retry_rest` using ``asyncio``."""

    def outer(func):
        @functools.wraps(func)
        async def inner(*a, **kw):
            last_exc = None
            for attempt in range(1, max_tries + 1):
                try:
                    return await func(*a, **kw)
                except InvalidRequestError:
                    raise
                except RETRYABLE as exc:
                    last_exc = exc
                    wait = backoff * attempt
                    logging.warning(
                        "%s: %s → retry in %ss (%s/%s)",
                        func.__name__,
                        exc,
                        wait,
                        attempt,
                        max_tries,
                    )
                    await asyncio.sleep(wait)
            raise RuntimeError(
                f"{func.__name__} failed after {max_tries} retries"
            ) from last_exc

        return inner

    return outer
