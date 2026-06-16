from aiogram.fsm.state import State, StatesGroup


class TipzyOrderFSM(StatesGroup):
    waiting_links = State()
    waiting_quantity = State()
    confirm = State()
