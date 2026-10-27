import json
import os
import time
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime

from env_config import ROOT_DIR, env

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
# Ключ сервисного аккаунта Google: либо путь к файлу (локально),
# либо всё содержимое JSON в переменной GOOGLE_SERVICE_ACCOUNT_JSON (GitHub Secrets).
CREDS_PATH = env("GOOGLE_SERVICE_ACCOUNT_FILE", "service_account.json")

SPREADSHEET_ID = env("GOOGLE_SPREADSHEET_ID", "1EoM1ckRUfeGoz0ag48F8VSGpL7OcpLjEXW6QFbijfZU")  # из URL между /d/ и /edit
SHEET_NAME = "Чек-лист"

HEADER_ROW = 3         # строка с заголовками колонок
COL_TASK = 2            # колонка "Название проверки" (B)
FIRST_RUN_COL = 4       # колонка D — даты; C содержит описание полей

ASSIGNMENT_CHECKS = {
    "Поручение": "Создание поручения — тип «Поручение»",
    "Поручение на стройке": "Создание поручения — тип «Поручение на стройке»",
    "Заявка на договор поставки": "Создание поручения — тип «Заявка на договор поставки»",
    "Заявка на договор услуг": "Создание поручения — тип «Заявка на договор услуг»",
}
ASSIGNMENT_ATTACHMENT_CHECK = "Создание поручения с вложением документа"


def _normalize_text(value):
    tokens = str(value or "").split()
    return " ".join(token for token in tokens if token not in ('—', '–', '-')).casefold()


def _load_credentials():
    raw_json = env("GOOGLE_SERVICE_ACCOUNT_JSON", "-")
    if raw_json != "-" and raw_json.strip():
        try:
            return Credentials.from_service_account_info(json.loads(raw_json), scopes=SCOPES)
        except Exception as e:
            print(f"[sheet_reporter] Ошибка парсинга GOOGLE_SERVICE_ACCOUNT_JSON: {e}")
            return None
    for candidate in (CREDS_PATH, str(ROOT_DIR / CREDS_PATH), str(ROOT_DIR / "service_account.json"), str(ROOT_DIR / "config" / "service_account.json")):
        if os.path.isfile(candidate):
            return Credentials.from_service_account_file(candidate, scopes=SCOPES)
    return None


def _connect_with_retry(max_attempts=4):
    """Подключение с повтором при 429 (Quota exceeded)."""
    creds = _load_credentials()
    if creds is None:
        print("[sheet_reporter] Учетные данные Google Sheets не найдены (пропуск записи).")
        return None
    if not SPREADSHEET_ID:
        print("[sheet_reporter] GOOGLE_SPREADSHEET_ID не задан (пропуск записи).")
        return None
    for attempt in range(max_attempts):
        try:
            client = gspread.authorize(creds)
            return client.open_by_key(SPREADSHEET_ID).worksheet(SHEET_NAME)
        except gspread.exceptions.APIError as e:
            if "429" in str(e) and attempt < max_attempts - 1:
                wait = 15 * (attempt + 1)
                print(f"[sheet_reporter] Лимит API (429), жду {wait} сек и пробую снова...")
                time.sleep(wait)
                continue
            raise


def _connect():
    return _connect_with_retry()


def _find_row_in_column(tasks_column, task_name: str, row_range=None):
    """Ищет строку с точным текстом в УЖЕ ПРОЧИТАННОМ столбце (без
    обращения к API) — используется внутри report_results(), где
    столбец читается один раз на весь пакет находок."""
    start = row_range[0] if row_range else 1
    end = row_range[1] if row_range else len(tasks_column)
    norm_target = _normalize_text(task_name)
    matches = []
    for i in range(start, min(end, len(tasks_column)) + 1):
        value = tasks_column[i - 1] if i - 1 < len(tasks_column) else ""
        if _normalize_text(value) == norm_target:
            matches.append(i)
    if not matches:
        alias_target = (norm_target.replace("ерлан талгатович", "бейсембаев куаныш")
                                   .replace("талгат ерланович", "алдажаров диас")
                                   .replace("бейсембаев куаныш", "ерлан талгатович")
                                   .replace("алдажаров диас", "талгат ерланович"))
        for i in range(start, min(end, len(tasks_column)) + 1):
            value = tasks_column[i - 1] if i - 1 < len(tasks_column) else ""
            if _normalize_text(value) == alias_target:
                matches.append(i)
    if len(matches) > 1:
        raise ValueError(
            f"Проверка '{task_name}' неоднозначна: строки {matches}. "
            "Укажите диапазон раздела, чтобы не записать результат в чужую строку."
        )
    return matches[0] if matches else None


