"""
Platega payment webhook handler.
POST /platega/webhook — Platega calls this URL when payment is confirmed.
"""
import hashlib
import hmac
import logging
from decimal import Decimal

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from bot.database.main import Database
from bot.database.models.main import User, Operations, Payments
from bot.misc.env import EnvKeys
from sqlalchemy import select, func

logger = logging.getLogger(__name__)


def _verify_platega_signature(data: dict, received_sig: str, secret: str) -> bool:
    """HMAC-SHA256 signature check for Platega."""
    # Sort keys alphabetically, concatenate key=value, hash with secret
    sorted_pairs = "&".join(f"{k}={v}" for k, v in sorted(data.items()) if k != "sign")
    expected = hmac.new(secret.encode(), sorted_pairs.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, received_sig.lower())


async def platega_webhook(request: Request) -> JSONResponse:
    """Handle incoming Platega payment notification."""
    try:
        data = await request.json()
    except Exception:
        return JSONResponse({"error": "bad request"}, status_code=400)

    logger.info(f"Platega webhook received: {data}")

    # Verify headers
    merchant_id = request.headers.get("X-MerchantId")
    secret = request.headers.get("X-Secret")

    expected_merchant_id = EnvKeys.PLATEGA_MERCHANT_ID
    expected_secret = EnvKeys.PLATEGA_SECRET_KEY

    if not expected_merchant_id or not expected_secret:
        logger.error("Platega credentials not configured")
        return JSONResponse({"error": "not_configured"}, status_code=500)

    if merchant_id != expected_merchant_id or secret != expected_secret:
        logger.warning("Platega: invalid credentials")
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    # Extract fields from Platega callback
    transaction_id = data.get("id")  # UUID
    status = data.get("status")  # CONFIRMED | CANCELED | CHARGEBACKED
    amount = data.get("amount")  # Amount in rubles
    currency = data.get("currency", "RUB")
    
    # User ID is stored in payload field when creating payment
    user_id_str = data.get("payload", "")
    
    try:
        user_id = int(user_id_str)
        amount_rub = float(amount)  # Already in rubles
    except (ValueError, TypeError):
        logger.error(f"Invalid payload or amount: {data}")
        return JSONResponse({"error": "invalid fields"}, status_code=400)

    if status != "CONFIRMED":
        logger.info(f"Payment not confirmed: {transaction_id}, status: {status}")
        return JSONResponse({"ok": True, "skipped": True})

    async with Database().session() as session:
        # Idempotency: check if already processed
        existing = (await session.execute(
            select(Payments).where(
                Payments.provider == "platega",
                Payments.external_id == transaction_id,
            )
        )).scalars().first()

        if existing and existing.status == "paid":
            return JSONResponse({"ok": True, "already_processed": True})

        user = (await session.execute(
            select(User).where(User.telegram_id == user_id)
        )).scalars().first()

        if not user:
            logger.error(f"Platega webhook: user {user_id} not found")
            return JSONResponse({"error": "user not found"}, status_code=404)

        # Update payment record
        if existing:
            existing.status = "paid"
            existing.amount = amount_rub
        else:
            payment = Payments(
                provider="platega",
                external_id=transaction_id,
                user_id=user_id,
                amount=amount_rub,
                currency=currency,
                status="paid",
            )
            session.add(payment)

        # Credit balance
        from decimal import Decimal
        user.balance = Decimal(str(user.balance)) + Decimal(str(amount_rub))
        session.add(Operations(
            user_id=user_id,
            operation_value=Decimal(str(amount_rub)),
            operation_time=func.now(),
        ))
        await session.commit()

    logger.info(f"Platega: credited {amount_rub} RUB to user {user_id} (payment {transaction_id})")
    return JSONResponse({"ok": True})


platega_routes = [
    Route("/platega/webhook", platega_webhook, methods=["POST"]),
]
