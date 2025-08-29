from aiogram import types
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder
import logging
from states import BouquetStates
from ai_service import deepseek_service


async def start_ai_generation(message: types.Message, state: FSMContext):
    """Начало процесса генерации через AI"""
    await state.set_state(BouquetStates.waiting_ai_keywords)
    await message.answer(
        "🤖 Опишите букет ключевыми словами\n\n"
        "Примеры:\n"
        "• красные розы, романтика, день рождения\n"
        "• весенние цветы, нежность, тюльпаны\n"
        "• белые лилии, элегантность, свадьба\n\n"
        "Опишите ваш букет:"
    )


async def process_ai_keywords(message: types.Message, state: FSMContext):
    """Обработка ключевых слов и генерация вариантов через AI"""
    keywords = message.text
    await state.update_data(ai_keywords=keywords)

    # Показываем сообщение о начале генерации
    processing_msg = await message.answer("🔄 Генерирую варианты...")

    # Генерируем варианты через AI
    options = await deepseek_service.generate_bouquet_options(keywords)

    # Сохраняем варианты в состоянии
    await state.update_data(ai_options=options, current_ai_page=0)

    # Удаляем сообщение о обработке
    await processing_msg.delete()

    # Проверяем, есть ли варианты
    if not options:
        await message.answer(
            "Не удалось сгенерировать варианты. Попробуйте другие ключевые слова или "
            "создайте букет вручную через меню '➕ Добавить букет'."
        )
        await state.clear()
        return

    # Показываем первый вариант
    await show_ai_options(message.chat.id, state, message.bot, page=0)


async def show_ai_options(chat_id, state, bot, page=0):
    """Показывает варианты AI с пагинацией"""
    data = await state.get_data()
    options = data.get('ai_options', [])

    if not options:
        await bot.send_message(chat_id, "Не удалось сгенерировать варианты. Попробуйте другие ключевые слова.")
        await state.set_state(BouquetStates.waiting_ai_keywords)
        return

    # Ограничиваем страницы
    total_pages = (len(options) + 2) // 3  # 3 варианта на страницу
    current_page = min(max(page, 0), total_pages - 1)

    # Получаем варианты для текущей страницы
    start_idx = current_page * 3
    end_idx = min(start_idx + 3, len(options))
    page_options = options[start_idx:end_idx]

    # Формируем сообщение
    message_text = "🤖 AI сгенерировал для вас варианты:\n\n"

    for i, option in enumerate(page_options, start=1):
        message_text += f"{start_idx + i}. **{option['title']}**\n"
        message_text += f"   {option['description']}\n\n"

    message_text += f"Страница {current_page + 1} из {total_pages}"

    # Добавляем предупреждение, если используется фолбэк
    if not deepseek_service.api_key:
        message_text += "\n\n⚠️ *Режим демонстрации*: используйте настоящий API-ключ для лучших результатов"

    # Создаем клавиатуру
    builder = InlineKeyboardBuilder()

    # Кнопки для выбора вариантов
    for i, option in enumerate(page_options, start=1):
        builder.add(types.InlineKeyboardButton(
            text=f"✅ {start_idx + i}",
            callback_data=f"ai_select:{start_idx + i - 1}"
        ))

    builder.adjust(3)  # 3 кнопки в ряд

    # Кнопки навигации
    nav_builder = InlineKeyboardBuilder()
    if current_page > 0:
        nav_builder.add(types.InlineKeyboardButton(
            text="⬅️ Назад",
            callback_data=f"ai_page:{current_page - 1}"
        ))

    if current_page < total_pages - 1:
        nav_builder.add(types.InlineKeyboardButton(
            text="Вперед ➡️",
            callback_data=f"ai_page:{current_page + 1}"
        ))

    nav_builder.adjust(2)

    # Кнопки действий
    action_builder = InlineKeyboardBuilder()
    action_builder.add(types.InlineKeyboardButton(
        text="🔄 Новые варианты",
        callback_data="ai_regenerate"
    ))
    action_builder.add(types.InlineKeyboardButton(
        text="❌ Отмена",
        callback_data="ai_cancel"
    ))
    action_builder.adjust(2)

    # Объединяем все клавиатуры
    builder.attach(nav_builder)
    builder.attach(action_builder)

    # Отправляем сообщение
    await bot.send_message(
        chat_id,
        message_text,
        reply_markup=builder.as_markup(),
        parse_mode="Markdown"
    )

    # Обновляем состояние
    await state.set_state(BouquetStates.waiting_ai_selection)
    await state.update_data(current_ai_page=current_page)


async def handle_ai_selection(callback: types.CallbackQuery, state: FSMContext):
    """Обработка выбора варианта AI"""
    action = callback.data

    if action.startswith("ai_select:"):
        option_index = int(action.split(":")[1])
        data = await state.get_data()
        options = data.get('ai_options', [])

        if 0 <= option_index < len(options):
            selected_option = options[option_index]

            # Сохраняем выбранный вариант
            await state.update_data(
                title=selected_option['title'],
                description=selected_option['description'],
                ai_selected=True
            )

            # Показываем подтверждение
            builder = InlineKeyboardBuilder()
            builder.add(types.InlineKeyboardButton(
                text="✅ Продолжить создание",
                callback_data="ai_confirm"
            ))
            builder.add(types.InlineKeyboardButton(
                text="✏️ Редактировать описание",
                callback_data="ai_edit"
            ))
            builder.add(types.InlineKeyboardButton(
                text="❌ Отмена",
                callback_data="ai_cancel"
            ))
            builder.adjust(1)

            await callback.message.edit_text(
                f"Вы выбрали:\n\n"
                f"**{selected_option['title']}**\n"
                f"{selected_option['description']}\n\n"
                f"Хотите продолжить с этим вариантом?",
                reply_markup=builder.as_markup(),
                parse_mode="Markdown"
            )

    elif action.startswith("ai_page:"):
        page = int(action.split(":")[1])
        await show_ai_options(callback.message.chat.id, state, callback.bot, page)
        await callback.answer()

    elif action == "ai_regenerate":
        await callback.message.edit_text("🔄 Генерирую новые варианты...")
        data = await state.get_data()
        keywords = data.get('ai_keywords', '')
        options = await deepseek_service.generate_bouquet_options(keywords)
        await state.update_data(ai_options=options, current_ai_page=0)
        await show_ai_options(callback.message.chat.id, state, callback.bot, 0)
        await callback.answer()

    elif action == "ai_cancel":
        await state.set_state(None)
        await callback.message.edit_text("Создание букета отменено.")
        await callback.answer()


async def handle_ai_confirmation(callback: types.CallbackQuery, state: FSMContext):
    """Обработка подтверждения выбора AI"""
    action = callback.data

    if action == "ai_confirm":
        data = await state.get_data()

        # Переходим к загрузке медиа
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

        await callback.message.edit_text(
            f"Отлично! Теперь пришлите 1-{limit} фото для букета\n"
            "📌 Для максимального качества отправляйте файлы как Документы\n"
            "🎥 Видео можно добавить отдельной кнопкой",
            reply_markup=builder.as_markup()
        )
        await state.set_state(BouquetStates.waiting_media)
        await callback.answer()

    elif action == "ai_edit":
        await callback.message.edit_text(
            "Введите новое описание для букета:"
        )
        await state.set_state(BouquetStates.waiting_description)
        await callback.answer()

    elif action == "ai_cancel":
        await state.set_state(None)
        await callback.message.edit_text("Создание букета отменено.")
        await callback.answer()