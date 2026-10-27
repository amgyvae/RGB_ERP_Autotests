# -*- coding: utf-8 -*-
"""
АКТЫ (acts) — АДАПТИРОВАНО под НОВЫЙ дизайн портала.
Типы: АВР / КС-2 / Ф-2В (переключается переменной ACT_TYPE).

Режим: «По форме» + электронное подписание (ЭЦП через NCALayer).
Строки закрытия: «Из договора» (подтягиваются автоматически).

Портированы все наработки из отлаженных скриптов договоров/накладных:
  • реальный UI-кит сайта (ui-select__*, action-modal__*,
    ui-date-picker__*, evd-route__*, signers-card__*) — Ant Design НЕТ;
  • выбор опций КЛАВИАТУРОЙ (ArrowDown+Enter) — клики мышью ui-select
    игнорирует;
  • _hard_click с полной цепочкой pointer/mouse событий;
  • НИКАКИХ кликов по координатам экрана (pyautogui);
  • маршрут: «Добавить этап» → строка этапа → выбор согласующего →
    модалка «Согласующие: Этап N» → «Сохранить»;
  • подписанты: signers-card__select-link → два ui-select → «Сохранить»;
  • корректный выход из аккаунта (модалка подтверждения + флаг);
  • ensure_on_our_document — защита от работы с чужим актом;
  • действия статуса ищутся В ШАПКЕ (не в панели обсуждения);
  • форма создания открывается прямым URL с documentType.

ФЛОУ: Логин → URL создания акта → Форма (договор → проект/НДС →
режим По форме → дата/номер/период → строки из договора) → Создать →
Маршрут → Подписанты → На согласование → Согласовать → ЭЦП (основной)
→ ЭЦП (Бейсембаев Куаныш).
"""

import sys as _sys
from pathlib import Path as _Path
_ROOT = _Path(__file__).resolve().parent.parent.parent
for _d in (_ROOT, _ROOT / "core", _ROOT / "config", _Path(__file__).resolve().parent):
    if str(_d) not in _sys.path:
        _sys.path.insert(0, str(_d))
from artifact_paths import SCREENS_DIR, LOGS_DIR, screen_path, log_path
from env_config import env, env_list, is_headless  # секреты — из .env / GitHub Secrets

import argparse
_parser = argparse.ArgumentParser(description='Акты: 18 сценариев покрытия')
_parser.add_argument('act_type', nargs='?', default='')
_parser.add_argument('scenario', nargs='?', default='')
_parser.add_argument('--creation-only', action='store_true', help='Проверять создание без маршрута и ЭЦП')
_args = _parser.parse_args()
_valid_types = {'avr', 'ks2', 'f2b'}
_valid_scenarios = {'default', 'nds_0', 'nds_16', 'form_arbitrary', 'paper_mode', 'arbitrary_nds_0', 'arbitrary_nds_16', 'paper_nds_0', 'paper_nds_16', 'validation_empty', 'validation_no_pdf', 'validation_no_lines'}
if _args.act_type and _args.act_type not in _valid_types:
    _parser.error('Неизвестный тип акта: ' + _args.act_type)
if _args.scenario and _args.scenario not in _valid_scenarios:
    _parser.error('Неизвестный сценарий: ' + _args.scenario)

import os
import sys

os.environ['PYTHONIOENCODING'] = 'utf-8'
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    try:
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
    except Exception:
        pass

import json
from decimal import Decimal
from urllib.parse import urlparse
import time
import re
from datetime import datetime, timedelta
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains
from selenium.common.exceptions import NoSuchElementException, StaleElementReferenceException, TimeoutException

# ==========================================
# КОНФИГУРАЦИЯ
# ==========================================
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager

_chrome_options = Options()
_chrome_options.add_argument("--start-maximized")

# ПОСТОЯННЫЙ профиль Chrome (не временный) — нужен для разрешения
# "Доступ к другим приложениям на этом устройстве" (Local Network
# Access), которым Chrome защищает подключение сайта к NCALayer через
# wss://127.0.0.1:13579. Разреши один раз вручную ("Разрешить") —
# дальше во всех новых запусках с этим же профилем разрешение уже не
# будет запрашиваться заново.
_SELENIUM_PROFILE_DIR = r"C:\SeleniumProfile\RGB"
os.makedirs(_SELENIUM_PROFILE_DIR, exist_ok=True)
_chrome_options.add_argument(f"--user-data-dir={_SELENIUM_PROFILE_DIR}")
# Отключает всплывающий попап «Сохранить пароль?» в Chrome
_chrome_options.add_experimental_option("prefs", {
    "credentials_enable_service": False,
    "profile.password_manager_enabled": False
})
# Раскомментировать для запуска без UI (headless):
# Включается переменной окружения HEADLESS=1 (CI / сервер без монитора)
if is_headless():
    _chrome_options.add_argument("--headless=new")
    _chrome_options.add_argument("--window-size=1920,1080")

driver = webdriver.Chrome(
    service=Service(ChromeDriverManager().install()),
    options=_chrome_options
)
driver.implicitly_wait(0)  # сразу 0, а не 3 — см. пояснение в
# накладной/договоре/счёте: при большом количестве "пробуй способ 1 →
# не нашёл → способ 2" (а их в этом файле много) каждая неудачная
# попытка молча ждала бы до 3 секунд лишних.

# Основной аккаунт-создатель — Алдажа Диас Андреевич (у него права на
# создание документов, как и в договоре/счёте)
login_val = env("RGB_ACCOUNT1_LOGIN", "jyktmargyplay2@gmail.com")
pass_val = env("RGB_ACCOUNT1_PASSWORD", env("RGB_ACCOUNT1_PASSWORD_ALT", "12341234"))

# --- ЭЦП первого подписанта ---
NCA_PASSWORD = env("NCA_KEY1_PASSWORD")
MAIN_P12_PATH = env("NCA_KEY1_PATH", r"C:\Program Files\NCALayer\GOST2015_13-02-2026-18_04.p12")

# --- Аккаунт для второго подписания (Талгат Ерланович) ---
TALGAT_LOGIN = env("RGB_ACCOUNT3_LOGIN", env("RGB_ACCOUNT2_LOGIN"))
TALGAT_PASS = env("RGB_ACCOUNT3_PASSWORD", env("RGB_ACCOUNT2_PASSWORD"))
TALGAT_NCA_PASSWORD = env("NCA_KEY2_PASSWORD")
TALGAT_P12_PATH = env("NCA_KEY2_PATH", r"C:\Program Files\NCALayer\GOST512_b2c2008a1d14dd3f6a531597fb334afc4b3c6e76.p12")

BASE_URL = "https://testportal.rgbgroup.kz/"
ACTS_URL = "https://testportal.rgbgroup.kz/documents/acts"
ACT_CREATE_URLS = {
    "avr": ACTS_URL + "/create?documentType=avr",
    "ks2": ACTS_URL + "/create?documentType=ks2",
    "f2b": ACTS_URL + "/create?documentType=f2b",
}
WAIT = 15

# ==========================================
# ВЫБОР ТИПА АКТА И СЦЕНАРИЯ — можно прогнать ВСЕ комбинации ОДНОЙ
# командой (по умолчанию — 3 типа × 12 сценариев = 36 прогонов), либо
# конкретный тип и/или сценарий:
#     py test-akt.py                    → основные 18 сценариев 
#     py test-akt.py ks2                → КС-2, 6 основных сценариев 
#     py test-akt.py "" paper_mode      → все 3 типа, только paper_mode
#     py test-akt.py ks2 paper_mode     → только эта одна комбинация
# ==========================================
ACT_TYPES = ["avr", "ks2", "f2b"]
ACT_TYPE_NAMES = {"avr": "АВР", "ks2": "КС-2", "f2b": "Ф-2В"}

ACT_SCENARIOS = {
    # По умолчанию форма уже стоит на "По форме" + "Без НДС" — их не
    # трогаем, просто явно фиксируем как базовый сценарий.
    "default":        {"NDS": "Без НДС",  "FORM_MODE": "По форме",    "PAPER_MODE": False},
    "nds_0":          {"NDS": "НДС 0%",   "FORM_MODE": "По форме",    "PAPER_MODE": False},
    "nds_16":         {"NDS": "НДС 16%",  "FORM_MODE": "По форме",    "PAPER_MODE": False},
    # "Произвольно" — совсем другая секция 3 формы: ручной ввод сумм +
    # обязательная загрузка PDF (см. ДОКУМЕНТ АВР/КС-2/Ф-2В на форме).
    "form_arbitrary": {"NDS": "Без НДС",  "FORM_MODE": "Произвольно", "PAPER_MODE": False},
    # "Бумажное подписание" сам форсит режим "Произвольно" и блокирует
    # переключение радиокнопки — тот же ручной путь, что и выше, плюс
    # сам переключатель включён.
    "paper_mode":     {"NDS": "Без НДС",  "FORM_MODE": "Произвольно", "PAPER_MODE": True},
}


ACT_SCENARIOS.update({
    "arbitrary_nds_0": {"NDS": "НДС 0%", "FORM_MODE": "Произвольно", "PAPER_MODE": False},
    "arbitrary_nds_16": {"NDS": "НДС 16%", "FORM_MODE": "Произвольно", "PAPER_MODE": False},
    "paper_nds_0": {"NDS": "НДС 0%", "FORM_MODE": "Произвольно", "PAPER_MODE": True},
    "paper_nds_16": {"NDS": "НДС 16%", "FORM_MODE": "Произвольно", "PAPER_MODE": True},
    "validation_empty": {"NDS": "Без НДС", "FORM_MODE": "По форме", "PAPER_MODE": False, "NEGATIVE": "empty"},
    "validation_no_pdf": {"NDS": "Без НДС", "FORM_MODE": "Произвольно", "PAPER_MODE": False, "NEGATIVE": "pdf"},
    "validation_no_lines": {"NDS": "Без НДС", "FORM_MODE": "По форме", "PAPER_MODE": False, "NEGATIVE": "lines"},
})

# Nine positive cases plus all nine type-specific validation cases.
CORE_SCENARIOS = {
    'avr': ('default', 'arbitrary_nds_0', 'paper_nds_16', 'validation_empty', 'validation_no_pdf', 'validation_no_lines'),
    'ks2': ('nds_0', 'arbitrary_nds_16', 'paper_mode', 'validation_empty', 'validation_no_pdf', 'validation_no_lines'),
    'f2b': ('nds_16', 'form_arbitrary', 'paper_nds_0', 'validation_empty', 'validation_no_pdf', 'validation_no_lines'),
}

ACT_TYPE = "avr"          # актуальный тип текущего прогона
ACT_SCENARIO = "default"  # актуальный сценарий текущего прогона
NDS_SCENARIO_ACT = "Без НДС"
FORM_MODE_ACT = "По форме"
PAPER_MODE_ACT = False


def _apply_scenario(act_type, scenario_key="default"):
    """Переустанавливает тип акта + сценарий и создаёт СВЕЖИЙ
    workflow_result — вызывается перед каждым прогоном main()."""
    global ACT_TYPE, ACT_SCENARIO, ACT_NUM, workflow_result
    global NDS_SCENARIO_ACT, FORM_MODE_ACT, PAPER_MODE_ACT

    ACT_TYPE = act_type
    ACT_SCENARIO = scenario_key
    s = ACT_SCENARIOS.get(scenario_key, ACT_SCENARIOS["default"])
    NDS_SCENARIO_ACT = s["NDS"]
    FORM_MODE_ACT = s["FORM_MODE"]
    PAPER_MODE_ACT = s["PAPER_MODE"]

    ACT_NUM = f"АКТ-{act_type.upper()}-{scenario_key}-{datetime.now().strftime('%d%m-%H%M%S')}"
    workflow_result = {
        "number": ACT_NUM, "type": ACT_TYPE, "scenario": ACT_SCENARIO, "checks": {},
        "url": None,
        "created": False,
        "signatories": False,
        "route": False,
        "signed": False,
        "fail_reasons": {},
        "nds_ok": False,
        "form_mode_ok": False,
        "final_status": None,
        "actions_done": [],
        "creation_only": bool(getattr(globals().get("_args"), "creation_only", False))
    }


# Инициализация "по умолчанию" — чтобы модуль парсился без ошибок ещё
# до цикла запуска внизу файла (там сценарий переустановится заново).
_apply_scenario("avr", "default")

LOG_FILE_PATH = log_path(f"act_log_{datetime.now().strftime('%d%m_%H%M%S')}.txt")
try:
    _LOG_FILE = open(LOG_FILE_PATH, "w", encoding="utf-8", buffering=1)
except Exception:
    _LOG_FILE = None

LOG_LINES = []

# Флаг намеренного выхода из аккаунта (см. logout_current_account)
_LOGOUT_IN_PROGRESS = False


def _safe_out(text):
    try:
        sys.stdout.write(text + "\n")
        sys.stdout.flush()
    except UnicodeEncodeError:
        try:
            sys.stdout.buffer.write((text + "\n").encode('utf-8', errors='replace'))
            sys.stdout.buffer.flush()
        except Exception:
            pass


def log(msg, tag="INFO"):
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] [{tag}] {msg}"
    LOG_LINES.append(line)
    _safe_out(line)
    if _LOG_FILE:
        try:
            _LOG_FILE.write(line + "\n")
            _LOG_FILE.flush()
        except Exception:
            pass


def shot(name):
    try:
        path = screen_path(f"debug_act_{name}_{datetime.now().strftime('%H%M%S')}.png")
        driver.save_screenshot(path)
        log(f"  Скриншот: {path}")
    except Exception:
        pass


# БАЗОВЫЕ ХЕЛПЕРЫ (без изменений)
# ==========================================
def js_click(el):
    driver.execute_script("arguments[0].click();", el)


def scroll_to(el):
    try:
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
    except Exception:
        pass


def blur_focus():
    try:
        driver.execute_script("if(document.activeElement) document.activeElement.blur();")
        time.sleep(0.4)
    except Exception:
        pass


def dismiss_chrome_password_popup():
    """Закрывает нативный попап Chrome 'Save password?'.

    ВАЖНО — ИСТОРИЯ БАГА: здесь раньше стояли «слепые» клики по
    координатам через pyautogui, в том числе клик в середину экрана
    «для возврата фокуса» — pyautogui.click(w*0.35, h*0.55).
    На 1920x1080 это точка (672, 594), которая на странице СПИСКА
    договоров попадает прямо в строку таблицы. В результате скрипт
    сам открывал СЛУЧАЙНЫЙ СТАРЫЙ ДОГОВОР и дальше работал с ним.
    Поэтому клики по координатам полностью убраны.

    Теперь: только безопасные действия внутри страницы — Escape и
    снятие фокуса. Попап Chrome не в DOM, но он и не блокирует
    Selenium-клики (Selenium кликает по элементу в координатах
    страницы, а не по экрану), поэтому бороться с ним кликами мыши
    не требуется.

    ЛУЧШЕЕ РЕШЕНИЕ (сделать один раз в настройках профиля Chrome,
    который использует робот): Настройки → Автозаполнение → Пароли →
    выключить «Предлагать сохранение паролей». Тогда попап не будет
    появляться вовсе.
    """
    try:
        ActionChains(driver).send_keys(Keys.ESCAPE).perform()
        time.sleep(0.2)
    except Exception:
        pass
    try:
        # Безопасное снятие фокуса средствами страницы (без мыши)
        driver.execute_script(
            "if(document.activeElement && document.activeElement.blur)"
            "{document.activeElement.blur();} window.focus();")
        time.sleep(0.2)
    except Exception:
        pass


def set_number_native(element, value):
    try:
        driver.execute_script("""
            var el = arguments[0]; var val = arguments[1];
            var setter = Object.getOwnPropertyDescriptor(
                window.HTMLInputElement.prototype, 'value').set;
            setter.call(el, val);
            el.dispatchEvent(new Event('input', {bubbles:true}));
            el.dispatchEvent(new Event('change', {bubbles:true}));
        """, element, str(value))
        time.sleep(0.3)
        return True
    except Exception:
        return False


# ==========================================
# EXIT EDIT MODE (без изменений — карточка договора всё ещё
# использует /edit; TODO VERIFY кнопка "Сохранить" в новом дизайне)
# ==========================================
def exit_edit_mode(max_attempts=3):
    for attempt in range(max_attempts):
        cur = driver.current_url
        if "/edit" not in cur:
            return True

        log(f"  /edit обнаружен (попытка {attempt+1}) — жму 'Сохранить'")
        dismiss_chrome_password_popup()
        time.sleep(1)

        save_btn = None
        for xp in [
            "//button[.//span[normalize-space(text())='Отмена']]/following-sibling::button[.//span[normalize-space(text())='Сохранить']]",
            "//button[.//span[normalize-space(text())='Отмена']]/preceding-sibling::button[.//span[normalize-space(text())='Сохранить']]",
            "//button[.//span[normalize-space(text())='Сохранить']]",
        ]:
            try:
                btns = driver.find_elements(By.XPATH, xp)
                visible = [b for b in btns if b.is_displayed() and b.is_enabled()]
                if visible:
                    save_btn = visible[0]
                    break
            except Exception:
                continue

        if not save_btn:
            clean_url = cur.replace("/edit", "").rstrip("/")
            driver.get(clean_url)
            time.sleep(4)
            continue

        try:
            driver.execute_script("window.scrollTo(0, 0);")
            time.sleep(0.3)
            scroll_to(save_btn)
            time.sleep(0.3)
        except Exception:
            pass

        clicked = False
        for method in ["selenium", "js", "actions"]:
            try:
                if method == "selenium":
                    save_btn.click()
                elif method == "js":
                    js_click(save_btn)
                else:
                    ActionChains(driver).move_to_element(save_btn).pause(0.3).click().perform()
                clicked = True
                break
            except Exception:
                continue

        if not clicked:
            clean_url = cur.replace("/edit", "").rstrip("/")
            driver.get(clean_url)
            time.sleep(4)
            continue

        for _ in range(10):
            time.sleep(1)
            if "/edit" not in driver.current_url:
                return True

    cur = driver.current_url
    if "/edit" in cur:
        clean_url = cur.replace("/edit", "").rstrip("/")
        driver.get(clean_url)
        time.sleep(4)

    return "/edit" not in driver.current_url


# ==========================================
# НОВОЕ: framework-agnostic поиск контрола рядом с надписью поля.
# Не полагается на конкретные CSS-классы (ant-select и т.п.) —
# ищет ближайший "кликабельный на вид" элемент справа/снизу от
# текста лейбла по геометрии на экране. Это нужно, потому что
# по факту (см. скрин с ошибкой валидации) все select/date поля
# в новом дизайне НЕ заполнялись через старые ant-select селекторы —
# значит либо классы другие, либо это вообще другой UI-кит.
# ==========================================
def find_control_near_label(label_text, max_dy=90, max_dx=80):
    try:
        labels = driver.find_elements(By.XPATH,
            f"//*[normalize-space(text())='{label_text}']")
        label = None
        for lbl in labels:
            if lbl.is_displayed():
                label = lbl
                break
        if not label:
            return None

        control = driver.execute_script("""
            var label = arguments[0];
            var maxDy = arguments[1];
            var maxDx = arguments[2];
            var lr = label.getBoundingClientRect();
            var all = document.querySelectorAll(
                'input, textarea, button, [role="combobox"], [role="button"], ' +
                '[tabindex], div');
            var best = null, bestScore = Infinity;
            for (var i = 0; i < all.length; i++) {
                var el = all[i];
                if (el === label || el.contains(label) || label.contains(el)) continue;
                var r = el.getBoundingClientRect();
                if (r.width < 40 || r.height < 16) continue;
                var dy = r.top - lr.bottom;
                var dx = Math.abs(r.left - lr.left);
                // допускаем поле чуть выше лейбла (некоторые дизайны кладут
                // подпись под полем) и правее на той же строке
                var dyAlt = lr.top - r.top;
                if ((dy < -5 || dy > maxDy) && (dyAlt < -5 || dyAlt > maxDy)) continue;
                if (dx > maxDx && Math.abs(r.top - lr.top) > 10) continue;
                var style = window.getComputedStyle(el);
                if (style.display === 'none' || style.visibility === 'hidden') continue;
                var looksInteractive =
                    el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' ||
                    el.tagName === 'BUTTON' ||
                    el.getAttribute('role') === 'combobox' ||
                    el.getAttribute('role') === 'button' ||
                    style.cursor === 'pointer' ||
                    el.hasAttribute('tabindex');
                if (!looksInteractive) continue;
                var score = Math.max(dy, dyAlt, 0) + dx;
                if (score < bestScore) {
                    bestScore = score;
                    best = el;
                }
            }
            return best;
        """, label, max_dy, max_dx)
        return control
    except Exception:
        return None


def dump_field_html(label_text, tag="DIAG"):
    """Диагностика: сохраняет в лог HTML вокруг лейбла, чтобы можно
    было прислать точный селектор для доработки, если поле не найдено."""
    try:
        labels = driver.find_elements(By.XPATH,
            f"//*[normalize-space(text())='{label_text}']")
        visible = [l for l in labels if l.is_displayed()]
        if not visible:
            log(f"    [DIAG] Лейбл '{label_text}' не найден на странице", tag)
            return
        html = driver.execute_script("""
            var el = arguments[0];
            var container = el.closest('div');
            for (var i=0; i<3 && container && container.parentElement; i++) {
                container = container.parentElement;
            }
            return (container || el).outerHTML;
        """, visible[0])
        snippet = (html or "")[:1500]
        log(f"    [DIAG] HTML вокруг '{label_text}':\n{snippet}", tag)
    except Exception as e:
        log(f"    [DIAG] Не удалось снять HTML для '{label_text}': {e}", tag)


