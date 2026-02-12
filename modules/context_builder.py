"""
Модуль построения расширенного контекста для AI.
Собирает информацию о пользователях, истории сообщений, активности.
"""
import discord
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
from collections import defaultdict


class ContextBuilder:
    """Построитель контекста для AI с расширенной аналитикой."""
    
    def __init__(self, max_history: int = 10, context_window_hours: int = 24):
        """
        Args:
            max_history: Максимальное количество сообщений в истории
            context_window_hours: Временное окно для анализа активности (часы)
        """
        self.max_history = max_history
        self.context_window_hours = context_window_hours
        
        # Хранилище истории: channel_id -> list of messages
        self._message_history: Dict[int, List[Dict[str, Any]]] = defaultdict(list)
    
    def add_message(self, channel_id: int, author: str, content: str) -> None:
        """
        Добавление сообщения в историю канала.
        
        Args:
            channel_id: ID канала
            author: Имя автора
            content: Содержимое сообщения
        """
        message_data = {
            'author': author,
            'content': content,
            'timestamp': datetime.now()
        }
        
        history = self._message_history[channel_id]
        history.append(message_data)
        
        # Ограничение размера истории
        if len(history) > self.max_history:
            history.pop(0)
    
    def get_message_history(self, channel_id: int) -> str:
        """
        Получение отформатированной истории сообщений.
        
        Args:
            channel_id: ID канала
        
        Returns:
            Отформатированная строка с историей
        """
        history = self._message_history.get(channel_id, [])
        
        if not history:
            return "История сообщений пуста."
        
        # Фильтрация по временному окну
        cutoff_time = datetime.now() - timedelta(hours=self.context_window_hours)
        recent_messages = [
            msg for msg in history
            if msg['timestamp'] > cutoff_time
        ]
        
        if not recent_messages:
            return "Нет недавних сообщений в заданном временном окне."
        
        formatted = ["📜 **Последние сообщения:**"]
        for msg in recent_messages[-self.max_history:]:
            time_str = msg['timestamp'].strftime('%H:%M')
            formatted.append(f"[{time_str}] {msg['author']}: {msg['content'][:100]}")
        
        return "\n".join(formatted)
    
    def build_user_context(self, guild: discord.Guild) -> str:
        """
        Построение контекста о пользователях сервера.
        
        Args:
            guild: Discord Guild объект
        
        Returns:
            Отформатированная строка с информацией о пользователях
        """
        status_map = {
            'online': '🟢 Онлайн',
            'idle': '🟡 Не активен',
            'dnd': '🔴 Не беспокоить',
            'offline': '⚫ Оффлайн'
        }
        
        user_lines = []
        activity_stats = defaultdict(int)
        
        for member in guild.members:
            if member.bot:
                continue
            
            status = status_map.get(str(member.status), str(member.status))
            activities = []
            
            if member.activities:
                for activity in member.activities:
                    activity_str = self._format_activity(activity)
                    if activity_str:
                        activities.append(activity_str)
                        # Статистика активностей
                        if isinstance(activity, discord.Game):
                            activity_stats['gaming'] += 1
                        elif isinstance(activity, discord.Spotify):
                            activity_stats['spotify'] += 1
                        elif isinstance(activity, discord.Streaming):
                            activity_stats['streaming'] += 1
            
            activity_text = ", ".join(activities) if activities else "Ничего не делает"
            
            user_lines.append(
                f"• **{member.display_name}** ({member.name}) | {status} | {activity_text}"
            )
        
        # Добавление статистики
        stats_lines = ["", "📊 **Статистика активности:**"]
        if activity_stats:
            if activity_stats['gaming'] > 0:
                stats_lines.append(f"🎮 Играют: {activity_stats['gaming']} чел.")
            if activity_stats['spotify'] > 0:
                stats_lines.append(f"🎵 Слушают музыку: {activity_stats['spotify']} чел.")
            if activity_stats['streaming'] > 0:
                stats_lines.append(f"📺 Стримят: {activity_stats['streaming']} чел.")
        else:
            stats_lines.append("Нет активной деятельности")
        
        return "\n".join(user_lines + stats_lines)
    
    def _format_activity(self, activity) -> Optional[str]:
        """Форматирование активности пользователя."""
        if isinstance(activity, discord.Spotify):
            return f"🎵 Слушает **{activity.title}** от *{activity.artist}*"
        elif isinstance(activity, discord.Game):
            return f"🎮 Играет в **{activity.name}**"
        elif isinstance(activity, discord.Streaming):
            return f"📺 Стримит **{activity.name}**"
        elif isinstance(activity, discord.CustomActivity):
            if activity.name:
                return f"💭 {activity.name}"
        elif isinstance(activity, discord.Activity):
            type_map = {
                discord.ActivityType.listening: "🎧 Слушает",
                discord.ActivityType.watching: "👀 Смотрит",
                discord.ActivityType.competing: "🏆 Соревнуется в"
            }
            prefix = type_map.get(activity.type, "📌")
            return f"{prefix} **{activity.name}**"
        
        return None
    
    def build_full_context(
        self,
        guild: discord.Guild,
        channel_id: int,
        author_name: str,
        system_prompt: str
    ) -> str:
        """
        Построение полного контекста для AI.
        
        Args:
            guild: Discord Guild
            channel_id: ID канала
            author_name: Имя автора запроса
            system_prompt: Базовый системный промпт
        
        Returns:
            Полный системный промпт с контекстом
        """
        user_context = self.build_user_context(guild)
        message_history = self.get_message_history(channel_id)
        
        full_prompt = f"""{system_prompt}

🌐 **КОНТЕКСТ СЕРВЕРА: {guild.name}**

{user_context}

{message_history}

👤 **Пользователь, задающий вопрос:** {author_name}

⚡ **Инструкции:**
- Используй информацию о текущей активности пользователей для персонализированных ответов
- Учитывай историю недавних сообщений для понимания контекста разговора
- Будь дружелюбным, но профессиональным
- Если видишь, что несколько людей делают что-то похожее, можешь предложить им объединиться
"""
        
        return full_prompt
    
    def clear_history(self, channel_id: Optional[int] = None) -> None:
        """
        Очистка истории сообщений.
        
        Args:
            channel_id: ID канала (если None, очищается вся история)
        """
        if channel_id is None:
            self._message_history.clear()
        elif channel_id in self._message_history:
            self._message_history[channel_id].clear()


# Глобальный экземпляр
context_builder = ContextBuilder()
