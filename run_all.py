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


MODULE_PLANNED_CHECKS = {
    "contacts": 25,
    "passport": 13,
    "smeta": 21,
    "finance": 27,
    "supply": 25,
    "quality": 35,
    "discussions": 18,
    "wiki": 11,
    "news": 17,
    "manager": 16,
    "tasks": 30,
    "gpr": 30,
    "contracts": 26,
    "waybills": 18,
    "invoices": 16,
    "acts": 19,
}


def _now_almaty_dt():
    return datetime.now(ALMATY_TZ)


def _now_almaty_str():
    return _now_almaty_dt().strftime("%d.%m.%Y %H:%M:%S")


def _fmt_duration(seconds: float) -> str:
    sec = max(0, int(round(float(seconds or 0))))
    hrs, rem = divmod(sec, 3600)
    mins, secs = divmod(rem, 60)
    if hrs:
        return f"{hrs} ч {mins} мин {secs} сек"
    if mins:
        return f"{mins} мин {secs} сек"
    return f"{secs} сек"


def _fmt_duration_short(seconds: float) -> str:
    sec = max(0, int(round(float(seconds or 0))))
    hrs, rem = divmod(sec, 3600)
    mins, secs = divmod(rem, 60)
    if hrs:
        return f"{hrs}ч {mins}м {secs}с"
    if mins:
        return f"{mins}м {secs}с"
    return f"{secs}с"


def _plural_stages(n: int) -> str:
    n_abs = abs(int(n)) % 100
    n1 = n_abs % 10
    if 11 <= n_abs <= 19:
        return "этапов"
    if n1 == 1:
        return "этап"
    if 2 <= n1 <= 4:
        return "этапа"
    return "этапов"


def _module_stem(key: str) -> str:
    _, cmd, _ = MODULES[key]
    return Path(cmd[-1]).stem.lower()


def _excluded_ecp_keys(selected_keys, web_only: bool):
    if not web_only:
        return []
    return [k for k, (_, _, needs_ecp) in MODULES.items() if needs_ecp and k not in selected_keys]


def _trigger_label() -> str:
    ev = os.environ.get("GITHUB_EVENT_NAME", "").strip()
    run_no = os.environ.get("GITHUB_RUN_NUMBER", "").strip()
    suffix = f" (run #{run_no})" if run_no else ""
    if ev == "schedule":
        return f"По утреннему расписанию{suffix}"
    if ev == "workflow_dispatch":
        return f"Ручной запуск GitHub Actions{suffix}"
    if ev == "repository_dispatch":
        return f"Внешний вебхук{suffix}"
    if ev:
        return f"CI ({ev}){suffix}"
    return "Локальный запуск"


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


