"""FastAPI admin REST endpoints — /api/admin/*"""
import logging, httpx
from datetime import datetime, timezone, timedelta
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc, and_, or_, text

from bot.database.main import Database
from bot.database.models.main import (
    User, TipzyOrder, Payments, Categories, Goods, ItemValues, PromoCodes, Operations, AuditLog
)
from bot.misc.env import EnvKeys
from bot.misc.tipzy import tipzy_balance, tipzy_services
from bot.database.methods.audit import log_audit

router = APIRouter()
log = logging.getLogger(__name__)

ADMIN_KEY = EnvKeys.ADMIN_API_KEY


def auth(request: Request):
    key = request.headers.get("X-Admin-Key","")
    import hmac
    if not hmac.compare_digest(key.encode(), ADMIN_KEY.encode()):
        raise HTTPException(401, "Unauthorized")


async def db_session():
    async with Database().session() as s:
        yield s


def _ser_order(o: TipzyOrder) -> dict:
    return {
        "id": o.id,
        "user_id": o.user_id,
        "product_name": "TG Старт бота",
        "link": o.link,
        "quantity": o.quantity,
        "price_paid": float(o.price_paid or 0),
        "status": o.status,
        "refunded": bool(getattr(o, "refunded", False)),
        "tipzy_order_id": o.tipzy_order_id,
        "tipzy_status": o.tipzy_status,
        "tipzy_start_count": o.tipzy_start_count,
        "tipzy_remains": o.tipzy_remains,
        "tipzy_charge": float(o.tipzy_charge or 0) if o.tipzy_charge else None,
        "error_message": o.error_message,
        "created_at": o.created_at.isoformat() if o.created_at else None,
        "updated_at": o.updated_at.isoformat() if o.updated_at else None,
    }


def _ser_user(u: User) -> dict:
    return {
        "telegram_id": u.telegram_id,
        "balance": float(u.balance or 0),
        "is_blocked": u.is_blocked,
        "registration_date": u.registration_date.isoformat() if u.registration_date else None,
    }


# ─── Stats ────────────────────────────────────────────────────────────────────

@router.get("/stats", dependencies=[Depends(auth)])
async def stats(db: AsyncSession = Depends(db_session)):
    # Revenue counts ONLY orders that actually delivered (completed/partial).
    # Failed, refunded, pending and in-progress orders are excluded so the
    # number reflects real earned money, not gross order volume.
    REVENUE_STATUSES = ["completed", "partial"]
    total_users    = (await db.execute(select(func.count(User.telegram_id)))).scalar() or 0
    total_orders   = (await db.execute(select(func.count(TipzyOrder.id)))).scalar() or 0
    total_revenue  = (await db.execute(
        select(func.coalesce(func.sum(TipzyOrder.price_paid), 0))
        .where(TipzyOrder.status.in_(REVENUE_STATUSES))
    )).scalar() or 0
    pending_orders = (await db.execute(select(func.count(TipzyOrder.id)).where(TipzyOrder.status.in_(["pending","processing","in_progress"])))).scalar() or 0
    total_deposited= (await db.execute(select(func.coalesce(func.sum(Payments.amount), 0)).where(Payments.status=="paid"))).scalar() or 0
    today_start    = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    new_today      = (await db.execute(select(func.count(User.telegram_id)).where(User.registration_date >= today_start))).scalar() or 0
    return {
        "total_users": total_users, "total_orders": total_orders,
        "total_revenue": float(total_revenue), "pending_orders": pending_orders,
        "total_deposited": float(total_deposited), "new_today": new_today,
    }


# ─── Analytics ────────────────────────────────────────────────────────────────

@router.get("/analytics", dependencies=[Depends(auth)])
async def analytics(days: int = Query(30, ge=7, le=90), db: AsyncSession = Depends(db_session)):
    since = datetime.now(timezone.utc) - timedelta(days=days)

    orders_rows = (await db.execute(text(f"""
        SELECT DATE(created_at AT TIME ZONE 'UTC') AS day,
               COUNT(*) AS cnt,
               COALESCE(SUM(price_paid) FILTER (WHERE status IN ('completed','partial')),0) AS revenue
        FROM tipzy_orders WHERE created_at >= :since
        GROUP BY day ORDER BY day
    """), {"since": since})).fetchall()

    dep_rows = (await db.execute(text(f"""
        SELECT DATE(created_at AT TIME ZONE 'UTC') AS day,
               COALESCE(SUM(amount),0) AS amount
        FROM payments WHERE status='paid' AND created_at >= :since
        GROUP BY day ORDER BY day
    """), {"since": since})).fetchall()

    # Build unified chart from BOTH order days and deposit days
    order_map: dict[str, dict] = {}
    for r in orders_rows:
        d = str(r.day)
        order_map[d] = {"orders": r.cnt, "revenue": float(r.revenue)}
    dep_map = {str(r.day): float(r.amount) for r in dep_rows}
    all_days = sorted(set(order_map.keys()) | set(dep_map.keys()))
    chart = [{"date": d,
              "orders": order_map.get(d, {}).get("orders", 0),
              "revenue": order_map.get(d, {}).get("revenue", 0),
              "deposited": dep_map.get(d, 0)} for d in all_days]

    status_rows = (await db.execute(text(
        "SELECT status, COUNT(*) AS cnt FROM tipzy_orders GROUP BY status"
    ))).fetchall()
    statuses = [{"status": r.status, "count": r.cnt} for r in status_rows]

    # top products (only one for now, but ready for multi-product)
    products = [{"name": "TG Старт бота",
                 "orders": (await db.execute(select(func.count(TipzyOrder.id)))).scalar() or 0,
                 "revenue": float((await db.execute(
                     select(func.coalesce(func.sum(TipzyOrder.price_paid),0))
                     .where(TipzyOrder.status.in_(["completed","partial"]))
                 )).scalar() or 0)}]

    return {"chart": chart, "statuses": statuses, "products": products}


