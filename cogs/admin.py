"""
Модуль админ-команд для управления ботом.
Доступен только пользователям с правами администратора.
"""
import discord
from discord.ext import commands
from typing import Optional
from core.logger import logger
from core.cache import cache
from core.rate_limiter import rate_limiter
from core.permissions import permissions
from modules.analytics import analytics
from modules.context_builder import context_builder
from config.config import config


class AdminCommands(commands.Cog):
    """Команды для администраторов бота."""
    
    def __init__(self, bot):
        self.bot = bot
    
    def _check_perm(self, ctx, perm: str) -> bool:
        """Проверка прав администратора."""
        if ctx.author.id in config.admin_ids:
            return True
        return permissions.has_permission(ctx.author.id, perm)
    
    @commands.command(name='stats')
    async def stats(self, ctx):
        """Показать общую статистику бота."""
        if not self._check_perm(ctx, 'admin.stats'):
            await ctx.send("❌ У вас нет прав (admin.stats).")
            return
        
        stats = analytics.get_stats()
        cache_stats = cache.get_stats()
        rate_stats = rate_limiter.get_stats()
        
        embed = discord.Embed(
            title="📊 Статистика бота",
            color=discord.Color.blue(),
            description="Общая информация о работе бота"
        )
        
        # Основная статистика
        embed.add_field(
            name="⏱️ Время работы",
            value=f"{stats['uptime_days']} дней",
            inline=True
        )
        embed.add_field(
            name="📨 Всего запросов",
            value=f"{stats['total_requests']:,}",
            inline=True
        )
        embed.add_field(
            name="🪙 Токенов использовано",
            value=f"{stats['total_tokens']:,}",
            inline=True
        )
        embed.add_field(
            name="👥 Уникальных пользователей",
            value=f"{stats['unique_users']}",
            inline=True
        )
        embed.add_field(
            name="⚠️ Недавних ошибок",
            value=f"{stats['recent_errors']}",
            inline=True
        )
        
        # Кэш
        embed.add_field(
            name="💾 Кэш",
            value=f"Размер: {cache_stats['size']}\nHit rate: {cache_stats['hit_rate']}",
            inline=True
        )
        
        # Rate limiter
        embed.add_field(
            name="🚦 Rate Limiter",
            value=f"Отслеживается: {rate_stats['tracked_users']} польз.",
            inline=True
        )
        
        # Топ пользователей
        if stats['top_users']:
            top_users_text = "\n".join([
                f"{i+1}. **{user['name']}**: {user['requests']} запросов"
                for i, user in enumerate(stats['top_users'][:5])
            ])
            embed.add_field(
                name="🏆 Топ пользователей",
                value=top_users_text,
                inline=False
            )
        
        # Используемые модели
        if stats['models_used']:
            models_text = ", ".join([f"`{m}`" for m in stats['models_used']])
            embed.add_field(
                name="🤖 Используемые модели",
                value=models_text,
                inline=False
            )
        
        await ctx.send(embed=embed)
    
    @commands.command(name='report')
    async def report(self, ctx, days: int = 7):
        """
        Показать отчёт за последние N дней.
        Использование: !report [дни]
        """
        if not self._check_perm(ctx, 'admin.report'):
            await ctx.send("❌ У вас нет прав (admin.report).")
            return
        
        if days < 1 or days > 30:
            await ctx.send("❌ Количество дней должно быть от 1 до 30.")
            return
        
        report = analytics.get_daily_report(days)
        
        embed = discord.Embed(
            title=f"📈 Отчёт за {days} дней",
            description=report,
            color=discord.Color.green()
        )
        
        await ctx.send(embed=embed)
    
    @commands.command(name='clearcache')
    async def clear_cache(self, ctx):
        """Очистить кэш бота."""
        if not self._check_perm(ctx, 'admin.cache'):
            await ctx.send("❌ У вас нет прав (admin.cache).")
            return
        
        cache.clear()
        logger.info(f"Кэш очищен администратором {ctx.author.name}")
        await ctx.send("✅ Кэш успешно очищен!")
    
    @commands.command(name='clearhistory')
    async def clear_history(self, ctx):
        """Очистить историю сообщений текущего канала."""
        if not self._check_perm(ctx, 'admin.history'):
            await ctx.send("❌ У вас нет прав (admin.history).")
            return
        
        context_builder.clear_history(ctx.channel.id)
        logger.info(f"История канала {ctx.channel.name} очищена администратором {ctx.author.name}")
        await ctx.send("✅ История сообщений канала очищена!")
    
    @commands.command(name='resetlimit')
    async def reset_limit(self, ctx, user: Optional[discord.Member] = None):
        """
        Сбросить rate limit для пользователя.
        Использование: !resetlimit [@пользователь]
        """
        if not self._check_perm(ctx, 'admin.ratelimit'):
            await ctx.send("❌ У вас нет прав (admin.ratelimit).")
            return
        
        target_user = user or ctx.author
        rate_limiter.reset_user(target_user.id)
        
        logger.info(f"Rate limit сброшен для {target_user.name} администратором {ctx.author.name}")
        await ctx.send(f"✅ Rate limit сброшен для {target_user.mention}!")
    
    @commands.command(name='config')
    async def show_config(self, ctx):
        """Показать текущую конфигурацию бота."""
        if not self._check_perm(ctx, 'admin.config'):
            await ctx.send("❌ У вас нет прав (admin.config).")
            return
        
        config_dict = config.to_dict()
        
        embed = discord.Embed(
            title="⚙️ Конфигурация бота",
            color=discord.Color.purple()
        )
        
        for key, value in config_dict.items():
            if isinstance(value, list):
                value = ", ".join(str(v) for v in value)
            embed.add_field(
                name=key.replace('_', ' ').title(),
                value=f"`{value}`",
                inline=True
            )
        
        await ctx.send(embed=embed)
    
    @commands.command(name='mystats')
    async def my_stats(self, ctx):
        """Показать вашу личную статистику использования."""
        user_stats = analytics.get_user_stats(ctx.author.id)
        
        if 'error' in user_stats:
            await ctx.send("📊 У вас пока нет статистики использования.")
            return
        
        embed = discord.Embed(
            title=f"📊 Статистика пользователя {ctx.author.display_name}",
            color=discord.Color.blue()
        )
        
        embed.add_field(
            name="📨 Запросов",
            value=f"{user_stats['count']:,}",
            inline=True
        )
        embed.add_field(
            name="🪙 Токенов",
            value=f"{user_stats['tokens']:,}",
            inline=True
        )
        embed.add_field(
            name="⏱️ Среднее время ответа",
            value=f"{user_stats['avg_response_time']:.2f}s",
            inline=True
        )
        
        # Rate limit информация
        remaining = rate_limiter.get_remaining(ctx.author.id)
        reset_time = rate_limiter.get_reset_time(ctx.author.id)
        
        embed.add_field(
            name="🚦 Доступно запросов",
            value=f"{remaining}/{config.rate_limit_requests}",
            inline=True
        )
        
        if reset_time > 0:
            embed.add_field(
                name="⏳ Сброс через",
                value=f"{int(reset_time)}s",
                inline=True
            )
        
        await ctx.send(embed=embed)


async def setup(bot):
    """Регистрация Cog."""
    await bot.add_cog(AdminCommands(bot))
