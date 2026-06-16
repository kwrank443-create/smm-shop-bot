"""TipzySMM API client — reuses a single httpx.AsyncClient with connection pooling."""
import logging
import httpx
from typing import Any

from bot.misc.env import EnvKeys
from bot.utils.retry import retry_async

logger = logging.getLogger(__name__)

TIPZY_BASE = "https://tipzysmm.ru/api/v2"

# Shared client with connection pooling (max 20 concurrent connections)
_client: httpx.AsyncClient | None = None


async def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(
            timeout=30,
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=5),
        )
    return _client


class TipzyError(Exception):
    pass


@retry_async(max_attempts=3, delay=1.0, backoff=2.0, exceptions=(httpx.HTTPError, TipzyError))
async def _tipzy_post(**params) -> Any:
    params["key"] = EnvKeys.TIPZY_API_KEY
    c = await _get_client()
    r = await c.post(TIPZY_BASE, data=params)
    r.raise_for_status()
    data = r.json()
    if isinstance(data, dict) and "error" in data:
        raise TipzyError(data["error"])
    return data


async def tipzy_balance() -> dict:
    return await _tipzy_post(action="balance")


async def tipzy_services() -> list:
    result = await _tipzy_post(action="services")
    return result if isinstance(result, list) else []


async def tipzy_create_order(link: str, quantity: int, service_id: int | None = None) -> dict:
    sid = service_id or EnvKeys.TIPZY_SERVICE_ID
    return await _tipzy_post(
        action="add",
        service=sid,
        link=link,
        quantity=quantity,
    )


async def tipzy_order_status(order_id: str | int) -> dict:
    return await _tipzy_post(action="status", order=order_id)


async def tipzy_orders_status(order_ids: list[str | int]) -> list[dict]:
    """Batch status check (up to 100 orders)."""
    ids_str = ",".join(str(i) for i in order_ids[:100])
    result = await _tipzy_post(action="status", orders=ids_str)
    if isinstance(result, dict):
        return [result]
    return result


async def tipzy_close():
    """Close the shared HTTP client (call on shutdown)."""
    global _client
    if _client and not _client.is_closed:
        await _client.aclose()
        _client = None


def calc_sell_price(quantity: int) -> float:
    """Price user pays (RUB) for given quantity, with volume tiers."""
    rate = EnvKeys.TIPZY_SELL_PER_UNIT_RUB
    # Volume discounts: 500+ → -10%, 1000+ → -20%, 5000+ → -30%
    if quantity >= 5000:
        rate *= 0.70
    elif quantity >= 1000:
        rate *= 0.80
    elif quantity >= 500:
        rate *= 0.90
    return round(rate * quantity, 2)
