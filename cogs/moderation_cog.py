"""
Модуль команд модерации (Moderation Cog).

Команды:
 - !warn — предупреждение
 - !warns — список предупреждений
 - !clearwarns — очистка предупреждений
 - !mute — замутить пользователя
 - !unmute — снять мут
 - !modlog — лог модерации
 - !modstats — статистика модерации
 - !whitelist — управление белым списком
 - !automod — настройка авто-модерации
 - !purge — массовое удаление сообщений
"""
import discord
from discord.ext import commands
from typing import Optional
from datetime import datetime

from core.logger import logger
from core.permissions import permissions
from modules.auto_moderator import auto_moderator, ModerationAction
from modules.reminder_system import parse_duration, format_duration
from config.config import config


class ModerationCog(commands.Cog):
    """Команды модерации."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    def _check_perm(self, ctx, perm: str) -> bool:
        """Проверка прав доступа."""
        # 1. Owners always allow
        if ctx.author.id in config.admin_ids:
            return True
            
        # 2. Check internal permission system
        if permissions.has_permission(ctx.author.id, perm):
            return True
            
        # 3. Fallback: Discord permissions
        if perm.startswith('moderation.') and ctx.guild and ctx.author.guild_permissions.manage_messages:
            return True
            
        return False

    # ═══════════════════════
    # ⚠️ ПРЕДУПРЕЖДЕНИЯ
    # ═══════════════════════

    @commands.command(name='warn', aliases=['предупреждение'])
    async def warn_user(self, ctx, user: discord.Member = None, *, reason: str = "Без причины"):
        """Выдать предупреждение пользователю."""
        if not self._check_perm(ctx, 'moderation.warn'):
            await ctx.reply("❌ Недостаточно прав (moderation.warn).")
            return

        if not user:
            await ctx.reply("❌ Формат: `!warn @пользователь [причина]`")
            return

        if user.bot:
            await ctx.reply("❌ Нельзя предупредить бота.")
            return

        result = auto_moderator.add_warning(
            user_id=user.id,
            reason=reason,
            moderator_id=ctx.author.id,
            auto=False,
            channel_id=ctx.channel.id,
        )

        embed = discord.Embed(
            title="⚠️ Предупреждение",
            color=discord.Color.yellow()
        )
        embed.add_field(name="👤 Пользователь", value=user.mention, inline=True)
        embed.add_field(name="📝 Причина", value=reason, inline=True)
        embed.add_field(name="⚠️ Всего предупреждений", value=str(result['warn_count']), inline=True)

        if result['recommended_action'] != ModerationAction.NONE:
            action_names = {
                ModerationAction.MUTE: '🔇 Мут',
                ModerationAction.KICK: '👢 Кик',
                ModerationAction.BAN: '🔨 Бан',
            }
            embed.add_field(
                name="🚨 Рекомендуемое действие",
                value=action_names.get(result['recommended_action'], 'N/A'),
                inline=False
            )

        embed.set_footer(text=f"Мод: {ctx.author.display_name}")
        await ctx.send(embed=embed)

    @commands.command(name='warns', aliases=['предупреждения', 'warnings'])
    async def show_warnings(self, ctx, user: discord.Member = None):
        """Показать предупреждения пользователя."""
        target = user or ctx.author
        
        # Если смотрят чужие варны - нужны права
        if target.id != ctx.author.id and not self._check_perm(ctx, 'moderation.view_log'):
             await ctx.reply("❌ Вы можете смотреть только свои предупреждения.")
             return
        warnings = auto_moderator.get_warnings(target.id)

        if not warnings:
            await ctx.reply(f"✅ У {target.display_name} нет предупреждений!")
            return

        embed = discord.Embed(
            title=f"⚠️ Предупреждения: {target.display_name}",
            color=discord.Color.yellow()
        )

        for i, w in enumerate(warnings[-10:], 1):
            dt = datetime.fromtimestamp(w['timestamp']).strftime('%Y-%m-%d %H:%M')
            auto_tag = " [авто]" if w.get('auto') else ""
            embed.add_field(
                name=f"#{i} — {dt}{auto_tag}",
                value=w['reason'][:200],
                inline=False
            )

        embed.set_footer(text=f"Всего: {len(warnings)}")
        await ctx.reply(embed=embed)

    @commands.command(name='clearwarns', aliases=['очистить_предупреждения'])
    async def clear_warnings(self, ctx, user: discord.Member = None):
        """Очистить предупреждения пользователя."""
        if not self._check_perm(ctx, 'moderation.kick'): # requires higher perm
            await ctx.reply("❌ Недостаточно прав.")
            return

        if not user:
            await ctx.reply("❌ Формат: `!clearwarns @пользователь`")
            return

        count = auto_moderator.clear_warnings(user.id)
        await ctx.reply(f"✅ Очищено {count} предупреждений для {user.display_name}.")

    # ═══════════════════════
    # 🔇 МУТ
    # ═══════════════════════

    @commands.command(name='mute', aliases=['мут', 'замутить'])
    async def mute_user(self, ctx, user: discord.Member = None,
                        duration_str: str = "10m", *, reason: str = ""):
        """
        Замутить пользователя (предотвращает ответы бота).
        Формат: !mute @user 30м [причина]
        """
        if not self._check_perm(ctx, 'moderation.mute'):
            await ctx.reply("❌ Недостаточно прав (moderation.mute).")
            return

        if not user:
            await ctx.reply("❌ Формат: `!mute @пользователь [время] [причина]`")
            return

        duration = parse_duration(duration_str)
        if not duration:
            duration = 600  # 10 минут по умолчанию

        unmute_at = auto_moderator.mute_user(
            user.id, duration, reason, ctx.author.id
        )

        embed = discord.Embed(
            title="🔇 Мут",
            color=discord.Color.dark_grey()
        )
        embed.add_field(name="👤 Пользователь", value=user.mention, inline=True)
        embed.add_field(name="⏰ Длительность", value=format_duration(duration), inline=True)
        if reason:
            embed.add_field(name="📝 Причина", value=reason, inline=False)
        embed.set_footer(text=f"Мод: {ctx.author.display_name}")

        await ctx.send(embed=embed)

        # Попытка выдать discord mute (timeout)
        try:
            from datetime import timedelta
            await user.timeout(timedelta(seconds=duration), reason=reason or "Мут модератором")
        except (discord.Forbidden, discord.HTTPException):
            pass  # Нет прав на discord timeout

    @commands.command(name='unmute', aliases=['размутить'])
    async def unmute_user(self, ctx, user: discord.Member = None):
        """Снять мут с пользователя."""
        if not self._check_perm(ctx, 'moderation.mute'):
            await ctx.reply("❌ Недостаточно прав.")
            return

        if not user:
            await ctx.reply("❌ Формат: `!unmute @пользователь`")
            return

        if auto_moderator.unmute_user(user.id):
            await ctx.reply(f"🔊 Мут снят с {user.display_name}!")
            try:
                await user.timeout(None, reason="Мут снят модератором")
            except (discord.Forbidden, discord.HTTPException):
                pass
        else:
            await ctx.reply(f"❓ {user.display_name} не замутен.")

    # ═══════════════════════
    # 📋 МОДЛОГ
    # ═══════════════════════

    @commands.command(name='modlog', aliases=['модлог'])
    async def show_modlog(self, ctx, limit: int = 10):
        """Показать лог модерации."""
        if not self._check_perm(ctx, 'moderation.view_log'):
            await ctx.reply("❌ Недостаточно прав.")
            return

        entries = auto_moderator.get_modlog(limit=limit)
        if not entries:
            await ctx.reply("📋 Модлог пуст.")
            return

        embed = discord.Embed(
            title="📋 Лог модерации",
            color=discord.Color.dark_blue()
        )

        action_emojis = {
            'warn': '⚠️', 'mute': '🔇', 'kick': '👢',
            'ban': '🔨', 'delete': '🗑️', 'none': '—',
        }

        for entry in entries[-10:]:
            dt = datetime.fromtimestamp(entry['timestamp']).strftime('%m-%d %H:%M')
            emoji = action_emojis.get(entry['action'], '❓')
            auto_tag = " [авто]" if entry['auto'] else ""
            embed.add_field(
                name=f"{emoji} {entry['action'].upper()} — {dt}{auto_tag}",
                value=f"Target: <@{entry['target_id']}>\n{entry['reason'][:150]}",
                inline=False
            )

        await ctx.reply(embed=embed)

    # ═══════════════════════
    # 📊 СТАТИСТИКА МОДЕРАЦИИ
    # ═══════════════════════

    @commands.command(name='modstats', aliases=['модстатистика'])
    async def mod_stats(self, ctx):
        """Статистика модерации."""
        if not self._check_perm(ctx, 'moderation.view_log'):
            await ctx.reply("❌ Недостаточно прав.")
            return

        stats = auto_moderator.get_stats()

        embed = discord.Embed(
            title="📊 Статистика модерации",
            color=discord.Color.dark_blue()
        )
        embed.add_field(name="⚠️ Warnings", value=str(stats['total_warnings']), inline=True)
        embed.add_field(name="👥 С предупр.", value=str(stats['users_with_warnings']), inline=True)
        embed.add_field(name="🔇 Активные муты", value=str(stats['active_mutes']), inline=True)
        embed.add_field(name="✅ Whitelist", value=str(stats['whitelist_size']), inline=True)
        embed.add_field(name="📋 Модлог", value=str(stats['modlog_entries']), inline=True)

        await ctx.reply(embed=embed)

    # ═══════════════════════
    # 🗑️ ОЧИСТКА СООБЩЕНИЙ
    # ═══════════════════════

    @commands.command(name='purge', aliases=['очистить', 'clean'])
    async def purge_messages(self, ctx, amount: int = 10):
        """
        Массовое удаление сообщений.
        Использование: !purge 50
        """
        if not self._check_perm(ctx, 'moderation.purge'):
            await ctx.reply("❌ Недостаточно прав (moderation.purge).")
            return

        if amount < 1 or amount > 200:
            await ctx.reply("❌ Количество: от 1 до 200.")
            return

        try:
            deleted = await ctx.channel.purge(limit=amount + 1)  # +1 для команды
            msg = await ctx.send(f"🗑️ Удалено {len(deleted) - 1} сообщений.")
            import asyncio
            await asyncio.sleep(3)
            await msg.delete()
        except discord.Forbidden:
            await ctx.reply("❌ Нет прав на удаление сообщений!")
        except discord.HTTPException as e:
            await ctx.reply(f"❌ Ошибка: {e}")

    # ═══════════════════════
    # ✅ WHITELIST
    # ═══════════════════════

    @commands.command(name='whitelist', aliases=['белый_список'])
    async def manage_whitelist(self, ctx, action: str = "", user: discord.Member = None):
        """
        Управление белым списком авто-модерации.
        !whitelist add @user — добавить
        !whitelist remove @user — удалить
        """
        if not self._check_perm(ctx, 'moderation.config'):
            await ctx.reply("❌ Недостаточно прав.")
            return

        if action == 'add' and user:
            auto_moderator.add_to_whitelist(user.id)
            await ctx.reply(f"✅ {user.display_name} добавлен в белый список.")
        elif action == 'remove' and user:
            auto_moderator.remove_from_whitelist(user.id)
            await ctx.reply(f"✅ {user.display_name} удалён из белого списка.")
        else:
            await ctx.reply(
                "**Белый список:**\n"
                "• `!whitelist add @user` — добавить\n"
                "• `!whitelist remove @user` — удалить"
            )


async def setup(bot):
    await bot.add_cog(ModerationCog(bot))
