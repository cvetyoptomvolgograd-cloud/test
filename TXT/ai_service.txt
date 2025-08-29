import aiohttp
import logging
import json
import os
from typing import List, Dict, Any
from dotenv import load_dotenv

# Загружаем переменные окружения
load_dotenv()


class DeepSeekService:
    def __init__(self):
        self.api_key = os.getenv("DEEPSEEK_API_KEY")
        self.base_url = "https://api.deepseek.com/v1/chat/completions"

        # Проверяем конфигурацию при инициализации
        if not self.api_key:
            logging.warning("DeepSeek API key not configured. AI features will be limited.")
        else:
            logging.info("DeepSeek API key loaded successfully")

    async def generate_bouquet_options(self, keywords: str) -> List[Dict[str, str]]:
        """Генерирует варианты названий и описаний букетов на основе ключевых слов"""
        if not self.api_key:
            logging.error("DeepSeek API key not configured")
            return self._generate_fallback_options(keywords)

        prompt = f"""
        Сгенерируй 3 варианта названий и описаний для букета на основе этих ключевых слов: {keywords}

        Требования:
        1. Название: краткое, 2-4 слова, привлекательное
        2. Описание: 1-2 предложения, эмоциональное, описывает букет
        3. Формат ответа: JSON массив с объектами, каждый с полями "title" и "description"

        Пример:
        [
          {{
            "title": "Алая нежность",
            "description": "Нежный букет из алых роз, идеальный для романтического вечера"
          }},
          {{
            "title": "Вечная любовь", 
            "description": "Роскошная композиция, символизирующая вечную и страстную любовь"
          }}
        ]
        """

        try:
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }

            payload = {
                "model": "deepseek-chat",
                "messages": [
                    {"role": "system",
                     "content": "Ты помощник для флориста, который генерирует креативные названия и описания для букетов."},
                    {"role": "user", "content": prompt}
                ],
                "temperature": 0.8,
                "max_tokens": 500
            }

            async with aiohttp.ClientSession() as session:
                async with session.post(self.base_url, json=payload, headers=headers) as response:
                    if response.status == 200:
                        data = await response.json()
                        content = data["choices"][0]["message"]["content"]

                        # Извлекаем JSON из ответа
                        try:
                            # Ищем JSON в тексте ответа
                            json_start = content.find('[')
                            json_end = content.rfind(']') + 1
                            if json_start >= 0 and json_end > json_start:
                                json_str = content[json_start:json_end]
                                options = json.loads(json_str)
                                return options
                            else:
                                logging.error("JSON not found in AI response")
                                return self._generate_fallback_options(keywords)
                        except (json.JSONDecodeError, ValueError) as e:
                            logging.error(f"Failed to parse AI response: {e}")
                            return self._generate_fallback_options(keywords)

                    elif response.status == 402:
                        # Обработка ошибки недостатка средств
                        error_text = await response.text()
                        logging.error(f"DeepSeek API error: Insufficient Balance. Please top up your account.")
                        return self._generate_fallback_options(keywords)

                    else:
                        error_text = await response.text()
                        logging.error(f"DeepSeek API error: {response.status}, {error_text}")
                        return self._generate_fallback_options(keywords)

        except Exception as e:
            logging.error(f"Error calling DeepSeek API: {e}")
            return self._generate_fallback_options(keywords)

    def _generate_fallback_options(self, keywords: str) -> List[Dict[str, str]]:
        """Фолбэк варианты если AI не доступен"""
        logging.info(f"Using fallback options for keywords: {keywords}")
        return [
            {
                "title": f"Букет '{keywords}'",
                "description": f"Красивый букет из {keywords}. Идеально для особого случая."
            },
            {
                "title": f"Композиция '{keywords}'",
                "description": f"Изысканная композиция из {keywords}. Создана с любовью."
            },
            {
                "title": f"Настроение '{keywords}'",
                "description": f"Букет, который передает настроение {keywords}. Прекрасный выбор."
            }
        ]


# Создаем глобальный экземпляр сервиса
deepseek_service = DeepSeekService()