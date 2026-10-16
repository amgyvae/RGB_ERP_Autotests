import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
for d in (ROOT, ROOT / "core", ROOT / "config"):
    p = str(d)
    if p not in sys.path:
        sys.path.insert(0, p)

import pytest
from sheet_reporter import report_result


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "checklist_task(task_name): связывает тест с задачей в колонке 'Задача' листа "
        "'Чек-лист' (текст должен совпадать дословно)"
    )


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()

    if report.when != "call":
        return

    marker = item.get_closest_marker("checklist_task")
    if marker is None:
        return

    task_name = marker.args[0]

    try:
        report_result(task_name=task_name, passed=report.passed)
    except Exception as e:
        print(f"[conftest] Не удалось записать в таблицу: {e}")