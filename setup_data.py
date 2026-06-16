"""Initializes DB and seeds the tipzy product."""
import asyncio
from dotenv import load_dotenv
load_dotenv()

from bot.database.models import register_models
from bot.database.main import Database
from bot.database.models.main import Categories, Goods, ItemValues
from sqlalchemy import select


async def main():
    await register_models()
    print("✅ Tables created")

    async with Database().session() as s:
        # Category
        cat = (await s.execute(select(Categories).where(Categories.name == "SMM услуги"))).scalars().first()
        if not cat:
            cat = Categories(name="SMM услуги")
            s.add(cat)
            await s.flush()
            print("✅ Category 'SMM услуги' created")
        else:
            print("ℹ️  Category already exists")

        # Product
        item_name = "TG Старт бота __tipzy__"
        item = (await s.execute(select(Goods).where(Goods.name == item_name))).scalars().first()
        if not item:
            item = Goods(
                name=item_name,
                price=0.05,  # sell price per unit (will show in card; real price computed dynamically)
                description=(
                    "⚡ Моментальные старты бота\n\n"
                    "• Живые аккаунты\n"
                    "• Минимум 1, максимум 56 000\n"
                    "• Скидка от 500 шт (-10%), от 1000 (-20%), от 5000 (-30%)\n"
                    "• Ссылка формата: https://t.me/YourBot?start=XXXXX"
                ),
                category_id=cat.id,
            )
            s.add(item)
            await s.flush()
            print(f"✅ Product '{item_name}' created")
        else:
            print("ℹ️  Product already exists")

        # ItemValues: is_infinity=True means unlimited stock (tipzy handles supply)
        val = (await s.execute(
            select(ItemValues).where(ItemValues.item_id == item.id)
        )).scalars().first()
        if not val:
            iv = ItemValues(item_id=item.id, value="__tipzy__:513", is_infinity=True)
            s.add(iv)
            print("✅ ItemValue seeded")

        await s.commit()

    print("\n🚀 Setup complete. Tipzy product is live in the catalog.")


asyncio.run(main())
