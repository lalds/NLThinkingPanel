"""
Система многоходовых диалогов (Conversation Chains).

Позволяет вести полноценные многоходовые диалоги с AI,
сохраняя полный контекст переписки в рамках цепочки.

Поддерживает:
 - Создание и управление цепочками (chainам)
 - Автоматическое создание chain при DM
 - Суммаризацию длинных цепочек (сжатие контекста)
 - Форки (ответвления) от существующих цепочек
 - Экспорт диалога в текст
"""
import json
import time
import hashlib
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime
from collections import defaultdict
from threading import Lock

from core.logger import logger


# @dataclass_replacement = None  # We won't use dataclass for slots optimization


class ConversationMessage:
    """Сообщение в цепочке."""
    __slots__ = ('role', 'content', 'author_name', 'timestamp', 'tokens_estimated')

    def __init__(self, role: str, content: str, author_name: str = "",
                 timestamp: float = None, tokens_estimated: int = 0):
        self.role = role  # 'user', 'assistant', 'system'
        self.content = content
        self.author_name = author_name
        self.timestamp = timestamp or time.time()
        self.tokens_estimated = tokens_estimated or len(content) // 4

    def to_dict(self) -> dict:
        return {
            'role': self.role,
            'content': self.content,
            'author_name': self.author_name,
            'timestamp': self.timestamp,
            'tokens_estimated': self.tokens_estimated,
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'ConversationMessage':
        return cls(
            role=data['role'],
            content=data['content'],
            author_name=data.get('author_name', ''),
            timestamp=data.get('timestamp', time.time()),
            tokens_estimated=data.get('tokens_estimated', 0),
        )


class ConversationChain:
    """Цепочка диалога."""

    def __init__(
        self,
        chain_id: str,
        channel_id: int,
        creator_id: int,
        creator_name: str,
        title: str = "Новый диалог",
        system_prompt: str = "",
        max_messages: int = 50,
        parent_chain_id: Optional[str] = None,
    ):
        self.chain_id = chain_id
        self.channel_id = channel_id
        self.creator_id = creator_id
        self.creator_name = creator_name
        self.title = title
        self.system_prompt = system_prompt
        self.max_messages = max_messages
        self.parent_chain_id = parent_chain_id

        self.messages: List[ConversationMessage] = []
        self.created_at = time.time()
        self.updated_at = time.time()
        self.is_active = True
        self.total_tokens_used = 0
        self.summary: Optional[str] = None  # Суммаризация старых сообщений

        # Участники (user_id -> display_name)
        self.participants: Dict[int, str] = {creator_id: creator_name}

    def add_message(self, role: str, content: str, author_name: str = "") -> ConversationMessage:
        """Добавить сообщение в цепочку."""
        msg = ConversationMessage(role=role, content=content, author_name=author_name)
        self.messages.append(msg)
        self.updated_at = time.time()
        self.total_tokens_used += msg.tokens_estimated

        # Если слишком много сообщений — оставляем только последние
        if len(self.messages) > self.max_messages:
            self._compress_old_messages()

        return msg

    def _compress_old_messages(self):
        """Сжатие старых сообщений в суммарий."""
        keep_count = self.max_messages // 2
        old_messages = self.messages[:-keep_count]
        self.messages = self.messages[-keep_count:]

        # Создаём текстовый суммарий
        summary_parts = []
        if self.summary:
            summary_parts.append(self.summary)

        summary_parts.append("\n--- Сжатый контекст ---")
        for msg in old_messages:
            role_prefix = "🤖" if msg.role == "assistant" else f"👤 {msg.author_name}"
            summary_parts.append(f"{role_prefix}: {msg.content[:150]}...")

        self.summary = "\n".join(summary_parts)[-2000:]  # Max 2000 символов

    def get_messages_for_api(self) -> List[Dict[str, str]]:
        """Получить сообщения в формате OpenAI API."""
        api_messages = []

        # System prompt
        system_content = self.system_prompt
        if self.summary:
            system_content += f"\n\n📋 ПРЕДЫДУЩИЙ КОНТЕКСТ:\n{self.summary}"

        api_messages.append({"role": "system", "content": system_content})

        # Сообщения
        for msg in self.messages:
            api_messages.append({
                "role": msg.role,
                "content": msg.content
            })

        return api_messages

    def get_context_window_tokens(self) -> int:
        """Примерная оценка токенов в текущем окне."""
        total = len(self.system_prompt) // 4
        if self.summary:
            total += len(self.summary) // 4
        for msg in self.messages:
            total += msg.tokens_estimated
        return total

    def export_text(self) -> str:
        """Экспорт цепочки в читаемый текст."""
        lines = [
            f"═══ Диалог: {self.title} ═══",
            f"ID: {self.chain_id}",
            f"Создано: {datetime.fromtimestamp(self.created_at).strftime('%Y-%m-%d %H:%M')}",
            f"Участники: {', '.join(self.participants.values())}",
            f"Сообщений: {len(self.messages)}",
            "═" * 40,
            ""
        ]

        if self.summary:
            lines.append(f"[Суммарий предыдущего контекста]\n{self.summary}\n")
            lines.append("─" * 40)

        for msg in self.messages:
            dt = datetime.fromtimestamp(msg.timestamp).strftime('%H:%M:%S')
            if msg.role == 'user':
                prefix = f"[{dt}] 👤 {msg.author_name}"
            elif msg.role == 'assistant':
                prefix = f"[{dt}] 🤖 AI"
            else:
                prefix = f"[{dt}] ⚙️ System"
            lines.append(f"{prefix}:\n{msg.content}\n")

        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {
            'chain_id': self.chain_id,
            'channel_id': self.channel_id,
            'creator_id': self.creator_id,
            'creator_name': self.creator_name,
            'title': self.title,
            'system_prompt': self.system_prompt,
            'max_messages': self.max_messages,
            'parent_chain_id': self.parent_chain_id,
            'messages': [m.to_dict() for m in self.messages],
            'created_at': self.created_at,
            'updated_at': self.updated_at,
            'is_active': self.is_active,
            'total_tokens_used': self.total_tokens_used,
            'summary': self.summary,
            'participants': {str(k): v for k, v in self.participants.items()},
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'ConversationChain':
        chain = cls(
            chain_id=data['chain_id'],
            channel_id=data['channel_id'],
            creator_id=data['creator_id'],
            creator_name=data['creator_name'],
            title=data.get('title', 'Диалог'),
            system_prompt=data.get('system_prompt', ''),
            max_messages=data.get('max_messages', 50),
            parent_chain_id=data.get('parent_chain_id'),
        )
        chain.messages = [ConversationMessage.from_dict(m) for m in data.get('messages', [])]
        chain.created_at = data.get('created_at', time.time())
        chain.updated_at = data.get('updated_at', time.time())
        chain.is_active = data.get('is_active', True)
        chain.total_tokens_used = data.get('total_tokens_used', 0)
        chain.summary = data.get('summary')
        chain.participants = {
            int(k): v for k, v in data.get('participants', {}).items()
        }
        return chain


class ConversationManager:
    """Менеджер многоходовых диалогов."""

    def __init__(self, data_dir: str = 'data/conversations'):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()

        # channel_id -> chain_id (активная цепочка в канале)
        self._active_chains: Dict[int, str] = {}
        # chain_id -> ConversationChain
        self._chains: Dict[str, ConversationChain] = {}
        # user_id -> List[chain_id] (все цепочки пользователя)
        self._user_chains: Dict[int, List[str]] = defaultdict(list)

        self._load_all()

    def _load_all(self):
        """Загрузка всех сохранённых цепочек."""
        index_file = self.data_dir / 'index.json'
        if not index_file.exists():
            return

        try:
            with open(index_file, 'r', encoding='utf-8') as f:
                index = json.load(f)

            self._active_chains = {int(k): v for k, v in index.get('active_chains', {}).items()}

            for chain_file in self.data_dir.glob('chain_*.json'):
                try:
                    with open(chain_file, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    chain = ConversationChain.from_dict(data)
                    self._chains[chain.chain_id] = chain
                    self._user_chains[chain.creator_id].append(chain.chain_id)
                except Exception as e:
                    logger.warning(f"Не удалось загрузить цепочку {chain_file}: {e}")

            logger.info(f"Загружено {len(self._chains)} цепочек диалогов")

        except Exception as e:
            logger.error(f"Ошибка загрузки цепочек: {e}")

    def _save_chain(self, chain: ConversationChain):
        """Сохранение одной цепочки."""
        try:
            chain_file = self.data_dir / f'chain_{chain.chain_id}.json'
            with open(chain_file, 'w', encoding='utf-8') as f:
                json.dump(chain.to_dict(), f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Ошибка сохранения цепочки {chain.chain_id}: {e}")

    def _save_index(self):
        """Сохранение индекса."""
        try:
            index = {
                'active_chains': {str(k): v for k, v in self._active_chains.items()},
            }
            with open(self.data_dir / 'index.json', 'w', encoding='utf-8') as f:
                json.dump(index, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Ошибка сохранения индекса: {e}")

    # ─── Создание и управление ───

    def create_chain(
        self,
        channel_id: int,
        creator_id: int,
        creator_name: str,
        title: str = "Новый диалог",
        system_prompt: str = "",
        activate: bool = True
    ) -> ConversationChain:
        """Создать новую цепочку диалога."""
        chain_id = hashlib.sha256(
            f"{channel_id}-{creator_id}-{time.time()}".encode()
        ).hexdigest()[:12]

        chain = ConversationChain(
            chain_id=chain_id,
            channel_id=channel_id,
            creator_id=creator_id,
            creator_name=creator_name,
            title=title,
            system_prompt=system_prompt,
        )

        with self._lock:
            self._chains[chain_id] = chain
            self._user_chains[creator_id].append(chain_id)

            if activate:
                self._active_chains[channel_id] = chain_id

            self._save_chain(chain)
            self._save_index()

        logger.info(f"Создана цепочка '{title}' (ID: {chain_id}) в канале {channel_id}")
        return chain

    def get_active_chain(self, channel_id: int) -> Optional[ConversationChain]:
        """Получить активную цепочку в канале."""
        chain_id = self._active_chains.get(channel_id)
        if chain_id:
            chain = self._chains.get(chain_id)
            if chain and chain.is_active:
                return chain
        return None

    def get_or_create_chain(
        self,
        channel_id: int,
        user_id: int,
        user_name: str,
        system_prompt: str = ""
    ) -> ConversationChain:
        """Получить активную цепочку или создать новую."""
        chain = self.get_active_chain(channel_id)
        if chain:
            # Добавляем участника
            chain.participants[user_id] = user_name
            return chain

        return self.create_chain(
            channel_id=channel_id,
            creator_id=user_id,
            creator_name=user_name,
            system_prompt=system_prompt,
        )

    def deactivate_chain(self, channel_id: int) -> Optional[str]:
        """Деактивировать текущую цепочку в канале."""
        chain_id = self._active_chains.pop(channel_id, None)
        if chain_id and chain_id in self._chains:
            self._chains[chain_id].is_active = False
            self._save_chain(self._chains[chain_id])
            self._save_index()
            return chain_id
        return None

    def fork_chain(
        self,
        parent_chain_id: str,
        user_id: int,
        user_name: str,
        fork_title: str = ""
    ) -> Optional[ConversationChain]:
        """Создать форк (ответвление) от существующей цепочки."""
        parent = self._chains.get(parent_chain_id)
        if not parent:
            return None

        title = fork_title or f"Форк: {parent.title}"
        new_chain = self.create_chain(
            channel_id=parent.channel_id,
            creator_id=user_id,
            creator_name=user_name,
            title=title,
            system_prompt=parent.system_prompt,
            activate=True,
        )

        # Копируем историю
        new_chain.messages = [
            ConversationMessage(
                role=m.role,
                content=m.content,
                author_name=m.author_name,
                timestamp=m.timestamp,
            )
            for m in parent.messages
        ]
        new_chain.summary = parent.summary
        new_chain.parent_chain_id = parent_chain_id

        self._save_chain(new_chain)
        return new_chain

    # ─── Сообщения ───

    def add_message(
        self,
        chain_id: str,
        role: str,
        content: str,
        author_name: str = ""
    ) -> Optional[ConversationMessage]:
        """Добавить сообщение в цепочку."""
        chain = self._chains.get(chain_id)
        if not chain:
            return None

        msg = chain.add_message(role=role, content=content, author_name=author_name)
        self._save_chain(chain)
        return msg

    # ─── Список цепочек ───

    def get_user_chains(self, user_id: int, limit: int = 10) -> List[Dict[str, Any]]:
        """Получить список цепочек пользователя."""
        chain_ids = self._user_chains.get(user_id, [])
        chains = []

        for cid in chain_ids[-limit:]:
            chain = self._chains.get(cid)
            if chain:
                chains.append({
                    'chain_id': chain.chain_id,
                    'title': chain.title,
                    'messages': len(chain.messages),
                    'is_active': chain.is_active,
                    'created_at': datetime.fromtimestamp(chain.created_at).strftime('%Y-%m-%d %H:%M'),
                    'updated_at': datetime.fromtimestamp(chain.updated_at).strftime('%Y-%m-%d %H:%M'),
                    'participants': len(chain.participants),
                    'tokens_used': chain.total_tokens_used,
                })

        chains.sort(key=lambda x: x['updated_at'], reverse=True)
        return chains

    def get_channel_chains(self, channel_id: int, limit: int = 10) -> List[Dict[str, Any]]:
        """Получить список цепочек в канале."""
        chains = []
        for chain in self._chains.values():
            if chain.channel_id == channel_id:
                chains.append({
                    'chain_id': chain.chain_id,
                    'title': chain.title,
                    'creator': chain.creator_name,
                    'messages': len(chain.messages),
                    'is_active': chain.is_active,
                    'updated_at': datetime.fromtimestamp(chain.updated_at).strftime('%Y-%m-%d %H:%M'),
                })

        chains.sort(key=lambda x: x['updated_at'], reverse=True)
        return chains[:limit]

    # ─── Суммаризация ───

    async def summarize_chain(self, chain_id: str) -> Optional[str]:
        """Суммаризация цепочки через AI."""
        chain = self._chains.get(chain_id)
        if not chain or len(chain.messages) < 3:
            return None

        try:
            from modules.ai_provider import ai_provider

            dialog_text = "\n".join([
                f"{'User' if m.role == 'user' else 'AI'}: {m.content[:200]}"
                for m in chain.messages[-20:]
            ])

            result = await ai_provider.generate_response(
                system_prompt=(
                    "Ты — суммаризатор. Сделай краткое резюме диалога в 3-5 предложениях. "
                    "Упомяни: основную тему, ключевые решения, и текущий статус обсуждения."
                ),
                user_message=f"Диалог:\n{dialog_text}",
                max_tokens=200,
                temperature=0.3,
                use_cache=False
            )

            summary = result['content']
            chain.title = summary[:50].replace('\n', ' ') + "..."
            self._save_chain(chain)

            return summary

        except Exception as e:
            logger.error(f"Ошибка суммаризации цепочки {chain_id}: {e}")
            return None

    # ─── Статистика ───

    def get_stats(self) -> Dict[str, Any]:
        """Общая статистика системы цепочек."""
        active_count = sum(1 for c in self._chains.values() if c.is_active)
        total_messages = sum(len(c.messages) for c in self._chains.values())
        total_tokens = sum(c.total_tokens_used for c in self._chains.values())

        return {
            'total_chains': len(self._chains),
            'active_chains': active_count,
            'total_messages': total_messages,
            'total_tokens_used': total_tokens,
            'unique_users': len(self._user_chains),
            'active_channels': len(self._active_chains),
        }


# Глобальный экземпляр
conversation_manager = ConversationManager()
