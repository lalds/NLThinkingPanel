"""
Система репутации и уровней (Reputation & Leveling).

Возможности:
 - XP за активность (сообщения, команды, полезные действия)
 - Уровни с прогрессивной шкалой
 - Бейджи и достижения
 - Лидерборд сервера
 - Бонусы за высокий уровень (расширенный rate limit и т.д.)
 - Ежедневные бонусы и streak
 - Передача репутации (+rep, -rep)
"""
import json
import math
import time
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime, timedelta
from collections import defaultdict
from threading import Lock

from core.logger import logger

# ─── Формулы ───

def xp_for_level(level: int) -> int:
    """XP, необходимый для достижения определённого уровня."""
    # Прогрессивная формула: каждый уровень требует на 15% больше XP
    return int(100 * (level ** 1.8))


def level_from_xp(total_xp: int) -> int:
    """Определить уровень по общему XP."""
    level = 0
    while xp_for_level(level + 1) <= total_xp:
        level += 1
    return level


def xp_progress(total_xp: int) -> Tuple[int, int, float]:
    """
    Returns:
        (xp_in_current_level, xp_needed_for_next, progress_percent)
    """
    current_level = level_from_xp(total_xp)
    current_threshold = xp_for_level(current_level)
    next_threshold = xp_for_level(current_level + 1)
    
    xp_into_level = total_xp - current_threshold
    xp_needed = next_threshold - current_threshold
    
    progress = xp_into_level / xp_needed if xp_needed > 0 else 1.0
    
    return xp_into_level, xp_needed, progress


# ─── Бейджи / Достижения ───

BADGES = {
    # ID: (emoji, name, description, condition_description)
    'first_message': ('💬', 'Первое слово', 'Отправил первое сообщение', 'Отправьте 1 сообщение'),
    'chatterbox': ('🗣️', 'Болтун', 'Отправил 100 сообщений', '100 сообщений'),
    'novelist': ('📚', 'Романист', 'Отправил 1000 сообщений', '1000 сообщений'),
    'first_ask': ('❓', 'Любопытный', 'Первый вопрос к AI', 'Задайте вопрос AI'),
    'ai_power_user': ('🤖', 'AI Энтузиаст', '50 вопросов к AI', '50 запросов к AI'),
    'researcher': ('🔬', 'Исследователь', '10 веб-поисков', '10 запросов !web'),
    'early_bird': ('🌅', 'Ранняя пташка', 'Написал до 7 утра', 'Напишите до 7:00'),
    'night_owl': ('🦉', 'Сова', 'Написал после полуночи', 'Напишите после 0:00'),
    'streak_7': ('🔥', 'Огонь!', '7-дневный streak', '7 дней подряд'),
    'streak_30': ('💎', 'Легенда', '30-дневный streak', '30 дней подряд'),
    'helper': ('🤝', 'Помощник', 'Получил 10 +rep', 'Получите 10 +rep'),
    'level_5': ('⭐', 'Звёздочка', 'Достиг 5 уровня', 'Уровень 5'),
    'level_10': ('🌟', 'Суперзвезда', 'Достиг 10 уровня', 'Уровень 10'),
    'level_25': ('☀️', 'Солнце', 'Достиг 25 уровня', 'Уровень 25'),
    'level_50': ('👑', 'Корона', 'Достиг 50 уровня', 'Уровень 50'),
    'generous': ('💝', 'Щедрый', 'Дал 25 +rep другим', '25 раз +rep'),
    'profile_set': ('📋', 'Визитка', 'Заполнил профиль', 'Создайте профиль'),
    'web_master': ('🌐', 'Веб-Мастер', '50 веб-поисков', '50 запросов !web'),
}


# ─── XP награды за действия ───

XP_REWARDS = {
    'message': 5,          # Обычное сообщение
    'ask_command': 15,     # Вопрос к AI
    'web_search': 20,      # Веб-поиск
    'help_given': 25,      # Помог другому (+rep)
    'daily_bonus': 50,     # Ежедневный бонус
    'streak_bonus': 10,    # Бонус за каждый день streak
    'first_of_day': 20,    # Первое сообщение дня
    'profile_create': 30,  # Создание профиля
    'quiz_win': 40,        # Победа в квизе
    'duel_win': 30,        # Победа в дуэли
}


