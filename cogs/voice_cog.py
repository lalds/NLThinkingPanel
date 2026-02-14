"""
Модуль для голосового взаимодействия (TTS + STT).
Поддерживает многопользовательское распознавание речи.
"""
import discord
from discord.ext import commands
import discord.ext.voice_recv as voice_recv
import asyncio
import os
import time
from core.logger import logger
from modules.voice_engine import voice_engine
from modules.ai_provider import ai_provider
from modules.personality_engine import personality_engine
from modules.context_builder import context_builder
from modules.web_panel import web_panel
from config.config import config

class UserAudioBuffer:
    """Буфер аудио для конкретного пользователя с определением тишины."""
    def __init__(self, user, callback, loop):
        self.user = user
        self.callback = callback
        self.loop = loop
        self.buffer = bytearray()
        self.last_audio_time = time.time()
        self.processing = False
        self.silence_threshold = 1.5 # секунды тишины перед обработкой
        self._check_task = self.loop.create_task(self._silence_checker())

    def add_audio(self, data):
        if self.processing:
            return
        self.buffer.extend(data)
        self.last_audio_time = time.time()

    async def _silence_checker(self):
        while True:
            await asyncio.sleep(0.5)
            if self.processing or not self.buffer:
                continue
            
            if time.time() - self.last_audio_time > self.silence_threshold:
                # Пользователь замолчал
                audio_to_process = bytes(self.buffer)
                self.buffer.clear()
                self.processing = True
                await self.callback(self.user, audio_to_process)
                self.processing = False

    def stop(self):
        self._check_task.cancel()

class AISink(voice_recv.AudioSink):
    """Sink для сбора аудио от всех пользователей раздельно."""
    def __init__(self, callback, loop):
        self.callback = callback
        self.loop = loop
        self.user_buffers = {} # user_id -> UserAudioBuffer

    def wants_opus(self):
        return False # Нам нужен PCM s16le

    def write(self, user, data):
        if user is None:
            return
            
        if user.id not in self.user_buffers:
            logger.info(f"Начало записи голоса для пользователя {user.display_name}")
            self.user_buffers[user.id] = UserAudioBuffer(user, self.callback, self.loop)
        
        self.user_buffers[user.id].add_audio(data.pcm)

    def cleanup(self):
        for buffer in self.user_buffers.values():
            buffer.stop()
        self.user_buffers.clear()

