"""
Основной модуль бота с командами для взаимодействия с AI.
"""
import discord
from discord.ext import commands
import time
import asyncio
from core.logger import logger
from core.rate_limiter import rate_limiter
from modules.ai_provider import ai_provider
from modules.analytics import analytics
from modules.context_builder import context_builder
from modules.search_engine import search_engine
from modules.user_profiles import user_profiles
from config.config import config


class AICog(commands.Cog):
    """Основные AI команды бота."""
    
    def __init__(self, bot):
        self.bot = bot
    
    @commands.Cog.listener()
    async def on_message(self, message):
        """Отслеживание сообщений для построения контекста."""
        # Игнорируем сообщения ботов
        if message.author.bot:
            return
        
        # Игнорируем команды
        if message.content.startswith(config.command_prefix):
            return
        
        # Добавляем в историю
        if message.guild:
            context_builder.add_message(
                channel_id=message.channel.id,
                author=message.author.display_name,
                content=message.content
            )
    
    @commands.command(name='ask')
    async def ask(self, ctx, *, question: str):
        """
        Задать вопрос AI с полным контекстом сервера.
        
        Использование: !ask [ваш вопрос]
        
        Примеры:
        !ask Кто сейчас играет в игры?
        !ask Что посоветуешь посмотреть?
        !ask Помоги мне с Python кодом
        """
        # Проверка rate limit
        if config.rate_limit_enabled:
            if not rate_limiter.is_allowed(ctx.author.id):
                remaining_time = rate_limiter.get_reset_time(ctx.author.id)
                await ctx.send(
                    f"⏳ {ctx.author.mention}, вы превысили лимит запросов. "
                    f"Попробуйте снова через {int(remaining_time)} секунд."
                )
                logger.warning(f"Rate limit exceeded for user {ctx.author.name}")
                return
        
        if len(question) > config.max_user_input_chars:
            await ctx.send(
                f"⚠️ Слишком длинный запрос. Максимум {config.max_user_input_chars} символов."
            )
            return

        async with ctx.typing():
            try:
                start_time = time.time()
                
                # Построение контекста
                full_prompt = context_builder.build_full_context(
                    guild=ctx.guild,
                    channel_id=ctx.channel.id,
                    author_name=ctx.author.display_name,
                    system_prompt=config.system_prompt
                )
                
                # Добавление профиля пользователя (если есть)
                user_profile_context = user_profiles.format_profile_for_context(
                    user_id=ctx.author.id,
                    user_name=ctx.author.display_name
                )
                if user_profile_context:
                    full_prompt += "\n" + user_profile_context
                
                # Оптимизация промпта если слишком длинный
                estimated_tokens = ai_provider.estimate_tokens(full_prompt + question)
                if estimated_tokens > config.max_tokens * 0.7:
                    logger.info(f"Оптимизация промпта ({estimated_tokens} токенов)")
                    full_prompt = ai_provider.optimize_prompt(full_prompt)
                
                # Генерация ответа
                logger.info(f"Запрос от {ctx.author.name}: {question[:100]}...")
                
                result = ai_provider.generate_response(
                    system_prompt=full_prompt,
                    user_message=question,
                    use_cache=config.cache_enabled
                )
                
                response_time = time.time() - start_time
                
                # Логирование в аналитику
                if config.analytics_enabled:
                    analytics.log_request(
                        user_id=ctx.author.id,
                        user_name=ctx.author.display_name,
                        model=result['model'],
                        tokens_used=result['tokens_used'],
                        response_time=response_time
                    )
                
                # Отправка ответа
                answer = result['content']
                
                # Добавление footer с метаинформацией
                cache_indicator = '🔄 Из кэша' if result['from_cache'] else f"🤖 {result['model']}"
                footer = f"\n\n*{cache_indicator} | ⏱️ {result['response_time']:.2f}s*"
                
                # Разбивка длинных сообщений
                if len(answer + footer) > 2000:
                    chunks = self._split_message(answer, 1900)
                    for i, chunk in enumerate(chunks):
                        if i == len(chunks) - 1:
                            await ctx.send(chunk + footer)
                        else:
                            await ctx.send(chunk)
                else:
                    await ctx.send(answer + footer)
                
                logger.info(
                    f"Успешный ответ для {ctx.author.name} "
                    f"({result['tokens_used']} токенов, {response_time:.2f}s)"
                )
                
            except Exception as e:
                error_msg = str(e)
                logger.error(f"Ошибка при обработке запроса: {error_msg}", exc_info=True)
                
                if config.analytics_enabled:
                    analytics.log_error(
                        error_type='ask_command',
                        message=error_msg,
                        user_id=ctx.author.id
                    )
                
                await ctx.send(
                    "⚠️ Произошла ошибка при обработке запроса. "
                    "Подробности сохранены в логах."
                )
    
    @commands.command(name='quick')
    async def quick(self, ctx, *, question: str):
        """
        Быстрый вопрос без контекста сервера (быстрее и дешевле).
        
        Использование: !quick [вопрос]
        """
        # Проверка rate limit
        if config.rate_limit_enabled:
            if not rate_limiter.is_allowed(ctx.author.id):
                remaining_time = rate_limiter.get_reset_time(ctx.author.id)
                await ctx.send(
                    f"⏳ Превышен лимит. Попробуйте через {int(remaining_time)}s."
                )
                return

        if len(question) > config.max_user_input_chars:
            await ctx.send(
                f"⚠️ Слишком длинный запрос. Максимум {config.max_user_input_chars} символов."
            )
            return
        
        async with ctx.typing():
            try:
                start_time = time.time()
                
                # Простой промпт без контекста
                simple_prompt = "Ты полезный ассистент. Отвечай кратко и по делу."
                
                result = ai_provider.generate_response(
                    system_prompt=simple_prompt,
                    user_message=question,
                    use_cache=config.cache_enabled
                )
                
                response_time = time.time() - start_time
                
                # Аналитика
                if config.analytics_enabled:
                    analytics.log_request(
                        user_id=ctx.author.id,
                        user_name=ctx.author.display_name,
                        model=result['model'],
                        tokens_used=result['tokens_used'],
                        response_time=response_time
                    )
                
                answer = result['content']
                footer = f"\n\n*⚡ Quick mode | {result['response_time']:.2f}s*"
                
                if len(answer + footer) > 2000:
                    chunks = self._split_message(answer, 1900)
                    for i, chunk in enumerate(chunks):
                        if i == len(chunks) - 1:
                            await ctx.send(chunk + footer)
                        else:
                            await ctx.send(chunk)
                else:
                    await ctx.send(answer + footer)
                
            except Exception as e:
                logger.error(f"Ошибка в quick команде: {e}", exc_info=True)
                await ctx.send("⚠️ Ошибка обработки запроса. Подробности сохранены в логах.")
    
    @commands.command(name='context')
    async def show_context(self, ctx):
        """Показать текущий контекст сервера (что видит AI)."""
        user_context = context_builder.build_user_context(ctx.guild)
        message_history = context_builder.get_message_history(ctx.channel.id)
        
        embed = discord.Embed(
            title=f"🌐 Контекст сервера: {ctx.guild.name}",
            color=discord.Color.blue()
        )
        
        # Разбиваем на части если слишком длинный
        if len(user_context) > 1024:
            user_context = user_context[:1021] + "..."
        
        embed.add_field(
            name="👥 Пользователи и активность",
            value=user_context,
            inline=False
        )
        
        if len(message_history) > 1024:
            message_history = message_history[:1021] + "..."
        
        embed.add_field(
            name="💬 История сообщений",
            value=message_history,
            inline=False
        )

        web_memory = context_builder.get_web_research_context(ctx.channel.id)
        if web_memory:
            if len(web_memory) > 1024:
                web_memory = web_memory[:1021] + "..."
            embed.add_field(
                name="🌍 Память веб-исследований",
                value=web_memory,
                inline=False
            )
        
        await ctx.send(embed=embed)

    @commands.command(name='web')
    async def web_search(self, ctx, *, question: str):
        """
        Поиск в сети, скрапинг нескольких страниц и краткая выжимка.
        Накопленная выжимка сохраняется в контексте текущего канала.
        """
        if config.rate_limit_enabled:
            if not rate_limiter.is_allowed(ctx.author.id):
                remaining_time = rate_limiter.get_reset_time(ctx.author.id)
                await ctx.send(f"⏳ Превышен лимит. Попробуйте через {int(remaining_time)} секунд.")
                return

        if len(question) > config.max_user_input_chars:
            await ctx.send(
                f"⚠️ Слишком длинный запрос. Максимум {config.max_user_input_chars} символов."
            )
            return

        async with ctx.typing():
            try:
                start_time = time.time()
                status_msg = await ctx.send(f"🔍 Ищу в сети информацию по запросу: *{question}*...")

                search_results = search_engine.search(question, max_results=7)
                if not search_results:
                    await status_msg.edit(content="❌ К сожалению, поиск не дал результатов.")
                    return

                await status_msg.edit(content="🌐 Открываю найденные страницы и собираю факты...")
                scraped_pages = search_engine.scrape_search_results(
                    search_results,
                    max_pages=3,
                    per_page_chars=3500
                )

                web_context = search_engine.format_results_for_ai(search_results)
                scraped_context = search_engine.format_scraped_for_ai(scraped_pages)
                memory_context = context_builder.get_web_research_context(ctx.channel.id)

                server_context = context_builder.build_user_context(ctx.guild)
                user_profile_context = user_profiles.format_profile_for_context(
                    user_id=ctx.author.id,
                    user_name=ctx.author.display_name
                )
                
                full_system_prompt = f"""{config.system_prompt}

Ты — ИИ-ассистент с доступом к Интернету.
Тебе переданы: результаты выдачи, извлечённый текст с нескольких страниц и память предыдущих веб-исследований в этом канале.

Требования к ответу:
1) Сначала дай краткую выжимку (3-7 пунктов).
2) Затем дай развернутый ответ по вопросу.
3) В конце добавь блок 'Источники' со ссылками, только из предоставленных данных.
4) Если данных недостаточно — явно так и скажи.

{web_context}

{scraped_context}

{memory_context if memory_context else ''}

---
Контекст сервера (для справки):
{server_context}
---

{user_profile_context if user_profile_context else ''}

Пользователь: {ctx.author.display_name}
Вопрос: {question}
"""
                
                await status_msg.edit(content="🧠 Делаю выжимку из собранных страниц...")
                result = ai_provider.generate_response(
                    system_prompt=full_system_prompt,
                    user_message=f"Сделай выжимку и ответ на вопрос: {question}",
                    use_cache=config.cache_enabled
                )
                
                response_time = time.time() - start_time

                if config.analytics_enabled:
                    analytics.log_request(
                        user_id=ctx.author.id,
                        user_name=ctx.author.display_name,
                        model=result['model'],
                        tokens_used=result['tokens_used'],
                        response_time=response_time
                    )

                source_urls = [page['href'] for page in scraped_pages[:5]]
                if not source_urls:
                    source_urls = [res.get('href', '') for res in search_results[:3] if res.get('href')]

                memory_summary = search_engine.build_memory_summary(question, scraped_pages)
                context_builder.add_web_research(
                    channel_id=ctx.channel.id,
                    query=question,
                    summary=memory_summary,
                    sources=source_urls
                )
                
                answer = result['content']
                footer = (
                    f"\n\n*🌐 Web+Scrape Mode | источников: {len(source_urls)} | "
                    f"{result['model']} | {result['response_time']:.2f}s*"
                )
                
                await status_msg.delete()

                if len(answer + footer) > 2000:
                    chunks = self._split_message(answer, 1900)
                    for i, chunk in enumerate(chunks):
                        if i == len(chunks) - 1:
                            await ctx.send(chunk + footer)
                        else:
                            await ctx.send(chunk)
                else:
                    await ctx.send(answer + footer)
                    
            except Exception as e:
                logger.error(f"Ошибка в команде !web: {e}", exc_info=True)
                await ctx.send("⚠️ Произошла ошибка при поиске. Подробности сохранены в логах.")
    
    @commands.group(name='profile', invoke_without_command=True)
    async def profile(self, ctx):
        """
        Управление вашим персональным профилем.
        
        Использование:
        !profile set <информация о вас>
        !profile show
        !profile delete
        """
        await ctx.send(
            "📋 **Управление профилем**\n\n"
            "Доступные команды:\n"
            "`!profile set <текст>` - Установить/обновить ваш профиль\n"
            "`!profile show` - Показать ваш профиль\n"
            "`!profile delete` - Удалить ваш профиль\n\n"
            "💡 Профиль используется ботом для персонализации ответов!"
        )
    
    @profile.command(name='set')
    async def profile_set(self, ctx, *, profile_text: str):
        """
        Установить или обновить ваш профиль.
        
        Примеры:
        !profile set Меня зовут Иван, я программист на Python. Люблю научную фантастику и кофе.
        !profile set Студент, изучаю машинное обучение. Предпочитаю краткие ответы.
        """
        if len(profile_text) > 1000:
            await ctx.send("⚠️ Профиль слишком длинный! Максимум 1000 символов.")
            return
        
        success = user_profiles.set_profile(
            user_id=ctx.author.id,
            user_name=ctx.author.display_name,
            profile_text=profile_text
        )
        
        if success:
            embed = discord.Embed(
                title="✅ Профиль сохранен!",
                description=f"Ваш профиль успешно {'обновлен' if user_profiles.has_profile(ctx.author.id) else 'создан'}.",
                color=discord.Color.green()
            )
            embed.add_field(
                name="📝 Ваш профиль:",
                value=profile_text[:1024],
                inline=False
            )
            embed.set_footer(text="Бот будет использовать эту информацию для персонализации ответов")
            await ctx.send(embed=embed)
            logger.info(f"Профиль установлен для {ctx.author.name}")
        else:
            await ctx.send("⚠️ Ошибка при сохранении профиля. Попробуйте позже.")
    
    @profile.command(name='show')
    async def profile_show(self, ctx):
        """Показать ваш текущий профиль."""
        profile_data = user_profiles.get_full_profile_data(ctx.author.id)
        
        if not profile_data:
            await ctx.send(
                "📋 У вас еще нет профиля.\n"
                "Создайте его командой: `!profile set <информация о вас>`"
            )
            return
        
        embed = discord.Embed(
            title=f"📋 Профиль: {ctx.author.display_name}",
            description=profile_data['profile'],
            color=discord.Color.blue()
        )
        embed.add_field(
            name="📅 Создан",
            value=profile_data['created_at'][:10],
            inline=True
        )
        embed.add_field(
            name="🔄 Обновлен",
            value=profile_data['updated_at'][:10],
            inline=True
        )
        embed.set_footer(text="Используйте !profile set для обновления")
        await ctx.send(embed=embed)
    
    @profile.command(name='delete')
    async def profile_delete(self, ctx):
        """Удалить ваш профиль."""
        if not user_profiles.has_profile(ctx.author.id):
            await ctx.send("📋 У вас нет профиля для удаления.")
            return
        
        # Подтверждение удаления
        confirm_msg = await ctx.send(
            "⚠️ **Подтверждение удаления**\n"
            "Вы уверены, что хотите удалить свой профиль?\n"
            "Отреагируйте ✅ для подтверждения или ❌ для отмены."
        )
        
        await confirm_msg.add_reaction("✅")
        await confirm_msg.add_reaction("❌")
        
        def check(reaction, user):
            return user == ctx.author and str(reaction.emoji) in ["✅", "❌"] and reaction.message.id == confirm_msg.id
        
        try:
            reaction, user = await self.bot.wait_for('reaction_add', timeout=30.0, check=check)
            
            if str(reaction.emoji) == "✅":
                if user_profiles.delete_profile(ctx.author.id):
                    await ctx.send("✅ Ваш профиль успешно удален.")
                else:
                    await ctx.send("⚠️ Ошибка при удалении профиля.")
            else:
                await ctx.send("❌ Удаление отменено.")
                
        except asyncio.TimeoutError:
            await ctx.send("⏱️ Время ожидания истекло. Удаление отменено.")

    def _split_message(self, text: str, chunk_size: int = 1900) -> list:
        """Разбивка длинного сообщения на части."""
        chunks = []
        current_chunk = ""
        
        for line in text.split('\n'):
            if len(current_chunk) + len(line) + 1 > chunk_size:
                if current_chunk:
                    chunks.append(current_chunk)
                current_chunk = line
            else:
                current_chunk += ('\n' if current_chunk else '') + line
        
        if current_chunk:
            chunks.append(current_chunk)
        
        return chunks


async def setup(bot):
    """Регистрация Cog."""
    await bot.add_cog(AICog(bot))
