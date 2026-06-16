"""Catalog → product → tipzy order flow."""
import logging
import re
import asyncio
from html import escape as html_escape
from aiogram import Router, F
from aiogram.filters import StateFilter
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy import select

from bot.database.main import Database
from bot.database.models.main import User, Categories, Goods, ItemValues, TipzyOrder
from bot.keyboards.inline import (
    categories_kb, products_kb, product_detail_kb,
    confirm_order_kb, mass_confirm_kb, cancel_kb,
)
from bot.misc.tipzy import tipzy_create_order, tipzy_order_status
from bot.misc.env import EnvKeys
from bot.database.methods.audit import log_audit

# ─── Tracked background tasks ────────────────────────────────────────────────
_active_tasks: set[asyncio.Task] = set()

def create_tracked_task(coro):
    """Create an asyncio.Task and track it for graceful shutdown."""
    task = asyncio.create_task(coro)
    _active_tasks.add(task)
    task.add_done_callback(_active_tasks.discard)
    return task

router = Router()
log = logging.getLogger(__name__)

LINK_RE = re.compile(r"https://t\.me/FreeModelDevBot\?start=\S+")
MAX_MASS_LINKS = 150

TIPZY_SERVICE_ID = int(getattr(EnvKeys, "TIPZY_SERVICE_ID", 513))
SELL_PRICE_PER_UNIT = float(getattr(EnvKeys, "TIPZY_SELL_PER_UNIT_RUB", 0.05))


class BuyState(StatesGroup):
    waiting_link     = State()
    waiting_quantity = State()
    confirm          = State()


class MassBuyState(StatesGroup):
    waiting_good     = State()  # новый: выбор товара
    waiting_links    = State()
    waiting_quantity = State()
    confirm          = State()


# ─── helpers ───────────────────────────────────────────────────────────────

async def _get_user(tg_id: int) -> User | None:
    async with Database().session() as s:
        return (await s.execute(
            select(User).where(User.telegram_id == tg_id)
        )).scalars().first()


def _price_text(qty: int, price_per_unit: float | None = None) -> str:
    price = price_per_unit if price_per_unit is not None else SELL_PRICE_PER_UNIT
    total = qty * price
    return f"{total:.2f} ₽"


# ─── Каталог ───────────────────────────────────────────────────────────────

@router.message(F.text == "🛒 Купить", StateFilter(None))
async def menu_shop(message: Message, state: FSMContext):
    await state.clear()
    async with Database().session() as s:
        cats = (await s.execute(select(Categories))).scalars().all()
    if not cats:
        await message.answer("📦 Каталог пока пуст.")
        return
    await message.answer("📦 <b>Каталог</b>\n\nВыберите раздел:", reply_markup=categories_kb(cats))


@router.callback_query(F.data.startswith("cat_"))
async def cb_category(call: CallbackQuery, state: FSMContext):
    cat_id = int(call.data.split("_", 1)[1])
    async with Database().session() as s:
        cat   = (await s.execute(select(Categories).where(Categories.id == cat_id))).scalars().first()
        goods = (await s.execute(select(Goods).where(Goods.category_id == cat_id))).scalars().all()
    if not goods:
        await call.answer("❌ В этом разделе нет товаров.", show_alert=True); return
    await state.update_data(cat_id=cat_id)
    cat_name = cat.name if cat else "Раздел"
    await call.message.edit_text(f"📦 <b>{cat_name}</b>\n\nВыберите товар:", reply_markup=products_kb(goods, cat_id))
    await call.answer()


@router.callback_query(F.data.startswith("back_cat_"))
async def cb_back_cat(call: CallbackQuery, state: FSMContext):
    await state.clear()
    async with Database().session() as s:
        cats = (await s.execute(select(Categories))).scalars().all()
    await call.message.edit_text("📦 <b>Каталог</b>\n\nВыберите раздел:", reply_markup=categories_kb(cats))
    await call.answer()


@router.callback_query(F.data.startswith("back_goods_"))
async def cb_back_goods(call: CallbackQuery, state: FSMContext):
    cat_id = int(call.data.split("_")[-1])
    async with Database().session() as s:
        cat   = (await s.execute(select(Categories).where(Categories.id == cat_id))).scalars().first()
        goods = (await s.execute(select(Goods).where(Goods.category_id == cat_id))).scalars().all()
    cat_name = cat.name if cat else "Раздел"
    await call.message.edit_text(f"📦 <b>{cat_name}</b>\n\nВыберите товар:", reply_markup=products_kb(goods, cat_id))
    await call.answer()


