from .main import router as main_router
from .profile import router as profile_router
from .balance_and_payment import router as balance_router
from .shop_and_goods import router as shop_router
from .cart import router as cart_router
from .referral_system import router as referral_router
from .invite_rewards import router as invite_router

from aiogram import Router

router = Router()
router.include_router(main_router)
router.include_router(invite_router)
router.include_router(profile_router)
router.include_router(balance_router)
router.include_router(shop_router)
router.include_router(cart_router)
router.include_router(referral_router)
