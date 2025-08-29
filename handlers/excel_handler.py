from aiogram import types
from aiogram.types import FSInputFile
import pandas as pd
import logging
import tempfile
import os
import re
from sqlalchemy import select

from database import get_db_session, Bouquet, Category, Product


# -----------------------------
# ВСПОМОГАТЕЛЬНЫЕ ПРЕОБРАЗОВАТЕЛИ
# -----------------------------

_URL_RE = re.compile(r"^https?://", re.IGNORECASE)

def _photos_to_urls(photos) -> str:
    """
    Вернуть ТОЛЬКО http(s) URL-адреса (через '; ') из поля photos.
    Поддерживаются форматы:
      • список словарей: {"file_id": "...", "url": "https://..."}
      • список строк: ["https://...", "AgACAgIA..."]
      • одиночная строка
    """
    if not photos:
        return ""
    try:
        urls = []
        if isinstance(photos, list):
            for item in photos:
                if isinstance(item, dict):
                    url = item.get("url")
                    if isinstance(url, str) and _URL_RE.match(url.strip()):
                        urls.append(url.strip())
                elif isinstance(item, str) and _URL_RE.match(item.strip()):
                    urls.append(item.strip())
        elif isinstance(photos, str) and _URL_RE.match(photos.strip()):
            urls.append(photos.strip())

        # уникализуем, сохраняя порядок
        seen = set()
        uniq = []
        for u in urls:
            if u not in seen:
                uniq.append(u)
                seen.add(u)
        return "; ".join(uniq)
    except Exception:
        return ""


def _composition_to_text(composition) -> str:
    """Сворачивает состав в строку «Название xКол-во; ...»."""
    if not composition:
        return ""
    parts = []
    try:
        for item in composition if isinstance(composition, list) else []:
            if isinstance(item, dict):
                title = (item.get("raw_name") or item.get("name") or "").strip()
                qty = item.get("qty")
                if title:
                    parts.append(f"{title}{f' x{qty}' if qty else ''}")
            else:
                parts.append(str(item))
    except Exception:
        pass
    return "; ".join(parts)


# -----------------------------
# ЭКСПОРТ ТОВАРОВ
# -----------------------------

async def export_products_to_excel(message: types.Message):
    """Экспорт всех товаров в Excel файл."""
    session = await get_db_session()
    try:
        result = await session.execute(
            select(Product, Category).join(Category, Product.category_id == Category.id)
        )
        products = result.all()

        if not products:
            await message.answer("В базе нет товаров для экспорта.")
            return

        data = []
        for product, category in products:
            data.append({
                "Категория": category.name,
                "Название": product.name,
                "Цвет": product.color or "",
                "Тип": product.product_type or "другое",
                "Создано": product.created_at.strftime("%Y-%m-%d %H:%M:%S")
                if getattr(product, "created_at", None) else ""
            })

        df = pd.DataFrame(data)

        with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp_file:
            tmp_path = tmp_file.name

        try:
            df.to_excel(tmp_path, index=False, engine="openpyxl")
            await message.answer_document(
                document=FSInputFile(tmp_path, filename="products_export.xlsx"),
                caption=f"Экспорт товаров: {len(products)} позиций"
            )
        finally:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass

    except Exception as e:
        logging.error(f"Ошибка при экспорте товаров: {e}", exc_info=True)
        await message.answer("Ошибка при экспорте данных.")
    finally:
        await session.close()


# -----------------------------
# ЭКСПОРТ БУКЕТОВ (КАТАЛОГ)
# -----------------------------

async def export_bouquets_to_excel(message: types.Message):
    """
    Экспорт всех букетов в Excel.
    В колонке «Фото (URL)» — ТОЛЬКО ссылки из Яндекс-облака; file_id отфильтровываются.
    """
    session = await get_db_session()
    try:
        result = await session.execute(select(Bouquet).order_by(Bouquet.created_at.desc()))
        bouquets = result.scalars().all()

        if not bouquets:
            await message.answer("В базе нет букетов для экспорта.")
            return

        rows = []
        for b in bouquets:
            created_at = b.created_at.strftime("%Y-%m-%d %H:%M:%S") if getattr(b, "created_at", None) else ""
            updated_at = b.updated_at.strftime("%Y-%m-%d %H:%M:%S") if getattr(b, "updated_at", None) else ""

            rows.append({
                "ID букета": getattr(b, "bouquet_id", ""),
                "Полное название": getattr(b, "title_display", getattr(b, "short_title", "")),
                "Короткое название": getattr(b, "short_title", ""),
                "Описание": getattr(b, "description", ""),
                "Состав": _composition_to_text(getattr(b, "composition", None)),
                "Цена (рубли)": (getattr(b, "price_minor", 0) or 0) / 100,
                "Валюта": getattr(b, "currency", "RUB") or "RUB",
                "Видео (URL)": getattr(b, "video_path", "") or "",
                "Фото (URL)": _photos_to_urls(getattr(b, "photos", None)),
                "Создано": created_at,
                "Обновлено": updated_at,
            })

        df = pd.DataFrame(rows)

        with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp_file:
            tmp_path = tmp_file.name

        try:
            df.to_excel(tmp_path, index=False, engine="openpyxl")
            await message.answer_document(
                document=FSInputFile(tmp_path, filename="catalog_bouquets.xlsx"),
                caption=f"Экспорт каталога (букеты): {len(bouquets)} шт."
            )
        finally:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass

    except Exception as e:
        logging.error(f"Ошибка при экспорте букетов: {e}", exc_info=True)
        await message.answer("Ошибка при экспорте каталога.")
    finally:
        await session.close()
