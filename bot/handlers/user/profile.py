"""Profile, statuses, my orders, promo handlers."""
import logging
from datetime import datetime, timezone
from aiogram import Router, F
from aiogram.filters import StateFilter
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy import select, func

from bot.database.main import Database
from bot.database.models.main import User, TipzyOrder, PromoCodes, PromoCodeUsages
from bot.keyboards.inline import profile_kb, statuses_kb, cancel_kb, main_menu_kb
from bot.utils.levels import get_level

router = Router()
log = logging.getLogger(__name__)


class PromoState(StatesGroup):
    waiting_code = State()


async def _get_or_create_user(tg_id: int, first_name: str = "") -> User | None:
    async with Database().session() as s:
        user = (await s.execute(select(User).where(User.telegram_id == tg_id))).scalars().first()
        return user


async def _profile_text_and_kb(tg_id: int, first_name: str, balance: float, reg_date) -> tuple[str, any]:
    async with Database().session() as s:
        result = (await s.execute(
            select(
                func.coalesce(func.count(TipzyOrder.id), 0),
                func.coalesce(func.sum(TipzyOrder.price_paid), 0.0),
            )
            .where(TipzyOrder.user_id == tg_id, TipzyOrder.status.in_(("completed", "partial")))
        )).one()
    orders_count = result[0] or 0
    spent = float(result[1] or 0.0)

    level_full, level_name = get_level(spent)
    reg_str = reg_date.strftime("%d.%m.%Y %H:%M") if reg_date else "—"

    # Invite stats
    invite_line = ""
    try:
        from bot.misc.invite_rewards import get_referrer_stats
        stats = await get_referrer_stats(tg_id)
        if stats["verified"] > 0 or stats["pending"] > 0:
            invite_line = (
                f"\n🎁 Инвайтов: <b>{stats['verified']}</b>"
                f" (наград: {stats['rewards_total']})"
            )
    except Exception:
        pass

    text = (
        f"<b>Профиль</b>\n\n"
        f"🆔 ID пользователя: <code>{tg_id}</code>\n"
        f"📛 Имя: {first_name}\n"
        f"💳 Баланс: <b>{balance:.2f} ₽</b>\n"
        f"{level_full} Уровень: {level_name}\n"
        f"📦 Всего покупок: <b>{orders_count}</b>\n"
        f"💸 Потрачено: <b>{spent:.2f} ₽</b>\n"
        f"📅 Дата регистрации: <code>{reg_str}</code>"
        f"{invite_line}"
    )
    return text, profile_kb()


@router.message(F.text == "👤 Профиль", StateFilter(None))
async def menu_profile(message: Message, state: FSMContext):
    await state.clear()
    user = await _get_or_create_user(message.from_user.id, message.from_user.first_name)
    if not user:
        await message.answer("❌ Профиль не найден. Нажми /start")
        return

    text, kb = await _profile_text_and_kb(
        tg_id=message.from_user.id,
        first_name=message.from_user.full_name or message.from_user.first_name,
        balance=float(user.balance or 0),
        reg_date=user.registration_date,
    )
    await message.answer(text, reply_markup=kb)


@router.callback_query(F.data == "back_profile")
async def cb_back_profile(call: CallbackQuery, state: FSMContext):
    await state.clear()
    user = await _get_or_create_user(call.from_user.id)
    if not user:
        await call.answer()
        return
    text, kb = await _profile_text_and_kb(
        tg_id=call.from_user.id,
        first_name=call.from_user.full_name or call.from_user.first_name,
        balance=float(user.balance or 0),
        reg_date=user.registration_date,
    )
    try:
        await call.message.edit_text(text, reply_markup=kb)
    except Exception:
        await call.message.answer(text, reply_markup=kb)
    await call.answer()


# ─── Мои заказы ────────────────────────────────────────────────────────────

@router.callback_query(F.data == "my_orders")
async def cb_my_orders(call: CallbackQuery):
    async with Database().session() as s:
        orders = (await s.execute(
            select(TipzyOrder)
            .where(TipzyOrder.user_id == call.from_user.id)
            .order_by(TipzyOrder.created_at.desc())
            .limit(10)
        )).scalars().all()

    if not orders:
        from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="◀️ Назад", callback_data="back_profile")
        ]])
        await call.message.edit_text("📭 У тебя пока нет заказов", reply_markup=kb)
        await call.answer()
        return

    STATUS_ICON = {
        "pending": "⏳", "processing": "🔄", "completed": "✅",
        "partial": "🟡", "failed": "❌", "refunded": "↩️", "cancelled": "🚫"
    }

    lines = ["<b>📋 Мои заказы</b> (последние 10)\n"]
    for o in orders:
        icon = STATUS_ICON.get(o.status, "❓")
        date_str = o.created_at.strftime("%d.%m.%Y") if o.created_at else "—"
        link_short = o.link[:30] + "…" if len(o.link) > 30 else o.link
        lines.append(
            f"{icon} <code>#{o.id}</code> — {o.quantity} шт — {float(o.price_paid):.2f}₽\n"
            f"   🔗 {link_short}\n"
            f"   📅 {date_str}"
        )

    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="◀️ Назад", callback_data="back_profile")
    ]])
    await call.message.edit_text("\n\n".join(lines), reply_markup=kb)
    await call.answer()


