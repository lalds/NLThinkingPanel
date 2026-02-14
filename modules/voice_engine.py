"""
Модуль для работы с голосом (TTS и в будущем STT).
"""
import os
import asyncio
import hashlib
import io
import wave
import time
import speech_recognition as sr
from gtts import gTTS
from pydub import AudioSegment
from core.logger import logger
from typing import Optional

class VoiceEngine:
    """Движок для обработки голоса (TTS и STT)."""
    
    def __init__(self, temp_dir: str = "data/voice_temp"):
        self.temp_dir = temp_dir
        if not os.path.exists(self.temp_dir):
            os.makedirs(self.temp_dir, exist_ok=True)
            logger.info(f"Создана директория для временных аудиофайлов: {self.temp_dir}")
        self.recognizer = sr.Recognizer()
        self.speech_speed = 1.3 # Коэффициент ускорения

    async def speech_to_text(self, audio_data: bytes) -> Optional[str]:
        """
        Преобразует аудио (PCM) в текст через Google STT.
        Оптимизировано: конвертирует в Mono для Google.
        """
        try:
            start_time = time.time()
            
            # Конвертируем PCM в WAV
            # Google STT лучше работает с Mono
            buffer = io.BytesIO()
            with wave.open(buffer, 'wb') as wf:
                wf.setnchannels(1) # Конвертируем в моно
                wf.setsampwidth(2) # 16-bit
                wf.setframerate(48000)
                
                mono_data = bytearray()
                for i in range(0, len(audio_data), 4):
                    mono_data.extend(audio_data[i:i+2])
                
                wf.writeframes(mono_data)
            
            buffer.seek(0)
            
            with sr.AudioFile(buffer) as source:
                audio = self.recognizer.record(source)
            
            def _recognize():
                try:
                    return self.recognizer.recognize_google(audio, language="ru-RU")
                except sr.UnknownValueError:
                    return ""
                except sr.RequestError as e:
                    logger.error(f"Ошибка сервиса Google STT: {e}")
                    return None

            text = await asyncio.get_event_loop().run_in_executor(None, _recognize)
            
            duration = time.time() - start_time
            if text and len(text.strip()) > 0:
                logger.info(f"✅ STT успешно ({duration:.2f}s): {text[:50]}...")
            else:
                logger.info(f"😶 STT вернул пустоту ({duration:.2f}s). Возможно, слишком тихо или неразборчиво.")
            
            return text
            
        except Exception as e:
            logger.error(f"Ошибка в VoiceEngine.speech_to_text: {e}")
            return None

    async def text_to_speech(self, text: str, lang: str = 'ru') -> Optional[str]:
        """
        Превращает текст в аудиофайл (MP3) и ускоряет его.
        """
        if not text:
            return None
            
        try:
            # Генерируем уникальное имя файла
            # Добавляем скорость в хэш, чтобы при изменении скорости кэш обновлялся
            speed_suffix = str(self.speech_speed).replace('.', '_')
            text_hash = hashlib.md5(f"{text}_{speed_suffix}".encode()).hexdigest()
            filename = os.path.abspath(os.path.join(self.temp_dir, f"tts_{text_hash}.mp3"))
            
            if os.path.exists(filename):
                return filename

            logger.info(f"Генерация TTS ({lang}, speed {self.speech_speed}x): {text[:50]}...")
            
            def _save_and_speedup():
                # 1. Генерируем стандартный TTS
                temp_file = filename + ".tmp.mp3"
                tts = gTTS(text=text, lang=lang)
                tts.save(temp_file)
                
                # 2. Ускоряем с помощью pydub
                audio = AudioSegment.from_file(temp_file)
                
                # speedup() от pydub делает ускорение без изменения тональности
                # chunk_size и crossfade помогают избежать щелчков
                faster_audio = audio.speedup(playback_speed=self.speech_speed)
                
                faster_audio.export(filename, format="mp3")
                
                # Удаляем временный файл
                if os.path.exists(temp_file):
                    os.remove(temp_file)
                
            await asyncio.get_event_loop().run_in_executor(None, _save_and_speedup)
            
            if os.path.exists(filename):
                return filename
            return None
            
        except Exception as e:
            logger.error(f"Ошибка в VoiceEngine.text_to_speech: {e}")
            return None

    async def cleanup(self):
        """Очистка папки с временными файлами."""
        try:
            count = 0
            for f in os.listdir(self.temp_dir):
                file_path = os.path.join(self.temp_dir, f)
                if os.path.isfile(file_path):
                    os.remove(file_path)
                    count += 1
            if count > 0:
                logger.info(f"Очищено {count} временных аудиофайлов.")
        except Exception as e:
            logger.error(f"Ошибка при очистке VoiceEngine: {e}")

# Глобальный экземпляр
voice_engine = VoiceEngine()
