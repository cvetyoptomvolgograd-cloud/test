from aiogram import F, types, Dispatcher
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder
from database import get_db_session, get_or_create_user, create_bouquet, get_user_bouquets, count_user_bouquets, \
    get_bouquet_by_id, update_bouquet, delete_bouquet
from states import BouquetStates
from utils import parse_composition, format_price
from sqlalchemy import select
from database import Bouquet
import logging
import asyncio
from collections import defaultdict
import os
import uuid
from storage import yandex_storage

# Глобальные переменные для обработки медиа-групп
media_groups = defaultdict(list)
media_group_locks = defaultdict(asyncio.Lock)


async def show_media_buttons(chat_id, state, bot):
    """Показать кнопки управления медиа"""
    try:
        data = await state.get_data()
        media_list = data.get('media', [])
        limit = data.get('media_limit', 6)

        builder = InlineKeyboardBuilder()
        builder.add(types.InlineKeyboardButton(
            text="Добавить видео",
            callback_data="action:add_video")
        )
        builder.add(types.InlineKeyboardButton(
            text="Готово",
            callback_data="action:media_done")
        )

        text = f"Фото добавлены. Всего: {len(media_list)}/{limit}\nВы можете добавить видео или продолжить."

        await bot.send_message(chat_id, text, reply_markup=builder.as_markup())
    except Exception as e:
        logging.error(f"Ошибка в show_media_buttons: {e}")


async def upload_photo_to_storage(bot, file_id, bouquet_id, index):
    """Загружает фото на Yandex Object Storage и возвращает URL"""
    try:
        # Проверяем доступность хранилища
        if not all([yandex_storage.access_key_id, yandex_storage.secret_access_key, yandex_storage.bucket_name]):
            logging.warning("Не настроены учетные данные Yandex Object Storage")
            return file_id  # возвращаем file_id как fallback

        # Скачиваем файл из Telegram
        file = await bot.get_file(file_id)
        file_path = file.file_path

        # Генерируем уникальное имя файла
        file_extension = os.path.splitext(file_path)[1] or '.jpg'
        unique_name = f"{uuid.uuid4().hex}{file_extension}"
        object_name = f"bouquets/{bouquet_id}/{unique_name}"

        # Скачиваем файл
        downloaded_file = await bot.download_file(file_path)
        file_content = downloaded_file.read()

        # Загружаем на Yandex Object Storage
        photo_url = await yandex_storage.upload_from_memory(
            file_content,
            object_name,
            content_type='image/jpeg'
        )

        logging.info(f"Фото успешно загружено на сервер: {photo_url}")
        return photo_url
    except Exception as e:
        logging.error(f"Ошибка при загрузке фото на сервер: {e}")
        return file_id  # возвращаем file_id как fallback


async def upload_video_to_storage(bot, file_id, bouquet_id):
    """Загружает видео на Yandex Object Storage и возвращает URL"""
    try:
        # Проверяем доступность хранилища
        if not all([yandex_storage.access_key_id, yandex_storage.secret_access_key, yandex_storage.bucket_name]):
            logging.warning("Не настроены учетные данные Yandex Object Storage")
            return file_id  # возвращаем file_id как fallback

        # Скачиваем файл из Telegram
        file = await bot.get_file(file_id)
        file_path = file.file_path

        # Генерируем уникальное имя файла
        file_extension = os.path.splitext(file_path)[1] or '.mp4'
        unique_name = f"{uuid.uuid4().hex}{file_extension}"
        object_name = f"bouquets/{bouquet_id}/{unique_name}"

        # Скачиваем файл
        downloaded_file = await bot.download_file(file_path)
        file_content = downloaded_file.read()

        # Загружаем на Yandex Object Storage
        video_url = await yandex_storage.upload_from_memory(
            file_content,
            object_name,
            content_type='video/mp4'
        )

        logging.info(f"Видео успешно загружено на сервер: {video_url}")
        return video_url
    except Exception as e:
        logging.error(f"Ошибка при загрузке видео на сервер: {e}")
        return file_id  # возвращаем file_id как fallback