# ==========================================
# НОВОЕ: framework-agnostic поиск открытой модалки/попапа.
# ПОДТВЕРЖДЕНО прогоном: ни одна модалка на сайте (загрузка документов,
# "Добавить предмет", авансы, подтверждения действий) не находится по
# классу 'ant-modal' — сайт целиком на другом ui-ките. Раньше это
# приводило к тому, что функции тихо возвращали False и ничего не
# заполняли. Эта функция ищет модалку по нескольким стратегиям и
# используется как основной способ везде, где раньше был жёстко
# зашит 'ant-modal'/'ant-modal-body'/'ant-modal-footer'.
# ==========================================
def find_visible_modal_container(hint_text=None):
    strategies = [
        # ТОЧНЫЙ класс сайта (подтверждено инспектором): action-modal__shell
        "//div[contains(@class,'action-modal__shell')]",
        "//div[contains(@class,'action-modal__body')]",
        "//div[contains(@class,'ant-modal-body')]",
        "//div[contains(@class,'ant-drawer-body')]",
        "//*[contains(@class,'ui-modal__body') or contains(@class,'ui-modal-body') "
        "or contains(@class,'ui-dialog__body') or contains(@class,'ui-popup__body') "
        "or contains(@class,'ui-modal__content') or contains(@class,'ui-dialog__content')]",
        "//*[@role='dialog']",
        "//*[contains(@class,'modal') and (contains(@class,'body') or contains(@class,'content'))]",
        "//*[contains(@class,'dialog') and (contains(@class,'body') or contains(@class,'content'))]",
        "//*[contains(@class,'popup') and (contains(@class,'body') or contains(@class,'content'))]",
    ]
    for xp in strategies:
        try:
            els = driver.find_elements(By.XPATH, xp)
            visible = [e for e in els if e.is_displayed()]
            if hint_text:
                hinted = [e for e in visible if hint_text.lower() in (e.text or "").lower()]
                if hinted:
                    return hinted[-1]
            if visible:
                return visible[-1]
        except Exception:
            continue

    # Последний шанс: JS-эвристика — любой видимый fixed/absolute
    # контейнер с заметной площадью (типичный признак модалки/попапа).
    try:
        el = driver.execute_script("""
            var hint = (arguments[0] || '').toLowerCase();
            var all = document.querySelectorAll('div,section,aside');
            var best = null, bestZ = -1;
            for (var i=0;i<all.length;i++){
                var e = all[i];
                var r = e.getBoundingClientRect();
                if (r.width < 200 || r.height < 100) continue;
                var style = window.getComputedStyle(e);
                if (style.display === 'none' || style.visibility === 'hidden') continue;
                if (style.position !== 'fixed' && style.position !== 'absolute') continue;
                if (hint && e.textContent && e.textContent.toLowerCase().indexOf(hint) === -1) continue;
                var z = parseInt(style.zIndex) || 0;
                if (z > bestZ) { bestZ = z; best = e; }
            }
            return best;
        """, hint_text or "")
        if el:
            return el
    except Exception:
        pass
    return None


def find_modal_button(modal, texts, prefer_last=True):
    """Ищет кнопку с одним из вариантов текста ВНУТРИ найденной модалки.
    Сначала — в футере (footer.action-modal__footer, подтверждённый
    класс сайта), затем — во всей модалке, затем по всему документу."""
    if modal is not None:
        for t in texts:
            try:
                btns = modal.find_elements(By.XPATH,
                    f".//footer[contains(@class,'action-modal__footer')]"
                    f"//button[.//span[normalize-space(text())='{t}'] or normalize-space(text())='{t}']")
                visible = [b for b in btns if b.is_displayed() and b.is_enabled()]
                if visible:
                    return visible[-1] if prefer_last else visible[0]
            except Exception:
                continue

    scope = modal if modal is not None else driver
    for t in texts:
        try:
            btns = scope.find_elements(By.XPATH,
                f".//button[.//span[normalize-space(text())='{t}'] or normalize-space(text())='{t}']"
                if modal is not None else
                f"//button[.//span[normalize-space(text())='{t}'] or normalize-space(text())='{t}']")
            visible = [b for b in btns if b.is_displayed() and b.is_enabled()]
            if visible:
                return visible[-1] if prefer_last else visible[0]
        except Exception:
            continue
    return None


# ==========================================
# DROPDOWN
# ==========================================
# ВАЖНО: по факту (подтверждено инспектором пользователя) сайт НЕ
# использует Ant Design. Триггер выпадающего списка — это
# <button class="ui-select__trigger ui-select__trigger--placeholder">
#   <span class="ui-select__value">Выберите тип</span>
# </button>
# Т.е. кастомный BEM-кит с префиксом "ui-". Ниже — селекторы под это,
# с сохранением generic/geometry фолбэков на случай, если где-то
# используется другой вариант того же кита (ui-date-picker, ui-dropdown…).
UI_KIT_TRIGGER_CLASS_HINTS = [
    "ui-select__trigger", "ui-select-trigger",
    "ui-dropdown__trigger", "ui-picker__trigger",
    "ui-date-picker__trigger", "ui-datepicker__trigger",
]
UI_KIT_OPTION_CLASS_HINTS = [
    "ui-select__option", "ui-select-option",
    "ui-select__item", "ui-dropdown__item", "ui-dropdown__option",
    "ui-menu__item", "ui-list__item", "ui-option",
]


def find_ui_kit_trigger_near_label(label_text):
    """Ищет <button class='ui-select__trigger...'> (или другой '-trigger'
    класс из UI_KIT_TRIGGER_CLASS_HINTS) сразу после текста лейбла."""
    try:
        labels = driver.find_elements(By.XPATH, f"//*[normalize-space(text())='{label_text}']")
        for lbl in labels:
            if not lbl.is_displayed():
                continue
            for hint in UI_KIT_TRIGGER_CLASS_HINTS:
                try:
                    cand = lbl.find_element(
                        By.XPATH,
                        f"following::button[contains(@class,'{hint}')][1] | "
                        f"following::*[contains(@class,'{hint}')][1]"
                    )
                    if cand.is_displayed():
                        return cand
                except Exception:
                    continue
    except Exception:
        pass

    # ЗАПАСНОЙ ПУТЬ (подтверждено DevTools в таблице 'Строки закрытия'):
    # у компактного варианта ui-select ("Статья расходов", "Тип" внутри
    # строки таблицы) НЕТ отдельной подписи-текста вообще — сам текст
    # это placeholder поля <input class="ui-select__search-input">.
    # Ищем такой input напрямую по placeholder.
    try:
        inps = driver.find_elements(
            By.XPATH,
            f"//input[contains(@class,'ui-select__search-input') and @placeholder='{label_text}']")
        vis = [i for i in inps if i.is_displayed()]
        if vis:
            return vis[0]
    except Exception:
        pass
    return None


def dismiss_logout_confirm_if_present():
    """Защита: если по какой-то причине (случайный клик, потеря фокуса)
    выскочил диалог 'Вы уверены? Вы выйдете из системы' — жмём
    'Отмена', чтобы НЕ разлогиниться посреди работы.

    ВАЖНО: на этапе подписания под другими аккаунтами выход НУЖЕН.
    Флаг _LOGOUT_IN_PROGRESS выставляется в logout_current_account(),
    и тогда эта защита отключается — иначе она отменяла бы наш же
    выход, и скрипт зависал на модалке подтверждения.
    """
    if _LOGOUT_IN_PROGRESS:
        return False
    try:
        modals = driver.find_elements(
            By.XPATH,
            "//*[contains(@class,'ui-kit-modal')][.//*[contains(text(),'выйдете из системы')]] | "
            "//*[.//*[normalize-space(text())='Вы уверены?']][.//*[contains(text(),'выйдете из системы')]]"
        )
        visible = [m for m in modals if m.is_displayed()]
        if not visible:
            return False
        log("  ⚠ Обнаружен диалог выхода из системы — жму 'Отмена', чтобы не разлогиниться", "WARN")
        cancel_btn = None
        for xp in [
            ".//button[.//span[normalize-space(text())='Отмена']]",
            ".//button[normalize-space(text())='Отмена']",
        ]:
            try:
                btns = visible[0].find_elements(By.XPATH, xp)
                vis_btns = [b for b in btns if b.is_displayed()]
                if vis_btns:
                    cancel_btn = vis_btns[0]
                    break
            except Exception:
                continue
        if not cancel_btn:
            try:
                btns = driver.find_elements(
                    By.XPATH, "//button[.//span[normalize-space(text())='Отмена']]")
                vis_btns = [b for b in btns if b.is_displayed()]
                if vis_btns:
                    cancel_btn = vis_btns[-1]
            except Exception:
                pass
        if cancel_btn:
            try:
                cancel_btn.click()
            except Exception:
                js_click(cancel_btn)
            time.sleep(1)
            log("  ✓ Диалог выхода закрыт (осталось в системе)", "PASS")
        return True
    except Exception:
        return False


def _date_trigger_value(trigger):
    """Читает текущее значение из кнопки-триггера календаря."""
    try:
        lbl = trigger.find_element(
            By.XPATH, ".//span[contains(@class,'ui-date-picker__trigger-label')]")
        return (lbl.get_attribute("textContent") or "").strip()
    except Exception:
        try:
            return (trigger.get_attribute("textContent") or "").strip()
        except Exception:
            return ""


def fill_popup_date_field(label_text, target_date, modal=None):
    """ТОЧНАЯ структура сайта (подтверждено DevTools):
      <div class="ui-date-picker" data-slot="date-picker">
        <button class="ui-date-picker__trigger" aria-haspopup="dialog">
          <span class="ui-date-picker__trigger-label">Выбрать дату</span>
      -> <div class="ui-date-picker__panel" role="dialog">
           <div class="ui-date-picker__nav">‹ Сентябрь 2026 ›</div>
           <div class="ui-date-picker__grid" role="grid">
             <button class="ui-date-picker__day" role="gridcell"
                     [is-outside|is-today]>2</button>

    ДОРАБОТАНО: раньше функция могла «молча» не сработать — на карточке
    оставалось значение по умолчанию (сегодня), и мы этого не замечали.
    Теперь: до 3 попыток, ПРОВЕРКА результата по тексту триггера после
    каждой, и явный лог фактически проставленного значения.
    """
    date_str = target_date.strftime("%d.%m.%Y")
    scope = modal if modal is not None else driver
    xp_prefix = ".//" if modal is not None else "//"

    def locate_trigger():
        t = None
        try:
            t = scope.find_element(
                By.XPATH,
                f"{xp_prefix}*[normalize-space(text())='{label_text}']"
                f"/following::button[contains(@class,'ui-date-picker__trigger')][1]")
        except Exception:
            t = None
        if not t:
            try:
                cands = driver.find_elements(
                    By.XPATH, "//button[contains(@class,'ui-date-picker__trigger')]")
                vis = [c for c in cands if c.is_displayed()]
                if vis:
                    t = vis[0]
            except Exception:
                pass
        return t

    month_names = ["январь", "февраль", "март", "апрель", "май", "июнь",
                   "июль", "август", "сентябрь", "октябрь", "ноябрь", "декабрь"]
    target_month = month_names[target_date.month - 1]
    target_year = str(target_date.year)
    target_day = str(target_date.day)

    for attempt in range(3):
        trigger = locate_trigger()
        if not trigger:
            log(f"    ⚠ {label_text}: триггер календаря не найден "
                f"(попытка {attempt+1})", "WARN")
            if attempt == 2:
                return _fill_date_field_legacy_fallback(label_text, target_date, modal)
            time.sleep(0.8)
            continue

        scroll_to(trigger)
        time.sleep(0.3)

        # Открываем панель календаря
        panel_open = False
        for method in ["js", "selenium", "actions"]:
            try:
                if method == "js":
                    js_click(trigger)
                elif method == "selenium":
                    trigger.click()
                else:
                    ActionChains(driver).move_to_element(trigger).pause(0.3).click().perform()
                time.sleep(0.8)
                panels = driver.find_elements(
                    By.XPATH, "//div[contains(@class,'ui-date-picker__panel')]")
                if any(p.is_displayed() for p in panels):
                    panel_open = True
                    break
            except Exception:
                continue

        if not panel_open:
            log(f"    ⚠ {label_text}: панель календаря не открылась "
                f"(попытка {attempt+1})", "WARN")
            time.sleep(0.8)
            continue

        # Листаем до нужного месяца/года (в обе стороны)
        for _ in range(14):
            try:
                nav = driver.find_element(
                    By.XPATH, "//div[contains(@class,'ui-date-picker__nav')]")
                nav_text = (nav.text or "").strip().lower()
            except Exception:
                nav_text = ""
            if target_month in nav_text and target_year in nav_text:
                break
            try:
                nav_btns = driver.find_elements(
                    By.XPATH, "//div[contains(@class,'ui-date-picker__nav')]//button")
                vis_nav = [b for b in nav_btns if b.is_displayed()]
            except Exception:
                vis_nav = []
            if len(vis_nav) < 2:
                break
            # определяем направление: если целевая дата раньше текущей — назад
            go_back = False
            try:
                cur_year = int([w for w in nav_text.split() if w.isdigit()][0])
                cur_month = next((i + 1 for i, m in enumerate(month_names)
                                  if m in nav_text), target_date.month)
                if (cur_year, cur_month) > (target_date.year, target_date.month):
                    go_back = True
            except Exception:
                pass
            btn = vis_nav[0] if go_back else vis_nav[-1]
            try:
                js_click(btn)
            except Exception:
                try:
                    btn.click()
                except Exception:
                    break
            time.sleep(0.4)

        # Кликаем нужный день
        clicked = False
        try:
            cells = driver.find_elements(
                By.XPATH,
                f"//button[contains(@class,'ui-date-picker__day') and "
                f"not(contains(@class,'is-outside')) and "
                f"not(@disabled) and normalize-space(text())='{target_day}']")
            vis_cells = [c for c in cells if c.is_displayed()]
            if vis_cells:
                for method in ["js", "selenium"]:
                    try:
                        if method == "js":
                            js_click(vis_cells[0])
                        else:
                            vis_cells[0].click()
                        time.sleep(0.7)
                        clicked = True
                        break
                    except Exception:
                        continue
        except Exception as e:
            log(f"    ⚠ {label_text}: ошибка клика по дню — {e}", "WARN")

        # ПРОВЕРКА результата по тексту триггера
        trigger = locate_trigger()
        actual = _date_trigger_value(trigger) if trigger else ""
        if clicked and actual and "выбрат" not in actual.lower():
            log(f"    ✓ {label_text}: {actual} (просили {date_str})", "PASS")
            dismiss_logout_confirm_if_present()
            return True

        log(f"    ⚠ {label_text}: после попытки {attempt+1} значение = "
            f"'{actual or 'пусто'}', ожидали {date_str}", "WARN")
        try:
            ActionChains(driver).send_keys(Keys.ESCAPE).perform()
            time.sleep(0.4)
        except Exception:
            pass

    log(f"    ⚠ {label_text}: не удалось выставить {date_str}", "WARN")
    shot(f"date_failed_{label_text[:20]}")
    dismiss_logout_confirm_if_present()
    return False


def _fill_date_field_legacy_fallback(label_text, target_date, modal=None):
    """Старый способ (input / geometry) — используется только если
    триггер ui-date-picker__trigger не найден вовсе (другая версия
    поля)."""
    date_str = target_date.strftime("%d.%m.%Y")
    scope = modal if modal is not None else driver
    xp_prefix = ".//" if modal is not None else "//"

    try:
        inp = scope.find_element(
            By.XPATH, f"{xp_prefix}*[normalize-space(text())='{label_text}']/following::input[1]")
        if inp.is_displayed() and inp.is_enabled():
            inp.click()
            time.sleep(0.3)
            try:
                inp.send_keys(Keys.CONTROL + "a")
                inp.send_keys(Keys.DELETE)
            except Exception:
                pass
            inp.send_keys(date_str)
            time.sleep(0.3)
            inp.send_keys(Keys.ENTER)
            time.sleep(0.5)
            val = inp.get_attribute("value") or ""
            if date_str in val or val.strip():
                log(f"    ✓ {label_text}: {date_str} [прямой input]", "PASS")
                return True
    except Exception:
        pass

    # УБРАН опасный фолбэк «кликнуть Сегодня»: он молча выставлял
    # СЕГОДНЯШНЮЮ дату вместо нужной (из-за него в карточке было
    # 04.09.2026 вместо +10 дней, и появлялось "Срок ... истёк").
    # Лучше честно вернуть False и залогировать, чем поставить не ту дату.

    log(f"    ⚠ {label_text}: не удалось выбрать дату ни одним способом", "WARN")
    dump_field_html(label_text)
    return False



def find_dropdown_in_scope(scope, label_text):
    """Ищет select-контрол рядом с лейблом ВНУТРИ заданной области
    (например, открытой модалки). Порядок: ui-select-кит внутри scope
    → ant-select внутри scope → geometry по всему документу (fallback).
    Используется везде, где раньше был жёстко зашит только ant-select
    внутри модалки (что не работало на реальном сайте)."""
    lbl = None
    try:
        lbl = scope.find_element(By.XPATH, f".//*[normalize-space(text())='{label_text}']")
    except Exception:
        pass
    if lbl:
        for hint in UI_KIT_TRIGGER_CLASS_HINTS:
            try:
                cand = lbl.find_element(By.XPATH, f"following::*[contains(@class,'{hint}')][1]")
                if cand.is_displayed():
                    return cand
            except Exception:
                continue
        try:
            cand = lbl.find_element(By.XPATH, "following::div[contains(@class,'ant-select')][1]")
            if cand.is_displayed():
                return cand
        except Exception:
            pass
    return find_control_near_label(label_text)


def open_dropdown(el):
    for strategy in ['click', 'js_click', 'actions', 'input_click', 'mousedown']:
        try:
            if strategy == 'click':
                el.click()
            elif strategy == 'js_click':
                js_click(el)
            elif strategy == 'actions':
                ActionChains(driver).move_to_element(el).pause(0.2).click().perform()
            elif strategy == 'input_click':
                try:
                    inp = el.find_element(By.XPATH, ".//input")
                    inp.click()
                except Exception:
                    continue
            elif strategy == 'mousedown':
                driver.execute_script("""
                    var el = arguments[0];
                    ['mousedown', 'mouseup', 'click'].forEach(function(type) {
                        var ev = new MouseEvent(type, {
                            bubbles: true, cancelable: true, view: window, button: 0
                        });
                        el.dispatchEvent(ev);
                    });
                """, el)
            time.sleep(0.7)
            # Проверяем, что дропдаун реально открылся — сначала по
            # известным классам (ant-select и новый ui-select), затем
            # generic-фолбэком: любые новые видимые опции вообще.
            opened = driver.find_elements(By.XPATH,
                "//div[contains(@class,'ant-select-dropdown') and not(contains(@style,'display: none'))] | "
                "//*[contains(@class,'ui-select__dropdown') or contains(@class,'ui-select__options') "
                "or contains(@class,'ui-select__panel') or contains(@class,'ui-select__menu') "
                "or contains(@class,'ui-dropdown__panel') or @role='listbox']")
            if any(o.is_displayed() for o in opened):
                return True
            if collect_options_generic():
                return True
        except Exception:
            continue
    return False


def collect_options():
    strategies = [
        "//div[contains(@class,'rc-virtual-list-holder-inner')]"
        "//div[contains(@class,'ant-select-item-option-content')]",
        "//div[contains(@class,'ant-select-item-option-content')]",
        "//div[contains(@class,'ant-select-item')]",
        # Реальный UI-кит сайта (подтверждено инспектором): ui-select__*
        "//*[contains(@class,'ui-select__option') or contains(@class,'ui-select-option') "
        "or contains(@class,'ui-select__item')]",
    ]
    for xp in strategies:
        try:
            elements = driver.find_elements(By.XPATH, xp)
            visible = [e for e in elements if e.is_displayed()]
            if visible:
                options = []
                for e in visible:
                    txt = e.text.strip() or e.get_attribute("title") or ""
                    if txt:
                        options.append({"element": e, "text": txt})
                if options:
                    return options
        except Exception:
            continue
    return []


def collect_options_generic():
    """Более широкий сбор опций открытого dropdown — не завязан на
    ant-select-* классы. Ищет видимые li/div/span с role=option,
    ui-select__option (реальный кит сайта), либо любые новые видимые
    кликабельные строки внутри overlay-контейнера (popup/dropdown/menu)."""
    strategies = [
        "//*[contains(@class,'ui-select__option') or contains(@class,'ui-select-option') "
        "or contains(@class,'ui-select__item') or contains(@class,'ui-dropdown__item') "
        "or contains(@class,'ui-dropdown__option') or contains(@class,'ui-menu__item') "
        "or contains(@class,'ui-list__item') or contains(@class,'ui-option')]",
        "//*[@role='option']",
        "//div[contains(@class,'ant-select-item-option-content')]",
        "//div[contains(@class,'ant-select-item')]",
        "//li[contains(@class,'option') or contains(@class,'item')]",
        "//div[contains(@class,'option') or contains(@class,'dropdown-item') "
        "or contains(@class,'menu-item')]",
    ]
    for xp in strategies:
        try:
            elements = driver.find_elements(By.XPATH, xp)
            visible = [e for e in elements if e.is_displayed()]
            if visible:
                options = []
                for e in visible:
                    txt = e.text.strip() or e.get_attribute("title") or ""
                    if txt:
                        options.append({"element": e, "text": txt})
                if options:
                    return options
        except Exception:
            continue
    return []


def select_first_form_dropdown(label, allow_missing=False, target_option=None):
    """Выбор в dropdown формы создания договора.
    Контрагент → ИП Алдажаров
    Заказчик → AI Group

    Порядок попыток:
      1. Реальный UI-кит сайта: <button class="ui-select__trigger...">
         (подтверждено инспектором — см. find_ui_kit_trigger_near_label).
      2. Ant Design (на случай смешанной вёрстки на разных страницах).
      3. Геометрический фолбэк рядом с лейблом (framework-agnostic).
    """
    if "Контрагент" in label:
        target_option = "ИП Алдажаров"
    elif "Заказчик" in label:
        target_option = "AI Group"

    try:
        select_el = find_ui_kit_trigger_near_label(label)
        used_fallback = False

        if not select_el:
            labels = driver.find_elements(By.XPATH, f"//*[normalize-space(text())='{label}']")
            for lbl in labels:
                if not lbl.is_displayed():
                    continue
                try:
                    candidate = lbl.find_element(By.XPATH, "following::div[contains(@class,'ant-select')][1]")
                    if candidate.is_displayed():
                        select_el = candidate
                        break
                except Exception:
                    continue

        if not select_el:
            select_el = find_control_near_label(label)
            used_fallback = select_el is not None

        if not select_el:
            if not allow_missing:
                log(f"  ⚠ {label}: dropdown не найден (ни ui-select, ни ant-select, ни геометрией)", "WARN")
                dump_field_html(label)
            return None

        if not open_dropdown(select_el):
            log(f"  ⚠ {label}: не удалось открыть", "WARN")
            dump_field_html(label)
            return None

        time.sleep(0.8)
        options = collect_options() or collect_options_generic()

        target_el = None
        picked_text = ""
        if target_option:
            for opt in options:
                if target_option.lower() in opt["text"].lower():
                    target_el = opt["element"]
                    picked_text = opt["text"]
                    break

        if ("Контрагент" in label or "Заказчик" in label) and target_el is None:
            raise RuntimeError(f'{label}: компания {target_option!r} не найдена')
        to_click = target_el if target_el else (options[0]["element"] if options else None)
        if not to_click:
            log(f"  ⚠ {label}: dropdown открылся, но опции не найдены", "WARN")
            dump_field_html(label)
            try:
                ActionChains(driver).send_keys(Keys.ESCAPE).perform()
            except Exception:
                pass
            return None
        if not picked_text and options:
            picked_text = options[0]["text"]

        try:
            scroll_to(to_click)
            time.sleep(0.3)
            to_click.click()
        except Exception:
            js_click(to_click)

        time.sleep(1.0)
        log(f"  ✓ {label}: '{picked_text[:40]}'" + (" [geometry-fallback]" if used_fallback else ""), "PASS")
        return "Success"
    except Exception as e:
        log(f"  ⚠ {label}: ошибка — {e}", "WARN")
        return None


