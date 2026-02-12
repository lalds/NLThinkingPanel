"""
Основной модуль бота с командами для взаимодействия с AI.
"""
import discord
from discord.ext import commands
import time
from core.logger import logger
from core.rate_limiter import rate_limiter
from modules.ai_provider import ai_provider
from modules.analytics import analytics
from modules.context_builder import context_builder
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
                    f"⚠️ Произошла ошибка при обработке запроса.\n"
                    f"```{error_msg[:500]}```"
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
                await ctx.send(f"⚠️ Ошибка: {str(e)[:500]}")
    
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
        
        await ctx.send(embed=embed)
    
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