async def handle_media_upload(bot, media_list, bouquet_id):
    """Загружает все медиафайлы на сервер и возвращает список URL"""
    uploaded_media = []

    for i, file_id in enumerate(media_list):
        photo_url = await upload_photo_to_storage(bot, file_id, bouquet_id, i)
        if photo_url:
            uploaded_media.append(photo_url)
        else:
            # Если не удалось загрузить на сервер, оставляем file_id как fallback
            uploaded_media.append(file_id)
            logging.warning(f"Не удалось загрузить фото {i} для букета {bouquet_id}, используем file_id")

    return uploaded_media


async def handle_photos(message: types.Message, state: FSMContext):
    try:
        # Получаем текущие данные состояния
        data = await state.get_data()
        media_list = data.get('media', [])
        limit = data.get('media_limit', 6)

        # Проверяем, является ли сообщение частью медиа-группы
        if message.media_group_id:
            async with media_group_locks[message.media_group_id]:
                # Добавляем файл в группу
                media_groups[message.media_group_id].append(message.photo[-1].file_id)

                # Если это первое фото в группе, создаем задачу для обработки всей группы
                if len(media_groups[message.media_group_id]) == 1:
                    asyncio.create_task(process_media_group(
                        message.media_group_id,
                        state,
                        message.chat.id,
                        message.bot  # Передаем bot
                    ))

            return

        # Обработка одиночного фото
        if len(media_list) >= limit:
            await message.answer(f"Достигнут лимит в {limit} фото")
            await show_media_buttons(message.chat.id, state, message.bot)
            return

        # Добавляем фото
        media_list.append(message.photo[-1].file_id)
        await state.update_data(media=media_list)

        await message.answer(f"Фото добавлено. Всего: {len(media_list)}/{limit}")
        await show_media_buttons(message.chat.id, state, message.bot)

    except Exception as e:
        logging.error(f"Ошибка в handle_photos: {e}", exc_info=True)
        await message.answer("Произошла ошибка при обработке фото. Попробуйте еще раз.")


async def process_media_group(media_group_id, state, chat_id, bot):  # Добавлен bot как параметр
    """Обработка всей медиа-группы после задержки"""
    try:
        # Ждем 1.5 секунды для получения всех фото в группе
        await asyncio.sleep(1.5)

        async with media_group_locks[media_group_id]:
            # Получаем все файлы из медиа-группы
            file_ids = media_groups.get(media_group_id, [])
            if not file_ids:
                return

            # Получаем текущие данные состояния
            data = await state.get_data()
            media_list = data.get('media', [])
            limit = data.get('media_limit', 6)

            # Добавляем файлы с учетом лимита
            added_count = 0
            for file_id in file_ids:
                if len(media_list) < limit:
                    media_list.append(file_id)
                    added_count += 1
                else:
                    break

            # Обновляем состояние
            await state.update_data(media=media_list)

            # Отправляем сообщение о добавлении
            if added_count > 0:
                await bot.send_message(
                    chat_id,
                    f"Добавлено {added_count} фото из альбома. Всего: {len(media_list)}/{limit}"
                )
                await show_media_buttons(chat_id, state, bot)

    except Exception as e:
        logging.error(f"Ошибка при обработке медиа-группы: {e}")
    finally:
        # Очищаем данные медиа-группы в любом случае
        try:
            async with media_group_locks[media_group_id]:
                if media_group_id in media_groups:
                    del media_groups[media_group_id]
        except KeyError:
            pass


# Остальной код остается без изменений...
# [Остальная часть файла остается без изменений]

