"""
Запускает waybill/contract/invoice/gpr скрипты БЕЗ ИЗМЕНЕНИЯ их бизнес-логики,
читает их вывод ("Название: ✓/✗" или нумерованные [OK]/[FAIL] для ГПР),
пишет каждую проверку отдельной строкой в чек-лист через sheet_reporter,
и отправляет итоговую сводку в Telegram.

Использование:
    py run_workflow_and_report.py waybill_workflow_new_design.py
    py run_workflow_and_report.py contract_workflow_new_design.py
    py run_workflow_and_report.py invoice_workflow_ecp.py
    py run_workflow_and_report.py gpr_test.py
    py run_workflow_and_report.py test-akt.py avr arbitrary_nds_16 --creation-only

ВАЖНО: диапазоны строк (ROW_RANGE) ниже соответствуют текущей структуре
Чек-лист_RGB.xlsx (секции "Накладные"/"Договоры"/"Счета/Инвойсы" по 5
строк проверок каждая). Если добавишь/удалишь строки в таблице выше
этих секций — поправь номера строк здесь.

TELEGRAM: TG_TOKEN — секретный ключ бота. Он хранится НЕ в коде, а в
файле .env (локально) или в GitHub Secrets (CI) — см. env_config.py.
Если ключ всё же "утёк" — сразу перевыпусти его через @BotFather
(/revoke) и обнови значение в .env / GitHub Secrets.
"""

from artifact_paths import ROOT_DIR, SCREENS_DIR, LOGS_DIR, screen_path, log_path

import os
import sys
import re
import subprocess
import glob
from datetime import datetime

import requests

from sheet_reporter import report_results

# ==========================================
# TELEGRAM
# ==========================================
from env_config import env, env_list, env_flag  # секреты — из .env / GitHub Secrets

TG_TOKEN = env("TG_TOKEN")
TG_CHATS = env_list("TG_CHATS")
# TG_ENABLED=0 в .env отключает отправку; без токена отправка отключается сама.
TG_ENABLED = env_flag("TG_ENABLED", default=True) and bool(TG_TOKEN and TG_CHATS)
TG_API = f"https://api.telegram.org/bot{TG_TOKEN}"

# Человекочитаемые названия модулей для сообщений в Telegram
MODULE_LABELS = {
    "panelrukovoditelya.py": "Панель руководителя",
    "news.py": "Лента новостей",
    "wiki.py": "WIKI",
    "obsuzhdenie.py": "Обсуждения",
    "quality.py": "Контроль качества",
    "supply.py": "Снабжение",
    "pasportProjects.py": "Паспорт проектов",
    "smeta.py": "Смета",
    "finance.py": "Финансы",
    "test-akt.py": "Акты",
    "gpr_test.py": "ГПР",
    "waybill_workflow_new_design.py": "Накладная",
    "contract_workflow_new_design.py": "Договор",
    "invoice_workflow_ecp.py": "Заявка на оплату (Счёт)",
}


def tg_send(text: str):
    if not TG_ENABLED:
        return
    for cid in TG_CHATS:
        try:
            requests.post(f"{TG_API}/sendMessage", data={
                "chat_id": cid, "text": text[:4000], "parse_mode": "HTML"
            }, timeout=10)
        except Exception as e:
            print(f"[telegram] Не удалось отправить сообщение в чат {cid}: {e}")


def tg_photo(path: str, caption: str = ""):
    if not TG_ENABLED:
        return
    if not os.path.exists(path):
        return
    for cid in TG_CHATS:
        try:
            with open(path, "rb") as f:
                requests.post(f"{TG_API}/sendPhoto", data={
                    "chat_id": cid, "caption": caption[:1000], "parse_mode": "HTML"
                }, files={"photo": f}, timeout=30)
        except Exception as e:
            print(f"[telegram] Не удалось отправить фото в чат {cid}: {e}")


def _latest_debug_screenshot(script_dir: str) -> str:
    """Ищет самый свежий debug_*.png — обычно это скриншот места,
    где что-то пошло не так (см. shot() в самих workflow-скриптах)."""
    files = glob.glob(os.path.join(script_dir, "screens", "**", "*.png"), recursive=True)
    if not files:
        files = glob.glob(os.path.join(script_dir, "debug_*.png"))
    if not files:
        return ""
    return max(files, key=os.path.getmtime)


