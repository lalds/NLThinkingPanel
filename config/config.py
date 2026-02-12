"""
Централизованная система конфигурации бота.
Поддерживает валидацию, типизацию и динамическую перезагрузку.
"""
import os
from dataclasses import dataclass, field
from typing import List, Dict, Any
from dotenv import load_dotenv

load_dotenv()


@dataclass
class BotConfig:
    """Основная конфигурация бота."""
    
    # Discord настройки
    discord_token: str = field(default_factory=lambda: os.getenv('DISCORD_TOKEN', ''))
    command_prefix: str = field(default_factory=lambda: os.getenv('COMMAND_PREFIX', '!'))
    
    # OpenRouter настройки
    openrouter_api_key: str = field(default_factory=lambda: os.getenv('OPENROUTER_API_KEY', ''))
    openrouter_model: str = field(default_factory=lambda: os.getenv('OPENROUTER_MODEL', 'anthropic/claude-3-haiku'))
    
    # AI настройки
    system_prompt: str = field(default_factory=lambda: os.getenv(
        'SYSTEM_PROMPT',
        'Ты профессиональный ассистент с глубоким пониманием контекста сообщества.'
    ))
    max_tokens: int = field(default_factory=lambda: int(os.getenv('MAX_TOKENS', '2000')))
    temperature: float = field(default_factory=lambda: float(os.getenv('TEMPERATURE', '0.7')))
    
    # Контекст и история
    max_history_messages: int = field(default_factory=lambda: int(os.getenv('MAX_HISTORY_MESSAGES', '10')))
    context_window_hours: int = field(default_factory=lambda: int(os.getenv('CONTEXT_WINDOW_HOURS', '24')))
    
    # Кэширование
    cache_enabled: bool = field(default_factory=lambda: os.getenv('CACHE_ENABLED', 'true').lower() == 'true')
    cache_ttl_seconds: int = field(default_factory=lambda: int(os.getenv('CACHE_TTL_SECONDS', '300')))
    
    # Rate limiting
    rate_limit_enabled: bool = field(default_factory=lambda: os.getenv('RATE_LIMIT_ENABLED', 'true').lower() == 'true')
    rate_limit_requests: int = field(default_factory=lambda: int(os.getenv('RATE_LIMIT_REQUESTS', '5')))
    rate_limit_window_seconds: int = field(default_factory=lambda: int(os.getenv('RATE_LIMIT_WINDOW', '60')))
    
    # Аналитика
    analytics_enabled: bool = field(default_factory=lambda: os.getenv('ANALYTICS_ENABLED', 'true').lower() == 'true')
    log_level: str = field(default_factory=lambda: os.getenv('LOG_LEVEL', 'INFO'))
    
    # Админы (список Discord ID через запятую)
    admin_ids: List[int] = field(default_factory=lambda: [
        int(id.strip()) for id in os.getenv('ADMIN_IDS', '').split(',') if id.strip()
    ])
    
    # Модули (какие модули включены)
    enabled_modules: List[str] = field(default_factory=lambda: 
        os.getenv('ENABLED_MODULES', 'context,history,analytics,moderation').split(',')
    )
    
    def validate(self) -> List[str]:
        """Валидация конфигурации. Возвращает список ошибок."""
        errors = []
        
        if not self.discord_token:
            errors.append("DISCORD_TOKEN не установлен")
        
        if not self.openrouter_api_key:
            errors.append("OPENROUTER_API_KEY не установлен")
        
        if self.temperature < 0 or self.temperature > 2:
            errors.append("TEMPERATURE должна быть между 0 и 2")
        
        if self.max_tokens < 100 or self.max_tokens > 4000:
            errors.append("MAX_TOKENS должен быть между 100 и 4000")
        
        return errors
    
    def to_dict(self) -> Dict[str, Any]:
        """Экспорт конфигурации в словарь (для логирования)."""
        return {
            'command_prefix': self.command_prefix,
            'model': self.openrouter_model,
            'max_tokens': self.max_tokens,
            'temperature': self.temperature,
            'cache_enabled': self.cache_enabled,
            'rate_limit_enabled': self.rate_limit_enabled,
            'enabled_modules': self.enabled_modules,
        }


# Глобальный экземпляр конфигурации
config = BotConfig()
