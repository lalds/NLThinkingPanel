"""
Модуль для поиска информации в сети Интернет.
Использует DuckDuckGo для анонимного и бесплатного поиска.
"""
from ddgs import DDGS
from typing import List, Dict, Any, Optional
from core.logger import logger
from core.cache import cache

class SearchEngine:
    """Провайдер поиска в Интернете."""
    
    def __init__(self, max_results: int = 5):
        self.max_results = max_results

    def search(self, query: str, max_results: Optional[int] = None) -> List[Dict[str, str]]:
        """
        Выполняет поиск в веб-сети.
        
        Args:
            query: Поисковый запрос
            max_results: Максимальное количество результатов
            
        Returns:
            Список словарей с ключами 'title', 'href', 'body'
        """
        limit = max_results or self.max_results
        
        # Проверка кэша (поиск тоже можно кэшировать на короткое время)
        cache_key = f"search_{query}_{limit}"
        cached_results = cache.get(cache_key)
        if cached_results:
            logger.info(f"Результаты поиска для '{query}' взяты из кэша")
            return cached_results

        try:
            logger.info(f"Выполнение веб-поиска: {query}")
            with DDGS() as ddgs:
                results = list(ddgs.text(query, max_results=limit))
                
                # Сохраняем в кэш на 30 минут (для поиска можно чуть дольше)
                cache.set(results, cache_key, ttl=1800)
                return results
                
        except Exception as e:
            logger.error(f"Ошибка при выполнении поиска: {e}")
            return []

    def format_results_for_ai(self, results: List[Dict[str, str]]) -> str:
        """Преобразует результаты поиска в текстовый блок для промпта."""
        if not results:
            return "Результаты поиска отсутствуют."
        
        formatted = ["🌐 **РЕЗУЛЬТАТЫ ПОИСКА В СЕТИ:**"]
        for i, res in enumerate(results, 1):
            formatted.append(f"{i}. **{res['title']}**")
            formatted.append(f"   Ссылка: {res['href']}")
            formatted.append(f"   Описание: {res['body']}\n")
            
        return "\n".join(formatted)

# Глобальный экземпляр
search_engine = SearchEngine()
