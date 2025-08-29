import math
import logging
from aiogram import types
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import select, delete

from states import BouquetStates
from database import get_db_session, get_or_create_user, Bouquet
from utils import format_price


PAGE_SIZE = 5


# ===== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ МЕДИА =====

def _extract_media_ref(item) -> str | None:
    """
    Привести элемент photos к строке для aiogram:
      - если dict: сначала берём file_id, затем url
      - если str: возвращаем как есть (подходит и file_id, и https://)
    """
    if item is None:
        return None
    if isinstance(item, dict):
        v = item.get("file_id") or item.get("tg_file_id") or item.get("telegram_file_id") or item.get("url")
        if isinstance(v, str) and v.strip():
            return v.strip()
        return None
    if isinstance(item, str) and item.strip():
        return item.strip()
    return None


def _first_media(bouquet: Bouquet) -> str | None:
    photos = getattr(bouquet, "photos", None)
    if not photos:
        return None
    if isinstance(photos, list):
        for it in photos:
            ref = _extract_media_ref(it)
            if ref:
                return ref
        return None
    return _extract_media_ref(photos)


def _composition_text(comp) -> str:
    """Свести состав к читабельному тексту."""
    if not comp:
        return "—"
    try:
        if isinstance(comp, list):
            parts = []
            for it in comp:
                if isinstance(it, dict):
                    name = (it.get("raw_name") or it.get("name") or "").strip()
                    qty = it.get("qty")
                    if name:
                        parts.append(f"• {name}{f' — {qty}' if qty else ''}")
                else:
                    parts.append(f"• {it}")
            return "\n".join(parts) if parts else "—"
        return str(comp)
    except Exception:
        return "—"


def _price_text(price_minor: int | None, currency: str | None) -> str:
    try:
        return format_price((price_minor or 0)) if hasattr(format_price, "__call__") else f"{(price_minor or 0) / 100:.0f} {currency or 'RUB'}"
    except Exception:
        rub = (price_minor or 0) / 100
        return f"{rub:.0f} {currency or 'RUB'}"


def _details_caption(b: Bouquet) -> str:
    return (
        f"<b>{b.title_display or b.short_title or 'Букет'}</b>\n\n"
        f"<b>Цена:</b> {_price_text(b.price_minor, b.currency)}\n"
        f"<b>Описание:</b>\n{(b.description or '—')}\n\n"
        f"<b>Состав:</b>\n{_composition_text(b.composition)}"
    )


def _detail_keyboard(bouquet_id: str, page: int | None = None) -> types.InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.add(types.InlineKeyboardButton(text="✏️ Редактировать", callback_data=f"edit_bouquet:{bouquet_id}"))
    kb.add(types.InlineKeyboardButton(text="🗑 Удалить", callback_data=f"delete_bouquet:{bouquet_id}"))
    if page is not None:
        kb.add(types.InlineKeyboardButton(text="◀️ Назад к списку", callback_data=f"back_to_list:{page}"))
    else:
        kb.add(types.InlineKeyboardButton(text="◀️ Назад к списку", callback_data="back_to_list"))
    kb.adjust(2)
    return kb.as_markup()


def _list_keyboard(items, page: int, total_pages: int) -> types.InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for b in items:
        kb.add(types.InlineKeyboardButton(
            text=f"#{b.bouquet_id} {b.short_title or b.title_display}",
            callback_data=f"bouquet_detail:{b.bouquet_id}:{page}"
        ))
    # навигация
    nav = InlineKeyboardBuilder()
    if page > 1:
        nav.add(types.InlineKeyboardButton(text="⬅️", callback_data=f"bouquet_list:page:{page-1}"))
    if page < total_pages:
        nav.add(types.InlineKeyboardButton(text="➡️", callback_data=f"bouquet_list:page:{page+1}"))
    nav.adjust(2)
    kb.attach(nav)
    return kb.as_markup()


# ===== СПИСОК БУКЕТОВ =====

