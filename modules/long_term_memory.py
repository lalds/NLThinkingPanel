"""
Модуль долговременной памяти (Cold Memory).
Использует SQLite для хранения истории и поиска релевантных фрагментов (RAG-lite).
"""
import os
import sys
import sqlite3
from pathlib import Path
from typing import List, Dict, Any, Optional
from datetime import datetime

# Добавляем корень проекта в путь поиска модулей, если файл запущен напрямую
if __name__ == "__main__":
    sys.path.append(str(Path(__file__).parent.parent))

from core.logger import logger

class LongTermMemory:
    """Менеджер архивной памяти с возможностью поиска."""
    
    def __init__(self, db_path: str = 'data/memory_archive.db'):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
        
    def _init_db(self):
        """Инициализация таблиц базы данных."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                # Основная таблица сообщений
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS messages (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        channel_id INTEGER,
                        author TEXT,
                        content TEXT,
                        timestamp DATETIME
                    )
                ''')
                # Индекс для быстрого поиска по тексту
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_content ON messages(content)')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_channel ON messages(channel_id)')
                conn.commit()
        except Exception as e:
            logger.error(f"Ошибка инициализации БД памяти: {e}")

    def add_entry(self, channel_id: int, author: str, content: str):
        """Добавление сообщения в архив."""
        if len(content) < 5:  # Игнорируем слишком короткие сообщения
            return
            
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    'INSERT INTO messages (channel_id, author, content, timestamp) VALUES (?, ?, ?, ?)',
                    (channel_id, author, content, datetime.now().isoformat())
                )
                conn.commit()
        except Exception as e:
            logger.error(f"Ошибка сохранения в архив: {e}")

    def search_relevant(self, channel_id: int, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """
        Поиск релевантных сообщений в архиве для текущего канала.
        Простая реализация RAG на основе ключевых слов.
        """
        # Очищаем запрос от лишних слов
        ignored_words = {'как', 'что', 'кто', 'где', 'когда', 'почему', 'это', 'был', 'была'}
        words = [w.lower() for w in query.split() if len(w) > 3 and w.lower() not in ignored_words]
        
        if not words:
            return []
            
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                
                # Строим динамический запрос для поиска слов
                search_conditions = ' OR '.join(['content LIKE ?' for _ in words])
                sql = f'''
                    SELECT author, content, timestamp 
                    FROM messages 
                    WHERE channel_id = ? AND ({search_conditions})
                    ORDER BY timestamp DESC
                    LIMIT ?
                '''
                
                params = [channel_id] + [f'%{w}%' for w in words] + [limit]
                cursor.execute(sql, params)
                
                return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Ошибка поиска в архиве: {e}")
            return []

    def get_stats(self) -> Dict[str, Any]:
        """Статистика памяти."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT COUNT(*) FROM messages')
                count = cursor.fetchone()[0]
                cursor.execute('SELECT COUNT(DISTINCT channel_id) FROM messages')
                channels = cursor.fetchone()[0]
                return {'total_entries': count, 'total_channels': channels}
        except:
            return {'total_entries': 0, 'total_channels': 0}

# Глобальный экземпляр
long_term_memory = LongTermMemory()