# Конфигурация модулей: под какое название файла — какой диапазон строк
# в чек-листе, и как называются проверки внутри этого диапазона
# (БЕЗ префикса модуля и БЕЗ "(авто)" — ровно как в самой таблице).
#
# ВАЖНО про порядок ключевых слов внутри "tasks": более КОНКРЕТНЫЕ
# фразы должны идти РАНЬШЕ более общих — иначе короткое слово вроде
# "документ" случайно перехватит строку "Документ из шаблона:
# выключено...", которая тоже содержит "документ" как подстроку.
# Проверка идёт по каждой строке лога независимо, ищем первое
# совпадение по порядку словаря.
# Проверки актов: разбор отчёта в общем скрипте автозаписи.
import json
ACT_TYPES = {'avr': 'АВР', 'ks2': 'КС-2', 'f2b': 'Ф-2В'}
SCENARIOS = {'default': ('По форме', 'Без НДС', False), 'nds_0': ('По форме', 'НДС 0%', False), 'nds_16': ('По форме', 'НДС 16%', False), 'form_arbitrary': ('Произвольно', 'Без НДС', False), 'paper_mode': ('Произвольно', 'Без НДС', True), 'arbitrary_nds_0': ('Произвольно', 'НДС 0%', False), 'arbitrary_nds_16': ('Произвольно', 'НДС 16%', False), 'paper_nds_0': ('Произвольно', 'НДС 0%', True), 'paper_nds_16': ('Произвольно', 'НДС 16%', True), 'validation_empty': ('пустая форма', None, False), 'validation_no_pdf': ('без обязательного PDF', None, False), 'validation_no_lines': ('без строк закрытия', None, False)}
COMMON = [('Выбор договора', 'Акты: выбор договора', 'Договор / дополнительное соглашение'), ('Выбранная ставка НДС', 'Акты: выбор ставки НДС', 'Без НДС; НДС 0%; НДС 16% — точное соответствие выбранной ставке'), ('Переключение в произвольный режим', 'Акты: переход в произвольный режим', 'Бумажное подписание выключено; режим Произвольно'), ('Возврат в режим по форме', 'Акты: возврат в режим по форме', 'Режим По форме после Произвольно'), ('Бумажное подписание фиксирует произвольный режим', 'Акты: блокировка режима при бумажном подписании', 'Бумажное подписание включено; Произвольно выбрано, обе радиокнопки недоступны'), ('Выбранный режим формирования', 'Акты: выбранный режим формирования', 'По форме / Произвольно — соответствие сценарию'), ('Состояние бумажного подписания', 'Акты: состояние бумажного подписания', 'Переключатель включён / выключен по сценарию'), ('Заполнение даты акта', 'Акты: заполнение даты', 'Дата акта — текущая дата'), ('Заполнение номера акта', 'Акты: заполнение номера', 'Уникальный номер тестового акта'), ('Заполнение периода закрытия', 'Акты: заполнение периода закрытия', 'Начало — текущая дата; конец — через 30 дней'), ('Заполнение строки закрытия', 'Акты: заполнение строки закрытия', 'Наименование, статья расходов, тип, дата, количество 1, цена 1000; режим По форме'), ('Ввод суммы без НДС', 'Акты: ввод суммы без НДС', 'Произвольно: сумма без НДС 100000'), ('Ввод суммы с НДС', 'Акты: ввод суммы с НДС', 'Произвольно: 100000 для Без НДС и 0%; 116000 для 16%'), ('Сумма формы: manualAmountWithoutVat', 'Акты: проверка суммы без НДС в форме', 'Прочитанное значение суммы без НДС = 100000'), ('Сумма формы: manualAmountWithVat', 'Акты: проверка суммы с НДС в форме', 'Прочитанное значение суммы с НДС соответствует ставке: 100000 / 116000'), ('Загрузка PDF', 'Акты: загрузка PDF документа', 'Режим Произвольно; PDF-файл акта; имя файла видно после загрузки'), ('Создание документа', 'Акты: создание и открытие карточки', 'Кнопка Создать; переход на карточку /documents/acts/<id>'), ('Карточка: Тип документа', 'Акты: тип документа в карточке', 'АВР / КС-2 / Ф-2В соответствует созданному типу'), ('Карточка: Номер акта', 'Акты: номер в карточке', 'Номер совпадает с введённым'), ('Карточка: Ставка НДС', 'Акты: ставка НДС в карточке', 'Ставка совпадает с выбранной'), ('Карточка: Режим', 'Акты: режим в карточке', 'По форме / Произвольно совпадает с выбранным'), ('Карточка: Бумажное подписание', 'Акты: бумажное подписание в карточке', 'Да / Нет соответствует переключателю'), ('Карточка: Дата акта', 'Акты: дата в карточке', 'Дата совпадает с введённой'), ('Карточка: период', 'Акты: период в карточке', 'Начало и конец периода совпадают с введёнными'), ('Карточка: сумма Без НДС', 'Акты: сумма без НДС в карточке', 'Произвольно: сохранённая сумма без НДС = 100000'), ('Карточка: сумма С НДС', 'Акты: сумма с НДС в карточке', 'Произвольно: сохранённая сумма с НДС = 100000 / 116000'), ('Статус нового акта', 'Акты: статус нового акта', 'Статус созданной карточки — Черновик'), ('Маршрут согласования', 'Акты: настройка маршрута согласования', 'Этап маршрута; согласующий Алдажаров — поиск Алд'), ('Указание подписантов', 'Акты: сохранение подписантов', 'Заказчик Бейсембаев; контрагент Алдажаров; подтверждение сохранения'), ('Отправка на согласование', 'Акты: отправка на согласование', 'Действие отправки; ожидаемый статус На согласовании'), ('Согласование акта', 'Акты: согласование', 'Подтверждение согласования; статус На подписании / Подписан'), ('Подписание', 'Акты: подписание двумя аккаунтами через ЭЦП', 'Электронный сценарий; две подписи; финальный статус Подписан'), ('Подписание', 'Акты: завершение бумажного подписания', 'Бумажный сценарий без NCALayer; финальный статус Подписан')]
WORKFLOW_KEYS = {'Маршрут согласования', 'Указание подписантов', 'Отправка на согласование', 'Согласование акта', 'Подписание'}
NEGATIVE_KEYS = {'validation_empty': 'Валидация: пустая форма', 'validation_no_pdf': 'Валидация: обязательный PDF', 'validation_no_lines': 'Валидация: обязательные строки закрытия'}
PREPARATION_KEYS = [r[0] for r in COMMON[:10]]
CARD_KEYS = [r[0] for r in COMMON[17:24]] + ['Статус нового акта']