def _find_row_by_task(ws, task_name: str, row_range=None):
    """Старая версия — делает собственный запрос на чтение столбца.
    Оставлена для обратной совместимости (если где-то вызывается
    напрямую), но report_result()/report_results() её больше не
    используют внутри пакетной записи."""
    tasks_column = ws.col_values(COL_TASK)
    return _find_row_in_column(tasks_column, task_name, row_range=row_range)


def _unmerged_row_spans(start, end, merges, columns):
    """Rows safe to copy between individual columns without touching merged headers."""
    blocked = []
    for merged in merges:
        left = merged.get('startColumnIndex', 0)
        right = merged.get('endColumnIndex', max(columns) + 1)
        if not any(left <= column < right for column in columns):
            continue
        lo = max(start, merged.get('startRowIndex', 0))
        hi = min(end, merged.get('endRowIndex', end))
        if lo < hi:
            blocked.append((lo, hi))
    spans = []
    cursor = start
    for lo, hi in sorted(blocked):
        if cursor < lo:
            spans.append((cursor, lo))
        cursor = max(cursor, hi)
    if cursor < end:
        spans.append((cursor, end))
    return spans


def _find_or_create_date_column(ws, date_str: str, header_values=None) -> int:
    """Ищет колонку с такой датой в шапке (начиная с FIRST_RUN_COL).
    Если header_values не передан — читает шапку сама (1 запрос);
    если передан (уже прочитан ранее в этом же прогоне) — читать не надо."""
    if header_values is None:
        header_values = ws.row_values(HEADER_ROW)

    # Поддерживаем и исходный чек-лист, и версию с полями в колонке C.
    fields_columns = [
        i + 1 for i, value in enumerate(header_values)
        if _normalize_text(value) == "заполняемые поля"
    ]
    first_run_col = max(FIRST_RUN_COL, max(fields_columns) + 1) if fields_columns else FIRST_RUN_COL

    for idx in range(first_run_col, len(header_values) + 1):
        if str(header_values[idx - 1] or "").strip() == date_str:
            return idx

    new_col = max(len(header_values) + 1, first_run_col)
    if new_col > ws.col_count:
        ws.add_cols(new_col - ws.col_count)
    requests = []
    if new_col > first_run_col:
        metadata = ws.spreadsheet.fetch_sheet_metadata(params={'fields': 'sheets(properties(sheetId),merges)'})
        sheet = next((s for s in metadata.get('sheets', []) if s.get('properties', {}).get('sheetId') == ws.id), None)
        if sheet is None:
            raise ValueError('Не удалось прочитать объединённые ячейки целевого листа')
        spans = _unmerged_row_spans(HEADER_ROW - 1, ws.row_count, sheet.get('merges', []), (new_col - 2, new_col - 1))
        if not any(start <= HEADER_ROW - 1 < end for start, end in spans):
            raise ValueError('Нельзя записать дату: ячейка заголовка входит в объединённый диапазон')
        for start, end in spans:
            source = dict(sheetId=ws.id, startRowIndex=start, endRowIndex=end,
                          startColumnIndex=new_col - 2, endColumnIndex=new_col - 1)
            destination = dict(source, startColumnIndex=new_col - 1, endColumnIndex=new_col)
            for paste_type in ('PASTE_FORMAT', 'PASTE_DATA_VALIDATION'):
                requests.append({'copyPaste': {'source': source, 'destination': destination, 'pasteType': paste_type}})
        requests.append({'setDataValidation': {
            'range': {'sheetId': ws.id, 'startRowIndex': HEADER_ROW - 1, 'endRowIndex': HEADER_ROW,
                      'startColumnIndex': new_col - 1, 'endColumnIndex': new_col}}})
    requests.append({'updateDimensionProperties': {
        'range': {'sheetId': ws.id, 'dimension': 'COLUMNS',
                  'startIndex': new_col - 1, 'endIndex': new_col},
        'properties': {'pixelSize': 190}, 'fields': 'pixelSize'}})
    # Сначала оформление, затем заголовок: при ошибке повторный запуск
    # не примет недооформленный столбец за готовый. Значения не копируются.
    ws.spreadsheet.batch_update({'requests': requests})
    ws.update_cell(HEADER_ROW, new_col, date_str)
    return new_col


def report_assignment_result(assignment_type, passed, *, with_attachment=False):
    """Записывает результат отдельного сценария, уже выполненного автотестом.

    Эта функция не запускает создание поручения и не копирует результат
    общей проверки на все типы. Вызывать после проверки конкретного типа.
    """
    if assignment_type not in ASSIGNMENT_CHECKS:
        raise ValueError(f"Неизвестный тип поручения: {assignment_type!r}")
    if with_attachment and assignment_type != "Поручение":
        raise ValueError("В чек-листе сценарий с вложением задан для типа 'Поручение'")
    task_name = (ASSIGNMENT_ATTACHMENT_CHECK if with_attachment
                 else ASSIGNMENT_CHECKS[assignment_type])
    report_result(task_name, passed, row_range=(95, 103))