async def list_bouquets(message: types.Message):
    """Показать список букетов текущего пользователя (постранично)."""
    session = await get_db_session()
    try:
        user = await get_or_create_user(session, message.from_user.id)

        # Подтягиваем только свои букеты
        res = await session.execute(
            select(Bouquet)
            .where(Bouquet.user_id == user.id)
            .order_by(Bouquet.created_at.desc())
        )
        all_bouquets = res.scalars().all()
        if not all_bouquets:
            await message.answer("У вас пока нет букетов. Нажмите «➕ Добавить букет».")
            return

        total = len(all_bouquets)
        total_pages = max(1, math.ceil(total / PAGE_SIZE))
        page = 1
        start = (page - 1) * PAGE_SIZE
        items = all_bouquets[start:start + PAGE_SIZE]

        text = f"📚 Ваши букеты ({total}): страница {page}/{total_pages}"
        await message.answer(text, reply_markup=_list_keyboard(items, page, total_pages))
    except Exception as e:
        logging.error(f"list_bouquets error: {e}", exc_info=True)
        await message.answer("Не удалось загрузить список букетов.")
    finally:
        await session.close()


async def handle_bouquet_pagination(callback: types.CallbackQuery):
    """Переключение страниц списка."""
    try:
        page = int(callback.data.split(":")[2])
    except Exception:
        page = 1

    session = await get_db_session()
    try:
        user = await get_or_create_user(session, callback.from_user.id)
        res = await session.execute(
            select(Bouquet)
            .where(Bouquet.user_id == user.id)
            .order_by(Bouquet.created_at.desc())
        )
        all_bouquets = res.scalars().all()
        if not all_bouquets:
            await callback.message.edit_text("Букетов пока нет.")
            await callback.answer()
            return

        total = len(all_bouquets)
        total_pages = max(1, math.ceil(total / PAGE_SIZE))
        page = max(1, min(page, total_pages))
        start = (page - 1) * PAGE_SIZE
        items = all_bouquets[start:start + PAGE_SIZE]

        text = f"📚 Ваши букеты ({total}): страница {page}/{total_pages}"
        await callback.message.edit_text(text, reply_markup=_list_keyboard(items, page, total_pages))
        await callback.answer()
    except Exception as e:
        logging.error(f"handle_bouquet_pagination error: {e}", exc_info=True)
        try:
            await callback.answer("Ошибка пагинации.")
        except Exception:
            pass
    finally:
        await session.close()


# ===== ДЕТАЛИ БУКЕТА =====

async def show_bouquet_details(callback: types.CallbackQuery):
    """Показать детальную карточку букета с фото (если есть)."""
    try:
        parts = (callback.data or "").split(":")
        bouquet_id = parts[1] if len(parts) > 1 else ""
        page = int(parts[2]) if len(parts) > 2 else None
    except Exception:
        bouquet_id = ""
        page = None

    session = await get_db_session()
    try:
        res = await session.execute(select(Bouquet).where(Bouquet.bouquet_id == bouquet_id))
        b = res.scalar_one_or_none()
        if not b:
            await callback.message.answer("Букет не найден (возможно, удалён).")
            await callback.answer()
            return

        caption = _details_caption(b)
        media_ref = _first_media(b)

        if media_ref:
            await callback.message.answer_photo(
                photo=media_ref,  # <-- здесь теперь СТРОКА (file_id или URL), не dict
                caption=caption,
                parse_mode="HTML",
                reply_markup=_detail_keyboard(b.bouquet_id, page)
            )
        else:
            await callback.message.answer(
                caption,
                parse_mode="HTML",
                reply_markup=_detail_keyboard(b.bouquet_id, page)
            )

        await callback.answer()
    except Exception as e:
        logging.error(f"Ошибка в show_bouquet_details: {e}", exc_info=True)
        try:
            await callback.answer("Не удалось показать детали букета.")
        except Exception:
            pass
    finally:
        await session.close()


# ===== РЕДАКТИРОВАНИЕ / УДАЛЕНИЕ =====

