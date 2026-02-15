"""
Модуль AI-провайдера с улучшенной обработкой запросов.
Поддерживает retry logic, fallback модели и оптимизацию промптов.
"""
import time
import asyncio
import g4f
from typing import Optional, Dict, Any, List
from openai import AsyncOpenAI
from core.logger import logger
from core.cache import cache
from config.config import config


class AIProvider:
    """Провайдер для работы с AI моделями через OpenRouter."""
    
    def __init__(self):
        """Инициализация клиента OpenAI."""
        self.client = AsyncOpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=config.openrouter_api_key,
        )
        
        # Fallback модели (актуальные бесплатные варианты)
        self.fallback_models = [
            'google/gemini-2.0-flash-lite-preview-02-05:free',
            'deepseek/deepseek-chat:free',
            'qwen/qwen-2.5-72b-instruct:free',
            'anthropic/claude-3-haiku',
            'openai/gpt-3.5-turbo',
            'meta-llama/llama-3-8b-instruct:free'
        ]
    
    async def generate_response(
        self,
        system_prompt: str,
        user_message: str,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        use_cache: bool = True
    ) -> Dict[str, Any]:
        """
        Генерация ответа от AI с расширенной обработкой.
        
        Args:
            system_prompt: Системный промпт
            user_message: Сообщение пользователя
            model: Модель (если None, используется из config)
            temperature: Температура генерации
            max_tokens: Максимальное количество токенов
            use_cache: Использовать ли кэширование
        
        Returns:
            Dict с ключами: content, model, tokens_used, response_time, from_cache
        """
        start_time = time.time()
        
        # Параметры по умолчанию
        model = model or config.openrouter_model
        temperature = temperature if temperature is not None else config.temperature
        max_tokens = max_tokens or config.max_tokens
        
        # Проверка кэша
        if use_cache and config.cache_enabled:
            cached = cache.get(system_prompt, user_message, model)
            if cached:
                logger.info(f"Ответ получен из кэша для модели {model}")
                cached['from_cache'] = True
                cached['response_time'] = time.time() - start_time
                return cached
        
        # Попытка генерации с retry logic
        models_to_try = [model] + [m for m in self.fallback_models if m != model]
        
        # Если запрошена модель "puter" или "gpt-5-nano", пробуем сначала Puter
        if model and ('puter' in model.lower() or 'gpt-5-nano' in model.lower()):
            models_to_try.insert(0, 'puter-gpt')
            
        last_error = None
        
        for attempt, current_model in enumerate(models_to_try):
            try:
                logger.info(f"Попытка {attempt + 1}: модель {current_model}")
                
                # Специальный случай для Puter
                if current_model == 'puter-gpt' or 'gpt-5-nano' in str(current_model).lower():
                    content = await self._generate_puter_response(system_prompt, user_message)
                    if content:
                        result = {
                            'content': content,
                            'model': 'Puter/GPT-5-Nano (Free)',
                            'tokens_used': 0,
                            'response_time': time.time() - start_time,
                            'from_cache': False
                        }
                        if use_cache and config.cache_enabled:
                            cache.set(result, system_prompt, user_message, model)
                        return result

                # Если Puter не сработал, и модель сугубо путеровская - не шлем её в OpenRouter
                if current_model == 'puter-gpt':
                    logger.warning("PuterJS не вернул ответ, пропускаем вызов OpenRouter для 'puter-gpt'.")
                    continue

                completion = await self.client.chat.completions.create(
                    extra_headers={
                        "HTTP-Referer": "https://github.com/NLThinkingPanel",
                        "X-Title": "NLThinkingPanel Pro",
                    },
                    model=current_model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_message},
                    ],
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                
                response_time = time.time() - start_time
                
                result = {
                    'content': completion.choices[0].message.content,
                    'model': current_model,
                    'tokens_used': completion.usage.total_tokens if completion.usage else 0,
                    'response_time': response_time,
                    'from_cache': False
                }
                
                # Сохранение в кэш
                if use_cache and config.cache_enabled:
                    cache.set(result, system_prompt, user_message, model)
                
                logger.info(
                    f"Успешный ответ от {current_model} "
                    f"({result['tokens_used']} токенов, {response_time:.2f}s)"
                )
                
                return result
                
            except Exception as e:
                last_error = e
                logger.warning(f"Ошибка с моделью {current_model}: {e}")
                
                # Если это не последняя попытка, пробуем следующую модель
                if attempt < len(models_to_try) - 1:
                    logger.info(f"Переключение на fallback модель...")
                    await asyncio.sleep(1)  # Заменили time.sleep на асинхронный
                    continue
        
        # Если все попытки провалились
        raise Exception(f"Все модели недоступны. Последняя ошибка: {last_error}")
    
    def optimize_prompt(self, prompt: str, max_length: int = 4000) -> str:
        """
        Оптимизация промпта для уменьшения токенов.
        
        Args:
            prompt: Исходный промпт
            max_length: Максимальная длина в символах
        
        Returns:
            Оптимизированный промпт
        """
        if len(prompt) <= max_length:
            return prompt
        
        logger.warning(f"Промпт слишком длинный ({len(prompt)} символов), оптимизация...")
        
        # Простая оптимизация: обрезка с сохранением важных частей
        lines = prompt.split('\n')
        
        # Сохраняем начало и конец (обычно там важная информация)
        important_lines = []
        current_length = 0
        
        # Берём первые строки
        for line in lines[:10]:
            if current_length + len(line) < max_length // 2:
                important_lines.append(line)
                current_length += len(line)
            else:
                break
        
        important_lines.append("\n... [контекст сокращён для оптимизации] ...\n")
        
        # Берём последние строки
        for line in reversed(lines[-10:]):
            if current_length + len(line) < max_length:
                important_lines.insert(-1, line)
                current_length += len(line)
            else:
                break
        
        optimized = '\n'.join(important_lines)
        logger.info(f"Промпт оптимизирован: {len(prompt)} -> {len(optimized)} символов")
        
        return optimized
    
    def estimate_tokens(self, text: str) -> int:
        """
        Примерная оценка количества токенов в тексте.
        Используется упрощённая формула: ~4 символа = 1 токен.
        
        Args:
            text: Текст для оценки
        
        Returns:
            Примерное количество токенов
        """
        return len(text) // 4

    async def _generate_puter_response(self, system_prompt: str, user_message: str) -> Optional[str]:
        """Генерация ответа через бесплатные шлюзы g4f с жесткими таймаутами."""
        try:
            # Предотвращаем попытки g4f писать в защищенные папки
            import os
            os.environ['G4F_COOKIES_DIR'] = os.path.join(os.getcwd(), "data", "g4f_cookies")
            if not os.path.exists(os.environ['G4F_COOKIES_DIR']):
                os.makedirs(os.environ['G4F_COOKIES_DIR'], exist_ok=True)

            def _ask_g4f_sync(provider):
                try:
                    return g4f.ChatCompletion.create(
                        model="gpt-4o-mini",
                        provider=provider,
                        messages=[
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_message},
                        ],
                    )
                except Exception:
                    return None

            # Динамический список провайдеров (только те, что есть в текущей версии)
            providers = []
            for p_name in ['DuckDuckGo', 'ChatGptEs', 'PuterJS', 'Liaobots']:
                if hasattr(g4f.Provider, p_name):
                    providers.append(getattr(g4f.Provider, p_name))

            for provider in providers:
                try:
                    logger.info(f"🚀 [G4F] Пробуем провайдер {provider.__name__}...")
                    response = await asyncio.wait_for(
                        asyncio.get_event_loop().run_in_executor(None, _ask_g4f_sync, provider),
                        timeout=10.0
                    )
                    
                    if response and isinstance(response, str) and len(response) > 5:
                        # Чистим ответ от мусора g4f если он есть
                        if "Using HTTP/2" in response: response = response.split("\n")[-1]
                        return response
                    
                except asyncio.TimeoutError:
                    logger.warning(f"⌛ Таймаут провайдера {provider.__name__}, идем дальше...")
                    continue
                except Exception as e:
                    logger.warning(f"❌ Провайдер {provider.__name__} выдал ошибку: {e}")
                    continue
            
            return None
            
        except Exception as e:
            logger.error(f"Критическая ошибка в пайплайне G4F: {e}")
            return None

    async def check_search_necessity(self, query: str) -> bool:
        """
        Проверяет, требует ли запрос поиска в интернете.
        Использует дешевую/быструю модель для классификации.
        """
        if not query:
            return False
            
        # Проверка на явные триггеры (быстрый путь)
        quick_triggers = ["погода", "курс", "новости", "сейчас", "сегодня", "url", "http", "поиск"]
        if any(t in query.lower() for t in quick_triggers):
            return True

        system_prompt = (
            "Ты — классификатор намерений. Твоя задача: определить, нужен ли поиск в Google/Интернете для качественного ответа. "
            "Отвечай ТОЛЬКО 'YES', если поиск НУЖЕН. Отвечай 'NO', если можно ответить, используя только свои знания.\n"
            "Примеры YES: 'какая погода?', 'курс биткоина', 'новости сегодня', 'кто победил в матче', 'документация по library v5'.\n"
            "Примеры NO: 'привет', 'напиши код на python', 'расскажи анекдот', 'что такое инфляция', 'переведи текст'.\n"
            "Reply with YES or NO only."
        )
        
        try:
            # Пробуем использовать очень дешевую/бесплатную модель для классификации
            classifier_model = 'google/gemini-2.0-flash-lite-preview-02-05:free'
            
            res = await self.client.chat.completions.create(
                model=classifier_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"Query: {query}"}
                ],
                max_tokens=20,
                temperature=0.1,
                extra_headers={
                    "HTTP-Referer": "https://github.com/NLThinkingPanel",
                    "X-Title": "NLThinkingPanel Classifier",
                }
            )
            
            content = res.choices[0].message.content.strip().upper()
            logger.info(f"🔍 Auto-Web Check '{query[:20]}...': {content}")
            return 'YES' in content
            
        except Exception:
            # Fallback: пробуем использовать текущую сконфигурированную модель
            try:
                res = await self.client.chat.completions.create(
                    model=config.openrouter_model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": f"Query: {query}"}
                    ],
                    max_tokens=20,
                    temperature=0.1
                )
                content = res.choices[0].message.content.strip().upper()
                return 'YES' in content
            except Exception as e:
                logger.error(f"Ошибка классификации поиска: {e}")
                return False


# Глобальный экземпляр
ai_provider = AIProvider()