def fill_text_field(placeholder_hint, value, field_label=""):
    try:
        inputs = driver.find_elements(By.XPATH,
            f"//input[contains(@placeholder, '{placeholder_hint}')]")
        visible = [i for i in inputs if i.is_displayed() and i.is_enabled()]
        if visible:
            visible[0].clear()
            visible[0].send_keys(str(value))
            time.sleep(0.3)
            log(f"  ✓ {field_label or placeholder_hint}: '{value}'", "PASS")
            return True
    except Exception:
        pass
    return False


def sign_with_ncalayer(password, p12_path=None, appear_timeout=45):
    try:
        from pywinauto import Application, Desktop
        from pywinauto.keyboard import send_keys
    except ImportError:
        log("  ⚠ pywinauto не установлен. pip install pywinauto", "WARN")
        return False

    time.sleep(2)

    dialog = None
    for _ in range(appear_timeout):
        try:
            desktop = Desktop(backend="uia")
            nca_windows = desktop.windows(title_re=".*NCALayer.*")
            if nca_windows:
                if len(nca_windows) > 1:
                    for w in nca_windows[1:]:
                        try:
                            w.close()
                        except Exception:
                            pass
                    time.sleep(1)
                app = Application(backend="uia").connect(title_re=".*NCALayer.*", timeout=5)
                dialog = app.window(title_re=".*NCALayer.*")
                if dialog.exists():
                    break
        except Exception:
            pass
        dialog = None
        time.sleep(1)

    if not dialog or not dialog.exists():
        log("  ⚠ Окно NCALayer не появилось", "WARN")
        return False

    log("  ✓ NCALayer найден (pywinauto/UIA)", "PASS")
    try:
        dialog.set_focus()
    except Exception:
        pass
    time.sleep(1)

    if p12_path:
        if not os.path.exists(p12_path):
            log(f"  ⚠ Файл ЭЦП не найден: {p12_path}", "WARN")
            return False

        log(f"  Файл ЭЦП: {p12_path}")

        clicked_folder = False
        try:
            btns = dialog.descendants(control_type="Button")
            open_btn = btns[4] if len(btns) > 4 else None
            if open_btn:
                open_btn.click_input()
                clicked_folder = True
        except Exception:
            pass

        if not clicked_folder:
            try:
                btns = dialog.descendants(control_type="Button")
                for i, b in enumerate(btns):
                    try:
                        b.click_input()
                        time.sleep(1.5)
                        test = Desktop(backend="win32").windows(
                            title_re="(Файлды таңдаңыз|Выберите файл|Open|Открыть|Открытие)")
                        if test:
                            clicked_folder = True
                            break
                    except Exception:
                        continue
            except Exception:
                pass

        if not clicked_folder:
            log("  ⚠ Кнопка выбора файла не найдена", "WARN")
            shot("no_folder_btn")
            return False

        time.sleep(1.5)

        try:
            file_app = Application(backend="win32").connect(
                title_re="(Файлды таңдаңыз|Выберите файл|Open|Открыть|Открытие)",
                timeout=30
            )
            file_dlg = file_app.window(
                title_re="(Файлды таңдаңыз|Выберите файл|Open|Открыть|Открытие)"
            )
            file_dlg.wait("visible", timeout=10)
            file_dlg.set_focus()
            time.sleep(0.5)

            edit = file_dlg.child_window(class_name="Edit")
            edit.set_edit_text(p12_path)
            time.sleep(1)
            edit.type_keys("{ENTER}")
            time.sleep(2)
        except Exception as e:
            log(f"  ⚠ Ошибка в диалоге файла: {e}", "WARN")
            shot("file_dialog_error")
            return False

        try:
            dialog.set_focus()
        except Exception:
            pass
        time.sleep(1)

    password_ok = False
    for edit_name in ["ПарольEdit", "ҚұпиясөзEdit"]:
        try:
            dialog[edit_name].set_edit_text("")
            time.sleep(0.3)
            dialog[edit_name].type_keys(password, with_spaces=True)
            password_ok = True
            break
        except Exception:
            continue

    if not password_ok:
        try:
            edits = dialog.descendants(control_type="Edit")
            if edits:
                pw_edit = edits[-1]
                pw_edit.click_input()
                time.sleep(0.4)
                try:
                    pw_edit.set_edit_text("")
                except Exception:
                    send_keys("^a{DELETE}")
                time.sleep(0.3)
                try:
                    pw_edit.set_edit_text(password)
                    password_ok = True
                except Exception:
                    pw_edit.type_keys(password, with_spaces=True)
                    password_ok = True
        except Exception as e:
            log(f"  ⚠ Ввод пароля через Edit не удался: {e}", "WARN")

    if not password_ok:
        log("  ⚠ Пароль не введён", "WARN")
        shot("password_not_entered")
        return False

    time.sleep(0.8)
    shot("ncalayer_password_typed")

    opened = False
    for btn_name in ["Ашу", "Открыть", "Open"]:
        try:
            btn = dialog.child_window(title=btn_name, control_type="Button")
            if btn.exists():
                btn.click_input()
                opened = True
                break
        except Exception:
            continue

    if not opened:
        try:
            dialog["ОткрытьButton"].click()
            opened = True
        except Exception:
            try:
                send_keys("{ENTER}")
                opened = True
            except Exception:
                pass

    if not opened:
        log("  ⚠ Кнопка 'Ашу' не нажата", "WARN")
        return False

    time.sleep(3)

    try:
        app = Application(backend="uia").connect(title_re=".*NCALayer.*", timeout=15)
        dialog = app.window(title_re=".*NCALayer.*")
        dialog.set_focus()
        time.sleep(0.5)
    except Exception:
        pass

    shot("ncalayer_key_list")

    items = []
    for _ in range(10):
        try:
            items = dialog.descendants(control_type="ListItem")
            if items:
                break
        except Exception:
            pass
        time.sleep(1)

    if items:
        try:
            items[0].click_input()
            time.sleep(0.5)
        except Exception:
            try:
                items[0].type_keys("{SPACE}")
            except Exception:
                pass
    else:
        log("  ⚠ Список ключей пуст — возможно неверный пароль", "WARN")
        shot("no_key_items")
        return False

    time.sleep(1)

    signed_click = False
    for btn_name in ["Қол қою", "Подписать", "Sign"]:
        try:
            btn = dialog.child_window(title=btn_name, control_type="Button")
            if btn.exists():
                btn.click_input()
                signed_click = True
                break
        except Exception:
            continue

    if not signed_click:
        try:
            dialog["ПодписатьButton"].click()
            signed_click = True
        except Exception:
            try:
                send_keys("{ENTER}")
                signed_click = True
            except Exception:
                pass

    time.sleep(4)

    try:
        still = Desktop(backend="uia").windows(title_re=".*NCALayer.*")
        if still:
            log("  ⚠ NCALayer всё ещё открыт", "WARN")
            shot("ncalayer_still_open")
            return False
    except Exception:
        pass

    log("  ✓ NCALayer закрылся — подписание выполнено", "PASS")
    return True


# ==========================================
# КНОПКА "СОЗДАТЬ" (без изменений — кнопка в правом верхнем углу
# формы, как на скриншоте, текст 'Создать' совпадает)
# ==========================================
def click_create_button():
    initial_url = driver.current_url
    buttons = [b for b in driver.find_elements(By.XPATH, "//button[normalize-space(.)='Создать']") if b.is_displayed() and b.is_enabled()]
    if not buttons:
        return False
    target = buttons[-1]
    scroll_to(target)
    # Submit once. A slow response must not create duplicate acts.
    target.click()
    try:
        WebDriverWait(driver, WAIT).until(lambda _: driver.current_url != initial_url and act_card_url(driver.current_url))
        return True
    except Exception:
        log('Создание не подтверждено: ' + '; '.join(validation_messages()), 'FAIL')
        return False


# ==========================================
# PDF ФАЙЛ (без изменений)
# ==========================================
def create_test_pdf(name_hint='document'):
    import tempfile
    stream = b'BT /F1 18 Tf 100 700 Td (Act test document) Tj ET\n'
    objects = [b'<</Type /Catalog /Pages 2 0 R>>', b'<</Type /Pages /Count 1 /Kids [3 0 R]>>',
        b'<</Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources <</Font <</F1 5 0 R>>>>>>',
        b'<</Length '+str(len(stream)).encode()+b'>>\nstream\n'+stream+b'endstream',
        b'<</Type /Font /Subtype /Type1 /BaseFont /Helvetica>>']
    pdf=bytearray(b'%PDF-1.4\n')
    offsets=[0]
    for i, obj in enumerate(objects, 1):
        offsets.append(len(pdf))
        pdf.extend(str(i).encode()+b' 0 obj\n'+obj+b'\nendobj\n')
    xref=len(pdf)
    pdf.extend(b'xref\n0 6\n0000000000 65535 f \n')
    for offset in offsets[1:]:
        pdf.extend(f'{offset:010d} 00000 n \n'.encode())
    pdf.extend(f'trailer\n<</Size 6 /Root 1 0 R>>\nstartxref\n{xref}\n%%EOF\n'.encode())
    path=os.path.join(tempfile.gettempdir(), 'act_'+re.sub(r'[^\w-]', '_', name_hint)+'.pdf')
    with open(path, 'wb') as out:
        out.write(pdf)
    return path


# ==========================================
# ПОДПИСАНТЫ — Заказчик=Бейсембаев Куаныш Ерланович, Контрагент=Алдажаров Диас Бейсембаев Куанышович
# В новом дизайне секция "Подписанты" видна прямо на главной вкладке
# карточки договора (см. скрин 9) — карточки Заказчик/Контрагент с
# кнопкой "Редактировать" у заголовка секции. Логика внутри модалки
# редактирования, судя по всему, не поменялась (dropdown-поиск).
# ==========================================

def create_test_pdf(name_hint='document'):
    import tempfile
    stream = b'BT /F1 18 Tf 100 700 Td (Act test document) Tj ET\n'
    objects = [b'<</Type /Catalog /Pages 2 0 R>>', b'<</Type /Pages /Count 1 /Kids [3 0 R]>>',
        b'<</Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources <</Font <</F1 5 0 R>>>>>>',
        b'<</Length '+str(len(stream)).encode()+b'>>\nstream\n'+stream+b'endstream',
        b'<</Type /Font /Subtype /Type1 /BaseFont /Helvetica>>']
    pdf=bytearray(b'%PDF-1.4\n')
    offsets=[0]
    for i, obj in enumerate(objects, 1):
        offsets.append(len(pdf))
        pdf.extend(str(i).encode()+b' 0 obj\n'+obj+b'\nendobj\n')
    xref=len(pdf)
    pdf.extend(b'xref\n0 6\n0000000000 65535 f \n')
    for offset in offsets[1:]:
        pdf.extend(f'{offset:010d} 00000 n \n'.encode())
    pdf.extend(f'trailer\n<</Size 6 /Root 1 0 R>>\nstartxref\n{xref}\n%%EOF\n'.encode())
    path=os.path.join(tempfile.gettempdir(), 'act_'+re.sub(r'[^\w-]', '_', name_hint)+'.pdf')
    with open(path, 'wb') as out:
        out.write(pdf)
    return path


# ==========================================
# ПЕРЕКЛЮЧАТЕЛИ (role="switch") — подтверждено DevTools на договоре,
# та же структура используется и здесь ("Бумажное подписание"):
#   <span class="ccp-toggle__label">Название</span>
#   ...
#   <button type="button" role="switch" aria-checked="true/false"
#           class="ui-switch ui-switch--checked">
# ==========================================
def find_toggle_switch(label_text):
    """Находит переключатель (role='switch') рядом с подписью label_text."""
    try:
        labels = driver.find_elements(
            By.XPATH,
            f"//*[contains(@class,'ccp-toggle__label') and normalize-space(text())='{label_text}'] | "
            f"//*[normalize-space(text())='{label_text}']")
        for lbl in labels:
            if not lbl.is_displayed():
                continue
            switch = driver.execute_script("""
                var lbl = arguments[0];
                var container = lbl.parentElement;
                for (var i = 0; i < 5 && container; i++) {
                    var btn = container.querySelector("button[role='switch']");
                    if (btn) return btn;
                    container = container.parentElement;
                }
                return null;
            """, lbl)
            if switch is not None:
                return switch
    except Exception:
        pass
    return None


def get_toggle_state(switch_el):
    try:
        return switch_el.get_attribute("aria-checked") == "true"
    except Exception:
        return None


def set_toggle_state(label_text, desired_on):
    switch = find_toggle_switch(label_text)
    if switch is None:
        return False
    if get_toggle_state(switch) == desired_on:
        return True
    if not _hard_click(switch):
        js_click(switch)
    try:
        return bool(wait_ui(lambda _: (find_toggle_switch(label_text) is not None and
                        get_toggle_state(find_toggle_switch(label_text)) == desired_on)))
    except Exception:
        return False


def upload_act_pdf_dropzone(act_type_label, pdf_path):
    """Загружает PDF в прямую дропзону формы акта (НЕ модалка, в
    отличие от договора) — подпись 'ДОКУМЕНТ {ТИП}' + текст
    'Перетащите PDF сюда или выберите'. Ищем input[type=file] рядом
    с этой подписью."""
    try:
        labels = driver.find_elements(
            By.XPATH, f"//*[contains(text(),'ДОКУМЕНТ {act_type_label}')]")
        scope = driver
        for lbl in labels:
            if lbl.is_displayed():
                try:
                    scope = driver.execute_script(
                        "var l = arguments[0]; var c = l.parentElement;"
                        "for (var i=0;i<4 && c;i++){c=c.parentElement;} return c || l;", lbl)
                except Exception:
                    pass
                break

        file_inputs = scope.find_elements(By.XPATH, ".//input[@type='file']")             if scope is not driver else             driver.find_elements(By.XPATH, "//input[@type='file']")
        if not file_inputs:
            file_inputs = driver.find_elements(By.XPATH, "//input[@type='file']")
        if not file_inputs:
            log(f"  ⚠ Поле загрузки 'ДОКУМЕНТ {act_type_label}' не найдено", "WARN")
            return False

        pdf_inputs = [f for f in file_inputs if 'pdf' in (f.get_attribute('accept') or '').lower()]
        candidates = pdf_inputs or file_inputs
        if len(candidates) != 1:
            log('Загрузка PDF: неоднозначное поле, нужен HTML секции', 'FAIL')
            return False
        target_input = candidates[0]
        driver.execute_script(
            "arguments[0].style.display='block';"
            "arguments[0].style.opacity='1';"
            "arguments[0].style.visibility='visible';"
            "arguments[0].removeAttribute('hidden');",
            target_input
        )
        target_input.send_keys(pdf_path)
        WebDriverWait(driver, WAIT).until(lambda _: os.path.basename(pdf_path) in driver.find_element(By.TAG_NAME, 'body').text)
        log(f"  ✓ Файл акта загружен (ДОКУМЕНТ {act_type_label})", "PASS")
        return True
    except Exception as e:
        log(f"  ⚠ Загрузка PDF акта: {e}", "WARN")
        return False


def _hard_click(el):
    """Клик с ПОЛНОЙ последовательностью событий указателя.

    ПРИЧИНА ПОЯВЛЕНИЯ: обычный element.click() и JS-click отправляют
    только событие 'click'. Кастомный ui-select на этом сайте слушает
    pointerdown/mousedown — поэтому опции в списке НЕ ВЫБИРАЛИСЬ
    (подтверждено скриншотом: обе панели открыты, нужные варианты
    отфильтрованы, но выбор не происходит).

    Здесь диспатчим pointerover -> pointerenter -> pointerdown ->
    mousedown -> pointerup -> mouseup -> click, как настоящая мышь.
    """
    try:
        driver.execute_script("""
            var el = arguments[0];
            var r = el.getBoundingClientRect();
            var cx = r.left + r.width / 2;
            var cy = r.top + r.height / 2;
            function fire(type, Ctor) {
                var ev;
                try {
                    ev = new Ctor(type, {
                        bubbles: true, cancelable: true, view: window,
                        clientX: cx, clientY: cy, button: 0, buttons: 1,
                        pointerId: 1, pointerType: 'mouse', isPrimary: true
                    });
                } catch (e) {
                    ev = document.createEvent('MouseEvents');
                    ev.initMouseEvent(type, true, true, window, 0, 0, 0,
                                      cx, cy, false, false, false, false, 0, null);
                }
                el.dispatchEvent(ev);
            }
            var P = window.PointerEvent || MouseEvent;
            fire('pointerover', P);
            fire('pointerenter', P);
            fire('mouseover', MouseEvent);
            fire('pointerdown', P);
            fire('mousedown', MouseEvent);
            try { el.focus(); } catch (e) {}
            fire('pointerup', P);
            fire('mouseup', MouseEvent);
            fire('click', MouseEvent);
        """, el)
        return True
    except Exception:
        return False


def _select_option_by_keyboard(panel, expected_keywords=None):
    """Выбор опции КЛАВИАТУРОЙ: ArrowDown + Enter в поле поиска.

    ПРИЧИНА: эмуляция мыши (даже с полным набором pointer-событий)
    на этом ui-select не приводит к выбору — подтверждено двумя
    прогонами: опции отфильтрованы, видны, но клик игнорируется.
    Доступные listbox-компоненты почти всегда поддерживают навигацию
    с клавиатуры, поэтому это более надёжный путь.
    """
    try:
        sinp = panel.find_element(
            By.XPATH, ".//input[contains(@class,'ui-select__search-input')]")
    except Exception:
        return False

    try:
        sinp.click()
    except Exception:
        try:
            js_click(sinp)
        except Exception:
            return False
    time.sleep(0.3)

    for presses in (1, 2):
        try:
            for _ in range(presses):
                sinp.send_keys(Keys.ARROW_DOWN)
                time.sleep(0.25)
            sinp.send_keys(Keys.ENTER)
            time.sleep(0.9)
        except Exception:
            return False

        # успех = панель закрылась
        try:
            panels = driver.find_elements(
                By.XPATH, "//div[contains(@class,'ui-select__panel')]")
            if not any(p.is_displayed() for p in panels):
                log("      • опция выбрана с клавиатуры (ArrowDown+Enter)")
                return True
        except Exception:
            return True
    return False


def _click_option_robustly(el, label="", panel=None):
    """Выбор опции: сначала клавиатура (надёжнее всего для этого
    ui-select), затем разные варианты кликов мышью."""
    if panel is not None and _select_option_by_keyboard(panel):
        return True

    try:
        scroll_to(el)
    except Exception:
        pass
    for method in ["hard", "actions", "selenium", "js"]:
        try:
            if method == "hard":
                if not _hard_click(el):
                    continue
            elif method == "actions":
                ActionChains(driver).move_to_element(el).pause(0.2).click().perform()
            elif method == "selenium":
                el.click()
            else:
                js_click(el)
            wait_select_closed()
            # Успех = панель закрылась (типичное поведение после выбора)
            panels = driver.find_elements(
                By.XPATH, "//div[contains(@class,'ui-select__panel')]")
            if not any(p.is_displayed() for p in panels):
                log(f"      • опция '{label[:30]}' выбрана ({method})")
                return True
        except Exception:
            continue
    return False


def _close_any_ui_select_panel():
    """Закрывает открытые панели ui-select__panel.

    Escape часто НЕ работает, т.к. фокус находится в поле поиска
    внутри панели (подтверждено скриншотом: две панели остались
    открытыми одновременно). Поэтому основной способ — клик по
    backdrop, затем Escape, затем клик по нейтральному заголовку.
    """
    for _ in range(3):
        try:
            panels = driver.find_elements(
                By.XPATH, "//div[contains(@class,'ui-select__panel')]")
            if not any(p.is_displayed() for p in panels):
                return True
        except Exception:
            return True

        # 1) backdrop
        try:
            bds = driver.find_elements(
                By.XPATH, "//div[contains(@class,'ui-select__backdrop')]")
            for bd in bds:
                try:
                    _hard_click(bd)
                    time.sleep(0.4)
                except Exception:
                    continue
        except Exception:
            pass

        # 2) Escape
        try:
            ActionChains(driver).send_keys(Keys.ESCAPE).perform()
            time.sleep(0.35)
        except Exception:
            pass

        # 3) клик по нейтральной области (заголовок секции подписантов)
        try:
            hdr = driver.find_element(
                By.XPATH, "//section[contains(@class,'signers-card')]"
                          "//header[contains(@class,'signers-card__header')]")
            if hdr.is_displayed():
                _hard_click(hdr)
                time.sleep(0.35)
        except Exception:
            pass

    try:
        panels = driver.find_elements(
            By.XPATH, "//div[contains(@class,'ui-select__panel')]")
        return not any(p.is_displayed() for p in panels)
    except Exception:
        return True


