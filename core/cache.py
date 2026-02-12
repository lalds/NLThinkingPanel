"""
Система кэширования с TTL для оптимизации повторяющихся запросов.
Поддерживает автоматическую очистку устаревших записей.
"""
import hashlib
import json
import time
from typing import Any, Optional, Dict
from dataclasses import dataclass
from threading import Lock


@dataclass
class CacheEntry:
    """Запись в кэше с временем жизни."""
    value: Any
    timestamp: float
    ttl: int  # Time to live в секундах
    
    def is_expired(self) -> bool:
        """Проверка, истёк ли срок жизни записи."""
        return time.time() - self.timestamp > self.ttl


class SmartCache:
    """
    Умный кэш с автоматической очисткой и статистикой.
    Thread-safe реализация.
    """
    
    def __init__(self, default_ttl: int = 300):
        """
        Args:
            default_ttl: Время жизни записи по умолчанию (секунды)
        """
        self._cache: Dict[str, CacheEntry] = {}
        self._lock = Lock()
        self.default_ttl = default_ttl
        
        # Статистика
        self.hits = 0
        self.misses = 0
        self.evictions = 0
    
    def _generate_key(self, *args, **kwargs) -> str:
        """Генерация уникального ключа на основе аргументов."""
        key_data = json.dumps({'args': args, 'kwargs': kwargs}, sort_keys=True)
        return hashlib.sha256(key_data.encode()).hexdigest()
    
    def get(self, *args, **kwargs) -> Optional[Any]:
        """
        Получение значения из кэша.
        
        Returns:
            Закэшированное значение или None, если не найдено/истекло
        """
        key = self._generate_key(*args, **kwargs)
        
        with self._lock:
            entry = self._cache.get(key)
            
            if entry is None:
                self.misses += 1
                return None
            
            if entry.is_expired():
                del self._cache[key]
                self.misses += 1
                self.evictions += 1
                return None
            
            self.hits += 1
            return entry.value
    
    def set(self, value: Any, *args, ttl: Optional[int] = None, **kwargs) -> None:
        """
        Сохранение значения в кэш.
        
        Args:
            value: Значение для сохранения
            ttl: Время жизни записи (если None, используется default_ttl)
        """
        key = self._generate_key(*args, **kwargs)
        ttl = ttl or self.default_ttl
        
        with self._lock:
            self._cache[key] = CacheEntry(
                value=value,
                timestamp=time.time(),
                ttl=ttl
            )
    
    def clear(self) -> None:
        """Полная очистка кэша."""
        with self._lock:
            self._cache.clear()
            self.hits = 0
            self.misses = 0
            self.evictions = 0
    
    def cleanup(self) -> int:
        """
        Удаление всех истёкших записей.
        
        Returns:
            Количество удалённых записей
        """
        with self._lock:
            expired_keys = [
                key for key, entry in self._cache.items()
                if entry.is_expired()
            ]
            
            for key in expired_keys:
                del self._cache[key]
            
            self.evictions += len(expired_keys)
            return len(expired_keys)
    
    def get_stats(self) -> Dict[str, Any]:
        """Получение статистики кэша."""
        total_requests = self.hits + self.misses
        hit_rate = (self.hits / total_requests * 100) if total_requests > 0 else 0
        
        return {
            'size': len(self._cache),
            'hits': self.hits,
            'misses': self.misses,
            'evictions': self.evictions,
            'hit_rate': f"{hit_rate:.2f}%",
            'total_requests': total_requests
        }


# Глобальный экземпляр кэша
cache = SmartCache()
