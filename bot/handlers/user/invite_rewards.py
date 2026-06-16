"""Invite-based referral handlers: deep link, channel verification, reward claiming."""
import logging

from aiogram import Router, F, Bot
from aiogram.types import (
    CallbackQuery, Message, InlineKeyboardButton, InlineKeyboardMarkup,
)
from aiogram.filters import CommandStart

from bot.misc.invite_rewards import (
    record_invite, verify_invite, get_referrer_stats,
    get_pending_reward, fulfill_reward, get_invite_link,
    INVITES_PER_REWARD, CHANNEL_ID, REWARD_GOODS_ID,
)
from bot.database.main import Database
from bot.database.models.main import User, BoughtGoods, ItemValues
from sqlalchemy import select

log = logging.getLogger(__name__)

router = Router()


# ── Notify referrer helper ──────────────────────────────────────────────────

async def _notify_referrer(bot: Bot, invited_user_id: int, event_type: str) -> None:
    """Send notification to referrer about invite activity."""
    async with Database().session() as s:
        from bot.misc.invite_rewards import ReferralInvite
        invite = (await s.execute(
            select(ReferralInvite).where(
                ReferralInvite.invited_user_id == invited_user_id,
            )
        )).scalars().first()

    if not invite:
        return

    referrer_id = invite.referrer_id
    stats = await get_referrer_stats(referrer_id)

    if event_type == "verified":
        text = (
            f"🔔 <b>Новый инвайт!</b>\n\n"
            f"Приглашённый пользователь подтвердил подписку.\n"
            f"📊 Всего инвайтов: <b>{stats['verified']}</b>\n"
        )
        if stats['next_reward_in'] > 0:
            text += f"🎯 До награды осталось: <b>{stats['next_reward_in']}</b> инвайтов\n"
        else:
            text += f"\n🎉 <b>Награда доступна!</b> Зайдите в «🎁 Пригласить друга» чтобы получить.\n"
    elif event_type == "pending_review":
        text = (
            f"👤 <b>Новый переход по вашей ссылке!</b>\n\n"
            f"Пользователь перешёл по ссылке, подписка на проверке.\n"
            f"📊 Всего инвайтов: <b>{stats['verified']}</b>"
            + (f" | 🎯 До награды: <b>{stats['next_reward_in']}</b>" if stats['next_reward_in'] > 0 else "")
        )
    elif event_type == "admin_approved":
        text = (
            f"✅ <b>Инвайт подтверждён!</b>\n\n"
            f"Администратор подтвердил подписку приглашённого.\n"
            f"📊 Всего инвайтов: <b>{stats['verified']}</b>\n"
        )
        if stats['next_reward_in'] > 0:
            text += f"🎯 До награды осталось: <b>{stats['next_reward_in']}</b> инвайтов\n"
        else:
            text += f"\n🎉 <b>Награда доступна!</b> Зайдите в «🎁 Пригласить друга» чтобы получить.\n"
    else:
        return

    try:
        await bot.send_message(referrer_id, text)
    except Exception:
        pass  # user may have blocked bot


# ── "Пригласить друга" button from main menu ────────────────────────────────

