"""All keyboards for the bot."""
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton


# ─── Reply (main menu) ─────────────────────────────────────────────────────

def main_menu_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="💳 Пополнить баланс"), KeyboardButton(text="🛒 Купить")],
            [KeyboardButton(text="📦 Массовый заказ"),   KeyboardButton(text="👤 Профиль")],
            [KeyboardButton(text="🎁 Пригласить друга"), KeyboardButton(text="❓ Помощь и правила")],
            [KeyboardButton(text="🌐 Язык")],
        ],
        resize_keyboard=True,
        one_time_keyboard=False,
    )


# ─── Cancel ────────────────────────────────────────────────────────────────

def cancel_kb(cb: str = "cancel") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="❌ Отмена", callback_data=cb)
    ]])


def profile_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎫 Активировать промокод", callback_data="activate_promo")],
        [InlineKeyboardButton(text="🎁 Пригласить друга",      callback_data="my_invites")],
        [InlineKeyboardButton(text="⭐ Статусы",              callback_data="statuses")],
        [InlineKeyboardButton(text="📋 Мои заказы",           callback_data="my_orders")],
        [InlineKeyboardButton(text="💸 Вывод средств",        callback_data="withdrawal")],
        [InlineKeyboardButton(text="🔔 Уведомления",          callback_data="notifications")],
        [InlineKeyboardButton(text="💱 Валюта",               callback_data="currency")],
    ])


def back_cancel_kb(back_cb: str = "back") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data=back_cb),
         InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")],
    ])


# ─── Пополнение ────────────────────────────────────────────────────────────

def deposit_methods_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 Через Platega (СБП/Карта/Крипта)", callback_data="pay_platega")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")],
    ])


def check_payment_kb(invoice_url: str, payment_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 Оплатить", url=invoice_url)],
        [InlineKeyboardButton(text="🔄 Проверить оплату", callback_data=f"check_pay_{payment_id}")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")],
    ])


# ─── Каталог ───────────────────────────────────────────────────────────────

def categories_kb(categories: list) -> InlineKeyboardMarkup:
    """categories: list of Categories ORM objects"""
    rows = []
    for cat in categories:
        rows.append([InlineKeyboardButton(text=cat.name, callback_data=f"cat_{cat.id}")])
    rows.append([InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def products_kb(goods: list, category_id: int) -> InlineKeyboardMarkup:
    """goods: list of Goods ORM objects"""
    rows = []
    for g in goods:
        # format: Name - Price
        label = f"{g.name}"
        rows.append([InlineKeyboardButton(text=label, callback_data=f"good_{g.id}")])
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data=f"back_cat_{category_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def product_detail_kb(good_id: int, category_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛒 Купить", callback_data=f"buy_{good_id}")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"back_goods_{category_id}")],
    ])


def confirm_order_kb(good_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Подтвердить", callback_data=f"confirm_order_{good_id}"),
         InlineKeyboardButton(text="❌ Отмена",       callback_data="cancel")],
    ])


def mass_confirm_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Подтвердить",  callback_data="confirm_mass"),
         InlineKeyboardButton(text="❌ Отмена",        callback_data="cancel")],
    ])


# ─── Профиль ───────────────────────────────────────────────────────────────

def statuses_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_profile")],
    ])


def my_orders_kb(page: int = 1, has_next: bool = False) -> InlineKeyboardMarkup:
    nav = []
    if page > 1:
        nav.append(InlineKeyboardButton(text="◀️", callback_data=f"orders_page_{page - 1}"))
    if has_next:
        nav.append(InlineKeyboardButton(text="▶️", callback_data=f"orders_page_{page + 1}"))
    rows = []
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="back_profile")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ─── Язык ──────────────────────────────────────────────────────────────────

def language_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🇷🇺 Русский",   callback_data="lang_ru"),
         InlineKeyboardButton(text="🇬🇧 English",   callback_data="lang_en")],
    ])


# ─── Промокод ──────────────────────────────────────────────────────────────

def promo_back_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_profile")],
    ])


# ─── Original admin keyboards (needed by admin handlers) ───────────────────
from typing import Callable, Iterable, Tuple
from aiogram.utils.keyboard import InlineKeyboardBuilder
from bot.i18n import localize
from bot.database.models import Permission
from bot.misc import LazyPaginator  # noqa: F401