# ─── Orders ───────────────────────────────────────────────────────────────────

@router.get("/orders", dependencies=[Depends(auth)])
async def list_orders(
    page: int = Query(1, ge=1), per_page: int = Query(20, ge=1, le=100),
    search: str = Query(""), status: str = Query(""),
    db: AsyncSession = Depends(db_session)
):
    q = select(TipzyOrder)
    if search:
        q = q.where(or_(
            text("CAST(tipzy_orders.user_id AS TEXT) LIKE :search"),
            TipzyOrder.link.ilike(f"%{search}%"),
            text("CAST(tipzy_orders.id AS TEXT) LIKE :search"),
        )).params(search=f"%{search}%")
    if status:
        q = q.where(TipzyOrder.status == status)
    total = (await db.execute(select(func.count()).select_from(q.subquery()))).scalar() or 0
    rows  = (await db.execute(q.order_by(desc(TipzyOrder.created_at)).offset((page-1)*per_page).limit(per_page))).scalars().all()
    return {"total": total, "page": page, "per_page": per_page, "items": [_ser_order(o) for o in rows]}


@router.get("/orders/{oid}", dependencies=[Depends(auth)])
async def get_order(oid: int, db: AsyncSession = Depends(db_session)):
    o = (await db.execute(select(TipzyOrder).where(TipzyOrder.id == oid))).scalars().first()
    if not o: raise HTTPException(404)
    return _ser_order(o)


@router.post("/orders/{oid}/refund", dependencies=[Depends(auth)])
async def refund_order(oid: int, request: Request, db: AsyncSession = Depends(db_session)):
    o = (await db.execute(select(TipzyOrder).where(TipzyOrder.id == oid))).scalars().first()
    if not o: raise HTTPException(404)
    # Guard against double refund: a failed order auto-refunds and sets refunded=True,
    # while a manual refund sets status="refunded". Block both cases.
    if o.status == "refunded" or getattr(o, "refunded", False):
        raise HTTPException(400, "Already refunded")
    u = (await db.execute(select(User).where(User.telegram_id == o.user_id))).scalars().first()
    if u: u.balance = float(u.balance or 0) + float(o.price_paid or 0)
    o.status = "refunded"
    if hasattr(o, "refunded"):
        o.refunded = True
    await db.commit()
    await log_audit("admin.order.refund", level="INFO", user_id=o.user_id,
                    resource_type="TipzyOrder", resource_id=str(oid),
                    details=f"refund {o.price_paid}₽", ip_address=request.client.host if request.client else None)
    return {"ok": True}


@router.post("/orders/{oid}/refresh", dependencies=[Depends(auth)])
async def refresh_order(oid: int, db: AsyncSession = Depends(db_session)):
    """Pull latest tipzy status and update the order in DB."""
    o = (await db.execute(select(TipzyOrder).where(TipzyOrder.id == oid))).scalars().first()
    if not o:
        raise HTTPException(404)
    if not o.tipzy_order_id:
        raise HTTPException(400, "No tipzy order ID yet")
    try:
        from bot.misc.tipzy import tipzy_order_status
        data = await tipzy_order_status(int(o.tipzy_order_id))
        o.tipzy_status      = data.get("status")
        o.tipzy_start_count = int(data["start_count"]) if data.get("start_count") is not None else None
        o.tipzy_remains     = int(data["remains"])     if data.get("remains")     is not None else None
        charge = data.get("charge")
        if charge is not None:
            from decimal import Decimal
            o.tipzy_charge = Decimal(str(charge))
        status = (data.get("status") or "").lower()
        if status in ("completed", "partial"):
            o.status = "completed"
        elif status in ("canceled", "cancelled", "failed"):
            o.status = "failed"
            # Auto-refund on failure, exactly once
            if not getattr(o, "refunded", False):
                from bot.database.models.main import User as _User
                user = (await db.execute(select(_User).where(_User.telegram_id == o.user_id))).scalars().first()
                if user and o.price_paid:
                    user.balance = float(user.balance or 0) + float(o.price_paid)
                    if hasattr(o, "refunded"):
                        o.refunded = True
        await db.commit()
        return {
            "ok": True,
            "tipzy_status": o.tipzy_status,
            "tipzy_start_count": o.tipzy_start_count,
            "tipzy_remains": o.tipzy_remains,
            "tipzy_charge": float(o.tipzy_charge) if o.tipzy_charge else None,
            "status": o.status,
        }
    except Exception as e:
        raise HTTPException(502, str(e))


# ─── Users ────────────────────────────────────────────────────────────────────

