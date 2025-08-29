# handlers/media_processing.py
from aiogram import F, types
from aiogram.fsm.context import FSMContext
import asyncio
import logging

from .shared_data import media_groups, media_group_locks, document_groups, document_group_locks
from .common import show_media_buttons
from storage import upload_video_to_storage
from states import BouquetStates


async def handle_back_to_media(callback_query: types.CallbackQuery, state: FSMContext):
    """Кнопка 'Назад' при загрузке медиа: возвращаемся к состоянию ожидания фото."""
    try:
        await callback_query.answer()
        await state.set_state(BouquetStates.waiting_media)
        await callback_query.message.edit_text("Вы можете добавить фото (или альбом).", reply_markup=None)
    except Exception as e:
        logging.error(f"handle_back_to_media error: {e}", exc_info=True)


async def handle_photos(message: types.Message, state: FSMContext):
    """Приём фотографий (включая альбомы)."""
    try:
        data = await state.get_data()
        media_list = data.get("media", [])
        limit = int(data.get("media_limit", 6))

        # Альбом
        if message.media_group_id:
            async with media_group_locks[message.media_group_id]:
                media_groups[message.media_group_id].append(message.photo[-1].file_id)
                if len(media_groups[message.media_group_id]) == 1:
                    asyncio.create_task(process_media_group(message.media_group_id, state, message.chat.id, message.bot))
            return

        # Одиночное фото
        if len(media_list) >= limit:
            await message.answer(f"Достигнут лимит в {limit} фото")
            await show_media_buttons(message.chat.id, state, message.bot)
            return

        media_list.append(message.photo[-1].file_id)
        await state.update_data(media=media_list)
        await message.answer(f"Фото добавлено. Всего: {len(media_list)}/{limit}")
        await show_media_buttons(message.chat.id, state, message.bot)
    except Exception as e:
        logging.error(f"handle_photos error: {e}", exc_info=True)
        await message.answer("Произошла ошибка при обработке фото.")


async def process_media_group(media_group_id: str, state: FSMContext, chat_id: int, bot):
    """Собираем все фото из альбома и добавляем в state с учётом лимита."""
    try:
        await asyncio.sleep(1.5)
        async with media_group_locks[media_group_id]:
            file_ids = media_groups.get(media_group_id, [])
            if not file_ids:
                return

            data = await state.get_data()
            media_list = data.get("media", [])
            limit = int(data.get("media_limit", 6))

            added = 0
            for fid in file_ids:
                if len(media_list) < limit:
                    media_list.append(fid)
                    added += 1
                else:
                    break

            await state.update_data(media=media_list)
            if added:
                await bot.send_message(chat_id, f"Добавлено фото из альбома: {added}. Всего: {len(media_list)}/{limit}")
                await show_media_buttons(chat_id, state, bot)
    except Exception as e:
        logging.error(f"process_media_group error: {e}", exc_info=True)
    finally:
        media_groups.pop(media_group_id, None)


async def handle_documents(message: types.Message, state: FSMContext):
    """Приём документов: изображения (оригиналы) и видео как документы."""
    try:
        if message.document is None:
            return

        mime = (message.document.mime_type or "")
        data = await state.get_data()
        media_list = data.get("media", [])
        limit = int(data.get("media_limit", 6))

        # Видео как документ
        if mime.startswith("video/"):
            processing = await message.answer("Загружаю видео...")
            try:
                url = await upload_video_to_storage(message.bot, message.document.file_id, data.get("current_id", "temp"))
                if url:
                    await state.update_data(video=url)
                    await processing.edit_text("Видео загружено ✅")
                else:
                    await processing.edit_text("❌ Не удалось загрузить видео. Попробуйте другой файл.")
            except Exception as e:
                logging.error(f"upload video error: {e}", exc_info=True)
                await processing.edit_text("❌ Не удалось загрузить видео.")
            await show_media_buttons(message.chat.id, state, message.bot)
            return

        # Изображение как документ
        if mime.startswith("image/"):
            if len(media_list) >= limit:
                await message.answer(f"Достигнут лимит в {limit} фото")
                await show_media_buttons(message.chat.id, state, message.bot)
                return

            # Альбом документов
            if message.media_group_id:
                async with document_group_locks[message.media_group_id]:
                    document_groups[message.media_group_id].append(message.document.file_id)
                    if len(document_groups[message.media_group_id]) == 1:
                        asyncio.create_task(process_document_group(message.media_group_id, state, message.chat.id, message.bot))
                return

            # Одиночный документ
            media_list.append(message.document.file_id)
            await state.update_data(media=media_list)
            await message.answer(f"Фото (как документ) добавлено. Всего: {len(media_list)}/{limit}")
            await show_media_buttons(message.chat.id, state, message.bot)
            return

        await message.answer("Неподдерживаемый тип файла. Отправьте изображение (JPEG/PNG/WEBP) или видео.")
    except Exception as e:
        logging.error(f"handle_documents error: {e}", exc_info=True)
        await message.answer("Произошла ошибка при обработке документа.")


async def process_document_group(media_group_id: str, state: FSMContext, chat_id: int, bot):
    try:
        await asyncio.sleep(1.5)
        async with document_group_locks[media_group_id]:
            file_ids = document_groups.get(media_group_id, [])
            if not file_ids:
                return

            data = await state.get_data()
            media_list = data.get("media", [])
            limit = int(data.get("media_limit", 6))

            added = 0
            for fid in file_ids:
                if len(media_list) < limit:
                    media_list.append(fid)
                    added += 1
                else:
                    break

            await state.update_data(media=media_list)
            if added:
                await bot.send_message(chat_id, f"Добавлено файлов (как документы): {added}. Всего: {len(media_list)}/{limit}")
                await show_media_buttons(chat_id, state, bot)
    except Exception as e:
        logging.error(f"process_document_group error: {e}", exc_info=True)
    finally:
        document_groups.pop(media_group_id, None)


async def handle_add_video(callback_query: types.CallbackQuery, state: FSMContext):
    try:
        await callback_query.answer()
        await state.set_state(BouquetStates.waiting_video)
        await callback_query.message.edit_text("Отправьте видео файла букета (MP4/MOV, до 20 МБ).", reply_markup=None)
    except Exception as e:
        logging.error(f"handle_add_video error: {e}", exc_info=True)


async def handle_media_done(callback_query: types.CallbackQuery, state: FSMContext):
    """Переход к вводу описания после загрузки медиа."""
    try:
        await callback_query.answer()
        data = await state.get_data()
        if not data.get("media"):
            await callback_query.message.answer("Нужно добавить хотя бы одно фото")
            return

        await state.set_state(BouquetStates.waiting_description)
        await callback_query.message.edit_text("📝 Введите описание букета (до 800 символов):", reply_markup=None)
    except Exception as e:
        logging.error(f"handle_media_done error: {e}", exc_info=True)


async def process_video(message: types.Message, state: FSMContext):
    """Приём видео как message.video в состоянии waiting_video."""
    try:
        if not message.video:
            await message.answer("Пришлите видео файлами (video) или как документ.")
            return

        processing = await message.answer("Загружаю видео...")
        data = await state.get_data()
        url = await upload_video_to_storage(message.bot, message.video.file_id, data.get("current_id", "temp"))
        if url:
            await state.update_data(video=url)
            await processing.edit_text("Видео загружено ✅")
        else:
            await processing.edit_text("❌ Не удалось загрузить видео.")
        await show_media_buttons(message.chat.id, state, message.bot)
    except Exception as e:
        logging.error(f"process_video error: {e}", exc_info=True)
        await message.answer("Произошла ошибка при загрузке видео.")