async def start_edit_bouquet(callback: types.CallbackQuery, state: FSMContext):
    """Показать меню выбора поля для редактирования."""
    try:
        bouquet_id = (callback.data or "").split(":")[1]
    except Exception:
        await callback.answer("Ошибка.")
        return

    kb = InlineKeyboardBuilder()
    kb.add(types.InlineKeyboardButton(text="Название", callback_data=f"edit_field:title:{bouquet_id}"))
    kb.add(types.InlineKeyboardButton(text="Описание", callback_data=f"edit_field:description:{bouquet_id}"))
    kb.add(types.InlineKeyboardButton(text="Состав", callback_data=f"edit_field:composition:{bouquet_id}"))
    kb.add(types.InlineKeyboardButton(text="Цена", callback_data=f"edit_field:price:{bouquet_id}"))
    kb.add(types.InlineKeyboardButton(text="◀️ Назад", callback_data=f"bouquet_detail:{bouquet_id}"))
    kb.adjust(2)

    await callback.message.answer("Что редактируем?", reply_markup=kb.as_markup())
    await callback.answer()


async def handle_edit_field(callback: types.CallbackQuery, state: FSMContext):
    """
    Переводит в нужное состояние редактирования.
    Дальше ввод обрабатывают общие хендлеры:
      - editing_title → process_title
      - editing_description → process_description
      - editing_composition → process_composition
      - editing_price → process_price
    """
    try:
        _, field, bouquet_id = (callback.data or "").split(":")
    except Exception:
        await callback.answer("Ошибка.")
        return

    await state.update_data(edit_bouquet_id=bouquet_id)

    if field == "title":
        await state.set_state(BouquetStates.editing_title)
        await callback.message.answer("Введите новое название:")
    elif field == "description":
        await state.set_state(BouquetStates.editing_description)
        await callback.message.answer("Введите новое описание:")
    elif field == "composition":
        await state.set_state(BouquetStates.editing_composition)
        await callback.message.answer("Введите состав (или воспользуйтесь мастером добавления в новом букете):")
    elif field == "price":
        await state.set_state(BouquetStates.editing_price)
        await callback.message.answer("Введите новую цену (целое число):")
    else:
        await callback.message.answer("Неизвестное поле.")
    await callback.answer()


async def handle_delete_bouquet(callback: types.CallbackQuery):
    """Удалить букет без подтверждения (можно добавить подтверждение по желанию)."""
    try:
        bouquet_id = (callback.data or "").split(":")[1]
    except Exception:
        await callback.answer("Ошибка.")
        return

    session = await get_db_session()
    try:
        await session.execute(delete(Bouquet).where(Bouquet.bouquet_id == bouquet_id))
        await session.commit()
        await callback.message.answer(f"Букет #{bouquet_id} удалён.")
        await callback.answer()
    except Exception as e:
        logging.error(f"handle_delete_bouquet error: {e}", exc_info=True)
        try:
            await callback.answer("Не удалось удалить букет.")
        except Exception:
            pass
    finally:
        await session.close()


async def handle_back_to_list(callback: types.CallbackQuery):
    """Возврат к списку (если передавали страницу — вернёмся к ней)."""
    try:
        parts = (callback.data or "").split(":")
        page = int(parts[1]) if len(parts) > 1 else 1
    except Exception:
        page = 1

    session = await get_db_session()
    try:
        user = await get_or_create_user(session, callback.from_user.id)
        res = await session.execute(
            select(Bouquet)
            .where(Bouquet.user_id == user.id)
            .order_by(Bouquet.created_at.desc())
        )
        all_bouquets = res.scalars().all()
        if not all_bouquets:
            await callback.message.edit_text("Букетов пока нет.")
            await callback.answer()
            return

        total = len(all_bouquets)
        total_pages = max(1, math.ceil(total / PAGE_SIZE))
        page = max(1, min(page, total_pages))
        start = (page - 1) * PAGE_SIZE
        items = all_bouquets[start:start + PAGE_SIZE]

        text = f"📚 Ваши букеты ({total}): страница {page}/{total_pages}"
        await callback.message.edit_text(text, reply_markup=_list_keyboard(items, page, total_pages))
        await callback.answer()
    except Exception as e:
        logging.error(f"handle_back_to_list error: {e}", exc_info=True)
        try:
            await callback.answer("Ошибка.")
        except Exception:
            pass
    finally:
        await session.close()
