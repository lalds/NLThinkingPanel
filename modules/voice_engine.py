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
import edge_tts
from core.logger import logger
from typing import Optional

class VoiceEngine:
    """Движок для обработки голоса (TTS и STT) на базе Edge-TTS."""
    
    def __init__(self, temp_dir: str = "data/voice_temp"):
        self.temp_dir = temp_dir
        if not os.path.exists(self.temp_dir):
            os.makedirs(self.temp_dir, exist_ok=True)
            logger.info(f"Создана директория для временных аудиофайлов: {self.temp_dir}")
        self.recognizer = sr.Recognizer()
        self.speech_speed = 1.3 # Коэффициент ускорения
        self.default_voice = "ru-RU-SvetlanaNeural"

    async def speech_to_text(self, audio_data: bytes) -> Optional[str]:
        """
        Преобразует аудио (PCM) в текст через Google STT.
        Оптимизировано: конвертирует в Mono для Google.
        """
        try:
            start_time = time.time()
            
            # Конвертируем PCM в WAV
            buffer = io.BytesIO()
            with wave.open(buffer, 'wb') as wf:
                wf.setnchannels(1) 
                wf.setsampwidth(2) 
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
            if text:
                logger.info(f"STT успешно ({duration:.2f}s): {text[:50]}...")
            
            return text
            
        except Exception as e:
            logger.error(f"Ошибка в VoiceEngine.speech_to_text: {e}")
            return None

    async def text_to_speech(self, text: str, lang: str = 'ru') -> Optional[str]:
        """
        Превращает текст в аудиофайл (MP3) через Edge-TTS.
        """
        if not text:
            return None
            
        try:
            # Превращаем коэффициент в формат edge-tts (например, 1.3 -> +30%)
            rate_val = int((self.speech_speed - 1) * 100)
            rate_str = f"{'+' if rate_val >= 0 else ''}{rate_val}%"
            
            # Генерируем уникальное имя файла
            text_hash = hashlib.md5(f"{text}_{rate_str}_{self.default_voice}".encode()).hexdigest()
            filename = os.path.abspath(os.path.join(self.temp_dir, f"tts_{text_hash}.mp3"))
            
            if os.path.exists(filename):
                return filename

            logger.info(f"Генерация Edge-TTS ({self.default_voice}, rate {rate_str}): {text[:50]}...")
            
            communicate = edge_tts.Communicate(text, self.default_voice, rate=rate_str)
            await communicate.save(filename)
            
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
