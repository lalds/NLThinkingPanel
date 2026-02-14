"""
Гибкая система прав доступа (RBAC + индивидуальные разрешения).

Поддерживает:
 - Иерархические роли: owner > admin > moderator > vip > member
 - Привязку Discord-ролей к внутренним ролям бота
 - Индивидуальные разрешения для пользователей
 - Временные повышения прав (например, на 1 час)
 - Чёрный и белый списки для команд
"""
import json
import time
from pathlib import Path
from typing import Dict, List, Set, Optional, Any
from dataclasses import dataclass, field
from core.logger import logger
from config.config import config


# ─── Определение уровней ───

ROLE_HIERARCHY = {
    'owner': 100,
    'admin': 80,
    'moderator': 60,
    'vip': 40,
    'trusted': 30,
    'member': 10,
    'restricted': 0,
}

# Какие разрешения даёт каждая роль по умолчанию
DEFAULT_ROLE_PERMISSIONS = {
    'owner': {
        '*',  # Полный доступ
    },
    'admin': {
        'admin.*',          # Админские команды
        'moderation.*',     # Модерация
        'commands.*',       # Все обычные команды
        'personality.*',    # Управление личностями
        'knowledge.*',      # Управление базой знаний
        'users.*',          # Управление пользователями
        'analytics.*',      # Просмотр аналитики
    },
    'moderator': {
        'moderation.*',
        'commands.utility',
        'commands.fun',
        'commands.ask',
        'commands.quick',
        'commands.web',
        'commands.profile',
        'commands.personality.manage', # Право менять личность
        'commands.kb.manage',          # Право добавлять статьи
        'users.view',
        'analytics.view',
        'admin.stats',      # Просмотр статистики
    },
    'vip': {
        'commands.ask',
        'commands.quick',
        'commands.web',
        'commands.fun',
        'commands.utility',
        'commands.profile',
        'commands.image',
        'commands.translate',
        'rate_limit.extended',
    },
    'trusted': {
        'commands.ask',
        'commands.quick',
        'commands.web',
        'commands.fun',
        'commands.utility',
        'commands.profile',
    },
    'member': {
        'commands.ask',
        'commands.quick',
        'commands.web',
        'commands.fun',
        'commands.utility',
        'commands.profile',
    },
    'restricted': set(),  # Нет прав
}


@dataclass
class TempElevation:
    """Временное повышение прав."""
    role: str
    granted_by: int
    expires_at: float
    reason: str = ""


