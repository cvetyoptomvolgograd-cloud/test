from aiogram import F, Dispatcher
from states import BouquetStates

# Поток создания
from .bouquet_creation_flow import (
    start_new_bouquet, process_title, process_description,
    process_composition, process_price, handle_actions
)

# Интерактивный состав
from .composition_picker import (
    show_category_page, show_product_page,
    handle_category_page, handle_category_select,
    handle_product_page, handle_product_select,
    process_quantity, handle_composition_done, handle_composition_back
)

# Медиа
from .media_processing import (
    handle_photos, handle_documents, handle_back_to_media,
    handle_media_done, handle_add_video
)

# Управление букетами
from .bouquet_management import (
    list_bouquets, show_bouquet_details, handle_bouquet_pagination,
    start_edit_bouquet, handle_edit_field, handle_delete_bouquet,
    handle_back_to_list
)

# Настройки/общее
from .settings import show_settings, handle_settings, process_photo_limit
from .product_handler import handle_catalog_import  # регистрация импорта файла
from .common import handle_back_to_menu
from .help import show_help


def setup_handlers(dp: Dispatcher):
    # Главное меню
    dp.message.register(start_new_bouquet, F.text == "➕ Добавить букет")
    dp.message.register(list_bouquets, F.text == "📚 Мои букеты")
    dp.message.register(show_settings, F.text == "⚙️ Настройки")
    dp.message.register(show_help, F.text == "❓ Помощь")

    # Создание
    dp.message.register(process_title, BouquetStates.waiting_title)
    dp.message.register(handle_photos, BouquetStates.waiting_media, F.photo)
    dp.message.register(handle_documents, BouquetStates.waiting_media, F.document)
    dp.message.register(process_description, BouquetStates.waiting_description)
    dp.message.register(process_composition, BouquetStates.waiting_composition)
    dp.message.register(process_price, BouquetStates.waiting_price)

    # Интерактивный состав
    dp.callback_query.register(handle_category_page, F.data.startswith("cat_page:"))
    dp.callback_query.register(handle_category_select, F.data.startswith("cat_select:"))
    dp.callback_query.register(handle_product_page, F.data.startswith("prod_page:"))
    dp.callback_query.register(handle_product_select, F.data.startswith("prod_select:"))
    dp.callback_query.register(handle_composition_done, F.data == "composition:done")
    dp.callback_query.register(handle_composition_back, F.data == "composition:back_to_categories")
    dp.message.register(process_quantity, BouquetStates.entering_quantity)

    # Колбэки action:*
    dp.callback_query.register(handle_actions, F.data.startswith("action:"))
    dp.callback_query.register(handle_bouquet_pagination, F.data.startswith("bouquet_list:page:"))
    dp.callback_query.register(show_bouquet_details, F.data.startswith("bouquet_detail:"))
    dp.callback_query.register(start_edit_bouquet, F.data.startswith("edit_bouquet:"))
    dp.callback_query.register(handle_edit_field, F.data.startswith("edit_field:"))
    dp.callback_query.register(handle_delete_bouquet, F.data.startswith("delete_bouquet:"))
    dp.callback_query.register(handle_settings, F.data.startswith("settings:"))
    dp.callback_query.register(handle_back_to_menu, F.data == "back_to_menu")
    dp.callback_query.register(handle_back_to_list, F.data == "back_to_list")
    dp.callback_query.register(handle_back_to_media, F.data == "back_to_media")
    dp.callback_query.register(handle_media_done, F.data == "media_done")
    dp.callback_query.register(handle_add_video, F.data == "add_video")

    # Редактирование
    dp.message.register(process_title, BouquetStates.editing_title)
    dp.message.register(handle_photos, BouquetStates.editing_media, F.photo)
    dp.message.register(handle_documents, BouquetStates.editing_media, F.document)
    dp.message.register(process_description, BouquetStates.editing_description)
    dp.message.register(process_composition, BouquetStates.editing_composition)
    dp.message.register(process_price, BouquetStates.editing_price)

    # Настройки
    dp.message.register(process_photo_limit, BouquetStates.waiting_photo_limit)

    # Импорт каталога: принимаем .xlsx ТОЛЬКО когда ждём файл
    dp.message.register(handle_catalog_import, BouquetStates.waiting_catalog_file, F.document)
