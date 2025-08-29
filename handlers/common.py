from aiogram import types
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder
import logging

# Хранилище и загрузка
from storage import upload_photo_to_storage
# групповые буферы для медиа отображаются/наполняются в media_processing
from handlers.shared_data import media_groups, media_group_locks, document_groups, document_group_locks


async def show_media_buttons(chat_id: int, state: FSMContext, bot):
    """
    Показать кнопки управления медиа при наборе фото.
    Кнопки:
      - «Готово» -> media_done
      - «Добавить видео» -> add_video
    """
    try:
        data = await state.get_data()
        media_list = data.get("media", [])
        limit = data.get("media_limit", 6)
        count = len(media_list)

        builder = InlineKeyboardBuilder()
        builder.add(types.InlineKeyboardButton(text="Готово", callback_data="media_done"))
        builder.add(types.InlineKeyboardButton(text="Добавить видео", callback_data="add_video"))
        builder.adjust(2)

        await bot.send_message(
            chat_id,
            f"📷 Фото: {count}/{limit}\n"
            "• Можно отправлять как фото или как документ (качество лучше)\n"
            "• Когда закончите — нажмите «Готово»",
            reply_markup=builder.as_markup()
        )
    except Exception as e:
        logging.error(f"Ошибка в show_media_buttons: {e}", exc_info=True)


async def handle_media_upload(bot, media_list, bouquet_id: str):
    """
    Загружает все фото в облако и возвращает СПИСОК СЛОВАРЕЙ для записи в БД.

    👉 Формат элемента:
        {
          "file_id": "<telegram_file_id>",             # ВСЕГДА
          "url": "https://<yandex-object-storage>..."  # если загрузка удалась
        }

    Если облако временно недоступно — всё равно вернём {"file_id": "..."}.
    """
    uploaded = []
    logging.info(f"Загрузка {len(media_list)} медиа для букета {bouquet_id}")

    for index, file_id in enumerate(media_list, start=1):
        try:
            url = await upload_photo_to_storage(bot, file_id, bouquet_id, index - 1)
            if url:
                uploaded.append({"file_id": file_id, "url": url})
                logging.info(f"[{index}] загружено -> {url}")
            else:
                uploaded.append({"file_id": file_id})
                logging.warning(f"[{index}] не удалось загрузить на облако, сохраняю только file_id")
        except Exception as e:
            logging.error(f"[{index}] ошибка загрузки фото: {e}", exc_info=True)
            uploaded.append({"file_id": file_id})

    logging.info(f"Итог медиа к сохранению: {uploaded}")
    return uploaded


async def handle_back_to_menu(callback: types.CallbackQuery, state: FSMContext):
    """Возврат в главное меню с клавиатурой."""
    try:
        keyboard = types.ReplyKeyboardMarkup(
            keyboard=[
                [types.KeyboardButton(text="➕ Добавить букет")],
                [types.KeyboardButton(text="📚 Мои букеты")],
                [types.KeyboardButton(text="⚙️ Настройки")],
                [types.KeyboardButton(text="❓ Помощь")],
            ],
            resize_keyboard=True
        )
        await callback.message.answer("Главное меню:", reply_markup=keyboard)
        await callback.answer()
    except Exception as e:
        logging.error(f"Ошибка в handle_back_to_menu: {e}", exc_info=True)
        try:
            await callback.answer("Произошла ошибка при возврате в меню.")
        except Exception:
            pass


# Файл не предназначен для прямого запуска
if __name__ == "__main__":
    print("Запустите основной скрипт бота.")
