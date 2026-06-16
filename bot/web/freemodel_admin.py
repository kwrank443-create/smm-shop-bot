"""Freemodel proxy admin API - key management and stats."""
from __future__ import annotations
import asyncio
import json
import secrets
import httpx
from datetime import datetime, timezone, timedelta
from typing import Optional
import logging
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import select, func, and_, Column, Integer, String, Float, DateTime, Boolean, Text, desc
from sqlalchemy.ext.asyncio import AsyncSession

# Import database
from bot.database.main import Database

logger = logging.getLogger(__name__)

router = APIRouter(tags=["freemodel"])

# Database session dependency
async def db_session():
    """Get database session."""
    db = Database()
    try:
        yield db.session()
    finally:
        pass  # Session cleanup handled by Database singleton

# Get Base from Database
Base = Database.BASE

# ─── Models ──────────────────────────────────────────────────────────────

class FMApiKey(Base):
    __tablename__ = "fm_api_keys"
    __table_args__ = {"extend_existing": True}
    id = Column(Integer, primary_key=True)
    key = Column(String(64), unique=True, nullable=False, index=True)
    name = Column(String(100), nullable=False)
    user_id = Column(Integer, nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    last_used_at = Column(DateTime(timezone=True), nullable=True)
    requests_count = Column(Integer, default=0)
    tokens_in = Column(Integer, default=0)
    tokens_out = Column(Integer, default=0)
    cost_actual = Column(Float, default=0.0)
    cost_standard = Column(Float, default=0.0)
    metadata_json = Column(Text, nullable=True)

class FMRequestLog(Base):
    __tablename__ = "fm_request_logs"
    __table_args__ = {"extend_existing": True}
    id = Column(Integer, primary_key=True)
    key_id = Column(Integer, nullable=False, index=True)
    model = Column(String(100), nullable=False)
    tokens_in = Column(Integer, default=0)
    tokens_out = Column(Integer, default=0)
    cost_actual = Column(Float, default=0.0)
    cost_standard = Column(Float, default=0.0)
    duration_ms = Column(Float, default=0.0)
    status = Column(String(20), default="success")
    error_msg = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)

# ─── Auth ────────────────────────────────────────────────────────────────

from bot.misc.env import EnvKeys

ADMIN_KEY = EnvKeys.FREEMODEL_ADMIN_KEY

async def auth(request: Request):
    key = request.headers.get("X-Admin-Key") or request.headers.get("Authorization", "").replace("Bearer ", "")
    if key != ADMIN_KEY:
        raise HTTPException(401, "Unauthorized")
    return True

# ─── Schemas ─────────────────────────────────────────────────────────────

class KeyCreate(BaseModel):
    name: str
    user_id: int | None = None

class KeyUpdate(BaseModel):
    name: str | None = None
    is_active: bool | None = None

class ProviderKeyUpdate(BaseModel):
    keys: list[str]

# ─── Endpoints ───────────────────────────────────────────────────────────

