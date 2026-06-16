"""Start, main menu, help, language handlers."""
import logging
from datetime import datetime, timezone
from aiogram import Router, F
from aiogram.filters import CommandStart, Command, StateFilter
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from sqlalchemy import select

from bot.database.main import Database
from bot.database.models.main import User
from bot.keyboards.inline import main_menu_kb, language_kb, cancel_kb
from bot.misc.env import EnvKeys
from bot.i18n import set_user_lang
from bot.database.methods.audit import log_audit

router = Router()
log = logging.getLogger(__name__)

SUPPORT_USERNAME = "@your_support"  # поменяй на своего


async def _get_or_create_user(tg_id: int, full_name: str = "", username: str | None = None) -> User:
    async with Database().session() as s:
        user = (await s.execute(select(User).where(User.telegram_id == tg_id))).scalars().first()
        if not user:
            user = User(
                telegram_id=tg_id,
                balance=0.0,
                registration_date=datetime.now(timezone.utc),
            )
            s.add(user)
            await s.commit()
            await s.refresh(user)
            await log_audit("user.registered", user_id=tg_id, details=f"tg={tg_id}")
        return user


# ─── /start ────────────────────────────────────────────────────────────────

@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()

    # Parse start parameter for invite deep link
    start_param = message.text.split(maxsplit=1)[1] if len(message.text.split()) > 1 else ""
    is_invite = start_param.startswith("invite_")

    user = await _get_or_create_user(
        message.from_user.id,
        message.from_user.full_name,
        message.from_user.username,
    )

    # Handle invite deep link
    if is_invite:
        try:
            referrer_id = int(start_param.split("_", 1)[1])
        except (ValueError, IndexError):
            referrer_id = None

        if referrer_id and referrer_id != message.from_user.id:
            from bot.handlers.user.invite_rewards import handle_invite_start
            await handle_invite_start(message, referrer_id)
            return

    name = message.from_user.first_name or "пользователь"
    await message.answer(
        f"👋 Привет, <b>{name}</b>!\n\n"
        f"Добро пожаловать в магазин. Здесь ты можешь купить услуги активации и цифровые товары.\n\n"
        f"Выбери нужный раздел 👇",
        reply_markup=main_menu_kb(),
    )


# ─── Cancel (universal) ────────────────────────────────────────────────────

@router.callback_query(F.data == "cancel")
async def cb_cancel(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.message.delete()
    await call.answer("Отменено.")


# ─── Язык ──────────────────────────────────────────────────────────────────

@router.message(F.text == "🌐 Язык")
async def menu_language(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "🌐 Выберите язык / Choose language",
        reply_markup=language_kb(),
    )


@router.callback_query(F.data.in_({"lang_ru", "lang_en"}))
async def cb_language(call: CallbackQuery):
    lang_code = "ru" if call.data == "lang_ru" else "en"
    lang_name = "Русский 🇷🇺" if lang_code == "ru" else "English 🇬🇧"
    set_user_lang(call.from_user.id, lang_code)

    # persist to DB
    async with Database().session() as s:
        user = (await s.execute(select(User).where(User.telegram_id == call.from_user.id))).scalar_one_or_none()
        if user:
            user.language = lang_code
            await s.commit()

    await call.message.edit_text(f"✅ Язык установлен: <b>{lang_name}</b>")
    await call.answer()
    await call.message.answer(
        "Привет! Выбери действие 👇" if lang_code == "ru" else "Hello! Choose an action 👇",
        reply_markup=main_menu_kb()
    )


# ─── Помощь и правила ──────────────────────────────────────────────────────

@router.message(F.text == "❓ Помощь и правила", StateFilter(None))
async def menu_help(message: Message, state: FSMContext):
    await state.clear()
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✍️ Написать в поддержку", url="https://t.me/clerkstoresupport_bot")],
        [InlineKeyboardButton(text="❓ Частые вопросы", url="https://t.me/clerkstoresupport_bot?start=faq")],
    ])
    text = (
        "❓ <b>Помощь и правила</b>\n\n"
        "📄 <a href=\"https://telegra.ph/Polzovatelskoe-soglashenie-05-29-25\">Пользовательское соглашение</a>\n"
        "⚖️ <a href=\"https://telegra.ph/Usloviya-obsluzhivaniya-TOS-05-29\">Условия обслуживания (TOS)</a>\n\n"
        "🆘 <b>Поддержка</b> — отдельный бот @clerkstoresupport_bot\n"
        "• Часы работы: 10:00–22:00 МСК\n"
        "• Среднее время ответа: до 30 минут\n\n"
        "💡 Перед обращением загляните в «Частые вопросы»."
    )
    await message.answer(text, reply_markup=kb, disable_web_page_preview=True)


