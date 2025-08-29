from aiogram import types
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import select
import logging

from states import BouquetStates
from database import get_db_session, get_or_create_user, create_bouquet, Bouquet
from utils import parse_composition, format_price
from .common import handle_media_upload
from storage import upload_video_to_storage

# ---------- Старт ----------

async def start_new_bouquet(message: types.Message, state: FSMContext):
    await state.clear()
    session = await get_db_session()
    try:
        user = await get_or_create_user(session, message.from_user.id)
        await state.update_data(chat_id=message.chat.id)

        # генерим следующий номер
        res = await session.execute(select(Bouquet).order_by(Bouquet.id.desc()).limit(1))
        last = res.scalar_one_or_none()
        try:
            last_num = int(last.bouquet_id) if last and last.bouquet_id.isdigit() else 200
        except Exception:
            last_num = 200
        bouquet_id = f"{last_num + 1:04d}"

        await state.update_data(
            current_id=bouquet_id,
            user_id=user.id,
            media=[],
            media_limit=user.media_limit,
            composition=[],
            video=None,
        )
        await message.answer("Введите краткое название букета (3–40 символов):")
        await state.set_state(BouquetStates.waiting_title)
    except Exception as e:
        logging.error(f"start_new_bouquet error: {e}", exc_info=True)
        await message.answer("Ошибка при создании букета. Попробуйте ещё раз.")
    finally:
        await session.close()

# ---------- Название ----------

async def process_title(message: types.Message, state: FSMContext):
    try:
        title = (message.text or "").strip()
        if not (3 <= len(title) <= 40):
            await message.answer("Название должно быть от 3 до 40 символов.")
            return

        data = await state.get_data()
        await state.update_data(title=title)

        kb = InlineKeyboardBuilder()
        kb.add(types.InlineKeyboardButton(text="Дальше", callback_data="action:next_step"))
        kb.add(types.InlineKeyboardButton(text="Изменить название", callback_data="action:change_title"))

        await message.answer(f"Название принято: {title} №{data['current_id']}", reply_markup=kb.as_markup())
    except Exception as e:
        logging.error(f"process_title error: {e}", exc_info=True)
        await message.answer("Не удалось обработать название. Попробуйте ещё раз.")

# ---------- Описание ----------

async def process_description(message: types.Message, state: FSMContext):
    try:
        desc = (message.text or "").strip()
        if len(desc) > 800:
            await message.answer("Описание слишком длинное (до 800 символов).")
            return

        await state.update_data(description=desc)

        kb = InlineKeyboardBuilder()
        kb.add(types.InlineKeyboardButton(text="Пропустить", callback_data="action:skip_composition"))
        kb.add(types.InlineKeyboardButton(text="Указать состав", callback_data="action:add_composition"))

        await message.answer("Хотите указать состав букета?", reply_markup=kb.as_markup())
        await state.set_state(BouquetStates.waiting_composition)
    except Exception as e:
        logging.error(f"process_description error: {e}", exc_info=True)
        await message.answer("Не удалось сохранить описание. Попробуйте ещё раз.")

# ---------- Текстовый ввод состава (фолбэк) ----------

async def process_composition(message: types.Message, state: FSMContext):
    try:
        composition = parse_composition(message.text or "")
        if not composition:
            await message.answer("Не удалось распознать состав. Пример: «Розы - 3»")
            return

        await state.update_data(composition=composition)

        kb = InlineKeyboardBuilder()
        kb.add(types.InlineKeyboardButton(text="Дальше", callback_data="action:next_step"))

        await message.answer("Состав сохранён. Переходим к цене.", reply_markup=kb.as_markup())
        await state.set_state(BouquetStates.waiting_price)
    except Exception as e:
        logging.error(f"process_composition error: {e}", exc_info=True)
        await message.answer("Ошибка при обработке состава. Попробуйте ещё раз.")

# ---------- Цена / предпросмотр ----------

