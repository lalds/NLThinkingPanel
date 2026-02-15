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
import re
import random
import audioop
from typing import Optional, Dict, List
from core.logger import logger
from modules.voice_engine import voice_engine
from modules.ai_provider import ai_provider
from modules.personality_engine import personality_engine
from modules.context_builder import context_builder
from modules.web_panel import web_panel
from modules.search_engine import search_engine
from modules.user_profiles import user_profiles
from modules.knowledge_base import knowledge_base
from modules.mood_analyzer import mood_analyzer
from config.config import config

class UserAudioBuffer:
    """Буфер аудио для конкретного пользователя с определением тишины."""
    def __init__(self, user, callback, loop):
        self.user = user
        self.callback = callback
        self.loop = loop
        self.buffer = bytearray()
        self.last_data_time = time.time() # Время последнего любого пакета
        self.last_speech_time = 0 # Время последнего ГРОМКОГО звука
        self.speech_detected = False # Была ли речь в текущем буфере
        self.processing = False
        self.silence_threshold = 1.2 # Секунд тишины после речи
        self._check_task = self.loop.create_task(self._silence_checker())

    def add_audio(self, data):
        if not data: return
        
        rms = audioop.rms(data, 2)
        now = time.time()
        self.last_data_time = now
        
        if rms > 350: # Подняли порог, чтобы игнорировать шорохи и тихий фон
            if not self.speech_detected:
                logger.debug(f"🎙️ [VAD] Голос: {self.user.display_name} (RMS: {rms})")
            self.speech_detected = True
            self.last_speech_time = now
        
        self.buffer.extend(data)

    async def _silence_checker(self):
        while True:
            try:
                await asyncio.sleep(0.3)
                now = time.time()
                
                if not self.buffer:
                    continue
                
                # 1. Защита от "бесконечной речи" (шума)
                # Если накопилось больше 30 секунд и это не просто тишина
                if self.speech_detected and len(self.buffer) > 48000 * 2 * 30:
                     logger.info(f"⚡ [VAD] Принудительная обработка (лимит 30с) для {self.user.display_name}")
                     self.last_speech_time = now - 20.0 # Имитируем тишину
                
                # 2. Если речь НЕ обнаружена и данных много (>5 сек) - чистим шум
                if not self.speech_detected and len(self.buffer) > 192000 * 5:
                    self.buffer.clear()
                    continue

                # 3. Обработка фразы по тишине
                if self.speech_detected and not self.processing:
                    silence_duration = now - self.last_speech_time
                    
                    if silence_duration > self.silence_threshold:
                        logger.info(f"⌛ [VAD] Обработка фразы {self.user.display_name}...")
                        audio_to_process = bytes(self.buffer)
                        self.buffer.clear()
                        self.speech_detected = False 
                        self.processing = True
                        
                        self.loop.create_task(self._run_callback(audio_to_process))
                
                # 4. Аварийный сброс (если вдруг застряли)
                if self.processing and now - self.last_data_time > 40.0:
                    logger.warning(f"⚠️ Аварийный сброс processing для {self.user.display_name}")
                    self.processing = False
                    
            except Exception as e:
                logger.error(f"Ошибка в _silence_checker: {e}")
                await asyncio.sleep(1)

    async def _run_callback(self, audio_data):
        try:
            await self.callback(self.user, audio_data)
        except Exception as e:
            logger.error(f"Ошибка в STT callback: {e}")
        finally:
            self.processing = False

    def stop(self):
        self._check_task.cancel()

