"""
Система напоминаний с планировщиком.

Возможности:
 - Однократные напоминания (!remind 30m Позвонить маме)
 - Повторяющиеся напоминания (!remind every 1h Перерыв!)
 - Естественный разбор времени (5м, 2ч, 1д, 30с)
 - Список активных напоминаний
 - Сохранение на диск (переживает рестарт)
 - Красивые embed-уведомления
"""
import re
import json
import time
import asyncio
import hashlib
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime, timedelta
from threading import Lock

from core.logger import logger


# ─── Парсинг времени ───

TIME_UNITS = {
    # Русские
    'с': 1, 'сек': 1, 'секунд': 1,
    'м': 60, 'мин': 60, 'минут': 60, 'минуты': 60,
    'ч': 3600, 'час': 3600, 'часа': 3600, 'часов': 3600,
    'д': 86400, 'день': 86400, 'дня': 86400, 'дней': 86400,
    'н': 604800, 'нед': 604800, 'неделя': 604800, 'недели': 604800,
    # Английские
    's': 1, 'sec': 1, 'second': 1, 'seconds': 1,
    'm': 60, 'min': 60, 'minute': 60, 'minutes': 60,
    'h': 3600, 'hr': 3600, 'hour': 3600, 'hours': 3600,
    'd': 86400, 'day': 86400, 'days': 86400,
    'w': 604800, 'week': 604800, 'weeks': 604800,
}

TIME_PATTERN = re.compile(r'(\d+)\s*([a-zA-Zа-яА-Я]+)')


def parse_duration(text: str) -> Optional[int]:
    """
    Парсит строку с длительностью.
    
    Примеры:
        "30м" -> 1800
        "2h30m" -> 9000
        "1д 12ч" -> 129600
        "5" -> 300 (по умолчанию минуты)
    
    Returns:
        Длительность в секундах или None
    """
    if not text:
        return None

    # Если просто число — считаем минутами
    if text.strip().isdigit():
        return int(text.strip()) * 60

    total_seconds = 0
    matches = TIME_PATTERN.findall(text)

    for amount_str, unit in matches:
        amount = int(amount_str)
        unit_lower = unit.lower()

        if unit_lower in TIME_UNITS:
            total_seconds += amount * TIME_UNITS[unit_lower]
        else:
            # Пробуем найти частичное совпадение
            for key, multiplier in TIME_UNITS.items():
                if key.startswith(unit_lower):
                    total_seconds += amount * multiplier
                    break

    return total_seconds if total_seconds > 0 else None


def format_duration(seconds: int) -> str:
    """Красивое отображение длительности."""
    if seconds < 60:
        return f"{seconds} сек"
    elif seconds < 3600:
        mins = seconds // 60
        secs = seconds % 60
        return f"{mins} мин" + (f" {secs} сек" if secs else "")
    elif seconds < 86400:
        hours = seconds // 3600
        mins = (seconds % 3600) // 60
        return f"{hours} ч" + (f" {mins} мин" if mins else "")
    else:
        days = seconds // 86400
        hours = (seconds % 86400) // 3600
        return f"{days} д" + (f" {hours} ч" if hours else "")


