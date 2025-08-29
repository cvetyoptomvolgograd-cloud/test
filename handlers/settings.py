from aiogram import types
from aiogram.fsm.context import FSMContext
import logging

from states import BouquetStates
from .product_handler import send_excel_template, handle_catalog_import
from .excel_handler import export_bouquets_to_excel  # если нужен экспорт каталога (букетов)


async def show_settings(message: types.Message):
    """Меню настроек."""
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="Изменить лимит фото", callback_data="settings:photo_limit")],
        [types.InlineKeyboardButton(text="📤 Получить шаблон каталога", callback_data="settings:excel_template")],
        [types.InlineKeyboardButton(text="📥 Импорт каталога (xlsx)", callback_data="settings:import_catalog")],
        [types.InlineKeyboardButton(text="📦 Экспорт каталога (букеты)", callback_data="settings:export_catalog")],
        [types.InlineKeyboardButton(text="Назад", callback_data="back_to_menu")],
    ])
    await message.answer("⚙️ Настройки:", reply_markup=keyboard)


async def handle_settings(callback_query: types.CallbackQuery, state: FSMContext):
    """Обработка кнопок меню настроек."""
    parts = (callback_query.data or "").split(":")
    action = parts[1] if len(parts) > 1 else ""

    if action == "photo_limit":
        await callback_query.message.answer("Введите новый лимит фото (1–10):")
        await state.set_state(BouquetStates.waiting_photo_limit)

    elif action == "excel_template":
        await send_excel_template(callback_query.message)

    elif action == "import_catalog":
        await callback_query.message.answer(
            "Отправьте .xlsx-файл по шаблону:\n"
            "• Лист «Категории»: колонка <b>category</b>\n"
            "• Лист «Товары»: колонки <b>category</b>, <b>name</b>, [color], [type]\n\n"
            "⚠️ При импорте текущий каталог категорий и товаров будет <b>перезаписан</b>."
        )
        await state.set_state(BouquetStates.waiting_catalog_file)

    elif action == "export_catalog":
        await export_bouquets_to_excel(callback_query.message)

    else:
        await callback_query.answer("Неизвестная команда.")
        return

    await callback_query.answer()


async def process_photo_limit(message: types.Message, state: FSMContext):
    """Сохранение нового лимита фото для пользователя."""
    try:
        new_limit = int((message.text or "").strip())
    except Exception:
        await message.answer("Пожалуйста, введите число от 1 до 10.")
        return

    if not (1 <= new_limit <= 10):
        await message.answer("Лимит должен быть от 1 до 10. Попробуйте снова.")
        return

    from database import get_db_session, get_or_create_user

    session = await get_db_session()
    try:
        user = await get_or_create_user(session, message.from_user.id)
        user.media_limit = new_limit
        await session.commit()
        await message.answer(f"Лимит фото изменён на {new_limit}")
        await show_settings(message)
    except Exception as e:
        logging.error(f"Ошибка при обновлении лимита фото: {e}", exc_info=True)
        await message.answer("Ошибка при изменении лимита фото.")
    finally:
        await session.close()
