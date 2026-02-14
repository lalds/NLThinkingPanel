"""
Основной модуль бота с командами для взаимодействия с AI.
"""
import discord
from discord.ext import commands
import time
import asyncio
from core.logger import logger
from core.rate_limiter import rate_limiter
from core.permissions import permissions
from core.event_system import event_system
from modules.ai_provider import ai_provider
from modules.analytics import analytics
from modules.context_builder import context_builder
from modules.search_engine import search_engine
from modules.user_profiles import user_profiles
from modules.personality_engine import personality_engine
from modules.knowledge_base import knowledge_base
from modules.mood_analyzer import mood_analyzer
from config.config import config


class AICog(commands.Cog):
    """Основные AI команды бота."""
    
    def __init__(self, bot):
        self.bot = bot

    async def _safe_should_use_web(self, question: str) -> bool:
        """Безопасная проверка авто-веб поиска (асинхронная)."""
        try:
            if hasattr(search_engine, 'should_use_web_search'):
                res = search_engine.should_use_web_search(
                    question=question,
                    mode=getattr(config, 'web_auto_search_mode', 'auto'),
                    triggers=getattr(config, 'web_auto_triggers', [])
                )
                if asyncio.iscoroutine(res):
                    return await res
                return res

            fallback_triggers = [
                'новости', 'сегодня', 'сейчас', 'актуальн', 'курс',
                'погода', 'цена', 'дата', 'событи', 'источник',
                'найди в интернете', 'поищи в интернете', 'http://', 'https://'
            ]
            q = question.lower()
            return any(t in q for t in fallback_triggers)
        except Exception:
            return False

    def _safe_gather_web_context(self, question: str, max_results: int, max_pages: int, per_page_chars: int) -> dict:
        """Безопасный сбор веб-контекста (совместим со старым SearchEngine без gather_web_context)."""
        empty_result = {
            "search_results": [],
            "scraped_pages": [],
            "web_context": "",
            "scraped_context": "",
            "memory_summary": "",
            "source_urls": []
        }
        try:
            if hasattr(search_engine, 'gather_web_context'):
                result = search_engine.gather_web_context(
                    question=question,
                    max_results=max_results,
                    max_pages=max_pages,
                    per_page_chars=per_page_chars
                )
                return result if result else empty_result
            
            # Fallback for older versions if needed (though current codebase seems to have it)
            return empty_result
        except Exception as e:
            logger.error(f"Error in _safe_gather_web_context: {e}")
            return empty_result 

    
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
        Задать вопрос AI с полным контекстом.
        Учитывается: история, личность, настроение, база знаний, веб.
        """
        # 1. Permission check
        if not permissions.has_permission(ctx.author.id, 'commands.ask'):
             await ctx.reply("❌ У вас нет прав на использование этой команды.")
             return

        # 2. Rate limit
        if config.rate_limit_enabled:
            # VIP users might have higher limits, handled in rate_limiter? 
            # Currently strict check.
            if not rate_limiter.is_allowed(ctx.author.id):
                remaining_time = rate_limiter.get_reset_time(ctx.author.id)
                await ctx.send(f"⏳ Лимит запросов. Ждите {int(remaining_time)}s.")
                return
        
        if len(question) > config.max_user_input_chars:
            await ctx.send(f"⚠️ Слишком длинно. Максимум {config.max_user_input_chars}.")
            return

        async with ctx.typing():
            try:
                start_time = time.time()
                
                # --- Context Gathering ---
                
                # A. Personality System Prompt
                active_persona = personality_engine.get_active_personality(ctx.channel.id, ctx.guild.id)
                base_system_prompt = personality_engine.get_system_prompt(ctx.channel.id, ctx.guild.id)
                
                # B. Knowledge Base (RAG)
                kb_context = knowledge_base.get_relevant_for_ai(question, ctx.guild.id) if ctx.guild else ""
                
                # C. Mood Context
                mood_ctx = mood_analyzer.get_mood_context_for_ai(ctx.author.id, ctx.channel.id)
                
                # D. User Profile
                profile_ctx = user_profiles.format_profile_for_context(ctx.author.id, ctx.author.display_name)
                
                # Combine System Prompt
                full_system_prompt = f"{base_system_prompt}\n\n"
                
                if kb_context:
                    full_system_prompt += f"{kb_context}\n\n"
                    
                if mood_ctx:
                    full_system_prompt += f"🎭 **КОНТЕКСТ НАСТРОЕНИЯ:**\n{mood_ctx}\n\n"
                    
                full_system_prompt += f"👤 **ПРОФИЛЬ ПОЛЬЗОВАТЕЛЯ:**\n{profile_ctx}\n"

                # E. Chat History & Web Search
                # We use context_builder to mix message history and potentially web results
                
                used_auto_web = False
                auto_web_sources = []
                web_block = ""
                
                # Check Auto-Web
                should_search = await self._safe_should_use_web(question)
                if should_search:
                     used_auto_web = True
                     web_data = self._safe_gather_web_context(question, 6, 2, 2500)
                     auto_web_sources = web_data['source_urls']
                     web_block = f"\n🌐 **WEB SEARCH:**\n{web_data['web_context']}\n{web_data['scraped_context']}\n"

                # Final Prompt Construction
                # context_builder builds the history block. We pass our refined system prompt to it.
                final_prompt = context_builder.build_full_context_with_query(
                    guild=ctx.guild,
                    channel_id=ctx.channel.id,
                    author_name=ctx.author.display_name,
                    system_prompt=full_system_prompt,
                    query=question
                )
                
                if web_block:
                    final_prompt += web_block
                
                # Optimize
                estimated_tokens = ai_provider.estimate_tokens(final_prompt)
                if estimated_tokens > config.max_tokens * 0.8:
                    final_prompt = ai_provider.optimize_prompt(final_prompt)
                
                # --- Generation ---
                result = await ai_provider.generate_response(
                    system_prompt=final_prompt,
                    user_message=question,
                    temperature=active_persona.temperature, # Use persona temp
                    use_cache=config.cache_enabled
                )
                
                response_time = time.time() - start_time
                
                # --- Post-processing ---
                
                # Analytics
                if config.analytics_enabled:
                    analytics.log_request(
                        user_id=ctx.author.id,
                        user_name=ctx.author.display_name,
                        model=result['model'],
                        tokens_used=result['tokens_used'],
                        response_time=response_time
                    )
                
                # Save Web Context to memory
                if used_auto_web:
                    context_builder.add_web_research(
                         ctx.channel.id, question, 
                         search_engine.build_memory_summary(question, web_data['scraped_pages']),
                         auto_web_sources
                    )
                
                # Format Response
                answer = result['content']
                footer_parts = [
                    f"🤖 {active_persona.name} ({result['model']})" if not result['from_cache'] else f"🔄 {active_persona.name} (Cache)",
                    f"⏱️ {response_time:.2f}s"
                ]
                if used_auto_web:
                    footer_parts.append("🌐 Web")
                
                footer = f"\n\n*{' | '.join(footer_parts)}*"
                
                # Emit Event
                await event_system.emit('ai.response', user_id=ctx.author.id, tokens=result['tokens_used'])

                # Send
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
                logger.error(f"Error in ask: {e}", exc_info=True)
                await ctx.send("⚠️ Ошибка. Мой мозг перегрелся. Попробуйте позже.")

    
    @commands.command(name='quick')
    async def quick(self, ctx, *, question: str):
        """Быстрый вопрос (без контекста чата), но с личностью бота."""
        if not permissions.has_permission(ctx.author.id, 'commands.quick'):
             await ctx.reply("❌ Нет прав.")
             return

        if len(question) > config.max_user_input_chars:
            await ctx.send("⚠️ Слишком длинно.")
            return

        async with ctx.typing():
            try:
                start_time = time.time()
                
                # Use current persona info + User Profile, but NO chat history
                active_persona = personality_engine.get_active_personality(ctx.channel.id, ctx.guild.id)
                profile_ctx = user_profiles.format_profile_for_context(ctx.author.id, ctx.author.display_name)
                
                system_prompt = f"{active_persona.system_prompt}\n\n{profile_ctx}\n\nОтвечай кратко и по делу."

                result = await ai_provider.generate_response(
                    system_prompt=system_prompt,
                    user_message=question,
                    temperature=active_persona.temperature,
                    use_cache=config.cache_enabled
                )
                
                response_time = time.time() - start_time
                answer = result['content']
                footer = f"\n\n*⚡ {active_persona.name} | {result['response_time']:.2f}s*"
                
                if len(answer + footer) > 2000:
                    await ctx.send(answer[:1900] + "..." + footer)
                else:
                    await ctx.send(answer + footer)
                    
            except Exception as e:
                logger.error(f"Error in quick: {e}")
                await ctx.send("⚠️ Ошибка.")
    
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

    @commands.command(name='mcp')
    async def mcp_info(self, ctx):
        """Информация о системе умного поиска (MCP-подобный протокол)."""
        embed = discord.Embed(
            title="🧠 Умный поиск (MCP Protocol)",
            description=(
                "Бот использует продвинутую систему анализа намерений для автоматического поиска в сети.\n\n"
                "✅ **Как это работает:**\n"
                "- Каждый ваш запрос анализируется быстрой AI моделью.\n"
                "- Если вам нужны свежие данные (погода, новости, курсы), бот сам использует Google/DuckDuckGo.\n"
                "- Результаты скрапятся и подаются основной модели в качестве контекста.\n\n"
                "⚙️ **Режимы (!config):**\n"
                "- `auto`: Умный выбор (по умолчанию)\n"
                "- `always`: Поиск при каждом запросе\n"
                "- `off`: Только локальные знания"
            ),
            color=discord.Color.gold()
        )
        await ctx.send(embed=embed)

    @commands.command(name='web')
    async def web_search(self, ctx, *, question: str):
        """
        Поиск в сети скрапинг и анализ.
        """
        if not permissions.has_permission(ctx.author.id, 'commands.web'):
             await ctx.reply("❌ Нет прав на веб-поиск.")
             return

        if len(question) > config.max_user_input_chars:
            await ctx.send(f"⚠️ Слишком длинно.")
            return

        async with ctx.typing():
            try:
                start_time = time.time()
                status_msg = await ctx.send(f"🔍 Ищу: *{question}*...")

                # 1. Search & Scrape
                web_data = self._safe_gather_web_context(question, 7, 3, 3500)
                search_results = web_data['search_results']
                scraped_pages = web_data['scraped_pages']
                
                if not search_results:
                    await status_msg.edit(content="❌ Ничего не найдено.")
                    return

                await status_msg.edit(content="🌐 Анализирую страницы...")

                # 2. Build Context
                active_persona = personality_engine.get_active_personality(ctx.channel.id, ctx.guild.id)
                
                web_context = web_data['web_context']
                scraped_context = web_data['scraped_context']
                memory_context = context_builder.get_web_research_context(ctx.channel.id)
                
                server_context = context_builder.build_user_context(ctx.guild)
                profile_ctx = user_profiles.format_profile_for_context(ctx.author.id, ctx.author.display_name)
                
                # 3. Construct System Prompt
                full_system_prompt = f"""{active_persona.system_prompt}

