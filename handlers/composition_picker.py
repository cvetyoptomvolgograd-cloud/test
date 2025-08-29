from aiogram import types
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import select
import logging
import math

from states import BouquetStates
from database import get_db_session, Category, Product


PAGE_SIZE = 6


# ---------- Витрина категорий ----------

async def show_category_page(chat_id: int, state: FSMContext, bot, page: int = 1):
    session = await get_db_session()
    try:
        result = await session.execute(select(Category).order_by(Category.name.asc()))
        categories = result.scalars().all()

        if not categories:
            await bot.send_message(chat_id, "Категории пусты. Сначала заполните каталог в ⚙️ Настройках.")
            return

        total_pages = max(1, math.ceil(len(categories) / PAGE_SIZE))
        page = max(1, min(page, total_pages))
        start = (page - 1) * PAGE_SIZE
        chunk = categories[start:start + PAGE_SIZE]

        kb = InlineKeyboardBuilder()
        for cat in chunk:
            kb.add(types.InlineKeyboardButton(text=f"📁 {cat.name}", callback_data=f"cat_select:{cat.id}:{page}"))

        # Навигация
        nav = InlineKeyboardBuilder()
        if page > 1:
            nav.add(types.InlineKeyboardButton(text="⬅️", callback_data=f"cat_page:{page-1}"))
        if page < total_pages:
            nav.add(types.InlineKeyboardButton(text="➡️", callback_data=f"cat_page:{page+1}"))
        nav.adjust(2)

        # Действия
        actions = InlineKeyboardBuilder()
        actions.add(types.InlineKeyboardButton(text="✅ Готово", callback_data="composition:done"))

        kb.attach(nav)
        kb.attach(actions)
        await bot.send_message(chat_id, "Выберите категорию:", reply_markup=kb.as_markup())
    except Exception as e:
        logging.error(f"show_category_page error: {e}", exc_info=True)
        await bot.send_message(chat_id, "Не удалось загрузить категории.")
    finally:
        await session.close()


# ---------- Витрина товаров категории ----------

async def show_product_page(chat_id: int, state: FSMContext, bot, category_id: int, page: int = 1):
    session = await get_db_session()
    try:
        # найдём категорию
        result_cat = await session.execute(select(Category).where(Category.id == category_id))
        category = result_cat.scalar_one_or_none()
        if not category:
            await bot.send_message(chat_id, "Категория не найдена.")
            return

        result = await session.execute(
            select(Product).where(Product.category_id == category_id).order_by(Product.name.asc())
        )
        products = result.scalars().all()
        if not products:
            await bot.send_message(chat_id, f"В категории «{category.name}» нет товаров.")
            return

        total_pages = max(1, math.ceil(len(products) / PAGE_SIZE))
        page = max(1, min(page, total_pages))
        start = (page - 1) * PAGE_SIZE
        chunk = products[start:start + PAGE_SIZE]

        kb = InlineKeyboardBuilder()
        for p in chunk:
            title = p.name if not p.color else f"{p.name} ({p.color})"
            kb.add(types.InlineKeyboardButton(text=f"➕ {title}", callback_data=f"prod_select:{p.id}"))

        nav = InlineKeyboardBuilder()
        if page > 1:
            nav.add(types.InlineKeyboardButton(text="⬅️", callback_data=f"prod_page:{category_id}:{page-1}"))
        if page < total_pages:
            nav.add(types.InlineKeyboardButton(text="➡️", callback_data=f"prod_page:{category_id}:{page+1}"))
        nav.adjust(2)

        actions = InlineKeyboardBuilder()
        actions.add(types.InlineKeyboardButton(text="◀️ К категориям", callback_data="composition:back_to_categories"))
        actions.add(types.InlineKeyboardButton(text="✅ Готово", callback_data="composition:done"))

        kb.attach(nav)
        kb.attach(actions)

        await bot.send_message(chat_id, f"Категория: <b>{category.name}</b>\nВыберите товар:", reply_markup=kb.as_markup())
    except Exception as e:
        logging.error(f"show_product_page error: {e}", exc_info=True)
        await bot.send_message(chat_id, "Не удалось загрузить товары категории.")
    finally:
        await session.close()


# ---------- Колбэки и ввод количества ----------

async def handle_category_page(callback: types.CallbackQuery, state: FSMContext):
    page = int(callback.data.split(":")[1])
    await callback.answer()
    await show_category_page(callback.message.chat.id, state, callback.bot, page=page)

async def handle_category_select(callback: types.CallbackQuery, state: FSMContext):
    # format: cat_select:<cat_id>:<page>
    parts = callback.data.split(":")
    category_id = int(parts[1])
    page = int(parts[2]) if len(parts) > 2 else 1
    await callback.answer()
    await state.set_state(BouquetStates.choosing_product)
    await show_product_page(callback.message.chat.id, state, callback.bot, category_id=category_id, page=page)