@router.get("/users", dependencies=[Depends(auth)])
async def list_users(
    page: int = Query(1, ge=1), per_page: int = Query(20, ge=1, le=100),
    search: str = Query(""), db: AsyncSession = Depends(db_session)
):
    q = select(User)
    if search:
        q = q.where(text("CAST(users.telegram_id AS TEXT) LIKE :search")).params(search=f"%{search}%")
    total = (await db.execute(select(func.count()).select_from(q.subquery()))).scalar() or 0
    rows  = (await db.execute(q.order_by(desc(User.registration_date)).offset((page-1)*per_page).limit(per_page))).scalars().all()

    # Aggregate order counts and spend in ONE query (no N+1).
    # total_spent counts only delivered orders (completed/partial).
    user_ids = [u.telegram_id for u in rows]
    agg_map: dict = {}
    if user_ids:
        agg_rows = (await db.execute(
            select(
                TipzyOrder.user_id,
                func.count(TipzyOrder.id).label("cnt"),
                func.coalesce(
                    func.sum(TipzyOrder.price_paid).filter(TipzyOrder.status.in_(["completed", "partial"])),
                    0,
                ).label("spent"),
            )
            .where(TipzyOrder.user_id.in_(user_ids))
            .group_by(TipzyOrder.user_id)
        )).all()
        agg_map = {r.user_id: (r.cnt, float(r.spent)) for r in agg_rows}

    result = []
    for u in rows:
        cnt, spent = agg_map.get(u.telegram_id, (0, 0.0))
        result.append({**_ser_user(u), "orders_count": cnt, "total_spent": spent})
    return {"total": total, "page": page, "per_page": per_page, "items": result}


@router.get("/users/{tg_id}", dependencies=[Depends(auth)])
async def get_user(tg_id: int, db: AsyncSession = Depends(db_session)):
    u = (await db.execute(select(User).where(User.telegram_id == tg_id))).scalars().first()
    if not u: raise HTTPException(404)

    orders   = (await db.execute(select(TipzyOrder).where(TipzyOrder.user_id == tg_id).order_by(desc(TipzyOrder.created_at)).limit(50))).scalars().all()
    payments = (await db.execute(select(Payments).where(Payments.user_id == tg_id, Payments.status == "paid").order_by(desc(Payments.created_at)).limit(30))).scalars().all()

    by_status: dict = {}
    for o in orders:
        by_status[o.status] = by_status.get(o.status, 0) + 1

    return {
        **_ser_user(u),
        "stats": {
            "total_orders": len(orders),
            "total_spent": sum(float(o.price_paid or 0) for o in orders),
            "total_deposited": sum(float(p.amount or 0) for p in payments),
            "orders_by_status": by_status,
        },
        "orders": [_ser_order(o) for o in orders],
        "payments": [{"id": p.id, "provider": p.provider, "external_id": p.external_id,
                      "amount": float(p.amount or 0), "currency": p.currency,
                      "created_at": p.created_at.isoformat() if p.created_at else None} for p in payments],
    }


@router.post("/users/{tg_id}/block", dependencies=[Depends(auth)])
async def toggle_block(tg_id: int, request: Request, db: AsyncSession = Depends(db_session)):
    u = (await db.execute(select(User).where(User.telegram_id == tg_id))).scalars().first()
    if not u: raise HTTPException(404)
    u.is_blocked = not u.is_blocked
    await db.commit()
    action = "admin.user.block" if u.is_blocked else "admin.user.unblock"
    await log_audit(action, level="WARNING", user_id=tg_id,
                    resource_type="User", resource_id=str(tg_id),
                    ip_address=request.client.host if request.client else None)
    return {"ok": True, "is_blocked": u.is_blocked}


@router.post("/users/{tg_id}/balance", dependencies=[Depends(auth)])
async def adjust_balance(tg_id: int, request: Request, db: AsyncSession = Depends(db_session)):
    data = await request.json()
    # Validate amount: must be a finite number, non-zero, within sane bounds
    try:
        amount = float(data.get("amount", 0))
    except (TypeError, ValueError):
        raise HTTPException(400, "amount must be a number")
    import math
    if not math.isfinite(amount):
        raise HTTPException(400, "amount must be finite")
    if amount == 0:
        raise HTTPException(400, "amount must be non-zero")
    # Hard cap on a single manual adjustment to prevent fat-finger mistakes
    MAX_ADJUST = 1_000_000.0
    if abs(amount) > MAX_ADJUST:
        raise HTTPException(400, f"amount exceeds limit of {MAX_ADJUST:.0f}₽")
    amount = round(amount, 2)

    u = (await db.execute(select(User).where(User.telegram_id == tg_id))).scalars().first()
    if not u: raise HTTPException(404)
    old_bal = float(u.balance or 0)
    new_bal = round(old_bal + amount, 2)
    # Never allow balance to go negative via manual adjustment
    if new_bal < 0:
        raise HTTPException(400, f"resulting balance would be negative ({new_bal:.2f}₽); current is {old_bal:.2f}₽")
    u.balance = new_bal
    await db.commit()
    await log_audit("admin.balance.adjust", level="INFO", user_id=tg_id,
                    resource_type="User", resource_id=str(tg_id),
                    details=f"{'+' if amount >= 0 else ''}{amount:.2f}₽: {old_bal:.2f}₽ → {new_bal:.2f}₽",
                    ip_address=request.client.host if request.client else None)
    return {"ok": True, "balance": new_bal, "old_balance": old_bal}


# ─── Catalog ──────────────────────────────────────────────────────────────────

@router.get("/catalog/categories", dependencies=[Depends(auth)])
async def get_categories(db: AsyncSession = Depends(db_session)):
    cats  = (await db.execute(select(Categories))).scalars().all()
    goods = (await db.execute(select(Goods))).scalars().all()
    cnt   = {}
    for g in goods: cnt[g.category_id] = cnt.get(g.category_id, 0) + 1
    return [{"id": c.id, "name": c.name, "goods_count": cnt.get(c.id, 0)} for c in cats]


