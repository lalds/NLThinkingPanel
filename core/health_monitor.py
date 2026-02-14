"""
Мониторинг здоровья и производительности бота.

Отслеживает:
 - Uptime и стабильность
 - Задержки ответов (latency)
 - Использование памяти и процессора
 - Состояние подключений (Discord WebSocket, API)
 - Heartbeat и автоматические алерты
 - Метрики производительности по модулям
"""
import os
import time
import asyncio
import platform
from typing import Dict, List, Any, Optional, Callable
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from collections import deque
from threading import Lock

from core.logger import logger


@dataclass
class HealthCheck:
    """Результат проверки здоровья."""
    component: str
    status: str          # 'healthy', 'degraded', 'unhealthy'
    latency_ms: float
    message: str = ""
    timestamp: float = field(default_factory=time.time)


@dataclass
class PerformanceMetric:
    """Метрика производительности."""
    name: str
    value: float
    unit: str
    timestamp: float = field(default_factory=time.time)


class HealthMonitor:
    """Мониторинг здоровья и производительности бота."""

    def __init__(self, heartbeat_interval: int = 30, max_metrics_history: int = 1000):
        self.heartbeat_interval = heartbeat_interval
        self.max_metrics_history = max_metrics_history
        self._lock = Lock()

        # Время старта
        self.start_time = time.time()
        self.last_heartbeat = time.time()

        # Метрики производительности
        self._response_times: deque = deque(maxlen=500)
        self._api_latencies: deque = deque(maxlen=200)
        self._error_count = 0
        self._total_requests = 0
        self._successful_requests = 0

        # Состояние компонентов
        self._component_status: Dict[str, HealthCheck] = {}

        # Алерты
        self._alerts: List[Dict[str, Any]] = []
        self._alert_callbacks: List[Callable] = []

        # Порог для алертов
        self.thresholds = {
            'response_time_warn_ms': 5000,
            'response_time_critical_ms': 15000,
            'error_rate_warn': 0.1,     # 10%
            'error_rate_critical': 0.3,  # 30%
            'memory_warn_mb': 512,
            'memory_critical_mb': 1024,
        }

        # Custom checks
        self._custom_checks: Dict[str, Callable] = {}

        # Метрики по модулям
        self._module_metrics: Dict[str, Dict[str, Any]] = {}

    # ─── Heartbeat ───

    def heartbeat(self) -> None:
        """Обновление heartbeat."""
        self.last_heartbeat = time.time()

    def is_alive(self) -> bool:
        """Проверка, жив ли бот (есть heartbeat)."""
        return (time.time() - self.last_heartbeat) < self.heartbeat_interval * 3

    # ─── Метрики производительности ───

    def record_response_time(self, response_time_ms: float, command: str = "unknown") -> None:
        """Запись времени ответа."""
        with self._lock:
            self._response_times.append({
                'time_ms': response_time_ms,
                'command': command,
                'timestamp': time.time()
            })
            self._total_requests += 1
            self._successful_requests += 1

            # Проверка порогов
            if response_time_ms > self.thresholds['response_time_critical_ms']:
                self._add_alert(
                    'critical',
                    f"Критически долгий ответ: {response_time_ms:.0f}ms ({command})"
                )
            elif response_time_ms > self.thresholds['response_time_warn_ms']:
                self._add_alert(
                    'warning',
                    f"Медленный ответ: {response_time_ms:.0f}ms ({command})"
                )

    def record_api_latency(self, latency_ms: float, api_name: str = "openrouter") -> None:
        """Запись задержки API."""
        with self._lock:
            self._api_latencies.append({
                'latency_ms': latency_ms,
                'api': api_name,
                'timestamp': time.time()
            })

    def record_error(self, error_type: str = "general") -> None:
        """Запись ошибки."""
        with self._lock:
            self._error_count += 1
            self._total_requests += 1

            # Проверка error rate
            if self._total_requests > 10:
                error_rate = self._error_count / self._total_requests
                if error_rate > self.thresholds['error_rate_critical']:
                    self._add_alert('critical', f"Критический уровень ошибок: {error_rate:.1%}")
                elif error_rate > self.thresholds['error_rate_warn']:
                    self._add_alert('warning', f"Повышенный уровень ошибок: {error_rate:.1%}")

    # ─── Модульные метрики ───

    def record_module_metric(self, module: str, metric: str, value: float) -> None:
        """Запись метрики для конкретного модуля."""
        with self._lock:
            if module not in self._module_metrics:
                self._module_metrics[module] = {}
            self._module_metrics[module][metric] = {
                'value': value,
                'timestamp': time.time()
            }

    def get_module_metrics(self, module: str) -> Dict[str, Any]:
        """Получение метрик модуля."""
        return self._module_metrics.get(module, {})

    # ─── Состояние компонентов ───

    def update_component_status(
        self,
        component: str,
        status: str,
        latency_ms: float = 0,
        message: str = ""
    ) -> None:
        """Обновление состояния компонента."""
        check = HealthCheck(
            component=component,
            status=status,
            latency_ms=latency_ms,
            message=message
        )
        self._component_status[component] = check

        if status == 'unhealthy':
            self._add_alert('critical', f"Компонент '{component}' недоступен: {message}")

    def register_check(self, name: str, check_fn: Callable) -> None:
        """Регистрация кастомной проверки здоровья."""
        self._custom_checks[name] = check_fn

    async def run_all_checks(self) -> Dict[str, HealthCheck]:
        """Запуск всех проверок здоровья."""
        results = {}

        # Встроенные проверки
        results['heartbeat'] = HealthCheck(
            component='heartbeat',
            status='healthy' if self.is_alive() else 'unhealthy',
            latency_ms=0,
            message=f"Последний: {time.time() - self.last_heartbeat:.1f}s назад"
        )

        results['memory'] = self._check_memory()
        results['uptime'] = HealthCheck(
            component='uptime',
            status='healthy',
            latency_ms=0,
            message=f"Работает {self.get_uptime_str()}"
        )

        # Пользовательские проверки
        for name, check_fn in self._custom_checks.items():
            try:
                if asyncio.iscoroutinefunction(check_fn):
                    result = await check_fn()
                else:
                    result = check_fn()
                results[name] = result
            except Exception as e:
                results[name] = HealthCheck(
                    component=name,
                    status='unhealthy',
                    latency_ms=0,
                    message=f"Ошибка проверки: {e}"
                )

        # Сохранённые состояния компонентов
        for comp, check in self._component_status.items():
            if comp not in results:
                results[comp] = check

        return results

    def _check_memory(self) -> HealthCheck:
        """Проверка использования памяти."""
        try:
            import psutil
            process = psutil.Process(os.getpid())
            memory_mb = process.memory_info().rss / 1024 / 1024

            if memory_mb > self.thresholds['memory_critical_mb']:
                status = 'unhealthy'
            elif memory_mb > self.thresholds['memory_warn_mb']:
                status = 'degraded'
            else:
                status = 'healthy'

            return HealthCheck(
                component='memory',
                status=status,
                latency_ms=0,
                message=f"{memory_mb:.1f} MB"
            )
        except ImportError:
            return HealthCheck(
                component='memory',
                status='healthy',
                latency_ms=0,
                message="psutil не установлен, мониторинг недоступен"
            )

    # ─── Алерты ───

    def _add_alert(self, severity: str, message: str) -> None:
        """Добавление алерта."""
        alert = {
            'severity': severity,
            'message': message,
            'timestamp': time.time(),
            'acknowledged': False,
        }

        self._alerts.append(alert)
        if len(self._alerts) > 200:
            self._alerts = self._alerts[-200:]

        logger.warning(f"HealthMonitor ALERT [{severity}]: {message}")

    def get_alerts(self, limit: int = 20, unack_only: bool = False) -> List[Dict[str, Any]]:
        """Получение алертов."""
        alerts = self._alerts
        if unack_only:
            alerts = [a for a in alerts if not a['acknowledged']]
        return alerts[-limit:]

    def acknowledge_alerts(self) -> int:
        """Подтверждение всех алертов."""
        count = 0
        for alert in self._alerts:
            if not alert['acknowledged']:
                alert['acknowledged'] = True
                count += 1
        return count

    # ─── Общая статистика ───

    def get_uptime_seconds(self) -> float:
        """Получение uptime в секундах."""
        return time.time() - self.start_time

    def get_uptime_str(self) -> str:
        """Красивое представление uptime."""
        seconds = self.get_uptime_seconds()
        days = int(seconds // 86400)
        hours = int((seconds % 86400) // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)

        parts = []
        if days > 0:
            parts.append(f"{days}д")
        if hours > 0:
            parts.append(f"{hours}ч")
        if minutes > 0:
            parts.append(f"{minutes}м")
        parts.append(f"{secs}с")

        return " ".join(parts)

    def get_performance_summary(self) -> Dict[str, Any]:
        """Сводка по производительности."""
        with self._lock:
            # Средние значения
            if self._response_times:
                times = [r['time_ms'] for r in self._response_times]
                avg_response = sum(times) / len(times)
                p95_response = sorted(times)[int(len(times) * 0.95)] if len(times) > 20 else max(times)
                p99_response = sorted(times)[int(len(times) * 0.99)] if len(times) > 100 else max(times)
            else:
                avg_response = 0
                p95_response = 0
                p99_response = 0

            if self._api_latencies:
                api_times = [r['latency_ms'] for r in self._api_latencies]
                avg_api = sum(api_times) / len(api_times)
            else:
                avg_api = 0

            error_rate = (
                self._error_count / self._total_requests
                if self._total_requests > 0 else 0
            )

            return {
                'uptime': self.get_uptime_str(),
                'uptime_seconds': self.get_uptime_seconds(),
                'total_requests': self._total_requests,
                'successful_requests': self._successful_requests,
                'error_count': self._error_count,
                'error_rate': f"{error_rate:.2%}",
                'avg_response_ms': round(avg_response, 2),
                'p95_response_ms': round(p95_response, 2),
                'p99_response_ms': round(p99_response, 2),
                'avg_api_latency_ms': round(avg_api, 2),
                'response_samples': len(self._response_times),
                'heartbeat_alive': self.is_alive(),
                'alerts_unacknowledged': len([
                    a for a in self._alerts if not a['acknowledged']
                ]),
                'platform': platform.system(),
                'python_version': platform.python_version(),
            }

    def get_dashboard_data(self) -> Dict[str, Any]:
        """Полные данные для дашборда."""
        return {
            'performance': self.get_performance_summary(),
            'module_metrics': {
                module: {k: v['value'] for k, v in metrics.items()}
                for module, metrics in self._module_metrics.items()
            },
            'recent_alerts': self.get_alerts(limit=10),
            'component_status': {
                name: {
                    'status': check.status,
                    'latency_ms': check.latency_ms,
                    'message': check.message,
                }
                for name, check in self._component_status.items()
            },
        }


# Глобальный экземпляр
health_monitor = HealthMonitor()
