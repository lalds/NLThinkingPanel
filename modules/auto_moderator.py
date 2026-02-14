"""
Умная авто-модерация с AI-детекцией токсичности.

Возможности:
 - Детекция токсичности (обсценная лексика, оскорбления, угрозы)
 - Детекция спама (повторяющиеся сообщения, flood)
 - Детекция рекламы и ссылок
 - Warnsystem с автоматическими наказаниями
 - Ведение модлога (все действия модерации)
 - Конфигурируемые фильтры по каналам
 - AI-классификация для edge cases
"""
import re
import json
import time
from pathlib import Path
from typing import Dict, List, Any, Optional, Set, Tuple
from datetime import datetime, timedelta
from collections import defaultdict, deque
from threading import Lock

from core.logger import logger


# ─── Словарь быстрых фильтров (русский + английский) ───

TOXIC_PATTERNS = [
    # Русские обсценные паттерны (regex)
    r'\bбля[дт]?\b', r'\bхуй', r'\bпиз[дц]', r'\bеб[аaлн]',
    r'\bсук[аи]', r'\bмуда[кч]', r'\bдеби[лр]', r'\bидиот',
    r'\bдаун\b', r'\bлох\b', r'\bтварь', r'\bшлюх',
    r'\bпидор', r'\bгандон', r'\bчмо\b',
    # Английские
    r'\bfuck', r'\bshit\b', r'\bbitch', r'\basshole',
    r'\bnigg', r'\bretard', r'\bfagg',
]

SPAM_URL_PATTERNS = [
    r'discord\.gg/\w+',
    r'discord\.com/invite/\w+',
    r'bit\.ly/\w+',
    r't\.me/\w+',
    r'click\s+here',
    r'free\s+nitro',
    r'бесплатн.{0,5}нитро',
    r'розыгрыш\s+нитро',
]

# ─── Уровни действий ───
class ModerationAction:
    NONE = 'none'
    WARN = 'warn'
    DELETE = 'delete'
    MUTE = 'mute'
    KICK = 'kick'
    BAN = 'ban'


class FilterResult:
    """Результат проверки фильтром."""
    __slots__ = ('triggered', 'filter_type', 'severity', 'action', 'reason', 'confidence')

    def __init__(
        self,
        triggered: bool = False,
        filter_type: str = "",
        severity: int = 0,
        action: str = ModerationAction.NONE,
        reason: str = "",
        confidence: float = 0.0,
    ):
        self.triggered = triggered
        self.filter_type = filter_type
        self.severity = severity       # 0-10
        self.action = action
        self.reason = reason
        self.confidence = confidence   # 0.0-1.0


class ModLogEntry:
    """Запись в модерационном логе."""
    __slots__ = ('timestamp', 'moderator_id', 'target_id', 'action', 'reason', 'auto', 'channel_id')

    def __init__(
        self,
        moderator_id: int,
        target_id: int,
        action: str,
        reason: str,
        auto: bool = False,
        channel_id: int = 0,
    ):
        self.timestamp = time.time()
        self.moderator_id = moderator_id
        self.target_id = target_id
        self.action = action
        self.reason = reason
        self.auto = auto
        self.channel_id = channel_id

    def to_dict(self) -> dict:
        return {
            'timestamp': self.timestamp,
            'moderator_id': self.moderator_id,
            'target_id': self.target_id,
            'action': self.action,
            'reason': self.reason,
            'auto': self.auto,
            'channel_id': self.channel_id,
        }