def notify_suite_start(selected_keys, web_only: bool = False):
    if not selected_keys:
        return
    now_dt = _now_almaty_dt()
    now_str = now_dt.strftime("%d.%m.%Y %H:%M:%S")
    has_ecp = any(MODULES[k][2] for k in selected_keys) and not web_only
    ecp_line = (
        "🔐 <b>С ЭЦП</b> (полный контур с подписанием NCALayer)"
        if has_ecp
        else "🌐 <b>БЕЗ ЭЦП</b> (веб-модули, подписание NCALayer отключено)"
    )
    excluded_ecp = _excluded_ecp_keys(selected_keys, web_only or not has_ecp)
    planned_stages = sum(MODULE_PLANNED_CHECKS.get(k, 0) for k in selected_keys)
    account = os.environ.get("RGB_ACCOUNT1_LOGIN", "jyktmargyplay2@gmail.com")

    # Сохраняем метаданные старта для расчёта общей длительности в финальном отчёте
    try:
        log_dir = ROOT / "logs"
        log_dir.mkdir(exist_ok=True)
        meta = {
            "started_epoch": round(time.time(), 2),
            "started_almaty": now_str,
            "started_hms": now_dt.strftime("%H:%M:%S"),
            "started_date": now_dt.strftime("%d.%m.%Y"),
            "web_only": bool(web_only or not has_ecp),
            "has_ecp": bool(has_ecp),
            "trigger": _trigger_label(),
            "selected_keys": list(selected_keys),
            "excluded_ecp_keys": excluded_ecp,
        }
        (log_dir / "suite_start_meta.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception as exc:
        print(f"[suite_meta] Не удалось сохранить suite_start_meta.json: {exc}")

    lines = [
        "🚀 <b>Автотест RGB ERP запущен</b>",
        f"📅 <b>Время старта:</b> {now_str} (Алматы, UTC+5)",
        f"🔐 <b>Режим ЭЦП:</b> {ecp_line}",
        f"⚙️ <b>Источник запуска:</b> {escape(_trigger_label())}",
        f"👤 <b>Аккаунты:</b> Sh Margulan Ju ({escape(account)}) · доп. роль: Алдажаров Диас",
        "",
        f"✅ <b>К проверке — {len(selected_keys)} из {len(MODULES)} модулей ({planned_stages} {_plural_stages(planned_stages)}):</b>",
    ]
    for idx, k in enumerate(selected_keys, 1):
        title = MODULES[k][0]
        cnt = MODULE_PLANNED_CHECKS.get(k, 0)
        stage_note = f" — <i>{cnt} {_plural_stages(cnt)}</i>" if cnt else ""
        lines.append(f"{idx}. {escape(title)}{stage_note}")

    if excluded_ecp:
        excl_titles = ", ".join(escape(MODULES[k][0]) for k in excluded_ecp)
        lines.extend([
            "",
            f"⏭ <b>Не входят в этот запуск (требуют ЭЦП NCALayer — {len(excluded_ecp)} мод.):</b>",
            f"<i>{excl_titles}</i>",
        ])

    _tg_send_chunked(lines)


def notify_suite_summary(selected_keys, web_only: bool = False):
    if not selected_keys:
        return
    finish_dt = _now_almaty_dt()
    now_str = finish_dt.strftime("%d.%m.%Y %H:%M:%S")
    log_dir = ROOT / "logs"

    # Читаем метаданные старта (локально или из скачанного артефакта report-suite-meta-*)
    start_meta = {}
    for meta_path in sorted(
        glob.glob(str(log_dir / "**" / "suite_start_meta.json"), recursive=True),
        key=lambda p: os.path.getmtime(p) if os.path.exists(p) else 0,
    ):
        try:
            start_meta = json.loads(Path(meta_path).read_text(encoding="utf-8"))
        except Exception:
            continue

    # Собираем все найденные JSON-сводки модулей (включая вложенные папки после download-artifact)
    summary_by_stem = {}
    for path_str in glob.glob(str(log_dir / "**" / "suite_module_*.json"), recursive=True):
        try:
            data = json.loads(Path(path_str).read_text(encoding="utf-8"))
            stem = Path(data.get("script", path_str)).stem.lower()
            summary_by_stem[stem] = data
        except Exception:
            continue

    has_ecp = any(MODULES[k][2] for k in selected_keys) and not web_only
    ecp_summary_str = (
        "🔐 <b>С ЭЦП</b> (полный контур с NCALayer)"
        if has_ecp
        else "🌐 <b>БЕЗ ЭЦП</b> (веб-контур, без NCALayer)"
    )
    excluded_ecp = _excluded_ecp_keys(selected_keys, web_only or not has_ecp)

    passed_modules = 0
    failed_modules = 0
    missing_modules = 0
    total_modules = len(selected_keys)
    sum_passed_chk = 0
    sum_total_chk = 0
    sum_failed_chk = 0
    sum_skipped_chk = 0
    sum_mod_durations = 0.0

    module_lines = []
    detail_lines = []

    for idx, key in enumerate(selected_keys, 1):
        title = MODULES[key][0]
        stem = _module_stem(key)
        info = summary_by_stem.get(stem)
        if info:
            p_chk = int(info.get("passed_checks", 0))
            t_chk = int(info.get("total_checks", 0))
            skipped = int(info.get("skipped_count", 0))
            failures = info.get("failures") or []
            f_chk = max(0, t_chk - p_chk - skipped) if not failures else len(failures)
            dur_s = float(info.get("duration_sec", 0.0) or 0.0)
            sum_mod_durations += dur_s
            sum_passed_chk += p_chk
            sum_total_chk += t_chk
            sum_failed_chk += f_chk
            sum_skipped_chk += skipped

            dur_tag = f" <i>(⏱ {_fmt_duration_short(dur_s)})</i>" if dur_s > 0 else ""
            ok = bool(info.get("ok"))
            if ok:
                passed_modules += 1
                module_lines.append(
                    f"{idx}. ✅ <b>{escape(title)}</b> — проверено {p_chk}/{t_chk} {_plural_stages(t_chk)}{dur_tag}"
                )
            else:
                failed_modules += 1
                origins = {f.get("origin", "Баг сайта") for f in failures}
                if not origins and skipped:
                    tag = "Пропущены этапы"
                elif "Ошибка кода" in origins and "Баг сайта" in origins:
                    tag = "Баг сайта + Ошибка кода"
                elif "Ошибка кода" in origins:
                    tag = "Ошибка кода"
                else:
                    tag = "Баг сайта"
                extra_bits = []
                if f_chk:
                    extra_bits.append(f"❌ ошибок: {f_chk}")
                if skipped:
                    extra_bits.append(f"⏸ не выполнено: {skipped}")
                extra_str = f" ({', '.join(extra_bits)})" if extra_bits else ""
                module_lines.append(
                    f"{idx}. 🔥 <b>{escape(title)}</b> — {p_chk}/{t_chk} успешно{extra_str}{dur_tag} <b>[{escape(tag)}]</b>"
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
                        f"\n🔸 <b>{escape(title)} ({p_chk}/{t_chk}):</b> не выполнено этапов: {skipped}"
                    )
        else:
            missing_modules += 1
            planned_c = MODULE_PLANNED_CHECKS.get(key, 0)
            sum_total_chk += planned_c
            sum_skipped_chk += planned_c
            module_lines.append(
                f"{idx}. ⚠️ <b>{escape(title)}</b> — <i>не проверен (отчёт модуля не сформирован)</i>"
            )

    if start_meta.get("started_epoch"):
        wall_sec = max(sum_mod_durations, time.time() - float(start_meta["started_epoch"]))
    else:
        wall_sec = sum_mod_durations

    started_hms = start_meta.get("started_hms")
    started_date = start_meta.get("started_date")
    finish_hms = finish_dt.strftime("%H:%M:%S")
    finish_date = finish_dt.strftime("%d.%m.%Y")
    if started_hms and started_date == finish_date:
        time_window_line = f"🕒 <b>Время прогона:</b> {started_hms} → {finish_hms} ({finish_date}, Алматы UTC+5)"
    elif start_meta.get("started_almaty"):
        time_window_line = f"🕒 <b>Время прогона:</b> {start_meta['started_almaty']} → {now_str} (Алматы UTC+5)"
    else:
        time_window_line = f"🕒 <b>Завершено:</b> {now_str} (Алматы, UTC+5)"

    header_icon = "✅" if (passed_modules == total_modules and total_modules > 0) else "📊"
    lines = [
        f"{header_icon} <b>ПОЛНЫЙ ИТОГ АВТОТЕСТА RGB ERP</b>",
        f"🔐 <b>Режим:</b> {ecp_summary_str}",
        time_window_line,
        f"⏱ <b>Общая длительность:</b> <b>{_fmt_duration(wall_sec)}</b>"
        + (f" <i>(чистое время тестов: {_fmt_duration(sum_mod_durations)})</i>"
           if wall_sec - sum_mod_durations > 90 and sum_mod_durations > 0 else ""),
        f"🏁 <b>Модули без ошибок:</b> <b>{passed_modules}/{total_modules}</b>"
        + (f" · ❌ с ошибками: {failed_modules}" if failed_modules else "")
        + (f" · ⚠️ без отчёта: {missing_modules}" if missing_modules else ""),
        f"📋 <b>Этапы проверок:</b> ✅ <b>{sum_passed_chk}/{sum_total_chk}</b> успешно"
        f" · ❌ ошибок: <b>{sum_failed_chk}</b> · ⏸ пропущено: <b>{sum_skipped_chk}</b>",
        "",
        "<b>Что проверено по модулям:</b>",
        *module_lines,
    ]

    if excluded_ecp:
        excl_titles = " · ".join(escape(MODULES[k][0]) for k in excluded_ecp)
        lines.extend([
            "",
            f"⏭ <b>Не проверялись в режиме БЕЗ ЭЦП ({len(excluded_ecp)} мод. NCALayer):</b>",
            f"<i>{excl_titles}</i>",
        ])

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


def run_module(key, log, web_only: bool = False):
    title, command, needs_ecp = MODULES[key]
    banner = f"\n{'=' * 70}\n▶ {title} ({key}) — {datetime.now():%d.%m.%Y %H:%M:%S}\n{'=' * 70}\n"
    print(banner, flush=True)
    log.write(banner)
    pp_dirs = [str(ROOT), str(ROOT / "core"), str(ROOT / "config")]
    if os.environ.get("PYTHONPATH"):
        pp_dirs.append(os.environ["PYTHONPATH"])
    default_web_only = "0" if needs_ecp else ("1" if web_only else os.environ.get("RGB_WEB_ONLY", "1"))
    env = dict(
        os.environ,
        PYTHONIOENCODING="utf-8",
        PYTHONUTF8="1",
        PYTHONPATH=os.pathsep.join(pp_dirs),
        RGB_WEB_ONLY=default_web_only,
    )
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
        notify_suite_start(selected, web_only=args.web_only)
        return 0

    if args.notify_summary:
        notify_suite_summary(selected, web_only=args.web_only)
        return 0

    log_dir = ROOT / "logs"
    log_dir.mkdir(exist_ok=True)
    if len(selected) > 1:
        for old_f in glob.glob(str(log_dir / "suite_module_*.json")):
            try:
                os.remove(old_f)
            except Exception:
                pass
        notify_suite_start(selected, web_only=args.web_only)

    log_path = log_dir / f"daily_run_{datetime.now():%Y%m%d_%H%M%S}.txt"
    results = []
    with open(log_path, "w", encoding="utf-8") as log:
        for key in selected:
            code, seconds = run_module(key, log, web_only=args.web_only)
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
        notify_suite_summary(selected, web_only=args.web_only)

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