@router.post("/catalog/categories", dependencies=[Depends(auth)])
async def create_category(request: Request, db: AsyncSession = Depends(db_session)):
    data = await request.json()
    name = (data.get("name") or "").strip()
    if not name: raise HTTPException(400, "name required")
    c = Categories(name=name)
    db.add(c); await db.commit(); await db.refresh(c)
    await log_audit("admin.catalog.category.create", resource_type="Category", resource_id=str(c.id),
                    details=name, ip_address=request.client.host if request.client else None)
    return {"ok": True, "id": c.id, "name": c.name, "goods_count": 0}


@router.patch("/catalog/categories/{cid}", dependencies=[Depends(auth)])
async def update_category(cid: int, request: Request, db: AsyncSession = Depends(db_session)):
    data = await request.json()
    c = (await db.execute(select(Categories).where(Categories.id == cid))).scalars().first()
    if not c: raise HTTPException(404)
    if data.get("name"): c.name = data["name"].strip()
    await db.commit()
    await log_audit("admin.catalog.category.update", resource_type="Category", resource_id=str(cid),
                    details=c.name, ip_address=request.client.host if request.client else None)
    return {"ok": True}


@router.delete("/catalog/categories/{cid}", dependencies=[Depends(auth)])
async def delete_category(cid: int, request: Request, db: AsyncSession = Depends(db_session)):
    c = (await db.execute(select(Categories).where(Categories.id == cid))).scalars().first()
    if not c: raise HTTPException(404)
    await db.delete(c); await db.commit()
    await log_audit("admin.catalog.category.delete", level="WARNING", resource_type="Category",
                    resource_id=str(cid), ip_address=request.client.host if request.client else None)
    return {"ok": True}


@router.get("/catalog/goods", dependencies=[Depends(auth)])
async def get_goods(db: AsyncSession = Depends(db_session)):
    goods = (await db.execute(select(Goods))).scalars().all()
    cats  = {c.id: c.name for c in (await db.execute(select(Categories))).scalars().all()}
    return [{
        "id": g.id, "name": g.name, "price": float(g.price),
        "description": g.description or "",
        "category_id": g.category_id,
        "category_name": cats.get(g.category_id, "—"),
        "is_infinity": getattr(g, "is_infinity", False),
        "is_active": not getattr(g, "hidden", False),
    } for g in goods]


@router.post("/catalog/goods", dependencies=[Depends(auth)])
async def create_good(request: Request, db: AsyncSession = Depends(db_session)):
    data = await request.json()
    g = Goods(
        name=data["name"],
        price=float(data.get("price", 0)),
        description=data.get("description", ""),
        category_id=int(data["category_id"]),
        is_infinity=bool(data.get("is_infinity", True)),
    )
    db.add(g); await db.commit(); await db.refresh(g)
    iv = ItemValues(item_id=g.id, value="__tipzy__", is_infinity=True)
    db.add(iv); await db.commit()
    await log_audit("admin.catalog.good.create", resource_type="Good", resource_id=str(g.id),
                    details=g.name, ip_address=request.client.host if request.client else None)
    return {"ok": True, "id": g.id}


@router.patch("/catalog/goods/{gid}", dependencies=[Depends(auth)])
async def update_good(gid: int, request: Request, db: AsyncSession = Depends(db_session)):
    data = await request.json()
    g = (await db.execute(select(Goods).where(Goods.id == gid))).scalars().first()
    if not g: raise HTTPException(404)
    if data.get("name"):        g.name        = data["name"]
    if data.get("price") is not None: g.price = float(data["price"])
    if data.get("description") is not None: g.description = data["description"]
    if data.get("category_id"): g.category_id = int(data["category_id"])
    await db.commit()
    await log_audit("admin.catalog.good.update", resource_type="Good", resource_id=str(gid),
                    details=g.name, ip_address=request.client.host if request.client else None)
    return {"ok": True}


@router.delete("/catalog/goods/{gid}", dependencies=[Depends(auth)])
async def delete_good(gid: int, request: Request, db: AsyncSession = Depends(db_session)):
    g = (await db.execute(select(Goods).where(Goods.id == gid))).scalars().first()
    if not g: raise HTTPException(404)
    await db.delete(g); await db.commit()
    await log_audit("admin.catalog.good.delete", level="WARNING", resource_type="Good",
                    resource_id=str(gid), ip_address=request.client.host if request.client else None)
    return {"ok": True}


# ─── Promo Codes ──────────────────────────────────────────────────────────────

@router.get("/promos", dependencies=[Depends(auth)])
async def list_promos(db: AsyncSession = Depends(db_session)):
    promos = (await db.execute(select(PromoCodes).order_by(desc(PromoCodes.created_at)))).scalars().all()
    cats   = {c.id: c.name for c in (await db.execute(select(Categories))).scalars().all()}
    goods  = {g.id: g.name for g in (await db.execute(select(Goods))).scalars().all()}
    return [{
        "id": p.id, "code": p.code,
        "discount_type":  p.discount_type,
        "discount_value": float(p.discount_value),
        "max_uses":       p.max_uses or 0,
        "current_uses":   p.current_uses or 0,
        "expires_at":     p.expires_at.isoformat() if p.expires_at else None,
        "is_active":      p.is_active,
        "category_name":  cats.get(p.category_id),
        "item_name":      goods.get(p.item_id),
        "created_at":     p.created_at.isoformat() if p.created_at else None,
    } for p in promos]