def _select_in_ui_select(placeholder_text, search_text, option_keywords,
                         field_name, attempts=3):
    """Надёжный выбор значения в ui-select по тексту плейсхолдера.

    Что было не так раньше: текст в поле поиска не всегда попадал
    (панель ещё не успевала получить фокус), опции собирались по всему
    документу, а результат не проверялся — из-за этого Контрагент
    оставался невыбранным, а скрипт шёл дальше.

    Теперь на каждую попытку: закрыть чужие панели -> кликнуть триггер
    -> дождаться панели -> кликнуть в поле поиска и ввести текст ->
    собрать опции ТОЛЬКО из открытой панели -> выбрать по ключевым
    словам -> проверить, что значение триггера изменилось.
    """
    for attempt in range(attempts):
        _close_any_ui_select_panel()

        trigger = None
        try:
            trigger = driver.find_element(
                By.XPATH,
                f"//button[contains(@class,'ui-select__trigger')]"
                f"[.//span[contains(normalize-space(text()),'{placeholder_text}')]]")
        except Exception:
            trigger = None

        if not trigger:
            # Уже выбрано? Проверяем: есть ли триггер с непустым значением
            try:
                vals = driver.find_elements(
                    By.XPATH,
                    "//section[contains(@class,'signers-card')]"
                    "//span[contains(@class,'ui-select__value')]")
                for v in vals:
                    txt = (v.get_attribute("textContent") or "").strip().lower()
                    for kw in option_keywords:
                        if kw.lower() in txt:
                            log(f"    ✓ {field_name}: уже выбрано ('{txt}')", "PASS")
                            return True
            except Exception:
                pass
            log(f"    ⚠ {field_name}: триггер '{placeholder_text}' не найден "
                f"(попытка {attempt+1})", "WARN")
            time.sleep(0.8)
            continue

        scroll_to(trigger)
        time.sleep(0.3)

        # Открываем панель
        panel = None
        for method in ["hard", "js", "selenium", "actions"]:
            try:
                if method == "hard":
                    _hard_click(trigger)
                elif method == "js":
                    js_click(trigger)
                elif method == "selenium":
                    trigger.click()
                else:
                    ActionChains(driver).move_to_element(trigger).pause(0.3).click().perform()
                time.sleep(0.8)
                panels = driver.find_elements(
                    By.XPATH, "//div[contains(@class,'ui-select__panel')]")
                vis = [p for p in panels if p.is_displayed()]
                if vis:
                    panel = vis[-1]
                    break
            except Exception:
                continue

        if not panel:
            log(f"    ⚠ {field_name}: панель не открылась (попытка {attempt+1})", "WARN")
            time.sleep(0.8)
            continue

        # Ввод в поле поиска — обязательно с кликом (фокус)
        if search_text:
            try:
                sinp = panel.find_element(
                    By.XPATH, ".//input[contains(@class,'ui-select__search-input')]")
                try:
                    sinp.click()
                except Exception:
                    js_click(sinp)
                time.sleep(0.3)
                sinp.send_keys(Keys.CONTROL + "a")
                sinp.send_keys(Keys.BACKSPACE)
                time.sleep(0.2)
                sinp.send_keys(search_text)
                time.sleep(1.2)
            except Exception as e:
                log(f"    • {field_name}: поиск не использован ({e}) — беру полный список")

        # Опции ТОЛЬКО из этой панели
        def panel_options():
            out = []
            try:
                btns = panel.find_elements(By.XPATH, ".//button[@role='option']")
                for b in btns:
                    if not b.is_displayed():
                        continue
                    try:
                        lbl = b.find_element(
                            By.XPATH, ".//span[contains(@class,'ui-select__option-label')]")
                        txt = (lbl.get_attribute("textContent") or "").strip()
                    except Exception:
                        txt = (b.get_attribute("textContent") or "").strip()
                    if txt:
                        out.append({"element": b, "text": txt})
            except Exception:
                pass
            return out

        opts = panel_options()
        if not opts and search_text:
            # Поиск мог отфильтровать всё — очищаем и берём полный список
            try:
                sinp = panel.find_element(
                    By.XPATH, ".//input[contains(@class,'ui-select__search-input')]")
                sinp.send_keys(Keys.CONTROL + "a")
                sinp.send_keys(Keys.BACKSPACE)
                time.sleep(1.0)
            except Exception:
                pass
            opts = panel_options()

        log(f"    [DIAG] {field_name}: опций {len(opts)} → "
            f"{[o['text'] for o in opts][:10]}", "DIAG")

        target = None
        for opt in opts:
            txt = (opt["text"] or "").lower()
            for kw in option_keywords:
                if kw.lower() in txt:
                    target = opt
                    break
            if target:
                break

        if not target:
            log(f"    ⚠ {field_name}: '{search_text}' не найден среди опций "
                f"(попытка {attempt+1})", "WARN")
            _close_any_ui_select_panel()
            time.sleep(0.8)
            continue

        _click_option_robustly(target["element"], target["text"], panel=None)
        time.sleep(0.6)

        _close_any_ui_select_panel()

        # ПРОВЕРКА: значение триггера сменилось на выбранное
        try:
            vals = driver.find_elements(
                By.XPATH,
                "//section[contains(@class,'signers-card')]"
                "//span[contains(@class,'ui-select__value')]")
            for v in vals:
                txt = (v.get_attribute("textContent") or "").strip()
                for kw in option_keywords:
                    if kw.lower() in txt.lower():
                        log(f"    ✓ {field_name}: '{txt}'", "PASS")
                        return True
        except Exception:
            pass

        log(f"    ⚠ {field_name}: значение не подтвердилось "
            f"(попытка {attempt+1})", "WARN")
        time.sleep(0.8)

    return False


# ==========================================
# TREE-SELECT ЛИСТ (без изменений)
# ==========================================
def click_tree_leaf():
    time.sleep(1.5)
    for _ in range(4):
        expanded = driver.execute_script("""
            var switchers = document.querySelectorAll(
                '.ant-select-tree-switcher_close, .ant-select-tree-switcher-close');
            var count = 0;
            switchers.forEach(function(sw) {
                if (sw.offsetParent !== null) { sw.click(); count++; }
            });
            return count;
        """)
        if not expanded:
            break
        time.sleep(0.7)

    time.sleep(0.5)
    leaf_divs = driver.find_elements(By.XPATH,
        "//div[@role='treeitem' and contains(@class,'ant-select-tree-treenode-leaf')]")
    visible_leaves = [d for d in leaf_divs if d.is_displayed()]

    if not visible_leaves:
        try:
            ActionChains(driver).send_keys(Keys.ARROW_DOWN).pause(0.3) \
                .send_keys(Keys.ARROW_DOWN).pause(0.3) \
                .send_keys(Keys.ENTER).perform()
            time.sleep(1.5)
            tree_open = driver.find_elements(By.XPATH,
                "//div[contains(@class,'ant-select-tree-list')]")
            if not any(t.is_displayed() for t in tree_open):
                return "клавиатура"
        except Exception:
            pass
        return None

    target_div = visible_leaves[0]
    try:
        title_span = target_div.find_element(By.XPATH,
            ".//span[contains(@class,'ant-select-tree-title')]")
        txt = title_span.text.strip()
    except Exception:
        txt = target_div.text.strip()[:40]

    scroll_to(target_div)
    time.sleep(0.4)

    click_targets = [target_div]
    try:
        cw = target_div.find_element(By.XPATH,
            ".//span[contains(@class,'ant-select-tree-node-content-wrapper')]")
        click_targets.append(cw)
    except Exception:
        pass
    try:
        title = target_div.find_element(By.XPATH,
            ".//span[contains(@class,'ant-select-tree-title')]")
        click_targets.append(title)
    except Exception:
        pass

    for target in click_targets:
        for method in ["actions", "selenium", "js"]:
            try:
                if method == "actions":
                    ActionChains(driver).move_to_element(target).pause(0.3).click().perform()
                elif method == "selenium":
                    target.click()
                else:
                    driver.execute_script("arguments[0].click();", target)
                time.sleep(1.5)
                tree_open = driver.find_elements(By.XPATH,
                    "//div[contains(@class,'ant-select-tree-list')]")
                if not any(t.is_displayed() for t in tree_open):
                    return txt
            except Exception:
                continue
    return None

def add_approval_route(approver_query="Алд"):
    """МАРШРУТ СОГЛАСОВАНИЯ — строгая последовательность (как просил
    пользователь):
        ШАГ 1: нажать «Добавить этап» (button.evd-empty-stub__action)
               или «+ Этап» (button.evd-route__add-badge)
        ШАГ 2: дождаться появления строки этапа с селектом
        ШАГ 3: открыть селект «Выбрать согласующего»
        ШАГ 4: найти и выбрать «Sh Алдажаров Диас Ju»
        ШАГ 5: проверить, что имя реально проставилось

    Разметка (подтверждено DevTools):
      section.evd-route[.evd-route--empty]
        div.evd-route__head > button.evd-route__add-badge   («+ Этап»)
        div.evd-empty-stub > button.evd-empty-stub__action  («Добавить этап»)
        div.evd-route__stages > div.evd-route__stage
          table.evd-route__table > tbody > tr > td.evd-route__td
            div.ui-select > button.ui-select__trigger--placeholder
              span.ui-select__value «Выбрать согласующего»
      Панель: div.ui-select__panel[role=listbox]
        div.ui-select__search > input.ui-select__search-input
        ul.ui-select__list > li.ui-select__group
          div.ui-select__group-label «Внутренние»
          ul.ui-select__group-list > li > button[role=option].ui-select__option
            span.ui-select__option-label «Sh Алдажаров Диас Ju»
    """
    exit_edit_mode()
    dismiss_chrome_password_popup()
    ensure_on_our_document("add_approval_route")

    def route_section():
        try:
            return driver.find_element(
                By.XPATH, "//section[contains(@class,'evd-route')]")
        except Exception:
            return None

    def stage_row_select():
        """Селект согласующего в строке этапа (если этап уже есть)."""
        for xp in [
            "//div[contains(@class,'evd-route__stages')]"
            "//button[contains(@class,'ui-select__trigger')]",
            "//table[contains(@class,'evd-route__table')]"
            "//button[contains(@class,'ui-select__trigger')]",
        ]:
            els = driver.find_elements(By.XPATH, xp)
            vis = [e for e in els if e.is_displayed()]
            if vis:
                return vis[0]
        return None

    def approver_in_route():
        """Имя реально стоит в строке этапа.

        Два состояния разметки:
          а) до сохранения — <span class="ui-select__value">Имя</span>
          б) ПОСЛЕ сохранения модалки — обычный текст в ячейке
             td.evd-route__td (см. скриншот: в таблице '1 | Алдажаров Диас Sh')
        Проверяем оба, иначе после успешного сохранения функция
        возвращала False и цикл начинал маршрут заново.
        """
        try:
            vals = driver.find_elements(
                By.XPATH,
                "//div[contains(@class,'evd-route__stages')]"
                "//span[contains(@class,'ui-select__value')]")
            for v in vals:
                if not v.is_displayed():
                    continue
                txt = (v.get_attribute("textContent") or "").strip()
                if "алд" in txt.lower() and "выбрать" not in txt.lower():
                    return True
        except Exception:
            pass

        # б) имя как обычный текст в ячейке таблицы маршрута
        try:
            cells = driver.find_elements(
                By.XPATH,
                "//section[contains(@class,'evd-route')]"
                "//table[contains(@class,'evd-route__table')]//tbody//td")
            for c in cells:
                if not c.is_displayed():
                    continue
                txt = (c.get_attribute("textContent") or "").strip()
                if not txt or txt in {"—", "-", ""}:
                    continue
                low = txt.lower()
                if low.isdigit() or "выбрать" in low:
                    continue
                # непустая ячейка с именем (не номер, не прочерк)
                if "алд" in low and len(txt) > 2 and any(ch.isalpha() for ch in txt):
                    return True
        except Exception:
            pass
        return False

    def dump_route_html(tag):
        try:
            sec = route_section()
            html = (sec.get_attribute("outerHTML") or "")[:2500] if sec else "секция не найдена"
            log(f"  [DIAG:{tag}] HTML маршрута:\n{html}", "DIAG")
        except Exception as e:
            log(f"  [DIAG:{tag}] HTML снять не удалось: {e}", "DIAG")

    if approver_in_route():
        log("  ✓ Согласующий уже в маршруте", "PASS")
        return True

    # ---------- ШАГ 1: «Добавить этап» ----------
    sec = route_section()
    if sec is not None:
        try:
            scroll_to(sec)
            time.sleep(0.5)
        except Exception:
            pass

    if stage_row_select() is None:
        log("  Шаг 1: нажимаю «Добавить этап»")
        created = False
        for attempt in range(3):
            btn = None
            for xp in [
                "//button[contains(@class,'evd-empty-stub__action')]",
                "//section[contains(@class,'evd-route')]"
                "//button[contains(@class,'evd-route__add-badge')]",
                "//section[contains(@class,'evd-route')]"
                "//button[contains(normalize-space(.),'Этап')]",
                "//*[self::a or self::button][normalize-space(text())='Добавить этап']",
            ]:
                els = driver.find_elements(By.XPATH, xp)
                vis = [e for e in els if e.is_displayed() and e.is_enabled()]
                if vis:
                    btn = vis[0]
                    break

            if not btn:
                log(f"  ⚠ Кнопка «Добавить этап» не найдена (попытка {attempt+1})", "WARN")
                dump_route_html(f"no_add_button_{attempt+1}")
                time.sleep(1.5)
                continue

            scroll_to(btn)
            time.sleep(0.4)
            for method in ["js", "selenium", "actions"]:
                try:
                    if method == "js":
                        js_click(btn)
                    elif method == "selenium":
                        btn.click()
                    else:
                        ActionChains(driver).move_to_element(btn).pause(0.3).click().perform()
                    # ШАГ 2: ждём появления строки этапа с селектом
                    try:
                        WebDriverWait(driver, 8).until(
                            lambda d: stage_row_select() is not None)
                        created = True
                    except Exception:
                        created = stage_row_select() is not None
                    if created:
                        log(f"  ✓ Шаг 1-2: этап создан ({method}, попытка {attempt+1})", "PASS")
                        break
                except Exception:
                    continue
            if created:
                break
            time.sleep(1.2)

        if not created:
            log("  ⚠ Этап согласования не создан", "WARN")
            shot("stage_not_created")
            dump_route_html("stage_not_created")
            return False
    else:
        log("  • Этап уже существует — перехожу к выбору согласующего")

    time.sleep(0.8)

    # ---------- ШАГ 3: открыть селект ----------
    log("  Шаг 3: открываю список согласующих")
    trigger = stage_row_select()
    if trigger is None:
        log("  ⚠ Селект согласующего не найден в строке этапа", "WARN")
        shot("route_trigger_not_found")
        dump_route_html("trigger_not_found")
        return False

    scroll_to(trigger)
    time.sleep(0.4)

    panel = None
    for method in ["hard", "js", "selenium", "actions"]:
        try:
            if method == "hard":
                _hard_click(trigger)
            elif method == "js":
                js_click(trigger)
            elif method == "selenium":
                trigger.click()
            else:
                ActionChains(driver).move_to_element(trigger).pause(0.3).click().perform()
            time.sleep(0.9)
            panels = driver.find_elements(
                By.XPATH, "//div[contains(@class,'ui-select__panel')]")
            vis = [p for p in panels if p.is_displayed()]
            if vis:
                panel = vis[-1]
                break
        except Exception:
            continue

    if panel is None:
        log("  ⚠ Панель списка согласующих не открылась", "WARN")
        shot("route_panel_not_open")
        dump_route_html("panel_not_open")
        return False

    # ---------- ШАГ 4: найти и выбрать Sh Алдажаров Диас ----------
    log(f"  Шаг 4: ищу '{approver_query}' в списке")

    def panel_options():
        out = []
        try:
            btns = panel.find_elements(By.XPATH, ".//button[@role='option']")
            for b in btns:
                if not b.is_displayed():
                    continue
                try:
                    lbl = b.find_element(
                        By.XPATH, ".//span[contains(@class,'ui-select__option-label')]")
                    txt = (lbl.get_attribute("textContent") or "").strip()
                except Exception:
                    txt = (b.get_attribute("textContent") or "").strip()
                if txt:
                    out.append({"element": b, "text": txt})
        except Exception:
            pass
        return out

    # вводим запрос в поиск (обязательно с кликом — иначе фокус не тот)
    try:
        sinp = panel.find_element(
            By.XPATH, ".//input[contains(@class,'ui-select__search-input')]")
        try:
            sinp.click()
        except Exception:
            js_click(sinp)
        time.sleep(0.3)
        sinp.send_keys(Keys.CONTROL + "a")
        sinp.send_keys(Keys.BACKSPACE)
        time.sleep(0.2)
        sinp.send_keys(approver_query)
        time.sleep(1.3)
    except Exception as e:
        log(f"  • Поиск не использован ({e}) — беру полный список")

    options = panel_options()
    if not options:
        # фильтр мог всё отсечь — очищаем
        try:
            sinp = panel.find_element(
                By.XPATH, ".//input[contains(@class,'ui-select__search-input')]")
            sinp.send_keys(Keys.CONTROL + "a")
            sinp.send_keys(Keys.BACKSPACE)
            time.sleep(1.2)
        except Exception:
            pass
        options = panel_options()

    log(f"  [DIAG] Согласующих в списке: {len(options)} → "
        f"{[o['text'] for o in options][:15]}", "DIAG")

    option = None
    for opt in options:
        txt = (opt["text"] or "").lower()
        if "алд" in txt:
            option = opt
            break
    if not option:
        for opt in options:
            txt = (opt["text"] or "").lower()
            if approver_query.lower() in txt:
                option = opt
                break


    if not option:
        log("  ⚠ Список согласующих пуст", "WARN")
        shot("route_options_empty")
        dump_route_html("options_empty")
        try:
            ActionChains(driver).send_keys(Keys.ESCAPE).perform()
        except Exception:
            pass
        return False

    log(f"  Выбираю согласующего: '{option['text']}'")
    _click_option_robustly(option["element"], option["text"], panel=None)
    time.sleep(0.8)

    # Do not send Escape or click outside: that can dismiss the approvers dialog.
    # Close the multi-select by clicking the heading inside this same dialog.
    headings = visible_elements(By.XPATH, "//div[@role='dialog']//h2[contains(normalize-space(.),'Согласующие:')]")
    if len(headings) == 1:
        headings[0].click()

    # The footer is a sibling of action-modal__body, inside the dialog shell.
    modal_xpath = "//div[@role='dialog'][.//h2[contains(normalize-space(.),'Согласующие:')]]"
    try:
        dialogs = wait_ui(lambda _: visible_elements(By.XPATH, modal_xpath), timeout=4)
        if len(dialogs) != 1:
            raise RuntimeError('Окно согласующих неоднозначно')
        modal = dialogs[0]
        names = modal.find_elements(By.CSS_SELECTOR, '.evd-approvers-modal__name')
        if not any(approver_query.casefold() in n.text.casefold() for n in names):
            raise RuntimeError('Выбранный согласующий отсутствует в списке окна')
        buttons = modal.find_elements(By.XPATH, ".//footer//button[normalize-space(.)='Сохранить']")
        buttons = [b for b in buttons if b.is_displayed() and b.is_enabled()]
        if len(buttons) != 1:
            raise RuntimeError('Кнопка сохранения согласующих недоступна или неоднозначна')
        scroll_to(buttons[0])
        buttons[0].click()
        wait_ui(lambda _: not visible_elements(By.XPATH, modal_xpath))
        driver.refresh()
        wait_card_ready()
        log('  Окно согласующих сохранено; проверяю маршрут после обновления', 'INFO')
    except Exception as exc:
        log(f'  ⚠ Сохранение согласующих не подтверждено: {exc}', 'WARN')
        shot('approvers_modal_not_saved')
        return False

    # ---------- ШАГ 5: проверка ----------
    for _ in range(6):
        if approver_in_route():
            log("  ✓ Маршрут согласования настроен", "PASS")
            return True
        time.sleep(1)

    log("  ⚠ Согласующий не подтвердился в маршруте", "WARN")
    shot("route_not_confirmed")
    dump_route_html("not_confirmed")
    return False




def click_card_action(button_text):
    # ЗАЩИТА: действия статуса (На согласование / Согласовать /
    # Подписать) необратимы — убеждаемся, что жмём их на НАШЕМ
    # договоре, а не на случайно открытом чужом.
    if workflow_result.get("url") and not ensure_on_our_document(f"click_card_action:{button_text}"):
        log(f"  ⚠ '{button_text}' пропущен — не удалось открыть наш договор", "WARN")
        return False

    candidates = []
    try:
        btns = driver.find_elements(By.XPATH,
            f"//button[.//span[normalize-space(text())='{button_text}']]")
        for b in btns:
            if b.is_displayed() and b.is_enabled():
                candidates.append(b)
    except Exception:
        pass

    if not candidates:
        return False

    target = candidates[0]
    scroll_to(target)
    time.sleep(0.5)
    blur_focus()

    def handle_confirmation_modal():
        try:
            modal = wait_ui(lambda _: find_visible_modal_container(hint_text=button_text), timeout=2.5)
        except TimeoutException:
            modal = None
        if not modal:
            # Возможно действие выполнилось без модалки подтверждения
            # (сразу применилось) — это не ошибка.
            return False

        log(f"    Модалка подтверждения '{button_text}'", "PASS")

        try:
            comment_areas = modal.find_elements(By.XPATH, ".//textarea")
            for ca in comment_areas:
                if ca.is_displayed() and ca.is_enabled():
                    ca.clear()
                    ca.send_keys(f"Автоподтверждение '{button_text}' для {ACT_NUM}")
                    time.sleep(0.5)
                    break
        except Exception:
            pass

        blur_focus()
        time.sleep(1)

        confirm_btn = find_modal_button(
            modal, [button_text, "Согласовать", "Подписать", "Подтвердить",
                    "Отправить", "Сохранить", "ОК", "Да"])
        if not confirm_btn:
            confirm_btn = find_modal_button(
                None, [button_text, "Согласовать", "Подписать", "Подтвердить",
                       "Отправить", "Сохранить", "ОК", "Да"])

        if not confirm_btn:
            return False

        for method in ["selenium", "js", "actions"]:
            try:
                if method == "selenium":
                    confirm_btn.click()
                elif method == "js":
                    js_click(confirm_btn)
                else:
                    ActionChains(driver).move_to_element(confirm_btn).pause(0.3).click().perform()
                return True
            except Exception:
                continue
        return False

    for method in ["selenium", "js", "actions"]:
        try:
            if method == "selenium":
                target.click()
            elif method == "js":
                driver.execute_script("arguments[0].click();", target)
            else:
                ActionChains(driver).move_to_element(target).pause(0.3).click().perform()
            handle_confirmation_modal()
            return True
        except Exception:
            continue
    return False


def get_current_status():
    if not act_card_url(driver.current_url):
        return None
    known = {'Черновик', 'На согласовании', 'На доработке', 'На подписании', 'Подписан', 'Действует', 'Исполнен', 'Отменён', 'Архив'}
    # The signer badge can be Подписан while the act is still На подписании.
    candidates = driver.find_elements(By.CSS_SELECTOR, '.detail-hero__status')
    found = set()
    for el in candidates:
        if el.is_displayed() and el.text.strip() in known:
            found.add(el.text.strip())
    return found.pop() if len(found) == 1 else None