Ты — ИИ-ассистент с доступом к Интернету.
Тебе переданы: результаты выдачи, извлечённый текст с нескольких страниц и память предыдущих веб-исследований.

Требования к ответу:
1) Сначала дай краткую выжимку (3-7 пунктов).
2) Затем дай развернутый ответ по вопросу.
3) В конце добавь блок 'Источники' со ссылками.

{web_context}

{scraped_context}

{memory_context if memory_context else ''}

---
Контекст сервера:
{server_context}
---

{profile_ctx}

Пользователь: {ctx.author.display_name}
Вопрос: {question}
"""
                
                await status_msg.edit(content="🧠 Формирую ответ...")
                
                result = await ai_provider.generate_response(
                    system_prompt=full_system_prompt,
                    user_message=f"Сделай выжимку и ответ на вопрос: {question}",
                    temperature=active_persona.temperature,
                    use_cache=config.cache_enabled
                )
                
                response_time = time.time() - start_time
                answer = result['content']
                
                # Analytics
                if config.analytics_enabled:
                    analytics.log_request(
                        user_id=ctx.author.id,
                        user_name=ctx.author.display_name,
                        model=result['model'],
                        tokens_used=result['tokens_used'],
                        response_time=response_time
                    )
                
                # Update memory
                source_urls = web_data['source_urls']
                memory_summary = search_engine.build_memory_summary(question, scraped_pages)
                context_builder.add_web_research(
                    channel_id=ctx.channel.id,
                    query=question,
                    summary=memory_summary,
                    sources=source_urls
                )
                
                footer = (
                    f"\n\n*🌐 Web | {active_persona.name} | источников: {len(source_urls)} | "
                    f"{result['response_time']:.2f}s*"
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
                logger.error(f"Error in web: {e}", exc_info=True)
                await ctx.send("⚠️ Ошибка веб-поиска.")
    
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
            "`!profile set <текст>` - Установить/обновить ваш профиль (до 10,000 символов/1000 слов)\n"
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
        if len(profile_text) > config.max_profile_chars:
            await ctx.send(f"⚠️ Профиль слишком длинный! Максимум {config.max_profile_chars} символов.")
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
            p_text = profile_text
            if len(p_text) > 1024:
                p_text = p_text[:1021] + "..."
                
            embed.add_field(
                name="📝 Ваш профиль:",
                value=p_text,
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
        
        profile_text = profile_data['profile']
        if len(profile_text) > 4000:
            profile_text = profile_text[:3997] + "..."

        embed = discord.Embed(
            title=f"📋 Профиль: {ctx.author.display_name}",
            description=profile_text,
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