async def start_new_bouquet(message: types.Message, state: FSMContext):
    await state.clear()  # Очищаем состояние перед началом нового букета
    session = await get_db_session()
    try:
        user = await get_or_create_user(session, message.from_user.id)

        # Сохраняем chat_id для последующих сообщений
        await state.update_data(chat_id=message.chat.id)

        # Генерация ID букета
        result = await session.execute(
            select(Bouquet).order_by(Bouquet.id.desc()).limit(1)
        )
        last_bouquet = result.scalar_one_or_none()

        next_id = 201 if not last_bouquet else int(last_bouquet.bouquet_id) + 1
        bouquet_id = f"{next_id:04d}"

        await state.update_data(
            current_id=bouquet_id,
            user_id=user.id,
            media=[],
            media_limit=user.media_limit
        )

        await message.answer("Введите краткое название букета (3-40 символов):")
        await state.set_state(BouquetStates.waiting_title)
    except Exception as e:
        logging.error(f"Ошибка в start_new_bouquet: {e}")
        await message.answer("Произошла ошибка при создании букета. Попробуйте еще раз.")
    finally:
        await session.close()


async def process_title(message: types.Message, state: FSMContext):
    try:
        if len(message.text) < 3 or len(message.text) > 40:
            await message.answer("Название должно быть от 3 до 40 символов")
            return

        data = await state.get_data()
        bouquet_id = data['current_id']

        builder = InlineKeyboardBuilder()
        builder.add(types.InlineKeyboardButton(
            text="Дальше",
            callback_data="action:next_step")
        )
        builder.add(types.InlineKeyboardButton(
            text="Изменить название",
            callback_data="action:change_title")
        )

        await state.update_data(title=message.text)
        await message.answer(
            f"Название принято: {message.text} №{bouquet_id}",
            reply_markup=builder.as_markup()
        )
    except Exception as e:
        logging.error(f"Ошибка в process_title: {e}")
        await message.answer("Произошла ошибка при обработке названия. Попробуйте еще раз.")


async def handle_documents(message: types.Message, state: FSMContext):
    try:
        # Обработка документов (HEIC и видео)
        if message.document.mime_type and message.document.mime_type.startswith('image/heic'):
            # Конвертация HEIC в JPEG временно отключена
            await message.answer("Поддержка HEIC временно отключена. Пожалуйста, используйте JPEG или PNG.")
            return
        elif message.document.mime_type and message.document.mime_type.startswith('video/'):
            # Обработка видео
            data = await state.get_data()
            if 'video' in data:
                await message.answer("Видео заменено. Клиент увидит кнопку ▶️ Видео.")
            else:
                await message.answer("Видео сохранено. Клиент увидит кнопку ▶️ Видео.")

            await state.update_data(video=message.document.file_id)
            await show_media_buttons(message.chat.id, state, message.bot)
        else:
            await message.answer("Неподдерживаемый формат файла")
    except Exception as e:
        logging.error(f"Ошибка в handle_documents: {e}")
        await message.answer("Произошла ошибка при обработке файла. Попробуйте еще раз.")


async def process_description(message: types.Message, state: FSMContext):
    try:
        if len(message.text) > 800:
            await message.answer("Описание слишком длинное")
            return

        await state.update_data(description=message.text)

        builder = InlineKeyboardBuilder()
        builder.add(types.InlineKeyboardButton(
            text="Пропустить",
            callback_data="action:skip_composition")
        )
        builder.add(types.InlineKeyboardButton(
            text="Указать состав",
            callback_data="action:add_composition")
        )

        await message.answer(
            "Хотите указать состав букета?",
            reply_markup=builder.as_markup()
        )
        await state.set_state(BouquetStates.waiting_composition)
    except Exception as e:
        logging.error(f"Ошибка в process_description: {e}")
        await message.answer("Произошла ошибка при обработке описания. Попробуйте еще раз.")


async def process_composition(message: types.Message, state: FSMContext):
    try:
        composition = parse_composition(message.text)
        if not composition:
            await message.answer("Не удалось распознать состав. Попробуйте еще раз в формате: 'Розы - 3'")
            return

        await state.update_data(composition=composition)

        builder = InlineKeyboardBuilder()
        builder.add(types.InlineKeyboardButton(
            text="Дальше",
            callback_data="action:next_step")
        )

        await message.answer(
            "Состав сохранен. Переходим к цене.",
            reply_markup=builder.as_markup()
        )
        await state.set_state(BouquetStates.waiting_price)
    except Exception as e:
        logging.error(f"Ошибка в process_composition: {e}")
        await message.answer("Произошла ошибка при обработке состава. Попробуйте еще раз.")