def report_result(task_name: str, passed: bool, row_range=None):
    """Записывает ОДИН результат. Делает собственные запросы к API —
    удобно для разовой записи, но если нужно записать МНОГО результатов
    за один прогон (несколько сценариев подряд) — используй
    report_results() ниже, иначе легко упереться в лимит API (429)."""
    print(f"[sheet_reporter] Ищу задачу: '{task_name}'" +
          (f" (строки {row_range[0]}-{row_range[1]})" if row_range else ""))
    ws = _connect()
    if ws is None:
        return

    row = _find_row_by_task(ws, task_name, row_range=row_range)
    if row is None:
        print(f"[sheet_reporter] Задача '{task_name}' не найдена в колонке B"
              + (f" в диапазоне строк {row_range}" if row_range else "") + ", пропуск")
        return

    today = datetime.now().strftime("%d.%m.%Y")
    col = _find_or_create_date_column(ws, today)
    status = "Успешно (Автотест)" if passed else "Не успешно (Автотест)"

    ws.update_cell(row, col, status)
    print(f"[sheet_reporter] Готово: '{task_name}' -> {status} (строка {row}, колонка {col}, дата {today})")


def report_results(findings, row_range=None):
    """Пишет НЕСКОЛЬКО результатов за один прогон МИНИМАЛЬНЫМ числом
    запросов к API (одно подключение, одно чтение столбца B, одно
    чтение шапки, ОДНА пакетная запись всех ячеек) — вместо N*3+
    запросов, как было раньше при вызове report_result() в цикле.
    Именно это и вызывало 429 Quota exceeded при нескольких сценариях
    подряд в одном прогоне.

    findings: список (task_name, passed) — как возвращает
              run_and_collect() в run_workflow_and_report.py.
    """
    if not findings:
        return {'written': 0}

    ws = _connect()
    if ws is None:
        return {'written': len(findings), 'skipped_no_creds': True}
    tasks_column = ws.col_values(COL_TASK)          # 1 запрос на чтение (а не N)
    header_values = ws.row_values(HEADER_ROW)        # 1 запрос на чтение (а не N)

    status_map = {True: "Успешно (Автотест)", False: "Не успешно (Автотест)"}
    resolved = []
    missing = []
    for task_name, passed in findings:
        print(f"[sheet_reporter] Ищу задачу: '{task_name}'" +
              (f" (строки {row_range[0]}-{row_range[1]})" if row_range else ""))
        row = _find_row_in_column(tasks_column, task_name, row_range=row_range)
        if row is None:
            print(f"[sheet_reporter] Задача '{task_name}' не найдена в колонке B"
                  + (f" в диапазоне строк {row_range}" if row_range else "") + ", пропуск")
            missing.append(task_name)
            continue
        status = status_map[bool(passed)]
        resolved.append((task_name, row, status))

    if missing:
        raise ValueError('Результаты не записаны: не найдены строки чек-листа: ' + '; '.join(missing))
    if not resolved:
        return {'written': 0}
    today = datetime.now().strftime("%d.%m.%Y")
    col = _find_or_create_date_column(ws, today, header_values=header_values)
    cells_to_update = [gspread.Cell(row, col, status) for _, row, status in resolved]

    if cells_to_update:
        # Одна пакетная запись всех ячеек сразу — 1 запрос вместо N.
        for attempt in range(4):
            try:
                ws.update_cells(cells_to_update)
                addresses = [gspread.utils.rowcol_to_a1(row, col) for _, row, _ in resolved]
                actual = ws.batch_get(addresses, value_render_option='UNFORMATTED_VALUE')
                if len(actual) != len(resolved) or any(
                        len(values) != 1 or len(values[0]) != 1 or values[0][0] != status
                        for values, (_, _, status) in zip(actual, resolved)):
                    raise RuntimeError('Google Sheets: контрольное чтение не подтвердило все записанные результаты')
                for task_name, row, status in resolved:
                    print(f"[sheet_reporter] Готово: '{task_name}' -> {status} "
                          f"(строка {row}, колонка {col}, дата {today})")
                return {'written': len(resolved), 'date': today, 'column': col, 'rows': [row for _, row, _ in resolved]}
            except gspread.exceptions.APIError as e:
                if "429" in str(e) and attempt < 3:
                    wait = 15 * (attempt + 1)
                    print(f"[sheet_reporter] Лимит API при записи (429), жду {wait} сек...")
                    time.sleep(wait)
                    continue
                raise