@router.post("/promos", dependencies=[Depends(auth)])
async def create_promo(request: Request, db: AsyncSession = Depends(db_session)):
    data = await request.json()
    from datetime import datetime
    expires = None
    if data.get("expires_at"):
        try: expires = datetime.fromisoformat(data["expires_at"])
        except: pass
    p = PromoCodes(code=data["code"].strip().upper(), discount_type=data.get("discount_type","percent"),
                   discount_value=float(data.get("discount_value",0)),
                   max_uses=int(data.get("max_uses",0)), is_active=True, expires_at=expires)
    db.add(p); await db.commit(); await db.refresh(p)
    await log_audit("admin.promo.create", resource_type="Promo", resource_id=str(p.id),
                    details=f"{p.code} {p.discount_type}={p.discount_value}",
                    ip_address=request.client.host if request.client else None)
    return {"ok": True, "id": p.id, "code": p.code}


@router.patch("/promos/{pid}", dependencies=[Depends(auth)])
async def update_promo(pid: int, request: Request, db: AsyncSession = Depends(db_session)):
    from datetime import datetime
    p = (await db.execute(select(PromoCodes).where(PromoCodes.id == pid))).scalars().first()
    if not p: raise HTTPException(404)
    data = await request.json()
    changes = []
    if "code" in data:
        p.code = data["code"].strip().upper(); changes.append(f"code={p.code}")
    if "discount_type" in data:
        p.discount_type = data["discount_type"]; changes.append(f"type={p.discount_type}")
    if "discount_value" in data:
        p.discount_value = float(data["discount_value"]); changes.append(f"value={p.discount_value}")
    if "max_uses" in data:
        p.max_uses = int(data["max_uses"]); changes.append(f"max_uses={p.max_uses}")
    if "is_active" in data:
        p.is_active = bool(data["is_active"]); changes.append(f"active={p.is_active}")
    if "category_id" in data:
        p.category_id = int(data["category_id"]) if data["category_id"] else None; changes.append(f"cat={p.category_id}")
    if "item_id" in data:
        p.item_id = int(data["item_id"]) if data["item_id"] else None; changes.append(f"item={p.item_id}")
    if "expires_at" in data:
        try: p.expires_at = datetime.fromisoformat(data["expires_at"]) if data["expires_at"] else None
        except: pass
        changes.append(f"expires={p.expires_at}")
    await db.commit()
    await db.refresh(p)
    await log_audit("admin.promo.update", resource_type="Promo", resource_id=str(p.id),
                    details=", ".join(changes) or "no changes",
                    ip_address=request.client.host if request.client else None)
    return {"ok": True, "id": p.id, "code": p.code}


@router.delete("/promos/{pid}", dependencies=[Depends(auth)])
async def delete_promo(pid: int, request: Request, db: AsyncSession = Depends(db_session)):
    p = (await db.execute(select(PromoCodes).where(PromoCodes.id == pid))).scalars().first()
    if not p: raise HTTPException(404)
    code = p.code
    await db.delete(p); await db.commit()
    await log_audit("admin.promo.delete", level="WARNING", resource_type="Promo",
                    resource_id=str(pid), details=code,
                    ip_address=request.client.host if request.client else None)
    return {"ok": True}



# ─── Referral Invites ─────────────────────────────────────────────────────

@router.get("/referrals/overview", dependencies=[Depends(auth)])
async def referrals_overview(db: AsyncSession = Depends(db_session)):
    """Aggregated referral invite stats."""
    from bot.misc.invite_rewards import ReferralInvite, ReferralReward, INVITES_PER_REWARD

    total_invites = (await db.execute(
        select(func.count(ReferralInvite.id))
    )).scalar() or 0

    verified = (await db.execute(
        select(func.count(ReferralInvite.id)).where(ReferralInvite.status == "verified")
    )).scalar() or 0

    pending = (await db.execute(
        select(func.count(ReferralInvite.id)).where(ReferralInvite.status == "pending")
    )).scalar() or 0

    rejected = (await db.execute(
        select(func.count(ReferralInvite.id)).where(ReferralInvite.status == "rejected")
    )).scalar() or 0

    rewards_total = (await db.execute(
        select(func.count(ReferralReward.id))
    )).scalar() or 0

    rewards_fulfilled = (await db.execute(
        select(func.count(ReferralReward.id)).where(ReferralReward.fulfilled == True)
    )).scalar() or 0

    # Top referrers
    top = (await db.execute(
        select(
            ReferralInvite.referrer_id,
            func.count(ReferralInvite.id).filter(ReferralInvite.status == "verified").label("verified"),
            func.count(ReferralInvite.id).label("total"),
        )
        .group_by(ReferralInvite.referrer_id)
        .order_by(desc("verified"))
        .limit(20)
    )).fetchall()

    return {
        "invites_per_reward": INVITES_PER_REWARD,
        "total_invites": int(total_invites),
        "verified": int(verified),
        "pending": int(pending),
        "rejected": int(rejected),
        "rewards_total": int(rewards_total),
        "rewards_fulfilled": int(rewards_fulfilled),
        "rewards_pending": int(rewards_total - rewards_fulfilled),
        "top_referrers": [
            {"referrer_id": r.referrer_id, "verified": r.verified, "total": r.total}
            for r in top
        ],
    }