@router.get("/stats")
async def get_stats(days: int = 7, _: bool = Depends(auth)):
    """Get aggregated stats from both proxy and local logs."""
    async with Database().session() as db:
        # Get proxy stats
        proxy_stats = {}
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get("http://127.0.0.1:8765/stats")
                proxy_stats = resp.json()
        except Exception as e:
            proxy_stats = {"error": str(e)}
        
        # Get local aggregated stats
        since = datetime.now(timezone.utc) - __import__('datetime').timedelta(days=days)
        
        total_requests = await db.scalar(
            select(func.count(FMRequestLog.id)).where(FMRequestLog.created_at >= since)
        ) or 0
        
        total_tokens_in = await db.scalar(
            select(func.sum(FMRequestLog.tokens_in)).where(FMRequestLog.created_at >= since)
        ) or 0
        
        total_tokens_out = await db.scalar(
            select(func.sum(FMRequestLog.tokens_out)).where(FMRequestLog.created_at >= since)
        ) or 0
        
        total_cost_actual = await db.scalar(
            select(func.sum(FMRequestLog.cost_actual)).where(FMRequestLog.created_at >= since)
        ) or 0.0
        
        total_cost_standard = await db.scalar(
            select(func.sum(FMRequestLog.cost_standard)).where(FMRequestLog.created_at >= since)
        ) or 0.0
        
        avg_duration = await db.scalar(
            select(func.avg(FMRequestLog.duration_ms)).where(
                and_(FMRequestLog.created_at >= since, FMRequestLog.status == "success")
            )
        ) or 0.0
        
        # Keys stats
        keys_total = await db.scalar(select(func.count(FMApiKey.id))) or 0
        keys_active = await db.scalar(
            select(func.count(FMApiKey.id)).where(FMApiKey.is_active == True)
        ) or 0
        
        # Model usage breakdown
        model_stats = await db.execute(
            select(
                FMRequestLog.model,
                func.count(FMRequestLog.id).label("count"),
                func.sum(FMRequestLog.tokens_in).label("tokens_in"),
                func.sum(FMRequestLog.tokens_out).label("tokens_out"),
            ).where(FMRequestLog.created_at >= since)
            .group_by(FMRequestLog.model)
            .order_by(func.count(FMRequestLog.id).desc())
            .limit(10)
        )
        models = [dict(m._mapping) for m in model_stats.all()]
        
        # Daily breakdown
        daily_stats = await db.execute(
            select(
                func.date(FMRequestLog.created_at).label("date"),
                func.count(FMRequestLog.id).label("requests"),
                func.sum(FMRequestLog.tokens_in).label("tokens_in"),
                func.sum(FMRequestLog.tokens_out).label("tokens_out"),
                func.sum(FMRequestLog.cost_actual).label("cost"),
            ).where(FMRequestLog.created_at >= since)
            .group_by(func.date(FMRequestLog.created_at))
            .order_by(func.date(FMRequestLog.created_at).desc())
        )
        daily = [dict(d._mapping) for d in daily_stats.all()]
        
        return {
            "summary": {
                "total_requests": total_requests,
                "total_tokens": total_tokens_in + total_tokens_out,
                "tokens_in": total_tokens_in,
                "tokens_out": total_tokens_out,
                "cost_actual": round(total_cost_actual, 4),
                "cost_standard": round(total_cost_standard, 4),
                "avg_duration_ms": round(avg_duration, 2),
            },
            "keys": {
                "total": keys_total,
                "active": keys_active,
                "proxy_available": proxy_stats.get("available_keys", 0),
                "proxy_total": proxy_stats.get("keys_total", 0),
            },
            "models": models,
            "daily": daily,
            "proxy": proxy_stats,
        }

@router.get("/keys")
async def list_keys(_: bool = Depends(auth)):
    """List all API keys."""
    async with Database().session() as db:
        result = await db.execute(
            select(FMApiKey).order_by(FMApiKey.created_at.desc())
        )
        keys = result.scalars().all()
        return {
            "keys": [
                {
                    "id": k.id,
                    "key": k.key[:8] + "..." + k.key[-4:],  # Partially hidden
                    "name": k.name,
                    "is_active": k.is_active,
                    "created_at": k.created_at.isoformat() if k.created_at else None,
                    "last_used_at": k.last_used_at.isoformat() if k.last_used_at else None,
                    "requests_count": k.requests_count,
                    "tokens_in": k.tokens_in,
                    "tokens_out": k.tokens_out,
                    "cost_actual": round(k.cost_actual, 4),
                }
                for k in keys
            ]
        }

@router.post("/keys")
async def create_key(data: KeyCreate, _: bool = Depends(auth)):
    """Create a new API key."""
    async with Database().session() as db:
        # Generate secure key
        key = "fm_" + secrets.token_urlsafe(32)[:48]
        
        fm_key = FMApiKey(
            key=key,
            name=data.name,
            user_id=data.user_id,
        )
        db.add(fm_key)
        await db.commit()
        await db.refresh(fm_key)
        
        return {
            "id": fm_key.id,
            "key": key,  # Full key shown only once!
            "name": fm_key.name,
        }

@router.get("/keys/{key_id}")
async def get_key(key_id: int, _: bool = Depends(auth)):
    """Get key details."""
    async with Database().session() as db:
        key = await db.get(FMApiKey, key_id)
        if not key:
            raise HTTPException(404, "Key not found")
        return {
            "id": key.id,
            "key": key.key[:8] + "..." + key.key[-4:],
            "name": key.name,
            "is_active": key.is_active,
            "created_at": key.created_at.isoformat() if key.created_at else None,
            "last_used_at": key.last_used_at.isoformat() if key.last_used_at else None,
            "requests_count": key.requests_count,
            "tokens_in": key.tokens_in,
            "tokens_out": key.tokens_out,
            "cost_actual": round(key.cost_actual, 4),
        }

@router.patch("/keys/{key_id}")
async def update_key(key_id: int, data: KeyUpdate, _: bool = Depends(auth)):
    """Update key."""
    async with Database().session() as db:
        key = await db.get(FMApiKey, key_id)
        if not key:
            raise HTTPException(404, "Key not found")
        
        if data.name is not None:
            key.name = data.name
        if data.is_active is not None:
            key.is_active = data.is_active
        
        await db.commit()
        return {"ok": True}