class PermissionManager:
    """Управление правами доступа."""

    def __init__(self, data_file: str = 'data/permissions.json'):
        self.data_file = Path(data_file)
        self.data_file.parent.mkdir(parents=True, exist_ok=True)

        # user_id -> role_name
        self._user_roles: Dict[int, str] = {}
        # user_id -> set of extra permissions
        self._user_permissions: Dict[int, Set[str]] = {}
        # user_id -> set of denied permissions
        self._user_denials: Dict[int, Set[str]] = {}
        # user_id -> TempElevation
        self._temp_elevations: Dict[int, TempElevation] = {}
        # discord_role_id -> bot_role
        self._discord_role_map: Dict[int, str] = {}
        # command_name -> set of required permissions
        self._command_permissions: Dict[str, str] = {}

        self._load_data()
        self._ensure_owners()

    def _ensure_owners(self):
        """Убедиться что admin_ids из конфига имеют роль owner."""
        for admin_id in config.admin_ids:
            if admin_id not in self._user_roles:
                self._user_roles[admin_id] = 'owner'

    def _load_data(self):
        """Загрузка сохранённых данных."""
        if not self.data_file.exists():
            return

        try:
            with open(self.data_file, 'r', encoding='utf-8') as f:
                data = json.load(f)

            self._user_roles = {int(k): v for k, v in data.get('user_roles', {}).items()}
            self._user_permissions = {
                int(k): set(v) for k, v in data.get('user_permissions', {}).items()
            }
            self._user_denials = {
                int(k): set(v) for k, v in data.get('user_denials', {}).items()
            }
            self._discord_role_map = {
                int(k): v for k, v in data.get('discord_role_map', {}).items()
            }
            self._command_permissions = data.get('command_permissions', {})

        except Exception as e:
            logger.error(f"Ошибка загрузки разрешений: {e}")

    def _save_data(self):
        """Сохранение данных."""
        try:
            data = {
                'user_roles': {str(k): v for k, v in self._user_roles.items()},
                'user_permissions': {
                    str(k): list(v) for k, v in self._user_permissions.items()
                },
                'user_denials': {
                    str(k): list(v) for k, v in self._user_denials.items()
                },
                'discord_role_map': {
                    str(k): v for k, v in self._discord_role_map.items()
                },
                'command_permissions': self._command_permissions,
            }
            with open(self.data_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Ошибка сохранения разрешений: {e}")

    # ─── Роли ───

    def get_user_role(self, user_id: int) -> str:
        """Получить роль пользователя."""
        # Проверка временного повышения
        if user_id in self._temp_elevations:
            elev = self._temp_elevations[user_id]
            if time.time() < elev.expires_at:
                return elev.role
            else:
                del self._temp_elevations[user_id]

        return self._user_roles.get(user_id, 'member')

    def set_user_role(self, user_id: int, role: str) -> bool:
        """Установить роль пользователя."""
        if role not in ROLE_HIERARCHY:
            return False

        self._user_roles[user_id] = role
        self._save_data()
        logger.info(f"Установлена роль '{role}' для пользователя {user_id}")
        return True

    def elevate_temporarily(
        self,
        user_id: int,
        role: str,
        duration_seconds: int,
        granted_by: int,
        reason: str = ""
    ) -> bool:
        """Временное повышение прав."""
        if role not in ROLE_HIERARCHY:
            return False

        self._temp_elevations[user_id] = TempElevation(
            role=role,
            granted_by=granted_by,
            expires_at=time.time() + duration_seconds,
            reason=reason
        )
        logger.info(
            f"Временное повышение до '{role}' для {user_id} "
            f"на {duration_seconds}s, причина: {reason}"
        )
        return True

    def get_role_level(self, user_id: int) -> int:
        """Получить числовой уровень прав пользователя."""
        role = self.get_user_role(user_id)
        return ROLE_HIERARCHY.get(role, 0)

    # ─── Разрешения ───

    def has_permission(self, user_id: int, permission: str) -> bool:
        """
        Проверка наличия разрешения.

        Поддерживает wildcard:
        - "moderation.*" даёт доступ к "moderation.warn", "moderation.kick" и т.д.
        """
        # Явные запреты имеют приоритет
        denials = self._user_denials.get(user_id, set())
        for denial in denials:
            if self._match_permission(denial, permission):
                return False

        # Проверка индивидуальных разрешений
        extras = self._user_permissions.get(user_id, set())
        for extra in extras:
            if self._match_permission(extra, permission):
                return True

        # Проверка разрешений роли
        role = self.get_user_role(user_id)
        role_perms = DEFAULT_ROLE_PERMISSIONS.get(role, set())
        for perm in role_perms:
            if self._match_permission(perm, permission):
                return True

        return False

    def _match_permission(self, pattern: str, target: str) -> bool:
        """Проверка совпадения разрешения с шаблоном."""
        if pattern == target:
            return True
        if pattern.endswith('.*'):
            prefix = pattern[:-2]
            return target.startswith(prefix + '.') or target == prefix
        if pattern == '*':
            return True
        return False

    def grant_permission(self, user_id: int, permission: str) -> None:
        """Выдать разрешение пользователю."""
        if user_id not in self._user_permissions:
            self._user_permissions[user_id] = set()
        self._user_permissions[user_id].add(permission)
        self._save_data()

    def revoke_permission(self, user_id: int, permission: str) -> None:
        """Отобрать разрешение."""
        if user_id in self._user_permissions:
            self._user_permissions[user_id].discard(permission)
            self._save_data()

    def deny_permission(self, user_id: int, permission: str) -> None:
        """Явно запретить разрешение (даже если роль его даёт)."""
        if user_id not in self._user_denials:
            self._user_denials[user_id] = set()
        self._user_denials[user_id].add(permission)
        self._save_data()

    # ─── Discord роли ───

    def map_discord_role(self, discord_role_id: int, bot_role: str) -> bool:
        """Привязать Discord роль к роли бота."""
        if bot_role not in ROLE_HIERARCHY:
            return False
        self._discord_role_map[discord_role_id] = bot_role
        self._save_data()
        return True

    def resolve_role_from_discord(self, member_role_ids: List[int]) -> str:
        """Определить роль бота на основе Discord ролей участника."""
        best_role = 'member'
        best_level = ROLE_HIERARCHY.get('member', 0)

        for role_id in member_role_ids:
            if role_id in self._discord_role_map:
                mapped_role = self._discord_role_map[role_id]
                level = ROLE_HIERARCHY.get(mapped_role, 0)
                if level > best_level:
                    best_role = mapped_role
                    best_level = level

        return best_role

    # ─── Команды ───

    def set_command_permission(self, command: str, permission: str) -> None:
        """Установить требуемое разрешение для команды."""
        self._command_permissions[command] = permission
        self._save_data()

    def can_use_command(self, user_id: int, command: str) -> bool:
        """Проверка, может ли пользователь использовать команду."""
        if command not in self._command_permissions:
            return True  # Если разрешение не задано — разрешено всем

        required_perm = self._command_permissions[command]
        return self.has_permission(user_id, required_perm)

    # ─── Информация ───

    def get_user_info(self, user_id: int) -> Dict[str, Any]:
        """Полная информация о правах пользователя."""
        role = self.get_user_role(user_id)
        role_perms = DEFAULT_ROLE_PERMISSIONS.get(role, set())
        extra_perms = self._user_permissions.get(user_id, set())
        denials = self._user_denials.get(user_id, set())

        temp = None
        if user_id in self._temp_elevations:
            elev = self._temp_elevations[user_id]
            if time.time() < elev.expires_at:
                temp = {
                    'role': elev.role,
                    'expires_in': int(elev.expires_at - time.time()),
                    'reason': elev.reason,
                }

        return {
            'role': role,
            'role_level': ROLE_HIERARCHY.get(role, 0),
            'role_permissions': sorted(role_perms),
            'extra_permissions': sorted(extra_perms),
            'denied_permissions': sorted(denials),
            'temp_elevation': temp,
        }

    def get_stats(self) -> Dict[str, Any]:
        """Статистика системы разрешений."""
        role_counts = {}
        for role in self._user_roles.values():
            role_counts[role] = role_counts.get(role, 0) + 1

        return {
            'total_users_with_roles': len(self._user_roles),
            'role_distribution': role_counts,
            'users_with_extra_perms': len(self._user_permissions),
            'users_with_denials': len(self._user_denials),
            'discord_role_mappings': len(self._discord_role_map),
            'active_temp_elevations': len([
                e for e in self._temp_elevations.values()
                if time.time() < e.expires_at
            ]),
        }


# Глобальный экземпляр
permissions = PermissionManager()
