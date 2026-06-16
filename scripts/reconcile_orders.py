"""One-shot reconciliation: sync all in_progress orders with Tipzy actual status."""
import asyncio
import sys
sys.path.insert(0, "/opt/bots/smm-bot")

from sqlalchemy import select
from bot.database.main import Database
from bot.database.models.main import TipzyOrder
from bot.misc.tipzy import tipzy_order_status

DONE_OK = {"completed", "partial"}
DONE_FAIL = {"canceled", "cancelled", "failed"}


async def main():
    fixed = []
    async with Database().session() as s:
        rows = (await s.execute(
            select(TipzyOrder).where(TipzyOrder.status.in_(["in_progress", "processing", "pending"]))
        )).scalars().all()

        print(f"Найдено {len(rows)} заказов в работе/ожидании")

        for o in rows:
            if not o.tipzy_order_id:
                print(f"  #{o.id}: нет tipzy_order_id — пропуск")
                continue
            try:
                data = await tipzy_order_status(int(o.tipzy_order_id))
                tstatus = (data.get("status") or "").strip()
                o.tipzy_status = tstatus or None
                if data.get("start_count") is not None:
                    o.tipzy_start_count = int(data["start_count"])
                if data.get("remains") is not None:
                    o.tipzy_remains = int(data["remains"])
                if data.get("charge") is not None:
                    from decimal import Decimal
                    o.tipzy_charge = Decimal(str(data["charge"]))

                low = tstatus.lower()
                old = o.status
                if low in DONE_OK:
                    o.status = "completed"
                elif low in DONE_FAIL:
                    o.status = "failed"
                if o.status != old:
                    fixed.append((o.id, old, o.status, tstatus))
                    print(f"  #{o.id}: {old} → {o.status} (tipzy={tstatus})")
                else:
                    print(f"  #{o.id}: без изменений (tipzy={tstatus})")
            except Exception as e:
                print(f"  #{o.id}: ОШИБКА {e}")

        await s.commit()

    print(f"\nИтого исправлено: {len(fixed)}")
    for oid, old, new, ts in fixed:
        print(f"  #{oid}: {old} → {new} [{ts}]")


if __name__ == "__main__":
    asyncio.run(main())
