"""
Модуль аналитики для отслеживания использования бота.
Собирает метрики, статистику и генерирует отчёты.
"""
import json
from pathlib import Path
from typing import Dict, Any, List
from datetime import datetime, timedelta
from collections import defaultdict
from threading import Lock


class Analytics:
    """Система аналитики и метрик бота."""
    
    def __init__(self, data_file: str = 'data/analytics.json'):
        """
        Args:
            data_file: Путь к файлу для сохранения данных
        """
        self.data_file = Path(data_file)
        self.data_file.parent.mkdir(exist_ok=True)
        
        self._lock = Lock()
        self._data = self._load_data()
    
    def _load_data(self) -> Dict[str, Any]:
        """Загрузка данных из файла."""
        if self.data_file.exists():
            try:
                with open(self.data_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception:
                pass
        
        return {
            'total_requests': 0,
            'total_tokens_used': 0,
            'requests_by_user': {},
            'requests_by_model': {},
            'errors': [],
            'daily_stats': {},
            'start_time': datetime.now().isoformat()
        }
    
    def _save_data(self) -> None:
        """Сохранение данных в файл."""
        try:
            with open(self.data_file, 'w', encoding='utf-8') as f:
                json.dump(self._data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"Ошибка сохранения аналитики: {e}")
    
    def log_request(
        self,
        user_id: int,
        user_name: str,
        model: str,
        tokens_used: int = 0,
        response_time: float = 0.0
    ) -> None:
        """
        Логирование запроса к AI.
        
        Args:
            user_id: Discord ID пользователя
            user_name: Имя пользователя
            model: Использованная модель
            tokens_used: Количество использованных токенов
            response_time: Время ответа в секундах
        """
        with self._lock:
            # Общая статистика
            self._data['total_requests'] += 1
            self._data['total_tokens_used'] += tokens_used
            
            # Статистика по пользователям
            user_key = str(user_id)
            if user_key not in self._data['requests_by_user']:
                self._data['requests_by_user'][user_key] = {
                    'name': user_name,
                    'count': 0,
                    'tokens': 0,
                    'avg_response_time': 0.0
                }
            
            user_stats = self._data['requests_by_user'][user_key]
            user_stats['count'] += 1
            user_stats['tokens'] += tokens_used
            
            # Обновление среднего времени ответа
            old_avg = user_stats['avg_response_time']
            count = user_stats['count']
            user_stats['avg_response_time'] = (old_avg * (count - 1) + response_time) / count
            
            # Статистика по моделям
            if model not in self._data['requests_by_model']:
                self._data['requests_by_model'][model] = 0
            self._data['requests_by_model'][model] += 1
            
            # Дневная статистика
            today = datetime.now().strftime('%Y-%m-%d')
            if today not in self._data['daily_stats']:
                self._data['daily_stats'][today] = {
                    'requests': 0,
                    'tokens': 0,
                    'unique_users': set()
                }
            
            daily = self._data['daily_stats'][today]
            daily['requests'] += 1
            daily['tokens'] += tokens_used
            
            # Конвертация set в list для JSON
            if isinstance(daily['unique_users'], set):
                daily['unique_users'] = list(daily['unique_users'])
            
            if user_key not in daily['unique_users']:
                daily['unique_users'].append(user_key)
            
            self._save_data()
    
    def log_error(self, error_type: str, message: str, user_id: int = None) -> None:
        """
        Логирование ошибки.
        
        Args:
            error_type: Тип ошибки
            message: Сообщение об ошибке
            user_id: ID пользователя (опционально)
        """
        with self._lock:
            error_entry = {
                'timestamp': datetime.now().isoformat(),
                'type': error_type,
                'message': message,
                'user_id': user_id
            }
            
            self._data['errors'].append(error_entry)
            
            # Ограничение размера лога ошибок
            if len(self._data['errors']) > 100:
                self._data['errors'] = self._data['errors'][-100:]
            
            self._save_data()
    
    def get_stats(self) -> Dict[str, Any]:
        """Получение общей статистики."""
        with self._lock:
            start_time = datetime.fromisoformat(self._data['start_time'])
            uptime = datetime.now() - start_time
            
            # Топ пользователей
            top_users = sorted(
                self._data['requests_by_user'].items(),
                key=lambda x: x[1]['count'],
                reverse=True
            )[:5]
            
            return {
                'uptime_days': uptime.days,
                'total_requests': self._data['total_requests'],
                'total_tokens': self._data['total_tokens_used'],
                'unique_users': len(self._data['requests_by_user']),
                'models_used': list(self._data['requests_by_model'].keys()),
                'top_users': [
                    {
                        'name': user[1]['name'],
                        'requests': user[1]['count'],
                        'tokens': user[1]['tokens']
                    }
                    for user in top_users
                ],
                'recent_errors': len(self._data['errors'])
            }
    
    def get_user_stats(self, user_id: int) -> Dict[str, Any]:
        """Получение статистики конкретного пользователя."""
        with self._lock:
            user_key = str(user_id)
            
            if user_key not in self._data['requests_by_user']:
                return {'error': 'Пользователь не найден в статистике'}
            
            return self._data['requests_by_user'][user_key]
    
    def get_daily_report(self, days: int = 7) -> str:
        """
        Генерация отчёта за последние N дней.
        
        Args:
            days: Количество дней для отчёта
        
        Returns:
            Отформатированный отчёт
        """
        with self._lock:
            report_lines = [f"📊 **Отчёт за последние {days} дней**\n"]
            
            # Получение дат
            dates = []
            for i in range(days):
                date = (datetime.now() - timedelta(days=i)).strftime('%Y-%m-%d')
                dates.append(date)
            
            total_requests = 0
            total_tokens = 0
            
            for date in reversed(dates):
                if date in self._data['daily_stats']:
                    stats = self._data['daily_stats'][date]
                    requests = stats['requests']
                    tokens = stats['tokens']
                    unique = len(stats['unique_users'])
                    
                    total_requests += requests
                    total_tokens += tokens
                    
                    report_lines.append(
                        f"**{date}**: {requests} запросов | {tokens} токенов | {unique} польз."
                    )
            
            report_lines.append(f"\n**Итого:** {total_requests} запросов, {total_tokens} токенов")
            
            return "\n".join(report_lines)


# Глобальный экземпляр
analytics = Analytics()
