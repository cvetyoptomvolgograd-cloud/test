from aiogram import types
from aiogram.types import FSInputFile
import pandas as pd
import tempfile
import os
import logging

from sqlalchemy import select, delete
from database import get_db_session, Category, Product


# ---------- Шаблон каталога ----------

async def send_excel_template(message: types.Message):
    """
    Отправляет Excel-шаблон каталога с двумя листами:
    - «Категории» (колонка: category)
    - «Товары» (колонки: category, name, color, type)
    """
    df_categories = pd.DataFrame({"category": ["Розы", "Тюльпаны", "Зелень"]})
    df_products = pd.DataFrame({
        "category": ["Розы", "Розы", "Тюльпаны", "Зелень"],
        "name": ["Роза эквадорская", "Роза кустовая", "Тюльпан белый", "Эвкалипт"],
        "color": ["красный", "розовый", "белый", ""],
        "type": ["цветок", "цветок", "цветок", "зелень"],
    })

    with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp_file:
        tmp_path = tmp_file.name

    try:
        with pd.ExcelWriter(tmp_path, engine="openpyxl") as writer:
            df_categories.to_excel(writer, index=False, sheet_name="Категории")
            df_products.to_excel(writer, index=False, sheet_name="Товары")

        await message.answer_document(
            document=FSInputFile(tmp_path, filename="catalog_template.xlsx"),
            caption=(
                "Шаблон каталога.\n"
                "Лист «Категории»: колонка category.\n"
                "Лист «Товары»: category, name, [color], [type]."
            ),
        )
    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass


# ---------- Импорт каталога из .xlsx ----------

async def handle_catalog_import(message: types.Message):
    """
    Импортирует категории и товары из .xlsx (по шаблону).
    Поведение: ПОЛНАЯ ПЕРЕЗАПИСЬ таблиц categories и products.
    Допускается:
      - Лист «Категории» (column: category) — необязателен, категории возьмём и из «Товары»
      - Лист «Товары» (columns: category, name, [color], [type]) — обязателен
    Нейминг листов — устойчивый к регистру и языку: ищем «Категории»/«categories», «Товары»/«products».
    """
    # Проверяем документ и расширение
    if not message.document:
        await message.answer("Пожалуйста, отправьте Excel-файл (.xlsx) по шаблону.")
        return

    filename = (message.document.file_name or "").lower()
    if not filename.endswith(".xlsx"):
        await message.answer("Формат файла должен быть .xlsx")
        return

    # Скачиваем файл во временный путь
    file_info = await message.bot.get_file(message.document.file_id)
    downloaded = await message.bot.download_file(file_info.file_path)

    with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp_file:
        data_bytes = downloaded.read() if hasattr(downloaded, "read") else downloaded.getvalue()
        tmp_file.write(data_bytes)
        tmp_path = tmp_file.name

    try:
        # Читаем все листы
        book = pd.read_excel(tmp_path, sheet_name=None, engine="openpyxl")

        # Функции поиска листов по имени
        def find_sheet(candidates):
            for name, df in book.items():
                if str(name).strip().lower() in candidates:
                    return df
            return None

        # Подготовим кандидаты имён
        cat_candidates = {"категории", "categories", "категорії"}
        prod_candidates = {"товары", "products", "товари"}

        df_categories = find_sheet(cat_candidates)
        df_products = find_sheet(prod_candidates)

        # Если лист «Товары» не найден — попробуем взять первый лист
        if df_products is None:
            # допускаем случай «один лист = товары»
            first_sheet_name = next(iter(book.keys()))
            df_products = book[first_sheet_name]

        # Приводим имена колонок к нижнему регистру и обрезаем пробелы
        def normalize_columns(df):
            df = df.copy()
            df.columns = [str(c).strip().lower() for c in df.columns]
            return df

        if df_categories is not None:
            df_categories = normalize_columns(df_categories)

        if df_products is None:
            await message.answer("Не найден лист с товарами. Ожидается «Товары»/«Products» или первый лист как товары.")
            return

        df_products = normalize_columns(df_products)

        # Проверим обязательные колонки для товаров
        required_prod = {"category", "name"}
        if not required_prod.issubset(set(df_products.columns)):
            await message.answer("Лист «Товары» должен содержать колонки: 'category' и 'name'.")
            return

        # Если лист «Категории» отсутствует — возьмём категории из товаров
        category_series = None
        if df_categories is not None:
            # Ищем колонку 'category' или 'name'
            if "category" in df_categories.columns:
                category_series = df_categories["category"]
            elif "name" in df_categories.columns:
                category_series = df_categories["name"]
            else:
                await message.answer("Лист «Категории» должен содержать колонку 'category' или 'name'.")
                return

        # Готовим списки
        categories_list = []
        if category_series is not None:
            categories_list = [str(x).strip() for x in category_series.dropna().tolist() if str(x).strip()]

        # Добьём категориями из товаров (если лист категорий пуст/отсутствует)
        prod_categories = [str(x).strip() for x in df_products["category"].dropna().tolist()]
        for c in prod_categories:
            if c and c not in categories_list:
                categories_list.append(c)

        # Нормализуем товары
        def safe_str(v):
            if pd.isna(v):
                return None
            s = str(v).strip()
            return s if s else None

        products_rows = []
        for _, row in df_products.iterrows():
            cat = safe_str(row.get("category"))
            name = safe_str(row.get("name"))
            color = safe_str(row.get("color")) if "color" in df_products.columns else None
            ptype = safe_str(row.get("type")) if "type" in df_products.columns else None
            if cat and name:
                products_rows.append((cat, name, color, (ptype or "другое")))

        if not products_rows:
            await message.answer("В листе «Товары» нет валидных строк (обязательны 'category' и 'name').")
            return

        # Пишем в БД
        session = await get_db_session()
        try:
            # Полная перезапись справочников
            await session.execute(delete(Product))
            await session.execute(delete(Category))
            await session.commit()

            # Создаём категории
            name_to_id = {}
            for cat_name in categories_list:
                cat_obj = Category(name=cat_name)
                session.add(cat_obj)
                await session.flush()
                name_to_id[cat_name] = cat_obj.id

            # Создаём товары
            for cat_name, name, color, ptype in products_rows:
                # подстрахуемся: если категории не было в categories_list, создадим на лету
                cat_id = name_to_id.get(cat_name)
                if cat_id is None:
                    cat_obj = Category(name=cat_name)
                    session.add(cat_obj)
                    await session.flush()
                    name_to_id[cat_name] = cat_obj.id
                    cat_id = cat_obj.id

                session.add(Product(
                    category_id=cat_id,
                    name=name,
                    color=color,
                    product_type=ptype or "другое",
                ))

            await session.commit()
            await message.answer(
                f"✅ Импорт завершён.\n"
                f"Категорий: {len(name_to_id)}\n"
                f"Товаров: {len(products_rows)}"
            )
        except Exception as db_err:
            await session.rollback()
            logging.error(f"Ошибка при импорте в БД: {db_err}", exc_info=True)
            await message.answer("Ошибка при импорте данных в базу.")
        finally:
            await session.close()

    except Exception as e:
        logging.error(f"Ошибка при обработке Excel файла: {e}", exc_info=True)
        await message.answer("Ошибка при чтении файла. Убедитесь, что это корректный .xlsx по шаблону.")
    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass
