from __future__ import annotations
import enum
import secrets
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import (
    BigInteger, Integer, String, Text, Boolean, ForeignKey,
    DateTime, JSON, Index, UniqueConstraint, select
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from config import settings

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    pool_pre_ping=True,
    connect_args={
        "server_settings": {},
        "statement_cache_size": 0,
    },
)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

def utcnow() -> datetime:
    return datetime.now(timezone.utc)

def gen_uid(prefix: str = "", n: int = 8) -> str:
    return prefix + secrets.token_hex(n // 2).upper()

class Base(DeclarativeBase):
    pass

# ─── enums ────────────────────────────────────────────────────────────────

class OrderStatus(str, enum.Enum):
    PENDING = "pending"        # создан, не отправлен
    SENT = "sent"              # отправлен в tipzy
    PROCESSING = "processing"  # tipzy обрабатывает
    PARTIAL = "partial"        # частично выполнен
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELED = "canceled"
    REFUNDED = "refunded"

class PaymentStatus(str, enum.Enum):
    PENDING = "pending"
    PAID = "paid"
    FAILED = "failed"
    EXPIRED = "expired"

class ProviderKind(str, enum.Enum):
    TIPZY = "tipzy"
    MANUAL = "manual"

# ─── tables ───────────────────────────────────────────────────────────────

class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    tg_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    username: Mapped[Optional[str]] = mapped_column(String(64))
    first_name: Mapped[Optional[str]] = mapped_column(String(128))
    language: Mapped[str] = mapped_column(String(8), default="ru")
    balance_kop: Mapped[int] = mapped_column(BigInteger, default=0)
    total_deposited_kop: Mapped[int] = mapped_column(BigInteger, default=0)
    total_spent_kop: Mapped[int] = mapped_column(BigInteger, default=0)
    is_banned: Mapped[bool] = mapped_column(Boolean, default=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

class Category(Base):
    __tablename__ = "categories"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    emoji: Mapped[Optional[str]] = mapped_column(String(8), default="📦")
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

class Product(Base):
    __tablename__ = "products"
    id: Mapped[int] = mapped_column(primary_key=True)
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id"))
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[Optional[str]] = mapped_column(Text)
    emoji: Mapped[str] = mapped_column(String(8), default="🤖")
    provider_kind: Mapped[ProviderKind] = mapped_column(String(16), default=ProviderKind.TIPZY)
    provider_service_id: Mapped[Optional[int]] = mapped_column(Integer)  # tipzy id
    cost_per_unit_kop: Mapped[int] = mapped_column(Integer, default=2)   # себестоимость
    price_per_unit_kop: Mapped[int] = mapped_column(Integer, default=4)  # цена для юзера
    min_quantity: Mapped[int] = mapped_column(Integer, default=1)
    max_quantity: Mapped[int] = mapped_column(Integer, default=56000)
    requires_link: Mapped[bool] = mapped_column(Boolean, default=True)
    link_hint: Mapped[Optional[str]] = mapped_column(String(300), default="https://t.me/Bot?start=...")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

class VolumeDiscount(Base):
    __tablename__ = "volume_discounts"
    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    from_quantity: Mapped[int] = mapped_column(Integer)
    discount_pct: Mapped[int] = mapped_column(Integer)  # 0..100

class Order(Base):
    __tablename__ = "orders"
    id: Mapped[int] = mapped_column(primary_key=True)
    uid: Mapped[str] = mapped_column(String(20), unique=True, index=True, default=lambda: gen_uid("O", 8))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    batch_id: Mapped[Optional[str]] = mapped_column(String(20), index=True)  # для массовых
    link: Mapped[Optional[str]] = mapped_column(String(500))
    quantity: Mapped[int] = mapped_column(Integer)
    unit_price_kop: Mapped[int] = mapped_column(Integer)
    discount_pct: Mapped[int] = mapped_column(Integer, default=0)
    total_price_kop: Mapped[int] = mapped_column(Integer)
    status: Mapped[OrderStatus] = mapped_column(String(20), default=OrderStatus.PENDING, index=True)
    tipzy_order_id: Mapped[Optional[int]] = mapped_column(Integer)
    tipzy_status: Mapped[Optional[str]] = mapped_column(String(40))
    tipzy_charge: Mapped[Optional[float]] = mapped_column()
    tipzy_remains: Mapped[Optional[int]] = mapped_column(Integer)
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    refunded_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

class Payment(Base):
    __tablename__ = "payments"
    id: Mapped[int] = mapped_column(primary_key=True)
    uid: Mapped[str] = mapped_column(String(20), unique=True, index=True, default=lambda: gen_uid("P", 8))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    amount_kop: Mapped[int] = mapped_column(BigInteger)
    method: Mapped[str] = mapped_column(String(40), default="platega")
    status: Mapped[PaymentStatus] = mapped_column(String(20), default=PaymentStatus.PENDING, index=True)
    external_id: Mapped[Optional[str]] = mapped_column(String(120), index=True)
    payment_url: Mapped[Optional[str]] = mapped_column(Text)
    raw_payload: Mapped[Optional[dict]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    paid_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

class WorkerLog(Base):
    __tablename__ = "worker_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[Optional[int]] = mapped_column(ForeignKey("orders.id"), index=True)
    level: Mapped[str] = mapped_column(String(16), default="INFO")
    message: Mapped[str] = mapped_column(Text)
    data: Mapped[Optional[dict]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)

class Setting(Base):
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[Optional[str]] = mapped_column(Text)

# ─── init ─────────────────────────────────────────────────────────────────

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with async_session() as db:
        cat = (await db.execute(select(Category).where(Category.name == "Telegram"))).scalar_one_or_none()
        if not cat:
            cat = Category(name="Telegram", emoji="✈️", sort_order=0)
            db.add(cat); await db.flush()
            db.add(Product(
                category_id=cat.id,
                name="Старт бота",
                description=(
                    "Накрутка переходов по реферальной ссылке Telegram-бота.\n"
                    "Моментальный старт. Просто пришли ссылку формата "
                    "https://t.me/BotName?start=код"
                ),
                emoji="🤖",
                provider_service_id=513,
                cost_per_unit_kop=2,
                price_per_unit_kop=4,
                min_quantity=1,
                max_quantity=56000,
                requires_link=True,
                link_hint="https://t.me/BotName?start=code",
            ))
            db.add_all([
                # сидим дефолтные пороги скидок (применяется к product_id=1 после flush)
            ])
            await db.commit()