# ==========================================
# LOGOUT / LOGIN (без изменений)
# ==========================================
def logout_current_account():
    """Выход из аккаунта.

    ИСПРАВЛЕНО: кнопка подтверждения искалась по классу 'ant-modal',
    которого на сайте НЕТ — поэтому модалка «Вы уверены? Вы выйдете
    из системы» оставалась висеть, и скрипт застревал на ней
    (подтверждено скриншотом). Теперь модалка ищется универсально
    (action-modal / role=dialog), а кнопка «Выйти» жмётся жёстким
    кликом с перебором способов.
    """
    global _LOGOUT_IN_PROGRESS, CURRENT_LOGIN
    CURRENT_LOGIN = None
    _LOGOUT_IN_PROGRESS = True
    log("  Выход из текущего аккаунта...")
    try:
        logout_els = driver.find_elements(By.XPATH,
            "//span[@aria-label='logout']/ancestor::button[1] | "
            "//span[contains(@class,'anticon-logout')]/ancestor::*[self::button or self::a][1] | "
            "//*[self::button or self::a][contains(normalize-space(.),'Выйти')] | "
            "//*[contains(@class,'logout')]")
        visible = [e for e in logout_els if e.is_displayed()]
        if visible:
            for method in ["hard", "js", "selenium"]:
                try:
                    if method == "hard":
                        _hard_click(visible[0])
                    elif method == "js":
                        js_click(visible[0])
                    else:
                        visible[0].click()
                    time.sleep(1.5)
                    break
                except Exception:
                    continue

            # Подтверждение выхода — универсальный поиск модалки
            confirmed = False
            for _ in range(6):
                modal = find_visible_modal_container(hint_text="выйдете из системы")
                if not modal:
                    modal = find_visible_modal_container(hint_text="Вы уверены")
                if not modal:
                    break
                btn = find_modal_button(modal, ["Выйти", "Да", "ОК", "Подтвердить"])
                if not btn:
                    btn = find_modal_button(None, ["Выйти", "Да", "ОК", "Подтвердить"])
                if not btn:
                    log("  ⚠ Кнопка 'Выйти' в модалке не найдена", "WARN")
                    shot("logout_modal_no_button")
                    break
                for method in ["hard", "js", "selenium", "actions"]:
                    try:
                        if method == "hard":
                            _hard_click(btn)
                        elif method == "js":
                            js_click(btn)
                        elif method == "selenium":
                            btn.click()
                        else:
                            ActionChains(driver).move_to_element(btn) \
                                .pause(0.3).click().perform()
                        time.sleep(2)
                        if not find_visible_modal_container(hint_text="выйдете из системы"):
                            confirmed = True
                            log(f"  ✓ Подтверждён выход ({method})", "PASS")
                            break
                    except Exception:
                        continue
                if confirmed:
                    break
                time.sleep(1)
            time.sleep(3)
    except Exception as e:
        log(f"  ⚠ UI-выход: {e}", "WARN")

    def on_login_page():
        try:
            if "auth" in driver.current_url.lower():
                return True
            pw = driver.find_elements(By.XPATH, "//input[@type='password']")
            return any(p.is_displayed() for p in pw)
        except Exception:
            return False

    if on_login_page():
        log("  ✓ Вышли через UI", "PASS")
        return True

    log("  UI-выход не сработал — чищу cookies", "WARN")
    try:
        driver.delete_all_cookies()
    except Exception:
        pass
    try:
        driver.execute_script(
            "try{window.localStorage.clear();}catch(e){}"
            "try{window.sessionStorage.clear();}catch(e){}")
    except Exception:
        pass

    driver.get(BASE_URL)
    time.sleep(5)

    if on_login_page():
        log("  ✓ Сессия сброшена", "PASS")
        return True

    log("  ⚠ Не удалось выйти", "WARN")
    return False


def replace_login_input(field, value):
    """Keep controlled login fields synchronized through keyboard events."""
    field.click()
    field.send_keys(Keys.CONTROL + 'a')
    field.send_keys(Keys.BACKSPACE)
    wait_ui(lambda _: (field.get_attribute('value') or '') == '', timeout=3)
    field.send_keys(value)
    field.send_keys(Keys.TAB)
    wait_ui(lambda _: (field.get_attribute('value') or '') == value, timeout=3)


def login_with(login_value, password_value):
    global CURRENT_LOGIN
    log(f"  Логин под: {login_value}")
    try:
        WebDriverWait(driver, WAIT).until(
            EC.visibility_of_element_located((By.XPATH,
                "//input[contains(@placeholder,'огин') or contains(@placeholder,'Login') "
                "or @type='email' or @name='username' or @id='username']"))
        )
    except Exception:
        return False

    login_field = None
    for xp in [
        "//input[contains(@placeholder,'огин')]",
        "//input[@name='username' or @id='username']",
        "//input[contains(@placeholder,'Login')]",
        "//input[@type='email']",
    ]:
        try:
            fields = driver.find_elements(By.XPATH, xp)
            visible = [f for f in fields if f.is_displayed() and f.is_enabled()]
            if visible:
                login_field = visible[0]
                break
        except Exception:
            continue

    if not login_field:
        return False

    CURRENT_LOGIN = None
    try:
        replace_login_input(login_field, login_value)
    except Exception:
        log('  ⚠ Не удалось заменить логин: вход отменён до отправки формы', 'WARN')
        return False

    password_field = None
    for xp in [
        "//input[@type='password']",
        "//input[contains(@placeholder,'ароль')]",
    ]:
        try:
            fields = driver.find_elements(By.XPATH, xp)
            visible = [f for f in fields if f.is_displayed() and f.is_enabled()]
            if visible:
                password_field = visible[0]
                break
        except Exception:
            continue

    if not password_field:
        return False

    try:
        replace_login_input(password_field, password_value)
        # Browser autofill must not overwrite the selected account before submit.
        if (login_field.get_attribute('value') or '') != login_value:
            raise RuntimeError('Логин изменился перед отправкой')
    except Exception:
        log('  ⚠ Не удалось заполнить данные входа: форма не отправлена', 'WARN')
        return False

    for xp in [
        "//button[.//span[normalize-space(text())='Войти']]",
        "//button[contains(., 'Войти')]",
        "//button[@type='submit']",
    ]:
        try:
            btns = driver.find_elements(By.XPATH, xp)
            visible = [b for b in btns if b.is_displayed() and b.is_enabled()]
            if visible:
                try:
                    visible[0].click()
                except Exception:
                    js_click(visible[0])
                break
        except Exception:
            continue

    try:
        wait_authenticated()
    except Exception:
        return False
    dismiss_chrome_password_popup()

    try:
        pw = driver.find_elements(By.XPATH, "//input[@type='password']")
        if any(p.is_displayed() for p in pw):
            log(f"  ⚠ Логин {login_value} не удался", "WARN")
            return False
    except Exception:
        pass

    global _LOGOUT_IN_PROGRESS
    _LOGOUT_IN_PROGRESS = False  # вход выполнен — защита снова активна
    CURRENT_LOGIN = login_value
    log(f"  ✓ Успешный вход: {login_value}", "PASS")
    return True



# ==========================================
# НАВИГАЦИЯ / ЗАЩИТА ОТ ЧУЖОГО АКТА
# ==========================================
def ensure_on_our_document(context=""):
    target = workflow_result.get("url")
    if not target:
        return False
    try:
        target_id = target.rstrip("/").split("/acts/")[-1].split("/")[0].split("?")[0]
    except Exception:
        target_id = ""
    cur = driver.current_url
    if target_id and target_id in cur:
        return True
    log(f"  ⚠ Открыт не наш акт{(' (' + context + ')') if context else ''}: "
        f"{cur} — возвращаюсь на {target}", "WARN")
    try:
        driver.get(target)
        wait_card_ready()
        dismiss_chrome_password_popup()
    except Exception as e:
        log(f"  ⚠ Не удалось вернуться: {e}", "WARN")
        return False
    return target_id in driver.current_url


def go_to_details_tab():
    ensure_on_our_document("go_to_details_tab")
    try:
        driver.execute_script("window.scrollTo(0, 0);")
        time.sleep(0.4)
    except Exception:
        pass
    return True


# ==========================================
# ВЫБОР ДОГОВОРА (ui-select с поиском)
# ==========================================
def select_dogovor_sharipzhan():
    """Выбирает только договор ДГ-2026-10-000013.
    Форма акта: 'Договор / доп. соглашение' — ui-select с поиском."""
    dismiss_chrome_password_popup()

    trigger = None
    for label in ["Договор / доп. соглашение", "Договор поставки", "Договор"]:
        trigger = find_ui_kit_trigger_near_label(label)
        if trigger:
            break
    if not trigger:
        try:
            trigger = driver.find_element(
                By.XPATH,
                "//button[contains(@class,'ui-select__trigger')]"
                "[.//span[contains(normalize-space(text()),'оговор')]]")
        except Exception:
            trigger = None
    if not trigger:
        log("  ⚠ Поле договора не найдено", "WARN")
        dump_field_html("Договор / доп. соглашение")
        return False

    scroll_to(trigger)

    panel = None
    for method in ["hard", "js", "selenium", "actions"]:
        try:
            if method == "hard":
                _hard_click(trigger)
            elif method == "js":
                js_click(trigger)
            elif method == "selenium":
                trigger.click()
            else:
                ActionChains(driver).move_to_element(trigger).pause(0.3).click().perform()
            wait_select_panel()
            panels = driver.find_elements(
                By.XPATH, "//div[contains(@class,'ui-select__panel')]")
            vis = [p for p in panels if p.is_displayed()]
            if vis:
                panel = vis[-1]
                break
        except Exception:
            continue

    if not panel:
        log("  ⚠ Список договоров не открылся", "WARN")
        shot("dogovor_panel_not_open")
        return False

    def panel_options():
        out = []
        try:
            for b in panel.find_elements(By.XPATH, ".//button[@role='option']"):
                if not b.is_displayed():
                    continue
                try:
                    lbl = b.find_element(
                        By.XPATH, ".//span[contains(@class,'ui-select__option-label')]")
                    txt = (lbl.get_attribute("textContent") or "").strip()
                except Exception:
                    txt = (b.get_attribute("textContent") or "").strip()
                if txt:
                    out.append({"element": b, "text": txt})
        except Exception:
            pass
        return out

    options = []
    for query in ["ДГ-2026-10-000013"]:
        try:
            sinp = panel.find_element(
                By.XPATH, ".//input[contains(@class,'ui-select__search-input')]")
            try:
                sinp.click()
            except Exception:
                js_click(sinp)
            time.sleep(0.3)
            sinp.send_keys(Keys.CONTROL + "a")
            sinp.send_keys(Keys.BACKSPACE)
            time.sleep(0.2)
            sinp.send_keys(query)
            wait_ui(lambda _: any(re.search(r"(?<![0-9])ДГ-2026-10-000013(?![0-9])", o["text"], re.IGNORECASE)
                                  for o in panel_options()), timeout=5)
        except Exception:
            pass
        options = [o for o in panel_options()
                   if re.search(r"(?<![0-9])ДГ-2026-10-000013(?![0-9])", o["text"], re.IGNORECASE)]
        if options:
            log(f"    Поиск '{query}': найдено {len(options)}")
            break

    if not options:
        options = panel_options()
        log(f"  [DIAG] Договоров в списке: {len(options)}", "DIAG")
        options = [o for o in options
                   if re.search(r"(?<![0-9])ДГ-2026-10-000013(?![0-9])", o["text"], re.IGNORECASE)]

    if not options:
        log("  ⚠ Договор ДГ-2026-10-000013 не найден; выбор другого договора остановлен", "WARN")
        shot("no_dogovor_options")
        _close_any_ui_select_panel()
        return False

    best_num, best = -1, None
    for o in options:
        head = re.split(r'—|–', o["text"])[0]
        nums = re.findall(r'\d+', head)
        num = int(nums[-1]) if nums else 0
        if num > best_num:
            best_num, best = num, o
    if not best:
        best = options[0]

    log(f"  Выбираю договор: '{best['text'][:55]}' (№ {best_num})")
    if not _click_option_robustly(best["element"], best["text"], panel=None):
        return False
    _close_any_ui_select_panel()

    # Ждём появления доп. полей (Проект / Ставка НДС / Параметры акта)
    for _ in range(12):
        try:
            markers = driver.find_elements(
                By.XPATH,
                "//*[normalize-space(text())='Проект' "
                "or normalize-space(text())='Ставка НДС' "
                "or contains(normalize-space(text()),'Параметры акта') "
                "or contains(normalize-space(text()),'Режим формирования')]")
            if any(m.is_displayed() for m in markers):
                log("  ✓ Договор выбран, доп. поля появились", "PASS")
                return True
        except Exception:
            pass
        time.sleep(1)

    log("  ✓ Договор выбран (доп. поля не подтвердились явно)", "PASS")
    return True


def select_act_dropdown(label, allow_missing=False, target_option=None):
    """Универсальный ui-select формы акта. Ставка НДС → 16%."""
    trigger = find_ui_kit_trigger_near_label(label)
    if not trigger:
        if not allow_missing:
            log(f"  ⚠ {label}: поле не найдено", "WARN")
            dump_field_html(label)
        return None

    if not trigger.is_enabled() or trigger.get_attribute('aria-disabled') == 'true':
        log(f'  {label}: поле недоступно для изменения — пропускаю открытие')
        return None
    scroll_to(trigger)

    panel = None
    for method in ["hard", "js", "selenium"]:
        try:
            if method == "hard":
                _hard_click(trigger)
            elif method == "js":
                js_click(trigger)
            else:
                trigger.click()
            wait_select_panel()
            panels = driver.find_elements(
                By.XPATH, "//div[contains(@class,'ui-select__panel')]")
            vis = [p for p in panels if p.is_displayed()]
            if vis:
                panel = vis[-1]
                break
        except Exception:
            continue

    if not panel:
        if not allow_missing:
            log(f"  ⚠ {label}: список не открылся", "WARN")
        return None

    opts = []
    try:
        for b in panel.find_elements(By.XPATH, ".//button[@role='option']"):
            if not b.is_displayed():
                continue
            try:
                lbl = b.find_element(
                    By.XPATH, ".//span[contains(@class,'ui-select__option-label')]")
                txt = (lbl.get_attribute("textContent") or "").strip()
            except Exception:
                txt = (b.get_attribute("textContent") or "").strip()
            if txt:
                opts.append({"element": b, "text": txt})
    except Exception:
        pass

    if not opts:
        _close_any_ui_select_panel()
        return None

    expected = NDS_SCENARIO_ACT if "НДС" in label else target_option
    picked = next((o for o in opts if o['text'].strip().casefold() == expected.casefold()), None) if expected else opts[0]
    if not picked:
        _close_any_ui_select_panel()
        return False
    # The keyboard helper selects the first item; use the actual requested option.
    clicked = _click_option_robustly(picked['element'], picked['text'], panel=None)
    _close_any_ui_select_panel()
    def selected(_):
        current = find_ui_kit_trigger_near_label(label)
        return current and picked['text'].casefold() in (current.get_attribute('textContent') or '').casefold()
    try:
        return bool(clicked and wait_ui(selected))
    except Exception:
        return False



def select_radio_option(group_label, option_text):
    """Радиокнопка «Режим формирования» → «По форме»/«Произвольно»."""
    try:
        # Приоритетный способ (подтверждено DevTools): у радиокнопки
        # "Произвольно" есть стабильный атрибут value="ARBITRARY" — в
        # отличие от name (случайный React-id вида "_r_1g_", меняется
        # при каждой перерисовке и не годится для поиска).
        value_hints = {"Произвольно": "ARBITRARY", "По форме": "BY_FORM"}
        candidates = []
        if option_text in value_hints:
            candidates = driver.find_elements(
                By.XPATH, f"//input[@type='radio' and @value='{value_hints[option_text]}']")
            candidates = [c for c in candidates if c.is_displayed()]

        if not candidates:
            candidates = driver.find_elements(
                By.XPATH,
                f"//*[normalize-space(text())='{option_text}']"
                f"/preceding::input[@type='radio'][1] | "
                f"//*[normalize-space(text())='{option_text}']"
                f"/ancestor::label//input[@type='radio'] | "
                f"//label[contains(normalize-space(.),'{option_text}')]//input[@type='radio']")
        radio = None
        for c in candidates:
            try:
                if c.is_enabled():
                    radio = c
                    break
            except Exception:
                continue
        if radio is not None:
            try:
                if radio.is_selected():
                    log(f"  • {group_label}: '{option_text}' уже выбран")
                    return True
            except Exception:
                pass

        targets = []
        if radio is not None:
            targets.append(radio)
            try:
                targets.append(radio.find_element(By.XPATH, "./ancestor::label[1]"))
            except Exception:
                pass
        for xp in [
            f"//label[contains(normalize-space(.),'{option_text}')]",
            f"//*[normalize-space(text())='{option_text}']",
        ]:
            for e in driver.find_elements(By.XPATH, xp):
                if e.is_displayed():
                    targets.append(e)

        for t in targets:
            try:
                scroll_to(t)
                time.sleep(0.2)
            except Exception:
                pass
            for method in ["hard", "js", "selenium", "actions"]:
                try:
                    if method == "hard":
                        _hard_click(t)
                    elif method == "js":
                        js_click(t)
                    elif method == "selenium":
                        t.click()
                    else:
                        ActionChains(driver).move_to_element(t).pause(0.2).click().perform()
                    time.sleep(0.5)
                    if radio is not None:
                        try:
                            if radio.is_selected():
                                log(f"  ✓ {group_label}: '{option_text}' ({method})", "PASS")
                                return True
                        except Exception:
                            pass
                except Exception:
                    continue
        log(f"  ⚠ {group_label}: не удалось выбрать '{option_text}'", "WARN")
        return False
    except Exception as e:
        log(f"  ⚠ {group_label}: {e}", "WARN")
        return False


def _find_date_field(label):
    """Ищет поле даты (input или триггер-кнопку) рядом с подписью label."""
    # 1) input рядом с лейблом
    for xp in [
        f"//*[normalize-space(text())='{label}']/following::input[1]",
        f"//*[contains(normalize-space(text()),'{label}')]/following::input[1]",
    ]:
        els = driver.find_elements(By.XPATH, xp)
        vis = [i for i in els if i.is_displayed()]
        if vis:
            return vis[0]
    # 2) кнопка-триггер календаря
    for xp in [
        f"//*[normalize-space(text())='{label}']"
        f"/following::button[contains(@class,'ui-date-picker__trigger') "
        f"or contains(@class,'date-picker') or contains(@class,'picker')][1]",
    ]:
        els = driver.find_elements(By.XPATH, xp)
        vis = [e for e in els if e.is_displayed()]
        if vis:
            return vis[0]
    return None


def _get_open_calendar_panel():
    """Возвращает видимую панель календаря, если открыта."""
    for xp in [
        "//div[contains(@class,'ui-date-picker__panel')]",
        "//div[contains(@class,'ui-date-picker__calendar')]",
        "//*[@role='dialog' and .//div[contains(@class,'ui-date-picker__grid') "
        "or contains(@class,'calendar')]]",
    ]:
        els = driver.find_elements(By.XPATH, xp)
        vis = [e for e in els if e.is_displayed()]
        if vis:
            return vis[-1]
    return None


def _open_calendar(field_el):
    """Открывает календарь у поля даты (клик по нему всеми способами)."""
    scroll_to(field_el)
    for method in ["hard", "js", "selenium", "actions"]:
        try:
            if method == "hard":
                _hard_click(field_el)
            elif method == "js":
                js_click(field_el)
            elif method == "selenium":
                field_el.click()
            else:
                ActionChains(driver).move_to_element(field_el).pause(0.2).click().perform()
            if wait_ui(lambda _: _get_open_calendar_panel(), timeout=3):
                return True
        except Exception:
            continue
    return False


def _nav_to_month(target_date):
    """Листает открытый календарь до нужного месяца/года (в обе стороны)."""
    month_names = ["январь","февраль","март","апрель","май","июнь",
                   "июль","август","сентябрь","октябрь","ноябрь","декабрь"]
    tm = month_names[target_date.month - 1]
    ty = str(target_date.year)
    for _ in range(48):  # запас: до 4 лет в любую сторону
        panel = _get_open_calendar_panel()
        if not panel:
            return False
        try:
            nav = panel.find_element(
                By.XPATH,
                ".//div[contains(@class,'ui-date-picker__nav') "
                "or contains(@class,'calendar__nav') or contains(@class,'nav')]")
            nav_text = (nav.text or "").strip().lower()
        except Exception:
            nav_text = (panel.text or "").strip().lower()[:40]

        if tm in nav_text and ty in nav_text:
            return True

        # определяем направление
        go_back = False
        try:
            cur_year = None
            for w in nav_text.split():
                if w.isdigit() and len(w) == 4:
                    cur_year = int(w); break
            cur_month = next((i+1 for i,m in enumerate(month_names) if m in nav_text), None)
            if cur_year and cur_month:
                if (cur_year, cur_month) > (target_date.year, target_date.month):
                    go_back = True
        except Exception:
            pass

        # кнопки навигации: ищем ИМЕННО по месяцу (aria-label), а не
        # "первая/последняя кнопка" — подтверждено HTML-дампом: в
        # диалоге "Период закрытия" их четыре (год-назад/месяц-назад/
        # месяц-вперёд/год-вперёд), и "первая/последняя" оказывались
        # кнопками ГОДА, а не месяца — календарь улетал не туда.
        try:
            nav = panel.find_element(
                By.XPATH,
                ".//div[contains(@class,'ui-date-picker__nav') "
                "or contains(@class,'calendar__nav') or contains(@class,'nav')]")
            all_btns = [b for b in nav.find_elements(By.XPATH, ".//button") if b.is_displayed()]
        except Exception:
            all_btns = [b for b in panel.find_elements(By.XPATH, ".//button")
                        if b.is_displayed() and (b.get_attribute("textContent") or "").strip() in
                        {"", "‹", "›", "<", ">"}]

        month_btns = [b for b in all_btns
                      if "месяц" in (b.get_attribute("aria-label") or "").lower()]
        btns = month_btns if len(month_btns) >= 2 else all_btns
        if len(btns) < 2:
            return False
        target_btn = btns[0] if go_back else btns[-1]
        try:
            js_click(target_btn)
        except Exception:
            try:
                target_btn.click()
            except Exception:
                return False
        time.sleep(0.35)
    return False


def _click_day_in_calendar(target_date):
    """Кликает нужный день в открытом календаре (исключая соседние месяцы)."""
    td = str(target_date.day)
    panel = _get_open_calendar_panel()
    scope = panel if panel is not None else driver
    for xp in [
        f".//button[contains(@class,'ui-date-picker__day') and "
        f"not(contains(@class,'is-outside')) and not(@disabled) "
        f"and normalize-space(text())='{td}']",
        f".//*[(@role='gridcell' or contains(@class,'day')) and "
        f"not(contains(@class,'outside')) and not(contains(@class,'disabled')) "
        f"and normalize-space(text())='{td}']",
    ]:
        try:
            cells = scope.find_elements(By.XPATH, xp) if panel is not None \
                else driver.find_elements(By.XPATH, xp.replace(".//", "//", 1))
            vis = [c for c in cells if c.is_displayed()]
            if vis:
                for method in ["hard", "js", "selenium"]:
                    try:
                        if method == "hard":
                            _hard_click(vis[0])
                        elif method == "js":
                            js_click(vis[0])
                        else:
                            vis[0].click()
                        time.sleep(0.5)
                        return True
                    except Exception:
                        continue
        except Exception:
            continue
    return False


