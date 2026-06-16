"""TipzySMM API client."""
import httpx
from typing import Any
from config import settings

class TipzyError(Exception):
    pass

class TipzyClient:
    def __init__(self, key: str | None = None, base_url: str | None = None):
        self.key = key or settings.TIPZY_API_KEY
        self.base_url = base_url or settings.TIPZY_BASE_URL

    async def _post(self, **params) -> Any:
        params["key"] = self.key
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post(self.base_url, data=params)
            r.raise_for_status()
            data = r.json()
        if isinstance(data, dict) and data.get("error"):
            raise TipzyError(str(data["error"]))
        return data

    async def balance(self) -> dict:
        return await self._post(action="balance")

    async def services(self) -> list[dict]:
        return await self._post(action="services")

    async def add_order(self, service_id: int, link: str, quantity: int) -> dict:
        return await self._post(action="add", service=service_id, link=link, quantity=quantity)

    async def status(self, order_id: int) -> dict:
        return await self._post(action="status", order=order_id)

    async def multi_status(self, order_ids: list[int]) -> dict:
        return await self._post(action="status", orders=",".join(map(str, order_ids)))

tipzy = TipzyClient()