class VoiceCog(commands.Cog):
    """Команды для работы с голосом (STT + TTS)."""
    
    def __init__(self, bot):
        self.bot = bot
        self._voice_clients = {}  # guild_id -> VoiceRecvClient
        self._active_listeners = {} # guild_id -> AISink
        self._voice_history = {} # guild_id -> list of {'user': str, 'text': str, 'time': float}
        self._locks = {} # guild_id -> asyncio.Lock (блокировка по серверам)
        
        # Ключевые слова для активации (можно расширить)
        self.wake_words = ['бот', 'bot', 'панель', 'panel', 'компьютер', 'computer']
        
        # Запуск фоновой очистки
        self.bot.loop.create_task(self._cleanup_loop())

    def _get_lock(self, guild_id):
        if guild_id not in self._locks:
            self._locks[guild_id] = asyncio.Lock()
        return self._locks[guild_id]

    async def _cleanup_loop(self):
        """Периодическая очистка временных файлов."""
        while not self.bot.is_closed():
            await asyncio.sleep(3600)  # Раз в час
            try:
                await voice_engine.cleanup()
                
                # Очистка старой истории
                current_time = time.time()
                for guild_id in list(self._voice_history.keys()):
                    self._voice_history[guild_id] = [
                        msg for msg in self._voice_history[guild_id] 
                        if current_time - msg['time'] < 300
                    ]
            except Exception as e:
                logger.error(f"Ошибка в _cleanup_loop VoiceCog: {e}")

    @commands.command(name='vjoin', aliases=['join'])
    async def vjoin(self, ctx):
        """Присоединиться к голосовому каналу и начать слушать."""
        if not ctx.author.voice:
            await ctx.reply("❌ Вы должны находиться в голосовом канале!")
            return

        channel = ctx.author.voice.channel
        
        try:
            if ctx.guild.id in self._voice_clients:
                vc = self._voice_clients[ctx.guild.id]
                if vc.channel.id != channel.id:
                    await vc.move_to(channel)
            else:
                vc = await channel.connect(cls=voice_recv.VoiceRecvClient)
                self._voice_clients[ctx.guild.id] = vc
            
            await ctx.send(f"✅ Слушаю в **{channel.name}**! Обратитесь ко мне по имени (Бот, Панель...), чтобы я ответил.")
            
            # Инициализация истории
            if ctx.guild.id not in self._voice_history:
                self._voice_history[ctx.guild.id] = []
            
            # Запускаем прослушивание
            if ctx.guild.id not in self._active_listeners:
                sink = AISink(self._process_voice_request, self.bot.loop)
                self._active_listeners[ctx.guild.id] = sink
                vc.listen(sink)
            
            # Приветствие
            persona = personality_engine.get_active_personality(ctx.channel.id, ctx.guild.id)
            if persona.name.lower() not in self.wake_words:
                self.wake_words.append(persona.name.lower())
            
            greeting_path = await voice_engine.text_to_speech(persona.greeting)
            if greeting_path:
                self._play_audio(ctx.guild.id, greeting_path)

        except Exception as e:
            logger.error(f"Ошибка при подключении к голосу: {e}", exc_info=True)
            await ctx.send(f"❌ Ошибка подключения: {e}")

    @commands.command(name='vleave', aliases=['leave'])
    async def vleave(self, ctx):
        """Выйти из голосового канала."""
        await self._stop_and_disconnect(ctx.guild)
        await ctx.send("👋 Ушел отдыхать. Пока!")

    async def _stop_and_disconnect(self, guild):
        """Остановка слушателей и отключение от канала."""
        if guild.id in self._voice_clients:
            vc = self._voice_clients[guild.id]
            if guild.id in self._active_listeners:
                try:
                    vc.stop_listening()
                    self._active_listeners[guild.id].cleanup()
                    del self._active_listeners[guild.id]
                except: pass
            
            await vc.disconnect()
            del self._voice_clients[guild.id]
            if guild.id in self._voice_history:
                del self._voice_history[guild.id]

    async def _process_voice_request(self, user, audio_data):
        """Обработка распознанного голоса пользователя."""
        # 1. STT
        text = await voice_engine.speech_to_text(audio_data)
        
        if not text or len(text.strip()) < 2:
            return

        logger.info(f"🎤 [VOICE] {user.display_name}: {text}")
        
        # Сохраняем в историю
        if user.guild.id not in self._voice_history:
            self._voice_history[user.guild.id] = []
            
        self._voice_history[user.guild.id].append({
            'user': user.display_name,
            'text': text,
            'time': time.time()
        })
        
        # Ограничиваем историю
        if len(self._voice_history[user.guild.id]) > 20:
             self._voice_history[user.guild.id] = self._voice_history[user.guild.id][-20:]

        # 2. Проверка Wake Word
        is_addressed = any(w in text.lower() for w in self.wake_words)
        if not is_addressed:
            return

        # Находим канал для ответа
        channel = user.guild.system_channel or user.guild.text_channels[0]
        
        lock = self._get_lock(user.guild.id)
        async with lock:
            try:
                # 3. Формируем контекст
                history_text = "\n".join([
                    f"{msg['user']}: {msg['text']}" 
                    for msg in self._voice_history[user.guild.id][-10:]
                ])
                
                active_persona = personality_engine.get_active_personality(channel.id, user.guild.id)
                system_prompt = personality_engine.get_system_prompt(channel.id, user.guild.id)
                
                context_prompt = (
                    f"{system_prompt}\n\n"
                    f"Ты участник голосового чата. Контекст последних реплик:\n"
                    f"{history_text}\n\n"
                    f"Пользователь {user.display_name} сказал: '{text}'.\n"
                    f"Ответь максимально естественно и кратко. Не повторяй приветствия."
                )
                
                # Отправляем состояние "Думает" на веб-панель
                await web_panel.broadcast({
                    'type': 'state',
                    'state': 'thinking',
                    'speaker': active_persona.name,
                    'text': '...'
                })
                
                # Запускаем в executor чтобы не блокировать loop, так как ai_provider синхронный
                def _gen():
                    return ai_provider.generate_response(
                        system_prompt=context_prompt,
                        user_message=text,
                        temperature=active_persona.temperature
                    )
                
                result = await asyncio.get_event_loop().run_in_executor(None, _gen)
                answer = result['content']
                
                # Сохраняем ответ в историю
                self._voice_history[user.guild.id].append({
                    'user': active_persona.name,
                    'text': answer,
                    'time': time.time()
                })
                
                # 4. TTS и воспроизведение
                audio_path = await voice_engine.text_to_speech(answer)
                if audio_path:
                    # Отправляем состояние "Говорит" на веб-панель
                    await web_panel.broadcast({
                        'type': 'state',
                        'state': 'talking',
                        'speaker': active_persona.name,
                        'text': answer
                    })
                    
                    self._play_audio(user.guild.id, audio_path)
                    
                    # Ожидаем конца аудио и возвращаемся в idle
                    # Примерная длительность: количество символов / 15
                    await asyncio.sleep(len(answer) / 15)
                    await web_panel.broadcast({'type': 'state', 'state': 'idle'})
                    
                # Дублируем текстом
                embed = discord.Embed(
                    description=f"🎤 **{user.display_name}**: {text}\n\n🤖 {answer}",
                    color=discord.Color.green()
                )
                embed.set_footer(text=f"Голосовой чат | {active_persona.name}")
                await channel.send(embed=embed)

            except Exception as e:
                logger.error(f"Критическая ошибка voice_processing: {e}")

    def _play_audio(self, guild_id: int, path: str):
        if guild_id in self._voice_clients:
            vc = self._voice_clients[guild_id]
            if vc.is_playing():
                vc.stop()
            try:
                vc.play(discord.FFmpegPCMAudio(path))
            except Exception as e:
                logger.error(f"Ошибка воспроизведения: {e}")

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        """Автоматический выход и очистка ресурсов."""
        if member.id == self.bot.user.id:
            # Если бота выкинули или переместили
            if not after.channel:
                 if member.guild.id in self._voice_clients:
                     logger.info(f"Бот отключен от голоса на сервере {member.guild.name}")
                     await self._stop_and_disconnect(member.guild)
            return
            
        if before.channel and not after.channel:
            vc = discord.utils.get(self.bot.voice_clients, guild=member.guild)
            if vc and vc.channel.id == before.channel.id and len(before.channel.members) == 1: 
                await asyncio.sleep(30) 
                if len(before.channel.members) == 1:
                    logger.info(f"Авто-выход (пустой канал) на сервере {member.guild.name}")
                    await self._stop_and_disconnect(member.guild)

async def setup(bot):
    """Регистрация Cog."""
    await bot.add_cog(VoiceCog(bot))