@router.message(F.text == "🎁 Пригласить друга")
async def invite_friend_button(message: Message, bot: Bot) -> None:
    """Handle 'Invite friend' button from main menu."""
    user_id = message.from_user.id
    stats = await get_referrer_stats(user_id)

    me = await bot.get_me()
    link = await get_invite_link(user_id, me.username)

    text = (
        f"🎁 <b>Реферальная программа</b>\n\n"
        f"Приглашайте друзей по ссылке. Когда друг подпишется\n"
        f"на канал @clerkstore_news, вы получите +1 инвайт.\n\n"
        f"За <b>{INVITES_PER_REWARD} инвайтов</b> — бесплатная\n"
        f"активация FreeModel!\n\n"
        f"📊 <b>Ваша статистика:</b>\n"
        f"  ✅ Подтверждённых: <b>{stats['verified']}</b>\n"
        f"  ⏳ Ожидают: <b>{stats['pending']}</b>\n"
        f"  🎁 Наград получено: <b>{stats['rewards_total']}</b>\n"
    )

    if stats['next_reward_in'] > 0:
        text += f"\n🎯 До следующей награды: <b>{stats['next_reward_in']}</b> инвайтов\n"
    elif stats['verified'] > 0:
        text += f"\n🎉 Награда доступна! Нажмите кнопку ниже\n"

    text += f"\n🔗 <b>Ваша ссылка:</b>\n<code>{link}</code>"

    buttons = [
        [InlineKeyboardButton(text="📋 Скопировать ссылку", switch_inline_query=link)],
    ]

    if stats['rewards_unfulfilled'] > 0:
        buttons.append([
            InlineKeyboardButton(
                text=f"🎁 Получить награду ({stats['rewards_unfulfilled']})",
                callback_data="claim_invite_reward",
            ),
        ])

    await message.answer(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        disable_web_page_preview=True,
    )


# ── Deep link handler (/start invite_<referrer_id>) ─────────────────────────

async def handle_invite_start(message: Message, referrer_id: int) -> None:
    """Process invite deep link."""
    invited_id = message.from_user.id

    if invited_id == referrer_id:
        await message.answer("❌ Нельзя пригласить самого себя.")
        return

    ok, reason = await record_invite(referrer_id, invited_id)

    if reason == "already_invited":
        await message.answer(
            "ℹ️ Вы уже были приглашены другим пользователем.\n"
            "Подпишитесь на канал и нажмите «Проверить подписку», если ещё не сделали это."
        )
    elif ok:
        await message.answer(
            "🎉 <b>Приглашение принято!</b>\n\n"
            "📢 Подпишитесь на наш новостной канал и нажмите кнопку ниже:\n\n"
            f"После подписки вашему другу начислится +1 инвайт.\n"
            f"За <b>{INVITES_PER_REWARD} инвайтов</b> — бесплатная активация FreeModel!",
            reply_markup=_verify_keyboard(),
        )
    else:
        await message.answer("❌ Не удалось обработать приглашение.")


def _verify_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="📢 Подписаться на канал",
            url=f"https://t.me/clerkstore_news",
        )],
        [InlineKeyboardButton(
            text="✅ Проверить подписку",
            callback_data="verify_channel_sub",
        )],
    ])


# ── Verify subscription callback ────────────────────────────────────────────

@router.callback_query(F.data == "verify_channel_sub")
async def verify_subscription_callback(call: CallbackQuery, bot: Bot) -> None:
    """Verify that user is subscribed to the channel."""
    user_id = call.from_user.id

    ok, reason = await verify_invite(bot, user_id)

    if ok:
        await call.message.edit_text(
            "✅ <b>Подписка подтверждена!</b>\n\n"
            "Спасибо! Вашему другу начислен +1 инвайт.\n"
            "Добро пожаловать в ClerkStore! 🎉",
        )

    elif reason == "already_invited":
        await call.answer("ℹ️ Вы уже были учтены.", show_alert=True)
    elif reason == "no_pending_invite":
        await call.answer("ℹ️ Нет активного приглашения.", show_alert=True)
    elif reason == "daily_limit":
        await call.answer("⏳ Лимит инвайтов на сегодня исчерпан.", show_alert=True)
    elif reason == "account_too_young":
        await call.answer("⏳ Ваш аккаунт слишком новый. Попробуйте позже.", show_alert=True)
    elif reason == "is_bot":
        await call.answer("❌ Боты не могут быть приглашены.", show_alert=True)
    elif reason == "bot_not_admin":
        await call.answer("⚠️ Техническая ошибка. Обратитесь в поддержку.", show_alert=True)
    else:
        await call.answer("❌ Не удалось проверить подписку.", show_alert=True)

    # Notify referrer on successful auto-verify
    if ok:
        await _notify_referrer(bot, user_id, "verified")


# ── Invite stats & rewards ──────────────────────────────────────────────────

