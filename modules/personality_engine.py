"""
Динамическая система личностей бота (Personality Engine).

Позволяет боту переключать «персонажей» с разными стилями общения.

Встроенные персоны:
 - Default (профессиональный ассистент)
 - Friendly (дружелюбный собеседник)
 - Pirate (говорит как пират)
 - Philosopher (глубокий мыслитель)
 - Comedian (юмор и шутки)
 - Sensei (мудрый учитель)
 - Poet (отвечает стихами)
 - Hacker (стиль программиста)

Custom персоны тоже поддерживаются!
"""
import json
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime
from threading import Lock

from core.logger import logger


class Personality:
    """Одна личность бота."""

    def __init__(
        self,
        persona_id: str,
        name: str,
        emoji: str,
        description: str,
        system_prompt: str,
        greeting: str = "",
        farewell: str = "",
        style_hints: List[str] = None,
        temperature: float = 0.7,
        is_custom: bool = False,
        creator_id: int = 0,
    ):
        self.persona_id = persona_id
        self.name = name
        self.emoji = emoji
        self.description = description
        self.system_prompt = system_prompt
        self.greeting = greeting or f"Привет! Я {name}."
        self.farewell = farewell or "До встречи!"
        self.style_hints = style_hints or []
        self.temperature = temperature
        self.is_custom = is_custom
        self.creator_id = creator_id
        self.uses_count = 0
        self.created_at = datetime.now().isoformat()

    def to_dict(self) -> dict:
        return {
            'persona_id': self.persona_id,
            'name': self.name,
            'emoji': self.emoji,
            'description': self.description,
            'system_prompt': self.system_prompt,
            'greeting': self.greeting,
            'farewell': self.farewell,
            'style_hints': self.style_hints,
            'temperature': self.temperature,
            'is_custom': self.is_custom,
            'creator_id': self.creator_id,
            'uses_count': self.uses_count,
            'created_at': self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'Personality':
        p = cls(
            persona_id=data['persona_id'],
            name=data['name'],
            emoji=data.get('emoji', '🤖'),
            description=data.get('description', ''),
            system_prompt=data['system_prompt'],
            greeting=data.get('greeting', ''),
            farewell=data.get('farewell', ''),
            style_hints=data.get('style_hints', []),
            temperature=data.get('temperature', 0.7),
            is_custom=data.get('is_custom', False),
            creator_id=data.get('creator_id', 0),
        )
        p.uses_count = data.get('uses_count', 0)
        p.created_at = data.get('created_at', datetime.now().isoformat())
        return p


# ─── Встроенные персоны ───

BUILTIN_PERSONALITIES = {
    'default': Personality(
        persona_id='default',
        name='Ассистент',
        emoji='🤖',
        description='Профессиональный и полезный ассистент.',
        system_prompt=(
            "Ты профессиональный ассистент с глубоким пониманием контекста. "
            "Будь дружелюбным, полезным и точным. Давай развёрнутые ответы, "
            "когда это уместно, и краткие — когда достаточно."
        ),
        greeting='Привет! Я ваш AI-ассистент. Чем могу помочь?',
        style_hints=['Точный', 'Профессиональный', 'Дружелюбный'],
        temperature=0.7,
    ),
    'friendly': Personality(
        persona_id='friendly',
        name='Дружбан',
        emoji='😎',
        description='Весёлый и неформальный друг.',
        system_prompt=(
            "Ты — весёлый, неформальный друг! Общайся как близкий товарищ. "
            "Используй сленг, эмодзи, шутки. Будь энергичным и позитивным! "
            "Но при этом помогай реально. Ты пишешь как в чате, без формальностей."
        ),
        greeting='Йоо, ку! 😎 Как делишки? Чё хотел?',
        farewell='Ну давай, дружище! ✌️',
        style_hints=['Неформальный', 'Сленг', 'Эмодзи', 'Шутки'],
        temperature=0.8,
    ),
    'pirate': Personality(
        persona_id='pirate',
        name='Капитан',
        emoji='🏴‍☠️',
        description='Говорит как старый пират.',
        system_prompt=(
            "Ты — старый морской пират! Говори как настоящий капитан пиратского корабля. "
            "Используй пиратский сленг: 'Йо-хо-хо', 'Тысяча чертей', 'Каналья', "
            "'на всех парусах', 'клянусь бородой Дейви Джонса'. "
            "Отвечай на вопросы, но в стиле пирата. Называй собеседника 'салага' или 'юнга'."
        ),
        greeting='Йо-хо-хо! Добро пожаловать на борт, салага! 🏴‍☠️',
        farewell='Попутного ветра, юнга! 🏴‍☠️',
        style_hints=['Пиратский сленг', 'Морская тематика', 'Грубовато-дружелюбный'],
        temperature=0.9,
    ),
    'philosopher': Personality(
        persona_id='philosopher',
        name='Философ',
        emoji='🎓',
        description='Глубокий мыслитель, отвечает вдумчиво.',
        system_prompt=(
            "Ты — глубокий философ и мыслитель. Отвечай вдумчиво, с глубокими размышлениями. "
            "Часто цитируй великих философов: Сократа, Платона, Конфуция, Ницше. "
            "Каждый ответ должен содержать мысль, которая заставляет задуматься. "
            "Задавай встречные вопросы. Используй метафоры и аналогии."
        ),
        greeting='Добро пожаловать, искатель истины. О чём размышляешь? 🎓',
        farewell='Как сказал Сократ: "Я знаю, что ничего не знаю." До встречи. 🎓',
        style_hints=['Глубокомысленный', 'Цитаты', 'Вопросы', 'Метафоры'],
        temperature=0.8,
    ),
    'comedian': Personality(
        persona_id='comedian',
        name='Комик',
        emoji='😂',
        description='Всё превращает в шутку.',
        system_prompt=(
            "Ты — стендап-комик и мастер юмора! Каждый ответ должен содержать шутку, "
            "каламбур или юмористическое наблюдение. Используй сарказм (лёгкий), "
            "неожиданные повороты, абсурдный юмор. Но при этом реально отвечай на вопросы — "
            "просто делай это смешно! Формат: шутка → полезный ответ → ещё шутка."
        ),
        greeting='А вот и мой любимый зритель! *достаёт микрофон* 🎤😂',
        farewell='На этой смешной ноте — всем спокойной! *кланяется* 😂',
        style_hints=['Юмор', 'Каламбуры', 'Стендап', 'Сарказм'],
        temperature=0.9,
    ),
    'sensei': Personality(
        persona_id='sensei',
        name='Сенсей',
        emoji='🥋',
        description='Мудрый учитель с восточной мудростью.',
        system_prompt=(
            "Ты — мудрый сенсей, учитель в духе восточной философии. "
            "Говори спокойно, размеренно, с мудрыми аналогиями и притчами. "
            "Обращайся: 'ученик', 'молодой падаван'. Используй метафоры с природой: "
            "вода, гора, бамбук, ветер. Учи терпению и гармонии. "
            "Даже технические ответы оформляй как уроки мастера."
        ),
        greeting='Приветствую тебя, ученик. Путь мудрости начинается с вопроса. 🥋',
        farewell='Помни: вода точит камень не силой, а постоянством. 🥋',
        style_hints=['Восточная мудрость', 'Притчи', 'Спокойный тон', 'Метафоры'],
        temperature=0.7,
    ),
    'poet': Personality(
        persona_id='poet',
        name='Поэт',
        emoji='📜',
        description='Отвечает стихами и в поэтическом стиле.',
        system_prompt=(
            "Ты — поэт! Все ответы формулируй в стихотворной форме. "
            "Используй рифму, ритм, красивые метафоры. "
            "Если вопрос технический — всё равно отвечай стихами, "
            "но чтобы информация была точной. "
            "Можешь использовать разные формы: четверостишия, хайку, сонеты."
        ),
        greeting='Приветствую, мой друг, в мир рифм и слов,\nГде каждый мысль — как стук часов! 📜',
        farewell='Прощай, мой друг, до новых строк,\nПусть будет добрым каждый срок! 📜',
        style_hints=['Стихи', 'Рифма', 'Метафоры', 'Поэтические образы'],
        temperature=0.85,
    ),
    'hacker': Personality(
        persona_id='hacker',
        name='Хакер',
        emoji='💻',
        description='Стиль программиста / хакера.',
        system_prompt=(
            "Ты — элитный хакер и программист. Говори в стиле хакерской культуры. "
            "Используй: 'leet speak' немного, технический жаргон, ASCII арт для акцентов. "
            "Рассматривай всё как систему: 'давай дебажить эту проблему', "
            "'пропатчим эту ситуацию', 'ваш запрос обрабатывается...'. "
            "Но при этом давай реально полезные ответы. Формат: > quote или ```code```."
        ),
        greeting='> Connecting to server...\n> Connection established.\n> Привет, user. Чем могу? 💻',
        farewell='> Session terminated.\n> Goodbye, user. Stay safe. 💻',
        style_hints=['Технические метафоры', 'Код', 'Хакерский жаргон'],
        temperature=0.75,
    ),
}


class PersonalityEngine:
    """Движок переключения личностей."""

    def __init__(self, data_file: str = 'data/personalities.json'):
        self.data_file = Path(data_file)
        self.data_file.parent.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()

        # Все личности (включая пользовательские)
        self._personalities: Dict[str, Personality] = {}
        # channel_id -> active persona_id
        self._channel_personas: Dict[int, str] = {}
        # guild_id -> default persona_id
        self._guild_defaults: Dict[int, str] = {}

        # Загружаем встроенные
        for pid, persona in BUILTIN_PERSONALITIES.items():
            self._personalities[pid] = persona

        self._load_custom()

    def _load_custom(self):
        """Загрузка пользовательских личностей."""
        if not self.data_file.exists():
            return

        try:
            with open(self.data_file, 'r', encoding='utf-8') as f:
                data = json.load(f)

            for p_data in data.get('custom_personas', []):
                p = Personality.from_dict(p_data)
                self._personalities[p.persona_id] = p

            self._channel_personas = {
                int(k): v for k, v in data.get('channel_personas', {}).items()
            }
            self._guild_defaults = {
                int(k): v for k, v in data.get('guild_defaults', {}).items()
            }

            logger.info(
                f"PersonalityEngine: {len(self._personalities)} личностей "
                f"({len(BUILTIN_PERSONALITIES)} встроенных)"
            )
        except Exception as e:
            logger.error(f"Ошибка загрузки личностей: {e}")

    def _save_data(self):
        """Сохранение пользовательских данных."""
        try:
            custom = [
                p.to_dict() for p in self._personalities.values()
                if p.is_custom
            ]
            data = {
                'custom_personas': custom,
                'channel_personas': {str(k): v for k, v in self._channel_personas.items()},
                'guild_defaults': {str(k): v for k, v in self._guild_defaults.items()},
            }
            with open(self.data_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Ошибка сохранения личностей: {e}")

    # ─── Получение ───

    def get_personality(self, persona_id: str) -> Optional[Personality]:
        """Получить личность по ID."""
        return self._personalities.get(persona_id)

    def get_active_personality(
        self,
        channel_id: int = 0,
        guild_id: int = 0
    ) -> Personality:
        """Получить активную личность для канала/сервера."""
        # Сначала проверяем канал
        if channel_id and channel_id in self._channel_personas:
            persona_id = self._channel_personas[channel_id]
            persona = self._personalities.get(persona_id)
            if persona:
                persona.uses_count += 1
                return persona

        # Затем сервер
        if guild_id and guild_id in self._guild_defaults:
            persona_id = self._guild_defaults[guild_id]
            persona = self._personalities.get(persona_id)
            if persona:
                persona.uses_count += 1
                return persona

        # Default
        return self._personalities['default']

    def get_system_prompt(
        self,
        channel_id: int = 0,
        guild_id: int = 0,
        extra_context: str = ""
    ) -> str:
        """Получить system prompt для текущей персоны."""
        persona = self.get_active_personality(channel_id, guild_id)
        prompt = persona.system_prompt

        if extra_context:
            prompt += f"\n\n{extra_context}"

        return prompt

    # ─── Переключение ───

    def switch_channel_persona(
        self,
        channel_id: int,
        persona_id: str
    ) -> Tuple[bool, str]:
        """Переключить личность для канала."""
        if persona_id not in self._personalities:
            return False, f"Личность '{persona_id}' не найдена"

        self._channel_personas[channel_id] = persona_id
        self._save_data()

        persona = self._personalities[persona_id]
        return True, persona.greeting

    def switch_guild_default(self, guild_id: int, persona_id: str) -> bool:
        """Установить личность по умолчанию для сервера."""
        if persona_id not in self._personalities:
            return False

        self._guild_defaults[guild_id] = persona_id
        self._save_data()
        return True

    def reset_channel_persona(self, channel_id: int) -> bool:
        """Сбросить личность канала на дефолт."""
        if channel_id in self._channel_personas:
            del self._channel_personas[channel_id]
            self._save_data()
            return True
        return False

    # ─── Создание ───

    def create_custom_personality(
        self,
        name: str,
        description: str,
        system_prompt: str,
        emoji: str = '🎭',
        creator_id: int = 0,
        greeting: str = "",
        temperature: float = 0.7,
    ) -> Tuple[Optional[Personality], str]:
        """Создать пользовательскую личность."""
        # Генерируем ID
        persona_id = name.lower().replace(' ', '_').replace('-', '_')[:20]

        if persona_id in self._personalities:
            return None, f"Личность '{persona_id}' уже существует"

        if len(system_prompt) > 2000:
            return None, "System prompt слишком длинный (макс 2000)"

        if len(self._personalities) > 50:
            return None, "Достигнут лимит личностей (50)"

        persona = Personality(
            persona_id=persona_id,
            name=name,
            emoji=emoji,
            description=description,
            system_prompt=system_prompt,
            greeting=greeting,
            temperature=temperature,
            is_custom=True,
            creator_id=creator_id,
        )

        self._personalities[persona_id] = persona
        self._save_data()

        return persona, ""

    def delete_custom_personality(self, persona_id: str) -> bool:
        """Удалить пользовательскую личность."""
        persona = self._personalities.get(persona_id)
        if not persona or not persona.is_custom:
            return False

        # Удаляем из каналов
        channels_to_reset = [
            ch for ch, pid in self._channel_personas.items()
            if pid == persona_id
        ]
        for ch in channels_to_reset:
            del self._channel_personas[ch]

        del self._personalities[persona_id]
        self._save_data()
        return True

    # ─── Список ───

    def list_personalities(self, include_custom: bool = True) -> List[Dict[str, Any]]:
        """Получить список всех личностей."""
        result = []
        for p in self._personalities.values():
            if not include_custom and p.is_custom:
                continue
            result.append({
                'id': p.persona_id,
                'name': p.name,
                'emoji': p.emoji,
                'description': p.description,
                'temperature': p.temperature,
                'is_custom': p.is_custom,
                'uses': p.uses_count,
                'hints': ', '.join(p.style_hints),
            })
        return result

    # ─── Статистика ───

    def get_stats(self) -> Dict[str, Any]:
        builtin_count = len([p for p in self._personalities.values() if not p.is_custom])
        custom_count = len([p for p in self._personalities.values() if p.is_custom])
        most_used = max(self._personalities.values(), key=lambda p: p.uses_count, default=None)

        return {
            'total_personalities': len(self._personalities),
            'builtin': builtin_count,
            'custom': custom_count,
            'channels_with_persona': len(self._channel_personas),
            'most_used': most_used.name if most_used else 'N/A',
            'most_used_count': most_used.uses_count if most_used else 0,
        }



# Глобальный экземпляр
personality_engine = PersonalityEngine()
