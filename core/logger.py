"""
Централизованная система логирования с поддержкой ротации файлов,
цветного вывода в консоль и структурированных логов.
"""
import logging
import sys
from pathlib import Path
from logging.handlers import RotatingFileHandler
from datetime import datetime


class ColoredFormatter(logging.Formatter):
    """Форматтер с цветным выводом для консоли."""
    
    COLORS = {
        'DEBUG': '\033[36m',    # Cyan
        'INFO': '\033[32m',     # Green
        'WARNING': '\033[33m',  # Yellow
        'ERROR': '\033[31m',    # Red
        'CRITICAL': '\033[35m', # Magenta
    }
    RESET = '\033[0m'
    
    def format(self, record):
        log_color = self.COLORS.get(record.levelname, self.RESET)
        record.levelname = f"{log_color}{record.levelname}{self.RESET}"
        return super().format(record)


def setup_logger(name: str = 'NLThinkingPanel', level: str = 'INFO') -> logging.Logger:
    """
    Настройка логгера с файловым и консольным выводом.
    
    Args:
        name: Имя логгера
        level: Уровень логирования (DEBUG, INFO, WARNING, ERROR, CRITICAL)
    
    Returns:
        Настроенный логгер
    """
    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, level.upper()))
    
    # Очистка существующих handlers
    logger.handlers.clear()
    
    # Создание директории для логов
    log_dir = Path('logs')
    log_dir.mkdir(exist_ok=True)
    
    # Форматы
    file_format = logging.Formatter(
        '%(asctime)s | %(levelname)-8s | %(name)s | %(funcName)s:%(lineno)d | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    console_format = ColoredFormatter(
        '%(asctime)s | %(levelname)-8s | %(message)s',
        datefmt='%H:%M:%S'
    )
    
    # Файловый handler с ротацией (макс 10MB, 5 файлов)
    file_handler = RotatingFileHandler(
        log_dir / f'{name.lower()}_{datetime.now().strftime("%Y%m%d")}.log',
        maxBytes=10*1024*1024,
        backupCount=5,
        encoding='utf-8'
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(file_format)
    
    # Консольный handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(console_format)
    
    # Добавление handlers
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    
    return logger


# Глобальный логгер
logger = setup_logger()
