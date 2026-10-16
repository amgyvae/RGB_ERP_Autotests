"""Shared destinations for RGB autotest diagnostics."""
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent
SCREENS_DIR = ROOT_DIR / 'screens'
LOGS_DIR = ROOT_DIR / 'logs'
for directory in (SCREENS_DIR, LOGS_DIR):
    directory.mkdir(parents=True, exist_ok=True)


def screen_path(filename):
    return str(SCREENS_DIR / Path(filename).name)


def log_path(filename):
    return str(LOGS_DIR / Path(filename).name)