@router.callback_query(F.data == "my_invites")
async def my_invites_callback(call: CallbackQuery, bot: Bot) -> None:
    """Show invite stats and link."""
    user_id = call.from_user.id
    stats = await get_referrer_stats(user_id)

    # Get bot username
    me = await bot.get_me()
    link = await get_invite_link(user_id, me.username)

    text = (
        f"🎁 <b>Реферальная программа</b>\n\n"
        f"Приглашайте друзей по ссылке. Когда друг подпишется на канал,\n"
        f"вы получите +1 инвайт. За <b>{INVITES_PER_REWARD} инвайтов</b> —\n"
        f"бесплатная активация FreeModel!\n\n"
        f"📊 <b>Ваша статистика:</b>\n"
        f"  ✅ Подтверждённых: <b>{stats['verified']}</b>\n"
        f"  ⏳ Ожидают: <b>{stats['pending']}</b>\n"
        f"  🎁 Наград получено: <b>{stats['rewards_total']}</b>\n"
    )

    if stats['next_reward_in'] > 0:
        text += f"\n🎯 До следующей награды: <b>{stats['next_reward_in']}</b> инвайтов\n"
    elif stats['verified'] > 0:
        text += f"\n🎉 Награда доступна! Нажмите «Получить награду»\n"

    text += f"\n🔗 <b>Ваша ссылка:</b>\n<code>{link}</code>"

    buttons = [
        [InlineKeyboardButton(text="📋 Скопировать ссылку", switch_inline_query=link)],
    ]

    if stats['rewards_unfulfilled'] > 0:
        buttons.append([
            InlineKeyboardButton(text=f"🎁 Получить награду ({stats['rewards_unfulfilled']})", callback_data="claim_invite_reward"),
        ])

    buttons.append([InlineKeyboardButton(text="🔙 Назад", callback_data="cancel")])

    await call.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        disable_web_page_preview=True,
    )


@router.callback_query(F.data == "claim_invite_reward")
async def claim_reward_callback(call: CallbackQuery, bot: Bot) -> None:
    """Claim unfulfilled FreeModel activation reward."""
    user_id = call.from_user.id

    reward = await get_pending_reward(user_id)
    if not reward:
        await call.answer("ℹ️ Нет доступных наград.", show_alert=True)
        return

    # Grant FreeModel activation: add to BoughtGoods (infinity item)
    try:
        async with Database().session() as s:
            # Get the FreeModel product
            from bot.database.models.main import Goods
            goods = (await s.execute(
                select(Goods).where(Goods.id == REWARD_GOODS_ID)
            )).scalars().first()

            if not goods:
                await call.answer("❌ Товар FreeModel не найден.", show_alert=True)
                return

            # Check for available stock (infinity items)
            stock = (await s.execute(
                select(ItemValues).where(
                    ItemValues.item_id == REWARD_GOODS_ID,
                    ItemValues.is_infinity == True,
                )
            )).scalars().first()

            if not stock:
                await call.answer("❌ Нет доступных активаций.", show_alert=True)
                return

            # Create purchase record
            import random
            unique_id = random.randint(100000000, 999999999)

            purchase = BoughtGoods(
                name=goods.name,
                value=stock.value,
                price=0,  # free reward
                bought_datetime=func.now(),
                unique_id=unique_id,
                buyer_id=user_id,
            )
            s.add(purchase)
            await s.commit()

        # Mark reward as fulfilled
        await fulfill_reward(reward['id'])

        await call.message.edit_text(
            f"🎉 <b>Награда получена!</b>\n\n"
            f"📦 Товар: <b>FreeModel Activate</b>\n"
            f"🆔 ID: <code>{unique_id}</code>\n\n"
            f"Проверьте раздел «Мои покупки» для деталей.\n"
            f"Спасибо за приглашения! 🙏",
        )

    except Exception as e:
        log.error("Failed to grant reward %s to %s: %s", reward['id'], user_id, e)
        await call.answer("❌ Ошибка при выдаче награды.", show_alert=True)