def scenario_name(act_type, scenario):
    mode, vat, paper = SCENARIOS[scenario]
    label = ACT_TYPES[act_type]
    if scenario in NEGATIVE_KEYS:
        return f'{label}: валидация — {mode}'
    return f'{label}: создание — {mode.lower()}, {vat}, ' + ('бумажное' if paper else 'электронное')

CORE_ACT_SCENARIOS = {
    'avr': {'default', 'arbitrary_nds_0', 'paper_nds_16', 'validation_empty', 'validation_no_pdf', 'validation_no_lines'},
    'ks2': {'nds_0', 'arbitrary_nds_16', 'paper_mode', 'validation_empty', 'validation_no_pdf', 'validation_no_lines'},
    'f2b': {'nds_16', 'form_arbitrary', 'paper_nds_0', 'validation_empty', 'validation_no_pdf', 'validation_no_lines'},
}

def checklist_rows():
    rows = [(name, fields) for _, name, fields in COMMON]
    for act_type in ACT_TYPES:
        for scenario, (mode, vat, paper) in SCENARIOS.items():
            if scenario not in CORE_ACT_SCENARIOS[act_type]:
                continue
            if scenario in NEGATIVE_KEYS:
                fields = {'validation_empty': 'Все обязательные поля пустые; создание заблокировано с валидацией', 'validation_no_pdf': 'Договор, дата, номер, период, суммы заполнены; PDF отсутствует; создание заблокировано', 'validation_no_lines': 'Договор, дата, номер, период заполнены; строки закрытия отсутствуют; создание заблокировано'}[scenario]
            else:
                fields = f"Тип {ACT_TYPES[act_type]}; {mode}; {vat}; бумажное {('Да' if paper else 'Нет')}; договор, дата, номер, период; "
                fields += 'строка закрытия' if mode == 'По форме' else 'суммы 100000 без НДС, ' + ('116000' if vat == 'НДС 16%' else '100000') + ' с НДС, PDF'
                fields += '; сверка сохранённой карточки и статуса Черновик. Результат относится к созданию.'
            rows.append((scenario_name(act_type, scenario), fields))
    return rows

def parse_act_results(output, task_map=None):
    statuses, reasons = ({}, {})

    def add(name, ok, context, reason=''):
        statuses[name] = statuses.get(name, True) and ok
        if not ok:
            message = context + ': ' + (reason or 'проверка не пройдена')
            old = reasons.get(name, '')
            if message not in old:
                reasons[name] = (old + '; ' + message).strip('; ')
    for line in output.splitlines():
        if not line.startswith('ACT_RESULT '):
            continue
        result = json.loads(line[len('ACT_RESULT '):])
        act_type, scenario = (result['type'], result['scenario'])
        if act_type not in ACT_TYPES or scenario not in SCENARIOS:
            raise ValueError(f'Неизвестный тип/сценарий актов: {act_type}/{scenario}')
        checks = result['checks']
        if not isinstance(checks, dict) or any((type(v) is not bool for v in checks.values())):
            raise ValueError('ACT_RESULT.checks должен содержать только булевы результаты')
        context = f'{ACT_TYPES[act_type]}/{scenario}'
        errors = result.get('fail_reasons', {})
        negative = scenario in NEGATIVE_KEYS
        full_flow = result.get('workflow_started', False) and (not result.get('creation_only', False))
        for source, title, _ in COMMON:
            if source not in checks:
                continue
            if source in WORKFLOW_KEYS and (not full_flow):
                continue
            if negative and source == 'Создание документа':
                continue
            if source == 'Подписание':
                if SCENARIOS[scenario][2] != (title == 'Акты: завершение бумажного подписания'):
                    continue
            add(title, checks[source], context, errors.get(source, ''))
        name = scenario_name(act_type, scenario)
        if negative:
            validation = NEGATIVE_KEYS[scenario]
            ok = checks.get(validation) is True and bool(checks) and all(checks.values())
            reason = errors.get(validation) or errors.get('Выполнение сценария', 'валидация не подтверждена')
        else:
            required = PREPARATION_KEYS + CARD_KEYS + ['Создание документа']
            if SCENARIOS[scenario][0] == 'Произвольно':
                required += [r[0] for r in COMMON[11:16]] + [r[0] for r in COMMON[24:26]]
            else:
                required += ['Заполнение строки закрытия']
            missing = [key for key in required if checks.get(key) is not True]
            ok = result.get('created') is True and (not missing)
            reason = '; '.join((key + ': ' + errors.get(key, 'результат отсутствует или неуспешен') for key in missing))
        if scenario in CORE_ACT_SCENARIOS[act_type]:
            add(name, ok, context, reason)
    return (list(statuses.items()), reasons)

