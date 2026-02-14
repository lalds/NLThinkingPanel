"""
Развлекательные команды (Fun Commands).

Включает:
 - !poll — создание голосований
 - !quiz — квизы и викторины
 - !duel — дуэли между пользователями
 - !fortune — предсказание/гадание
 - !8ball — магический шар
 - !flip — монетка
 - !roll — кости
 - !rps — камень-ножницы-бумага
 - !meme — генерация мемов через AI
 - !roast — дружеский прожарка через AI
 - !compliment — комплимент через AI
"""
import discord
from discord.ext import commands
import random
import time
import asyncio
import hashlib
from typing import Dict, List, Optional, Any
from datetime import datetime

from core.logger import logger
from modules.reputation_system import reputation_system, BADGES
from modules.personality_engine import personality_engine
from core.permissions import permissions


# ─── Предсказания ───

FORTUNES = [
    ("🌟", "Звёзды благосклонны", "Сегодня удача на твоей стороне! Отличный день для новых начинаний."),
    ("⭐", "Благоприятно", "Хороший день. Возможны приятные сюрпризы от близких."),
    ("💫", "Нейтрально", "Обычный день. Но даже в обычном можно найти красоту."),
    ("🌙", "Будь осторожен", "Лучше дважды подумать, прежде чем действовать."),
    ("⚡", "Испытание", "Впереди вызов, но ты справишься!"),
    ("🔮", "Мистическое", "Скоро произойдёт нечто неожиданное..."),
    ("🍀", "Удача!", "Тебе повезёт! Купи лотерейный билет (шутка... но может быть)."),
    ("🌈", "Гармония", "День полон гармонии. Отличное время для творчества."),
    ("🎯", "Фокус", "Сконцентрируйся на главном — и результат не заставит себя ждать."),
    ("🦋", "Перемены", "Ветер перемен дует в твою сторону. Прими его."),
]

EIGHT_BALL_ANSWERS = [
    # Положительные
    "🟢 Определённо да!", "🟢 Без сомнений!", "🟢 Можешь быть уверен!",
    "🟢 Абсолютно!", "🟢 Звёзды говорят ДА!",
    # Нейтральные
    "🟡 Вероятнее всего...", "🟡 Хорошие шансы", "🟡 Знаки указывают на да",
    "🟡 Попробуй и узнаешь", "🟡 Спроси позже",
    # Отрицательные
    "🔴 Не рассчитывай на это", "🔴 Мой ответ — нет", "🔴 Весьма сомнительно",
    "🔴 Звёзды не в твою пользу", "🔴 Даже не думай!",
]

RPS_CHOICES = {
    '🪨': 'камень',
    '✂️': 'ножницы',
    '📄': 'бумага',
}

RPS_WINS = {
    'камень': 'ножницы',
    'ножницы': 'бумага',
    'бумага': 'камень',
}


