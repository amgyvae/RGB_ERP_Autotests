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
import glob
from html import escape
import json
import os
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent
for _p in (ROOT, ROOT / "core", ROOT / "config"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

RUNNER = os.path.join("core", "run_workflow_and_report.py")
MODULE_TIMEOUT = 3 * 60 * 60  # 3 часа на модуль
ALMATY_TZ = timezone(timedelta(hours=5))

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


def _now_almaty_str():
    return datetime.now(ALMATY_TZ).strftime("%d.%m.%Y %H:%M:%S")


def _module_stem(key: str) -> str:
    _, cmd, _ = MODULES[key]
    return Path(cmd[-1]).stem.lower()


def _tg_send_chunked(lines):
    try:
        from run_workflow_and_report import tg_send
    except Exception as exc:
        print(f"[telegram] Не удалось импортировать tg_send: {exc}")
        return
    current = ""
    for line in lines:
        if len(current) + len(line) + 1 > 3800:
            tg_send(current)
            current = ""
        current += ("\n" if current else "") + line
    if current:
        tg_send(current)


def notify_suite_start(selected_keys):
    if not selected_keys:
        return
    now_str = _now_almaty_str()
    account = os.environ.get("RGB_ACCOUNT1_LOGIN", "jyktmargyplay2@gmail.com")
    lines = [
        "🚀 <b>Автотест RGB ERP запущен</b>",
        f"🕒 <b>Время старта:</b> {now_str} (Алматы, UTC+5)",
        f"👤 <b>Основной аккаунт:</b> {escape(account)}",
        f"📦 <b>Модулей в очереди ({len(selected_keys)}):</b>",
    ]
    for idx, k in enumerate(selected_keys, 1):
        title = MODULES[k][0]
        lines.append(f"{idx}. {escape(title)}")
    _tg_send_chunked(lines)


def notify_suite_summary(selected_keys):
    if not selected_keys:
        return
    now_str = _now_almaty_str()
    log_dir = ROOT / "logs"

    # Собираем все найденные JSON-сводки модулей (включая вложенные папки после download-artifact)
    summary_by_stem = {}
    for path_str in glob.glob(str(log_dir / "**" / "suite_module_*.json"), recursive=True):
        try:
            data = json.loads(Path(path_str).read_text(encoding="utf-8"))
            stem = Path(data.get("script", path_str)).stem.lower()
            summary_by_stem[stem] = data
        except Exception:
            continue

    passed_modules = 0
    total_modules = len(selected_keys)
    module_lines = []
    detail_lines = []

    for idx, key in enumerate(selected_keys, 1):
        title = MODULES[key][0]
        stem = _module_stem(key)
        info = summary_by_stem.get(stem)
        if info:
            p_chk = info.get("passed_checks", 0)
            t_chk = info.get("total_checks", 0)
            ok = bool(info.get("ok"))
            failures = info.get("failures") or []
            skipped = info.get("skipped_count", 0)
            if ok:
                passed_modules += 1
                module_lines.append(f"{idx}. ✅ <b>{escape(title)}</b> — УСПЕШНО ({p_chk}/{t_chk})")
            else:
                # Определяем преобладающий тип проблемы по модулю
                origins = {f.get("origin", "Баг сайта") for f in failures}
                if not origins and skipped:
                    tag = "Пропущены этапы"
                elif "Ошибка кода" in origins and "Баг сайта" in origins:
                    tag = "Баг сайта + Ошибка кода"
                elif "Ошибка кода" in origins:
                    tag = "Ошибка кода"
                else:
                    tag = "Баг сайта"
                module_lines.append(
                    f"{idx}. 🔥 <b>{escape(title)}</b> — {p_chk}/{t_chk} успешно <b>[{escape(tag)}]</b>"
                )
                if failures:
                    detail_lines.append(f"\n🔸 <b>{escape(title)} ({p_chk}/{t_chk}):</b>")
                    for f_item in failures[:8]:
                        f_name = escape(str(f_item.get("name", "")))
                        f_reason = escape(str(f_item.get("reason", "см. лог")))
                        f_origin = escape(str(f_item.get("origin", "Баг сайта")))
                        detail_lines.append(f"  • ❌ {f_name} — <b>[{f_origin}]</b> <i>{f_reason}</i>")
                    if len(failures) > 8:
                        detail_lines.append(f"  • <i>... и ещё {len(failures) - 8} ошибок</i>")
                elif skipped:
                    detail_lines.append(
                        f"\n🔸 <b>{escape(title)} ({p_chk}/{t_chk}):</b> пропущено этапов: {skipped}"
                    )
        else:
            module_lines.append(f"{idx}. ⚠️ <b>{escape(title)}</b> — нет данных отчёта")

    header_icon = "✅" if passed_modules == total_modules else "📊"
    lines = [
        f"{header_icon} <b>ПОЛНЫЙ ИТОГ АВТОТЕСТА RGB ERP</b>",
        f"🕒 <b>Время завершения:</b> {now_str} (Алматы, UTC+5)",
        f"🏁 <b>Прошло модулей:</b> <b>{passed_modules}/{total_modules}</b> полностью без ошибок",
        "",
        "<b>Сводка по модулям:</b>",
        *module_lines,
    ]
    if detail_lines:
        lines.append("")
        lines.append("<b>Детализация ошибок (Баг сайта / Ошибка кода):</b>")
        lines.extend(detail_lines)

    _tg_send_chunked(lines)


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
    parser.add_argument("--notify-start", action="store_true", help="отправить в Telegram уведомление о старте автотеста")
    parser.add_argument("--notify-summary", action="store_true", help="отправить в Telegram итоговую сводку по всем модулям")
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

    raw_modules = []
    for m in args.modules:
        raw_modules.extend(part.strip() for part in m.replace(" ", ",").split(",") if part.strip())
    selected = resolve(raw_modules, args.web_only)

    if args.notify_start:
        notify_suite_start(selected)
        return 0

    if args.notify_summary:
        notify_suite_summary(selected)
        return 0

    log_dir = ROOT / "logs"
    log_dir.mkdir(exist_ok=True)
    if len(selected) > 1:
        for old_f in glob.glob(str(log_dir / "suite_module_*.json")):
            try:
                os.remove(old_f)
            except Exception:
                pass
        notify_suite_start(selected)

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

    if len(selected) > 1:
        notify_suite_summary(selected)

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
