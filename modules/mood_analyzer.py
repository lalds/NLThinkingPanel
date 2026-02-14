"""
Система анализа настроения (Mood Analyzer).

Анализирует:
 - Настроение пользователя по его сообщениям (sentiment analysis через AI)
 - Общее настроение сервера / канала
 - Тренды настроения (улучшается / ухудшается)
 - Эмоциональные карты (кто что чувствует)

Используется для:
 - Персонализации ответов AI (если пользователь грустный — подбодрить)
 - Предупреждения токсичности (если настроение негативное — alert)
 - Красивой визуализации через embed
"""
import time
import asyncio
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime, timedelta
from collections import defaultdict, deque
from threading import Lock

from core.logger import logger


# ─── Маппинг эмодзи ───

MOOD_EMOJIS = {
    'ecstatic':   '🤩',
    'happy':      '😄',
    'positive':   '🙂',
    'neutral':    '😐',
    'bored':      '😑',
    'sad':        '😢',
    'angry':      '😠',
    'toxic':      '🤬',
    'confused':   '🤔',
    'excited':    '🎉',
    'anxious':    '😰',
    'sarcastic':  '😏',
}

MOOD_SCORES = {
    'ecstatic':  1.0,
    'excited':   0.9,
    'happy':     0.7,
    'positive':  0.5,
    'neutral':   0.0,
    'confused':  -0.1,
    'bored':     -0.2,
    'sarcastic': -0.3,
    'anxious':   -0.4,
    'sad':       -0.6,
    'angry':     -0.8,
    'toxic':     -1.0,
}

# Быстрые маркеры настроения (без AI)
QUICK_MOOD_KEYWORDS = {
    'positive': [
        'спасибо', 'круто', 'класс', 'супер', 'отлично', 'хорошо', 'прекрасно',
        'лучший', 'love', 'замечательно', 'обожаю', 'кайф', 'огонь', '❤', '🔥',
        '😄', '😊', '🥰', '👍', '💪', 'ахаха', 'лмао', 'ахах', 'хаха',
    ],
    'negative': [
        'плохо', 'ужас', 'отстой', 'бесит', 'ненавижу', 'дерьмо', 'trash',
        'хуже', 'идиот', 'тупой', 'сломалось', 'баг', 'ошибка', 'не работает',
        '😠', '😡', '🤮', '💀', '😤', 'блин', 'фак',
    ],
    'sad': [
        'грустно', 'печально', 'депрессия', 'одиноко', 'скучно',
        'тоска', 'плач', '😢', '😭', '😿',
    ],
    'excited': [
        'ого', 'невероятно', 'обалдеть', 'вау', 'вот это', '!!!',
        'шикарно', 'изумительно', '🤩', '🎉', '🎊',
    ],
}


class MoodEntry:
    """Запись настроения пользователя."""

    __slots__ = ('user_id', 'mood', 'score', 'confidence', 'message_snippet', 'timestamp')

    def __init__(
        self,
        user_id: int,
        mood: str,
        score: float,
        confidence: float,
        message_snippet: str,
        timestamp: float = None
    ):
        self.user_id = user_id
        self.mood = mood
        self.score = score
        self.confidence = confidence
        self.message_snippet = message_snippet[:80]
        self.timestamp = timestamp or time.time()