# ─── Статусы ───────────────────────────────────────────────────────────────

@router.callback_query(F.data == "statuses")
async def cb_statuses(call: CallbackQuery):
    text = (
        "<b>⭐ Система уровней</b>\n\n"
        "Уровень зависит от суммы всех покупок:\n\n"
        "⭐ <b>Новичок</b> — 0 ₽\n"
        "🥈 <b>Опытный</b> — от 500 ₽\n"
        "🥇 <b>Продвинутый</b> — от 3 000 ₽\n"
        "💎 <b>Премиум</b> — от 10 000 ₽\n\n"
        "Чем выше уровень — тем больше скидок и приоритет в обработке заказов."
    )
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="◀️ Назад", callback_data="back_profile")
    ]])
    await call.message.edit_text(text, reply_markup=kb)
    await call.answer()


# ─── Промокод ──────────────────────────────────────────────────────────────

@router.callback_query(F.data == "activate_promo")
async def cb_activate_promo(call: CallbackQuery, state: FSMContext):
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="❌ Отмена", callback_data="back_profile")
    ]])
    await call.message.edit_text(
        "🎫 <b>Активация промокода</b>\n\nВведи промокод:",
        reply_markup=kb
    )
    await state.set_state(PromoState.waiting_code)
    await call.answer()


@router.message(PromoState.waiting_code)
async def promo_code_input(message: Message, state: FSMContext):
    code = message.text.strip().upper()
    now = datetime.now(timezone.utc)

    async with Database().session() as s:
        promo = (await s.execute(
            select(PromoCodes).where(PromoCodes.code == code).with_for_update()
        )).scalars().first()

        if not promo or not promo.is_active:
            await message.answer("❌ Промокод не найден или недействителен", reply_markup=cancel_kb("back_profile"))
            return

        if promo.expires_at and promo.expires_at < now:
            await message.answer("❌ Срок действия промокода истёк", reply_markup=cancel_kb("back_profile"))
            return

        if promo.max_uses > 0 and promo.current_uses >= promo.max_uses:
            await message.answer("❌ Промокод уже исчерпал лимит использований", reply_markup=cancel_kb("back_profile"))
            return

        # Проверяем что юзер ещё не использовал этот промокод
        already = (await s.execute(
            select(PromoCodeUsages).where(
                PromoCodeUsages.promo_id == promo.id,
                PromoCodeUsages.user_id == message.from_user.id
            )
        )).scalars().first()
        if already:
            await message.answer("❌ Вы уже использовали этот промокод", reply_markup=cancel_kb("back_profile"))
            return

        user = (await s.execute(
            select(User).where(User.telegram_id == message.from_user.id).with_for_update()
        )).scalars().first()
        if not user:
            await state.clear()
            return

        balance = float(user.balance or 0)
        disc_val = float(promo.discount_value or 0)

        if promo.discount_type == "percent":
            bonus = round(balance * disc_val / 100, 2)
            desc = f"{disc_val:.0f}% на баланс → +{bonus:.2f} ₽"
        else:
            bonus = disc_val
            desc = f"+{bonus:.2f} ₽ на баланс"

        user.balance = balance + bonus
        promo.current_uses = (promo.current_uses or 0) + 1
        s.add(PromoCodeUsages(promo_id=promo.id, user_id=message.from_user.id))
        await s.commit()

    await state.clear()
    await message.answer(
        f"✅ <b>Промокод активирован!</b>\n\n🎁 {desc}",
        reply_markup=main_menu_kb()
    )


# ─── Уведомления / Валюта (заглушки) ───────────────────────────────────────

@router.callback_query(F.data == "notifications")
async def cb_notifications(call: CallbackQuery):
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="◀️ Назад", callback_data="back_profile")
    ]])
    await call.message.edit_text(
        "🔔 <b>Уведомления</b>\n\nФункция в разработке. Скоро будет доступна.",
        reply_markup=kb
    )
    await call.answer()


@router.callback_query(F.data == "currency")
async def cb_currency(call: CallbackQuery):
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="◀️ Назад", callback_data="back_profile")
    ]])
    await call.message.edit_text(
        "💱 <b>Валюта</b>\n\nВ настоящее время используется: <b>₽ (рубли)</b>\n\nСмена валюты скоро будет доступна.",
        reply_markup=kb
    )
    await call.answer()


@router.callback_query(F.data == "withdrawal")
async def cb_withdrawal(call: CallbackQuery):
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="◀️ Назад", callback_data="back_profile")
    ]])
    await call.message.edit_text(
        "💸 <b>Вывод средств</b>\n\nВывод средств недоступен. Баланс можно использовать только для покупки услуг.",
        reply_markup=kb
    )
    await call.answer()
