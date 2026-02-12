"""
Модуль AI-провайдера с улучшенной обработкой запросов.
Поддерживает retry logic, fallback модели и оптимизацию промптов.
"""
import time
from typing import Optional, Dict, Any, List
from openai import OpenAI
from core.logger import logger
from core.cache import cache
from config.config import config


class AIProvider:
    """Провайдер для работы с AI моделями через OpenRouter."""
    
    def __init__(self):
        """Инициализация клиента OpenAI."""
        self.client = OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=config.openrouter_api_key,
        )
        
        # Fallback модели (если основная недоступна)
        self.fallback_models = [
            'anthropic/claude-3-haiku',
            'openai/gpt-3.5-turbo',
            'google/gemini-flash-1.5',
            'meta-llama/llama-3-8b-instruct:free'
        ]
    
    def generate_response(
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
        last_error = None
        
        for attempt, current_model in enumerate(models_to_try):
            try:
                logger.info(f"Попытка {attempt + 1}: модель {current_model}")
                
                completion = self.client.chat.completions.create(
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
                    time.sleep(1)  # Небольшая задержка перед retry
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


# Глобальный экземпляр
ai_provider = AIProvider()
