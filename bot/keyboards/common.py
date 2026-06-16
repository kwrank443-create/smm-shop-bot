from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton,
)

def main_menu_kb(is_admin: bool = False) -> ReplyKeyboardMarkup:
    rows = [
        [KeyboardButton(text="🛒 Каталог"), KeyboardButton(text="📦 Массовый заказ")],
        [KeyboardButton(text="👤 Профиль"), KeyboardButton(text="📋 Мои заказы")],
        [KeyboardButton(text="💳 Пополнить"), KeyboardButton(text="ℹ️ Помощь")],
    ]
    if is_admin:
        rows.append([KeyboardButton(text="🛠 Админка")])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)

def cancel_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")],
    ])

def confirm_kb(yes_data: str = "confirm", no_data: str = "cancel") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Подтвердить", callback_data=yes_data),
            InlineKeyboardButton(text="❌ Отмена", callback_data=no_data),
        ]
    ])

def back_to_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏠 В меню", callback_data="menu")],
    ])