async def process_price(message: types.Message, state: FSMContext):
    try:
        if not message.text.isdigit() or not (1 <= int(message.text) <= 999999):
            await message.answer("Введите корректную цену (целое число от 1 до 999999)")
            return

        price = int(message.text)
        await state.update_data(price=price)

        # Показ превью и предложение сохранить
        data = await state.get_data()

        preview_text = (
            f"<b>{data['title']} №{data['current_id']}</b>\n\n"
            f"<b>Цена:</b> {format_price(price * 100)}\n\n"
            f"<b>Описание:</b>\n{data['description']}\n\n"
        )

        if data.get('composition'):
            preview_text += "<b>Состав:</b>\n"
            for item in data['composition']:
                preview_text += f"{item['raw_name']} - {item['qty']}\n"

        builder = InlineKeyboardBuilder()
        builder.add(types.InlineKeyboardButton(
            text="💾 Сохранить",
            callback_data="action:save_bouquet")
        )
        builder.add(types.InlineKeyboardButton(
            text="✏️ Изменить",
            callback_data="action:edit_bouquet")
        )

        await message.answer(preview_text, reply_markup=builder.as_markup())
        await state.set_state(BouquetStates.preview)
    except Exception as e:
        logging.error(f"Ошибка в process_price: {e}")
        await message.answer("Произошла ошибка при обработке цены. Попробуйте еще раз.")


async def list_bouquets(message: types.Message):
    session = await get_db_session()
    try:
        user = await get_or_create_user(session, message.from_user.id)
        bouquets = await get_user_bouquets(session, user.id, page=1)

        if not bouquets:
            await message.answer("У вас пока нет сохраненных букетов.")
            return

        # Формируем сообщение со списком букетов
        response = "<b>Ваши букеты:</b>\n\n"
        for i, bouquet in enumerate(bouquets, 1):
            video_mark = " 🎬" if bouquet.video_path else ""
            response += f"{i}. {bouquet.title_display} - {format_price(bouquet.price_minor)}{video_mark}\n"

        # Создаем клавиатуру с кнопками для выбора букета
        builder = InlineKeyboardBuilder()
        for bouquet in bouquets:
            builder.add(types.InlineKeyboardButton(
                text=f"📝 {bouquet.short_title}",
                callback_data=f"bouquet_detail:{bouquet.bouquet_id}"
            ))

        # Добавляем кнопку возврата
        builder.add(types.InlineKeyboardButton(
            text="🔙 Назад",
            callback_data="back_to_menu"
        ))

        builder.adjust(1)  # По одной кнопке в ряд

        await message.answer(response, reply_markup=builder.as_markup())

    except Exception as e:
        logging.error(f"Ошибка в list_bouquets: {e}")
        await message.answer("Произошла ошибка при загрузке списка букетов.")
    finally:
        await session.close()


async def show_settings(message: types.Message):
    session = await get_db_session()
    try:
        user = await get_or_create_user(session, message.from_user.id)

        response = (
            f"<b>Настройки:</b>\n\n"
            f"Лимит фото: {user.media_limit}\n"
            f"Валюта: RUB\n"
            f"Язык: RU"
        )

        builder = InlineKeyboardBuilder()
        if user.media_limit == 6:
            builder.add(types.InlineKeyboardButton(
                text="Установить лимит 10 фото",
                callback_data="settings:media_limit:10"
            ))
        else:
            builder.add(types.InlineKeyboardButton(
                text="Установить лимит 6 фото",
                callback_data="settings:media_limit:6"
            ))

        await message.answer(response, reply_markup=builder.as_markup())
    except Exception as e:
        logging.error(f"Ошибка в show_settings: {e}")
        await message.answer("Произошла ошибка при загрузке настроек.")
    finally:
        await session.close()


