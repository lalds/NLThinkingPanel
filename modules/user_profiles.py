"""
Модуль для управления персональными профилями пользователей.
Позволяет пользователям сохранять информацию о себе для персонализации ответов.
"""
import json
from pathlib import Path
from typing import Dict, Optional, Any
from datetime import datetime
from core.logger import logger

class UserProfileManager:
    """Менеджер профилей пользователей."""
    
    def __init__(self, data_file: str = 'data/user_profiles.json'):
        self.data_file = Path(data_file)
        self.data_file.parent.mkdir(parents=True, exist_ok=True)
        self._profiles = self._load_profiles()
    
    def _load_profiles(self) -> Dict[int, Dict[str, Any]]:
        """Загрузка профилей из файла."""
        if self.data_file.exists():
            try:
                with open(self.data_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    # Конвертируем ключи обратно в int
                    return {int(k): v for k, v in data.items()}
            except Exception as e:
                logger.error(f"Ошибка при загрузке профилей: {e}")
                return {}
        return {}
    
    def _save_profiles(self):
        """Сохранение профилей в файл."""
        try:
            with open(self.data_file, 'w', encoding='utf-8') as f:
                json.dump(self._profiles, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Ошибка при сохранении профилей: {e}")
    
    def set_profile(self, user_id: int, user_name: str, profile_text: str) -> bool:
        """
        Устанавливает или обновляет профиль пользователя.
        
        Args:
            user_id: Discord ID пользователя
            user_name: Имя пользователя
            profile_text: Текст профиля (информация о пользователе)
            
        Returns:
            True если успешно сохранено
        """
        try:
            self._profiles[user_id] = {
                'name': user_name,
                'profile': profile_text,
                'updated_at': datetime.now().isoformat(),
                'created_at': self._profiles.get(user_id, {}).get('created_at', datetime.now().isoformat())
            }
            self._save_profiles()
            logger.info(f"Профиль обновлен для пользователя {user_name} (ID: {user_id})")
            return True
        except Exception as e:
            logger.error(f"Ошибка при установке профиля: {e}")
            return False
    
    def get_profile(self, user_id: int) -> Optional[str]:
        """
        Получает профиль пользователя.
        
        Args:
            user_id: Discord ID пользователя
            
        Returns:
            Текст профиля или None если профиль не найден
        """
        profile_data = self._profiles.get(user_id)
        if profile_data:
            return profile_data.get('profile')
        return None
    
    def get_full_profile_data(self, user_id: int) -> Optional[Dict[str, Any]]:
        """Получает полные данные профиля включая метаданные."""
        return self._profiles.get(user_id)
    
    def delete_profile(self, user_id: int) -> bool:
        """
        Удаляет профиль пользователя.
        
        Args:
            user_id: Discord ID пользователя
            
        Returns:
            True если профиль был удален
        """
        if user_id in self._profiles:
            del self._profiles[user_id]
            self._save_profiles()
            logger.info(f"Профиль удален для пользователя ID: {user_id}")
            return True
        return False
    
    def has_profile(self, user_id: int) -> bool:
        """Проверяет, есть ли у пользователя профиль."""
        return user_id in self._profiles
    
    def get_all_profiles(self) -> Dict[int, Dict[str, Any]]:
        """Возвращает все профили (для админов)."""
        return self._profiles.copy()
    
    def get_stats(self) -> Dict[str, Any]:
        """Возвращает статистику по профилям."""
        return {
            'total_profiles': len(self._profiles),
            'recent_updates': sorted(
                [(uid, data['name'], data['updated_at']) 
                 for uid, data in self._profiles.items()],
                key=lambda x: x[2],
                reverse=True
            )[:5]
        }
    
    def format_profile_for_context(self, user_id: int, user_name: str) -> str:
        """
        Форматирует профиль пользователя для добавления в контекст AI.
        
        Args:
            user_id: Discord ID пользователя
            user_name: Имя пользователя
            
        Returns:
            Отформатированный текст профиля для промпта
        """
        profile = self.get_profile(user_id)
        if profile:
            return f"""
📋 **ПРОФИЛЬ ПОЛЬЗОВАТЕЛЯ {user_name}:**
{profile}

Используй эту информацию для персонализации ответов. Обращайся к пользователю с учетом его предпочтений и интересов.
"""
        return ""

# Глобальный экземпляр
user_profiles = UserProfileManager()