class AISink(voice_recv.AudioSink):
    """Sink для сбора аудио от всех пользователей раздельно."""
    def __init__(self, callback, loop):
        self.callback = callback
        self.loop = loop
        self.user_buffers = {}
        self.last_packet_time = time.time()

    def wants_opus(self):
        return False

    def write(self, user, data):
        if user is None: return
        self.last_packet_time = time.time()
            
        if user.id not in self.user_buffers:
            logger.info(f"🆕 [SINK] Слушаем: {user.display_name}")
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
        
        # Состояния для Serum (секретка)
        self._pending_serum = {} # user_id -> {'ts': float}
        self._last_addressed = {} # guild_id -> {'user_id': int, 'ts': float}
        self._marathon_tasks = {} # guild_id -> asyncio.Task
        self._thinking_loops = {} # guild_id -> asyncio.Task
        
        # Запуск фоновых задач
        self.bot.loop.create_task(self._cleanup_loop())
        self.bot.loop.create_task(self._voice_health_check())

    def _get_lock(self, guild_id):
        if guild_id not in self._locks:
            self._locks[guild_id] = asyncio.Lock()
        return self._locks[guild_id]

    def _extract_number(self, text: str) -> Optional[int]:
        """Пытается извлечь число из текста (цифрами или словами)."""
        # 1. Поиск цифр
        digits = re.findall(r'\d+', text)
        if digits:
            return int(digits[0])
            
        # 2. Поиск слов (упрощенный маппинг)
        nums_map = {
            'ноль': 0, 'один': 1, 'два': 2, 'три': 3, 'четыре': 4, 'пять': 5,
            'шесть': 6, 'семь': 7, 'восемь': 8, 'девять': 9, 'десять': 10,
            'одиннадцать': 11, 'двенадцать': 12, 'тринадцать': 13, 'четырнадцать': 14,
            'пятнадцать': 15, 'шестнадцать': 16, 'семнадцатый': 17, 'восемнадцатый': 18,
            'девятнадцать': 19, 'двадцать': 20, 'тридцать': 30, 'сорок': 40,
            'пятьдесят': 50, 'шестьдесят': 60, 'семьдесят': 70, 'восемьдесят': 80,
            'девяносто': 90
        }
        
        words = text.lower().split()
        total = 0
        found = False
        for w in words:
            if w in nums_map:
                total += nums_map[w]
                found = True
        
        return total if found else None

    async def _cleanup_loop(self):
        """Фоновая задача для очистки старых данных и проверки Sinks."""
        while not self.bot.is_closed():
            await asyncio.sleep(300) # Раз в 5 минут
            try:
                await voice_engine.cleanup()
                now = time.time()
                
                # 1. Очистка старой истории
                for gid in list(self._voice_history.keys()):
                    self._voice_history[gid] = [
                        m for m in self._voice_history[gid] 
                        if now - m['time'] < 3600
                    ]
                
                # 2. Проверка "живости" прослушивания (логирование простоя)
                for gid, sink in list(self._active_listeners.items()):
                    for uid, buffer in list(sink.user_buffers.items()):
                        if now - buffer.last_data_time > 600: # 10 минут тишины
                             logger.debug(f"ℹ️ Узел {buffer.user.display_name} в режиме ожидания.")
                             
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
            greeting = persona.greeting
            
            # Проверка особого пользователя
            reymax_info = self._check_special_user_presence(ctx.guild)
            if reymax_info:
                greeting = f"{greeting} {reymax_info}"

            if persona.name.lower() not in self.wake_words:
                self.wake_words.append(persona.name.lower())
            
            greeting_path = await voice_engine.text_to_speech(greeting)
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
        if guild.id in self._marathon_tasks:
            task = self._marathon_tasks.pop(guild.id)
            task.cancel()
            
        await self._stop_thinking_loop(guild.id)

        if guild.id in self._voice_clients:
            vc = self._voice_clients.pop(guild.id)
            if guild.id in self._active_listeners:
                try:
                    sink = self._active_listeners.pop(guild.id)
                    vc.stop_listening()
                    sink.cleanup()
                except: pass
            
            try:
                await vc.disconnect()
            except: pass
            
            self._voice_history.pop(guild.id, None)

    async def _process_voice_request(self, user, audio_data):
        """Обработка распознанного голоса пользователя."""
        audio_path = None
        answer = None
        
        # 1. STT (Вне лока, чтобы не блокировать других)
        try:
            text = await asyncio.wait_for(voice_engine.speech_to_text(audio_data), timeout=15.0)
        except asyncio.TimeoutError:
            logger.warning(f"⌛ Таймаут STT для {user.display_name}")
            return
        
        if not text:
            return
            
        # Фильтруем мусор, но разрешаем цифры (для Serum) и короткие ответы в диалоге
        is_num = any(char.isdigit() for char in text)
        is_pending = user.id in self._pending_serum
        
        if len(text.strip()) < 3 and not (is_num or is_pending):
            return

        logger.info(f"🎤 [VOICE] {user.display_name}: {text}")
        
        # Сохраняем в историю
        if user.guild.id not in self._voice_history:
            self._voice_history[user.guild.id] = []
        self._voice_history[user.guild.id].append({
            'user': user.display_name, 'text': text, 'time': time.time()
        })
        if len(self._voice_history[user.guild.id]) > 20:
             self._voice_history[user.guild.id] = self._voice_history[user.guild.id][-20:]

        # --- СЕКРЕТКА: СЕРУМ ---
        if user.id in self._pending_serum:
            state = self._pending_serum[user.id]
            if time.time() - state['ts'] < 60:
                num = self._extract_number(text)
                if num:
                    del self._pending_serum[user.id]
                    # Пробуем разные варианты регистра (Win case-insensitive, но на всякий случай)
                    paths_to_try = [
                        os.path.abspath(os.path.join("farts", f"Пук{num}.m4a")),
                        os.path.abspath(os.path.join("farts", f"пук{num}.m4a"))
                    ]
                    
                    found_path = None
                    for p in paths_to_try:
                        if os.path.exists(p):
                            found_path = p
                            break
                    
                    if found_path:
                        logger.info(f"💨 [SERUM] Воспроизведение звука {num} для {user.display_name}")
                        self._play_audio(user.guild.id, found_path)
                        return
                    else:
                        logger.warning(f"💨 [SERUM] Число {num} получено, но файл farts/пук{num}.m4a не найден")
            else:
                del self._pending_serum[user.id]

        # 2. ПРОВЕРКА ПРОЩАНИЯ (Авто-выход)
        farewell_keywords = ["пока", "прощай", "уходи", "отключайся", "отключись", "выйди", "до свидания", "отвал"]
        if any(word in text.lower() for word in farewell_keywords):
            logger.info(f"👋 Обнаружено прощание от {user.display_name}. Ухожу...")
            
            bye_path = await voice_engine.text_to_speech("Хорошо, отдыхай. Если понадоблюсь — зови!")
            if bye_path:
                self._play_audio(user.guild.id, bye_path)
                await asyncio.sleep(2.5) # Даем договорить
            
            await self._stop_and_disconnect(user.guild)
            return

        # 2. Проверка Wake Word или "окна разговора"
        is_addressed = any(w in text.lower() for w in self.wake_words)
        
        is_in_conversation = False
        if user.guild.id in self._last_addressed:
            state = self._last_addressed[user.guild.id]
            if state['user_id'] == user.id and time.time() - state['ts'] < 15:
                is_in_conversation = True

        if not is_addressed and not is_in_conversation:
            # Даже если не обратились по имени, проверяем стоп-фразы для марафона
            if "я не хочу марафон" in text.lower() or "останови марафон" in text.lower():
                if user.guild.id in self._marathon_tasks:
                    logger.info(f"🛑 [MARATHON] Остановка по просьбе {user.display_name}")
                    self._marathon_tasks[user.guild.id].cancel()
                    reply_path = await voice_engine.text_to_speech("Хорошо, останавливаю марафон.")
                    if reply_path: self._play_audio(user.guild.id, reply_path)
            return

        # Активация прошла успешно
        logger.info(f"🎯 [VOICE] Активация для {user.display_name} (Wake Word: {is_addressed}, Окно: {is_in_conversation})")

        # 2.5a Обработка "Марафона"
        if "марафон" in text.lower():
            if user.guild.id in self._marathon_tasks:
                 reply_path = await voice_engine.text_to_speech("Марафон уже запущен.")
                 if reply_path: self._play_audio(user.guild.id, reply_path)
                 return
            
            logger.info(f"🏃 [MARATHON] Старт марафона на сервере {user.guild.name}")
            task = self.bot.loop.create_task(self._run_marathon(user.guild.id))
            self._marathon_tasks[user.guild.id] = task
            return

        # 2.6 Проверка Serum
        text_lower = text.lower()
        if ("serum" in text_lower or "серум" in text_lower) and any(kw in text_lower for kw in ['ссылк', 'плагин', 'скачат', 'где']):
            logger.info(f"✨ [SERUM] Активация секрета для {user.display_name}")
            reply = "Конечно. Подскажи, какая именно версия тебе нужна?"
            path = await voice_engine.text_to_speech(reply)
            if path:
                self._play_audio(user.guild.id, path)
                self._pending_serum[user.id] = {'ts': time.time()}
                return

        # Находим канал для ответа
        channel = user.guild.system_channel or user.guild.text_channels[0]
        
        # 2. ГЕНЕРАЦИЯ ОТВЕТА
        try:
            # 2.1 Запуск звука "думанья" (Тут нужен лок на VoiceClient)
            lock = self._get_lock(user.guild.id)
            async with lock:
                await self._start_thinking_loop(user.guild.id)
            
            # Подготовка промпта
            active_persona = personality_engine.get_active_personality(channel.id, user.guild.id)
            base_system_prompt = personality_engine.get_system_prompt(channel.id, user.guild.id)
            
            # --- СБОР РАСШИРЕННОГО КОНТЕКСТА ---
            # 1. База знаний (RAG)
            kb_context = knowledge_base.get_relevant_for_ai(text, user.guild.id)
            
            # 2. Настроение и профиль
            mood_ctx = mood_analyzer.get_mood_context_for_ai(user.id, channel.id)
            profile_ctx = user_profiles.format_profile_for_context(user.id, user.display_name)
            
            # 3. Веб-поиск (MCP-подобный протокол для голоса)
            web_block = ""
            used_web = False
            should_search = await search_engine.should_use_web_search(text)
            
            if should_search:
                logger.info(f"🌐 [VOICE] Активация веб-поиска для {user.display_name}")
                web_data = search_engine.gather_web_context(text, 5, 2, 2000)
                web_block = f"\n🌐 **WEB SEARCH RESULTS:**\n{web_data['web_context']}\n{web_data['scraped_context']}\n"
                used_web = True
                
                # Сохраняем в память канала
                context_builder.add_web_research(
                    channel.id, text, 
                    search_engine.build_memory_summary(text, web_data['scraped_pages']),
                    web_data['source_urls']
                )

            # Собираем системный промпт
            full_system_prompt = f"{base_system_prompt}\n\n"
            if kb_context:
                full_system_prompt += f"{kb_context}\n\n"
            if mood_ctx:
                full_system_prompt += f"🎭 **КОНТЕКСТ НАСТРОЕНИЯ:**\n{mood_ctx}\n\n"
            
            full_system_prompt += f"👤 **ПРОФИЛЬ ПОЛЬЗОВАТЕЛЯ:**\n{profile_ctx}\n"

            # 4. Финальная сборка через context_builder
            context_prompt = context_builder.build_full_context_with_query(
                guild=user.guild,
                channel_id=channel.id,
                author_name=user.display_name,
                system_prompt=full_system_prompt,
                query=text
            )
            
            if web_block:
                context_prompt += f"\n{web_block}\n"
                context_prompt += "\nИНСТРУКЦИЯ: Используй предоставленные результаты веб-поиска для ответа на вопрос. Если там есть погода или новости — озвучь их."
            
            # Финальные инструкции всегда в конце
            context_prompt += "\n\nИНСТРУКЦИЯ: Ты общаешься в ГОЛОСОВОМ чате. Отвечай максимально КРАТКО (1-3 предложения), емко и по существу. Ссылки и URL не читай."
            
            # 2.2 Запрос к AI с таймаутом
            logger.info(f"🤖 [AI] Генерация ответа для {user.display_name} (Web: {used_web})...")
            result = await asyncio.wait_for(
                ai_provider.generate_response(
                    system_prompt=context_prompt,
                    user_message=text,
                    temperature=active_persona.temperature
                ),
                timeout=25.0
            )
            answer = result['content']
            
            # 2.3 Генерация TTS
            audio_path = await voice_engine.text_to_speech(answer)
            
            # 3. ВОСПРОИЗВЕДЕНИЕ (СНОВА ЛОК)
            async with lock:
                await self._stop_thinking_loop(user.guild.id)

                if audio_path:
                    self._play_audio(user.guild.id, audio_path)
                    
                    # Отправляем в веб-панель
                    await web_panel.broadcast({
                        'type': 'state', 'state': 'talking',
                        'speaker': active_persona.name, 'text': answer
                    })
                    
            # Текстовый дубль
            embed = discord.Embed(description=f"🎤 **{user.display_name}**: {text}\n\n🤖 {answer}", color=discord.Color.blue())
            await channel.send(embed=embed, delete_after=60)

        except asyncio.TimeoutError:
            logger.error(f"⌛ Таймаут генерации AI для {user.display_name}")
            async with lock: await self._stop_thinking_loop(user.guild.id)
        except Exception as e:
            logger.error(f"❌ Ошибка voice_request: {e}", exc_info=True)
            async with lock: await self._stop_thinking_loop(user.guild.id)
        finally:
            logger.info(f"👂 [VOICE] Обработка завершена для {user.display_name}")
            
            # Обновляем окно разговора ПОСЛЕ ответа (даем 15 сек на продолжение)
            self._last_addressed[user.guild.id] = {'user_id': user.id, 'ts': time.time()}
            
            if user.guild.id in self._voice_clients:
                asyncio.create_task(self._delayed_relisten(user.guild.id))

        # Сброс анимации в фоне
        if audio_path and answer:
            asyncio.create_task(self._reset_idle_state(len(answer) / 10))

    async def _delayed_relisten(self, guild_id: int):
        """Отложенный перезапуск слушателя после окончания речи бота."""
        try:
            # Ждем, пока бот закончит говорить (максимум 30 секунд)
            for _ in range(60):  # 60 * 0.5 = 30 секунд
                if guild_id not in self._voice_clients:
                    return
                
                vc = self._voice_clients[guild_id]
                if not vc.is_playing():
                    break
                
                await asyncio.sleep(0.5)
            
            # Теперь делаем перезапуск
            if guild_id in self._voice_clients and guild_id in self._active_listeners:
                vc = self._voice_clients[guild_id]
                sink = self._active_listeners[guild_id]
                
                logger.info(f"🔄 [SYNC] Перезапуск слушателя для {vc.guild.name}")
                
                try:
                    vc.stop_listening()
                    
                    # Очистка буферов
                    for buf in sink.user_buffers.values():
                        buf.buffer.clear()
                        buf.speech_detected = False
                        buf.processing = False
                except Exception as e:
                    logger.warning(f"Ошибка при остановке: {e}")
                
                await asyncio.sleep(0.3)
                vc.listen(sink)
                logger.info(f"✅ [SYNC] Слушатель перезапущен, бот готов")
                
        except Exception as e:
            logger.error(f"❌ Ошибка в _delayed_relisten: {e}")

    async def _reset_idle_state(self, delay: float):
        """Фоновый сброс состояния анимации."""
        try:
            await asyncio.sleep(delay)
            await web_panel.broadcast({'type': 'state', 'state': 'idle'})
        except Exception as e:
            logger.error(f"Ошибка сброса idle state: {e}")

    async def _run_marathon(self, guild_id: int):
        """Циклический перебор всех звуков из farts."""
        try:
            fart_dir = "farts"
            if not os.path.exists(fart_dir):
                return
                
            fart_files = [f for f in os.listdir(fart_dir) if f.endswith(('.m4a', '.mp3', '.wav'))]
            
            def get_num(name):
                m = re.search(r'\d+', name)
                return int(m.group()) if m else 999
                
            fart_files.sort(key=get_num)
            
            # Стартовое сообщение
            start_path = await voice_engine.text_to_speech(f"Начинаю марафон из {len(fart_files)} звуков. Держитесь.")
            if start_path:
                self._play_audio(guild_id, start_path)
                while guild_id in self._voice_clients and self._voice_clients[guild_id].is_playing():
                    await asyncio.sleep(0.5)

            for f in fart_files:
                abs_path = os.path.abspath(os.path.join(fart_dir, f))
                num = get_num(f)
                
                # Анонс
                ann_path = await voice_engine.text_to_speech(f"Звук номер {num}")
                if ann_path:
                    self._play_audio(guild_id, ann_path)
                    while guild_id in self._voice_clients and self._voice_clients[guild_id].is_playing():
                        await asyncio.sleep(0.2)
                
                await asyncio.sleep(0.3)
                
                # Проигрывание
                self._play_audio(guild_id, abs_path)
                while guild_id in self._voice_clients and self._voice_clients[guild_id].is_playing():
                    await asyncio.sleep(0.2)
                
                await asyncio.sleep(1.0) # Пауза между
                
            finish_path = await voice_engine.text_to_speech("Марафон окончен. Все выжили?")
            if finish_path: self._play_audio(guild_id, finish_path)
            
        except asyncio.CancelledError:
            logger.info(f"Марафон в {guild_id} отменен.")
        except Exception as e:
            logger.error(f"Ошибка марафона: {e}")
        finally:
            if guild_id in self._marathon_tasks:
                del self._marathon_tasks[guild_id]

    async def _start_thinking_loop(self, guild_id: int):
        """Запускает циклическое проигрывание случайного звука ожидания из SoundsAsset."""
        await self._stop_thinking_loop(guild_id)
        
        sound_dir = "SoundsAsset"
        if not os.path.exists(sound_dir):
            logger.warning(f"Директория {sound_dir} не найдена")
            return

        sounds = [f for f in os.listdir(sound_dir) if f.endswith(('.mp3', '.wav', '.m4a', '.flac'))]
        if not sounds:
            logger.warning(f"В {sound_dir} не найдено аудиофайлов")
            return

        selected_sound = random.choice(sounds)
        sound_path = os.path.abspath(os.path.join(sound_dir, selected_sound))
        
        logger.info(f"🤔 [THINKING] Проигрывание фона: {selected_sound}")

        async def loop_fn():
            try:
                while True:
                    if guild_id not in self._voice_clients:
                        break
                    
                    vc = self._voice_clients[guild_id]
                    if not vc.is_playing():
                        vc.play(discord.FFmpegPCMAudio(sound_path))
                    
                    await asyncio.sleep(0.5)
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logger.error(f"Ошибка в цикле звука: {e}")

        self._thinking_loops[guild_id] = self.bot.loop.create_task(loop_fn())

    async def _stop_thinking_loop(self, guild_id: int):
        """Останавливает цикл звука ожидания."""
        if guild_id in self._thinking_loops:
            task = self._thinking_loops[guild_id]
            task.cancel()
            del self._thinking_loops[guild_id]
            # Ждем завершения с коротким таймаутом
            try:
                await asyncio.wait_for(task, timeout=1.0)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass
            
        # Также останавливаем текущее воспроизведение, если это был звук ожидания
        if guild_id in self._voice_clients:
            vc = self._voice_clients[guild_id]
            if vc.is_playing():
                vc.stop()

    async def _cleanup_loop(self):
        """Очистка старых данных диалогов и памяти каждые 15 минут."""
        while True:
            await asyncio.sleep(900)
            try:
                now = time.time()
                # Удаляем историю голоса старше 1 часа
                for guild_id in list(self._voice_history.keys()):
                    self._voice_history[guild_id] = [
                        m for m in self._voice_history[guild_id]
                        if now - m['time'] < 3600
                    ]
                
                # Чистим зависшие запросы Serum
                for user_id in list(self._pending_serum.keys()):
                    if now - self._pending_serum[user_id]['ts'] > 300:
                        del self._pending_serum[user_id]
                
                logger.debug("🧼 [VOICE] Плановая очистка ресурсов завершена")
            except Exception as e:
                logger.error(f"Ошибка в _cleanup_loop: {e}")

    async def _voice_health_check(self):
        """Проверка 'замирания' голосовых потоков (Watchdog)."""
        while True:
            await asyncio.sleep(60) 
            try:
                now = time.time()
                for guild_id in list(self._voice_clients.keys()):
                    vc = self._voice_clients.get(guild_id)
                    sink = self._active_listeners.get(guild_id)
                    
                    if not vc or not vc.is_connected() or not sink:
                        continue
                    
                    # Если бот в канале, но 5 минут нет активности (пакетов) - ребут слушателя
                    if now - sink.last_packet_time > 300:
                        # Если бот сам не говорит в этот момент
                        if not vc.is_playing():
                            logger.info(f"🔄 [WATCHDOG] Обнаружено замирание потока в {vc.guild.name}. Перезапуск...")
                            await self._delayed_relisten(guild_id)
            except Exception as e:
                logger.error(f"Ошибка в _voice_health_check: {e}")

    def _is_reymax(self, member):
        """Проверка, является ли пользователь Reymax-ом."""
        return member.name == "reymax_2008" or member.display_name == "некомфортно вырезал диван"

    def _get_reymax_status_text(self, member):
        """Получение текста статуса для Reymax."""
        status_map = {
            discord.Status.online: "теперь в сети",
            discord.Status.idle: "теперь отошел от компьютера",
            discord.Status.dnd: "теперь в режиме 'не беспокоить'",
            discord.Status.offline: "теперь не в сети (оффлайн)"
        }
        return status_map.get(member.status, "изменил свой статус")

    def _check_special_user_presence(self, guild):
        """Первичная проверка Reymax-а при входе бота."""
        member = discord.utils.find(self._is_reymax, guild.members)
        if member and member.status != discord.Status.offline:
            status_map = {
                discord.Status.online: "в сети",
                discord.Status.idle: "отошел от компьютера",
                discord.Status.dnd: "в режиме 'не беспокоить'"
            }
            return f"Кстати, ваш любимчик {member.display_name} сейчас {status_map.get(member.status, 'в сети')}."
        return None

    @commands.Cog.listener()
    async def on_presence_update(self, before, after):
        """Трансляция изменения статуса Reymax в голосовой канал."""
        if not self._is_reymax(after):
            return
            
        if before.status == after.status:
            return
            
        guild = after.guild
        if guild.id in self._voice_clients:
            vc = self._voice_clients[guild.id]
            if vc.is_connected():
                status_text = self._get_reymax_status_text(after)
                text = f"Внимание всем участникам! {after.display_name} {status_text}."
                audio_path = await voice_engine.text_to_speech(text)
                if audio_path:
                    self._play_audio(guild.id, audio_path)

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

        # Логика для Reymax (вход в канал)
        if self._is_reymax(member) and not before.channel and after.channel:
             if member.guild.id in self._voice_clients:
                 vc = self._voice_clients[member.guild.id]
                 if vc.channel.id == after.channel.id:
                     text = f"Внимание! В канал зашел {member.display_name}. Всем сохранять спокойствие!"
                     audio_path = await voice_engine.text_to_speech(text)
                     if audio_path:
                         self._play_audio(member.guild.id, audio_path)

async def setup(bot):
    """Регистрация Cog."""
    await bot.add_cog(VoiceCog(bot))
