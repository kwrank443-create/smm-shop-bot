"""Auto-answer middleware — ensures every callback query gets answered.

Prevents Telegram from showing 'clock' animation on unhandled callbacks.
Safe to use alongside handlers that already call answer() — duplicate
answers are silently ignored by Telegram API.
"""
import logging
from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery

logger = logging.getLogger(__name__)


class AutoAnswerMiddleware(BaseMiddleware):
    """Automatically calls call.answer() after every callback handler."""

    async def __call__(
        self,
        handler: Callable[[CallbackQuery, Dict[str, Any]], Awaitable[Any]],
        event: CallbackQuery,
        data: Dict[str, Any],
    ) -> Any:
        result = await handler(event, data)
        try:
            await event.answer()
        except Exception:
            # Telegram may raise if callback is too old — ignore
            pass
        return result