@router.get("/referrals/invites", dependencies=[Depends(auth)])
async def referrals_invites_list(
    status: str = Query("", pattern="^(|pending|verified|rejected)$"),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(db_session),
):
    """Paginated list of referral invites."""
    from bot.misc.invite_rewards import ReferralInvite

    q = select(ReferralInvite)
    if status:
        q = q.where(ReferralInvite.status == status)

    total = (await db.execute(
        select(func.count()).select_from(q.subquery())
    )).scalar() or 0

    rows = (await db.execute(
        q.order_by(desc(ReferralInvite.created_at))
        .offset((page - 1) * per_page).limit(per_page)
    )).scalars().all()

    return {
        "total": int(total), "page": page, "per_page": per_page,
        "items": [
            {
                "id": r.id,
                "referrer_id": r.referrer_id,
                "invited_user_id": r.invited_user_id,
                "status": r.status,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "verified_at": r.verified_at.isoformat() if r.verified_at else None,
            }
            for r in rows
        ],
    }


@router.get("/referrals/rewards", dependencies=[Depends(auth)])
async def referrals_rewards_list(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(db_session),
):
    """Paginated list of referral rewards."""
    from bot.misc.invite_rewards import ReferralReward

    total = (await db.execute(
        select(func.count(ReferralReward.id))
    )).scalar() or 0

    rows = (await db.execute(
        select(ReferralReward)
        .order_by(desc(ReferralReward.created_at))
        .offset((page - 1) * per_page).limit(per_page)
    )).scalars().all()

    return {
        "total": int(total), "page": page, "per_page": per_page,
        "items": [
            {
                "id": r.id,
                "referrer_id": r.referrer_id,
                "reward_type": r.reward_type,
                "invites_at_reward": r.invites_at_reward,
                "fulfilled": r.fulfilled,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ],
    }



@router.post("/referrals/invites/{invite_id}/approve", dependencies=[Depends(auth)])
async def approve_invite(invite_id: int, request: Request, db: AsyncSession = Depends(db_session)):
    """Manually approve a needs_review invite."""
    from bot.misc.invite_rewards import ReferralInvite, _check_and_grant_reward
    inv = (await db.execute(
        select(ReferralInvite).where(ReferralInvite.id == invite_id)
    )).scalars().first()
    if not inv:
        raise HTTPException(404, "invite not found")
    if inv.status not in ("needs_review", "pending"):
        raise HTTPException(400, f"cannot approve invite in status '{inv.status}'")

    inv.status = "verified"
    inv.verified_at = func.now()
    await db.commit()

    await log_audit("admin.invite.approve", user_id=inv.referrer_id,
                    resource_type="ReferralInvite", resource_id=str(invite_id),
                    ip_address=request.client.host if request.client else None)

    # Check if reward should be granted
    reward_id = await _check_and_grant_reward(inv.referrer_id)

    # Notify referrer
    try:
        from bot.handlers.user.invite_rewards import _notify_referrer
        from aiogram import Bot
        from bot.misc.env import EnvKeys
        tg_bot = Bot(token=EnvKeys.TOKEN)
        await _notify_referrer(tg_bot, inv.invited_user_id, "admin_approved")
        await tg_bot.session.close()
    except Exception as e:
        log.warning("Failed to notify referrer after approve: %s", e)

    return {"ok": True, "status": "verified", "reward_granted": reward_id is not None}


@router.post("/referrals/invites/{invite_id}/reject", dependencies=[Depends(auth)])
async def reject_invite(invite_id: int, request: Request, db: AsyncSession = Depends(db_session)):
    """Reject a needs_review or pending invite."""
    from bot.misc.invite_rewards import ReferralInvite
    inv = (await db.execute(
        select(ReferralInvite).where(ReferralInvite.id == invite_id)
    )).scalars().first()
    if not inv:
        raise HTTPException(404, "invite not found")
    if inv.status in ("verified", "rejected"):
        raise HTTPException(400, f"cannot reject invite in status '{inv.status}'")

    inv.status = "rejected"
    await db.commit()

    await log_audit("admin.invite.reject", user_id=inv.referrer_id,
                    resource_type="ReferralInvite", resource_id=str(invite_id),
                    ip_address=request.client.host if request.client else None)

    return {"ok": True, "status": "rejected"}

@router.get("/referrals/user/{tg_id}", dependencies=[Depends(auth)])
async def referrals_user_detail(tg_id: int, db: AsyncSession = Depends(db_session)):
    """Referral invite details for a specific user."""
    from bot.misc.invite_rewards import ReferralInvite, ReferralReward, get_referrer_stats

    invites = (await db.execute(
        select(ReferralInvite)
        .where(ReferralInvite.referrer_id == tg_id)
        .order_by(desc(ReferralInvite.created_at))
        .limit(50)
    )).scalars().all()

    rewards = (await db.execute(
        select(ReferralReward)
        .where(ReferralReward.referrer_id == tg_id)
        .order_by(desc(ReferralReward.created_at))
    )).scalars().all()

    stats = await get_referrer_stats(tg_id)

    return {
        "referrer_id": tg_id,
        "stats": stats,
        "invites": [
            {
                "id": r.id,
                "invited_user_id": r.invited_user_id,
                "status": r.status,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "verified_at": r.verified_at.isoformat() if r.verified_at else None,
            }
            for r in invites
        ],
        "rewards": [
            {
                "id": r.id,
                "reward_type": r.reward_type,
                "invites_at_reward": r.invites_at_reward,
                "fulfilled": r.fulfilled,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rewards
        ],
    }

# ─── Broadcast ────────────────────────────────────────────────────────────────
import uuid, asyncio as _asyncio
from typing import Optional
from dataclasses import dataclass, field as dc_field

@dataclass
class BroadcastState:
    id: str
    text: str
    total: int = 0
    sent: int = 0
    failed: int = 0
    status: str = "pending"  # pending | running | completed | cancelled
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    task: Optional[any] = dc_field(default=None, repr=False)

_active_broadcasts: dict[str, BroadcastState] = {}

@router.post("/broadcast/start", dependencies=[Depends(auth)])
async def broadcast_start(request: Request, db: AsyncSession = Depends(db_session)):
    data = await request.json()
    text_msg = data.get("text", "").strip()
    if not text_msg:
        raise HTTPException(400, "text required")

    users = (await db.execute(select(User.telegram_id).where(User.is_blocked == False))).scalars().all()
    user_ids = [u for u in users]

    bc_id = str(uuid.uuid4())[:8]
    bc = BroadcastState(id=bc_id, text=text_msg, total=len(user_ids))
    _active_broadcasts[bc_id] = bc

    # Start broadcast as a background task
    bc.task = _asyncio.create_task(_run_broadcast(bc_id, user_ids, text_msg))

    await log_audit("admin.broadcast.start", level="INFO",
                    details=f"id={bc_id} total={len(user_ids)} len={len(text_msg)}",
                    ip_address=request.client.host if request.client else None)
    return {"ok": True, "broadcast_id": bc_id, "total": len(user_ids)}


async def _run_broadcast(bc_id: str, user_ids: list[int], text: str):
    from aiogram import Bot
    from aiogram.client.default import DefaultBotProperties
    from aiogram.exceptions import TelegramRetryAfter, TelegramForbiddenError

    bc = _active_broadcasts[bc_id]
    bc.status = "running"
    bc.started_at = datetime.now(timezone.utc).isoformat()

    tg = Bot(token=EnvKeys.TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
    try:
        for uid in user_ids:
            if bc.status == "cancelled":
                break
            try:
                await tg.send_message(uid, text, disable_notification=True)
                bc.sent += 1
            except TelegramForbiddenError:
                bc.failed += 1
            except TelegramRetryAfter as e:
                await _asyncio.sleep(e.retry_after)
                try:
                    await tg.send_message(uid, text, disable_notification=True)
                    bc.sent += 1
                except Exception:
                    bc.failed += 1
            except Exception:
                bc.failed += 1
            await _asyncio.sleep(0.04)
    finally:
        try:
            await tg.session.close()
        except Exception:
            pass

    if bc.status == "cancelled":
        bc.finished_at = datetime.now(timezone.utc).isoformat()
    else:
        bc.status = "completed"
        bc.finished_at = datetime.now(timezone.utc).isoformat()
        await log_audit("admin.broadcast.complete", level="INFO",
                        details=f"id={bc_id} sent={bc.sent} failed={bc.failed}")


@router.get("/broadcast/{bc_id}", dependencies=[Depends(auth)])
async def broadcast_status(bc_id: str):
    bc = _active_broadcasts.get(bc_id)
    if not bc:
        raise HTTPException(404, "broadcast not found")
    progress = round((bc.sent + bc.failed) / bc.total * 100, 1) if bc.total else 0
    return {
        "id": bc.id, "status": bc.status, "total": bc.total,
        "sent": bc.sent, "failed": bc.failed,
        "progress": progress,
        "started_at": bc.started_at, "finished_at": bc.finished_at,
    }


@router.post("/broadcast/{bc_id}/cancel", dependencies=[Depends(auth)])
async def broadcast_cancel(bc_id: str, request: Request):
    bc = _active_broadcasts.get(bc_id)
    if not bc:
        raise HTTPException(404, "broadcast not found")
    if bc.status not in ("pending", "running"):
        raise HTTPException(400, f"cannot cancel broadcast in status '{bc.status}'")
    bc.status = "cancelled"
    await log_audit("admin.broadcast.cancel", level="INFO",
                    details=f"id={bc_id}",
                    ip_address=request.client.host if request.client else None)
    return {"ok": True, "id": bc_id, "status": "cancelled"}


@router.get("/broadcast", dependencies=[Depends(auth)])
async def broadcast_list():
    return {
        "items": [
            {"id": b.id, "status": b.status, "total": b.total,
             "sent": b.sent, "failed": b.failed,
             "started_at": b.started_at, "finished_at": b.finished_at}
            for b in sorted(_active_broadcasts.values(), key=lambda x: x.started_at or "", reverse=True)
        ]
    }


# ─── Integrations ─────────────────────────────────────────────────────────────

@router.get("/integrations/tipzy", dependencies=[Depends(auth)])
async def tipzy_info():
    try:
        bal  = await tipzy_balance()
        svcs = await tipzy_services()
    except Exception as e:
        raise HTTPException(502, str(e))
    return {"ok": True, **bal, "services_count": len(svcs)}


@router.get("/integrations/tipzy/services", dependencies=[Depends(auth)])
async def tipzy_svcs():
    try:
        return await tipzy_services()
    except Exception as e:
        raise HTTPException(502, str(e))


@router.get("/integrations/settings", dependencies=[Depends(auth)])
async def get_settings():
    return {
        "tipzy_service_id":   EnvKeys.TIPZY_SERVICE_ID,
        "cost_per_unit":      EnvKeys.TIPZY_COST_PER_UNIT_RUB,
        "sell_per_unit":      EnvKeys.TIPZY_SELL_PER_UNIT_RUB,
        "min_deposit":        EnvKeys.MIN_AMOUNT,
        "max_deposit":        EnvKeys.MAX_AMOUNT,
        "pay_currency":       EnvKeys.PAY_CURRENCY,
        "bot_username":       "@clerkstore_bot",
        "platega_configured": bool(EnvKeys.PLATEGA_SECRET_KEY),
        "webhook_url":        f"{EnvKeys.WEBHOOK_URL.rstrip('/') or 'https://example.com'}/platega/webhook",
    }


# ─── Audit Logs ───────────────────────────────────────────────────────────────

@router.get("/logs", dependencies=[Depends(auth)])
async def get_logs(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    level: str = Query(""),
    action: str = Query(""),
    user_id: Optional[int] = Query(None),
    days: int = Query(7, ge=1, le=90),
    db: AsyncSession = Depends(db_session),
):
    since = datetime.now(timezone.utc) - timedelta(days=days)
    q = select(AuditLog).where(AuditLog.timestamp >= since)
    if level:   q = q.where(AuditLog.level   == level.upper())
    if action:  q = q.where(AuditLog.action.ilike(f"%{action}%"))
    if user_id: q = q.where(AuditLog.user_id == user_id)

    total = (await db.execute(select(func.count()).select_from(q.subquery()))).scalar() or 0
    rows  = (await db.execute(
        q.order_by(desc(AuditLog.timestamp)).offset((page-1)*per_page).limit(per_page)
    )).scalars().all()

    return {
        "total": total, "page": page, "per_page": per_page,
        "items": [{
            "id":            r.id,
            "timestamp":     r.timestamp.isoformat() if r.timestamp else None,
            "level":         r.level,
            "action":        r.action,
            "user_id":       r.user_id,
            "resource_type": r.resource_type,
            "resource_id":   r.resource_id,
            "details":       r.details,
            "ip_address":    r.ip_address,
        } for r in rows],
    }


@router.get("/logs/actions", dependencies=[Depends(auth)])
async def get_log_actions(db: AsyncSession = Depends(db_session)):
    rows = (await db.execute(
        select(AuditLog.action, func.count().label("cnt"))
        .group_by(AuditLog.action).order_by(desc(func.count()))
    )).all()
    return [{"action": r.action, "count": r.cnt} for r in rows]


# ─── CSV Exports ────────────────────────────────────────────────────────────
import csv, io
from starlette.responses import StreamingResponse

async def _stream_csv(query, columns, session_maker, filename: str):
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(columns)
    yield output.getvalue()
    output.seek(0); output.truncate(0)

    offset = 0
    BATCH = 1000
    while True:
        async with session_maker() as s:
            rows = (await s.execute(query.offset(offset).limit(BATCH))).all()
        if not rows:
            break
        for row in rows:
            writer.writerow([getattr(row, c, row[i]) if hasattr(row, c) else row[i] for i, c in enumerate(columns)])
        yield output.getvalue()
        output.seek(0); output.truncate(0)
        offset += BATCH


@router.get("/export/orders", dependencies=[Depends(auth)])
async def export_orders_csv(db: AsyncSession = Depends(db_session)):
    from bot.database.models.main import TipzyOrder
    query = select(
        TipzyOrder.id, TipzyOrder.user_id, TipzyOrder.link,
        TipzyOrder.status, TipzyOrder.tipzy_order_id,
        TipzyOrder.price_paid, TipzyOrder.quantity,
        TipzyOrder.created_at, TipzyOrder.updated_at,
        TipzyOrder.tipzy_charge, TipzyOrder.error_message,
    ).order_by(TipzyOrder.created_at.desc())
    cols = ["id","user_id","link","status","tipzy_order_id","price_paid",
            "quantity","created_at","updated_at","tipzy_charge","error_message"]
    return StreamingResponse(
        _stream_csv(query, cols, Database().session, "orders.csv"),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=orders.csv"},
    )


@router.get("/export/users", dependencies=[Depends(auth)])
async def export_users_csv(db: AsyncSession = Depends(db_session)):
    from bot.database.models.main import User
    query = select(
        User.telegram_id, User.balance, User.role_id,
        User.referral_id, User.registration_date, User.is_blocked,
        User.language,
    ).order_by(User.telegram_id)
    cols = ["telegram_id","balance","role_id","referral_id",
            "registration_date","is_blocked","language"]
    return StreamingResponse(
        _stream_csv(query, cols, Database().session, "users.csv"),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=users.csv"},
    )


@router.get("/export/logs", dependencies=[Depends(auth)])
async def export_logs_csv(db: AsyncSession = Depends(db_session)):
    from bot.database.models.main import AuditLog
    query = select(
        AuditLog.id, AuditLog.timestamp, AuditLog.level,
        AuditLog.action, AuditLog.user_id, AuditLog.resource_type,
        AuditLog.resource_id, AuditLog.details, AuditLog.ip_address,
    ).order_by(AuditLog.timestamp.desc()).limit(10000)
    cols = ["id","timestamp","level","action","user_id",
            "resource_type","resource_id","details","ip_address"]
    return StreamingResponse(
        _stream_csv(query, cols, Database().session, "logs.csv"),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=logs.csv"},
    )
