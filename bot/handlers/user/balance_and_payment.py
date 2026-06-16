"""Balance top-up flow (Platega)."""
import logging
from datetime import datetime
from aiogram import Router, F
from aiogram.filters import StateFilter
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy import select

from bot.database.main import Database
from bot.database.models.main import User, Payments
from bot.keyboards.inline import deposit_methods_kb, check_payment_kb, cancel_kb, main_menu_kb
from bot.misc.env import EnvKeys
from bot.services.platega import create_payment_link, check_payment_status

router = Router()
log = logging.getLogger(__name__)

MIN_AMOUNT = float(getattr(EnvKeys, "MIN_AMOUNT", 10))
MAX_AMOUNT = float(getattr(EnvKeys, "MAX_AMOUNT", 50000))


class DepositState(StatesGroup):
    waiting_amount = State()
    waiting_method  = State()


# ─── Пополнить баланс ──────────────────────────────────────────────────────

@router.message(F.text == "💳 Пополнить баланс", StateFilter(None))
async def menu_deposit(message: Message, state: FSMContext):
    await state.clear()
    await state.set_state(DepositState.waiting_amount)
    await message.answer(
        f"💳 Введите сумму пополнения (минимум {MIN_AMOUNT:.2f} ₽):",
        reply_markup=cancel_kb(),
    )


@router.message(DepositState.waiting_amount)
async def deposit_amount_input(message: Message, state: FSMContext):
    text = message.text.strip().replace(",", ".")
    try:
        amount = float(text)
    except ValueError:
        await message.answer(f"❌ Введите число, например: <code>100</code>", reply_markup=cancel_kb())
        return

    if amount < MIN_AMOUNT:
        await message.answer(
            f"❌ Минимальная сумма — <b>{MIN_AMOUNT:.2f} ₽</b>",
            reply_markup=cancel_kb(),
        )
        return

    if amount > MAX_AMOUNT:
        await message.answer(
            f"❌ Максимальная сумма — <b>{MAX_AMOUNT:.0f} ₽</b>",
            reply_markup=cancel_kb(),
        )
        return

    await state.update_data(amount=amount)
    await state.set_state(DepositState.waiting_method)
    await message.answer(
        f"💰 Сумма: <b>{amount:.2f} ₽</b>\n\nВыберите способ пополнения:",
        reply_markup=deposit_methods_kb(),
    )


# ─── Выбор метода оплаты ───────────────────────────────────────────────────

@router.callback_query(F.data.startswith("pay_"), DepositState.waiting_method)
async def cb_pay_platega(call: CallbackQuery, state: FSMContext):
    log.info(f"cb_pay_platega: {call.data}")
    data = await state.get_data()
    amount = data.get("amount")
    if not amount:
        await call.answer("❌ Сессия истекла. Начни заново.", show_alert=True)
        await state.clear()
        return

    # Создаём запись о платеже
    async with Database().session() as s:
        user = (await s.execute(
            select(User).where(User.telegram_id == call.from_user.id)
        )).scalars().first()

        if not user:
            await state.clear()
            await call.answer("❌ Профиль не найден. Нажми /start", show_alert=True)
            return

        # Создаём платёжную ссылку через Platega API
        log.info(f"cb_pay_platega: create_payment_link for amount={amount}")
        payment_data = await create_payment_link(
            amount=amount,
            user_id=user.telegram_id,
            description=f"Пополнение баланса {amount:.2f} ₽",
        )
        log.info(f"cb_pay_platega: payment_data={payment_data}")

        if not payment_data:
            await state.clear()
            await call.answer("❌ Ошибка создания платежа. Попробуй позже.", show_alert=True)
            return

        transaction_id = payment_data.get("transactionId")
        invoice_url = payment_data.get("url")

        payment = Payments(
            user_id=user.telegram_id,
            amount=amount,
            currency="RUB",
            provider="platega",
            external_id=transaction_id,
            status="pending",
        )
        s.add(payment)
        await s.commit()
        await s.refresh(payment)
        payment_id = payment.id

    await state.clear()
    await call.message.edit_text(
        f"💳 <b>Счёт создан</b>\n\n"
        f"Сумма: <b>{amount:.2f} ₽</b>\n"
        f"Способ: Platega (СБП / Карта / Крипта)\n\n"
        f"Нажми кнопку ниже для оплаты. После оплаты нажми «Проверить оплату».\n\n"
        f"⚠️ Не закрывай это сообщение до проверки!",
        reply_markup=check_payment_kb(invoice_url, payment_id),
    )
    await call.answer()


# ─── Проверка оплаты ───────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("check_pay_"))
async def cb_check_payment(call: CallbackQuery):
    payment_id = int(call.data.split("_")[-1])

    async with Database().session() as s:
        payment = (await s.execute(
            select(Payments).where(Payments.id == payment_id)
        )).scalars().first()

        if not payment:
            await call.answer("❌ Платёж не найден.", show_alert=True)
            return

        if payment.status == "paid":
            await call.answer("✅ Уже зачислено!", show_alert=True)
            return

        # Проверяем статус через Platega API
        status = await check_payment_status(payment.external_id)
        
        if status == "CONFIRMED":
            # Реально зачисляем баланс (а не просто говорим "будет")
            from bot.database.methods.transactions import process_payment_with_referral
            from bot.misc import EnvKeys
            
            success, msg = await process_payment_with_referral(
                user_id=payment.user_id,
                amount=float(payment.amount),
                provider="platega",
                external_id=payment.external_id,
                referral_percent=EnvKeys.REFERRAL_PERCENT
            )
            if success:
                # Обновляем статус платежа чтобы не зачислить дважды
                payment.status = "paid"
                await s.commit()
                await call.answer(f"✅ Зачислено {payment.amount:.2f} ₽!", show_alert=True)
            else:
                await call.answer(f"⚠️ Ошибка: {msg}", show_alert=True)
            return
        elif status == "CANCELED":
            payment.status = "failed"
            await s.commit()
            await call.answer("❌ Платёж отменён.", show_alert=True)
            return

    await call.answer(
        "⏳ Оплата ещё не подтверждена. Попробуй через несколько секунд.",
        show_alert=True,
    )
