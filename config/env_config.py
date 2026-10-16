"""Конфиденциальные настройки автотестов RGB ERP.

Логины, пароли, пароли ЭЦП, токен Telegram и ID таблицы НЕ хранятся в коде.
Они читаются из переменных окружения, а локально — из файла `.env`
рядом с этим модулем (см. `.env.example`). В GitHub Actions те же
переменные передаются через GitHub Secrets.

Приоритет: переменная окружения > значение из `.env`.
Модуль не требует сторонних пакетов (python-dotenv не нужен).
"""
import os
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT_DIR / ".env"

# Гарантируем, что модули из core, config и корня всегда импортируются без ошибок
for _dir in (ROOT_DIR, ROOT_DIR / "core", ROOT_DIR / "config"):
    _p = str(_dir)
    if _p not in sys.path:
        sys.path.insert(0, _p)

_warned = set()


def _load_dotenv(path: Path = ENV_FILE) -> None:
    """Простой парсер `.env`: KEY=VALUE, комментарии `#`, кавычки по краям."""
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export "):]
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        # Уже заданные переменные окружения (например, из GitHub Secrets) не перезаписываем.
        os.environ.setdefault(key, value)


_load_dotenv()


def env(name: str, default: str = "") -> str:
    """Возвращает значение настройки; если она не задана — предупреждает один раз."""
    value = os.environ.get(name, "")
    if value:
        return value
    if not default and name not in _warned:
        _warned.add(name)
        print(f"[env_config] Не задана переменная {name}: заполните .env "
              f"(шаблон — .env.example) или GitHub Secret.", file=sys.stderr)
    return default


def env_list(name: str) -> list:
    """Список из значения через запятую: '111, -222' -> ['111', '-222']."""
    return [item.strip() for item in env(name).split(",") if item.strip()]


def env_flag(name: str, default: bool = False) -> bool:
    value = os.environ.get(name, "").strip().lower()
    if not value:
        return default
    return value in ("1", "true", "yes", "on", "да")


def is_headless() -> bool:
    """HEADLESS=1 — запуск Chrome без окна (CI, сервер без монитора)."""
    return env_flag("HEADLESS", default=False)