class MoodAnalyzer:
    """Анализатор настроения сервера и пользователей."""

    def __init__(
        self,
        history_window_hours: int = 6,
        max_entries_per_user: int = 50,
        max_entries_per_channel: int = 200,
    ):
        self.history_window_hours = history_window_hours
        self.max_entries_per_user = max_entries_per_user
        self.max_entries_per_channel = max_entries_per_channel
        self._lock = Lock()

        # user_id -> deque[MoodEntry]
        self._user_moods: Dict[int, deque] = defaultdict(
            lambda: deque(maxlen=max_entries_per_user)
        )
        # channel_id -> deque[MoodEntry]
        self._channel_moods: Dict[int, deque] = defaultdict(
            lambda: deque(maxlen=max_entries_per_channel)
        )

        # Кэш анализа AI (чтобы не спамить API)
        self._analysis_cache: Dict[str, Tuple[str, float, float]] = {}
        self._cache_ttl = 300  # 5 минут

    # ─── Быстрый анализ (без AI) ───

    def quick_analyze(self, text: str) -> Tuple[str, float, float]:
        """
        Быстрый анализ настроения по ключевым словам.
        
        Returns:
            (mood, score, confidence) — confidence 0.0-1.0
        """
        if not text:
            return 'neutral', 0.0, 0.0

        text_lower = text.lower()

        # Подсчёт совпадений по категориям
        scores = {'positive': 0, 'negative': 0, 'sad': 0, 'excited': 0}

        for category, keywords in QUICK_MOOD_KEYWORDS.items():
            for keyword in keywords:
                if keyword in text_lower:
                    scores[category] += 1

        total_matches = sum(scores.values())
        if total_matches == 0:
            return 'neutral', 0.0, 0.3

        # Определяем доминирующую категорию
        dominant = max(scores, key=scores.get)
        confidence = min(0.8, total_matches * 0.15)  # Макс 0.8 для быстрого анализа

        mood_map = {
            'positive': ('happy', 0.6),
            'negative': ('angry', -0.7),
            'sad': ('sad', -0.5),
            'excited': ('excited', 0.8),
        }

        mood, score = mood_map.get(dominant, ('neutral', 0.0))
        return mood, score, confidence

    # ─── AI-анализ ───

    async def ai_analyze(self, text: str) -> Tuple[str, float, float]:
        """
        Глубокий анализ настроения через AI.
        Используется для важных сообщений.
        
        Returns:
            (mood, score, confidence)
        """
        # Проверка кэша
        cache_key = text[:100]
        if cache_key in self._analysis_cache:
            cached_mood, cached_score, cached_time = self._analysis_cache[cache_key]
            if time.time() - cached_time < self._cache_ttl:
                return cached_mood, cached_score, 0.9

        try:
            from modules.ai_provider import ai_provider

            system_prompt = (
                "Ты — анализатор эмоций. Определи настроение текста.\n"
                "Ответь ОДНИМ словом из списка: "
                "ecstatic, happy, positive, neutral, bored, confused, "
                "sarcastic, anxious, sad, angry, toxic, excited\n"
                "Ответь ТОЛЬКО одним словом."
            )

            result = ai_provider.generate_response(
                system_prompt=system_prompt,
                user_message=text[:500],
                max_tokens=10,
                temperature=0.1,
                use_cache=False
            )

            content = result['content'].strip().lower()

            # Валидация ответа
            if content in MOOD_SCORES:
                mood = content
            else:
                # Пытаемся найти слово из списка в ответе
                for m in MOOD_SCORES:
                    if m in content:
                        mood = m
                        break
                else:
                    mood = 'neutral'

            score = MOOD_SCORES[mood]
            confidence = 0.9

            # Кэширование
            self._analysis_cache[cache_key] = (mood, score, time.time())

            return mood, score, confidence

        except Exception as e:
            logger.warning(f"MoodAnalyzer: AI анализ не удался: {e}")
            return self.quick_analyze(text)

    # ─── Запись настроения ───

    def record_mood(
        self,
        user_id: int,
        channel_id: int,
        mood: str,
        score: float,
        confidence: float,
        message_snippet: str
    ) -> None:
        """Записать настроение пользователя."""
        entry = MoodEntry(
            user_id=user_id,
            mood=mood,
            score=score,
            confidence=confidence,
            message_snippet=message_snippet
        )

        with self._lock:
            self._user_moods[user_id].append(entry)
            self._channel_moods[channel_id].append(entry)

    async def analyze_and_record(
        self,
        user_id: int,
        channel_id: int,
        text: str,
        use_ai: bool = False
    ) -> Tuple[str, float]:
        """
        Анализирует текст и записывает результат.
        
        Returns:
            (mood, score)
        """
        if use_ai:
            mood, score, confidence = await self.ai_analyze(text)
        else:
            mood, score, confidence = self.quick_analyze(text)

        self.record_mood(
            user_id=user_id,
            channel_id=channel_id,
            mood=mood,
            score=score,
            confidence=confidence,
            message_snippet=text
        )

        return mood, score

    # ─── Статистика пользователя ───

    def get_user_mood(self, user_id: int) -> Dict[str, Any]:
        """Текущее настроение пользователя (усреднённое)."""
        entries = list(self._user_moods.get(user_id, []))
        if not entries:
            return {
                'mood': 'neutral',
                'emoji': MOOD_EMOJIS['neutral'],
                'score': 0.0,
                'trend': 'stable',
                'samples': 0,
            }

        # Фильтрация по времени
        cutoff = time.time() - self.history_window_hours * 3600
        recent = [e for e in entries if e.timestamp > cutoff]

        if not recent:
            return {
                'mood': 'neutral',
                'emoji': MOOD_EMOJIS['neutral'],
                'score': 0.0,
                'trend': 'stable',
                'samples': 0,
            }

        # Взвешенное среднее (более свежие сообщения важнее)
        total_weight = 0
        weighted_score = 0
        now = time.time()

        for e in recent:
            age_hours = (now - e.timestamp) / 3600
            weight = max(0.1, 1.0 - age_hours / self.history_window_hours)
            weighted_score += e.score * weight * e.confidence
            total_weight += weight * e.confidence

        avg_score = weighted_score / total_weight if total_weight > 0 else 0

        # Определяем mood по score
        mood = self._score_to_mood(avg_score)

        # Определяем тренд
        trend = self._calculate_trend(recent)

        return {
            'mood': mood,
            'emoji': MOOD_EMOJIS.get(mood, '❓'),
            'score': round(avg_score, 3),
            'trend': trend,
            'samples': len(recent),
            'last_mood': recent[-1].mood if recent else 'neutral',
        }

    def _score_to_mood(self, score: float) -> str:
        """Преобразование числового score в название настроения."""
        if score >= 0.8:
            return 'ecstatic'
        elif score >= 0.6:
            return 'happy'
        elif score >= 0.3:
            return 'positive'
        elif score >= -0.15:
            return 'neutral'
        elif score >= -0.35:
            return 'bored'
        elif score >= -0.55:
            return 'sad'
        elif score >= -0.75:
            return 'angry'
        else:
            return 'toxic'

    def _calculate_trend(self, entries: List[MoodEntry]) -> str:
        """Определяет тренд: improving, declining, stable."""
        if len(entries) < 4:
            return 'stable'

        mid = len(entries) // 2
        first_half = entries[:mid]
        second_half = entries[mid:]

        avg_first = sum(e.score for e in first_half) / len(first_half)
        avg_second = sum(e.score for e in second_half) / len(second_half)

        diff = avg_second - avg_first

        if diff > 0.2:
            return 'improving'
        elif diff < -0.2:
            return 'declining'
        else:
            return 'stable'

    # ─── Статистика канала / сервера ───

    def get_channel_mood(self, channel_id: int) -> Dict[str, Any]:
        """Настроение канала (баланс положительных/отрицательных)."""
        entries = list(self._channel_moods.get(channel_id, []))
        if not entries:
            return {
                'mood': 'neutral',
                'emoji': MOOD_EMOJIS['neutral'],
                'avg_score': 0.0,
                'positive_percent': 50,
                'negative_percent': 50,
                'participants': 0,
            }

        cutoff = time.time() - self.history_window_hours * 3600
        recent = [e for e in entries if e.timestamp > cutoff]

        if not recent:
            return self.get_channel_mood.__wrapped__() if hasattr(self.get_channel_mood, '__wrapped__') else {
                'mood': 'neutral', 'emoji': MOOD_EMOJIS['neutral'],
                'avg_score': 0.0, 'positive_percent': 50,
                'negative_percent': 50, 'participants': 0,
            }

        scores = [e.score for e in recent]
        avg = sum(scores) / len(scores)
        positive = len([s for s in scores if s > 0.1])
        negative = len([s for s in scores if s < -0.1])
        total = len(scores)

        unique_users = len(set(e.user_id for e in recent))

        return {
            'mood': self._score_to_mood(avg),
            'emoji': MOOD_EMOJIS.get(self._score_to_mood(avg), '❓'),
            'avg_score': round(avg, 3),
            'positive_percent': round(positive / total * 100) if total > 0 else 50,
            'negative_percent': round(negative / total * 100) if total > 0 else 50,
            'participants': unique_users,
            'total_messages_analyzed': total,
        }

    def get_mood_leaderboard(self, channel_id: Optional[int] = None, limit: int = 10) -> List[Dict[str, Any]]:
        """Лидерборд настроения — кто самый позитивный."""
        user_ids = set()
        if channel_id:
            entries = self._channel_moods.get(channel_id, [])
            user_ids = set(e.user_id for e in entries)
        else:
            user_ids = set(self._user_moods.keys())

        board = []
        for uid in user_ids:
            mood_data = self.get_user_mood(uid)
            if mood_data['samples'] > 0:
                board.append({
                    'user_id': uid,
                    'mood': mood_data['mood'],
                    'emoji': mood_data['emoji'],
                    'score': mood_data['score'],
                    'trend': mood_data['trend'],
                    'samples': mood_data['samples'],
                })

        board.sort(key=lambda x: x['score'], reverse=True)
        return board[:limit]

    # ─── Промпт для AI ───

    def get_mood_context_for_ai(self, user_id: int, channel_id: int) -> str:
        """Генерирует строку контекста настроения для промпта AI."""
        user_mood = self.get_user_mood(user_id)
        channel_mood = self.get_channel_mood(channel_id)

        parts = []
        parts.append(
            f"🎭 **НАСТРОЕНИЕ ПОЛЬЗОВАТЕЛЯ:** {user_mood['emoji']} {user_mood['mood']} "
            f"(score: {user_mood['score']}, тренд: {user_mood['trend']})"
        )
        parts.append(
            f"📊 **АТМОСФЕРА КАНАЛА:** {channel_mood['emoji']} {channel_mood['mood']} "
            f"(позитив {channel_mood['positive_percent']}% / негатив {channel_mood['negative_percent']}%)"
        )

        if user_mood['trend'] == 'declining':
            parts.append("⚠️ Настроение пользователя ухудшается — будь особенно внимательным и поддерживающим.")
        elif user_mood['score'] < -0.4:
            parts.append("💙 Пользователь, похоже, расстроен — будь мягким и эмпатичным.")
        elif user_mood['score'] > 0.6:
            parts.append("🌟 Пользователь в отличном настроении — поддержи его энергию!")

        return "\n".join(parts)

    # ─── Общая статистика ───

    def get_stats(self) -> Dict[str, Any]:
        """Общая статистика системы mood analysis."""
        total_user_entries = sum(len(v) for v in self._user_moods.values())
        total_channel_entries = sum(len(v) for v in self._channel_moods.values())

        return {
            'users_tracked': len(self._user_moods),
            'channels_tracked': len(self._channel_moods),
            'total_user_mood_entries': total_user_entries,
            'total_channel_mood_entries': total_channel_entries,
            'cache_size': len(self._analysis_cache),
        }


# Глобальный экземпляр
mood_analyzer = MoodAnalyzer()