async def show_bouquet_details(callback: types.CallbackQuery):
    try:
        bouquet_id = callback.data.split(":")[1]

        session = await get_db_session()
        try:
            bouquet = await get_bouquet_by_id(session, bouquet_id)
            if not bouquet:
                await callback.answer("Букет не найден")
                return

            # Формируем сообщение с деталями букета
            details_text = (
                f"<b>{bouquet.title_display}</b>\n\n"
                f"<b>Цена:</b> {format_price(bouquet.price_minor)}\n\n"
                f"<b>Описание:</b>\n{bouquet.description}\n\n"
            )

            if bouquet.composition:
                details_text += "<b>Состав:</b>\n"
                for item in bouquet.composition:
                    details_text += f"{item['raw_name']} - {item['qty']}\n"

            # Создаем клавиатуру с действиями
            builder = InlineKeyboardBuilder()
            builder.add(types.InlineKeyboardButton(
                text="✏️ Редактировать",
                callback_data=f"edit_bouquet:{bouquet_id}"
            ))
            builder.add(types.InlineKeyboardButton(
                text="🗑️ Удалить",
                callback_data=f"delete_bouquet:{bouquet_id}"
            ))
            builder.add(types.InlineKeyboardButton(
                text="◀️ Назад к списку",
                callback_data="bouquet_list:page:1"
            ))

            builder.adjust(1)  # По одной кнопке в ряд

            # Если есть фото, отправляем первое фото с описанием
            if bouquet.photos:
                await callback.message.answer_photo(
                    bouquet.photos[0],
                    caption=details_text,
                    reply_markup=builder.as_markup()
                )
            else:
                await callback.message.answer(
                    details_text,
                    reply_markup=builder.as_markup()
                )

        finally:
            await session.close()

    except Exception as e:
        logging.error(f"Ошибка в show_bouquet_details: {e}")
        await callback.answer("Произошла ошибка при загрузке деталей букета.")


async def handle_bouquet_pagination(callback: types.CallbackQuery):
    try:
        page = int(callback.data.split(":")[2])
        session = await get_db_session()
        try:
            user = await get_or_create_user(session, callback.from_user.id)
            bouquets = await get_user_bouquets(session, user.id, page=page)

            if not bouquets:
                await callback.answer("Нет букетов для отображения")
                return

            # Формируем сообщение со списком букетов
            response = f"<b>Ваши букеты (страница {page}):</b>\n\n"
            for i, bouquet in enumerate(bouquets, 1):
                video_mark = " 🎬" if bouquet.video_path else ""
                response += f"{i}. {bouquet.title_display} - {format_price(bouquet.price_minor)}{video_mark}\n"

            # Создаем клавиатуру с пагинацией и кнопками выбора
            builder = InlineKeyboardBuilder()

            # Кнопки для выбора букета
            for bouquet in bouquets:
                builder.add(types.InlineKeyboardButton(
                    text=bouquet.short_title,
                    callback_data=f"bouquet_detail:{bouquet.bouquet_id}"
                ))

            # Кнопки пагинации
            total = await count_user_bouquets(session, user.id)
            total_pages = (total + 9) // 10  # Округление вверх

            if total_pages > 1:
                pagination_builder = InlineKeyboardBuilder()
                if page > 1:
                    pagination_builder.add(types.InlineKeyboardButton(
                        text="◀️ Назад",
                        callback_data=f"bouquet_list:page:{page - 1}"
                    ))
                if page < total_pages:
                    pagination_builder.add(types.InlineKeyboardButton(
                        text="▶️ Вперед",
                        callback_data=f"bouquet_list:page:{page + 1}"
                    ))

                builder.adjust(1)  # По одной кнопке в ряд
                pagination_builder.adjust(2)  # По две кнопки в ряд для пагинации

                # Объединяем клавиатуры
                builder.attach(pagination_builder)

            await callback.message.edit_text(
                response,
                reply_markup=builder.as_markup()
            )

        finally:
            await session.close()

    except Exception as e:
        logging.error(f"Ошибка в handle_bouquet_pagination: {e}")
        await callback.answer("Произошла ошибка при загрузке списка букетов.")