class Reminder:
    """Напоминание."""

    def __init__(
        self,
        reminder_id: str,
        user_id: int,
        channel_id: int,
        guild_id: int,
        message: str,
        fire_at: float,
        created_at: float = None,
        recurring: bool = False,
        interval_seconds: int = 0,
        fired: bool = False
    ):
        self.reminder_id = reminder_id
        self.user_id = user_id
        self.channel_id = channel_id
        self.guild_id = guild_id
        self.message = message
        self.fire_at = fire_at
        self.created_at = created_at or time.time()
        self.recurring = recurring
        self.interval_seconds = interval_seconds
        self.fired = fired

    @property
    def remaining_seconds(self) -> float:
        return max(0, self.fire_at - time.time())

    @property
    def is_due(self) -> bool:
        return time.time() >= self.fire_at

    def to_dict(self) -> dict:
        return {
            'reminder_id': self.reminder_id,
            'user_id': self.user_id,
            'channel_id': self.channel_id,
            'guild_id': self.guild_id,
            'message': self.message,
            'fire_at': self.fire_at,
            'created_at': self.created_at,
            'recurring': self.recurring,
            'interval_seconds': self.interval_seconds,
            'fired': self.fired,
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'Reminder':
        return cls(
            reminder_id=data['reminder_id'],
            user_id=data['user_id'],
            channel_id=data['channel_id'],
            guild_id=data.get('guild_id', 0),
            message=data['message'],
            fire_at=data['fire_at'],
            created_at=data.get('created_at', time.time()),
            recurring=data.get('recurring', False),
            interval_seconds=data.get('interval_seconds', 0),
            fired=data.get('fired', False),
        )


class ReminderSystem:
    """Система управления напоминаниями."""

    def __init__(self, data_file: str = 'data/reminders.json'):
        self.data_file = Path(data_file)
        self.data_file.parent.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()

        # reminder_id -> Reminder
        self._reminders: Dict[str, Reminder] = {}
        # user_id -> list of reminder_ids
        self._user_reminders: Dict[int, List[str]] = {}

        # Callback для отправки уведомлений (устанавливается ботом)
        self._notification_callback = None

        # Настройки
        self.max_reminders_per_user = 25
        self.min_interval_seconds = 30
        self.max_duration_seconds = 30 * 86400  # 30 дней

        self._load_data()

    def _load_data(self):
        if not self.data_file.exists():
            return

        try:
            with open(self.data_file, 'r', encoding='utf-8') as f:
                data = json.load(f)

            for r_data in data.get('reminders', []):
                r = Reminder.from_dict(r_data)
                if not r.fired or r.recurring:
                    self._reminders[r.reminder_id] = r
                    if r.user_id not in self._user_reminders:
                        self._user_reminders[r.user_id] = []
                    self._user_reminders[r.user_id].append(r.reminder_id)

            logger.info(f"Загружено {len(self._reminders)} напоминаний")
        except Exception as e:
            logger.error(f"Ошибка загрузки напоминаний: {e}")

    def _save_data(self):
        try:
            data = {
                'reminders': [r.to_dict() for r in self._reminders.values()],
            }
            with open(self.data_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Ошибка сохранения напоминаний: {e}")

    def set_notification_callback(self, callback):
        """Установить callback для отправки уведомлений."""
        self._notification_callback = callback

    # ─── Создание ───

    def create_reminder(
        self,
        user_id: int,
        channel_id: int,
        guild_id: int,
        message: str,
        duration_seconds: int,
        recurring: bool = False,
    ) -> Tuple[Optional[Reminder], str]:
        """
        Создать новое напоминание.
        
        Returns:
            (Reminder, error_message)
        """
        # Валидация
        user_reminders = self._user_reminders.get(user_id, [])
        if len(user_reminders) >= self.max_reminders_per_user:
            return None, f"Достигнут лимит напоминаний ({self.max_reminders_per_user})"

        if duration_seconds < self.min_interval_seconds:
            return None, f"Минимальное время: {self.min_interval_seconds} секунд"

        if duration_seconds > self.max_duration_seconds:
            return None, f"Максимальное время: {self.max_duration_seconds // 86400} дней"

        if len(message) > 500:
            return None, "Текст напоминания слишком длинный (макс 500 символов)"

        # Создание
        reminder_id = hashlib.sha256(
            f"{user_id}-{time.time()}-{message}".encode()
        ).hexdigest()[:10]

        reminder = Reminder(
            reminder_id=reminder_id,
            user_id=user_id,
            channel_id=channel_id,
            guild_id=guild_id,
            message=message,
            fire_at=time.time() + duration_seconds,
            recurring=recurring,
            interval_seconds=duration_seconds if recurring else 0,
        )

        with self._lock:
            self._reminders[reminder_id] = reminder
            if user_id not in self._user_reminders:
                self._user_reminders[user_id] = []
            self._user_reminders[user_id].append(reminder_id)
            self._save_data()

        logger.info(
            f"Создано напоминание {reminder_id} для user {user_id}: "
            f"'{message[:50]}' через {format_duration(duration_seconds)}"
        )

        return reminder, ""

    # ─── Получение ───

    def get_user_reminders(self, user_id: int) -> List[Reminder]:
        """Получить все активные напоминания пользователя."""
        reminder_ids = self._user_reminders.get(user_id, [])
        reminders = []
        for rid in reminder_ids:
            r = self._reminders.get(rid)
            if r and not r.fired:
                reminders.append(r)
        reminders.sort(key=lambda x: x.fire_at)
        return reminders

    def get_due_reminders(self) -> List[Reminder]:
        """Получить все напоминания, которые пора отправить."""
        due = []
        for r in self._reminders.values():
            if r.is_due and not r.fired:
                due.append(r)
        return due

    # ─── Удаление ───

    def delete_reminder(self, reminder_id: str, user_id: int = None) -> bool:
        """Удалить напоминание."""
        reminder = self._reminders.get(reminder_id)
        if not reminder:
            return False
        if user_id and reminder.user_id != user_id:
            return False

        with self._lock:
            del self._reminders[reminder_id]
            if reminder.user_id in self._user_reminders:
                try:
                    self._user_reminders[reminder.user_id].remove(reminder_id)
                except ValueError:
                    pass
            self._save_data()

        return True

    def delete_all_reminders(self, user_id: int) -> int:
        """Удалить все напоминания пользователя."""
        reminder_ids = self._user_reminders.get(user_id, []).copy()
        count = 0
        for rid in reminder_ids:
            if self.delete_reminder(rid, user_id):
                count += 1
        return count

    # ─── Обработка ───

    def mark_fired(self, reminder_id: str) -> Optional[Reminder]:
        """Пометить напоминание как выполненное."""
        reminder = self._reminders.get(reminder_id)
        if not reminder:
            return None

        if reminder.recurring:
            # Перенос на следующий интервал
            reminder.fire_at = time.time() + reminder.interval_seconds
            self._save_data()
            return reminder
        else:
            reminder.fired = True
            with self._lock:
                del self._reminders[reminder_id]
                if reminder.user_id in self._user_reminders:
                    try:
                        self._user_reminders[reminder.user_id].remove(reminder_id)
                    except ValueError:
                        pass
                self._save_data()
            return reminder

    # ─── Фоновая задача ───

    async def check_loop(self, bot):
        """
        Фоновый цикл проверки напоминаний.
        Вызывается из бота.
        """
        await bot.wait_until_ready()
        logger.info("🔔 Reminder check loop запущен")

        while not bot.is_closed():
            try:
                due = self.get_due_reminders()
                for reminder in due:
                    try:
                        channel = bot.get_channel(reminder.channel_id)
                        if channel:
                            import discord
                            embed = discord.Embed(
                                title="🔔 Напоминание!",
                                description=reminder.message,
                                color=discord.Color.gold(),
                                timestamp=datetime.now()
                            )
                            embed.set_footer(
                                text=f"ID: {reminder.reminder_id}"
                                + (" | 🔁 Повторяющееся" if reminder.recurring else "")
                            )
                            user = bot.get_user(reminder.user_id)
                            mention = f"<@{reminder.user_id}>"
                            await channel.send(
                                content=f"{mention} у тебя напоминание!",
                                embed=embed
                            )
                    except Exception as e:
                        logger.error(f"Ошибка отправки напоминания {reminder.reminder_id}: {e}")

                    self.mark_fired(reminder.reminder_id)

            except Exception as e:
                logger.error(f"Ошибка в reminder check loop: {e}")

            await asyncio.sleep(5)  # Проверка каждые 5 секунд

    # ─── Статистика ───

    def get_stats(self) -> Dict[str, Any]:
        active = len([r for r in self._reminders.values() if not r.fired])
        recurring = len([r for r in self._reminders.values() if r.recurring])

        return {
            'total_active': active,
            'recurring': recurring,
            'unique_users': len(self._user_reminders),
        }


# Глобальный экземпляр
reminder_system = ReminderSystem()