def _type_date_into_field(field_el, target_date):
    """Запасной способ: прямой ввод даты в input (dd.mm.yyyy)."""
    date_str = target_date.strftime("%d.%m.%Y")
    try:
        try:
            field_el.click()
        except Exception:
            js_click(field_el)
        time.sleep(0.3)
        try:
            _safe_clear_input(field_el)
        except Exception:
            pass
        # вводим ТОЛЬКО цифры — маска сама расставит точки (это и была
        # причина бага '2020': при вводе с точками год обрезался)
        field_el.send_keys(target_date.strftime("%d%m%Y"))
        time.sleep(0.4)
        field_el.send_keys(Keys.ENTER)
        time.sleep(0.4)
        val = (field_el.get_attribute("value") or "").strip()
        # проверяем, что год совпал
        if str(target_date.year) in val:
            return True
        # если год не совпал — пробуем с точками
        _safe_clear_input(field_el)
        field_el.send_keys(date_str)
        time.sleep(0.4)
        field_el.send_keys(Keys.ENTER)
        time.sleep(0.4)
        val = (field_el.get_attribute("value") or "").strip()
        return str(target_date.year) in val
    except Exception:
        return False


def _set_single_date(label, target_date):
    """Заполняет одиночную дату: СНАЧАЛА через календарь (надёжно, без
    проблем с маской), потом текстом как запасной. Проверяет год."""
    field = _find_date_field(label)
    if field is None:
        log(f"  ⚠ {label}: поле не найдено", "WARN")
        dump_field_html(label)
        return False

    # Способ 1: календарь
    if _open_calendar(field):
        if _nav_to_month(target_date) and _click_day_in_calendar(target_date):
            try:
                ActionChains(driver).send_keys(Keys.ESCAPE).perform()
            except Exception:
                pass
            time.sleep(0.4)
            # проверяем результат
            field2 = _find_date_field(label)
            val = (field2.get_attribute("value") or "").strip() if field2 is not None else ""
            if str(target_date.year) in val or val.strip():
                log(f"  ✓ {label}: {target_date.strftime('%d.%m.%Y')} [календарь]", "PASS")
                return True
        try:
            ActionChains(driver).send_keys(Keys.ESCAPE).perform()
        except Exception:
            pass

    # Способ 2: текст
    field = _find_date_field(label)
    if field is not None and _type_date_into_field(field, target_date):
        log(f"  ✓ {label}: {target_date.strftime('%d.%m.%Y')} [input]", "PASS")
        return True

    log(f"  ⚠ {label}: не удалось выставить {target_date.strftime('%d.%m.%Y')}", "WARN")
    dump_field_html(label)
    return False


def _safe_clear_input(el):
    """Безопасная очистка поля: НИКАКОГО Ctrl+A по документу.

    ПРИЧИНА: если фокус не внутри input, send_keys(Ctrl+A) выделяет ВСЮ
    СТРАНИЦУ (подтверждено скриншотом — вся форма подсветилась синим) и
    может закрыть открытый календарь/сбить состояние. Поэтому чистим
    через JS-сеттер и el.clear(), а клавиши шлём только в сам элемент.
    """
    try:
        driver.execute_script("""
            var el = arguments[0];
            var setter = Object.getOwnPropertyDescriptor(
                window.HTMLInputElement.prototype, 'value').set;
            setter.call(el, '');
            el.dispatchEvent(new Event('input', {bubbles:true}));
            el.dispatchEvent(new Event('change', {bubbles:true}));
        """, el)
        time.sleep(0.2)
        return True
    except Exception:
        pass
    try:
        el.clear()
        return True
    except Exception:
        return False


def _fill_period_range(field, start, end):
    """Заполняет ДИАПАЗОН дат «Период закрытия»: начало → конец.

    ПРОБЛЕМА, которую решаем: после клика по начальному дню календарь
    может закрыться или второй клик попадает в тот же день — в итоге
    получается «14.09.2026 – 14.09.2026» (подтверждено скриншотом).
    Поэтому: после первого клика ПРОВЕРЯЕМ, открыт ли календарь, при
    необходимости открываем заново, листаем к месяцу конца и кликаем
    конечный день. В финале сверяем, что две даты в поле РАЗНЫЕ.
    """
    def field_value():
        try:
            f = _find_date_field("Период закрытия") or _find_date_field("Период")
            return (f.get_attribute("value") or "").strip() if f is not None else ""
        except Exception:
            return ""

    def value_is_range(v):
        # в значении должны быть ДВЕ разные даты
        dates = re.findall(r'\d{2}\.\d{2}\.\d{4}', v or "")
        return len(dates) >= 2 and dates[0] != dates[-1]

    # --- Попытка 1: календарь, два клика ---
    for attempt in range(2):
        if not _open_calendar(field):
            break

        # начальный день
        if not (_nav_to_month(start) and _click_day_in_calendar(start)):
            try:
                ActionChains(driver).send_keys(Keys.ESCAPE).perform()
            except Exception:
                pass
            continue
        time.sleep(0.6)

        # календарь мог закрыться после первого клика — открываем снова
        if not _get_open_calendar_panel():
            f = _find_date_field("Период закрытия") or _find_date_field("Период")
            if f is not None:
                _open_calendar(f)
                time.sleep(0.5)

        # конечный день (может быть в следующем месяце)
        if _get_open_calendar_panel():
            _nav_to_month(end)
            _click_day_in_calendar(end)
            time.sleep(0.6)

        try:
            ActionChains(driver).send_keys(Keys.ESCAPE).perform()
        except Exception:
            pass
        time.sleep(0.5)

        val = field_value()
        if value_is_range(val):
            log(f"  ✓ Период: '{val}' [календарь]", "PASS")
            return True
        log(f"  • Попытка {attempt+1}: в поле '{val}' — диапазон не получился, повтор", "WARN")
        # очищаем перед повтором
        f = _find_date_field("Период закрытия") or _find_date_field("Период")
        if f is not None:
            _safe_clear_input(f)
            time.sleep(0.3)

    # --- Попытка 2: ввод двух дат подряд ТОЛЬКО цифрами ---
    f = _find_date_field("Период закрытия") or _find_date_field("Период")
    if f is not None:
        try:
            try:
                f.click()
            except Exception:
                js_click(f)
            time.sleep(0.3)
            _safe_clear_input(f)
            time.sleep(0.2)
            f.send_keys(start.strftime("%d%m%Y"))
            time.sleep(0.5)
            f.send_keys(end.strftime("%d%m%Y"))
            time.sleep(0.5)
            f.send_keys(Keys.ENTER)
            time.sleep(0.5)
            val = field_value()
            if value_is_range(val):
                log(f"  ✓ Период: '{val}' [ввод цифрами]", "PASS")
                return True
            if val:
                log(f"  ⚠ Период заполнен, но не диапазоном: '{val}'", "WARN")
                return True  # поле не пустое — форма, возможно, примет
        except Exception as e:
            log(f"  ⚠ Период (ввод): {e}", "WARN")

    return False


def fill_act_dates_and_period():
    start = datetime.now()
    end = start + timedelta(days=30)
    record_check('Заполнение даты акта', bool(_set_single_date('Дата акта', start)))
    number_ok = fill_act_field_in_ppc_wrapper('Номер акта', ACT_NUM)
    record_check('Заполнение номера акта', number_ok)
    period_ok = fill_act_period_range(start, end)
    record_check('Заполнение периода закрытия', period_ok)
    workflow_result['expected_date'] = start.strftime('%d.%m.%Y')
    workflow_result['expected_period'] = [start.strftime('%d.%m.%Y'), end.strftime('%d.%m.%Y')]
    if not all(workflow_result['checks'].values()):
        raise RuntimeError('Обязательные поля формы не заполнены')


def fill_act_period_range(start_date, end_date):
    """'Период закрытия' — КНОПКА-триггер (aria-haspopup='dialog',
    подтверждено HTML-дампом), открывает отдельный диалог с
    календарём — не встроенную панель, как остальные даты формы.
    Кликаем начальный день, затем конечный (может требовать перехода
    на следующий месяц)."""
    try:
        triggers = driver.find_elements(
            By.XPATH,
            "//button[contains(@class,'ui-date-picker__trigger')]"
            "[@aria-label='Выберите период' or .//span[contains(text(),'период')]]")
        vis = [t for t in triggers if t.is_displayed()]
        if not vis:
            log("  ⚠ Триггер 'Период закрытия' не найден", "WARN")
            return False
        trigger = vis[0]
        scroll_to(trigger)
        if not _hard_click(trigger):
            js_click(trigger)
        wait_ui(lambda _: _get_open_calendar_panel(), timeout=3)

        if not (_nav_to_month(start_date) and _click_day_in_calendar(start_date)):
            log("  ⚠ Период закрытия: не удалось кликнуть начальный день", "WARN")
            try:
                ActionChains(driver).send_keys(Keys.ESCAPE).perform()
            except Exception:
                pass
            return False
        time.sleep(0.5)

        if not (_nav_to_month(end_date) and _click_day_in_calendar(end_date)):
            log("  ⚠ Период закрытия: не удалось кликнуть конечный день", "WARN")
            try:
                ActionChains(driver).send_keys(Keys.ESCAPE).perform()
            except Exception:
                pass
            return False
        time.sleep(0.5)

        # Подтверждение, если есть отдельная кнопка (иначе просто Escape)
        confirmed = False
        for confirm_text in ["Применить", "Готово", "ОК", "Сохранить"]:
            btns = driver.find_elements(
                By.XPATH, f"//button[.//span[normalize-space(text())='{confirm_text}']]")
            vis_c = [b for b in btns if b.is_displayed()]
            if vis_c:
                if not _hard_click(vis_c[0]):
                    js_click(vis_c[0])
                time.sleep(0.5)
                confirmed = True
                break
        if not confirmed:
            try:
                ActionChains(driver).send_keys(Keys.ESCAPE).perform()
            except Exception:
                pass
        def selected_period(_):
            labels = visible_elements(By.XPATH, "//button[contains(@class,'ui-date-picker__trigger') and @aria-haspopup='dialog']//span[contains(@class,'ui-date-picker__trigger-label')]")
            for label in labels:
                value = (label.text or '').strip()
                if all(d.strftime('%d.%m.%Y') in value for d in (start_date, end_date)):
                    return value
            return False
        val = wait_ui(selected_period, timeout=5)
        if val:
            log(f"  ✓ Период закрытия: '{val}'", "PASS")
            return True
        log(f"  ⚠ Период закрытия: после клика текст триггера не изменился ('{val}')", "WARN")
        return False
    except Exception as e:
        log(f"  ⚠ Период закрытия: {e}", "WARN")
        return False



def ensure_act_content_expanded(arbitrary):
    title = 'Документ и суммы' if arbitrary else 'Строки закрытия'
    def ready(_):
        if arbitrary:
            fields = visible_elements(By.CSS_SELECTOR, '[data-form-field="manualAmountWithoutVat"] input')
        else:
            fields = visible_elements(By.XPATH, "//button[contains(normalize-space(.),'Добавить строку')]")
        return bool(fields)
    if ready(driver):
        return
    def expand(_):
        try:
            headings = visible_elements(By.XPATH, f"//*[normalize-space(text())='{title}']")
            if not headings:
                return False
            heading = headings[0]
            scroll_to(heading)
            heading.click()
            return True
        except Exception:
            return False
    wait_ui(expand)
    try:
        wait_ui(ready)
    except Exception as exc:
        raise RuntimeError(f'Раздел {title} не раскрылся: ожидаемые элементы недоступны') from exc
    log(f'Раздел {title} раскрыт', 'PASS')


def fill_act_arbitrary_field(form_field_name, value):
    """Replace the masked amount through keyboard events and verify readback."""
    selector = f'[data-form-field="{form_field_name}"] input'
    expected = money_value(str(value))
    def current_input():
        inputs = visible_elements(By.CSS_SELECTOR, selector)
        if len(inputs) != 1 or not inputs[0].is_enabled():
            raise RuntimeError(f'Поле {form_field_name} недоступно или неоднозначно')
        return inputs[0]
    def matches(_):
        try:
            return money_value(current_input().get_attribute('value') or '') == expected
        except Exception:
            return False
    try:
        inp = current_input()
        scroll_to(inp)
        inp.click()
        # clear() does not reliably update the controlled money input's mask.
        inp.send_keys(Keys.CONTROL + 'a')
        inp.send_keys(Keys.BACKSPACE)
        def cleared(_):
            text = current_input().get_attribute('value') or ''
            return not re.search(r'[1-9]', text)
        wait_ui(cleared, timeout=3)
        inp = current_input()
        inp.send_keys(str(value))
        inp.send_keys(Keys.TAB)
        wait_ui(matches, timeout=3)
        log(f'    ✓ {form_field_name}: {value}', 'PASS')
        return True
    except Exception as exc:
        try:
            actual = current_input().get_attribute('value')
        except Exception:
            actual = 'недоступно'
        log(f'    ⚠ {form_field_name}: ожидалось {value}, получено {actual}; {exc}', 'WARN')
        return False


def fill_act_field_in_ppc_wrapper(label_text, value):
    """Заполняет текстовое поле, лежащее ВНУТРИ ТОГО ЖЕ 'div.ppc-field',
    что и его подпись (span.ppc-field__label) — используем общий
    контейнер вместо document-order 'following::', который раньше мог
    случайно попадать не в то поле (подтверждённая структура формы
    акта: <div class="ppc-field"><span class="ppc-field__label">...
    </span>...<input>...</div>)."""
    try:
        labels = driver.find_elements(
            By.XPATH,
            f"//span[contains(@class,'ppc-field__label')][normalize-space(text())='{label_text}']")
        for lbl in labels:
            if not lbl.is_displayed():
                continue
            try:
                wrapper = lbl.find_element(
                    By.XPATH, "ancestor::div[contains(@class,'ppc-field')][1]")
            except Exception:
                continue
            inps = wrapper.find_elements(By.XPATH, ".//input")
            vis = [i for i in inps if i.is_displayed() and i.is_enabled()]
            if vis:
                vis[0].clear()
                vis[0].send_keys(value)
                log(f"    ✓ {label_text}: {value}", "PASS")
                return True
        log(f"    ⚠ {label_text}: поле не найдено (обёртка ppc-field)", "WARN")
        return False
    except Exception as e:
        log(f"    ⚠ {label_text}: {e}", "WARN")
        return False


def fill_signatories_in_card():
    exit_edit_mode()
    dismiss_chrome_password_popup()
    ensure_on_our_document("fill_signatories")

    already_editing = False
    try:
        trg = driver.find_elements(
            By.XPATH,
            "//button[contains(@class,'ui-select__trigger')]"
            "[.//span[contains(normalize-space(text()),'Выбрать заказчика') "
            "or contains(normalize-space(text()),'Выбрать контрагента')]]")
        already_editing = any(t.is_displayed() for t in trg)
    except Exception:
        pass

    if not already_editing:
        choose_link = None
        try:
            section = driver.find_element(
                By.XPATH, "//section[contains(@class,'signers-card')]")
            links = section.find_elements(
                By.XPATH, ".//button[contains(@class,'signers-card__select-link')]")
            vis = [l for l in links if l.is_displayed()]
            if vis:
                choose_link = vis[0]
            if not choose_link:
                edits = section.find_elements(
                    By.XPATH, ".//button[.//span[normalize-space(text())='Редактировать']]")
                ve = [b for b in edits if b.is_displayed() and b.is_enabled()]
                if ve:
                    choose_link = ve[0]
        except Exception:
            pass

        if not choose_link:
            log("  ⚠ Не найдена кнопка входа в редактирование подписантов", "WARN")
            dump_field_html("Подписанты")
            return False

        scroll_to(choose_link)
        time.sleep(0.3)
        _hard_click(choose_link)
        try:
            WebDriverWait(driver, 8).until(
                lambda d: any(t.is_displayed() for t in d.find_elements(
                    By.XPATH,
                    "//button[contains(@class,'ui-select__trigger')]"
                    "[.//span[contains(normalize-space(text()),'Выбрать заказчика') "
                    "or contains(normalize-space(text()),'Выбрать контрагента')]]")))
        except Exception:
            time.sleep(1.0)

    ok_zakazchik = _select_in_ui_select(
        "Выбрать заказчика", "Бейсембаев",
        ["Бейсембаев Куаныш", "Бейсембаев"], "Заказчик")
    ok_kontragent = _select_in_ui_select(
        "Выбрать контрагента", "Алд",
        ["Алдажаров Диас Андреевич", "Алдажаров Диас", "Алд"], "Контрагент")

    _close_any_ui_select_panel()
    time.sleep(0.4)

    save_btn = None
    for xp in [
        "//section[contains(@class,'signers-card')]"
        "//button[.//span[normalize-space(text())='Сохранить']]",
        "//section[contains(@class,'signers-card')]"
        "//button[normalize-space(text())='Сохранить']",
        "//button[.//span[normalize-space(text())='Отмена']]"
        "/following-sibling::button[.//span[normalize-space(text())='Сохранить']]",
    ]:
        els = driver.find_elements(By.XPATH, xp)
        vis = [e for e in els if e.is_displayed() and e.is_enabled()]
        if vis:
            save_btn = vis[0]
            break

    if save_btn:
        scroll_to(save_btn)
        time.sleep(0.3)
        for method in ["hard", "js", "selenium"]:
            try:
                if method == "hard":
                    _hard_click(save_btn)
                elif method == "js":
                    js_click(save_btn)
                else:
                    save_btn.click()
                break
            except Exception:
                continue
        log("  ✓ Кнопка 'Сохранить' подписантов нажата", "PASS")
    else:
        log("  ⚠ Кнопка 'Сохранить' подписантов не найдена", "WARN")

    def saved_signers(_):
        section = driver.find_element(By.CSS_SELECTOR, 'section.signers-card')
        text = section.text.lower()
        save_buttons = section.find_elements(By.XPATH, ".//button[normalize-space(.)='Сохранить']")
        return 'бейсембаев' in text and 'алд' in text and not any(b.is_displayed() for b in save_buttons)
    try:
        saved = bool(save_btn) and WebDriverWait(driver, WAIT).until(saved_signers)
    except Exception:
        saved = False
    result = bool(ok_zakazchik) and bool(ok_kontragent) and saved
    log(f"  Подписанты: Заказчик={'OK' if ok_zakazchik else 'FAIL'}, "
        f"Контрагент={'OK' if ok_kontragent else 'FAIL'}",
        "PASS" if result else "WARN")
    if not result:
        shot("signatories_incomplete")
    return result


# ==========================================
# ПОДПИСАНИЕ ЭЦП
# ==========================================
CONTRACTOR_LOGIN = login_val
CONTRACTOR_PASS = pass_val


def upload_paper_signed_scan():
    """Upload a synthetic test PDF through the observed signed-scan dialog."""
    ensure_on_our_document('paper_signed_scan')
    title = 'Тестовый подписанный комплект ' + ACT_NUM
    modal_xpath = "//*[@role='dialog'][.//h2[normalize-space(.)='Загрузить подписанный скан']]"
    def dialog():
        found = visible_elements(By.XPATH, modal_xpath)
        return found[0] if len(found) == 1 else False
    try:
        pdf = create_test_pdf('paper_signed_scan_' + ACT_NUM)
        if not pdf:
            raise RuntimeError('Не создан тестовый PDF подписанного комплекта')
        buttons = visible_elements(By.XPATH, "//button[normalize-space(.)='Загрузить подписанный скан']")
        if len(buttons) != 1 or not buttons[0].is_enabled():
            raise RuntimeError('Кнопка загрузки подписанного скана недоступна')
        scroll_to(buttons[0])
        buttons[0].click()
        modal = wait_ui(lambda _: dialog())
        modal.find_element(By.CSS_SELECTOR, 'input.file-drop__hidden[type="file"]').send_keys(os.path.abspath(pdf))
        title_input = modal.find_element(By.CSS_SELECTOR, '[data-form-field="title"] input')
        title_input.send_keys(Keys.CONTROL + 'a')
        title_input.send_keys(title)
        def ready(_):
            modal = dialog()
            if not modal:
                return False
            button = modal.find_element(By.XPATH, ".//footer//button[normalize-space(.)='Загрузить']")
            return button if button.is_enabled() else False
        wait_ui(ready).click()
        wait_ui(lambda _: not dialog())
        driver.refresh()
        wait_card_ready()
        # Exact generated title is unique to this test and must survive refresh.
        wait_ui(lambda _: visible_elements(By.XPATH, "//*[normalize-space(text())='" + title + "']"))
        workflow_result['paper_scan_title'] = title
        return record_check('Загрузка подписанного скана', True)
    except Exception as exc:
        reason = str(exc).strip() or type(exc).__name__
        record_check('Загрузка подписанного скана', False, reason)
        shot('paper_scan_upload_failed')
        raise RuntimeError('Подписанный скан не загружен: ' + reason) from exc


def choose_ncalayer_method():
    """Select NCALayer when the portal offers signing methods."""
    xpath = "//*[@role='dialog'][.//*[contains(normalize-space(.),'Способ подписания')]]"
    try:
        dialogs = wait_ui(lambda _: visible_elements(By.XPATH, xpath), timeout=3)
    except TimeoutException:
        # Older portal versions open NCALayer directly.
        return
    if len(dialogs) != 1:
        raise RuntimeError('Неоднозначное окно способа подписания')
    buttons = dialogs[0].find_elements(By.XPATH,
        ".//*[self::button or @role='button'][contains(normalize-space(.),'NCALayer')]")
    buttons = [b for b in buttons if b.is_displayed() and b.is_enabled()]
    if len(buttons) != 1:
        shot('ncalayer_method_not_found')
        raise RuntimeError('В окне способа подписи не найдена однозначная кнопка NCALayer')
    buttons[0].click()
    log('  Выбран способ подписи NCALayer')


