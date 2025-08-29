import os
import asyncio
import logging
import signal
import sys
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.storage.redis import RedisStorage
from aiogram.client.default import DefaultBotProperties
from aiogram.utils.keyboard import ReplyKeyboardBuilder
from aiogram.dispatcher.middlewares.base import BaseMiddleware
from aiogram.types import Update
from aiogram.fsm.context import FSMContext
from dotenv import load_dotenv

# Импортируем наши модули
from database import init_db, get_db_session, get_or_create_user
from handlers import setup_handlers

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("bot.log", encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# Загрузка переменных окружения
load_dotenv()

# Глобальные переменные для управления состоянием бота
bot = None
dp = None


class FSMLoggingMiddleware(BaseMiddleware):
    """Middleware для логирования изменений состояний FSM"""

    async def __call__(self, handler, event, data):
        state = data.get('state')
        if state:
            current_state = await state.get_state()
            logger.info(f"FSM State Change: {current_state}")

        return await handler(event, data)


async def create_bot():
    """Создание и настройка экземпляров бота и диспетчера"""
    global bot, dp

    try:
        # Инициализация бота
        bot = Bot(token=os.getenv("BOT_TOKEN"), default=DefaultBotProperties(parse_mode="HTML"))

        # Инициализация хранилища состояний (Redis)
        storage = RedisStorage.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"))
        dp = Dispatcher(storage=storage)

        # Добавляем middleware для логирования FSM
        dp.update.outer_middleware(FSMLoggingMiddleware())

        # Регистрация основных обработчиков команд (В ПЕРВУЮ ОЧЕРЕДЬ!)
        dp.message.register(cmd_start, Command("start"))
        dp.message.register(cmd_help, Command("help"))
        dp.message.register(cmd_help, F.text == "❓ Помощь")

        # Регистрация обработчиков (ВО ВТОРУЮ ОЧЕРЕДЬ!)
        setup_handlers(dp)

        logger.info("Бот успешно создан и настроен")
        return True
    except Exception as e:
        logger.error(f"Ошибка при создании бота: {e}")
        return False


async def cmd_start(message: types.Message, state: FSMContext):
    """Обработчик команды /start"""
    try:
        # Очищаем состояние при старте
        await state.clear()

        session = await get_db_session()
        try:
            user = await get_or_create_user(session, message.from_user.id)

            # Создаем клавиатуру главного меню
            builder = ReplyKeyboardBuilder()
            builder.add(types.KeyboardButton(text="➕ Добавить букет"))
            builder.add(types.KeyboardButton(text="📚 Мои букеты"))
            builder.add(types.KeyboardButton(text="⚙️ Настройки"))
            builder.add(types.KeyboardButton(text="❓ Помощь"))

            await message.answer(
                "Добро пожаловать в конструктор букетов!\n\n"
                "Выберите действие из меню:",
                reply_markup=builder.as_markup(resize_keyboard=True)
            )
        except Exception as e:
            logger.error(f"Ошибка в cmd_start (работа с БД): {e}")
            await message.answer("Произошла ошибка при инициализации. Попробуйте еще раз.")
        finally:
            await session.close()
    except Exception as e:
        logger.error(f"Ошибка в cmd_start: {e}")
        await message.answer("Произошла внутренняя ошибка. Попробуйте позже.")


async def cmd_help(message: types.Message, state: FSMContext):
    """Обработчик команды /help"""
    try:
        # Очищаем состояние при запросе помощи
        await state.clear()

        help_text = (
            "🤖 <b>Помощь по боту</b>\n\n"
            "• <b>➕ Добавить букет</b> - создать новый букет\n"
            "• <b>📚 Мои букеты</b> - просмотр ваших букетов\n"
            "• <b>⚙️ Настройки</b> - настройки бота\n\n"
            "Процесс добавления букета:\n"
            "1. Введите название\n"
            "2. Добавьте фотографии\n"
            "3. Укажите описание\n"
            "4. Добавьте состав (опционально)\n"
            "5. Укажите цену\n"
            "6. Сохраните букет\n"
        )
        await message.answer(help_text)
    except Exception as e:
        logger.error(f"Ошибка в cmd_help: {e}")
        await message.answer("Произошла ошибка при отображении справки.")


async def shutdown():
    """Корректное завершение работы бота"""
    logger.info("Завершение работы бота...")
    if bot:
        await bot.session.close()
    logger.info("Бот остановлен")


def handle_exception(exc_type, exc_value, exc_traceback):
    """Глобальный обработчик необработанных исключений"""
    if issubclass(exc_type, KeyboardInterrupt):
        # Не логируем KeyboardInterrupt
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return

    logger.error("Необработанное исключение:", exc_info=(exc_type, exc_value, exc_traceback))


# Установка глобального обработчика исключений
sys.excepthook = handle_exception


async def main():
    """Основная функция запуска бота"""
    max_retries = 5
    retry_delay = 10  # секунд

    for attempt in range(max_retries):
        try:
            logger.info(f"Попытка запуска бота {attempt + 1}/{max_retries}")

            # Инициализация база данных
            await init_db()
            logger.info("База данных инициализирована")

            # Соединение с Redis
            try:
                import redis
                redis_client = redis.Redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"))
                redis_client.ping()
                logger.info("Redis подключен успешно")
            except redis.ConnectionError:
                logger.error("Не удалось подключиться к Redis. Убедитесь, что Redis запущен.")
                return False

            # Создание бота
            if not await create_bot():
                raise Exception("Не удалось создать бота")

            # Запуск бота
            logger.info("Запуск polling...")
            await dp.start_polling(bot)
            break

        except Exception as e:
            logger.error(f"Ошибка при запуске бота (попытка {attempt + 1}): {e}")

            if attempt < max_retries - 1:
                logger.info(f"Повторная попытка через {retry_delay} секунд...")
                await asyncio.sleep(retry_delay)
                retry_delay *= 2  # Экспоненциальная задержка
            else:
                logger.error("Достигнуто максимальное количество попыток. Завершение работы.")
                await shutdown()
                sys.exit(1)

        except KeyboardInterrupt:
            logger.info("Получен сигнал прерывания (Ctrl+C)")
            await shutdown()
            break


if __name__ == "__main__":
    # Обработка сигналов для корректного завершения
    signal.signal(signal.SIGINT, lambda s, f: asyncio.create_task(shutdown()))
    signal.signal(signal.SIGTERM, lambda s, f: asyncio.create_task(shutdown()))

    # Запуск основного цикла
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Бот остановлен пользователем")
    except Exception as e:
        logger.error(f"Критическая ошибка в основном цикле: {e}")
    finally:
        logger.info("Работа бота завершена")