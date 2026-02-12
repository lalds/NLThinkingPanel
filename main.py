"""
NLThinkingPanel Pro - Профессиональный Discord бот с AI.

Модульная архитектура, расширенная аналитика, кэширование,
rate limiting и система улучшения ответов AI.
"""
import discord
from discord.ext import commands
import asyncio
from pathlib import Path

from core.logger import logger, setup_logger
from config.config import config
from core.cache import cache


class NLThinkingPanelBot(commands.Bot):
    """Основной класс бота с расширенной функциональностью."""
    
    def __init__(self):
        """Инициализация бота."""
        # Настройка intents
        intents = discord.Intents.default()
        intents.message_content = True
        intents.presences = True
        intents.members = True
        
        super().__init__(
            command_prefix=config.command_prefix,
            intents=intents,
            help_command=commands.DefaultHelpCommand(
                no_category='Команды',
                dm_help=True
            )
        )
        
        self.start_time = None
    
    async def setup_hook(self):
        """Загрузка расширений (cogs) при запуске."""
        logger.info("Загрузка модулей...")
        
        # Загрузка всех cogs из директории cogs/
        cogs_dir = Path('cogs')
        if cogs_dir.exists():
            for cog_file in cogs_dir.glob('*.py'):
                if cog_file.stem.startswith('_'):
                    continue
                
                try:
                    await self.load_extension(f'cogs.{cog_file.stem}')
                    logger.info(f"✅ Загружен модуль: {cog_file.stem}")
                except Exception as e:
                    logger.error(f"❌ Ошибка загрузки модуля {cog_file.stem}: {e}")
        
        logger.info("Все модули загружены")
    
    async def on_ready(self):
        """Событие готовности бота."""
        self.start_time = discord.utils.utcnow()
        
        logger.info("=" * 50)
        logger.info(f"🤖 Бот запущен: {self.user.name} (ID: {self.user.id})")
        logger.info(f"📊 Серверов: {len(self.guilds)}")
        logger.info(f"👥 Пользователей: {sum(g.member_count for g in self.guilds)}")
        logger.info(f"🔧 Префикс команд: {config.command_prefix}")
        logger.info(f"🤖 Модель: {config.openrouter_model}")
        logger.info(f"📦 Модулей загружено: {len(self.cogs)}")
        logger.info("=" * 50)
        
        # Установка статуса
        activity = discord.Activity(
            type=discord.ActivityType.watching,
            name=f"{config.command_prefix}ask | {len(self.guilds)} серверов"
        )
        await self.change_presence(activity=activity, status=discord.Status.online)
        
        # Запуск фоновых задач
        self.loop.create_task(self.cleanup_task())
    
    async def cleanup_task(self):
        """Фоновая задача для очистки кэша и других ресурсов."""
        await self.wait_until_ready()
        
        while not self.is_closed():
            try:
                # Очистка устаревших записей в кэше каждые 5 минут
                await asyncio.sleep(300)
                
                if config.cache_enabled:
                    cleaned = cache.cleanup()
                    if cleaned > 0:
                        logger.info(f"🧹 Очищено {cleaned} устаревших записей кэша")
                
            except Exception as e:
                logger.error(f"Ошибка в cleanup_task: {e}")
    
    async def on_command_error(self, ctx, error):
        """Обработка ошибок команд."""
        if isinstance(error, commands.CommandNotFound):
            return  # Игнорируем неизвестные команды
        
        elif isinstance(error, commands.MissingRequiredArgument):
            await ctx.send(
                f"❌ Отсутствует обязательный аргумент: `{error.param.name}`\n"
                f"Используйте `{config.command_prefix}help {ctx.command.name}` для справки."
            )
        
        elif isinstance(error, commands.BadArgument):
            await ctx.send(
                f"❌ Неверный аргумент команды.\n"
                f"Используйте `{config.command_prefix}help {ctx.command.name}` для справки."
            )
        
        elif isinstance(error, commands.CommandOnCooldown):
            await ctx.send(
                f"⏳ Команда на перезарядке. Попробуйте через {error.retry_after:.1f}s."
            )
        
        else:
            logger.error(f"Необработанная ошибка команды: {error}", exc_info=error)
            await ctx.send(
                f"⚠️ Произошла непредвиденная ошибка.\n"
                f"```{str(error)[:500]}```"
            )


def main():
    """Точка входа в приложение."""
    # Настройка логгера
    setup_logger(level=config.log_level)
    
    logger.info("🚀 Запуск NLThinkingPanel Pro...")
    
    # Валидация конфигурации
    errors = config.validate()
    if errors:
        logger.error("❌ Ошибки конфигурации:")
        for error in errors:
            logger.error(f"  - {error}")
        logger.error("\nПроверьте файл .env и исправьте ошибки.")
        return
    
    logger.info("✅ Конфигурация валидна")
    logger.info(f"📋 Включенные модули: {', '.join(config.enabled_modules)}")
    
    # Создание необходимых директорий
    Path('data').mkdir(exist_ok=True)
    Path('logs').mkdir(exist_ok=True)
    
    # Создание и запуск бота
    bot = NLThinkingPanelBot()
    
    try:
        bot.run(config.discord_token, log_handler=None)
    except discord.errors.PrivilegedIntentsRequired:
        logger.error("\n" + "=" * 60)
        logger.error("❌ ОШИБКА: Не включены Privileged Intents!")
        logger.error("=" * 60)
        logger.error("\nДля работы бота необходимо включить следующие Intents:")
        logger.error("1. Перейдите на https://discord.com/developers/applications")
        logger.error("2. Выберите ваше приложение -> раздел 'Bot'")
        logger.error("3. Включите в разделе 'Privileged Gateway Intents':")
        logger.error("   ✓ Presence Intent")
        logger.error("   ✓ Server Members Intent")
        logger.error("   ✓ Message Content Intent")
        logger.error("4. Сохраните изменения и перезапустите бота\n")
    except KeyboardInterrupt:
        logger.info("\n👋 Бот остановлен пользователем")
    except Exception as e:
        logger.error(f"❌ Критическая ошибка: {e}", exc_info=True)


if __name__ == "__main__":
    main()
