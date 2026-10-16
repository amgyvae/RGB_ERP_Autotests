import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent

for _dir in (ROOT_DIR, ROOT_DIR / "core", ROOT_DIR / "config"):
    _p = str(_dir)
    if _p not in sys.path:
        sys.path.insert(0, _p)
SCREENS_DIR = ROOT_DIR / 'screens'
LOGS_DIR = ROOT_DIR / 'logs'
for directory in (SCREENS_DIR, LOGS_DIR):
    directory.mkdir(parents=True, exist_ok=True)


def screen_path(filename):
    return str(SCREENS_DIR / Path(filename).name)


def log_path(filename):
    return str(LOGS_DIR / Path(filename).name)
