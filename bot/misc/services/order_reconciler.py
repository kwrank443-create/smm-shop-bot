"""
Order reconciler — periodically syncs in-progress Tipzy orders with their
actual status from the Tipzy API.

Why this exists:
The per-order watcher (`_watch_tipzy_status`) is a fire-and-forget asyncio
task created at order time. It only polls for ~5 minutes and dies if the bot
restarts. Orders that take longer, or that were in progress during a restart,
get stuck in "in_progress" forever. This reconciler runs in the background for
the whole bot lifetime and reconciles any stuck order, so status is eventually
always correct and refunds for failed orders are issued exactly once.
"""
import asyncio
import logging
from decimal import Decimal

from sqlalchemy import select

from bot.database.main import Database
from bot.database.models.main import TipzyOrder, User
from bot.misc.tipzy import tipzy_order_status

log = logging.getLogger(__name__)

# Tipzy terminal statuses
DONE_OK = {"completed", "partial"}
DONE_FAIL = {"canceled", "cancelled", "failed"}
ACTIVE_DB_STATUSES = ["in_progress", "processing", "pending"]

# How often to reconcile, and how old an order must be before we touch it
INTERVAL_SECONDS = 120
MIN_AGE_SECONDS = 60


class OrderReconciler:
    """Background task that keeps order statuses in sync with Tipzy."""

    def __init__(self, bot=None, interval: int = INTERVAL_SECONDS):
        self.bot = bot
        self.interval = interval
        self._task: asyncio.Task | None = None
        self._running = False

    async def start(self):
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())
        log.info("OrderReconciler started (interval=%ss)", self.interval)

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        log.info("OrderReconciler stopped")

    async def _loop(self):
        # Initial delay so we don't collide with startup
        await asyncio.sleep(15)
        while self._running:
            try:
                await self.reconcile_once()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.warning("OrderReconciler cycle error: %s", e)
            await asyncio.sleep(self.interval)

    async def reconcile_once(self) -> int:
        """Reconcile all active orders once. Returns number of orders updated."""
        updated = 0
        async with Database().session() as s:
            rows = (await s.execute(
                select(TipzyOrder).where(
                    TipzyOrder.status.in_(ACTIVE_DB_STATUSES),
                    TipzyOrder.refunded == False
                ).with_for_update(skip_locked=True)
            )).scalars().all()

            for o in rows:
                if not o.tipzy_order_id:
                    continue
                try:
                    data = await tipzy_order_status(int(o.tipzy_order_id))
                except Exception as e:
                    log.debug("reconcile #%s: tipzy fetch failed: %s", o.id, e)
                    continue

                tstatus = (data.get("status") or "").strip()
                if not tstatus:
                    continue

                o.tipzy_status = tstatus
                if data.get("start_count") is not None:
                    try:
                        o.tipzy_start_count = int(data["start_count"])
                    except (ValueError, TypeError):
                        pass
                if data.get("remains") is not None:
                    try:
                        o.tipzy_remains = int(data["remains"])
                    except (ValueError, TypeError):
                        pass
                if data.get("charge") is not None:
                    try:
                        o.tipzy_charge = Decimal(str(data["charge"]))
                    except Exception:
                        pass

                low = tstatus.lower()
                old_status = o.status
                if low in DONE_OK:
                    o.status = "completed"
                elif low in DONE_FAIL:
                    o.status = "failed"
                    # Auto-refund on failure (already filtered refunded=False in query)
                    await self._refund(s, o)

                if o.status != old_status:
                    updated += 1
                    log.info("reconcile #%s: %s -> %s (tipzy=%s)",
                             o.id, old_status, o.status, tstatus)
                    await self._notify(o, old_status)

            await s.commit()
        if updated:
            log.info("OrderReconciler updated %s order(s)", updated)
        return updated

    async def _refund(self, session, order):
        """Refund the order amount to the user's balance, marking it refunded."""
        try:
            user = (await session.execute(
                select(User).where(User.telegram_id == order.user_id).with_for_update()
            )).scalars().first()
            if user and order.price_paid:
                user.balance = float(user.balance or 0) + float(order.price_paid)
                order.refunded = True
                log.info("reconcile refund #%s: +%s to user %s",
                         order.id, order.price_paid, order.user_id)
        except Exception as e:
            log.warning("reconcile refund #%s failed: %s", order.id, e)

    async def _notify(self, order, old_status):
        """Notify the user about the resolved order, best-effort."""
        if not self.bot or not order.user_id:
            return
        try:
            if order.status == "completed":
                msg = (
                    f"🎉 <b>Заказ #{order.id} выполнен!</b>\n\n"
                    f"✅ Статус: <b>{order.tipzy_status}</b>"
                )
            elif order.status == "failed":
                refunded = getattr(order, "refunded", False)
                msg = (
                    f"⚠️ <b>Заказ #{order.id} не выполнен</b>\n\n"
                    f"Статус: <b>{order.tipzy_status}</b>\n"
                    + ("💳 Деньги возвращены на баланс." if refunded else "")
                )
            else:
                return
            await self.bot.send_message(order.user_id, msg)
        except Exception:
            pass
