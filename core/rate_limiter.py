"""
Система rate limiting для защиты от спама.
Использует алгоритм скользящего окна (sliding window).
"""
import time
from collections import deque
from typing import Dict, Deque
from threading import Lock


class RateLimiter:
    """
    Rate limiter на основе скользящего окна.
    Отслеживает количество запросов в заданном временном окне.
    """
    
    def __init__(self, max_requests: int = 5, window_seconds: int = 60):
        """
        Args:
            max_requests: Максимальное количество запросов в окне
            window_seconds: Размер временного окна в секундах
        """
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        
        # Хранилище: user_id -> deque of timestamps
        self._requests: Dict[int, Deque[float]] = {}
        self._lock = Lock()
    
    def is_allowed(self, user_id: int) -> bool:
        """
        Проверка, разрешён ли запрос для пользователя.
        
        Args:
            user_id: Discord ID пользователя
        
        Returns:
            True если запрос разрешён, False если превышен лимит
        """
        current_time = time.time()
        
        with self._lock:
            # Инициализация очереди для нового пользователя
            if user_id not in self._requests:
                self._requests[user_id] = deque()
            
            user_requests = self._requests[user_id]
            
            # Удаление устаревших запросов (вне окна)
            while user_requests and current_time - user_requests[0] > self.window_seconds:
                user_requests.popleft()
            
            # Проверка лимита
            if len(user_requests) >= self.max_requests:
                return False
            
            # Добавление нового запроса
            user_requests.append(current_time)
            return True
    
    def get_remaining(self, user_id: int) -> int:
        """
        Получение количества оставшихся разрешённых запросов.
        
        Args:
            user_id: Discord ID пользователя
        
        Returns:
            Количество оставшихся запросов
        """
        current_time = time.time()
        
        with self._lock:
            if user_id not in self._requests:
                return self.max_requests
            
            user_requests = self._requests[user_id]
            
            # Очистка устаревших
            while user_requests and current_time - user_requests[0] > self.window_seconds:
                user_requests.popleft()
            
            return max(0, self.max_requests - len(user_requests))
    
    def get_reset_time(self, user_id: int) -> float:
        """
        Получение времени до сброса лимита (в секундах).
        
        Args:
            user_id: Discord ID пользователя
        
        Returns:
            Секунды до сброса лимита
        """
        current_time = time.time()
        
        with self._lock:
            if user_id not in self._requests or not self._requests[user_id]:
                return 0
            
            oldest_request = self._requests[user_id][0]
            reset_time = oldest_request + self.window_seconds - current_time
            
            return max(0, reset_time)
    
    def reset_user(self, user_id: int) -> None:
        """Сброс лимита для конкретного пользователя (админ-функция)."""
        with self._lock:
            if user_id in self._requests:
                self._requests[user_id].clear()
    
    def get_stats(self) -> Dict[str, int]:
        """Получение общей статистики."""
        with self._lock:
            total_users = len(self._requests)
            total_requests = sum(len(reqs) for reqs in self._requests.values())
            
            return {
                'tracked_users': total_users,
                'active_requests': total_requests,
                'max_requests_per_window': self.max_requests,
                'window_seconds': self.window_seconds
            }


# Глобальный экземпляр rate limiter
rate_limiter = RateLimiter()
