"""Level calculation utility — single source of truth for user tiers."""


def get_level(spent: float) -> tuple[str, str]:
    """Returns (emoji + level_name, level_name_only).
    
    Thresholds:
        >= 10_000 → 💎 Премиум
        >=  3_000 → 🥇 Продвинутый
        >=    500 → 🥈 Опытный
        <     500 → ⭐ Новичок
    """
    if spent >= 10_000:
        return "💎 Премиум", "Премиум"
    elif spent >= 3_000:
        return "🥇 Продвинутый", "Продвинутый"
    elif spent >= 500:
        return "🥈 Опытный", "Опытный"
    return "⭐ Новичок", "Новичок"