async def process_price(message: types.Message, state: FSMContext):
    try:
        txt = (message.text or "").strip()
        if not txt.isdigit() or not (1 <= int(txt) <= 999999):
            await message.answer("Введите корректную цену (целое число от 1 до 999999).")
            return

        price = int(txt)
        await state.update_data(price=price)

        data = await state.get_data()
        preview = (
            f"<b>{data.get('title','')} №{data.get('current_id')}</b>\n\n"
            f"<b>Цена:</b> {format_price(price * 100)}\n\n"
            f"<b>Описание:</b>\n{data.get('description','')}\n\n"
        )

        comp = data.get("composition") or []
        if comp:
            preview += "<b>Состав:</b>\n"
            for item in comp:
                preview += f"• {item.get('raw_name','')} — {item.get('qty','')}\n"

        kb = InlineKeyboardBuilder()
        kb.add(types.InlineKeyboardButton(text="💾 Сохранить", callback_data="action:save_bouquet"))
        kb.add(types.InlineKeyboardButton(text="✏️ Изменить", callback_data="action:edit_bouquet"))

        await message.answer(preview, reply_markup=kb.as_markup())
    except Exception as e:
        logging.error(f"process_price error: {e}", exc_info=True)
        await message.answer("Не удалось обработать цену. Попробуйте ещё раз.")

# ---------- Переходы / сохранение ----------

async def handle_actions(callback: types.CallbackQuery, state: FSMContext):
    try:
        action = (callback.data or "").split(":")[1]

        if action == "next_step":
            current = await state.get_state()
            if current == BouquetStates.waiting_title.state:
                data = await state.get_data()
                limit = data.get("media_limit", 6)

                kb = InlineKeyboardBuilder()
                kb.add(types.InlineKeyboardButton(text="Добавить видео", callback_data="action:add_video"))
                kb.add(types.InlineKeyboardButton(text="Готово", callback_data="action:media_done"))

                await callback.message.edit_text(
                    f"Отлично! Теперь пришлите 1–{limit} фото для букета\n"
                    "📌 Для максимального качества отправляйте файлы как <b>Документы</b>\n"
                    "🎥 Видео можно добавить отдельной кнопкой",
                    reply_markup=kb.as_markup()
                )
                await state.set_state(BouquetStates.waiting_media)
                await callback.answer()
                return

            if current in (BouquetStates.waiting_description.state, BouquetStates.waiting_composition.state):
                await state.set_state(BouquetStates.waiting_price)
                await callback.message.edit_text("Введите цену (целое число):")
                await callback.answer()
                return

        elif action == "change_title":
            await state.set_state(BouquetStates.waiting_title)
            await callback.message.edit_text("Введите новое название:")
            await callback.answer()
            return

        elif action == "add_video":
            from .media_processing import handle_add_video
            await handle_add_video(callback, state)
            return

        elif action == "media_done":
            from .media_processing import handle_media_done
            await handle_media_done(callback, state)
            return

        elif action == "skip_composition":
            await state.set_state(BouquetStates.waiting_price)
            await callback.message.edit_text("Введите цену (целое число):")
            await callback.answer()
            return

        elif action == "add_composition":
            # старт интерактивного выбора из каталога
            from .composition_picker import show_category_page
            await show_category_page(callback.message.chat.id, state, callback.bot, page=1)
            await state.set_state(BouquetStates.choosing_category)
            await callback.answer()
            return

        elif action == "save_bouquet":
            data = await state.get_data()
            session = await get_db_session()
            try:
                media = data.get("media", [])
                if media and isinstance(media[0], str) and not media[0].startswith("http"):
                    media = await handle_media_upload(callback.bot, media, data["current_id"])

                video_url = data.get("video")
                if video_url and not str(video_url).startswith("http"):
                    video_url = await upload_video_to_storage(callback.bot, video_url, data["current_id"])

                bouquet = await create_bouquet(session, {
                    "bouquet_id": data["current_id"],
                    "user_id": data["user_id"],
                    "short_title": data.get("title"),
                    "title_display": f"{data.get('title')} №{data.get('current_id')}",
                    "photos": media,
                    "video_path": video_url,
                    "description": data.get("description", ""),
                    "composition": data.get("composition", []),
                    "price_minor": (data.get("price", 0) or 0) * 100,
                })
                await callback.message.answer(f"Букет «{bouquet.title_display}» сохранён!")
                await state.clear()
            except Exception as e:
                logging.error(f"save_bouquet error: {e}", exc_info=True)
                await callback.message.answer("Ошибка при сохранении букета. Попробуйте ещё раз.")
            finally:
                await session.close()
            await callback.answer()
            return

        elif action == "edit_bouquet":
            await state.set_state(BouquetStates.waiting_price)
            await callback.message.edit_text("Введите новую цену (целое число):")
            await callback.answer()
            return

    except Exception as e:
        logging.error(f"handle_actions error: {e}", exc_info=True)
        try:
            await callback.answer("Произошла ошибка. Попробуйте ещё раз.")
        except Exception:
            pass
