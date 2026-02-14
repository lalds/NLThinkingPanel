"""
Асинхронная система событий (Publish / Subscribe).

Позволяет модулям общаться друг с другом без прямых зависимостей.
Поддерживает:
 - Подписку на события с приоритетами
 - Wildcard подписки (например "user.*")
 - Middleware (перехватчики перед доставкой события)
 - Историю событий для дебага
 - Одноразовые подписки (once)
"""
import asyncio
import time
import fnmatch
from typing import Callable, Dict, List, Any, Optional, Awaitable
from dataclasses import dataclass, field
from collections import defaultdict
from threading import Lock

from core.logger import logger


@dataclass
class EventRecord:
    """Запись о произошедшем событии (для истории)."""
    event_name: str
    data: Dict[str, Any]
    timestamp: float
    handlers_called: int
    processing_time_ms: float


@dataclass
class Subscription:
    """Подписка на событие."""
    callback: Callable[..., Awaitable[None]]
    priority: int = 0       # Чем выше, тем раньше вызывается
    once: bool = False       # Одноразовая подписка
    source: str = "unknown"  # Кто подписался (для дебага)


class EventSystem:
    """
    Центральная шина событий бота.

    Примеры событий:
    - "user.message"         — пользователь написал сообщение
    - "user.joined"          — пользователь зашёл на сервер
    - "ai.response"          — AI сгенерировал ответ
    - "moderation.warn"      — выдано предупреждение
    - "reputation.levelup"   — пользователь повысил уровень
    - "mood.shift"           — изменение настроения сервера
    """

    def __init__(self, max_history: int = 500):
        self._subscribers: Dict[str, List[Subscription]] = defaultdict(list)
        self._wildcard_subscribers: List[tuple] = []  # (pattern, Subscription)
        self._middleware: List[Callable] = []
        self._history: List[EventRecord] = []
        self._max_history = max_history
        self._lock = Lock()

        # Счётчики
        self.total_events_emitted = 0
        self.total_handlers_called = 0

    # ─── Подписка ───

    def on(
        self,
        event: str,
        callback: Callable[..., Awaitable[None]],
        priority: int = 0,
        source: str = "unknown"
    ) -> None:
        """Подписка на событие."""
        sub = Subscription(callback=callback, priority=priority, source=source)

        if '*' in event or '?' in event:
            self._wildcard_subscribers.append((event, sub))
            logger.debug(f"EventSystem: wildcard подписка '{event}' от [{source}]")
        else:
            self._subscribers[event].append(sub)
            # Сортировка по приоритету (desc)
            self._subscribers[event].sort(key=lambda s: s.priority, reverse=True)
            logger.debug(f"EventSystem: подписка на '{event}' от [{source}] (priority={priority})")

    def once(
        self,
        event: str,
        callback: Callable[..., Awaitable[None]],
        priority: int = 0,
        source: str = "unknown"
    ) -> None:
        """Одноразовая подписка — автоматически удаляется после первого вызова."""
        sub = Subscription(callback=callback, priority=priority, once=True, source=source)

        if '*' in event or '?' in event:
            self._wildcard_subscribers.append((event, sub))
        else:
            self._subscribers[event].append(sub)
            self._subscribers[event].sort(key=lambda s: s.priority, reverse=True)

    def off(self, event: str, callback: Callable) -> bool:
        """Отписка от события по callback."""
        removed = False
        if event in self._subscribers:
            before = len(self._subscribers[event])
            self._subscribers[event] = [
                s for s in self._subscribers[event] if s.callback != callback
            ]
            removed = len(self._subscribers[event]) < before

        # Wildcard
        before_wc = len(self._wildcard_subscribers)
        self._wildcard_subscribers = [
            (p, s) for p, s in self._wildcard_subscribers
            if not (p == event and s.callback == callback)
        ]
        if len(self._wildcard_subscribers) < before_wc:
            removed = True

        return removed

    # ─── Middleware ───

    def use_middleware(self, middleware_fn: Callable) -> None:
        """
        Добавляет middleware.
        Middleware — это async функция(event_name, data) -> data | None.
        Если вернёт None, событие подавляется.
        """
        self._middleware.append(middleware_fn)
        logger.debug(f"EventSystem: добавлен middleware {middleware_fn.__name__}")

    # ─── Emit ───

    async def emit(self, event: str, **data) -> int:
        """
        Публикация события.

        Args:
            event: Имя события
            **data: Данные события

        Returns:
            Количество вызванных обработчиков
        """
        start_time = time.time()
        self.total_events_emitted += 1

        # Прогон через middleware
        current_data = data
        for mw in self._middleware:
            try:
                result = await mw(event, current_data)
                if result is None:
                    logger.debug(f"EventSystem: событие '{event}' подавлено middleware {mw.__name__}")
                    return 0
                current_data = result
            except Exception as e:
                logger.error(f"EventSystem: ошибка в middleware {mw.__name__}: {e}")

        # Сбор обработчиков
        handlers: List[Subscription] = []

        # Точные подписчики
        if event in self._subscribers:
            handlers.extend(self._subscribers[event])

        # Wildcard подписчики
        for pattern, sub in self._wildcard_subscribers:
            if fnmatch.fnmatch(event, pattern):
                handlers.append(sub)

        # Сортировка по приоритету
        handlers.sort(key=lambda s: s.priority, reverse=True)

        # Вызов обработчиков
        handlers_called = 0
        to_remove_once: List[Subscription] = []

        for sub in handlers:
            try:
                await sub.callback(event, **current_data)
                handlers_called += 1
                self.total_handlers_called += 1

                if sub.once:
                    to_remove_once.append(sub)

            except Exception as e:
                logger.error(
                    f"EventSystem: ошибка в обработчике '{event}' "
                    f"[{sub.source}]: {e}"
                )

        # Удаление одноразовых подписок
        for sub in to_remove_once:
            if event in self._subscribers and sub in self._subscribers[event]:
                self._subscribers[event].remove(sub)
            self._wildcard_subscribers = [
                (p, s) for p, s in self._wildcard_subscribers if s != sub
            ]

        # Запись в историю
        processing_time = (time.time() - start_time) * 1000
        record = EventRecord(
            event_name=event,
            data={k: str(v)[:100] for k, v in current_data.items()},
            timestamp=time.time(),
            handlers_called=handlers_called,
            processing_time_ms=round(processing_time, 2)
        )

        with self._lock:
            self._history.append(record)
            if len(self._history) > self._max_history:
                self._history = self._history[-self._max_history:]

        return handlers_called

    def emit_sync(self, event: str, **data) -> None:
        """Синхронная обёртка для emit (ставит в очередь asyncio)."""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.ensure_future(self.emit(event, **data))
            else:
                loop.run_until_complete(self.emit(event, **data))
        except RuntimeError:
            pass  # Нет event loop

    # ─── Информация ───

    def get_history(self, limit: int = 20, event_filter: Optional[str] = None) -> List[dict]:
        """Получение истории событий."""
        with self._lock:
            history = self._history.copy()

        if event_filter:
            history = [r for r in history if fnmatch.fnmatch(r.event_name, event_filter)]

        return [
            {
                'event': r.event_name,
                'handlers': r.handlers_called,
                'time_ms': r.processing_time_ms,
                'timestamp': r.timestamp
            }
            for r in history[-limit:]
        ]

    def get_stats(self) -> Dict[str, Any]:
        """Статистика системы событий."""
        total_subs = sum(len(subs) for subs in self._subscribers.values())
        total_wc = len(self._wildcard_subscribers)

        return {
            'total_events_emitted': self.total_events_emitted,
            'total_handlers_called': self.total_handlers_called,
            'registered_events': len(self._subscribers),
            'total_subscriptions': total_subs + total_wc,
            'wildcard_subscriptions': total_wc,
            'middleware_count': len(self._middleware),
            'history_size': len(self._history)
        }

    def get_registered_events(self) -> List[str]:
        """Список всех событий, на которые есть подписки."""
        events = list(self._subscribers.keys())
        events.extend([p for p, _ in self._wildcard_subscribers])
        return sorted(set(events))


# Глобальный экземпляр
event_system = EventSystem()