@router.callback_query(F.data.startswith("good_"))
async def cb_product(call: CallbackQuery, state: FSMContext):
    good_id = int(call.data.split("_", 1)[1])
    async with Database().session() as s:
        good = (await s.execute(select(Goods).where(Goods.id == good_id))).scalars().first()
    if not good:
        await call.answer("❌ Товар не найден.", show_alert=True); return
    await state.update_data(good_id=good_id)
    min_qty, max_qty = 1, 56000
    price_str = f"{float(good.price):.2f} ₽/шт"
    desc = good.description or "Реальные запуски вашего Telegram-бота."
    text = (
        f"🤖 <b>{good.name}</b>\n\n{desc}\n\n"
        f"💰 Цена: <b>{price_str}</b>\n"
        f"📊 Мин: <b>{min_qty}</b> / Макс: <b>{max_qty}</b>\n\n"
        f"Нажмите кнопку покупки ниже:"
    )
    await call.message.edit_text(text, reply_markup=product_detail_kb(good_id, good.category_id))
    await call.answer()


# ─── Покупка (одиночная) ───────────────────────────────────────────────────

@router.callback_query(F.data.startswith("buy_"))
async def cb_buy(call: CallbackQuery, state: FSMContext):
    good_id = int(call.data.split("_", 1)[1])
    await state.update_data(good_id=good_id, mass=False)
    await state.set_state(BuyState.waiting_link)
    await call.message.edit_text(
        "🔗 Отправьте ссылку на бота в формате:\n"
        "<code>https://t.me/FreeModelDevBot?start=XXXXX</code>",
        reply_markup=cancel_kb(),
    )
    await call.answer()


@router.message(BuyState.waiting_link)
async def buy_link_input(message: Message, state: FSMContext):
    link = message.text.strip()
    if not LINK_RE.match(link):
        await message.answer(
            "❌ Неверный формат ссылки.\n"
            "Ссылка должна начинаться с: <code>https://t.me/FreeModelDevBot?start=</code>\n"
            "Пример: <code>https://t.me/FreeModelDevBot?start=abc123</code>",
            reply_markup=cancel_kb(),
        )
        return

    data = await state.get_data()
    good_id = data.get("good_id")

    async with Database().session() as s:
        good = (await s.execute(select(Goods).where(Goods.id == good_id))).scalars().first()

    if not good:
        await message.answer("❌ Товар не найден.", reply_markup=cancel_kb())
        await state.clear()
        return

    qty = 1
    total = qty * float(good.price)

    await state.update_data(link=link, quantity=qty, price=float(good.price))
    await state.set_state(BuyState.confirm)

    await message.answer(
        f"📋 <b>Подтверждение заказа</b>\n\n"
        f"🔗 Ссылка: <code>{html_escape(link)}</code>\n"
        f"🔢 Количество: <b>{qty} шт</b>\n"
        f"💰 Стоимость: <b>{total:.2f} ₽</b>",
        reply_markup=confirm_order_kb(good_id),
    )


