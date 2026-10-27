"""Единая точка запуска всех модулей автотестов RGB ERP.

Используется и локально (Планировщик заданий Windows), и в GitHub Actions.
Модули выполняются ПОСЛЕДОВАТЕЛЬНО: они пишут в одну Google-таблицу
и используют одни и те же тестовые аккаунты.

Примеры:
    python run_all.py                    # все модули
    python run_all.py contacts smeta     # выбранные модули
    python run_all.py --web-only         # без модулей, которым нужен NCALayer
    python run_all.py --list             # список модулей
    python run_all.py --matrix all       # JSON-матрица для GitHub Actions

Код завершения: 0 — все модули успешны, 1 — есть ошибки/пропуски.
"""
import argparse
import json
import os
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RUNNER = os.path.join("core", "run_workflow_and_report.py")
MODULE_TIMEOUT = 3 * 60 * 60  # 3 часа на модуль

# ключ: (название, команда, нужен ли NCALayer / ЭЦП)
MODULES = {
    "contacts":    ("Контакты",                [RUNNER, os.path.join("tests", "contacts", "contacts_test.py")],                 False),
    "passport":    ("Паспорт проектов",        [RUNNER, os.path.join("tests", "passport", "pasportProjects.py")],               False),
    "smeta":       ("Смета",                   [RUNNER, os.path.join("tests", "smeta", "smeta.py")],                            False),
    "finance":     ("Финансы (ДДС / ГФР)",     [RUNNER, os.path.join("tests", "finance", "finance.py")],                        False),
    "supply":      ("Снабжение",               [RUNNER, os.path.join("tests", "supply", "supply.py")],                          False),
    "quality":     ("Контроль качества",       [RUNNER, os.path.join("tests", "quality", "quality.py")],                        False),
    "discussions": ("Обсуждения",              [RUNNER, os.path.join("tests", "discussions", "obsuzhdenie.py")],                False),
    "wiki":        ("База знаний WIKI",        [RUNNER, os.path.join("tests", "wiki", "wiki.py")],                              False),
    "news":        ("Лента новостей",          [RUNNER, os.path.join("tests", "news", "news.py")],                              False),
    "manager":     ("Панель руководителя",     [RUNNER, os.path.join("tests", "manager", "panelrukovoditelya.py")],             False),
    "tasks":       ("Задачи и поручения",      [os.path.join("tests", "tasks", "zadashi.py")],                                  False),
    "gpr":         ("ГПР",                     [RUNNER, os.path.join("tests", "gpr", "gpr_test.py")],                           True),
    "contracts":   ("Договоры",                [RUNNER, os.path.join("tests", "contracts", "contract_workflow_new_design.py")], True),
    "waybills":    ("Накладные",               [RUNNER, os.path.join("tests", "waybills", "waybill_workflow_new_design.py")],   True),
    "invoices":    ("Счета на оплату",         [RUNNER, os.path.join("tests", "invoices", "invoice_workflow_ecp.py")],          True),
    "acts":        ("Акты (АВР, КС-2, Ф-2В)",  [RUNNER, os.path.join("tests", "acts", "test-akt.py")],                          True),
}


def resolve(names, web_only=False):
    if not names or names == ["all"]:
        names = list(MODULES)
    unknown = [n for n in names if n not in MODULES]
    if unknown:
        raise SystemExit(f"Неизвестные модули: {', '.join(unknown)}. Доступны: {', '.join(MODULES)}")
    return [n for n in names if not (web_only and MODULES[n][2])]


def run_module(key, log):
    title, command, _ = MODULES[key]
    banner = f"\n{'=' * 70}\n▶ {title} ({key}) — {datetime.now():%d.%m.%Y %H:%M:%S}\n{'=' * 70}\n"
    print(banner, flush=True)
    log.write(banner)
    pp_dirs = [str(ROOT), str(ROOT / "core"), str(ROOT / "config")]
    if os.environ.get("PYTHONPATH"):
        pp_dirs.append(os.environ["PYTHONPATH"])
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1", PYTHONPATH=os.pathsep.join(pp_dirs))
    started = time.monotonic()
    timed_out = threading.Event()
    with subprocess.Popen([sys.executable, "-u", *command], cwd=ROOT, env=env,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          text=True, encoding="utf-8", errors="replace") as proc:
        def expire():
            if proc.poll() is None:
                timed_out.set()
                proc.kill()

        timer = threading.Timer(MODULE_TIMEOUT, expire)
        timer.daemon = True
        timer.start()
        try:
            for line in proc.stdout:
                print(line, end="", flush=True)
                log.write(line)
            code = proc.wait()
        finally:
            timer.cancel()
    if timed_out.is_set():
        code = 124
        print(f"⏱ {title}: превышен лимит {MODULE_TIMEOUT // 60} мин, процесс остановлен", flush=True)
    return code, time.monotonic() - started


def main():
    parser = argparse.ArgumentParser(description="Запуск автотестов RGB ERP")
    parser.add_argument("modules", nargs="*", help="ключи модулей (по умолчанию — все)")
    parser.add_argument("--web-only", action="store_true", help="пропустить модули с NCALayer")
    parser.add_argument("--list", action="store_true", help="показать список модулей")
    parser.add_argument("--matrix", metavar="MODULES", help="вывести JSON-матрицу для GitHub Actions")
    args = parser.parse_args()

    if args.list:
        for key, (title, command, nca) in MODULES.items():
            print(f"{key:12} {title:28} {' '.join(command):55} {'NCALayer' if nca else 'web'}")
        return 0

    if args.matrix is not None:
        names = [n.strip() for n in args.matrix.replace(" ", ",").split(",") if n.strip()]
        selected = resolve(names, args.web_only)
        print(json.dumps({"include": [{"module": k, "title": MODULES[k][0]} for k in selected]},
                         ensure_ascii=False))
        return 0

    selected = resolve(args.modules, args.web_only)
    log_dir = ROOT / "logs"
    log_dir.mkdir(exist_ok=True)
    log_path = log_dir / f"daily_run_{datetime.now():%Y%m%d_%H%M%S}.txt"
    results = []
    with open(log_path, "w", encoding="utf-8") as log:
        for key in selected:
            code, seconds = run_module(key, log)
            results.append((key, code, seconds))
            log.flush()

        summary = ["", "=" * 70, "ИТОГ ПРОГОНА", "=" * 70]
        for key, code, seconds in results:
            status = "✅ OK" if code == 0 else f"❌ код {code}"
            summary.append(f"{MODULES[key][0]:28} {status:12} {seconds / 60:6.1f} мин")
        summary.append(f"Полный лог: {log_path}")
        text = "\n".join(summary)
        print(text, flush=True)
        log.write(text + "\n")

    step_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if step_summary:
        rows = ["| Модуль | Результат | Время |", "|---|---|---|"]
        for key, code, seconds in results:
            status = "✅ Успешно" if code == 0 else f"❌ Ошибки (код {code})"
            rows.append(f"| {MODULES[key][0]} | {status} | {seconds / 60:.1f} мин |")
        with open(step_summary, "a", encoding="utf-8") as fh:
            fh.write("\n".join(rows) + "\n")

    return 0 if all(code == 0 for _, code, _ in results) else 1


if __name__ == "__main__":
    sys.exit(main())