MODULE_CONFIG = {
    "test-akt.py": {
        "row_range": (142, 210),
        "result_format": "acts",
        "tasks": {name: name for name, _ in checklist_rows()},
    },
    "gpr_test.py": {
        "row_range": (119, 139),
        "result_format": "gpr",
        "tasks": {
            "01": 'Вход в раздел ГПР',
            "02": 'Элементы страницы списка ГПР',
            "03": 'Фильтры этапов проектов',
            "04": 'Переключение вида «Сетка/Лист»',
            "05": 'Поиск проектов и очистка поиска',
            "06": 'Форма создания ГПР: открытие, крестик и отмена',
            "07": 'Создание ГПР: валидация пустой формы',
            "08": 'Создание ГПР',
            "09": 'Карточка созданного ГПР',
            "10": 'Изменение причины версии ГПР',
            "11": 'Открытие графика, вкладки и обновление',
            "12": 'Добавление строки графика',
            "13": 'История графика и возврат к карточке',
            "14": 'Маршрут ГПР: этап и согласующий',
            "15": 'Назначение утверждающего ГПР',
            "16": 'Обсуждение ГПР: комментарий и вкладка «История»',
            "17": 'Редактирование ГПР: открытие и отмена',
            "18": 'Отправка ГПР на согласование',
            "19": 'Согласование ГПР первым пользователем',
            "20": 'Утверждение ГПР и подписание ЭЦП',
            "21": 'Наличие созданного ГПР в списке проекта',
        },
    },
    "waybill_workflow_new_design.py": {
        "row_range": (45, 54),
        "tasks": {
            "бумажное подписание (без эцп)": "Бумажное подписание (без ЭЦП)",
            "ставка ндс: без ндс": "Ставка НДС: Без НДС",
            "ставка ндс: ндс 0%": "Ставка НДС: НДС 0%",
            "режим формирования: по форме": "Режим формирования: По форме",
            "подписание эцп": "Подписание ЭЦП",
            "материалы": "Заполнение материалов",
            "маршрут": "Маршрут согласования",
            "подписанты": "Указание подписантов",
            "создана": "Создание документа",
            "создан": "Создание документа",
        },
    },
    "contract_workflow_new_design.py": {
        "row_range": (57, 76),
        "tasks": {
            "сценарий: предоплата": "Сценарий: Предоплата",
            "сценарий: открытый договор": "Сценарий: Открытый договор",
            "сценарий: бартер": "Сценарий: Бартер",
            # "договор услуг и поставки" ДО просто "договор услуг" —
            # иначе короткая фраза перехватит длинную.
            "тип договора: договор услуг и поставки": "Тип договора: Договор услуг и поставки",
            "тип договора: договор услуг": "Тип договора: Договор услуг",
            "тип договора: импорт": "Тип договора: Импорт",
            "тип оплаты: выдача наличных": "Тип оплаты: Выдача наличных",
            "тип оплаты: постоплата (под гарантию)": "Тип оплаты: Постоплата (под гарантию)",
            "тип оплаты: постоплата (под залог)": "Тип оплаты: Постоплата (под залог)",
            "тип оплаты: частичные платежи": "Тип оплаты: Частичные платежи",
            "подписывается бумажно: выключено": "Подписывается бумажно: выключено",
            "документ из шаблона: выключено": "Документ из шаблона: выключено (ручная загрузка PDF)",
            "ставка ндс: ндс 0%": "Ставка НДС: НДС 0%",
            "ставка ндс: без ндс": "Ставка НДС: Без НДС",
            "подписание эцп": "Подписание ЭЦП",
            "маршрут": "Маршрут согласования",
            "подписанты": "Указание подписантов",
            "документ": "Прикрепление документа",  # общее слово — намеренно в конце
            "создана": "Создание документа",
            "создан": "Создание документа",
        },
    },
    "invoice_workflow_ecp.py": {
        "row_range": (79, 87),
        "tasks": {
            # "под гарантию"/"под залог" ДО просто "постоплата" —
            # иначе короткая фраза перехватит длинную.
            "тип оплаты: постоплата (под гарантию)": "Тип оплаты: Постоплата (под гарантию)",
            "тип оплаты: постоплата (под залог)": "Тип оплаты: Постоплата (под залог)",
            "тип оплаты: постоплата": "Тип оплаты: Постоплата",
            "тип оплаты: предоплата (100%)": "Тип оплаты: Предоплата (100%)",
            "тип оплаты: частичные платежи": "Тип оплаты: Частичные платежи",
            "предмет": "Указание предмета/платежа",
            "маршрут": "Маршрут согласования",
            "создана": "Создание документа",
            "создан": "Создание документа",
            # ВАЖНО: по договорённости для Счёта "Подписание ЭЦП" в
            # чек-лист больше не пишем вообще (кнопка нестабильно
            # находилась на этом статусе) — ключевое слово намеренно
            # убрано, строка останется незаполненной, это ожидаемо.
        },
    },
}

RESULT_LINE = re.compile(r"^(.+?):\s*([✓✗])\s*$")
REASON_LINE = re.compile(r"^\[ПРИЧИНА\]\s*(.+?):\s*(.+)$")


GPR_RESULT_LINE = re.compile(r"^\[(OK|FAIL)\s*\](?:\(некрит\.\))?\s+(\d{2})\s+.+$")


def parse_gpr_results(output: str, task_map: dict):
    """Читает только нумерованные строки итогового отчёта GprTest.report().

    Промежуточные [OK] OK не являются результатами отдельных проверок.
    Невыполненные после остановки шаги не получают выдуманный статус.
    """
    statuses = {}
    reasons = {}
    pending_failure = None
    for line in output.splitlines():
        match = GPR_RESULT_LINE.match(line.strip())
        if match:
            status, number = match.groups()
            if number not in task_map:
                raise ValueError(f"Неизвестный шаг ГПР в отчёте: {number}")
            task_name = task_map[number]
            passed = status == "OK"
            # При повторе отчёта не превращаем уже зафиксированный FAIL в OK.
            statuses[task_name] = statuses.get(task_name, True) and passed
            pending_failure = task_name if not passed else None
        elif pending_failure:
            if line.startswith("        ") and line.strip():
                reasons[pending_failure] = line.strip()
            pending_failure = None
    return list(statuses.items()), reasons