@router.delete("/keys/{key_id}")
async def delete_key(key_id: int, _: bool = Depends(auth)):
    """Delete key."""
    async with Database().session() as db:
        key = await db.get(FMApiKey, key_id)
        if not key:
            raise HTTPException(404, "Key not found")
        
        await db.delete(key)
        await db.commit()
        return {"ok": True}

@router.get("/logs")
async def get_logs(
    key_id: int | None = None,
    days: int = 7,
    limit: int = 100,
    _: bool = Depends(auth)
):
    """Get request logs."""
    async with Database().session() as db:
        since = datetime.now(timezone.utc) - __import__('datetime').timedelta(days=days)
        
        query = select(FMRequestLog).where(FMRequestLog.created_at >= since)
        if key_id:
            query = query.where(FMRequestLog.key_id == key_id)
        
        query = query.order_by(FMRequestLog.created_at.desc()).limit(limit)
        
        result = await db.execute(query)
        logs = result.scalars().all()
        
        return {
            "logs": [
                {
                    "id": l.id,
                    "key_id": l.key_id,
                    "model": l.model,
                    "tokens_in": l.tokens_in,
                    "tokens_out": l.tokens_out,
                    "cost_actual": round(l.cost_actual, 4),
                    "duration_ms": round(l.duration_ms, 2),
                    "status": l.status,
                    "created_at": l.created_at.isoformat() if l.created_at else None,
                }
                for l in logs
            ]
        }

# ─── Provider Keys Management ─────────────────────────────────────

@router.get("/provider-keys")
async def list_provider_keys(request: Request, db: AsyncSession = Depends(db_session)):
    """Get all 60 provider keys with their status"""
    await auth(request)
    from bot.web.freemodel_app import proxy
    if not proxy:
        return {"keys": [], "total": 0}
    
    stats = await proxy.get_stats()
    return {
        "keys": stats.get("keys", []),
        "total": stats.get("keys_total", 0),
        "available": stats.get("available_keys", 0),
        "active_requests": stats.get("active_requests", 0),
        "avg_latency_ms": stats.get("avg_latency_ewma_ms", 0)
    }

@router.post("/provider-keys/reload")
async def reload_provider_keys(request: Request, db: AsyncSession = Depends(db_session)):
    """Reload provider keys from proxy.py KEYS list"""
    await auth(request)
    from bot.web.freemodel_app import proxy
    if proxy:
        # Force reload from source
        import importlib
        import bot.web.freemodel_app as fm
        importlib.reload(fm)
        return {"ok": True, "message": "Keys reloaded"}
    return {"ok": False, "message": "Proxy not running"}

@router.post("/provider-keys/update")
async def update_provider_keys(data: ProviderKeyUpdate, request: Request, db: AsyncSession = Depends(db_session)):
    """Update provider keys list"""
    await auth(request)
    from bot.web.freemodel_app import proxy
    if not proxy:
        return {"ok": False, "message": "Proxy not running"}
    
    # Update the proxy keys
    proxy.keys = data.keys
    proxy.key_index = 0
    
    return {"ok": True, "total": len(data.keys)}

@router.post("/provider-keys/add")
async def add_provider_keys(data: ProviderKeyUpdate, request: Request, db: AsyncSession = Depends(db_session)):
    """Add new provider keys to existing list"""
    await auth(request)
    from bot.web.freemodel_app import proxy
    if not proxy:
        return {"ok": False, "message": "Proxy not running"}
    
    existing_fingerprints = set(k.get("fingerprint", "") for k in proxy.keys)
    added = 0
    
    for key in data.keys:
        # Generate fingerprint for new key
        import hashlib
        fingerprint = f"manual_{hashlib.md5(key.encode()).hexdigest()[:12]}"
        if fingerprint not in existing_fingerprints:
            proxy.keys.append({
                "key": key,
                "fingerprint": fingerprint,
                "status": "available",
                "available": True
            })
            added += 1
    
    return {"ok": True, "added": added, "total": len(proxy.keys)}

@router.delete("/provider-keys/{fingerprint}")
async def remove_provider_key(fingerprint: str, request: Request, db: AsyncSession = Depends(db_session)):
    """Remove a provider key by fingerprint"""
    await auth(request)
    from bot.web.freemodel_app import proxy
    if not proxy:
        return {"ok": False, "message": "Proxy not running"}
    
    initial_len = len(proxy.keys)
    proxy.keys = [k for k in proxy.keys if k.get("fingerprint") != fingerprint]
    
    removed = initial_len - len(proxy.keys)
    return {"ok": True, "removed": removed}

# ─── Tables creation ─────────────────────────────────────────────────────

async def init_tables():
    """Create tables if not exist."""
    async with Database().engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
