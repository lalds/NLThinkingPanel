"""
Персональная база знаний сервера (Knowledge Base).

Wiki-подобная система для сохранения важной информации сервера.

Возможности:
 - Создание, редактирование и поиск статей
 - Теги и категории
 - Полнотекстовый поиск (SQLite FTS5)
 - Версионирование (история изменений)
 - AI-подсказки на основе базы знаний
 - Авторство и статистика
"""
import json
import time
import sqlite3
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime
from threading import Lock

from core.logger import logger


class KnowledgeArticle:
    """Статья в базе знаний."""

    def __init__(
        self,
        article_id: int,
        title: str,
        content: str,
        guild_id: int,
        author_id: int,
        author_name: str,
        tags: List[str] = None,
        category: str = "general",
        created_at: float = None,
        updated_at: float = None,
        views: int = 0,
        is_pinned: bool = False,
    ):
        self.article_id = article_id
        self.title = title
        self.content = content
        self.guild_id = guild_id
        self.author_id = author_id
        self.author_name = author_name
        self.tags = tags or []
        self.category = category
        self.created_at = created_at or time.time()
        self.updated_at = updated_at or time.time()
        self.views = views
        self.is_pinned = is_pinned


class KnowledgeBase:
    """База знаний сервера."""

    def __init__(self, db_path: str = 'data/knowledge_base.db'):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()

        self._init_db()

    def _init_db(self):
        """Инициализация базы данных."""
        with sqlite3.connect(str(self.db_path)) as conn:
            cursor = conn.cursor()

            # Основная таблица статей
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS articles (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    content TEXT NOT NULL,
                    guild_id INTEGER NOT NULL,
                    author_id INTEGER NOT NULL,
                    author_name TEXT DEFAULT '',
                    tags TEXT DEFAULT '[]',
                    category TEXT DEFAULT 'general',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    views INTEGER DEFAULT 0,
                    is_pinned INTEGER DEFAULT 0,
                    is_deleted INTEGER DEFAULT 0
                )
            ''')

            # Таблица версий (история изменений)
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS article_versions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    article_id INTEGER NOT NULL,
                    title TEXT NOT NULL,
                    content TEXT NOT NULL,
                    editor_id INTEGER NOT NULL,
                    editor_name TEXT DEFAULT '',
                    edited_at REAL NOT NULL,
                    change_reason TEXT DEFAULT '',
                    FOREIGN KEY (article_id) REFERENCES articles(id)
                )
            ''')

            # Полнотекстовый поиск
            cursor.execute('''
                CREATE VIRTUAL TABLE IF NOT EXISTS articles_fts USING fts5(
                    title, content, tags, category,
                    content_rowid='id',
                    tokenize='unicode61'
                )
            ''')

            # Индексы
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_articles_guild ON articles(guild_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_articles_category ON articles(category)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_articles_author ON articles(author_id)')

            conn.commit()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    # ─── Создание и редактирование ───

    def create_article(
        self,
        title: str,
        content: str,
        guild_id: int,
        author_id: int,
        author_name: str = "",
        tags: List[str] = None,
        category: str = "general",
    ) -> Tuple[Optional[int], str]:
        """
        Создать новую статью.
        
        Returns:
            (article_id, error_message)
        """
        if not title or len(title) > 200:
            return None, "Название должно быть от 1 до 200 символов"
        if not content or len(content) > 10000:
            return None, "Содержание должно быть от 1 до 10000 символов"

        tags = tags or []
        tags_json = json.dumps(tags, ensure_ascii=False)
        now = time.time()

        with self._lock:
            try:
                with self._get_connection() as conn:
                    cursor = conn.cursor()

                    # Проверка дубликата названия на том же сервере
                    cursor.execute(
                        'SELECT id FROM articles WHERE title = ? AND guild_id = ? AND is_deleted = 0',
                        (title, guild_id)
                    )
                    if cursor.fetchone():
                        return None, f"Статья с названием '{title}' уже существует"

                    cursor.execute('''
                        INSERT INTO articles 
                        (title, content, guild_id, author_id, author_name, tags, category, created_at, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (title, content, guild_id, author_id, author_name, tags_json, category, now, now))

                    article_id = cursor.lastrowid

                    # FTS
                    cursor.execute('''
                        INSERT INTO articles_fts (rowid, title, content, tags, category)
                        VALUES (?, ?, ?, ?, ?)
                    ''', (article_id, title, content, ' '.join(tags), category))

                    # Первая версия
                    cursor.execute('''
                        INSERT INTO article_versions
                        (article_id, title, content, editor_id, editor_name, edited_at, change_reason)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    ''', (article_id, title, content, author_id, author_name, now, 'Создание статьи'))

                    conn.commit()

                logger.info(f"Создана статья #{article_id}: '{title}' (guild={guild_id})")
                return article_id, ""

            except Exception as e:
                logger.error(f"Ошибка создания статьи: {e}")
                return None, str(e)

    def edit_article(
        self,
        article_id: int,
        new_content: str,
        editor_id: int,
        editor_name: str = "",
        new_title: str = None,
        new_tags: List[str] = None,
        change_reason: str = "",
    ) -> Tuple[bool, str]:
        """Редактирование статьи."""
        if len(new_content) > 10000:
            return False, "Содержание слишком длинное (макс 10000)"

        now = time.time()

        with self._lock:
            try:
                with self._get_connection() as conn:
                    cursor = conn.cursor()

                    cursor.execute(
                        'SELECT * FROM articles WHERE id = ? AND is_deleted = 0',
                        (article_id,)
                    )
                    article = cursor.fetchone()
                    if not article:
                        return False, "Статья не найдена"

                    title = new_title or article['title']
                    tags = new_tags if new_tags is not None else json.loads(article['tags'])
                    tags_json = json.dumps(tags, ensure_ascii=False)

                    # Сохраняем версию
                    cursor.execute('''
                        INSERT INTO article_versions
                        (article_id, title, content, editor_id, editor_name, edited_at, change_reason)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    ''', (article_id, title, new_content, editor_id, editor_name, now, change_reason))

                    # Обновляем статью
                    cursor.execute('''
                        UPDATE articles
                        SET title = ?, content = ?, tags = ?, updated_at = ?
                        WHERE id = ?
                    ''', (title, new_content, tags_json, now, article_id))

                    # Обновляем FTS
                    cursor.execute('DELETE FROM articles_fts WHERE rowid = ?', (article_id,))
                    cursor.execute('''
                        INSERT INTO articles_fts (rowid, title, content, tags, category)
                        VALUES (?, ?, ?, ?, ?)
                    ''', (article_id, title, new_content, ' '.join(tags), article['category']))

                    conn.commit()

                return True, ""

            except Exception as e:
                logger.error(f"Ошибка редактирования статьи: {e}")
                return False, str(e)

    def delete_article(self, article_id: int, user_id: int) -> bool:
        """Мягкое удаление статьи."""
        with self._lock:
            try:
                with self._get_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute(
                        'UPDATE articles SET is_deleted = 1 WHERE id = ?',
                        (article_id,)
                    )
                    conn.commit()
                return cursor.rowcount > 0
            except Exception as e:
                logger.error(f"Ошибка удаления статьи: {e}")
                return False

    # ─── Поиск ───

    def search(
        self,
        query: str,
        guild_id: int,
        limit: int = 10,
        category: str = None
    ) -> List[Dict[str, Any]]:
        """Полнотекстовый поиск по базе знаний."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()

                # Sanitize query for FTS5 simple usage
                # Removing characters that interfere with FTS5 syntax if not properly handled
                safe_query = query.replace('"', '').replace("'", '').replace(':', ' ').strip()
                if not safe_query:
                    return []
                
                # Wrap in quotes to treat as a phrase/string literal match for safety
                formatted_query = f'"{safe_query}"' 

                sql = '''
                    SELECT a.id, a.title, a.content, a.author_name, a.tags, 
                           a.category, a.views, a.is_pinned, a.created_at, a.updated_at,
                           rank
                    FROM articles_fts
                    JOIN articles a ON a.id = articles_fts.rowid
                    WHERE articles_fts MATCH ? AND a.guild_id = ? AND a.is_deleted = 0
                '''
                params = [formatted_query, guild_id]

                if category:
                    sql += ' AND a.category = ?'
                    params.append(category)

                sql += ' ORDER BY rank LIMIT ?'
                params.append(limit)

                cursor.execute(sql, params)
                rows = cursor.fetchall()

                results = []
                for row in rows:
                    results.append({
                        'id': row['id'],
                        'title': row['title'],
                        'content': row['content'][:300] + '...' if len(row['content']) > 300 else row['content'],
                        'author': row['author_name'],
                        'tags': json.loads(row['tags']),
                        'category': row['category'],
                        'views': row['views'],
                        'pinned': bool(row['is_pinned']),
                        'created': datetime.fromtimestamp(row['created_at']).strftime('%Y-%m-%d'),
                    })

                return results

        except Exception as e:
            logger.error(f"Ошибка поиска в KB: {e}")
            return []

    def get_article(self, article_id: int, increment_views: bool = True) -> Optional[Dict[str, Any]]:
        """Получить статью по ID."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()

                if increment_views:
                    cursor.execute(
                        'UPDATE articles SET views = views + 1 WHERE id = ? AND is_deleted = 0',
                        (article_id,)
                    )

                cursor.execute(
                    'SELECT * FROM articles WHERE id = ? AND is_deleted = 0',
                    (article_id,)
                )
                row = cursor.fetchone()

                if not row:
                    return None

                return {
                    'id': row['id'],
                    'title': row['title'],
                    'content': row['content'],
                    'author_id': row['author_id'],
                    'author': row['author_name'],
                    'tags': json.loads(row['tags']),
                    'category': row['category'],
                    'views': row['views'],
                    'pinned': bool(row['is_pinned']),
                    'created': datetime.fromtimestamp(row['created_at']).strftime('%Y-%m-%d %H:%M'),
                    'updated': datetime.fromtimestamp(row['updated_at']).strftime('%Y-%m-%d %H:%M'),
                }

        except Exception as e:
            logger.error(f"Ошибка получения статьи: {e}")
            return None

    def list_articles(
        self,
        guild_id: int,
        category: str = None,
        limit: int = 20,
        sort_by: str = 'updated'
    ) -> List[Dict[str, Any]]:
        """Получить список статей."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()

                sql = 'SELECT * FROM articles WHERE guild_id = ? AND is_deleted = 0'
                params = [guild_id]

                if category:
                    sql += ' AND category = ?'
                    params.append(category)

                order_map = {
                    'updated': 'updated_at DESC',
                    'created': 'created_at DESC',
                    'views': 'views DESC',
                    'title': 'title ASC',
                }
                sql += f' ORDER BY is_pinned DESC, {order_map.get(sort_by, "updated_at DESC")}'
                sql += ' LIMIT ?'
                params.append(limit)

                cursor.execute(sql, params)
                rows = cursor.fetchall()

                return [
                    {
                        'id': row['id'],
                        'title': row['title'],
                        'preview': row['content'][:100] + '...' if len(row['content']) > 100 else row['content'],
                        'author': row['author_name'],
                        'category': row['category'],
                        'tags': json.loads(row['tags']),
                        'views': row['views'],
                        'pinned': bool(row['is_pinned']),
                        'updated': datetime.fromtimestamp(row['updated_at']).strftime('%Y-%m-%d'),
                    }
                    for row in rows
                ]

        except Exception as e:
            logger.error(f"Ошибка списка статей: {e}")
            return []

    # ─── Версии ───

    def get_article_history(self, article_id: int, limit: int = 10) -> List[Dict[str, Any]]:
        """История изменений статьи."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT * FROM article_versions
                    WHERE article_id = ?
                    ORDER BY edited_at DESC
                    LIMIT ?
                ''', (article_id, limit))

                return [
                    {
                        'version_id': row['id'],
                        'editor': row['editor_name'],
                        'edited_at': datetime.fromtimestamp(row['edited_at']).strftime('%Y-%m-%d %H:%M'),
                        'reason': row['change_reason'],
                        'title': row['title'],
                        'content_preview': row['content'][:200],
                    }
                    for row in cursor.fetchall()
                ]

        except Exception as e:
            logger.error(f"Ошибка получения истории: {e}")
            return []

    # ─── Категории и теги ───

    def get_categories(self, guild_id: int) -> List[Dict[str, Any]]:
        """Получить все категории и количество статей в каждой."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT category, COUNT(*) as count
                    FROM articles
                    WHERE guild_id = ? AND is_deleted = 0
                    GROUP BY category
                    ORDER BY count DESC
                ''', (guild_id,))

                return [
                    {'name': row['category'], 'count': row['count']}
                    for row in cursor.fetchall()
                ]

        except Exception as e:
            logger.error(f"Ошибка получения категорий: {e}")
            return []

    def get_popular_tags(self, guild_id: int, limit: int = 20) -> List[Tuple[str, int]]:
        """Получить популярные теги."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    'SELECT tags FROM articles WHERE guild_id = ? AND is_deleted = 0',
                    (guild_id,)
                )

                tag_counts: Dict[str, int] = {}
                for row in cursor.fetchall():
                    tags = json.loads(row['tags'])
                    for tag in tags:
                        tag_counts[tag] = tag_counts.get(tag, 0) + 1

                sorted_tags = sorted(tag_counts.items(), key=lambda x: x[1], reverse=True)
                return sorted_tags[:limit]

        except Exception as e:
            logger.error(f"Ошибка получения тегов: {e}")
            return []

    # ─── AI контекст ───

    def get_relevant_for_ai(self, query: str, guild_id: int, limit: int = 3) -> str:
        """
        Получить релевантные статьи для контекста AI.
        Используется ContextBuilder'ом для обогащения ответов.
        """
        results = self.search(query, guild_id, limit=limit)
        if not results:
            return ""

        parts = ["\n📚 **РЕЛЕВАНТНЫЕ СТАТЬИ ИЗ БАЗЫ ЗНАНИЙ:**"]
        for r in results:
            parts.append(f"- **{r['title']}** [{r['category']}]: {r['content'][:200]}")

        return "\n".join(parts)

    # ─── Статистика ───

    def get_stats(self, guild_id: int = None) -> Dict[str, Any]:
        """Статистика базы знаний."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()

                where = 'WHERE is_deleted = 0'
                params = []
                if guild_id:
                    where += ' AND guild_id = ?'
                    params.append(guild_id)

                cursor.execute(f'SELECT COUNT(*) as cnt FROM articles {where}', params)
                total = cursor.fetchone()['cnt']

                cursor.execute(f'SELECT COALESCE(SUM(views), 0) as total FROM articles {where}', params)
                total_views = cursor.fetchone()['total']

                cursor.execute(f'SELECT COUNT(DISTINCT author_id) as cnt FROM articles {where}', params)
                authors = cursor.fetchone()['cnt']

                cursor.execute(f'SELECT COUNT(DISTINCT category) as cnt FROM articles {where}', params)
                categories = cursor.fetchone()['cnt']

                return {
                    'total_articles': total,
                    'total_views': total_views,
                    'unique_authors': authors,
                    'categories': categories,
                }

        except Exception as e:
            logger.error(f"Ошибка получения статистики KB: {e}")
            return {'total_articles': 0, 'total_views': 0}

    # ─── Pin ───

    def pin_article(self, article_id: int) -> bool:
        """Закрепить статью."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    'UPDATE articles SET is_pinned = 1 WHERE id = ?',
                    (article_id,)
                )
                conn.commit()
            return True
        except Exception:
            return False

    def unpin_article(self, article_id: int) -> bool:
        """Открепить статью."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    'UPDATE articles SET is_pinned = 0 WHERE id = ?',
                    (article_id,)
                )
                conn.commit()
            return True
        except Exception:
            return False


# Глобальный экземпляр
knowledge_base = KnowledgeBase()
