"""Platega API client for creating payment links."""
import logging
from typing import Optional, Dict, Any
from bot.misc.env import EnvKeys
import aiohttp

logger = logging.getLogger(__name__)

PLATEGA_API_URL = "https://app.platega.io/v2"


async def create_payment_link(
    amount: float,
    user_id: int,
    description: str,
    return_url: str = "https://t.me/clerkstore_bot",
    failed_url: str = "https://t.me/clerkstore_bot",
) -> Optional[Dict[str, Any]]:
    """
    Create a Platega payment link.
    
    Returns:
        {
            "transactionId": "uuid",
            "status": "PENDING",
            "url": "https://pay.platega.io/...",
            "expiresIn": "00:15:00",
            "rate": 91.2
        }
    """
    merchant_id = EnvKeys.PLATEGA_MERCHANT_ID
    secret = EnvKeys.PLATEGA_SECRET_KEY
    
    if not merchant_id or not secret:
        logger.error("Platega credentials not configured")
        return None
    
    payload = {
        "paymentDetails": {
            "amount": round(amount, 2),  # Amount in rubles
            "currency": "RUB"
        },
        "description": description,
        "return": return_url,
        "failedUrl": failed_url,
        "payload": str(user_id),  # Store user_id in payload for webhook
        "callbackUrl": "https://admin.clerkstore.eu.cc/platega/webhook",
    }
    
    headers = {
        "X-MerchantId": merchant_id,
        "X-Secret": secret,
        "Content-Type": "application/json",
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{PLATEGA_API_URL}/transaction/process",
                json=payload,
                headers=headers,
            ) as resp:
                data = await resp.json()
                logger.info(f"Created Platega payment: {data}")
                return data
    except Exception as e:
        logger.error(f"Failed to create Platega payment: {e}")
        return None


async def check_payment_status(transaction_id: str) -> Optional[str]:
    """
    Check payment status.
    
    Returns:
        "PENDING" | "CONFIRMED" | "CANCELED" | None
    """
    merchant_id = EnvKeys.PLATEGA_MERCHANT_ID
    secret = EnvKeys.PLATEGA_SECRET_KEY
    
    if not merchant_id or not secret:
        return None
    
    headers = {
        "X-MerchantId": merchant_id,
        "X-Secret": secret,
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{PLATEGA_API_URL}/transaction/{transaction_id}/status",
                headers=headers,
            ) as resp:
                data = await resp.text()
                return data
    except Exception as e:
        logger.error(f"Failed to check Platega status: {e}")
        return None
