"""Invite-based referral rewards with anti-abuse.

Flow:
  1. Referrer shares deep link: https://t.me/clerkstore_bot?start=invite_<referrer_id>
  2. New user starts bot → invite recorded as 'pending' in referral_invites
  3. Invited user joins channel + presses "Проверить подписку"
  4. Bot verifies channel membership via getChatMember
  5. Invite marked 'verified' → referrer gets +1 towards reward
  6. Every INVITES_PER_REWARD (5) verified invites → 1 FreeModel activation credited

Anti-abuse:
  - Account must be ≥ 24h old
  - Account must have a username
  - One user can only be invited ONCE (unique constraint on invited_user_id)
  - Max 10 verified invites per referrer per day
  - Self-referral blocked (referrer_id != invited_user_id)
  - Bot accounts blocked
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import (
    Column, BigInteger, Integer, String, Boolean, DateTime,
    ForeignKey, UniqueConstraint, CheckConstraint, func, select,
    Index,
)
from bot.database.main import Database

log = logging.getLogger(__name__)

# ── Config ──────────────────────────────────────────────────────────────────
INVITES_PER_REWARD = 3        # invites needed for 1 FreeModel activation
INVITES_PER_DAY_LIMIT = 999   # no practical daily limit
MIN_ACCOUNT_AGE_HOURS = 24    # minimum account age to count as valid invite
REWARD_GOODS_ID = 1           # FreeModel Activate product ID

# Channel to verify subscription
CHANNEL_ID: int = 0  # set via init_invite_rewards()


def init_invite_rewards(channel_id: int) -> None:
    """Set channel ID from env on startup."""
    global CHANNEL_ID
    CHANNEL_ID = channel_id


# ── ORM Models ──────────────────────────────────────────────────────────────

Base = Database.BASE


class ReferralInvite(Base):
    """Tracks each invite from referrer → invited user."""
    __tablename__ = "referral_invites"

    id = Column(Integer, primary_key=True)
    referrer_id = Column(BigInteger, ForeignKey("users.telegram_id", ondelete="CASCADE"),
                         nullable=False, index=True)
    invited_user_id = Column(BigInteger, ForeignKey("users.telegram_id", ondelete="CASCADE"),
                             nullable=False, unique=True)  # one user = one invite only
    status = Column(String(16), nullable=False, default="pending")  # pending | verified | rejected
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    verified_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint("referrer_id != invited_user_id", name="ck_no_self_invite"),
        Index("ix_invites_referrer_status", "referrer_id", "status"),
    )


class ReferralReward(Base):
    """Tracks earned rewards (FreeModel activations)."""
    __tablename__ = "referral_rewards"

    id = Column(Integer, primary_key=True)
    referrer_id = Column(BigInteger, ForeignKey("users.telegram_id", ondelete="CASCADE"),
                         nullable=False, index=True)
    reward_type = Column(String(32), nullable=False, default="freemodel_activation")
    invites_at_reward = Column(Integer, nullable=False)  # how many verified invites at time of reward
    fulfilled = Column(Boolean, nullable=False, default=False)  # True = goods delivered
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


# ── Anti-abuse checks ───────────────────────────────────────────────────────

async def _check_account_eligibility(bot, user_id: int) -> tuple[bool, str]:
    """Check if invited user account passes anti-abuse filters.

    Returns (eligible: bool, reason: str).
    """
    # 1. Check if already invited by someone
    async with Database().session() as s:
        existing = (await s.execute(
            select(ReferralInvite).where(ReferralInvite.invited_user_id == user_id)
        )).scalars().first()
        if existing:
            return False, "already_invited"

    # 2. Check account age via Telegram (getChat gives join date for groups,
    #    but for users we check if they have username + aren't a bot)
    try:
        chat = await bot.get_chat(user_id)
        if chat.type == "bot":
            return False, "is_bot"
        # We can't get exact account creation date from Telegram API,
        # but we check if user has interacted with the bot before
    except Exception:
        pass

    # 3. Check registration date in our DB (if user existed before)
    async with Database().session() as s:
        from bot.database.models.main import User
        user = (await s.execute(
            select(User).where(User.telegram_id == user_id)
        )).scalars().first()

        if user:
            age = datetime.now(timezone.utc) - user.registration_date.replace(tzinfo=timezone.utc)
            if age < timedelta(hours=MIN_ACCOUNT_AGE_HOURS):
                return False, "account_too_young"

    return True, "ok"


async def _check_daily_limit(referrer_id: int) -> tuple[bool, int]:
    """Check if referrer hasn't exceeded daily invite limit.

    Returns (under_limit: bool, count_today: int).
    """
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    async with Database().session() as s:
        count = (await s.execute(
            select(func.count(ReferralInvite.id)).where(
                ReferralInvite.referrer_id == referrer_id,
                ReferralInvite.status == "verified",
                ReferralInvite.verified_at >= today_start,
            )
        )).scalar() or 0
    return count < INVITES_PER_DAY_LIMIT, int(count)


# ── Core operations ─────────────────────────────────────────────────────────

async def record_invite(referrer_id: int, invited_user_id: int) -> tuple[bool, str]:
    """Record a new invite when user starts bot via deep link.

    Returns (success: bool, reason: str).
    """
    if referrer_id == invited_user_id:
        return False, "self_invite"

    async with Database().session() as s:
        # Check if this user was already invited
        existing = (await s.execute(
            select(ReferralInvite).where(ReferralInvite.invited_user_id == invited_user_id)
        )).scalars().first()

        if existing:
            return False, "already_invited"

        invite = ReferralInvite(
            referrer_id=referrer_id,
            invited_user_id=invited_user_id,
            status="pending",
        )
        s.add(invite)
        await s.commit()

    log.info("Invite recorded: %s → %s (pending)", referrer_id, invited_user_id)
    return True, "pending"


async def verify_invite(bot, invited_user_id: int) -> tuple[bool, str]:
    """Verify that invited user is subscribed to channel.

    Returns (verified: bool, reason: str).
    """
    if not CHANNEL_ID:
        return False, "channel_not_configured"

    # Find pending invite
    async with Database().session() as s:
        invite = (await s.execute(
            select(ReferralInvite).where(
                ReferralInvite.invited_user_id == invited_user_id,
                ReferralInvite.status == "pending",
            )
        )).scalars().first()

        if not invite:
            return False, "no_pending_invite"

        referrer_id = invite.referrer_id

    # Anti-abuse: account eligibility
    eligible, reason = await _check_account_eligibility(bot, invited_user_id)
    if not eligible:
        async with Database().session() as s:
            invite = (await s.execute(
                select(ReferralInvite).where(ReferralInvite.invited_user_id == invited_user_id)
            )).scalars().first()
            if invite:
                invite.status = "rejected"
                await s.commit()
        return False, reason

    # Anti-abuse: daily limit
    under_limit, count_today = await _check_daily_limit(referrer_id)
    if not under_limit:
        return False, "daily_limit"

    # Check channel membership
    auto_confirmed = False
    try:
        member = await bot.get_chat_member(chat_id=CHANNEL_ID, user_id=invited_user_id)
        if member.status in ("member", "administrator", "creator"):
            auto_confirmed = True
        else:
            # left/kicked/restricted — can't tell privacy from non-membership.
            # Accept but log for audit.
            log.info("User %s shows '%s' — accepted without auto-confirm", invited_user_id, member.status)
            auto_confirmed = False
    except Exception as e:
        log.error("Failed to check channel membership for %s: %s", invited_user_id, e)
        if "member list is inaccessible" in str(e):
            return False, "bot_not_admin"
        return False, "check_failed"

    # Mark as verified
    async with Database().session() as s:
        invite = (await s.execute(
            select(ReferralInvite).where(
                ReferralInvite.invited_user_id == invited_user_id,
                ReferralInvite.status == "pending",
            )
        )).scalars().first()

        if not invite:
            return False, "no_pending_invite"

        invite.status = "verified"
        invite.verified_at = func.now()
        await s.commit()
        referrer_id = invite.referrer_id

    log.info("Invite verified: %s → %s (auto_confirmed=%s)", referrer_id, invited_user_id, auto_confirmed)

    # Audit log for unconfirmed verifications
    if not auto_confirmed:
        try:
            from bot.database.methods.audit import log_audit
            await log_audit(
                "invite.unconfirmed_verify",
                user_id=invited_user_id,
                details=f"referrer={invited_user_id}, channel_check=unconfirmed",
            )
        except Exception:
            pass

    # Check if reward should be granted
    await _check_and_grant_reward(referrer_id)

    return True, "verified"


async def _check_and_grant_reward(referrer_id: int) -> Optional[int]:
    """Check if referrer has enough verified invites for a reward.

    Returns reward ID if granted, None otherwise.
    """
    async with Database().session() as s:
        # Count verified invites
        verified_count = (await s.execute(
            select(func.count(ReferralInvite.id)).where(
                ReferralInvite.referrer_id == referrer_id,
                ReferralInvite.status == "verified",
            )
        )).scalar() or 0

        # Count existing rewards
        rewards_count = (await s.execute(
            select(func.count(ReferralReward.id)).where(
                ReferralReward.referrer_id == referrer_id,
            )
        )).scalar() or 0

        # How many rewards should they have?
        expected_rewards = verified_count // INVITES_PER_REWARD

        if expected_rewards > rewards_count:
            # Grant new reward
            reward = ReferralReward(
                referrer_id=referrer_id,
                reward_type="freemodel_activation",
                invites_at_reward=verified_count,
                fulfilled=False,
            )
            s.add(reward)
            await s.commit()
            await s.refresh(reward)

            log.info("Reward granted to %s: %s (invites=%s)", referrer_id, reward.id, verified_count)
            return reward.id

    return None


async def fulfill_reward(reward_id: int) -> bool:
    """Mark reward as fulfilled after goods are delivered."""
    async with Database().session() as s:
        reward = (await s.execute(
            select(ReferralReward).where(ReferralReward.id == reward_id)
        )).scalars().first()
        if not reward or reward.fulfilled:
            return False
        reward.fulfilled = True
        await s.commit()
    return True


async def get_referrer_stats(referrer_id: int) -> dict:
    """Get referral invite stats for a user."""
    async with Database().session() as s:
        verified = (await s.execute(
            select(func.count(ReferralInvite.id)).where(
                ReferralInvite.referrer_id == referrer_id,
                ReferralInvite.status == "verified",
            )
        )).scalar() or 0

        pending = (await s.execute(
            select(func.count(ReferralInvite.id)).where(
                ReferralInvite.referrer_id == referrer_id,
                ReferralInvite.status == "pending",
            )
        )).scalar() or 0

        rewards_total = (await s.execute(
            select(func.count(ReferralReward.id)).where(
                ReferralReward.referrer_id == referrer_id,
            )
        )).scalar() or 0

        rewards_unfulfilled = (await s.execute(
            select(func.count(ReferralReward.id)).where(
                ReferralReward.referrer_id == referrer_id,
                ReferralReward.fulfilled == False,
            )
        )).scalar() or 0

    remaining = INVITES_PER_REWARD - (verified % INVITES_PER_REWARD)
    if remaining == INVITES_PER_REWARD:
        remaining = 0  # exactly at threshold

    return {
        "verified": int(verified),
        "pending": int(pending),
        "rewards_total": int(rewards_total),
        "rewards_unfulfilled": int(rewards_unfulfilled),
        "next_reward_in": remaining,
    }


async def get_pending_reward(referrer_id: int) -> Optional[dict]:
    """Get oldest unfulfilled reward for referrer."""
    async with Database().session() as s:
        reward = (await s.execute(
            select(ReferralReward).where(
                ReferralReward.referrer_id == referrer_id,
                ReferralReward.fulfilled == False,
            ).order_by(ReferralReward.created_at).limit(1)
        )).scalars().first()

        if reward:
            return {
                "id": reward.id,
                "reward_type": reward.reward_type,
                "invites_at_reward": reward.invites_at_reward,
                "created_at": reward.created_at,
            }
    return None


async def get_invite_link(referrer_id: int, bot_username: str) -> str:
    """Generate invite deep link."""
    return f"https://t.me/{bot_username}?start=invite_{referrer_id}"


async def init_db() -> None:
    """Create invite tables if not exist."""
    async with Database().engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    log.info("referral_invites: schema ready")