@router.callback_query(F.data.startswith("confirm_order_"), BuyState.confirm)
async def cb_confirm_order(call: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    link = data.get("link")
    qty = int(data.get("quantity", 1))
    good_id = data.get("good_id")
    price = float(data.get("price", SELL_PRICE_PER_UNIT))
    total = qty * price

    await state.clear()

    async with Database().session() as s:
        user = (await s.execute(
            select(User).where(User.telegram_id == call.from_user.id).with_for_update()
        )).scalars().first()

        if not user:
            await call.answer("❌ Профиль не найден.", show_alert=True)
            return

        if float(user.balance or 0) < total:
            await call.answer(
                f"❌ Недостаточно средств. Баланс: {float(user.balance):.2f} ₽, нужно: {total:.2f} ₽",
                show_alert=True,
            )
            return

        user.balance = float(user.balance) - total

        order = TipzyOrder(
            user_id=call.from_user.id,
            link=link,
            quantity=qty,
            price_paid=total,
            status="pending",
        )
        s.add(order)
        await s.commit()
        await s.refresh(order)
        order_id = order.id

    await call.message.edit_text(
        f"⏳ <b>Заказ #{order_id} создан!</b>\n\n"
        f"Отправляем запрос к сервису. Это займёт до 1 минуты.\n"
        f"Статус придёт сюда автоматически."
    )
    await call.answer()

    await _process_tipzy(call, order_id, link, qty, total)


async def _watch_tipzy_status(bot, user_id: int, order_id: int, tipzy_id: int):
    """Poll tipzy every 15s for up to 5 min and notify user when done."""
    if not tipzy_id:
        return
    DONE_S = {"Completed", "Partial", "Canceled", "Cancelled", "Failed"}
    for _ in range(20):
        await asyncio.sleep(15)
        try:
            from bot.misc.tipzy import tipzy_order_status
            st = await tipzy_order_status(tipzy_id)
            tipzy_status = (st.get("status") if isinstance(st, dict) else "").strip()
            charge       = (st.get("charge") if isinstance(st, dict) else None)
            remains      = (st.get("remains") if isinstance(st, dict) else None)
            start_count  = (st.get("start_count") if isinstance(st, dict) else None)

            async with Database().session() as s:
                order = (await s.execute(select(TipzyOrder).where(TipzyOrder.id == order_id))).scalars().first()
                if order:
                    order.tipzy_status = tipzy_status or None
                    if charge        is not None: order.tipzy_charge      = str(charge)
                    if remains       is not None: order.tipzy_remains     = int(remains)
                    if start_count   is not None: order.tipzy_start_count = int(start_count)
                    if tipzy_status in DONE_S:
                        order.status = "completed" if tipzy_status in ("Completed", "Partial") else "failed"
                        # Refund on failure, exactly once
                        if order.status == "failed" and not getattr(order, "refunded", False):
                            u = (await s.execute(select(User).where(User.telegram_id == order.user_id))).scalars().first()
                            if u and order.price_paid:
                                u.balance = float(u.balance or 0) + float(order.price_paid)
                                if hasattr(order, "refunded"):
                                    order.refunded = True
                    await s.commit()

            if tipzy_status in DONE_S:
                if tipzy_status in ("Completed", "Partial"):
                    msg = (
                        f"🎉 <b>Заказ #{order_id} выполнен!</b>\n\n"
                        f"✅ Статус: <b>{tipzy_status}</b>\n"
                        + (f"📊 Засчитано: <b>{start_count}</b>\n" if start_count else "")
                    )
                    # Invite reminder (every 3rd completed order)
                    try:
                        from bot.misc.invite_rewards import get_referrer_stats
                        stats = await get_referrer_stats(user_id)
                        completed_count = stats.get("verified", 0)
                        if completed_count % 3 == 0 and completed_count > 0:
                            pass  # already has invites, skip nag
                        msg += (
                            "\n💡 <b>Совет:</b> Пригласите друзей по реферальной ссылке "
                            "и получите FreeModel бесплатно! Раздел «🎁 Пригласить друга»"
                        )
                    except Exception:
                        pass
                else:
                    msg = (
                        f"⚠️ <b>Заказ #{order_id} не выполнен</b>\n\n"
                        f"Статус: <b>{tipzy_status}</b>\n"
                        f"💳 Деньги вернутся на баланс автоматически."
                    )
                try:
                    await bot.send_message(user_id, msg)
                except Exception:
                    pass
                return
        except Exception as e:
            log.warning(f"watch tipzy #{order_id}: {e}")
    # таймаут — не дождались
    try:
        await bot.send_message(user_id,
            f"⏳ Заказ #{order_id} ещё выполняется. Проверь статус в «📋 Мои заказы».")
    except Exception:
        pass


async def _process_tipzy(call: CallbackQuery, order_id: int, link: str, qty: int, total: float):
    try:
        resp = await tipzy_create_order(link=link, quantity=qty, service_id=TIPZY_SERVICE_ID)
        tipzy_id = resp.get("order") if isinstance(resp, dict) else resp
        async with Database().session() as s:
            order = (await s.execute(select(TipzyOrder).where(TipzyOrder.id == order_id))).scalars().first()
            if order:
                order.tipzy_order_id = str(tipzy_id)
                order.status = "in_progress"
                await s.commit()
        await log_audit("user.order.created", user_id=call.from_user.id,
                        resource_type="TipzyOrder", resource_id=str(order_id),
                        details=f"tipzy={tipzy_id} qty={qty} paid={total:.2f}₽ link={link}")
        await call.message.answer(
            f"✅ <b>Заказ #{order_id} отправлен в обработку!</b>\n\n"
            f"⏱ Ожидайте — это займёт около минуты.\n"
            f"📬 Вы получите уведомление, когда заказ будет выполнен."
        )
        # Запускаем фоновую проверку статуса
        create_tracked_task(_watch_tipzy_status(call.bot, call.from_user.id, order_id, tipzy_id))
    except Exception as e:
        log.error(f"Tipzy error order #{order_id}: {e}")
        async with Database().session() as s:
            user = (await s.execute(select(User).where(User.telegram_id == call.from_user.id))).scalars().first()
            order = (await s.execute(select(TipzyOrder).where(TipzyOrder.id == order_id))).scalars().first()
            if user:
                user.balance = float(user.balance or 0) + total
            if order:
                order.status = "failed"
            await s.commit()
        await log_audit("user.order.failed", level="WARNING", user_id=call.from_user.id,
                        resource_type="TipzyOrder", resource_id=str(order_id),
                        details=str(e))
        await call.message.answer(
            f"❌ <b>Ошибка заказа #{order_id}</b>\n\n"
            f"Ошибка: {e}\n"
            f"💳 <b>{total:.2f} ₽ возвращены на баланс.</b>"
        )


# ─── Массовый заказ ────────────────────────────────────────────────────────

@router.message(F.text == "📦 Массовый заказ", StateFilter(None))
async def menu_mass(message: Message, state: FSMContext):
    await state.clear()
    await state.set_state(MassBuyState.waiting_good)
    
    # Показать список доступных товаров для выбора
    from bot.database import Database
    from bot.database.models.main import Goods
    from sqlalchemy import select
    
    async with Database().session() as s:
        goods_list = (await s.execute(
            select(Goods).order_by(Goods.id)
        )).scalars().all()
    
    if not goods_list:
        await message.answer("❌ Нет доступных товаров.", reply_markup=cancel_kb())
        return
    
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    buttons = []
    for g in goods_list:
        buttons.append([InlineKeyboardButton(
            text=f"{g.name} — {float(g.price):.2f}₽",
            callback_data=f"mass_good_{g.id}"
        )])
    buttons.append([InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")])
    
    await message.answer(
        "📦 <b>Массовый заказ</b>\n\nВыберите товар:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )


@router.callback_query(F.data.startswith("mass_good_"), MassBuyState.waiting_good)
async def mass_select_good(call: CallbackQuery, state: FSMContext):
    good_id = int(call.data.split("_")[-1])
    async with Database().session() as s:
        good = (await s.execute(select(Goods).where(Goods.id == good_id))).scalars().first()
    if not good or not good.is_available:
        await call.answer("❌ Товар недоступен", show_alert=True)
        return
    
    await state.update_data(mass_good_id=good_id, mass_good_name=good.name, mass_price=float(good.price))
    await call.answer()
    await call.message.edit_text(
        f"📦 <b>Массовый заказ</b> — <b>{good.name}</b>\n\n"
        f"💰 Цена за ссылку: <b>{good.price:.2f} ₽</b>\n\n"
        f"Отправьте ссылки (каждая с новой строки), максимум {MAX_MASS_LINKS} штук.",
        reply_markup=cancel_kb()
    )
    await state.set_state(MassBuyState.waiting_links)


@router.message(MassBuyState.waiting_links)
async def mass_links_input(message: Message, state: FSMContext):
    raw = message.text.strip()
    lines = [l.strip() for l in raw.splitlines() if l.strip()]
    valid = [l for l in lines if LINK_RE.match(l)]
    invalid = len(lines) - len(valid)

    if not valid:
        await message.answer(
            "❌ Не найдено ни одной валидной ссылки.\n"
            "Формат: <code>https://t.me/BotName?start=xxx</code>",
            reply_markup=cancel_kb(),
        )
        return

    if len(valid) > MAX_MASS_LINKS:
        valid = valid[:MAX_MASS_LINKS]
        await message.answer(f"⚠️ Взяты первые {MAX_MASS_LINKS} ссылок.")

    # Берём товар из state (выбранный пользователем), не первый из БД
    data = await state.get_data()
    price = data.get("mass_price", SELL_PRICE_PER_UNIT)
    good_name = data.get("mass_good_name", "Товар")

    qty = 1
    total_per_link = qty * price
    grand_total = total_per_link * len(valid)

    await state.update_data(links=valid, quantity=qty, price=price, good_name=good_name)
    await state.set_state(MassBuyState.confirm)

    warning = f"\n⚠️ {invalid} невалидных ссылок пропущено." if invalid else ""
    await message.answer(
        f"📋 <b>Подтверждение массового заказа</b>{warning}\n\n"
        f"🔗 Ссылок: <b>{len(valid)}</b>\n"
        f"🔢 Стартов на каждую: <b>{qty}</b>\n"
        f"💰 Стоимость каждой: <b>{total_per_link:.2f} ₽</b>\n"
        f"💸 Итого: <b>{grand_total:.2f} ₽</b>",
        reply_markup=mass_confirm_kb(),
    )


@router.callback_query(F.data == "confirm_mass", MassBuyState.confirm)
async def cb_confirm_mass(call: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    links: list[str] = data.get("links", [])
    qty: int = int(data.get("quantity", 1))
    price: float = float(data.get("price", SELL_PRICE_PER_UNIT))
    per_link_total = qty * price
    grand_total = per_link_total * len(links)

    await state.clear()

    async with Database().session() as s:
        user = (await s.execute(
            select(User).where(User.telegram_id == call.from_user.id).with_for_update()
        )).scalars().first()

        if not user or float(user.balance or 0) < grand_total:
            bal = float(user.balance or 0) if user else 0
            await call.answer(
                f"❌ Недостаточно средств. Баланс: {bal:.2f} ₽, нужно: {grand_total:.2f} ₽",
                show_alert=True,
            )
            return

        user.balance = float(user.balance) - grand_total
        orders = []
        for link in links:
            o = TipzyOrder(
                user_id=call.from_user.id,
                link=link,
                quantity=qty,
                price_paid=per_link_total,
                status="pending",
            )
            s.add(o)
            orders.append(o)
        await s.commit()
        for o in orders:
            await s.refresh(o)

    await call.message.edit_text(
        f"⏳ <b>Массовый заказ принят!</b>\n\n"
        f"📦 Ссылок: <b>{len(links)}</b>\n"
        f"💸 Списано: <b>{grand_total:.2f} ₽</b>\n\n"
        f"Отправляем запросы к сервису..."
    )
    await call.answer()

    # Запускаем tipzy для каждой ссылки
    done, failed = 0, 0
    for order in orders:
        try:
            resp = await tipzy_create_order(link=order.link, quantity=qty, service_id=TIPZY_SERVICE_ID)
            tipzy_id = resp.get("order") if isinstance(resp, dict) else resp
            async with Database().session() as s:
                o = (await s.execute(select(TipzyOrder).where(TipzyOrder.id == order.id))).scalars().first()
                if o:
                    o.tipzy_order_id = str(tipzy_id)
                    o.status = "in_progress"
                    await s.commit()
            done += 1
            create_tracked_task(_watch_tipzy_status(call.bot, call.from_user.id, order.id, tipzy_id))
        except Exception as e:
            log.error(f"Mass order tipzy error for #{order.id}: {e}")
            async with Database().session() as s:
                o = (await s.execute(select(TipzyOrder).where(TipzyOrder.id == order.id))).scalars().first()
                if o:
                    o.status = "failed"
                    await s.commit()
            # Возврат за провальный заказ (по реальной цене, не константе)
            async with Database().session() as s:
                u = (await s.execute(select(User).where(User.telegram_id == call.from_user.id))).scalars().first()
                if u and o:
                    u.balance = float(u.balance or 0) + float(o.price_paid or 0)
                    await s.commit()
            failed += 1

    result = f"✅ <b>Готово!</b>\n\n✔ Успешно: <b>{done}</b>\n❌ Ошибок: <b>{failed}</b>"
    if failed:
        # Recalculate actual refund from failed orders
        result += f"\n💳 Возврат за ошибки: <b>{failed * (per_link_total):.2f} ₽</b>"
    await call.message.answer(result)