async def start_edit_bouquet(callback: types.CallbackQuery, state: FSMContext):
    try:
        bouquet_id = callback.data.split(":")[1]

        session = await get_db_session()
        try:
            bouquet = await get_bouquet_by_id(session, bouquet_id)
            if not bouquet:
                await callback.answer("Букет не найден")
                return

            # Загружаем данные букета в состояние
            await state.update_data(
                editing_bouquet_id=bouquet_id,
                current_id=bouquet.bouquet_id,
                title=bouquet.short_title,
                media=bouquet.photos,
                video=bouquet.video_path,
                description=bouquet.description,
                composition=bouquet.composition,
                price=bouquet.price_minor // 100,  # Конвертируем обратно в рубли
                media_limit=10  # Устанавливаем лимит для редактирования
            )

            # Создаем клавиатуру для выбора поля для редактирования
            builder = InlineKeyboardBuilder()
            builder.add(types.InlineKeyboardButton(
                text="Название",
                callback_data="edit_field:title"
            ))
            builder.add(types.InlineKeyboardButton(
                text="Фото",
                callback_data="edit_field:media"
            ))
            builder.add(types.InlineKeyboardButton(
                text="Описание",
                callback_data="edit_field:description"
            ))
            builder.add(types.InlineKeyboardButton(
                text="Состав",
                callback_data="edit_field:composition"
            ))
            builder.add(types.InlineKeyboardButton(
                text="Цену",
                callback_data="edit_field:price"
            ))
            builder.add(types.InlineKeyboardButton(
                text="✅ Завершить редактирование",
                callback_data="edit_field:finish"
            ))

            await callback.message.answer(
                "Что вы хотите отредактировать?",
                reply_markup=builder.as_markup()
            )

        finally:
            await session.close()

    except Exception as e:
        logging.error(f"Ошибка в start_edit_bouquet: {e}")
        await callback.answer("Произошла ошибка при начале редактирования.")


async def handle_edit_field(callback: types.CallbackQuery, state: FSMContext):
    try:
        field = callback.data.split(":")[1]

        if field == "title":
            await callback.message.answer("Введите новое название букета (3-40 символов):")
            await state.set_state(BouquetStates.editing_title)

        elif field == "media":
            data = await state.get_data()
            await callback.message.answer(
                f"Пришлите новые фото (альбомом или по одному). Текущее количество: {len(data.get('media', []))}"
            )
            await state.set_state(BouquetStates.editing_media)

        elif field == "description":
            await callback.message.answer("Введите новое описание букета (до 800 символов):")
            await state.set_state(BouquetStates.editing_description)

        elif field == "composition":
            await callback.message.answer("Введите новый состав букета в формате: 'Розы - 3\nХризантемы - 5'")
            await state.set_state(BouquetStates.editing_composition)

        elif field == "price":
            await callback.message.answer("Введите новую цену букета (целое число):")
            await state.set_state(BouquetStates.editing_price)

        elif field == "finish":
            # Сохраняем изменения
            data = await state.get_data()
            bouquet_id = data.get('editing_bouquet_id')

            session = await get_db_session()
            try:
                # Загружаем медиа на сервер, если есть новые фото
                uploaded_media = data.get('media', [])
                if uploaded_media and isinstance(uploaded_media[0], str) and not uploaded_media[0].startswith('http'):
                    uploaded_media = await handle_media_upload(callback.bot, uploaded_media, data['current_id'])

                # Загружаем видео на сервер, если есть новое видео
                video_url = data.get('video')
                if video_url and not video_url.startswith('http'):
                    video_url = await upload_video_to_storage(callback.bot, video_url, data['current_id'])

                update_data = {
                    "short_title": data.get('title'),
                    "title_display": f"{data.get('title')} №{data.get('current_id')}",
                    "photos": uploaded_media,
                    "video_path": video_url,
                    "description": data.get('description'),
                    "composition": data.get('composition'),
                    "price_minor": data.get('price', 0) * 100
                }

                bouquet = await update_bouquet(session, bouquet_id, update_data)
                await callback.message.answer(f"Букет {bouquet.title_display} успешно обновлен!")

                await state.clear()

            except Exception as e:
                logging.error(f"Ошибка при обновлении букета: {e}")
                await callback.message.answer("Произошла ошибка при сохранении изменений.")
            finally:
                await session.close()

    except Exception as e:
        logging.error(f"Ошибка в handle_edit_field: {e}")
        await callback.answer("Произошла ошибка при редактировании.")