class UserReputation:
    """Данные репутации одного пользователя."""

    def __init__(self, user_id: int, user_name: str = ""):
        self.user_id = user_id
        self.user_name = user_name
        self.total_xp = 0
        self.rep_points = 0        # Очки репутации от других
        self.messages_count = 0
        self.ai_requests = 0
        self.web_searches = 0

        # Daily/Streak
        self.last_daily_claim: Optional[str] = None  # YYYY-MM-DD
        self.current_streak = 0
        self.longest_streak = 0
        self.last_active_date: Optional[str] = None

        # Бейджи: set of badge_ids
        self.badges: List[str] = []

        # Rep given/received
        self.rep_given = 0         # Сколько раз дал +rep
        self.rep_received = 0      # Сколько раз получил +rep
        self.rep_given_today: Dict[str, int] = {}  # date -> count (лимит в день)

        # Время регистрации в системе
        self.joined_at = time.time()

    @property
    def level(self) -> int:
        return level_from_xp(self.total_xp)

    @property
    def progress(self) -> Tuple[int, int, float]:
        return xp_progress(self.total_xp)

    @property
    def rank_title(self) -> str:
        """Получить титул по уровню."""
        lvl = self.level
        if lvl >= 50:
            return '👑 Легенда'
        elif lvl >= 35:
            return '☀️ Мастер'
        elif lvl >= 25:
            return '🌟 Эксперт'
        elif lvl >= 15:
            return '⭐ Ветеран'
        elif lvl >= 10:
            return '🏅 Опытный'
        elif lvl >= 5:
            return '📘 Знающий'
        elif lvl >= 2:
            return '📗 Активный'
        else:
            return '📙 Новичок'

    def to_dict(self) -> dict:
        return {
            'user_id': self.user_id,
            'user_name': self.user_name,
            'total_xp': self.total_xp,
            'rep_points': self.rep_points,
            'messages_count': self.messages_count,
            'ai_requests': self.ai_requests,
            'web_searches': self.web_searches,
            'last_daily_claim': self.last_daily_claim,
            'current_streak': self.current_streak,
            'longest_streak': self.longest_streak,
            'last_active_date': self.last_active_date,
            'badges': self.badges,
            'rep_given': self.rep_given,
            'rep_received': self.rep_received,
            'joined_at': self.joined_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'UserReputation':
        user = cls(data['user_id'], data.get('user_name', ''))
        user.total_xp = data.get('total_xp', 0)
        user.rep_points = data.get('rep_points', 0)
        user.messages_count = data.get('messages_count', 0)
        user.ai_requests = data.get('ai_requests', 0)
        user.web_searches = data.get('web_searches', 0)
        user.last_daily_claim = data.get('last_daily_claim')
        user.current_streak = data.get('current_streak', 0)
        user.longest_streak = data.get('longest_streak', 0)
        user.last_active_date = data.get('last_active_date')
        user.badges = data.get('badges', [])
        user.rep_given = data.get('rep_given', 0)
        user.rep_received = data.get('rep_received', 0)
        user.joined_at = data.get('joined_at', time.time())
        return user


class ReputationSystem:
    """Система репутации и уровней."""

    def __init__(self, data_file: str = 'data/reputation.json'):
        self.data_file = Path(data_file)
        self.data_file.parent.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()

        # user_id -> UserReputation
        self._users: Dict[int, UserReputation] = {}

        # Настройки
        self.max_daily_rep_gives = 5
        self.xp_cooldown_seconds = 30  # Минимальное время между начислениями XP за сообщения
        self._last_xp_grant: Dict[int, float] = {}  # user_id -> timestamp

        self._load_data()

    def _load_data(self):
        if not self.data_file.exists():
            return
        try:
            with open(self.data_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            for user_data in data.get('users', []):
                user = UserReputation.from_dict(user_data)
                self._users[user.user_id] = user
            logger.info(f"Загружено {len(self._users)} профилей репутации")
        except Exception as e:
            logger.error(f"Ошибка загрузки репутации: {e}")

    def _save_data(self):
        try:
            data = {
                'users': [u.to_dict() for u in self._users.values()]
            }
            with open(self.data_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Ошибка сохранения репутации: {e}")

    def _get_or_create_user(self, user_id: int, user_name: str = "") -> UserReputation:
        """Получить или создать профиль."""
        if user_id not in self._users:
            self._users[user_id] = UserReputation(user_id, user_name)
        elif user_name:
            self._users[user_id].user_name = user_name
        return self._users[user_id]

    # ─── Начисление XP ───

    def grant_xp(
        self,
        user_id: int,
        user_name: str,
        action: str,
        bonus_xp: int = 0
    ) -> Tuple[int, bool, Optional[str]]:
        """
        Начислить XP за действие.
        
        Returns:
            (xp_granted, leveled_up, new_badge)
        """
        with self._lock:
            user = self._get_or_create_user(user_id, user_name)

            # Cooldown для сообщений
            if action == 'message':
                last = self._last_xp_grant.get(user_id, 0)
                if time.time() - last < self.xp_cooldown_seconds:
                    return 0, False, None
                self._last_xp_grant[user_id] = time.time()

            # Считаем XP
            base_xp = XP_REWARDS.get(action, 5) + bonus_xp

            # Streak бонус
            today = datetime.now().strftime('%Y-%m-%d')
            if user.last_active_date != today:
                if user.last_active_date:
                    yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
                    if user.last_active_date == yesterday:
                        user.current_streak += 1
                        base_xp += XP_REWARDS['streak_bonus'] * min(user.current_streak, 10)
                    else:
                        user.current_streak = 1
                else:
                    user.current_streak = 1

                user.last_active_date = today
                user.longest_streak = max(user.longest_streak, user.current_streak)

                # First of day бонус
                base_xp += XP_REWARDS['first_of_day']

            old_level = user.level
            user.total_xp += base_xp

            # Обновляем счётчики
            if action == 'message':
                user.messages_count += 1
            elif action == 'ask_command':
                user.ai_requests += 1
            elif action == 'web_search':
                user.web_searches += 1

            leveled_up = user.level > old_level

            # Проверка бейджей
            new_badge = self._check_badges(user)

            self._save_data()

            return base_xp, leveled_up, new_badge

    # ─── Репутация ───

    def give_rep(self, from_id: int, to_id: int, from_name: str = "",
                 to_name: str = "") -> Tuple[bool, str]:
        """
        Дать +rep пользователю.
        
        Returns:
            (success, message)
        """
        if from_id == to_id:
            return False, "Нельзя дать репутацию себе!"

        with self._lock:
            giver = self._get_or_create_user(from_id, from_name)
            receiver = self._get_or_create_user(to_id, to_name)

            # Проверка дневного лимита
            today = datetime.now().strftime('%Y-%m-%d')
            today_count = giver.rep_given_today.get(today, 0)
            if today_count >= self.max_daily_rep_gives:
                return False, f"Лимит +rep на сегодня исчерпан ({self.max_daily_rep_gives})"

            # Начисление
            receiver.rep_points += 1
            receiver.rep_received += 1
            giver.rep_given += 1
            giver.rep_given_today[today] = today_count + 1

            # XP бонус получателю
            receiver.total_xp += XP_REWARDS['help_given']

            # Бейдж
            new_badge = self._check_badges(receiver)

            self._save_data()

            msg = f"+1 rep для {receiver.user_name}! (Всего: {receiver.rep_points})"
            if new_badge:
                msg += f" 🎖️ Получен бейдж: {BADGES[new_badge][0]} {BADGES[new_badge][1]}"

            return True, msg

    # ─── Daily Bonus ───

    def claim_daily(self, user_id: int, user_name: str = "") -> Tuple[bool, int, int, str]:
        """
        Получить ежедневный бонус.
        
        Returns:
            (success, xp_gained, streak, message)
        """
        with self._lock:
            user = self._get_or_create_user(user_id, user_name)
            today = datetime.now().strftime('%Y-%m-%d')

            if user.last_daily_claim == today:
                return False, 0, user.current_streak, "Вы уже получили бонус сегодня!"

            # Streak
            yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
            if user.last_daily_claim == yesterday:
                user.current_streak += 1
            else:
                user.current_streak = 1

            user.last_daily_claim = today
            user.longest_streak = max(user.longest_streak, user.current_streak)

            # XP
            streak_multiplier = min(user.current_streak, 10)
            xp = XP_REWARDS['daily_bonus'] + XP_REWARDS['streak_bonus'] * streak_multiplier

            user.total_xp += xp

            self._check_badges(user)
            self._save_data()

            return True, xp, user.current_streak, f"+{xp} XP! Streak: {user.current_streak} дней 🔥"

    # ─── Бейджи ───

    def _check_badges(self, user: UserReputation) -> Optional[str]:
        """Проверка и выдача новых бейджей."""
        new_badge = None

        badge_checks = {
            'first_message': user.messages_count >= 1,
            'chatterbox': user.messages_count >= 100,
            'novelist': user.messages_count >= 1000,
            'first_ask': user.ai_requests >= 1,
            'ai_power_user': user.ai_requests >= 50,
            'researcher': user.web_searches >= 10,
            'web_master': user.web_searches >= 50,
            'streak_7': user.current_streak >= 7,
            'streak_30': user.current_streak >= 30,
            'helper': user.rep_received >= 10,
            'generous': user.rep_given >= 25,
            'level_5': user.level >= 5,
            'level_10': user.level >= 10,
            'level_25': user.level >= 25,
            'level_50': user.level >= 50,
        }

        for badge_id, condition in badge_checks.items():
            if condition and badge_id not in user.badges:
                user.badges.append(badge_id)
                new_badge = badge_id
                logger.info(f"Бейдж '{badge_id}' выдан пользователю {user.user_name}")

        # Time-based
        now = datetime.now()
        if now.hour < 7 and 'early_bird' not in user.badges:
            user.badges.append('early_bird')
            new_badge = 'early_bird'
        if now.hour >= 0 and now.hour < 4 and 'night_owl' not in user.badges:
            user.badges.append('night_owl')
            new_badge = 'night_owl'

        return new_badge

    # ─── Лидерборд ───

    def get_leaderboard(self, limit: int = 10, sort_by: str = 'xp') -> List[Dict[str, Any]]:
        """Получить лидерборд."""
        users = list(self._users.values())

        if sort_by == 'xp':
            users.sort(key=lambda u: u.total_xp, reverse=True)
        elif sort_by == 'rep':
            users.sort(key=lambda u: u.rep_points, reverse=True)
        elif sort_by == 'streak':
            users.sort(key=lambda u: u.current_streak, reverse=True)
        elif sort_by == 'messages':
            users.sort(key=lambda u: u.messages_count, reverse=True)

        board = []
        for i, user in enumerate(users[:limit]):
            xp_current, xp_needed, progress = user.progress
            board.append({
                'rank': i + 1,
                'user_id': user.user_id,
                'name': user.user_name,
                'level': user.level,
                'xp': user.total_xp,
                'xp_progress': f"{xp_current}/{xp_needed}",
                'progress_percent': round(progress * 100),
                'rep': user.rep_points,
                'streak': user.current_streak,
                'title': user.rank_title,
                'badges_count': len(user.badges),
            })

        return board

    # ─── Информация о пользователе ───

    def get_user_card(self, user_id: int) -> Optional[Dict[str, Any]]:
        """Получить карточку пользователя."""
        user = self._users.get(user_id)
        if not user:
            return None

        xp_current, xp_needed, progress = user.progress

        # Progress bar
        bar_length = 20
        filled = int(bar_length * progress)
        bar = '█' * filled + '░' * (bar_length - filled)

        badge_display = " ".join([
            BADGES[b][0] for b in user.badges if b in BADGES
        ]) or "Нет бейджей"

        return {
            'user_id': user.user_id,
            'name': user.user_name,
            'level': user.level,
            'title': user.rank_title,
            'total_xp': user.total_xp,
            'xp_current': xp_current,
            'xp_needed': xp_needed,
            'progress_bar': bar,
            'progress_percent': round(progress * 100),
            'rep_points': user.rep_points,
            'messages': user.messages_count,
            'ai_requests': user.ai_requests,
            'streak': user.current_streak,
            'longest_streak': user.longest_streak,
            'badges': badge_display,
            'badges_list': user.badges,
            'joined': datetime.fromtimestamp(user.joined_at).strftime('%Y-%m-%d'),
        }

    # ─── Статистика ───

    def get_stats(self) -> Dict[str, Any]:
        total_xp = sum(u.total_xp for u in self._users.values())
        total_messages = sum(u.messages_count for u in self._users.values())
        total_rep = sum(u.rep_points for u in self._users.values())

        return {
            'total_users': len(self._users),
            'total_xp_distributed': total_xp,
            'total_messages_tracked': total_messages,
            'total_rep_points': total_rep,
            'avg_level': round(
                sum(u.level for u in self._users.values()) / max(len(self._users), 1), 1
            ),
            'max_streak': max(
                (u.longest_streak for u in self._users.values()), default=0
            ),
        }


# Глобальный экземпляр
reputation_system = ReputationSystem()