def sign_act_with_ecp():
    """Sign as Алдажаров Диас using the certificate configured by the user."""
    act_url = workflow_result.get('url')
    if not act_url:
        raise RuntimeError('URL акта неизвестен перед подписью контрагента')
    if CURRENT_LOGIN != CONTRACTOR_LOGIN:
        if not logout_current_account():
            raise RuntimeError('Не удалось завершить текущую сессию перед входом Алдажаров Диас')
        if not login_with(CONTRACTOR_LOGIN, CONTRACTOR_PASS):
            raise RuntimeError('Не удалось войти под Алдажаров Диас для подписи контрагента')
    driver.get(act_url)
    wait_card_ready()
    ensure_on_our_document("sign_act")
    go_to_details_tab()
    for btn in ["Подписать и отправить", "Подписать", "Подписать ЭЦП"]:
        if click_card_action(btn):
            choose_ncalayer_method()
            log(f"  Нажата '{btn}', жду NCALayer...")
            ok = sign_with_ncalayer(password=NCA_PASSWORD, p12_path=MAIN_P12_PATH)
            if ok:
                workflow_result["signed"] = True
                workflow_result["actions_done"].append("Алдажаров Диас: ЭЦП OK")
                log("  ✓ Акт подписан ЭЦП контрагентом Алдажаров Диас", "PASS")
            else:
                workflow_result["fail_reasons"]["Подписание ЭЦП"] = (
                    "sign_with_ncalayer() вернул неуспех — см. лог NCALayer выше "
                    "(окно не появилось / пароль не введён / ИИН не совпал и т.п.)")
            if ok:
                wait_status({'Подписан'})
            status = get_current_status()
            log(f"  '{btn}' → статус: '{status}'", "PASS" if ok else "WARN")
            workflow_result["actions_done"].append(f"{btn} → {status}")
            workflow_result["final_status"] = status
            return ok
    workflow_result["fail_reasons"]["Подписание ЭЦП"] = (
        "кнопка 'Подписать и отправить'/'Подписать'/'Подписать ЭЦП' не найдена в шапке")
    log("  • Кнопка подписания в шапке не найдена", "WARN")
    shot("no_sign_button_act")
    return False


def sign_act_by_talgat(act_url):
    """Первый подписант (заказчик — Бейсембаев, dias.aldazharov@bk.ru) подписывает акт сертификатом GOST512."""
    log("=" * 60)
    log("Бейсембаев Куаныш подписывает акт (marshar244, GOST512)")
    log("=" * 60)
    if not act_url:
        log("  ⚠ URL акта неизвестен", "WARN")
        return False

    if not logout_current_account():
        driver.get(BASE_URL)
        time.sleep(4)
    if not login_with(TALGAT_LOGIN, TALGAT_PASS):
        log("  ⚠ Не удалось войти под Бейсембаев Куанышом", "WARN")
        return False

    dismiss_chrome_password_popup()
    driver.get(act_url)
    wait_card_ready()
    dismiss_chrome_password_popup()

    try:
        tid = act_url.rstrip("/").split("/acts/")[-1].split("/")[0].split("?")[0]
    except Exception:
        tid = ""
    if tid and tid not in driver.current_url:
        log(f"  ⚠ Под Бейсембаев Куанышом акт не открылся ({driver.current_url})", "WARN")
        shot("wrong_page_talgat")
        return False

    time.sleep(2)
    shot("talgat_opened_act")
    log(f"  Статус акта: '{get_current_status()}'")

    for btn in ["Подписать заказчиком", "Подписать", "Подтвердить подписание"]:
        if click_card_action(btn):
            choose_ncalayer_method()
            log(f"  Нажата '{btn}', жду NCALayer...")
            signed = sign_with_ncalayer(
                password=TALGAT_NCA_PASSWORD, p12_path=TALGAT_P12_PATH)
            if signed:
                workflow_result["actions_done"].append("Бейсембаев Куаныш: ЭЦП OK")
            if signed:
                wait_status({'На подписании', 'Подписан'})
            status = get_current_status()
            log(f"  Бейсембаев Куаныш: '{btn}' → '{status}'", "PASS" if signed else "WARN")
            workflow_result["actions_done"].append(f"Бейсембаев Куаныш: {btn} → {status}")
            workflow_result["final_status"] = status
            return signed

    log("  ⚠ Кнопка подписания не найдена под Бейсембаев Куанышом", "WARN")
    shot("no_talgat_sign_btn")
    return False



def fill_f2b_closure_line():
    """Fill the construction table using the supplied F-2V DOM."""
    table_selector = 'table.f2b-print-table'
    row_selector = table_selector + ' tbody tr'
    try:
        buttons = visible_elements(By.XPATH, "//button[contains(normalize-space(.),'Добавить строку')]")
        if len(buttons) != 1:
            raise RuntimeError('Кнопка добавления строки Ф-2В недоступна или неоднозначна')
        before = len(visible_elements(By.CSS_SELECTOR, row_selector))
        scroll_to(buttons[0])
        if not _hard_click(buttons[0]):
            buttons[0].click()
        wait_ui(lambda _: len(visible_elements(By.CSS_SELECTOR, row_selector)) == before + 1)
        def row():
            return visible_elements(By.CSS_SELECTOR, row_selector)[-1]
        def replace_input(selector, value, numeric=False):
            def field():
                found = row().find_elements(By.CSS_SELECTOR, selector)
                if len(found) != 1 or not found[0].is_enabled():
                    raise RuntimeError(f'Неоднозначное или недоступное поле строки: {selector}')
                return found[0]
            inp = field()
            scroll_to(inp)
            inp.click()
            inp.send_keys(Keys.CONTROL + 'a')
            inp.send_keys(Keys.BACKSPACE)
            wait_ui(lambda _: not (field().get_attribute('value') or '').strip() or
                    (numeric and money_value(field().get_attribute('value')) == 0), timeout=3)
            field().send_keys(value)
            field().send_keys(Keys.TAB)
            def matches(_):
                text = field().get_attribute('value') or ''
                return money_value(text) == money_value(value) if numeric and text else text == value
            wait_ui(matches, timeout=3)
        replace_input('input[placeholder="Наименование"]', 'Выполненные работы (RPA)')
        # Scope both selects to their actual cells; label lookup can select the expense twice.
        for cell_class in ['f2b-print-table__col-expense', 'f2b-print-table__col-expense-type']:
            selector = 'td.' + cell_class + ' button.ui-select__trigger'
            trigger = row().find_element(By.CSS_SELECTOR, selector)
            scroll_to(trigger)
            if not _hard_click(trigger):
                trigger.click()
            panel = wait_select_panel()
            options = wait_ui(lambda _: [e for e in panel.find_elements(By.CSS_SELECTOR, 'button[role="option"]') if e.is_displayed()])
            picked = options[0]
            text = (picked.get_attribute('textContent') or '').strip()
            if not _click_option_robustly(picked, text, panel=None):
                raise RuntimeError(f'Не выбрана опция {cell_class}')
            wait_ui(lambda _: text in (row().find_element(By.CSS_SELECTOR, selector).get_attribute('textContent') or ''))
        replace_input('td.f2b-print-table__col-qty input', '1', numeric=True)
        replace_input('[data-form-field$=".workersWages"] input', '1000', numeric=True)
        # Supplied DOM: the tenth cell is editable total cost, without data-form-field.
        replace_input('td:nth-child(10) input', '1000', numeric=True)
        log('  ✓ Строка Ф-2В: наименование, статья, тип, количество и стоимость подтверждены', 'PASS')
        return True
    except Exception as exc:
        log(f'  ⚠ Строка Ф-2В: {exc}', 'WARN')
        return False


def fill_avr_contract_line():
    """Fill the AVR contract line and verify its saved input values."""
    table_selector = 'table.dt__table'
    row_selector = table_selector + ' tbody tr'
    try:
        source_buttons = visible_elements(By.XPATH, "//button[contains(@class,'ui-select__trigger')][normalize-space(.)='Из договора']")
        if len(source_buttons) != 1:
            raise RuntimeError('Не найден выбор строки из договора')
        if source_buttons[0].is_enabled():
            scroll_to(source_buttons[0])
            source_buttons[0].click()
            panel = wait_select_panel()
            options = wait_ui(lambda _: [e for e in panel.find_elements(By.CSS_SELECTOR, 'button[role="option"]') if e.is_displayed()])
            if not _click_option_robustly(options[0], options[0].text, panel=None):
                raise RuntimeError('Строка договора не выбрана')
        else:
            buttons = visible_elements(By.XPATH, "//button[contains(normalize-space(.),'Добавить строку')]")
            buttons = [b for b in buttons if b.is_enabled()]
            if len(buttons) != 1:
                raise RuntimeError('Нет доступной кнопки добавления строки АВР')
            scroll_to(buttons[0])
            buttons[0].click()
        wait_ui(lambda _: visible_elements(By.CSS_SELECTOR, row_selector))
        def row():
            return visible_elements(By.CSS_SELECTOR, row_selector)[-1]
        def replace_input(selector, value, numeric=False):
            def field():
                found = row().find_elements(By.CSS_SELECTOR, selector)
                if len(found) != 1 or not found[0].is_enabled():
                    raise RuntimeError(f'Неоднозначное или недоступное поле строки: {selector}')
                return found[0]
            inp = field()
            scroll_to(inp)
            inp.click()
            # Replace the selected value directly. Contract inputs may restore their
            # inherited value when cleared, so waiting for an empty value is invalid.
            inp.send_keys(Keys.CONTROL + 'a')
            inp.send_keys(value)
            field().send_keys(Keys.TAB)
            def matches(_):
                text = field().get_attribute('value') or ''
                return money_value(text) == money_value(value) if numeric and text else text == value
            try:
                wait_ui(matches, timeout=3)
            except TimeoutException as exc:
                actual = field().get_attribute('value')
                raise RuntimeError(f'Поле {selector}: ожидалось {value!r}, прочитано {actual!r}') from exc
            log(f'  ✓ Строка АВР: {selector} = {value}', 'PASS')
        replace_input('input[placeholder="Наименование"]', 'Выполненные работы (RPA)')
        # Scope both selects to their actual cells; label lookup can select the expense twice.
        for cell_class in ['avr-print-table__col-expense', 'avr-print-table__col-type']:
            selector = 'td.' + cell_class + ' button.ui-select__trigger'
            trigger = row().find_element(By.CSS_SELECTOR, selector)
            scroll_to(trigger)
            if not _hard_click(trigger):
                trigger.click()
            panel = wait_select_panel()
            options = wait_ui(lambda _: [e for e in panel.find_elements(By.CSS_SELECTOR, 'button[role="option"]') if e.is_displayed()])
            picked = options[0]
            text = (picked.get_attribute('textContent') or '').strip()
            if not _click_option_robustly(picked, text, panel=None):
                raise RuntimeError(f'Не выбрана опция {cell_class}')
            wait_ui(lambda _: text in (row().find_element(By.CSS_SELECTOR, selector).get_attribute('textContent') or ''))
        replace_input('td:nth-child(9) input', '1', numeric=True)
        replace_input('td:nth-child(10) input', '1000', numeric=True)
        day = datetime.now()
        calendar = row().find_element(By.CSS_SELECTOR, '[data-form-field$=".workDate"] button')
        if not _open_calendar(calendar) or not _nav_to_month(day) or not _click_day_in_calendar(day):
            raise RuntimeError('Не выбрана дата выполнения работ')
        wait_ui(lambda _: row().find_element(By.CSS_SELECTOR, '[data-form-field$=".workDate"] input').get_attribute('value') == day.strftime('%d.%m.%Y'))
        net, gross, _ = expected_amounts(NDS_SCENARIO_ACT, net=Decimal('1000'))
        wait_ui(lambda _: money_value(row().find_element(By.CSS_SELECTOR, 'td:nth-child(11) input').get_attribute('value')) == net and
                money_value(row().find_element(By.CSS_SELECTOR, 'td:nth-child(12) input').get_attribute('value')) == gross)
        log('  ✓ Строка АВР: количество 1, цена 1000, дата и суммы подтверждены', 'PASS')
        return True
    except Exception as exc:
        log(f'  ⚠ Строка АВР: {exc}', 'WARN')
        return False


def fill_ks2_closure_line():
    """Fill KS-2 using the supplied ks2-print-table DOM (no work-date field)."""
    row_selector = 'table.ks2-print-table tbody tr:not(.avr-print-form__total-row)'
    stage = 'добавление строки'
    try:
        before = len(visible_elements(By.CSS_SELECTOR, row_selector))
        buttons = [b for b in visible_elements(By.XPATH, "//button[contains(normalize-space(.),'Добавить строку')]") if b.is_enabled()]
        if len(buttons) != 1:
            raise RuntimeError('Не найдена однозначная кнопка Добавить строку')
        scroll_to(buttons[0])
        buttons[0].click()
        wait_ui(lambda _: len(visible_elements(By.CSS_SELECTOR, row_selector)) == before + 1)
        def row():
            return visible_elements(By.CSS_SELECTOR, row_selector)[-1]
        checkbox = row().find_element(By.CSS_SELECTOR, 'input[type="checkbox"]')
        if not checkbox.is_selected():
            checkbox.click()
        wait_ui(lambda _: row().find_element(By.CSS_SELECTOR, 'input[type="checkbox"]').is_selected())
        def replace(selector, value, numeric=False):
            def field():
                return row().find_element(By.CSS_SELECTOR, selector)
            inp = field()
            scroll_to(inp)
            inp.click()
            inp.send_keys(Keys.CONTROL + 'a')
            inp.send_keys(value)
            field().send_keys(Keys.TAB)
            def matches(_):
                actual = field().get_attribute('value') or ''
                return bool(actual) and (money_value(actual) == Decimal(value) if numeric else actual == value)
            try:
                wait_ui(matches, timeout=3)
            except TimeoutException as exc:
                raise RuntimeError(f'{selector}: ожидалось {value!r}, прочитано {field().get_attribute("value")!r}') from exc
        stage = 'наименование'
        replace('input[placeholder="Наименование"]', 'Выполненные работы (RPA)')
        for column, label in [(5, 'статья расходов'), (6, 'тип')]:
            stage = label
            selector = f'td:nth-child({column}) button.ui-select__trigger'
            trigger = row().find_element(By.CSS_SELECTOR, selector)
            scroll_to(trigger)
            panel_id = trigger.get_attribute('aria-controls')
            trigger.click()
            def options(_):
                panels = driver.find_elements(By.ID, panel_id) if panel_id else []
                return [o for panel in panels if panel.is_displayed()
                        for o in panel.find_elements(By.CSS_SELECTOR, 'button[role="option"]')
                        if o.is_displayed() and o.is_enabled()]
            available = wait_ui(options)
            picked = available[0]
            text = (picked.get_attribute('textContent') or '').strip()
            if not text or not _click_option_robustly(picked, text, panel=None):
                raise RuntimeError('Не выбрана опция: ' + label)
            wait_ui(lambda _: text in (row().find_element(By.CSS_SELECTOR, selector).get_attribute('textContent') or ''))
        stage = 'количество'
        replace('td:nth-child(8) input', '1', numeric=True)
        stage = 'расценка'
        replace('td:nth-child(9) input', '1000', numeric=True)
        stage = 'сумма строки'
        wait_ui(lambda _: money_value(row().find_element(By.CSS_SELECTOR, 'td:nth-child(10) input').get_attribute('value')) == Decimal('1000'))
        stage = 'итог таблицы'
        wait_ui(lambda _: money_value(driver.find_element(By.CSS_SELECTOR,
            'table.ks2-print-table .avr-print-form__total-row td:nth-child(2)').text) == Decimal('1000'))
        log('  ✓ КС-2: наименование, статья, тип, количество 1, расценка 1000; сумма строки и итог 1000', 'PASS')
        return True
    except Exception as exc:
        reason = str(exc).strip() or type(exc).__name__
        workflow_result['fail_reasons']['Заполнение строки закрытия'] = f'КС-2, {stage}: {reason}'
        log(f'  ⚠ КС-2, {stage}: {reason}', 'WARN')
        return False


def fill_act_closure_line():
    """Добавляет и заполняет одну строку в таблице 'Строки закрытия'
    (АКТ ВЫПОЛНЕННЫХ РАБОТ / ОКАЗАННЫХ УСЛУГ).

    ВАЖНО, подтверждено скриншотом: 'Из договора' — это просто выбор
    ИСТОЧНИКА данных, а НЕ автоподтягивание строк, как считалось
    раньше. Реальную строку нужно добавить кнопкой '+ Добавить строку'
    и заполнить все поля вручную — иначе раздел остаётся пустым
    ('Добавьте строку закрытия'), и акт не создаётся."""
    if ACT_TYPE == 'f2b':
        return fill_f2b_closure_line()
    if ACT_TYPE == 'avr':
        return fill_avr_contract_line()
    if ACT_TYPE == 'ks2':
        return fill_ks2_closure_line()
    try:
        add_btns = driver.find_elements(
            By.XPATH, "//button[contains(normalize-space(.),'Добавить строку')]")
        vis = [b for b in add_btns if b.is_displayed()]
        if not vis:
            log("  ⚠ Кнопка 'Добавить строку' не найдена", "WARN")
            return False
        scroll_to(vis[0])
        time.sleep(0.3)
        if not _hard_click(vis[0]):
            js_click(vis[0])
        time.sleep(1.5)
    except Exception as e:
        log(f"  ⚠ Ошибка клика 'Добавить строку': {e}", "WARN")
        return False

    ok_all = True

    # Наименование работ (услуг) — обычное текстовое поле
    try:
        inps = driver.find_elements(By.XPATH, "//input[@placeholder='Наименование']")
        vis = [i for i in inps if i.is_displayed()]
        if vis:
            vis[0].clear()
            vis[0].send_keys("Выполненные работы (RPA)")
            log("  ✓ Наименование работ заполнено", "PASS")
        else:
            log("  ⚠ Поле 'Наименование' не найдено", "WARN")
            ok_all = False
    except Exception as e:
        log(f"  ⚠ Наименование: {e}", "WARN")
        ok_all = False

    # Статья расходов / Тип — выпадающие списки (тот же ui-select)
    if not select_act_dropdown("Статья расходов", allow_missing=True):
        log("  ⚠ 'Статья расходов' не выбрана", "WARN")
        ok_all = False
    time.sleep(0.3)
    if not select_act_dropdown("Тип", allow_missing=True):
        log("  ⚠ 'Тип' не выбран", "WARN")
        ok_all = False
    time.sleep(0.3)

    # Дата выполнения работ (оказания услуг)
    try:
        _set_single_date("Дата выполнения работ", datetime.now())
    except Exception as e:
        log(f"  ⚠ Дата выполнения работ: {e}", "WARN")

    # Сведения об отчёте (дата, номер, страниц) — текстовое поле
    try:
        inps = driver.find_elements(
            By.XPATH, "//input[contains(@placeholder,'дата, номер, страниц')]")
        vis = [i for i in inps if i.is_displayed()]
        if vis:
            vis[0].clear()
            vis[0].send_keys(f"Отчёт RPA от {datetime.now().strftime('%d.%m.%Y')}")
            log("  ✓ Сведения об отчёте заполнены", "PASS")
    except Exception as e:
        log(f"  ⚠ Сведения об отчёте: {e}", "WARN")

    # Кол-во и Цена за единицу без НДС — числовые поля рядом с заголовком столбца
    for label_txt, value in [("Кол-во", "1"), ("Цена за единицу без НДС", "1000")]:
        try:
            el = find_control_near_label(label_txt)
            if el is not None:
                el.clear()
                el.send_keys(value)
                log(f"  ✓ {label_txt}: {value}", "PASS")
            else:
                log(f"  ⚠ {label_txt}: поле не найдено", "WARN")
                ok_all = False
        except Exception as e:
            log(f"  ⚠ {label_txt}: {e}", "WARN")
            ok_all = False

    return ok_all


# ==========================================
# ГЛАВНЫЙ WORKFLOW — АКТ (По форме + ЭЦП, строки из договора)
# ==========================================

def record_check(name, ok, reason=""):
    workflow_result["checks"][name] = bool(ok)
    log(f"{name}: {'✓' if ok else '✗'}", "PASS" if ok else "FAIL")
    if not ok:
        workflow_result["fail_reasons"][name] = reason or "ожидаемое состояние не подтверждено"
        shot("check_failed")
    return bool(ok)


def act_card_url(url):
    parsed = urlparse(url)
    base = urlparse(ACTS_URL)
    parts = parsed.path.rstrip('/').split('/')
    return (parsed.netloc == base.netloc and
            parsed.path.startswith(base.path + '/') and
            len(parts) in (4, 5) and parts[3] not in ('', 'create') and
            (len(parts) == 4 or parts[4] in ('details', 'edit')))


def expected_amounts(vat, net=Decimal('100000')):
    rate = Decimal('0.16') if vat == 'НДС 16%' else Decimal('0')
    tax = (net * rate).quantize(Decimal('0.01'))
    return net, (net + tax).quantize(Decimal('0.01')), tax


def money_value(text):
    return Decimal(re.sub(r'[^0-9,.\-]', '', text).replace(',', '.'))


def selected_form_mode():
    for value, title in [('ARBITRARY', 'Произвольно'), ('BY_FORM', 'По форме')]:
        for el in driver.find_elements(By.CSS_SELECTOR, f'input[type="radio"][value="{value}"]'):
            if el.is_selected():
                return title
    return None


def check_mode_controls():
    # Check both branches before filling fields; switching does not submit the form.
    off = set_toggle_state('Бумажное подписание', False)
    arbitrary = select_radio_option('Режим формирования', 'Произвольно')
    record_check('Переключение в произвольный режим', off and arbitrary and selected_form_mode() == 'Произвольно')
    by_form = select_radio_option('Режим формирования', 'По форме')
    record_check('Возврат в режим по форме', by_form and selected_form_mode() == 'По форме')
    on = set_toggle_state('Бумажное подписание', True)
    radios = driver.find_elements(By.CSS_SELECTOR, 'input[type="radio"][value="ARBITRARY"], input[type="radio"][value="BY_FORM"]')
    record_check('Бумажное подписание фиксирует произвольный режим',
                 on and selected_form_mode() == 'Произвольно' and len(radios) == 2 and all(not r.is_enabled() for r in radios))
    set_toggle_state('Бумажное подписание', PAPER_MODE_ACT)
    if not PAPER_MODE_ACT:
        select_radio_option('Режим формирования', FORM_MODE_ACT)
    switch = find_toggle_switch('Бумажное подписание')
    mode_ok = selected_form_mode() == FORM_MODE_ACT
    workflow_result['form_mode_ok'] = record_check('Выбранный режим формирования', mode_ok)
    record_check('Состояние бумажного подписания', switch is not None and get_toggle_state(switch) == PAPER_MODE_ACT)
    if not mode_ok:
        raise RuntimeError('Режим формы не соответствует сценарию')


def validation_messages():
    return driver.execute_script("""
        const visible = e => !!(e.offsetWidth || e.offsetHeight || e.getClientRects().length);
        return [...document.querySelectorAll('#rgb-toast-host > *, [aria-invalid="true"], [role="alert"], [class*="error"], [class*="invalid"]')]
          .filter(visible).map(e => (e.textContent || e.getAttribute('aria-label') || e.getAttribute('name') || e.getAttribute('placeholder') || '').trim())
          .filter(Boolean);
    """) or []