class AutoModerator:
    """Система умной авто-модерации."""

    def __init__(self, data_dir: str = 'data/moderation'):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()

        # Warns: user_id -> list of {timestamp, reason, severity}
        self._warnings: Dict[int, List[Dict]] = defaultdict(list)
        # Модлог
        self._modlog: List[ModLogEntry] = []
        # Flood tracking: user_id -> deque of (message_hash, timestamp)
        self._flood_tracker: Dict[int, deque] = defaultdict(lambda: deque(maxlen=20))
        # Muted users: user_id -> unmute_timestamp
        self._muted_users: Dict[int, float] = {}
        # Whitelist: user_ids не проверяются
        self._whitelist: Set[int] = set()
        # Channel-specific settings
        self._channel_config: Dict[int, Dict[str, Any]] = {}

        # Настройки
        self.warn_threshold_kick = 5   # Предупреждений до кика
        self.warn_threshold_ban = 10   # Предупреждений до бана
        self.flood_window_seconds = 10
        self.flood_max_messages = 5
        self.duplicate_threshold = 3   # Одинаковых сообщений подряд

        # Compiled regex
        self._toxic_compiled = [re.compile(p, re.IGNORECASE) for p in TOXIC_PATTERNS]
        self._spam_compiled = [re.compile(p, re.IGNORECASE) for p in SPAM_URL_PATTERNS]

        self._load_data()

    def _load_data(self):
        """Загрузка данных."""
        data_file = self.data_dir / 'moderation_data.json'
        if not data_file.exists():
            return

        try:
            with open(data_file, 'r', encoding='utf-8') as f:
                data = json.load(f)

            self._warnings = {
                int(k): v for k, v in data.get('warnings', {}).items()
            }
            self._whitelist = set(data.get('whitelist', []))
            self._channel_config = {
                int(k): v for k, v in data.get('channel_config', {}).items()
            }
            self._muted_users = {
                int(k): v for k, v in data.get('muted_users', {}).items()
            }
        except Exception as e:
            logger.error(f"Ошибка загрузки данных модерации: {e}")

    def _save_data(self):
        """Сохранение данных."""
        try:
            data = {
                'warnings': {str(k): v for k, v in self._warnings.items()},
                'whitelist': list(self._whitelist),
                'channel_config': {str(k): v for k, v in self._channel_config.items()},
                'muted_users': {str(k): v for k, v in self._muted_users.items()},
            }
            with open(self.data_dir / 'moderation_data.json', 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Ошибка сохранения данных модерации: {e}")

    # ─── Фильтрация ───

    def check_message(self, user_id: int, content: str, channel_id: int = 0) -> FilterResult:
        """
        Полная проверка сообщения всеми фильтрами.
        
        Returns:
            FilterResult с информацией о нарушении (если есть)
        """
        # Пропуск whitelist
        if user_id in self._whitelist:
            return FilterResult()

        # Проверка мута
        if self.is_muted(user_id):
            return FilterResult(
                triggered=True,
                filter_type='muted',
                severity=0,
                action=ModerationAction.DELETE,
                reason='Пользователь замутен',
                confidence=1.0,
            )

        # 1. Проверка токсичности
        toxic_result = self._check_toxicity(content)
        if toxic_result.triggered:
            return toxic_result

        # 2. Проверка спама/рекламы
        spam_result = self._check_spam(content)
        if spam_result.triggered:
            return spam_result

        # 3. Проверка флуда
        flood_result = self._check_flood(user_id, content)
        if flood_result.triggered:
            return flood_result

        # 4. Проверка caps lock
        caps_result = self._check_caps(content)
        if caps_result.triggered:
            return caps_result

        return FilterResult()

    def _check_toxicity(self, content: str) -> FilterResult:
        """Проверка на токсичную лексику."""
        for pattern in self._toxic_compiled:
            if pattern.search(content):
                match = pattern.search(content).group()
                return FilterResult(
                    triggered=True,
                    filter_type='toxicity',
                    severity=7,
                    action=ModerationAction.WARN,
                    reason=f'Обнаружена токсичная лексика: "{match[:20]}..."',
                    confidence=0.9,
                )
        return FilterResult()

    def _check_spam(self, content: str) -> FilterResult:
        """Проверка на спам и рекламу."""
        for pattern in self._spam_compiled:
            if pattern.search(content):
                return FilterResult(
                    triggered=True,
                    filter_type='spam',
                    severity=8,
                    action=ModerationAction.DELETE,
                    reason='Обнаружена спам-ссылка или реклама',
                    confidence=0.95,
                )
        return FilterResult()

    def _check_flood(self, user_id: int, content: str) -> FilterResult:
        """Проверка на флуд."""
        now = time.time()
        msg_hash = hash(content.lower().strip())

        # Записываем сообщение
        tracker = self._flood_tracker[user_id]
        tracker.append((msg_hash, now))

        # Подсчёт сообщений за окно
        recent = [(h, t) for h, t in tracker if now - t < self.flood_window_seconds]

        # Слишком много сообщений
        if len(recent) > self.flood_max_messages:
            return FilterResult(
                triggered=True,
                filter_type='flood',
                severity=5,
                action=ModerationAction.WARN,
                reason=f'Флуд: {len(recent)} сообщений за {self.flood_window_seconds}с',
                confidence=0.85,
            )

        # Дубликаты
        hashes = [h for h, t in recent]
        most_common_count = max(hashes.count(h) for h in set(hashes)) if hashes else 0
        if most_common_count >= self.duplicate_threshold:
            return FilterResult(
                triggered=True,
                filter_type='duplicate',
                severity=4,
                action=ModerationAction.DELETE,
                reason=f'Дубликат сообщения ({most_common_count} раз)',
                confidence=0.9,
            )

        return FilterResult()

    def _check_caps(self, content: str, threshold: float = 0.7, min_length: int = 15) -> FilterResult:
        """Проверка на CAPS LOCK."""
        if len(content) < min_length:
            return FilterResult()

        alpha_chars = [c for c in content if c.isalpha()]
        if not alpha_chars:
            return FilterResult()

        upper_ratio = sum(1 for c in alpha_chars if c.isupper()) / len(alpha_chars)

        if upper_ratio > threshold:
            return FilterResult(
                triggered=True,
                filter_type='caps',
                severity=2,
                action=ModerationAction.WARN,
                reason=f'Caps Lock: {upper_ratio:.0%} заглавных букв',
                confidence=0.7,
            )

        return FilterResult()

    # ─── AI-проверка ───

    async def ai_check_toxicity(self, content: str) -> FilterResult:
        """Глубокая проверка токсичности через AI."""
        try:
            from modules.ai_provider import ai_provider

            result = await ai_provider.generate_response(
                system_prompt=(
                    "Ты — классификатор токсичности текста.\n"
                    "Определи, содержит ли текст: оскорбления, угрозы, дискриминацию, "
                    "сексуальный контент, или другой вредный контент.\n"
                    "Ответь в формате: SAFE или TOXIC:причина\n"
                    "Примеры:\n"
                    "- 'Привет, как дела?' -> SAFE\n"
                    "- 'Ты тупой' -> TOXIC:оскорбление\n"
                ),
                user_message=content[:500],
                max_tokens=30,
                temperature=0.1,
                use_cache=True,
            )

            response = result['content'].strip().upper()

            if response.startswith('TOXIC'):
                reason = response.split(':', 1)[1] if ':' in response else 'AI обнаружил нарушение'
                return FilterResult(
                    triggered=True,
                    filter_type='ai_toxicity',
                    severity=6,
                    action=ModerationAction.WARN,
                    reason=f'AI-модерация: {reason}',
                    confidence=0.85,
                )

        except Exception as e:
            logger.warning(f"Ошибка AI проверки токсичности: {e}")

        return FilterResult()

    # ─── Предупреждения ───

    def add_warning(
        self,
        user_id: int,
        reason: str,
        severity: int = 5,
        moderator_id: int = 0,
        auto: bool = True,
        channel_id: int = 0,
    ) -> Dict[str, Any]:
        """Выдать предупреждение пользователю."""
        with self._lock:
            warning = {
                'timestamp': time.time(),
                'reason': reason,
                'severity': severity,
                'moderator_id': moderator_id,
                'auto': auto,
            }
            self._warnings[user_id].append(warning)

            # Модлог
            self._modlog.append(ModLogEntry(
                moderator_id=moderator_id,
                target_id=user_id,
                action=ModerationAction.WARN,
                reason=reason,
                auto=auto,
                channel_id=channel_id,
            ))

            warn_count = len(self._warnings[user_id])
            self._save_data()

            # Определяем автоматическое наказание
            recommended_action = ModerationAction.NONE
            if warn_count >= self.warn_threshold_ban:
                recommended_action = ModerationAction.BAN
            elif warn_count >= self.warn_threshold_kick:
                recommended_action = ModerationAction.KICK
            elif warn_count >= 3:
                recommended_action = ModerationAction.MUTE

            return {
                'warn_count': warn_count,
                'recommended_action': recommended_action,
                'warning': warning,
            }

    def get_warnings(self, user_id: int) -> List[Dict]:
        """Получить все предупреждения пользователя."""
        return self._warnings.get(user_id, [])

    def clear_warnings(self, user_id: int) -> int:
        """Очистить предупреждения пользователя."""
        count = len(self._warnings.get(user_id, []))
        self._warnings[user_id] = []
        self._save_data()
        return count

    # ─── Мут ───

    def mute_user(self, user_id: int, duration_seconds: int, reason: str = "",
                  moderator_id: int = 0) -> float:
        """Замутить пользователя на время."""
        unmute_at = time.time() + duration_seconds
        self._muted_users[user_id] = unmute_at

        self._modlog.append(ModLogEntry(
            moderator_id=moderator_id,
            target_id=user_id,
            action=ModerationAction.MUTE,
            reason=f"Мут на {duration_seconds}с: {reason}",
        ))

        self._save_data()
        return unmute_at

    def unmute_user(self, user_id: int) -> bool:
        """Снять мут с пользователя."""
        if user_id in self._muted_users:
            del self._muted_users[user_id]
            self._save_data()
            return True
        return False

    def is_muted(self, user_id: int) -> bool:
        """Проверка, замутен ли пользователь."""
        if user_id not in self._muted_users:
            return False
        if time.time() > self._muted_users[user_id]:
            del self._muted_users[user_id]
            return False
        return True

    def get_mute_remaining(self, user_id: int) -> float:
        """Оставшееся время мута в секундах."""
        if user_id not in self._muted_users:
            return 0
        remaining = self._muted_users[user_id] - time.time()
        return max(0, remaining)

    # ─── Whitelist ───

    def add_to_whitelist(self, user_id: int) -> None:
        self._whitelist.add(user_id)
        self._save_data()

    def remove_from_whitelist(self, user_id: int) -> None:
        self._whitelist.discard(user_id)
        self._save_data()

    # ─── Модлог ───

    def get_modlog(self, limit: int = 20, user_id: Optional[int] = None) -> List[Dict]:
        """Получить записи модлога."""
        entries = self._modlog
        if user_id:
            entries = [e for e in entries if e.target_id == user_id]

        return [e.to_dict() for e in entries[-limit:]]

    # ─── Статистика ───

    def get_stats(self) -> Dict[str, Any]:
        """Статистика автомодерации."""
        total_warnings = sum(len(w) for w in self._warnings.values())
        users_with_warnings = len([u for u, w in self._warnings.items() if len(w) > 0])
        active_mutes = len([u for u in self._muted_users if self.is_muted(u)])

        return {
            'total_warnings': total_warnings,
            'users_with_warnings': users_with_warnings,
            'active_mutes': active_mutes,
            'whitelist_size': len(self._whitelist),
            'modlog_entries': len(self._modlog),
        }


# Глобальный экземпляр
auto_moderator = AutoModerator()