async def handle_product_page(callback: types.CallbackQuery, state: FSMContext):
    # format: prod_page:<cat_id>:<page>
    _, cat_id, page = callback.data.split(":")
    await callback.answer()
    await show_product_page(callback.message.chat.id, state, callback.bot, category_id=int(cat_id), page=int(page))

async def handle_product_select(callback: types.CallbackQuery, state: FSMContext):
    """
    После клика по товару:
      1) сохраняем его id в FSM
      2) показываем подсказку «Введите количество для <название товара>»
    """
    product_id = int(callback.data.split(":")[1])
    await state.update_data(selected_product_id=product_id)
    await state.set_state(BouquetStates.entering_quantity)

    # Получим название/цвет, чтобы показать пользователю
    session = await get_db_session()
    try:
        res = await session.execute(
            select(Product, Category).join(Category, Product.category_id == Category.id).where(Product.id == product_id)
        )
        row = res.one_or_none()
        if not row:
            await callback.message.answer("Товар не найден. Вернёмся к категориям.")
            await state.set_state(BouquetStates.choosing_category)
            await show_category_page(callback.message.chat.id, state, callback.bot, page=1)
            await callback.answer()
            return

        product, _ = row
        title = product.name if not product.color else f"{product.name} ({product.color})"
        await callback.message.answer(
            f"Введите количество для <b>{title}</b> (целое число 1..9999):",
            parse_mode="HTML"
        )
    except Exception as e:
        logging.error(f"handle_product_select error: {e}", exc_info=True)
        await callback.message.answer("Ошибка. Попробуйте ещё раз выбрать товар.")
    finally:
        await session.close()

    await callback.answer()

async def process_quantity(message: types.Message, state: FSMContext):
    try:
        qty_text = (message.text or "").strip()
        if not qty_text.isdigit():
            await message.answer("Введите целое число. Попробуйте ещё раз:")
            return
        qty = int(qty_text)
        if not (1 <= qty <= 9999):
            await message.answer("Количество должно быть 1..9999. Попробуйте ещё раз:")
            return

        data = await state.get_data()
        product_id = int(data.get("selected_product_id") or 0)
        if not product_id:
            await message.answer("Не удалось определить товар. Вернёмся к категориям.")
            await state.set_state(BouquetStates.choosing_category)
            await show_category_page(message.chat.id, state, message.bot, page=1)
            return

        session = await get_db_session()
        try:
            res = await session.execute(
                select(Product, Category).join(Category, Product.category_id == Category.id).where(Product.id == product_id)
            )
            row = res.one_or_none()
            if not row:
                await message.answer("Товар не найден. Вернёмся к категориям.")
                await state.set_state(BouquetStates.choosing_category)
                await show_category_page(message.chat.id, state, message.bot, page=1)
                return

            product, category = row
            composition = data.get("composition", []) or []
            composition.append({
                "raw_name": product.name,
                "qty": qty,
                "color": product.color,
                "type": product.product_type,
                "category": category.name,
                "product_id": product.id
            })
            await state.update_data(composition=composition, selected_product_id=None)

            title = product.name if not product.color else f"{product.name} ({product.color})"
            await message.answer(
                f"Добавлено: <b>{title}</b> — {qty} шт.\n"
                f"➕ Можно добавить ещё или завершить.",
                parse_mode="HTML"
            )

            await state.set_state(BouquetStates.choosing_category)
            await show_category_page(message.chat.id, state, message.bot, page=1)
        finally:
            await session.close()

    except Exception as e:
        logging.error(f"process_quantity error: {e}", exc_info=True)
        await message.answer("Ошибка при добавлении. Попробуйте ещё раз.")
        await state.set_state(BouquetStates.choosing_category)
        await show_category_page(message.chat.id, state, message.bot, page=1)

async def handle_composition_done(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    data = await state.get_data()
    comp = data.get("composition", []) or []
    if not comp:
        await state.set_state(BouquetStates.waiting_price)
        await callback.message.edit_text("Состав пуст. Введите цену (целое число):")
        return

    text = "<b>Состав сохранён:</b>\n"
    for item in comp:
        text += f"• {item['raw_name']} — {item['qty']}\n"
    text += "\nТеперь введите цену (целое число):"

    await state.set_state(BouquetStates.waiting_price)
    await callback.message.edit_text(text, parse_mode="HTML")

async def handle_composition_back(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(BouquetStates.choosing_category)
    await show_category_page(callback.message.chat.id, state, callback.bot, page=1)