def run_and_collect(script_path: str, task_map: dict, result_format="standard", script_args=()):
    print(f"Запускаю {script_path} ...")
    result = subprocess.run(
        [sys.executable, script_path, *script_args], cwd=ROOT_DIR,
        capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    output = result.stdout + "\n" + result.stderr
    console_log = LOGS_DIR / f"{Path(script_path).stem}_console_{datetime.now():%Y%m%d_%H%M%S}_{uuid.uuid4().hex[:8]}.txt"
    console_log.write_text(output, encoding="utf-8")
    print("Полный лог:", console_log)
    print(output[-3000:])  # хвост вывода для контроля глазами

    if result_format == "acts":
        return parse_act_results(output, task_map)

    if result_format == "gpr":
        return parse_gpr_results(output, task_map)

    findings = []
    reasons = {}  # {task_name: "текст причины"} — только для провалов

    for line in output.splitlines():
        stripped = line.strip()

        rm = REASON_LINE.match(stripped)
        if rm:
            raw_name, reason_text = rm.group(1).strip(), rm.group(2).strip()
            # Строки [ПРИЧИНА] пишутся самими скриптами уже готовым
            # названием проверки (тем же, что в чек-листе) — точное
            # совпадение с task_map.values(), без префиксного поиска.
            for task_name in task_map.values():
                if task_name.lower() == raw_name.lower():
                    reasons[task_name] = reason_text
                    break
            continue

        m = RESULT_LINE.match(stripped)
        if not m:
            continue
        label, mark = m.group(1).strip().lower(), m.group(2)
        for prefix, task_name in task_map.items():
            if prefix in label:
                findings.append((task_name, mark == "✓"))
                break

    return findings, reasons


def _clean_reason(reason: str) -> str:
    if not reason:
        return ""
    cleaned = str(reason).split("Stacktrace:")[0]
    cleaned = cleaned.split("; For documentation")[0]
    cleaned = cleaned.split(" (Session info:")[0]
    cleaned = re.sub(r"https?://\S+", "", cleaned)
    cleaned = cleaned.replace("Message: element click intercepted: ", "")
    cleaned = cleaned.replace("Message: ", "")
    cleaned = re.sub(r"TimeoutException:\s*$", "Превышено время ожидания (таймаут)", cleaned)
    cleaned = cleaned.strip().rstrip(":")
    return cleaned.strip()[:180]


def send_telegram_summary(script_name: str, findings: list, reasons: dict,
                          *, skipped=(), error="", sheet_error="", screenshot=None):
    """Common summary and delivery for workflow modules, including Finance."""
    module_label = MODULE_LABELS.get(os.path.basename(script_name), script_name)
    total_checks = len(findings) + len(skipped)
    passed_checks = sum(bool(ok) for _, ok in findings)
    failed_items = [(name, reasons.get(name)) for name, ok in findings if not ok]

    if findings and not failed_items and not skipped and not error and (not sheet_error or sheet_error == "FileNotFoundError"):
        lines = [f"✅ <b>Автотест: {escape(module_label)} — УСПЕШНО</b> ({passed_checks}/{total_checks})", ""]
    else:
        emoji = "🔥" if (failed_items or error) else "⚠️"
        title = "ЕСТЬ ОШИБКИ" if (failed_items or error) else "ВЫПОЛНЕН НЕ ПОЛНОСТЬЮ"
        lines = [f"{emoji} <b>Автотест: {escape(module_label)} — {title}</b> ({passed_checks}/{total_checks} успешно)", ""]

    if error:
        lines.append("❌ <b>Ошибка запуска:</b> " + escape(_clean_reason(error)))
    if sheet_error and sheet_error != "FileNotFoundError":
        lines.append("⚠️ <b>Google Sheets:</b> " + escape(_clean_reason(sheet_error)))

    lines.append("<b>Этапы сценария:</b>")
    idx = 1
    for name, ok in findings:
        if ok:
            lines.append(f"{idx}. ✅ {escape(name)}")
        else:
            reason = reasons.get(name)
            clean = _clean_reason(reason)
            lines.append(f"{idx}. ❌ {escape(name)}" + (f" — <i>{escape(clean)}</i>" if clean else ""))
        idx += 1

    for name in skipped:
        lines.append(f"{idx}. ⏸ {escape(name)} (пропущен)")
        idx += 1

    if not findings and not skipped and not error:
        lines.append("Нет результатов выполненных проверок. Подробности в локальном логе.")

    current = ""
    for line in lines:
        if len(current) + len(line) + 1 > 3800:
            tg_send(current)
            current = ""
        current += ("\n" if current else "") + line
    if current:
        tg_send(current)

    # Finance passes a screenshot from the current run explicitly.
    if failed_items or error:
        if screenshot is None:
            script_dir = os.path.dirname(os.path.abspath(script_name)) or "."
            screenshot = _latest_debug_screenshot(script_dir)
        if screenshot:
            tg_photo(screenshot, caption=f"📸 Последний скриншот: {module_label}")



from datetime import datetime
from html import escape
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid
def contacts_checks(script_path=None):
    candidates = [
        Path(script_path).parent / 'contacts_checks.json' if script_path else None,
        ROOT_DIR / 'tests' / 'contacts' / 'contacts_checks.json',
        Path(__file__).resolve().parent / 'contacts_checks.json'
    ]
    for p in candidates:
        if p and p.is_file():
            return json.loads(p.read_text(encoding='utf-8'))
    raise FileNotFoundError('Не найден contacts_checks.json')
CONTACTS_ROW_RANGE = (213, 237)

def parse_contacts_results(output, run_id):
    lines = [line[len('CONTACTS_RESULT '):] for line in output.splitlines() if line.startswith('CONTACTS_RESULT ')]
    if len(lines) != 1:
        raise ValueError('Ожидался ровно один итог CONTACTS_RESULT')
    payload = json.loads(lines[0])
    if payload.get('version') != 1 or payload.get('run_id') != run_id:
        raise ValueError('Неверная версия или идентификатор прогона')
    results = payload.get('results')
    if not isinstance(results, list) or len(results) != 25:
        raise ValueError('Итог должен содержать все 25 проверок, включая пропуски')
    ids = [r.get('id') for r in results]
    if any((type(i) is not int for i in ids)) or sorted(ids) != list(range(1, 26)):
        raise ValueError('Пропущены/повторены номера проверок')
    if any((r.get('status') not in ('PASS', 'FAIL', 'SKIP') or not isinstance(r.get('reason', ''), str) for r in results)):
        raise ValueError('Недопустимый статус/причина')
    return sorted(results, key=lambda r: r['id'])

def contacts_findings_for_sheet(results, script_path=None):
    checks = contacts_checks(script_path)
    return [('Контакты: ' + checks[r['id'] - 1]['name'], r['status'] == 'PASS') for r in results if r['status'] != 'SKIP']

def contacts_summary(results, script_path=None):
    checks = contacts_checks(script_path)
    total_count = len(results)
    passed_count = sum(1 for r in results if r['status'] == 'PASS')
    failed = [r for r in results if r['status'] == 'FAIL']
    skipped = [r for r in results if r['status'] == 'SKIP']

    if not failed and not skipped:
        lines = [f"✅ <b>Автотест: Контакты — УСПЕШНО</b> ({passed_count}/{total_count})", ""]
    else:
        icon = '🔥' if failed else '⚠️'
        title = 'ЕСТЬ ОШИБКИ' if failed else 'ВЫПОЛНЕН НЕ ПОЛНОСТЬЮ'
        lines = [f"{icon} <b>Автотест: Контакты — {title}</b> ({passed_count}/{total_count} успешно)", ""]

    lines.append("<b>Этапы сценария:</b>")
    for idx, r in enumerate(results, 1):
        name = escape(checks[r['id'] - 1]['name'])
        st = r['status']
        reason = _clean_reason(r.get('reason', ''))
        if st == 'PASS':
            lines.append(f"{idx}. ✅ {name}")
        elif st == 'FAIL':
            lines.append(f"{idx}. ❌ {name}" + (f" — <i>{escape(reason)}</i>" if reason else ""))
        else:
            lines.append(f"{idx}. ⏸ {name}" + (f" — <i>{escape(reason)}</i>" if reason else " (пропущен)"))

    messages = []
    current = ""
    for line in lines:
        if len(current) + len(line) + 1 > 3800:
            messages.append(current)
            current = ""
        current += ("\n" if current else "") + line
    if current:
        messages.append(current)
    return messages

def contacts_current_screenshot(results, run_id):
    root = (SCREENS_DIR / 'contacts' / run_id).resolve()
    for r in reversed(results):
        if r['status'] != 'FAIL' or not r.get('screenshot'):
            continue
        path = Path(r['screenshot']).resolve()
        if path.parent == root and path.suffix == '.png' and path.is_file():
            return str(path)
    return None

def contacts_stream(command, cwd, env, log_path, timeout=1800):
    """Stream progress immediately, preserving the complete machine-readable log."""
    import threading
    timed_out = threading.Event()
    chunks = []
    with subprocess.Popen(command, cwd=cwd, env=env, stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT, text=True, encoding='utf-8',
                          errors='replace', bufsize=1) as process:
        def expire():
            if process.poll() is None:
                timed_out.set()
                process.kill()
        timer = threading.Timer(timeout, expire)
        timer.daemon = True
        timer.start()
        try:
            with open(log_path, 'w', encoding='utf-8') as log:
                for line in process.stdout:
                    chunks.append(line)
                    log.write(line)
                    log.flush()
                    if not line.startswith('CONTACTS_RESULT '):
                        print(line, end='', flush=True)
            code = process.wait()
            if timed_out.is_set():
                raise subprocess.TimeoutExpired(command, timeout)
            return subprocess.CompletedProcess(command, code, ''.join(chunks), '')
        finally:
            timer.cancel()
            if process.poll() is None:
                process.kill()
            process.wait()


def run_contacts(script_path, args, report_results, tg_send, tg_photo):
    run_id = uuid.uuid4().hex
    env = dict(os.environ, CONTACTS_RUN_ID=run_id, PYTHONIOENCODING='utf-8')
    script_path = Path(script_path).resolve()
    log_path = LOGS_DIR / f'contacts_log_{datetime.now():%Y%m%d_%H%M%S}_{run_id[:8]}.txt'
    try:
        completed = contacts_stream([sys.executable, '-u', str(script_path), *args], ROOT_DIR, env, log_path)
        output = completed.stdout + '\n' + completed.stderr
        results = parse_contacts_results(output, run_id)
        if completed.returncode not in (0, 1) or (completed.returncode != 0 and all((r['status'] == 'PASS' for r in results))):
            raise ValueError(f'Код завершения {completed.returncode} противоречит итогам')
    except Exception as exc:
        message = '❌ <b>Автотест: Контакты</b>\nНет достоверного полного отчёта: ' + escape(str(exc)[:500])
        print(message)
        tg_send(message)
        return 2
    findings = contacts_findings_for_sheet(results, script_path)
    try:
        report_results(findings, row_range=CONTACTS_ROW_RANGE)
    except Exception as exc:
        print('Не удалось записать результаты в Google Sheets:', type(exc).__name__)
        tg_send('⚠️ <b>Контакты: результаты не записаны в Google Sheets</b>\nЛокальный отчёт сохранён.')
        for message in contacts_summary(results, script_path):
            tg_send(message)
        return 2
    for message in contacts_summary(results, script_path):
        tg_send(message)
    screenshot = contacts_current_screenshot(results, run_id)
    if screenshot:
        tg_photo(screenshot, caption='📸 Последний скриншот: Контакты')
    print('Полный лог:', log_path)
    return 0 if all((r['status'] == 'PASS' for r in results)) else 1


# Финансы: единый отчёт, без повторной отправки из дочернего скрипта.
def validate_workflow_results(payload, run_id, expected):
    if payload.get('run_id') != run_id:
        raise ValueError('Отчёт относится к другому запуску')
    rows = payload.get('results')
    if not isinstance(rows, list):
        raise ValueError('Нет списка результатов автотеста')
    seen = set()
    for row in rows:
        if (not isinstance(row, dict) or row.get('name') not in expected
                or type(row.get('ok')) is not bool or row['name'] in seen
                or not isinstance(row.get('reason', ''), str)):
            raise ValueError('Недостоверный или повторный результат автотеста')
        seen.add(row['name'])
    if not isinstance(payload.get('error', ''), str):
        raise ValueError('Неверный формат ошибки запуска')
    return rows, [name for name in expected if name not in seen]






def run_structured_workflow(script_path, args, module_key, checks_file, row_range):
    for stream_name in ('stdout', 'stderr'):
        stream = getattr(sys, stream_name, None)
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8', errors='replace')
    script = Path(script_path).resolve()
    checks_candidate = script.parent / checks_file
    if not checks_candidate.exists():
        checks_candidate = ROOT_DIR / 'tests' / script.parent.name / checks_file
    if not checks_candidate.exists():
        checks_candidate = ROOT_DIR / checks_file
    if not checks_candidate.exists():
        checks_candidate = Path(__file__).resolve().parent / checks_file
    expected = json.loads(checks_candidate.read_text(encoding='utf-8'))
    selective_quality = False
    if module_key == 'QUALITY':
        from quality_selection import fixed_only, selected_quality_checks
        try:
            expected = selected_quality_checks(expected, args)
        except ValueError as exc:
            send_telegram_summary(script.name, [], {}, skipped=[], error=str(exc))
            return 2
        selective_quality = fixed_only(args)
    run_id = uuid.uuid4().hex
    result_path = LOGS_DIR / f'{script.stem}_results_{run_id}.json'
    log_path = LOGS_DIR / f'{script.stem}_console_{run_id}.txt'
    pp_dirs = [str(ROOT_DIR), str(ROOT_DIR / 'core'), str(ROOT_DIR / 'config'), str(script.parent)]
    if os.environ.get('PYTHONPATH'):
        pp_dirs.append(os.environ['PYTHONPATH'])
    env = dict(os.environ, PYTHONIOENCODING='utf-8', PYTHONPATH=os.pathsep.join(pp_dirs))
    env.update({module_key + '_MANAGED': '1', module_key + '_RUN_ID': run_id,
                module_key + '_RESULT_PATH': str(result_path)})
    env.pop(module_key + '_NO_RUN', None)
    rows, skipped, payload = [], ([] if selective_quality else expected), {}
    run_error = sheet_error = ''
    try:
        completed = contacts_stream([sys.executable, '-u', str(script), *args], ROOT_DIR, env,
                                    log_path, timeout=7200)
        payload = json.loads(result_path.read_text(encoding='utf-8'))
        rows, skipped = validate_workflow_results(payload, run_id, expected)
        run_error = payload.get('error', '')
        if completed.returncode not in (0, 1) or (completed.returncode == 1 and not run_error and all(r['ok'] for r in rows)):
            run_error = f'Код завершения {completed.returncode}; см. лог {log_path.name}'
    except Exception as exc:
        run_error = f'{type(exc).__name__}: нет достоверного полного отчёта; см. {log_path.name}'
    findings = [(row['name'], row['ok']) for row in rows]
    if findings:
        try:
            written = report_results(findings, row_range=row_range)
            if not written or written.get('written') != len(findings):
                sheet_error = 'VerificationError'
        except Exception as exc:
            sheet_error = type(exc).__name__
    screenshot = ""
    if payload.get('screenshot'):
        shot_path = Path(payload['screenshot']).resolve()
        if shot_path.parent == SCREENS_DIR.resolve() and shot_path.name.startswith('debug_') and shot_path.is_file():
            screenshot = str(shot_path)
    reasons = {row['name']: row.get('reason', '') for row in rows if not row['ok']}
    delivery_error = False
    try:
        send_telegram_summary(script.name, findings, reasons, skipped=skipped,
                              error=run_error, sheet_error=sheet_error, screenshot=screenshot)
    except Exception as exc:
        delivery_error = True
        print('Ошибка общего обработчика Telegram:', type(exc).__name__, flush=True)
    print('Лог:', log_path)
    print('Результаты:', result_path)
    if run_error or sheet_error or delivery_error:
        return 2
    return 1 if skipped or any(not r['ok'] for r in rows) else 0


def run_finance(script_path, args):
    return run_structured_workflow(script_path, args, 'FINANCE', 'finance_checks.json', (240, 266))


def run_smeta(script_path, args):
    return run_structured_workflow(script_path, args, 'SMETA', 'smeta_checks.json', (269, 289))


def run_passport(script_path, args):
    return run_structured_workflow(script_path, args, 'PASSPORT', 'passport_checks.json', (291, 303))


def run_supply(script_path, args):
    return run_structured_workflow(script_path, args, 'SUPPLY', 'supply_checks.json', (305, 330))


def run_quality(script_path, args):
    return run_structured_workflow(script_path, args, 'QUALITY', 'quality_checks.json', (332, 366))


def run_discussions(script_path, args):
    return run_structured_workflow(script_path, args, 'DISCUSSIONS', 'discussions_checks.json', (369, 386))


def run_wiki(script_path, args):
    return run_structured_workflow(script_path, args, 'WIKI', 'wiki_checks.json', (389, 399))


def run_news(script_path, args):
    return run_structured_workflow(script_path, args, 'NEWS', 'news_checks.json', (402, 418))


def run_manager(script_path, args):
    return run_structured_workflow(script_path, args, 'MANAGER', 'manager_checks.json', (421, 436))


def main():
    if len(sys.argv) >= 2 and os.path.basename(sys.argv[1]).lower() == "panelrukovoditelya.py":
        raise SystemExit(run_manager(sys.argv[1], sys.argv[2:]))
    if len(sys.argv) >= 2 and os.path.basename(sys.argv[1]).lower() == "news.py":
        raise SystemExit(run_news(sys.argv[1], sys.argv[2:]))
    if len(sys.argv) >= 2 and os.path.basename(sys.argv[1]).lower() == "wiki.py":
        raise SystemExit(run_wiki(sys.argv[1], sys.argv[2:]))
    if len(sys.argv) >= 2 and os.path.basename(sys.argv[1]).lower() == "obsuzhdenie.py":
        raise SystemExit(run_discussions(sys.argv[1], sys.argv[2:]))
    if len(sys.argv) >= 2 and os.path.basename(sys.argv[1]).lower() == "quality.py":
        raise SystemExit(run_quality(sys.argv[1], sys.argv[2:]))
    if len(sys.argv) >= 2 and os.path.basename(sys.argv[1]).lower() == "supply.py":
        raise SystemExit(run_supply(sys.argv[1], sys.argv[2:]))
    if len(sys.argv) >= 2 and os.path.basename(sys.argv[1]).lower() == "pasportprojects.py":
        raise SystemExit(run_passport(sys.argv[1], sys.argv[2:]))
    if len(sys.argv) >= 2 and os.path.basename(sys.argv[1]).lower() == "smeta.py":
        raise SystemExit(run_smeta(sys.argv[1], sys.argv[2:]))
    if len(sys.argv) >= 2 and os.path.basename(sys.argv[1]).lower() == "finance.py":
        raise SystemExit(run_finance(sys.argv[1], sys.argv[2:]))
    if len(sys.argv) >= 2 and os.path.basename(sys.argv[1]) == "contacts_test.py":
        raise SystemExit(run_contacts(sys.argv[1], sys.argv[2:], report_results, tg_send, tg_photo))
    if len(sys.argv) < 2:
        print("Использование: py run_workflow_and_report.py <файл_скрипта.py> [аргументы автотеста]")
        return

    script_path = sys.argv[1]
    script_name = os.path.basename(script_path)
    config = MODULE_CONFIG.get(script_name)

    if config is None:
        print(f"Не знаю, к какому модулю относится '{script_name}'. "
              f"Добавь его в MODULE_CONFIG в этом файле.")
        return

    findings, reasons = run_and_collect(
        script_path, config["tasks"], config.get("result_format", "standard"), sys.argv[2:]
    )

    if not findings:
        print("Не нашёл ни одной строки с итогами в выводе — сверь MODULE_CONFIG и формат отчёта.")
        tg_send(f"❌ <b>Автотест: {MODULE_LABELS.get(script_name, script_name)}</b>\n"
                f"Не нашёл ни одной строки с итогами в выводе скрипта — "
                f"возможно, упал раньше, чем успел что-то залогировать.")
        return

    # Пакетная запись всех находок ОДНИМ прогоном — раньше здесь был
    # цикл с report_result() на каждую строку, что при нескольких
    # сценариях подряд (много находок за раз) упиралось в лимит
    # Google Sheets API (429 Quota exceeded).
    report_results(findings, row_range=config["row_range"])

    send_telegram_summary(script_name, findings, reasons)


if __name__ == "__main__":
    main()