class FunCommands(commands.Cog):
    """Развлекательные команды."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # Активные дуэли: channel_id -> duel data
        self._active_duels: Dict[int, Dict] = {}
        # Активные голосования: msg_id -> poll data
        self._active_polls: Dict[int, Dict] = {}
        # Активные квизы: channel_id -> quiz data
        self._active_quizzes: Dict[int, Dict] = {}

    async def cog_check(self, ctx):
        """Проверка прав для всех команд кога."""
        return permissions.has_permission(ctx.author.id, 'commands.fun')

    # ─── 🎲 Кости ───

    @commands.command(name='roll', aliases=['dice', 'кости'])
    async def roll_dice(self, ctx, dice_str: str = '1d6'):
        """
        Бросить кости.
        Формат: NdM (N кубиков с M гранями)
        
        Примеры: !roll 2d6, !roll 1d20, !roll 3d8
        """
        try:
            parts = dice_str.lower().split('d')
            if len(parts) != 2:
                raise ValueError

            num_dice = int(parts[0]) if parts[0] else 1
            num_sides = int(parts[1])

            if num_dice < 1 or num_dice > 100:
                await ctx.reply("❌ От 1 до 100 кубиков!")
                return
            if num_sides < 2 or num_sides > 1000:
                await ctx.reply("❌ От 2 до 1000 граней!")
                return

            rolls = [random.randint(1, num_sides) for _ in range(num_dice)]
            total = sum(rolls)

            # Красивый вывод
            if num_dice <= 10:
                dice_display = " + ".join([f"**{r}**" for r in rolls])
                embed = discord.Embed(
                    title="🎲 Бросок костей!",
                    description=f"{dice_display}\n\n📊 **Итого: {total}**",
                    color=discord.Color.orange()
                )
            else:
                embed = discord.Embed(
                    title="🎲 Бросок костей!",
                    description=f"🎯 {num_dice}d{num_sides}\n\n📊 **Итого: {total}**\n"
                                f"Мин: {min(rolls)} | Макс: {max(rolls)} | Среднее: {total/num_dice:.1f}",
                    color=discord.Color.orange()
                )

            await ctx.reply(embed=embed)

            # XP
            reputation_system.grant_xp(ctx.author.id, ctx.author.display_name, 'message')

        except (ValueError, IndexError):
            await ctx.reply("❌ Формат: `!roll NdM` (например `!roll 2d6`)")

    # ─── 🪙 Монетка ───

    @commands.command(name='flip', aliases=['coin', 'монетка'])
    async def flip_coin(self, ctx):
        """Бросить монетку."""
        result = random.choice(['Орёл! 🦅', 'Решка! 👑'])
        edge = random.randint(1, 100) == 1  # 1% шанс ребра

        if edge:
            result = '🤯 Монетка встала на ребро!!!'
            color = discord.Color.gold()
        elif 'Орёл' in result:
            color = discord.Color.blue()
        else:
            color = discord.Color.red()

        embed = discord.Embed(
            title="🪙 Бросок монетки",
            description=f"**{result}**",
            color=color
        )
        await ctx.reply(embed=embed)

    # ─── 🔮 Магический шар ───

    @commands.command(name='8ball', aliases=['шар', 'ball'])
    async def eight_ball(self, ctx, *, question: str = ""):
        """Задай вопрос магическому шару!"""
        if not question:
            await ctx.reply("❓ Задай вопрос! Пример: `!8ball Будет ли сегодня хороший день?`")
            return

        answer = random.choice(EIGHT_BALL_ANSWERS)

        embed = discord.Embed(
            title="🔮 Магический шар",
            color=discord.Color.purple()
        )
        embed.add_field(name="❓ Вопрос", value=question[:500], inline=False)
        embed.add_field(name="🔮 Ответ", value=answer, inline=False)

        await ctx.reply(embed=embed)

    # ─── 🍀 Предсказание ───

    @commands.command(name='fortune', aliases=['предсказание', 'гадание'])
    async def fortune(self, ctx):
        """Получить предсказание на сегодня!"""
        # Детерминированное предсказание на основе user_id + даты
        seed = int(hashlib.md5(
            f"{ctx.author.id}-{datetime.now().strftime('%Y-%m-%d')}".encode()
        ).hexdigest(), 16)
        random.seed(seed)
        emoji, title, text = random.choice(FORTUNES)
        lucky_number = random.randint(1, 100)
        lucky_color = random.choice(['🔴', '🔵', '🟢', '🟡', '🟣', '🟠'])
        random.seed()  # Reset seed

        embed = discord.Embed(
            title=f"{emoji} Предсказание дня",
            description=f"**{title}**\n\n{text}",
            color=discord.Color.dark_purple(),
            timestamp=datetime.now()
        )
        embed.add_field(name="🔢 Счастливое число", value=str(lucky_number), inline=True)
        embed.add_field(name="🎨 Счастливый цвет", value=lucky_color, inline=True)
        embed.set_footer(text=f"Предсказание для {ctx.author.display_name}")

        await ctx.reply(embed=embed)

    # ─── ✂️ Камень-ножницы-бумага ───

    @commands.command(name='rps', aliases=['кнб', 'камень'])
    async def rock_paper_scissors(self, ctx, *, choice: str = ""):
        """Камень-ножницы-бумага! Использование: !rps камень"""
        choice_map = {
            'камень': 'камень', 'rock': 'камень', 'к': 'камень', '🪨': 'камень',
            'ножницы': 'ножницы', 'scissors': 'ножницы', 'н': 'ножницы', '✂️': 'ножницы',
            'бумага': 'бумага', 'paper': 'бумага', 'б': 'бумага', '📄': 'бумага',
        }

        user_choice = choice_map.get(choice.lower().strip())
        if not user_choice:
            await ctx.reply("✂️ Выбери: `!rps камень`, `!rps ножницы`, или `!rps бумага`")
            return

        bot_choice = random.choice(['камень', 'ножницы', 'бумага'])
        
        emoji_map = {'камень': '🪨', 'ножницы': '✂️', 'бумага': '📄'}

        if user_choice == bot_choice:
            result = "🤝 Ничья!"
            color = discord.Color.yellow()
        elif RPS_WINS[user_choice] == bot_choice:
            result = "🏆 Ты победил!"
            color = discord.Color.green()
            reputation_system.grant_xp(ctx.author.id, ctx.author.display_name, 'message', bonus_xp=5)
        else:
            result = "💀 Ты проиграл!"
            color = discord.Color.red()

        embed = discord.Embed(
            title="Камень-Ножницы-Бумага",
            color=color
        )
        embed.add_field(
            name=f"Ты: {emoji_map[user_choice]}",
            value=user_choice.capitalize(),
            inline=True
        )
        embed.add_field(name="VS", value="⚔️", inline=True)
        embed.add_field(
            name=f"Бот: {emoji_map[bot_choice]}",
            value=bot_choice.capitalize(),
            inline=True
        )
        embed.add_field(name="Результат", value=result, inline=False)

        await ctx.reply(embed=embed)

    # ─── 📊 Голосования ───

    @commands.command(name='poll', aliases=['голосование', 'опрос'])
    async def create_poll(self, ctx, *, poll_text: str = ""):
        """
        Создать голосование.
        Формат: !poll Вопрос | Вариант1 | Вариант2 | Вариант3
        
        Максимум 10 вариантов. Если без вариантов — да/нет голосование.
        """
        if not poll_text:
            await ctx.reply(
                "📊 Формат: `!poll Вопрос | Вариант1 | Вариант2`\n"
                "Или просто: `!poll Вопрос` (для да/нет)"
            )
            return

        parts = [p.strip() for p in poll_text.split('|')]
        question = parts[0]

        number_emojis = ['1️⃣', '2️⃣', '3️⃣', '4️⃣', '5️⃣', '6️⃣', '7️⃣', '8️⃣', '9️⃣', '🔟']

        if len(parts) == 1:
            # Да / Нет голосование
            embed = discord.Embed(
                title="📊 Голосование",
                description=question,
                color=discord.Color.blue(),
                timestamp=datetime.now()
            )
            embed.set_footer(text=f"Создал: {ctx.author.display_name}")

            msg = await ctx.send(embed=embed)
            await msg.add_reaction('👍')
            await msg.add_reaction('👎')
            await msg.add_reaction('🤷')
        else:
            # Мультивариантное голосование
            options = parts[1:][:10]

            description = "\n".join([
                f"{number_emojis[i]} {option}"
                for i, option in enumerate(options)
            ])

            embed = discord.Embed(
                title=f"📊 {question}",
                description=description,
                color=discord.Color.blue(),
                timestamp=datetime.now()
            )
            embed.set_footer(
                text=f"Создал: {ctx.author.display_name} | Голосуйте реакциями!"
            )

            msg = await ctx.send(embed=embed)
            for i in range(len(options)):
                await msg.add_reaction(number_emojis[i])

    # ─── ⚔️ Дуэли ───

    @commands.command(name='duel', aliases=['дуэль', 'бой'])
    async def duel(self, ctx, opponent: discord.Member = None):
        """
        Вызвать на дуэль другого участника!
        Использование: !duel @user
        """
        if not opponent:
            await ctx.reply("⚔️ Укажи, кого вызвать: `!duel @пользователь`")
            return

        if opponent.id == ctx.author.id:
            await ctx.reply("🤦 Нельзя вызвать себя на дуэль!")
            return

        if opponent.bot:
            await ctx.reply("🤖 Нельзя драться с ботом!")
            return

        if ctx.channel.id in self._active_duels:
            await ctx.reply("⚔️ В этом канале уже идёт дуэль! Подожди.")
            return

        # Приглашение
        embed = discord.Embed(
            title="⚔️ Вызов на дуэль!",
            description=(
                f"**{ctx.author.display_name}** вызывает **{opponent.display_name}** на дуэль!\n\n"
                f"{opponent.mention}, прими вызов реакцией ⚔️ (30 секунд)"
            ),
            color=discord.Color.red()
        )
        msg = await ctx.send(embed=embed)
        await msg.add_reaction('⚔️')

        # Ожидание ответа
        def check(reaction, user):
            return (
                user.id == opponent.id
                and str(reaction.emoji) == '⚔️'
                and reaction.message.id == msg.id
            )

        try:
            await self.bot.wait_for('reaction_add', timeout=30.0, check=check)
        except asyncio.TimeoutError:
            await ctx.send(f"⏰ {opponent.display_name} не принял вызов. Трус! 🐔")
            return

        # Дуэль!
        self._active_duels[ctx.channel.id] = True

        try:
            p1_hp = 100
            p2_hp = 100
            round_num = 0

            battle_log = []

            while p1_hp > 0 and p2_hp > 0 and round_num < 10:
                round_num += 1

                # Атаки
                p1_dmg = random.randint(10, 35)
                p2_dmg = random.randint(10, 35)

                # Критический удар (15%)
                p1_crit = random.random() < 0.15
                p2_crit = random.random() < 0.15
                if p1_crit:
                    p1_dmg = int(p1_dmg * 1.5)
                if p2_crit:
                    p2_dmg = int(p2_dmg * 1.5)

                # Промах (10%)
                p1_miss = random.random() < 0.10
                p2_miss = random.random() < 0.10

                if not p1_miss:
                    p2_hp = max(0, p2_hp - p1_dmg)
                    crit_text = " 💥 КРИТ!" if p1_crit else ""
                    battle_log.append(
                        f"⚔️ {ctx.author.display_name} наносит **{p1_dmg}** урона!{crit_text}"
                    )
                else:
                    battle_log.append(f"💨 {ctx.author.display_name} промахнулся!")

                if not p2_miss and p2_hp > 0:
                    p1_hp = max(0, p1_hp - p2_dmg)
                    crit_text = " 💥 КРИТ!" if p2_crit else ""
                    battle_log.append(
                        f"⚔️ {opponent.display_name} наносит **{p2_dmg}** урона!{crit_text}"
                    )
                elif p2_hp > 0:
                    battle_log.append(f"💨 {opponent.display_name} промахнулся!")

                battle_log.append(
                    f"❤️ {ctx.author.display_name}: {p1_hp} HP | "
                    f"{opponent.display_name}: {p2_hp} HP"
                )
                battle_log.append("─" * 30)

                await asyncio.sleep(0.5)

            # Определение победителя
            if p1_hp > p2_hp:
                winner = ctx.author
                loser = opponent
            elif p2_hp > p1_hp:
                winner = opponent
                loser = ctx.author
            else:
                winner = None

            # Результат
            if winner:
                result_text = f"🏆 **{winner.display_name}** побеждает!"
                color = discord.Color.gold()
                reputation_system.grant_xp(winner.id, winner.display_name, 'duel_win')
            else:
                result_text = "🤝 Ничья! Оба дуэлянта стоят на ногах."
                color = discord.Color.dark_grey()

            embed = discord.Embed(
                title="⚔️ Результат дуэли",
                description="\n".join(battle_log[-12:]) + f"\n\n{result_text}",
                color=color
            )
            embed.set_footer(text=f"Раундов: {round_num}")

            await ctx.send(embed=embed)

        finally:
            self._active_duels.pop(ctx.channel.id, None)

    # ─── 🤖 AI Fun ───

    @commands.command(name='roast', aliases=['прожарка'])
    async def roast(self, ctx, target: discord.Member = None):
        """Дружеская прожарка (через AI). Использование: !roast @user"""
        if not target:
            target = ctx.author

        try:
            from modules.ai_provider import ai_provider

            result = ai_provider.generate_response(
                system_prompt=(
                    "Ты — мастер дружеской прожарки. Сделай смешную, но НЕ оскорбительную "
                    "прожарку пользователя. Должно быть смешно и добродушно. "
                    "Максимум 2-3 предложения. Не используй нецензурную лексику."
                ),
                user_message=f"Прожарь пользователя с ником '{target.display_name}'",
                max_tokens=150,
                temperature=0.9
            )

            embed = discord.Embed(
                title=f"🔥 Прожарка: {target.display_name}",
                description=result['content'],
                color=discord.Color.orange()
            )
            embed.set_footer(text="Это шутка! Без обид! 😊")

            await ctx.reply(embed=embed)

        except Exception as e:
            await ctx.reply(f"❌ Ошибка прожарки: {e}")

    @commands.command(name='compliment', aliases=['комплимент'])
    async def compliment(self, ctx, target: discord.Member = None):
        """Сделать AI-комплимент пользователю."""
        if not target:
            target = ctx.author

        try:
            from modules.ai_provider import ai_provider

            result = ai_provider.generate_response(
                system_prompt=(
                    "Ты — мастер комплиментов. Скажи очень приятный и оригинальный "
                    "комплимент пользователю. Будь креативным и искренним. "
                    "2-3 предложения максимум."
                ),
                user_message=f"Сделай комплимент пользователю '{target.display_name}'",
                max_tokens=150,
                temperature=0.8
            )

            embed = discord.Embed(
                title=f"💝 Комплимент для {target.display_name}",
                description=result['content'],
                color=discord.Color.magenta()
            )

            await ctx.reply(embed=embed)

        except Exception as e:
            await ctx.reply(f"❌ Ошибка: {e}")

    @commands.command(name='meme', aliases=['мем'])
    async def generate_meme_text(self, ctx, *, topic: str = ""):
        """AI сгенерирует мем-текст на заданную тему."""
        if not topic:
            topic = "рандомная тема"

        try:
            from modules.ai_provider import ai_provider

            result = ai_provider.generate_response(
                system_prompt=(
                    "Ты — генератор мемов. Создай смешной мем в текстовом формате.\n"
                    "Формат:\n"
                    "🖼️ [Описание картинки]\n"
                    "📝 Верхний текст: ...\n"
                    "📝 Нижний текст: ...\n\n"
                    "Должно быть смешно и актуально!"
                ),
                user_message=f"Создай мем на тему: {topic}",
                max_tokens=200,
                temperature=0.95
            )

            embed = discord.Embed(
                title=f"🎭 Мем: {topic}",
                description=result['content'],
                color=discord.Color.green()
            )

            await ctx.reply(embed=embed)

        except Exception as e:
            await ctx.reply(f"❌ Ошибка: {e}")

    # ─── 🧠 Квиз ───

    @commands.command(name='quiz', aliases=['квиз', 'викторина'])
    async def quiz(self, ctx, *, category: str = "общие знания"):
        """
        Квиз! AI генерирует вопрос.
        Использование: !quiz [категория]
        Категории: наука, история, технологии, кино, музыка, спорт
        """
        if ctx.channel.id in self._active_quizzes:
            await ctx.reply("🧠 В этом канале уже идёт квиз!")
            return

        try:
            from modules.ai_provider import ai_provider

            result = ai_provider.generate_response(
                system_prompt=(
                    "Ты — квизмастер. Создай один вопрос с 4 вариантами ответа.\n"
                    "Формат (СТРОГО):\n"
                    "ВОПРОС: [вопрос]\n"
                    "А) [вариант]\n"
                    "Б) [вариант]\n"
                    "В) [вариант]\n"
                    "Г) [вариант]\n"
                    "ОТВЕТ: [Буква]\n\n"
                    "Вопрос должен быть интересным и не слишком лёгким."
                ),
                user_message=f"Категория: {category}",
                max_tokens=300,
                temperature=0.8
            )

            content = result['content']

            # Парсинг ответа
            lines = content.strip().split('\n')
            question_text = ""
            options = []
            correct_answer = ""

            for line in lines:
                line = line.strip()
                if line.upper().startswith('ВОПРОС:'):
                    question_text = line.split(':', 1)[1].strip()
                elif line.startswith(('А)', 'Б)', 'В)', 'Г)', 'A)', 'B)', 'C)', 'D)')):
                    options.append(line)
                elif line.upper().startswith('ОТВЕТ:'):
                    correct_answer = line.split(':', 1)[1].strip().upper()[0]

            if not question_text or len(options) < 4:
                await ctx.reply("🧠 Не удалось сгенерировать квиз. Попробуй ещё раз!")
                return

            letter_map = {'А': 0, 'Б': 1, 'В': 2, 'Г': 3, 'A': 0, 'B': 1, 'C': 2, 'D': 3}
            correct_idx = letter_map.get(correct_answer, 0)

            reaction_letters = ['🇦', '🇧', '🇨', '🇩']

            embed = discord.Embed(
                title=f"🧠 Квиз: {category.capitalize()}",
                description=f"**{question_text}**\n\n" + "\n".join([
                    f"{reaction_letters[i]} {opt}" for i, opt in enumerate(options)
                ]),
                color=discord.Color.teal()
            )
            embed.set_footer(text="Ответь реакцией! У тебя 30 секунд ⏰")

            msg = await ctx.send(embed=embed)
            for emoji in reaction_letters[:len(options)]:
                await msg.add_reaction(emoji)

            self._active_quizzes[ctx.channel.id] = {
                'msg_id': msg.id,
                'correct_idx': correct_idx,
                'answered': set(),
            }

            # Ждём 30 секунд
            await asyncio.sleep(30)

            # Подсчёт результатов
            if ctx.channel.id in self._active_quizzes:
                quiz_data = self._active_quizzes.pop(ctx.channel.id)

                msg = await ctx.channel.fetch_message(quiz_data['msg_id'])

                correct_emoji = reaction_letters[correct_idx]
                winners = []

                for reaction in msg.reactions:
                    if str(reaction.emoji) == correct_emoji:
                        async for user in reaction.users():
                            if not user.bot:
                                winners.append(user)

                result_embed = discord.Embed(
                    title="🧠 Результаты квиза!",
                    color=discord.Color.green()
                )
                result_embed.add_field(
                    name="✅ Правильный ответ",
                    value=f"{correct_emoji} {options[correct_idx]}",
                    inline=False
                )

                if winners:
                    winner_list = ", ".join([w.display_name for w in winners])
                    result_embed.add_field(
                        name=f"🏆 Победители ({len(winners)})",
                        value=winner_list,
                        inline=False
                    )
                    for w in winners:
                        reputation_system.grant_xp(w.id, w.display_name, 'quiz_win')
                else:
                    result_embed.add_field(
                        name="😢 Победители",
                        value="Никто не ответил правильно!",
                        inline=False
                    )

                await ctx.send(embed=result_embed)

        except Exception as e:
            self._active_quizzes.pop(ctx.channel.id, None)
            await ctx.reply(f"❌ Ошибка квиза: {e}")


async def setup(bot):
    await bot.add_cog(FunCommands(bot))