async def handle_delete_bouquet(callback: types.CallbackQuery):
    try:
        bouquet_id = callback.data.split(":")[1]

        session = await get_db_session()
        try:
            success = await delete_bouquet(session, bouquet_id)
            if success:
                await callback.message.answer("Букет успешно удален!")
            else:
                await callback.message.answer("Не удалось удалить букет.")

        finally:
            await session.close()

    except Exception as e:
        logging.error(f"Ошибка в handle_delete_bouquet: {e}")
        await callback.answer("Произошла ошибка при удалении букета.")


async def handle_back_to_menu(callback: types.CallbackQuery, state: FSMContext):
    """Обработчик кнопки возврата в меню"""
    try:
        from photo_catalog import cmd_start
        await state.clear()
        await cmd_start(callback.message)
        await callback.answer()
    except Exception as e:
        logging.error(f"Ошибка в handle_back_to_menu: {e}")
        await callback.answer("Произошла ошибка при возврате в меню.")


async def handle_actions(callback: types.CallbackQuery, state: FSMContext):
    try:
        action = callback.data.split(":")[1]

        if action == "next_step":
            data = await state.get_data()
            current_state = await state.get_state()

            logging.info(f"Переход к следующему шагу. Текущее состояние: {current_state}")

            if current_state == BouquetStates.waiting_title.state:
                # Переход к загрузке медиа
                limit = data.get('media_limit', 6)

                builder = InlineKeyboardBuilder()
                builder.add(types.InlineKeyboardButton(
                    text="Добавить видео",
                    callback_data="action:add_video")
                )
                builder.add(types.InlineKeyboardButton(
                    text="Готово",
                    callback_data="action:media_done")
                )

                await callback.message.answer(
                    f"Пришлите 1-{limit} фото (альбомом или по одному)\n"
                    "Видео можно добавить отдельной кнопкой",
                    reply_markup=builder.as_markup()
                )
                await state.set_state(BouquetStates.waiting_media)
                logging.info("Состояние установлено: waiting_media")

            elif current_state == BouquetStates.waiting_media.state:
                # Проверка минимального количества фото
                if 'media' not in data or len(data['media']) == 0:
                    await callback.answer("Нужно хотя бы одно фото")
                    return

                await callback.message.answer("Введите описание букета (до 800 символов):")
                await state.set_state(BouquetStates.waiting_description)

            elif current_state == BouquetStates.waiting_composition.state:
                await callback.message.answer("Введите цену букета (целое число):")
                await state.set_state(BouquetStates.waiting_price)

        elif action == "media_done":
            # Проверка минимального количества фото
            data = await state.get_data()
            if 'media' not in data or len(data['media']) == 0:
                await callback.answer("Нужно хотя бы одно фото")
                return

            await callback.message.answer("Введите описание букета (до 800 символов):")
            await state.set_state(BouquetStates.waiting_description)

        elif action == "skip_composition":
            await callback.message.answer("Введите цену букета (целое число):")
            await state.set_state(BouquetStates.waiting_price)

        elif action == "save_bouquet":
            data = await state.get_data()

            # Проверка наличия обязательных полей
            if "current_id" not in data:
                logging.error("Ошибка: current_id не найден в состоянии")
                await callback.message.answer("Ошибка: не найден идентификатор букета. Начните заново.")
                await state.clear()
                return

            # Загружаем медиа на сервер
            uploaded_media = await handle_media_upload(callback.bot, data.get('media', []), data['current_id'])

            # Если есть видео, загружаем его тоже
            video_url = None
            if 'video' in data:
                video_url = await upload_video_to_storage(callback.bot, data['video'], data['current_id'])

            session = await get_db_session()
            try:
                bouquet_data = {
                    "bouquet_id": data["current_id"],
                    "user_id": data["user_id"],
                    "short_title": data["title"],
                    "title_display": f"{data['title']} №{data['current_id']}",
                    "photos": uploaded_media,  # Используем URL вместо file_id
                    "video_path": video_url,  # Используем URL вместо file_id
                    "description": data["description"],
                    "composition": data.get("composition"),
                    "price_minor": data["price"] * 100  # Конвертируем в копейки
                }

                bouquet = await create_bouquet(session, bouquet_data)
                await callback.message.answer(f"Букет {bouquet.title_display} сохранен!")

                await state.clear()
            except Exception as e:
                logging.error(f"Ошибка при сохранении букета: {e}")
                await callback.message.answer("Произошла ошибка при сохранении букета. Попробуйте еще раз.")
            finally:
                await session.close()

    except Exception as e:
        logging.error(f"Ошибка в handle_actions: {e}")
        await callback.answer("Произошла ошибка. Попробуйте еще раз.")


