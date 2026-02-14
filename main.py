"""
NLThinkingPanel Pro — Профессиональный Discord бот с AI.

Модульная архитектура, расширенная аналитика, кэширование,
rate limiting, система улучшения ответов AI, репутация,
личности, база знаний, авто-модерация, напоминания и многое другое.
"""
import discord
from discord.ext import commands
import asyncio
from pathlib import Path

from core.logger import logger, setup_logger
from config.config import config
from core.cache import cache
from core.health_monitor import health_monitor
from core.event_system import event_system
from modules.reminder_system import reminder_system
from modules.mood_analyzer import mood_analyzer
from modules.auto_moderator import auto_moderator
from modules.reputation_system import reputation_system, BADGES as BADGES_MAP


class NLThinkingPanelBot(commands.Bot):
    """Основной класс бота с расширенной функциональностью."""
    
    def __init__(self):
        """Инициализация бота."""
        # Настройка intents
        intents = discord.Intents.default()
        intents.message_content = True
        intents.presences = True
        intents.members = True
        intents.voice_states = True
        
        super().__init__(
            command_prefix=config.command_prefix,
            intents=intents,
            allowed_mentions=discord.AllowedMentions.none(),
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
        
        logger.info("═" * 60)
        logger.info(f"🤖 Бот запущен: {self.user.name} (ID: {self.user.id})")
        logger.info(f"📊 Серверов: {len(self.guilds)}")
        logger.info(f"👥 Пользователей: {sum(g.member_count for g in self.guilds)}")
        logger.info(f"🔧 Префикс команд: {config.command_prefix}")
        logger.info(f"🤖 Модель: {config.openrouter_model}")
        logger.info(f"📦 Модулей загружено: {len(self.cogs)}")
        logger.info("═" * 60)
        
        # Установка статуса
        activity = discord.Activity(
            type=discord.ActivityType.watching,
            name=f"{config.command_prefix}ask | {len(self.guilds)} серверов"
        )
        await self.change_presence(activity=activity, status=discord.Status.online)
        
        # Health Monitor
        health_monitor.heartbeat()
        health_monitor.update_component_status('discord', 'healthy', self.latency * 1000, 'Подключен')
        
        # Emit event
        await event_system.emit('bot.ready', guilds=len(self.guilds), user=str(self.user))
        
        # Запуск фоновых задач
        self.loop.create_task(self.cleanup_task())
        self.loop.create_task(reminder_system.check_loop(self))
        self.loop.create_task(self.heartbeat_task())
        self.loop.create_task(self.mood_tracking_task())
    
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
    
    async def heartbeat_task(self):
        """Heartbeat и мониторинг здоровья."""
        await self.wait_until_ready()
        
        while not self.is_closed():
            try:
                health_monitor.heartbeat()
                health_monitor.update_component_status(
                    'discord_ws',
                    'healthy' if self.latency < 1 else 'degraded',
                    self.latency * 1000,
                    f'Latency: {self.latency*1000:.0f}ms'
                )
                await asyncio.sleep(30)
            except Exception as e:
                logger.error(f"Ошибка в heartbeat_task: {e}")
    
    async def mood_tracking_task(self):
        """Фоновая задача для трекинга настроения (логирование)."""
        await self.wait_until_ready()
        logger.info("🎭 Mood tracking task запущена")
        
        while not self.is_closed():
            try:
                await asyncio.sleep(600)  # Каждые 10 минут
                stats = mood_analyzer.get_stats()
                health_monitor.record_module_metric('mood_analyzer', 'users_tracked', stats['users_tracked'])
            except Exception as e:
                logger.error(f"Ошибка в mood_tracking_task: {e}")
    
    async def on_message(self, message):
        """Обработка каждого сообщения — авто-модерация, репутация, mood."""
        if message.author.bot:
            return
        
        # Авто-модерация
        try:
            filter_result = auto_moderator.check_message(
                user_id=message.author.id,
                content=message.content,
                channel_id=message.channel.id if hasattr(message.channel, 'id') else 0
            )
            
            if filter_result.triggered:
                if filter_result.action == 'delete':
                    try:
                        await message.delete()
                    except discord.Forbidden:
                        pass
                
                if filter_result.action in ('warn', 'delete'):
                    auto_moderator.add_warning(
                        user_id=message.author.id,
                        reason=filter_result.reason,
                        severity=filter_result.severity,
                        auto=True,
                        channel_id=message.channel.id if hasattr(message.channel, 'id') else 0,
                    )
                    
                    await event_system.emit(
                        'moderation.auto_action',
                        user_id=message.author.id,
                        action=filter_result.action,
                        reason=filter_result.reason,
                    )
        except Exception as e:
            logger.error(f"Ошибка авто-модерации: {e}")
        
        # Репутация (XP за сообщения)
        try:
            xp_granted, leveled_up, new_badge = reputation_system.grant_xp(
                user_id=message.author.id,
                user_name=message.author.display_name,
                action='message'
            )
            
            if leveled_up:
                card = reputation_system.get_user_card(message.author.id)
                if card:
                    embed = discord.Embed(
                        title="🎉 Уровень повышен!",
                        description=(
                            f"{message.author.mention} достиг **уровня {card['level']}**!\n"
                            f"{card['title']}"
                        ),
                        color=discord.Color.gold()
                    )
                    await message.channel.send(embed=embed, delete_after=15)
            
            if new_badge and new_badge in BADGES_MAP:
                badge_info = BADGES_MAP[new_badge]
                await message.channel.send(
                    f"🏆 {message.author.mention} получил бейдж: "
                    f"{badge_info[0]} **{badge_info[1]}**!",
                    delete_after=10
                )
        except Exception:
            pass  # Не критично
        
        # Mood tracking (быстрый, без AI)
        try:
            if len(message.content) > 5:
                await mood_analyzer.analyze_and_record(
                    user_id=message.author.id,
                    channel_id=message.channel.id if hasattr(message.channel, 'id') else 0,
                    text=message.content,
                    use_ai=False  # Быстрый анализ
                )
        except Exception:
            pass  # Не критично
        
        # Обязательно обрабатываем команды
        await self.process_commands(message)
    
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
                "⚠️ Произошла непредвиденная ошибка. "
                "Подробности сохранены в логах."
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
    for directory in ['data', 'logs', 'data/conversations', 'data/moderation']:
        Path(directory).mkdir(parents=True, exist_ok=True)
    
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
