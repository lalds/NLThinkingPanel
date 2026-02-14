"""
Утилитарные команды (Utility Commands).

Включает:
 - !remind — напоминания
 - !rep / +rep — репутация
 - !daily — ежедневный бонус
 - !level / !rank — уровень и карточка
 - !leaderboard / !top — лидерборд
 - !badges — бейджи
 - !personality — переключение личности
 - !kb — база знаний (создание, поиск, чтение)
 - !chain — управление цепочками диалогов
 - !mood — настроение
 - !health — здоровье бота
 - !translate — перевод текста
"""
import discord
from discord.ext import commands
from typing import Optional
from datetime import datetime

from core.logger import logger
from core.permissions import permissions
from modules.reputation_system import reputation_system, BADGES
from modules.reminder_system import reminder_system, parse_duration, format_duration
from modules.personality_engine import personality_engine
from modules.knowledge_base import knowledge_base
from modules.conversation_chains import conversation_manager
from modules.mood_analyzer import mood_analyzer
from core.health_monitor import health_monitor
from config.config import config


class UtilityCommands(commands.Cog):
    """Утилитарные команды."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ═══════════════════════
    # 🔔 НАПОМИНАНИЯ
    # ═══════════════════════

    @commands.command(name='remind', aliases=['напомни', 'reminder', 'timer'])
    async def remind(self, ctx, time_str: str = "", *, message: str = "Напоминание!"):
        """
        Создать напоминание.
        
        Примеры:
        !remind 30м Позвонить маме
        !remind 2ч Сделать перерыв
        !remind 1д Оплатить счёт
        """
        if not time_str:
            await ctx.reply(
                "🔔 **Напоминания**\n"
                "Формат: `!remind <время> <текст>`\n"
                "Примеры:\n"
                "• `!remind 30м Позвонить маме`\n"
                "• `!remind 2ч Перерыв!`\n"
                "• `!remind 1д Оплатить счёт`\n"
                "\nВремя: с/м/ч/д (секунды/минуты/часы/дни)"
            )
            return

        duration = parse_duration(time_str)
        if not duration:
            await ctx.reply("❌ Не могу распознать время. Примеры: 30м, 2ч, 1д")
            return

        reminder, error = reminder_system.create_reminder(
            user_id=ctx.author.id,
            channel_id=ctx.channel.id,
            guild_id=ctx.guild.id if ctx.guild else 0,
            message=message,
            duration_seconds=duration,
        )

        if error:
            await ctx.reply(f"❌ {error}")
            return

        embed = discord.Embed(
            title="🔔 Напоминание создано!",
            color=discord.Color.gold()
        )
        embed.add_field(name="📝 Текст", value=message[:500], inline=False)
        embed.add_field(name="⏰ Через", value=format_duration(duration), inline=True)
        embed.add_field(name="🆔 ID", value=reminder.reminder_id, inline=True)

        await ctx.reply(embed=embed)

    @commands.command(name='reminders', aliases=['напоминания', 'myreminders'])
    async def list_reminders(self, ctx):
        """Список ваших активных напоминаний."""
        reminders = reminder_system.get_user_reminders(ctx.author.id)

        if not reminders:
            await ctx.reply("📭 У тебя нет активных напоминаний.")
            return

        embed = discord.Embed(
            title="🔔 Ваши напоминания",
            color=discord.Color.gold()
        )

        for r in reminders[:10]:
            remaining = format_duration(int(r.remaining_seconds))
            recurring_tag = " 🔁" if r.recurring else ""
            embed.add_field(
                name=f"#{r.reminder_id}{recurring_tag}",
                value=f"📝 {r.message[:100]}\n⏰ Через: {remaining}",
                inline=False
            )

        embed.set_footer(text=f"Всего: {len(reminders)} | Удалить: !delremind <id>")
        await ctx.reply(embed=embed)

    @commands.command(name='delremind', aliases=['удалить_напоминание'])
    async def delete_reminder(self, ctx, reminder_id: str = ""):
        """Удалить напоминание. Использование: !delremind <id>"""
        if not reminder_id:
            await ctx.reply("❌ Укажи ID напоминания: `!delremind <id>`")
            return

        if reminder_system.delete_reminder(reminder_id, ctx.author.id):
            await ctx.reply(f"✅ Напоминание `{reminder_id}` удалено!")
        else:
            await ctx.reply("❌ Напоминание не найдено или не принадлежит тебе.")

    # ═══════════════════════
    # ⭐ РЕПУТАЦИЯ И УРОВНИ
    # ═══════════════════════

    @commands.command(name='level', aliases=['rank', 'уровень', 'ранг', 'lvl'])
    async def show_level(self, ctx, user: discord.Member = None):
        """Показать уровень и карточку пользователя."""
        target = user or ctx.author
        card = reputation_system.get_user_card(target.id)

        if not card:
            # Создаём профиль если нет
            reputation_system.grant_xp(target.id, target.display_name, 'message', bonus_xp=0)
            card = reputation_system.get_user_card(target.id)

        if not card:
            await ctx.reply("❌ Профиль не найден.")
            return

        embed = discord.Embed(
            title=f"{card['title']} {target.display_name}",
            color=discord.Color.gold()
        )
        embed.set_thumbnail(url=target.display_avatar.url)

        embed.add_field(
            name=f"📊 Уровень {card['level']}",
            value=f"`{card['progress_bar']}` {card['progress_percent']}%\n"
                  f"XP: {card['xp_current']}/{card['xp_needed']}",
            inline=False
        )
        embed.add_field(name="⭐ Всего XP", value=str(card['total_xp']), inline=True)
        embed.add_field(name="💝 Репутация", value=str(card['rep_points']), inline=True)
        embed.add_field(name="🔥 Streak", value=f"{card['streak']} дней", inline=True)
        embed.add_field(name="💬 Сообщений", value=str(card['messages']), inline=True)
        embed.add_field(name="🤖 AI запросов", value=str(card['ai_requests']), inline=True)
        embed.add_field(
            name=f"🏆 Бейджи ({len(card['badges_list'])})",
            value=card['badges'],
            inline=False
        )

        await ctx.reply(embed=embed)

    @commands.command(name='rep', aliases=['reрутация', '+rep'])
    async def give_reputation(self, ctx, target: discord.Member = None):
        """Дать +rep пользователю. Использование: !rep @user"""
        if not target:
            await ctx.reply("❌ Укажи, кому дать репутацию: `!rep @пользователь`")
            return

        success, message = reputation_system.give_rep(
            from_id=ctx.author.id,
            to_id=target.id,
            from_name=ctx.author.display_name,
            to_name=target.display_name,
        )

        if success:
            embed = discord.Embed(
                title="💝 +REP",
                description=message,
                color=discord.Color.magenta()
            )
        else:
            embed = discord.Embed(
                title="❌ Ошибка",
                description=message,
                color=discord.Color.red()
            )

        await ctx.reply(embed=embed)

    @commands.command(name='daily', aliases=['ежедневный', 'бонус'])
    async def daily_bonus(self, ctx):
        """Получить ежедневный бонус XP!"""
        success, xp, streak, message = reputation_system.claim_daily(
            ctx.author.id, ctx.author.display_name
        )

        if success:
            embed = discord.Embed(
                title="🎁 Ежедневный бонус!",
                description=message,
                color=discord.Color.green()
            )
            if streak >= 7:
                embed.add_field(name="🔥 Streak!", value=f"{streak} дней подряд!", inline=False)
        else:
            embed = discord.Embed(
                title="⏰ Уже получен",
                description=message,
                color=discord.Color.dark_grey()
            )

        await ctx.reply(embed=embed)

    @commands.command(name='top', aliases=['leaderboard', 'лидерборд', 'топ'])
    async def leaderboard(self, ctx, sort: str = "xp"):
        """
        Лидерборд сервера.
        Сортировка: xp, rep, streak, messages
        """
        sort_names = {
            'xp': '⭐ XP', 'rep': '💝 Репутация',
            'streak': '🔥 Streak', 'messages': '💬 Сообщения',
        }

        if sort not in sort_names:
            sort = 'xp'

        board = reputation_system.get_leaderboard(limit=10, sort_by=sort)

        if not board:
            await ctx.reply("📊 Лидерборд пуст!")
            return

        embed = discord.Embed(
            title=f"🏆 Лидерборд: {sort_names[sort]}",
            color=discord.Color.gold()
        )

        medals = ['🥇', '🥈', '🥉']
        lines = []
        for entry in board:
            rank_display = medals[entry['rank'] - 1] if entry['rank'] <= 3 else f"`#{entry['rank']}`"
            lines.append(
                f"{rank_display} **{entry['name']}** — "
                f"Уровень {entry['level']} | {entry['xp']} XP | "
                f"({entry['progress_percent']}%)"
            )

        embed.description = "\n".join(lines)
        embed.set_footer(text=f"Сортировка: {sort_names[sort]}")

        await ctx.reply(embed=embed)

    @commands.command(name='badges', aliases=['бейджи', 'достижения'])
    async def show_badges(self, ctx, user: discord.Member = None):
        """Показать все бейджи пользователя."""
        target = user or ctx.author
        card = reputation_system.get_user_card(target.id)

        if not card:
            await ctx.reply("❌ Профиль не найден.")
            return

        embed = discord.Embed(
            title=f"🏆 Достижения {target.display_name}",
            color=discord.Color.gold()
        )

        # Полученные
        obtained = []
        for badge_id in card['badges_list']:
            if badge_id in BADGES:
                emoji, name, desc, _ = BADGES[badge_id]
                obtained.append(f"{emoji} **{name}** — {desc}")

        # Не полученные
        locked = []
        for badge_id, (emoji, name, desc, condition) in BADGES.items():
            if badge_id not in card['badges_list']:
                locked.append(f"🔒 ~~{name}~~ — {condition}")

        if obtained:
            embed.add_field(
                name=f"✅ Получено ({len(obtained)})",
                value="\n".join(obtained[:15]),
                inline=False
            )

        if locked:
            embed.add_field(
                name=f"🔒 Заблокировано ({len(locked)})",
                value="\n".join(locked[:10]),
                inline=False
            )

        await ctx.reply(embed=embed)

    # ═══════════════════════
    # 🎭 ЛИЧНОСТЬ
    # ═══════════════════════

    @commands.command(name='personality', aliases=['persona', 'личность'])
    async def manage_personality(self, ctx, action: str = "list", *, value: str = ""):
        """
        Управление личностью бота.
        
        !personality — список личностей
        !personality switch pirate — переключить 
        !personality info sensei — подробности
        !personality reset — сбросить на дефолт
        """
        if action == 'list':
            personas = personality_engine.list_personalities()
            embed = discord.Embed(
                title="🎭 Доступные личности",
                color=discord.Color.purple()
            )

            for p in personas:
                custom_tag = " [custom]" if p['is_custom'] else ""
                embed.add_field(
                    name=f"{p['emoji']} {p['name']}{custom_tag}",
                    value=f"ID: `{p['id']}`\n{p['description'][:80]}",
                    inline=True
                )

            # Текущая личность
            current = personality_engine.get_active_personality(ctx.channel.id)
            embed.set_footer(text=f"Текущая: {current.emoji} {current.name} | Переключить: !personality switch <id>")

            await ctx.reply(embed=embed)

        elif action in ('switch', 'set', 'use'):
            if not permissions.has_permission(ctx.author.id, 'commands.personality.manage'):
                 await ctx.reply("❌ Нет прав на смену личности.")
                 return

            if not value:
                await ctx.reply("❌ Укажи ID личности: `!personality switch pirate`")
                return

            success, greeting = personality_engine.switch_channel_persona(ctx.channel.id, value)

            if success:
                persona = personality_engine.get_personality(value)
                embed = discord.Embed(
                    title=f"🎭 Личность переключена: {persona.emoji} {persona.name}",
                    description=greeting,
                    color=discord.Color.purple()
                )
                if persona.style_hints:
                    embed.add_field(
                        name="📝 Стиль",
                        value=", ".join(persona.style_hints),
                        inline=False
                    )
                await ctx.reply(embed=embed)
            else:
                await ctx.reply(f"❌ {greeting}")

        elif action in ('info', 'details'):
            persona = personality_engine.get_personality(value)
            if not persona:
                await ctx.reply(f"❌ Личность '{value}' не найдена")
                return

            embed = discord.Embed(
                title=f"{persona.emoji} {persona.name}",
                description=persona.description,
                color=discord.Color.purple()
            )
            embed.add_field(name="🌡️ Температура", value=str(persona.temperature), inline=True)
            embed.add_field(name="📊 Использований", value=str(persona.uses_count), inline=True)
            embed.add_field(name="📝 Стиль", value=", ".join(persona.style_hints), inline=False)
            embed.add_field(name="👋 Приветствие", value=persona.greeting[:200], inline=False)

            await ctx.reply(embed=embed)

        elif action == 'reset':
            if not permissions.has_permission(ctx.author.id, 'commands.personality.manage'):
                 await ctx.reply("❌ Нет прав.")
                 return
            personality_engine.reset_channel_persona(ctx.channel.id)
            await ctx.reply("✅ Личность сброшена на стандартную.")

    # ═══════════════════════
    # 📚 БАЗА ЗНАНИЙ
    # ═══════════════════════

    @commands.command(name='kb', aliases=['wiki', 'знания'])
    async def knowledge_base_cmd(self, ctx, action: str = "help", *, content: str = ""):
        """
        База знаний сервера.
        
        !kb search programming — поиск
        !kb read 5 — прочитать статью #5
        !kb add Название | Содержание — добавить
        !kb list — список статей
        !kb categories — категории
        """
        guild_id = ctx.guild.id if ctx.guild else 0

        if action == 'help':
            embed = discord.Embed(
                title="📚 База знаний",
                description=(
                    "**Команды:**\n"
                    "• `!kb search <запрос>` — поиск\n"
                    "• `!kb read <id>` — прочитать статью\n"
                    "• `!kb add Название | Содержание` — добавить\n"
                    "• `!kb list [категория]` — список\n"
                    "• `!kb categories` — категории\n"
                    "• `!kb edit <id> | Новое содержание` — редактировать"
                ),
                color=discord.Color.dark_teal()
            )
            await ctx.reply(embed=embed)

        elif action == 'search':
            if not content:
                await ctx.reply("❌ Укажи запрос: `!kb search программирование`")
                return

            results = knowledge_base.search(content, guild_id, limit=5)
            if not results:
                await ctx.reply("🔍 Ничего не найдено.")
                return

            embed = discord.Embed(
                title=f"🔍 Результаты: {content}",
                color=discord.Color.dark_teal()
            )
            for r in results:
                tags = " ".join([f"`{t}`" for t in r['tags']]) if r['tags'] else ""
                pinned = "📌 " if r['pinned'] else ""
                embed.add_field(
                    name=f"{pinned}#{r['id']} {r['title']}",
                    value=f"{r['content'][:150]}\n{tags}\n👁️ {r['views']} | ✍️ {r['author']}",
                    inline=False
                )

            await ctx.reply(embed=embed)

        elif action == 'read':
            try:
                article_id = int(content.strip())
            except (ValueError, AttributeError):
                await ctx.reply("❌ Формат: `!kb read <id>`")
                return

            article = knowledge_base.get_article(article_id)
            if not article:
                await ctx.reply("❌ Статья не найдена.")
                return

            tags = " ".join([f"`{t}`" for t in article['tags']]) if article['tags'] else ""

            embed = discord.Embed(
                title=f"📚 {article['title']}",
                description=article['content'][:4000],
                color=discord.Color.dark_teal()
            )
            embed.add_field(name="📁 Категория", value=article['category'], inline=True)
            embed.add_field(name="👁️ Просмотров", value=str(article['views']), inline=True)
            embed.add_field(name="✍️ Автор", value=article['author'], inline=True)
            if tags:
                embed.add_field(name="🏷️ Теги", value=tags, inline=False)
            embed.set_footer(
                text=f"Создано: {article['created']} | Обновлено: {article['updated']}"
            )

            await ctx.reply(embed=embed)

        elif action == 'add':
            if not permissions.has_permission(ctx.author.id, 'commands.kb.manage'):
                 await ctx.reply("❌ Нет прав на добавление статей.")
                 return

            parts = content.split('|', 1)
            if len(parts) < 2:
                await ctx.reply("❌ Формат: `!kb add Название | Содержание статьи`")
                return

            title = parts[0].strip()
            body = parts[1].strip()

            article_id, error = knowledge_base.create_article(
                title=title,
                content=body,
                guild_id=guild_id,
                author_id=ctx.author.id,
                author_name=ctx.author.display_name,
            )

            if error:
                await ctx.reply(f"❌ {error}")
            else:
                embed = discord.Embed(
                    title="📚 Статья создана!",
                    description=f"**{title}** (ID: #{article_id})",
                    color=discord.Color.green()
                )
                await ctx.reply(embed=embed)
                reputation_system.grant_xp(ctx.author.id, ctx.author.display_name, 'message', bonus_xp=25)

        elif action == 'list':
            category = content.strip() if content else None
            articles = knowledge_base.list_articles(guild_id, category=category)

            if not articles:
                await ctx.reply("📭 Нет статей.")
                return

            embed = discord.Embed(
                title="📚 Статьи базы знаний",
                color=discord.Color.dark_teal()
            )

            for a in articles[:15]:
                pinned = "📌 " if a['pinned'] else ""
                embed.add_field(
                    name=f"{pinned}#{a['id']} {a['title']}",
                    value=f"{a['preview']}\n`{a['category']}` | ✍️ {a['author']} | 👁️ {a['views']}",
                    inline=False
                )

            await ctx.reply(embed=embed)

        elif action == 'categories':
            cats = knowledge_base.get_categories(guild_id)
            if not cats:
                await ctx.reply("📁 Нет категорий.")
                return

            embed = discord.Embed(
                title="📁 Категории",
                description="\n".join([f"📂 **{c['name']}** — {c['count']} статей" for c in cats]),
                color=discord.Color.dark_teal()
            )
            await ctx.reply(embed=embed)

    # ═══════════════════════
    # 🎭 НАСТРОЕНИЕ
    # ═══════════════════════

    @commands.command(name='mood', aliases=['настроение', 'vibes'])
    async def show_mood(self, ctx, user: discord.Member = None):
        """Показать настроение пользователя или канала."""
        if user:
            mood = mood_analyzer.get_user_mood(user.id)
            embed = discord.Embed(
                title=f"{mood['emoji']} Настроение: {user.display_name}",
                color=discord.Color.purple()
            )
            embed.add_field(name="Настроение", value=mood['mood'].capitalize(), inline=True)
            embed.add_field(name="Score", value=str(mood['score']), inline=True)
            embed.add_field(name="Тренд", value=mood['trend'], inline=True)
            embed.add_field(name="Сэмплов", value=str(mood['samples']), inline=True)
        else:
            channel_mood = mood_analyzer.get_channel_mood(ctx.channel.id)
            embed = discord.Embed(
                title=f"{channel_mood['emoji']} Атмосфера канала",
                color=discord.Color.purple()
            )
            embed.add_field(name="Настроение", value=channel_mood['mood'].capitalize(), inline=True)
            embed.add_field(
                name="Баланс",
                value=f"👍 {channel_mood['positive_percent']}% | 👎 {channel_mood['negative_percent']}%",
                inline=True
            )
            embed.add_field(
                name="Участников",
                value=str(channel_mood['participants']),
                inline=True
            )

        await ctx.reply(embed=embed)

    # ═══════════════════════
    # 🏥 ЗДОРОВЬЕ БОТА
    # ═══════════════════════

    @commands.command(name='health', aliases=['здоровье', 'status', 'uptime'])
    async def show_health(self, ctx):
        """Показать состояние здоровья бота."""
        health_monitor.heartbeat()
        perf = health_monitor.get_performance_summary()

        embed = discord.Embed(
            title="🏥 Здоровье бота",
            color=discord.Color.green() if perf['heartbeat_alive'] else discord.Color.red()
        )

        embed.add_field(name="⏱️ Uptime", value=perf['uptime'], inline=True)
        embed.add_field(name="📊 Запросов", value=str(perf['total_requests']), inline=True)
        embed.add_field(name="❌ Ошибок", value=f"{perf['error_count']} ({perf['error_rate']})", inline=True)
        embed.add_field(name="⚡ Ср. ответ", value=f"{perf['avg_response_ms']}ms", inline=True)
        embed.add_field(name="📈 P95", value=f"{perf['p95_response_ms']}ms", inline=True)
        embed.add_field(name="🐍 Python", value=perf['python_version'], inline=True)

        # Алерты
        alerts_count = perf['alerts_unacknowledged']
        if alerts_count > 0:
            embed.add_field(
                name=f"⚠️ Алерты ({alerts_count})",
                value="Есть непрочитанные алерты",
                inline=False
            )

        # Пинг Discord
        ws_latency = round(self.bot.latency * 1000, 2)
        embed.add_field(name="🌐 WS Пинг", value=f"{ws_latency}ms", inline=True)

        await ctx.reply(embed=embed)

    # ═══════════════════════
    # 🌐 ПЕРЕВОД
    # ═══════════════════════

    @commands.command(name='translate', aliases=['перевод', 'переведи', 'tr'])
    async def translate(self, ctx, lang: str = "", *, text: str = ""):
        """
        Перевод текста через AI.
        Использование: !translate en Привет мир!
        """
        if not lang or not text:
            await ctx.reply(
                "🌐 Формат: `!translate <язык> <текст>`\n"
                "Примеры:\n"
                "• `!translate en Привет мир!`\n"
                "• `!translate ru Hello world!`\n"
                "• `!translate ja Как дела?`"
            )
            return

        try:
            from modules.ai_provider import ai_provider

            lang_names = {
                'en': 'английский', 'ru': 'русский', 'es': 'испанский',
                'fr': 'французский', 'de': 'немецкий', 'ja': 'японский',
                'zh': 'китайский', 'ko': 'корейский', 'it': 'итальянский',
                'pt': 'португальский', 'ar': 'арабский', 'hi': 'хинди',
                'uk': 'украинский', 'pl': 'польский', 'tr': 'турецкий',
            }
            lang_display = lang_names.get(lang.lower(), lang)

            result = ai_provider.generate_response(
                system_prompt=f"Ты — переводчик. Переведи текст на {lang_display}. Отвечай ТОЛЬКО переводом, без пояснений.",
                user_message=text,
                max_tokens=500,
                temperature=0.2
            )

            embed = discord.Embed(
                title=f"🌐 Перевод → {lang_display.capitalize()}",
                color=discord.Color.blue()
            )
            embed.add_field(name="📝 Оригинал", value=text[:500], inline=False)
            embed.add_field(name="🌍 Перевод", value=result['content'][:1000], inline=False)

            await ctx.reply(embed=embed)

        except Exception as e:
            await ctx.reply(f"❌ Ошибка перевода: {e}")


async def setup(bot):
    await bot.add_cog(UtilityCommands(bot))