async def handle_settings(callback: types.CallbackQuery):
    try:
        setting_type = callback.data.split(":")[1]
        value = callback.data.split(":")[2]

        if setting_type == "media_limit":
            session = await get_db_session()
            try:
                user = await get_or_create_user(session, callback.from_user.id)
                user.media_limit = int(value)
                await session.commit()

                await callback.message.answer(f"Лимит фото изменен на {value}")
            finally:
                await session.close()

        await callback.answer()
    except Exception as e:
        logging.error(f"Ошибка в handle_settings: {e}")
        await callback.answer("Произошла ошибка при изменении настроек.")


# Функция регистрации обработчиков
def setup_handlers(dp: Dispatcher):
    # Обработчики для добавления букета
    dp.message.register(start_new_bouquet, F.text == "➕ Добавить букет")
    dp.message.register(process_title, BouquetStates.waiting_title)
    dp.message.register(handle_photos, BouquetStates.waiting_media, F.photo)
    dp.message.register(handle_documents, BouquetStates.waiting_media, F.document)
    dp.message.register(process_description, BouquetStates.waiting_description)
    dp.message.register(process_composition, BouquetStates.waiting_composition)
    dp.message.register(process_price, BouquetStates.waiting_price)

    # Обработчики для списка букетов
    dp.message.register(list_bouquets, F.text == "📚 Мои букеты")

    # Обработчики для настроек
    dp.message.register(show_settings, F.text == "⚙️ Настройки")

    # Обработчики колбэков
    dp.callback_query.register(handle_actions, F.data.startswith("action:"))
    dp.callback_query.register(handle_bouquet_pagination, F.data.startswith("bouquet_list:page:"))
    dp.callback_query.register(show_bouquet_details, F.data.startswith("bouquet_detail:"))
    dp.callback_query.register(start_edit_bouquet, F.data.startswith("edit_bouquet:"))
    dp.callback_query.register(handle_edit_field, F.data.startswith("edit_field:"))
    dp.callback_query.register(handle_delete_bouquet, F.data.startswith("delete_bouquet:"))
    dp.callback_query.register(handle_settings, F.data.startswith("settings:"))
    dp.callback_query.register(handle_back_to_menu, F.data == "back_to_menu")

    # Обработчики для состояний редактирования
    dp.message.register(process_title, BouquetStates.editing_title)
    dp.message.register(handle_photos, BouquetStates.editing_media, F.photo)
    dp.message.register(handle_documents, BouquetStates.editing_media, F.document)
    dp.message.register(process_description, BouquetStates.editing_description)
    dp.message.register(process_composition, BouquetStates.editing_composition)
    dp.message.register(process_price, BouquetStates.editing_price)