from aiogram.fsm.state import StatesGroup, State

class BouquetStates(StatesGroup):
    # Создание
    waiting_title = State()
    waiting_media = State()
    waiting_description = State()
    waiting_composition = State()
    waiting_price = State()

    # Интерактивный набор состава
    choosing_category = State()
    choosing_product = State()
    entering_quantity = State()

    # Редактирование
    editing_title = State()
    editing_media = State()
    editing_description = State()
    editing_composition = State()
    editing_price = State()

    # Настройки
    waiting_photo_limit = State()
    waiting_catalog_file = State()  # <- ждём .xlsx для импорта каталога