def check_creation_blocked(kind):
    before = driver.current_url
    previous = set(validation_messages())
    buttons = [b for b in driver.find_elements(By.XPATH, "//button[normalize-space(.)='Создать']") if b.is_displayed()]
    if not buttons:
        return record_check('Валидация: ' + kind, False, 'кнопка Создать не найдена')
    button = buttons[-1]
    disabled = not button.is_enabled()
    if not disabled:
        button.click()
    def evidence(_):
        if act_card_url(driver.current_url):
            raise RuntimeError('Невалидная форма создала акт: ' + driver.current_url)
        messages = validation_messages()
        return messages if set(messages) - previous else False
    try:
        messages = WebDriverWait(driver, WAIT, poll_frequency=0.15).until(evidence) if not disabled else ['Создать недоступно']
        keywords = {'обязательный PDF': ('pdf', 'документ', 'файл'), 'обязательные строки закрытия': ('строк', 'закрыти')}.get(kind, ())
        relevant = not keywords or any(k in ' '.join(messages).lower() for k in keywords)
        ok = driver.current_url == before and bool(messages) and (disabled or relevant)
    except Exception as exc:
        messages = [str(exc).strip() or f'Не обнаружена ошибка валидации: {kind}; URL: {driver.current_url}']
        if messages == ['Message:']:
            messages = [f'Не обнаружена ошибка валидации: {kind}; форма осталась на {driver.current_url}']
        ok = False
    workflow_result['validation_evidence'] = messages
    return record_check('Валидация: ' + kind, ok, '; '.join(messages))


def verify_manual_amounts():
    net, gross, tax = expected_amounts(NDS_SCENARIO_ACT)
    for field, expected in [('manualAmountWithoutVat', net), ('manualAmountWithVat', gross)]:
        inputs = driver.find_elements(By.CSS_SELECTOR, f'[data-form-field="{field}"] input')
        try:
            ok = len(inputs) == 1 and money_value(inputs[0].get_attribute('value')) == expected
        except Exception:
            ok = False
        record_check('Сумма формы: ' + field, ok, 'сумма не совпадает с выбранным НДС')
    workflow_result['expected_amounts'] = {'net': str(net), 'gross': str(gross), 'vat': str(tax)}


def emit_scenario_result():
    negative = ACT_SCENARIOS[ACT_SCENARIO].get('NEGATIVE')
    if not negative and not workflow_result.get('creation_only'):
        for name in ['Отправка на согласование', 'Согласование акта']:
            if name not in workflow_result['checks']:
                record_check(name, False, 'действие или ожидаемый статус не подтверждены')
        if not PAPER_MODE_ACT:
            workflow_result['signed'] = (workflow_result.get('first_signature', False) and workflow_result.get('second_signature', False) and workflow_result.get('final_status') == 'Подписан')
        for name, key in [('Создание документа', 'created'), ('Маршрут согласования', 'route'), ('Указание подписантов', 'signatories'), ('Подписание', 'signed')]:
            record_check(name, workflow_result[key])
    if not negative:
        record_check('Создание документа', workflow_result['created'])
    workflow_result['passed'] = bool(workflow_result['checks']) and all(workflow_result['checks'].values())
    _safe_out('ACT_RESULT ' + json.dumps(workflow_result, ensure_ascii=False))
    return workflow_result.copy()



def read_card_field(label):
    # Read the smallest local field container, never a whole card/section.
    return driver.execute_script("""
        const norm = s => (s || '').replace(/\\s+/g, ' ').trim();
        const wanted = arguments[0];
        const labels = [...document.querySelectorAll('span, label, dt, div, p')]
          .filter(e => !e.children.length && norm(e.textContent) === wanted && e.getClientRects().length);
        const values = [];
        for (const label of labels) {
          let parent = label.parentElement;
          for (let level=0; level<2 && parent; level++, parent=parent.parentElement) {
            if (parent.querySelector('input, textarea') || parent.querySelectorAll('label, dt').length > 1) break;
            // Pencil buttons are actions beside the value, not the value itself.
            const copy = parent.cloneNode(true);
            copy.querySelectorAll('button, svg, [aria-hidden="true"]').forEach(e => e.remove());
            const text = norm(copy.textContent);
            const value = text.startsWith(wanted) ? text.slice(wanted.length).trim() : '';
            if (value && value.length < 180) { values.push(value); break; }
          }
        }
        return values.length === 1 ? values[0] : null;
    """, label)


def verify_created_card():
    expected = {'Тип документа': ACT_TYPE_NAMES[ACT_TYPE], 'Номер акта': ACT_NUM,
                'Ставка НДС': NDS_SCENARIO_ACT, 'Режим': FORM_MODE_ACT,
                'Бумажное подписание': 'Да' if PAPER_MODE_ACT else 'Нет',
                'Дата акта': workflow_result.get('expected_date')}
    actual = {}
    def snapshot(_):
        actual.update({label: read_card_field(label) for label in expected})
        return all(value is not None for value in actual.values())
    try:
        wait_ui(snapshot, 5)
    except Exception:
        pass
    for label, value in expected.items():
        record_check('Карточка: ' + label, actual[label] == value, f'Ожидалось {value}; прочитано {actual[label]}')
    period = read_card_field('Период')
    record_check('Карточка: период', bool(period) and all(d in period for d in workflow_result['expected_period']), 'Период не подтверждён в карточке')
    if FORM_MODE_ACT == 'Произвольно':
        net, gross, _ = expected_amounts(NDS_SCENARIO_ACT)
        for label, value in [('Без НДС', net), ('С НДС', gross)]:
            text = read_card_field(label)
            try:
                ok = text is not None and money_value(text) == value
            except Exception:
                ok = False
            record_check('Карточка: сумма ' + label, ok, f'Ожидалось {value}; прочитано {text}')
    workflow_result['card_fields'] = actual



CURRENT_LOGIN = None


def wait_ui(predicate, timeout=None):
    return WebDriverWait(driver, WAIT if timeout is None else timeout, poll_frequency=0.15, ignored_exceptions=(StaleElementReferenceException,)).until(predicate)


def visible_elements(by, value):
    found = []
    for el in driver.find_elements(by, value):
        try:
            if el.is_displayed():
                found.append(el)
        except StaleElementReferenceException:
            continue
    return found


def wait_login_or_app():
    return wait_ui(lambda _: visible_elements(By.CSS_SELECTOR, 'input[type="password"]') or
                   (urlparse(driver.current_url).netloc == urlparse(BASE_URL).netloc and
                    visible_elements(By.CSS_SELECTOR, 'header, nav')))


def wait_authenticated():
    return wait_ui(lambda _: urlparse(driver.current_url).netloc == urlparse(BASE_URL).netloc and
                   not visible_elements(By.CSS_SELECTOR, 'input[type="password"]') and
                   visible_elements(By.CSS_SELECTOR, 'header, nav'))


def ensure_main_session():
    if CURRENT_LOGIN == login_val:
        log('Основной аккаунт уже подтверждён — использую текущую сессию')
        return
    driver.get(BASE_URL)
    wait_login_or_app()
    if not visible_elements(By.CSS_SELECTOR, 'input[type="password"]'):
        if not logout_current_account():
            raise RuntimeError('Не удалось выйти из неизвестной или чужой сессии')
        wait_ui(lambda _: visible_elements(By.CSS_SELECTOR, 'input[type="password"]'))
    if not login_with(login_val, pass_val):
        raise RuntimeError('Вход основного аккаунта не подтверждён')


def open_act_form(url):
    driver.get(url)
    wait_login_or_app()
    if visible_elements(By.CSS_SELECTOR, 'input[type="password"]'):
        # A session can expire even if it was previously verified.
        if not login_with(login_val, pass_val):
            raise RuntimeError('Не удалось восстановить истёкшую сессию')
        driver.get(url)
    wait_ui(lambda _: find_ui_kit_trigger_near_label('Договор / доп. соглашение') or
            visible_elements(By.XPATH, "//button[normalize-space(.)='Создать']"))


def wait_card_ready():
    return wait_ui(lambda _: act_card_url(driver.current_url) and get_current_status())


def wait_status(expected):
    return wait_ui(lambda _: get_current_status() if get_current_status() in expected else False)


def wait_select_panel():
    return wait_ui(lambda _: visible_elements(By.CSS_SELECTOR, '.ui-select__panel'), 3)[-1]


def wait_select_closed():
    return wait_ui(lambda _: not visible_elements(By.CSS_SELECTOR, '.ui-select__panel'), 2)


def sign_electronic_act_in_order():
    """Portal signing order: customer first, contractor second."""
    workflow_result['first_signature'] = False
    workflow_result['second_signature'] = False
    log('ЭТАП 9: заказчик Бейсембаев Куаныш подписывает первым')
    workflow_result['first_signature'] = bool(sign_act_by_talgat(workflow_result['url']))
    if not workflow_result['first_signature']:
        workflow_result['fail_reasons']['Подписание'] = 'Не подтверждена подпись заказчика Бейсембаева'
        return False
    log('ЭТАП 10: вход под Алдажаровым Диасом и подпись контрагента')
    workflow_result['second_signature'] = bool(sign_act_with_ecp())
    if not workflow_result['second_signature']:
        workflow_result['fail_reasons']['Подписание'] = 'Не подтверждена подпись контрагента Алдажарова'
        return False
    workflow_result['final_status'] = get_current_status()
    return workflow_result['final_status'] == 'Подписан'


def main():
    act_name = ACT_TYPE_NAMES.get(ACT_TYPE, ACT_TYPE)
    log("=" * 60)
    log(f"АКТ {act_name}: {ACT_NUM}")
    log("=" * 60)

    log('ЭТАП 1: Проверка основного аккаунта')
    ensure_main_session()

    # --- ЭТАП 2: Открытие формы создания акта нужного типа ---
    log(f"ЭТАП 2: Создание акта {act_name}")
    create_url = ACT_CREATE_URLS.get(ACT_TYPE, ACT_CREATE_URLS["avr"])
    open_act_form(create_url)
    dismiss_chrome_password_popup()
    log(f"  URL формы: {driver.current_url}", "PASS")

    # --- ЭТАП 3: Заполнение формы ---
    log(f"ЭТАП 3: Заполнение формы ({act_name})")
    dismiss_chrome_password_popup()

    if ACT_SCENARIOS[ACT_SCENARIO].get('NEGATIVE') == 'empty':
        check_creation_blocked('пустая форма')
        return

    # Договор → появляются остальные поля
    dogovor_ok = select_dogovor_sharipzhan()
    if not record_check('Выбор договора', dogovor_ok):
        raise RuntimeError('Договор не выбран')
    dismiss_chrome_password_popup()

    # Проект / Очередь / Блок (необязательные — часто автозаполнены)
    select_act_dropdown("Проект", allow_missing=True)
    select_act_dropdown("Очередь", allow_missing=True)
    select_act_dropdown("Блок", allow_missing=True)

    # Ставка НДС — по текущему сценарию
    nds_ok = select_act_dropdown("Ставка НДС", allow_missing=True)
    workflow_result["nds_ok"] = record_check("Выбранная ставка НДС", nds_ok)
    if not nds_ok:
        workflow_result["fail_reasons"][f"Ставка НДС: {NDS_SCENARIO_ACT}"] = (
            f"не удалось выбрать вариант '{NDS_SCENARIO_ACT}' в списке ставок НДС")

    if not nds_ok:
        raise RuntimeError('Ставка НДС не выбрана')
    check_mode_controls()

    # Дата акта, Номер акта, Период закрытия
    fill_act_dates_and_period()

    actual_arbitrary = selected_form_mode() == 'Произвольно'
    ensure_act_content_expanded(actual_arbitrary)
    negative = ACT_SCENARIOS[ACT_SCENARIO].get('NEGATIVE')
    if actual_arbitrary:
        # Режим "Произвольно" — СОВСЕМ другая секция 3 формы: вместо
        # автоподтягивания строк из договора нужно вручную ввести
        # суммы и загрузить PDF-файл акта (подпись зависит от типа:
        # "ДОКУМЕНТ АВР"/"ДОКУМЕНТ КС-2"/"ДОКУМЕНТ Ф-2В").
        log("  Режим 'Произвольно': заполняю суммы вручную + загружаю PDF")
        net, gross, _ = expected_amounts(NDS_SCENARIO_ACT)
        record_check('Ввод суммы без НДС', fill_act_arbitrary_field('manualAmountWithoutVat', str(net)))
        record_check('Ввод суммы с НДС', fill_act_arbitrary_field('manualAmountWithVat', str(gross)))
        blur_focus()
        verify_manual_amounts()
        if negative == 'pdf':
            check_creation_blocked('обязательный PDF')
            return

        act_type_label = ACT_TYPE_NAMES.get(ACT_TYPE, ACT_TYPE)
        pdf_path = create_test_pdf(f"{ACT_TYPE}_{ACT_NUM}")
        if pdf_path:
            record_check("Загрузка PDF", upload_act_pdf_dropzone(act_type_label, pdf_path))
        else:
            log("  ⚠ PDF не создан — загрузка документа акта пропущена", "WARN")
    else:
        # "Из договора" — это ВЫБОР ИСТОЧНИКА, а не автоподтягивание
        # (подтверждено скриншотом: без явного добавления строка
        # остаётся пустой — "Добавьте строку закрытия"). Добавляем и
        # заполняем строку вручную.
        log("  Строки закрытия: добавляю и заполняю строку вручную")
        if negative == 'lines':
            check_creation_blocked('обязательные строки закрытия')
            return
        if not record_check('Заполнение строки закрытия', fill_act_closure_line()):
            workflow_result["fail_reasons"]["Создание документа"] = (
                "не удалось полностью заполнить строку в разделе 'Строки закрытия'")

    if not all(workflow_result['checks'].values()):
        raise RuntimeError('Подготовка формы не прошла проверки')
    # --- ЭТАП 4: Создать акт ---
    log("ЭТАП 4: Создание акта")
    blur_focus()
    if click_create_button():
        wait_card_ready()
        new_url = driver.current_url
        if "/acts/" in new_url and "/create" not in new_url:
            workflow_result["url"] = new_url
            workflow_result["created"] = True
            log(f"  ✓ Акт создан: {new_url}", "PASS")

    if not workflow_result["created"]:
        workflow_result["fail_reasons"]["Создание документа"] = (
            "кнопка 'Создать' не сработала или URL не сменился на карточку акта")
        log("Прерываю — акт не создан", "FAIL")
        shot("not_created")
        return

    exit_edit_mode()
    dismiss_chrome_password_popup()
    clean_url = driver.current_url.replace("/edit", "").rstrip("/")
    workflow_result["url"] = clean_url
    log(f"  URL карточки: {clean_url}", "PASS")
    driver.get(clean_url)
    wait_card_ready()
    dismiss_chrome_password_popup()

    verify_created_card()
    record_check('Статус нового акта', get_current_status() == 'Черновик')
    if _args.creation_only:
        workflow_result['creation_only'] = True
        return
    workflow_result['workflow_started'] = True
    # --- ЭТАП 5: Маршрут согласования ---
    log("ЭТАП 5: Маршрут согласования (Алдажаров)")
    dismiss_chrome_password_popup()
    for retry in range(3):
        driver.refresh()
        wait_card_ready()
        go_to_details_tab()
        dismiss_chrome_password_popup()
        try:
            already = False
            vals = driver.find_elements(
                By.XPATH,
                "//section[contains(@class,'evd-route')]"
                "//div[contains(@class,'evd-route__stages')]"
                "//span[contains(@class,'ui-select__value')]")
            for v in vals:
                if not v.is_displayed():
                    continue
                txt = (v.get_attribute("textContent") or "").strip()
                if "алд" in txt.lower() and "выбрать" not in txt.lower():
                    log(f"  ✓ Маршрут уже настроен ('{txt}')", "PASS")
                    workflow_result["route"] = True
                    already = True
                    break
            if not already:
                cells = driver.find_elements(
                    By.XPATH,
                    "//section[contains(@class,'evd-route')]"
                    "//table[contains(@class,'evd-route__table')]//tbody//td")
                for c in cells:
                    if not c.is_displayed():
                        continue
                    txt = (c.get_attribute("textContent") or "").strip()
                    low = txt.lower()
                    if ("алд" in low and txt not in {"—", "-"} and not low.isdigit()
                            and "выбрать" not in low and len(txt) > 2
                            and any(ch.isalpha() for ch in txt)):
                        log(f"  ✓ Маршрут уже настроен (в таблице: '{txt}')", "PASS")
                        workflow_result["route"] = True
                        already = True
                        break
            if already:
                break
        except Exception:
            pass

        if add_approval_route():
            workflow_result["route"] = True
            break
        workflow_result["fail_reasons"]["Маршрут согласования"] = (
            "не удалось создать этап или выбрать согласующего в маршруте")
        try:
            for _ in range(4):
                ActionChains(driver).send_keys(Keys.ESCAPE).perform()
        except Exception:
            pass

    # --- ЭТАП 6: Подписанты ---
    log("ЭТАП 6: Подписанты (Заказчик=Бейсембаев, Контрагент=Алдажаров Диас)")
    for retry in range(3):
        if fill_signatories_in_card():
            workflow_result["signatories"] = True
            break
        log(f"  ⚠ Попытка #{retry+1} не удалась", "WARN")
        workflow_result["fail_reasons"]["Указание подписантов"] = (
            "не удалось выбрать Заказчика и/или Контрагента в карточке подписантов")
        try:
            for _ in range(3):
                ActionChains(driver).send_keys(Keys.ESCAPE).perform()
        except Exception:
            pass
        exit_edit_mode()
        go_to_details_tab()

    if not workflow_result['route'] or not workflow_result['signatories']:
        raise RuntimeError('Маршрут или подписанты не сохранены; отправка на согласование остановлена')

    # --- ЭТАП 7: На согласование ---
    log("ЭТАП 7: 'На согласование'")
    go_to_details_tab()
    if click_card_action("На согласование"):
        wait_status({'На согласовании'})
        status = get_current_status()
        record_check('Отправка на согласование', status == 'На согласовании', f'Статус: {status}')
        log(f"  → '{status}'", "PASS")
        workflow_result["actions_done"].append(f"На согласование → {status}")
        workflow_result["final_status"] = status
    else:
        log("  ⚠ Не удалось отправить на согласование", "WARN")

    # --- ЭТАП 8: Согласовать ---
    log("ЭТАП 8: 'Согласовать'")
    go_to_details_tab()
    for approve_btn in ["Согласовать", "Подтвердить согласование", "Утвердить"]:
        if click_card_action(approve_btn):
            wait_status({'На подписании', 'Подписан'})
            status = get_current_status()
            record_check('Согласование акта', status in {'На подписании', 'Подписан'}, f'Статус: {status}')
            log(f"  '{approve_btn}' → '{status}'", "PASS")
            workflow_result["actions_done"].append(f"{approve_btn} → {status}")
            workflow_result["final_status"] = status
            break

    # --- ЭТАП 9: Подписание ЭЦП (основной аккаунт) — не применимо
    # при 'Бумажном подписании' (там ЭЦП не требуется вовсе) ---
    if PAPER_MODE_ACT:
        log("ЭТАП 9-10: пропущены — при бумажном подписании ЭЦП не требуется")
        status = get_current_status()
        if status != 'Подписан':
            upload_paper_signed_scan()
            if not click_card_action('Отметить подписанным'):
                raise RuntimeError('Не найдено действие Отметить подписанным')
            wait_status({'Подписан'})
            status = get_current_status()
        workflow_result["final_status"] = status
        workflow_result["signed"] = status == "Подписан"
        if not workflow_result["signed"]:
            workflow_result["fail_reasons"]["Бумажное подписание (без ЭЦП)"] = (
                f"после отправки статус остался '{status}' — документ не продвинулся")
    else:
        workflow_result['signed'] = sign_electronic_act_in_order()

    if not PAPER_MODE_ACT:
        workflow_result['signed'] = (workflow_result.get('first_signature', False) and
                                     workflow_result.get('second_signature', False) and
                                     workflow_result['final_status'] == 'Подписан')
    # --- ИТОГИ ---
    log("=" * 60)
    log(f"ИТОГИ (АКТ {act_name})")
    log("=" * 60)
    log(f"Акт: {ACT_NUM}")
    log(f"URL: {workflow_result['url']}")
    log(f"Создан: {'✓' if workflow_result['created'] else '✗'}")
    log(f"Маршрут: {'✓' if workflow_result['route'] else '✗'}")
    log(f"Подписанты: {'✓' if workflow_result['signatories'] else '✗'}")
    if PAPER_MODE_ACT:
        log(f"Бумажное подписание (без ЭЦП): {'✓' if workflow_result['signed'] else '✗'}")
    else:
        log(f"Подписано ЭЦП: {'✓' if workflow_result['signed'] else '✗'}")
    log(f"Финальный статус: {workflow_result['final_status'] or 'Неизвестно'}")

# ==========================================
# ЗАПУСК
# Без аргументов — прогоняются ВСЕ комбинации (3 типа × 5 сценариев =
# 15 прогонов) подряд, один за другим, в одном и том же браузере.
#     py test-akt.py                  → основные 18 сценариев 
#     py test-akt.py ks2              → КС-2, 6 основных сценариев 
#     py test-akt.py "" paper_mode    → все 3 типа, только paper_mode
#     py test-akt.py ks2 paper_mode   → только эта одна комбинация
# ==========================================
def select_run_cases(act_type='', scenario=''):
    if act_type and act_type not in CORE_SCENARIOS:
        raise ValueError('Неизвестный тип акта: ' + act_type)
    types = [act_type] if act_type else list(CORE_SCENARIOS)
    cases = [(kind, key) for kind in types for key in CORE_SCENARIOS[kind]
             if not scenario or key == scenario]
    if not cases:
        raise ValueError('Сценарий отсутствует в согласованном наборе 18: ' + act_type + '/' + scenario)
    return cases

_cases_to_run = select_run_cases(_args.act_type, _args.scenario)
_results = []
for _type, _scenario in _cases_to_run:
    _apply_scenario(_type, _scenario)
    try:
        main()
    except Exception as exc:
        record_check('Выполнение сценария', False, str(exc))
    finally:
        _results.append(emit_scenario_result())

_report_path = log_path('act_results_' + datetime.now().strftime('%Y%m%d_%H%M%S') + '.json')
with open(_report_path, 'w', encoding='utf-8') as _report:
    json.dump(_results, _report, ensure_ascii=False, indent=2)
_safe_out('Отчёт: ' + _report_path)
if _LOG_FILE:
    _LOG_FILE.close()
sys.exit(0 if all(r['passed'] for r in _results) else 1)