def admin_console_keyboard(maintenance_mode: bool = False, role: int = 127) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    if role & Permission.CATALOG_MANAGE:
        kb.button(text=localize("admin.menu.shop"), callback_data="shop_management")
        kb.button(text=localize("admin.menu.goods"), callback_data="goods_management")
        kb.button(text=localize("admin.menu.categories"), callback_data="categories_management")
    if role & Permission.PROMO_MANAGE:
        kb.button(text=localize("admin.menu.promo"), callback_data="promo_mgmt")
    if role & Permission.USERS_MANAGE:
        kb.button(text=localize("admin.menu.users"), callback_data="user_management")
    if role & Permission.ADMINS_MANAGE:
        kb.button(text=localize("admin.menu.roles"), callback_data="role_mgmt")
    if role & Permission.BROADCAST:
        kb.button(text=localize("admin.menu.broadcast"), callback_data="send_message")
    if role & Permission.SETTINGS_MANAGE:
        maintenance_key = "admin.menu.maintenance_on" if maintenance_mode else "admin.menu.maintenance_off"
        kb.button(text=localize(maintenance_key), callback_data="toggle_maintenance")
    kb.button(text=localize("btn.back"), callback_data="back_to_menu")
    kb.adjust(1)
    return kb.as_markup()


def simple_buttons(buttons: Iterable[Tuple[str, str]], per_row: int = 1) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for text, cb in buttons:
        kb.button(text=text, callback_data=cb)
    kb.adjust(per_row)
    return kb.as_markup()


def back(cb: str = "menu", text: str | None = None) -> InlineKeyboardMarkup:
    return simple_buttons([(text or localize("btn.back"), cb)])


def close() -> InlineKeyboardMarkup:
    return simple_buttons([(localize("btn.close"), "close")])


async def lazy_paginated_keyboard(
        paginator: 'LazyPaginator',
        item_text: Callable[[object], str],
        item_callback: Callable[[object], str],
        page: int = 0,
        back_cb: str | None = None,
        nav_cb_prefix: str = "",
        back_text: str | None = None,
) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    items = await paginator.get_page(page)
    for item in items:
        kb.button(text=item_text(item), callback_data=item_callback(item))
    kb.adjust(1)
    total_pages = await paginator.get_total_pages()
    if total_pages > 1:
        nav_buttons = []
        if page > 0:
            nav_buttons.append(InlineKeyboardButton(text="◀️", callback_data=f"{nav_cb_prefix}{page - 1}"))
        nav_buttons.append(InlineKeyboardButton(text=f"{page + 1}/{total_pages}", callback_data="noop"))
        if page < total_pages - 1:
            nav_buttons.append(InlineKeyboardButton(text="▶️", callback_data=f"{nav_cb_prefix}{page + 1}"))
        kb.row(*nav_buttons)
    if back_cb:
        kb.row(InlineKeyboardButton(text=back_text or localize("btn.back"), callback_data=back_cb))
    return kb.as_markup()


def item_info(item_name: str, category_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text=localize("btn.buy"), callback_data=f"buy_{item_name}")
    kb.button(text=localize("btn.back"), callback_data=f"goods_{category_id}_0")
    kb.adjust(1)
    return kb.as_markup()


def payment_menu(pay_url: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text=localize("btn.pay"), url=pay_url)
    kb.button(text=localize("btn.check_payment"), callback_data="check_payment")
    kb.button(text=localize("btn.back"), callback_data="back_to_menu")
    kb.adjust(1)
    return kb.as_markup()


def get_payment_choice() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text=localize("btn.pay.crypto"), callback_data="pay_cryptopay")
    kb.button(text=localize("btn.pay.stars"),  callback_data="pay_stars")
    kb.button(text=localize("btn.back"),        callback_data="back_to_menu")
    kb.adjust(1)
    return kb.as_markup()


def question_buttons(question: str, back_data: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text=localize("btn.yes"), callback_data=f"yes_{question}")
    kb.button(text=localize("btn.no"),  callback_data=back_data)
    kb.adjust(2)
    return kb.as_markup()


def check_sub(channel_username: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text=localize("subscribe.open_channel"), url=f"https://t.me/{channel_username.lstrip('@')}")
    kb.button(text=localize("btn.check_subscription"), callback_data="check_subscription")
    kb.adjust(1)
    return kb.as_markup()


def rating_keyboard(item_name: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for i in range(1, 6):
        kb.button(text=str(i), callback_data=f"rate_{item_name}_{i}")
    kb.adjust(5)
    return kb.as_markup()


def referral_system_keyboard(has_referrals: bool = False, has_earnings: bool = False) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    if has_referrals:
        kb.button(text=localize("btn.view_referrals"), callback_data="view_referrals")
    if has_earnings:
        kb.button(text=localize("btn.view_earnings"), callback_data="view_earnings")
    kb.button(text=localize("btn.back"), callback_data="back_to_menu")
    kb.adjust(1)
    return kb.as_markup()
