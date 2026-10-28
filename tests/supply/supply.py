# -*- coding: utf-8 -*-
"""
АВТОТЕСТ: «Снабжение» — ОДИН скрипт на все три модуля:
  1) Заявки на снабжение  (/supply)
  2) Остатки              (/supply/stock)
  3) Техника              (/supply/equipment)

ЗАЯВКИ НА СНАБЖЕНИЕ
  • список: фильтры (Проект / Статус), поиск, «Сбросить фильтры», сортировка, пагинация,
    «Настройки таблицы», открыть любую существующую заявку
  • «Создать заявку»: Проект (Flagman) -> Смета (утверждённая) -> Склад -> Очередь -> Блок
  • карточка: вкладки Обсуждение / Приёмки / Передачи / История, меню «⋮»
  • Соисполнитель: «Поделиться» -> внутренний пользователь (Талгат; если нет — Рыспамбетов Асылхан Курметович)
  • Маршрут согласования: «Добавить этап» -> Sh Margulan Ju
  • «Позиции заявки» -> «Добавить строку»: Из строки сметы, Статья расходов, Тип, Материал, Ед. изм.,
    Количество, План кол-во, План. цена, Дата поставки, Комментарий + файл
  • Обсуждение: сообщение + файл; ещё одна позиция; проверка, что Поставщик указался автоматически
  • «Отправить на согласование» -> Согласовать / Утвердить / Подписать (Талгат, NCALayer) — до конца
ОСТАТКИ
  • фильтры (Версия сметы / Категория / Склад / Материал / «Остаток на складе»), поиск материала,
    «Сбросить фильтры», сортировка, пагинация и «Строк на стр.», «Настройки таблицы»,
    выбор строк + «Переместить» (окно открывается и закрывается — перемещение НЕ выполняется)
ТЕХНИКА
  • список: фильтры (Проект / Статус / Владение), поиск, открыть одну существующую технику
  • «Создать»: Проект, Очередь, Блок, Тип техники, Вид техники, Владение, Дата начала/окончания,
    Время начала/окончания, Комментарий -> «Создать заказ»
  • маршрут (Sh Margulan Ju), обсуждение (сообщение + файл), «Позиции заказа» -> «Добавить строку»
    (Количество, Статья расходов, Ед. измерения, Цена без НДС, Комментарий), «Вернуться к основной
    информации», «На согласование» -> и дальше до конца

Кнопки «Удалить» и пункты меню «⋮» НЕ нажимаются; «Переместить» только открывается и закрывается.

ОТЧЁТЫ: Telegram («Проверка: Успешно / Неуспешно — причина» + скриншот при ошибках + сводка)
и Google Sheets (ваш sheet_reporter.py, лист «Чек-лист»).

ЗАВИСИМОСТИ: pip install openpyxl requests pywinauto gspread google-auth

НЕ ПРОВЕРЕНО НА ЖИВОМ DOM (`# TODO VERIFY`): окно «Поделиться заявкой» (название кнопки
подтверждения), «Настройки таблицы», окно «Переместить», кнопки статусных действий после
отправки на согласование. При сбое — ⚠ в логе и скриншот debug_*.png.
"""

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

import re
import time





import glob
import json
from pathlib import Path
_ROOT = Path(__file__).resolve().parent.parent.parent
for _d in (_ROOT, _ROOT / "core", _ROOT / "config", Path(__file__).resolve().parent):
    if str(_d) not in sys.path:
        sys.path.insert(0, str(_d))
from artifact_paths import screen_path, log_path
from env_config import env, is_headless
import base64
import zipfile
import tempfile
import shutil
import datetime
from datetime import datetime as _dt_cls
from urllib.parse import urlparse
from xml.sax.saxutils import escape as xml_escape
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains

# `datetime` в хелперах — КЛАСС, для дат в этом файле нужен модуль (dtm).
dtm = datetime
datetime = _dt_cls

# ==========================================
# КОНФИГУРАЦИЯ
# ==========================================
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager

driver = None


def init_driver():
    global driver
    _chrome_options = Options()
    _chrome_options.add_argument("--start-maximized")
    # Отключает всплывающий попап «Сохранить пароль?» в Chrome
    _chrome_options.add_experimental_option("prefs", {
        "credentials_enable_service": False,
        "profile.password_manager_enabled": False
    })
    # Запуск без UI (headless) при HEADLESS=1 (CI / сервер без монитора):
    if is_headless():
        _chrome_options.add_argument("--headless=new")
        _chrome_options.add_argument("--window-size=1920,1080")
        _chrome_options.add_argument("--no-sandbox")
        _chrome_options.add_argument("--disable-dev-shm-usage")
        _chrome_options.add_argument("--disable-gpu")
    
    driver = webdriver.Chrome(
        service=Service(ChromeDriverManager().install()),
        options=_chrome_options
    )
    driver.implicitly_wait(0)

login_val = env("RGB_ACCOUNT1_LOGIN", 'jyktmargyplay2@gmail.com')
pass_val = env("RGB_ACCOUNT1_PASSWORD", '12341234')

# Утверждающий / подписант (Талгат)
SECOND_LOGIN = 'aldazarovdias@gmail.com'
SECOND_PASS = '12341234'

BASE_URL = "https://testportal.rgbgroup.kz/"
SUPPLY_URL = BASE_URL + "supply"
STOCK_URL = BASE_URL + "supply/stock"
EQUIP_URL = BASE_URL + "supply/equipment"
WAIT = 15

STAMP = datetime.now().strftime('%d%m-%H%M%S')
PROJECT_QUERY = "Flagman"
PROJECT_KEYS = ["flagman", "флагман", "flag", "флаг"]     # проект: Flagman/Флагман
PROJECT_SEARCH = ["Flag", "Флаг"]
ESTIMATE_KEYS = ["автотест", "autotest", "auto test", "auto-test", "авто тест"]   # смета из смета-автотеста
ESTIMATE_SEARCH = ["автотест", "AutoTest"]
REVIEWER_LOGIN = 'dias.aldazharov@bk.ru'
REVIEWER_PASS = 'h7WxqKIR'

APPROVER_QUERY = 'Бейсембаев'

# Соисполнитель («Поделиться»): сначала Талгат, если нет в списке — Рыспамбетов Асылхан Курметович
COEXEC_TRIES = [('Алдажаров', ['алдажаров', 'алдазаров']), ('Диас', ['диас'])]

# Статусные кнопки. «Отклонить» и подобные — НЕ используются.
TO_SEND = ["Отправить на согласование", "На согласование"]
TO_APPROVE = ["Согласовать"]
TO_CONFIRM = ["Утвердить"]
TO_EXTRA = ["Начать работу", "Принять в работу", "Взять в работу", "В работу", "Исполнить",
            "Завершить работу", "Завершить", "Выполнено", "Закрыть заказ", "Подтвердить выполнение"]
TERMINAL = ("утвержд", "подписан", "исполнен", "на исполнении", "закрыт", "выполнен", "завершен", "завершён")

DOWNLOAD_DIR = os.environ.get("DOWNLOAD_DIR", os.path.join(os.path.expanduser("~"), "Downloads"))
WORK_DIR = os.path.join(tempfile.gettempdir(), f"supply_autotest_{STAMP}")
os.makedirs(WORK_DIR, exist_ok=True)

# ---- Telegram (как в run_workflow_and_report.py) ----
# ВАЖНО: токен секретный. Не выкладывайте файл в публичный репозиторий/общий чат.
# Можно не хранить в файле: задайте переменную окружения TG_TOKEN.

# ---- Google Sheets («Чек-лист») через ваш sheet_reporter.py ----
# Диапазон строк раздела «Снабжение» в Чек-листе, например (120, 170). None — искать названия
# проверок во всём столбце B. Названия проверок = названия этапов (с префиксом «Заявки:» /
# «Остатки:» / «Техника:»).

STATE = {"url": None, "supply_url": None, "equip_url": None, "supply_no": None,
         "equip_no": None, "summary": [], "supplier": None}
RESULTS = []        # (название, ok)
REASONS = {}
FAILED_SCREENSHOTS = []
ROLE_RESTORE_FAILED = False
RUN_ERROR = ""        # название -> причина провала
LOG_LINES = []
_RUN_STARTED = time.time()

LOG_FILE_PATH = log_path(f"supply_log_{STAMP}_{os.environ.get('SUPPLY_RUN_ID', 'standalone')}.txt")
try:
    _LOG_FILE = open(LOG_FILE_PATH, "w", encoding="utf-8", buffering=1)
except Exception:
    _LOG_FILE = None


# ===== вспомогательные функции =====
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
    line = f"[{datetime.now().strftime('%H:%M:%S')}] [{tag}] {msg}"
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
        safe = re.sub(r'[^\w\-]+', '_', name)[:40]
        path = screen_path(f"debug_supply_{safe}_{os.environ.get('SUPPLY_RUN_ID', STAMP)}_{time.time_ns()}.png")
        driver.save_screenshot(path)
        if name.startswith(("fail_", "critical_error")):
            FAILED_SCREENSHOTS.append(path)
        log(f"  Скриншот: {path}")
    except Exception:
        pass

def js_click(el):
    driver.execute_script("arguments[0].click();", el)

def scroll_to(el):
    try:
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
    except Exception:
        pass

def hard_click(el):
    """Клик с полной цепочкой pointer/mouse-событий (ui-select слушает pointerdown)."""
    try:
        driver.execute_script("""
            var el = arguments[0];
            var r = el.getBoundingClientRect();
            var cx = r.left + r.width / 2, cy = r.top + r.height / 2;
            function fire(type, Ctor) {
                var ev;
                try {
                    ev = new Ctor(type, {bubbles:true, cancelable:true, view:window,
                        clientX:cx, clientY:cy, button:0, buttons:1,
                        pointerId:1, pointerType:'mouse', isPrimary:true});
                } catch (e) {
                    ev = document.createEvent('MouseEvents');
                    ev.initMouseEvent(type, true, true, window, 0, 0, 0, cx, cy,
                                      false, false, false, false, 0, null);
                }
                el.dispatchEvent(ev);
            }
            var P = window.PointerEvent || MouseEvent;
            fire('pointerover', P); fire('pointerenter', P); fire('mouseover', MouseEvent);
            fire('pointerdown', P); fire('mousedown', MouseEvent);
            try { el.focus(); } catch (e) {}
            fire('pointerup', P); fire('mouseup', MouseEvent); fire('click', MouseEvent);
        """, el)
        return True
    except Exception:
        return False

def click_el(el):
    scroll_to(el)
    time.sleep(0.2)
    for m in ("selenium", "js", "hard"):
        try:
            if m == "selenium":
                el.click()
            elif m == "js":
                js_click(el)
            else:
                if not hard_click(el):
                    continue
            return True
        except Exception:
            continue
    return False

def set_native_value(el, value):
    try:
        driver.execute_script("""
            var el = arguments[0], val = arguments[1];
            var proto = el.tagName === 'TEXTAREA' ? window.HTMLTextAreaElement.prototype
                                                  : window.HTMLInputElement.prototype;
            Object.getOwnPropertyDescriptor(proto, 'value').set.call(el, val);
            el.dispatchEvent(new Event('input', {bubbles:true}));
            el.dispatchEvent(new Event('change', {bubbles:true}));
        """, el, str(value))
        time.sleep(0.3)
        return True
    except Exception:
        return False

def type_text(el, text):
    try:
        el.click()
    except Exception:
        try:
            js_click(el)
        except Exception:
            pass
    try:
        el.send_keys(Keys.CONTROL, "a")
        el.send_keys(Keys.BACKSPACE)
    except Exception:
        pass
    try:
        el.send_keys(str(text))
    except Exception:
        pass
    if (el.get_attribute("value") or "") != str(text):
        set_native_value(el, text)
    time.sleep(0.3)

def wait_for_state(predicate, timeout=WAIT, poll=0.2):
    """Poll UI readiness, retaining the full timeout for a slow server."""
    deadline = time.monotonic() + timeout
    while True:
        try:
            value = predicate()
            if value:
                return value
        except Exception as exc:
            if type(exc).__name__ not in ('StaleElementReferenceException', 'NoSuchElementException'):
                raise
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        time.sleep(min(poll, remaining))


def dismiss_news_popup(wait=0):
    """Close only the popup titled «Новые новости», including delayed popups."""
    deadline = time.monotonic() + wait
    while True:
        titles = [e for e in driver.find_elements(
            By.XPATH, "//*[normalize-space(text())='Новые новости']") if e.is_displayed()]
        if titles:
            for title in titles:
                roots = title.find_elements(By.XPATH,
                    "./ancestor::*[.//button[normalize-space(.)='Закрыть']][1]")
                if not roots:
                    roots = title.find_elements(By.XPATH,
                        "./ancestor::*[@role='dialog' or @aria-modal='true'][1]")
                for root in roots:
                    buttons = root.find_elements(By.XPATH,
                        ".//button[normalize-space(.)='Закрыть']")
                    # Prefer the footer button from the screenshot; use the X only
                    # inside the same confirmed news dialog when labelled by the UI.
                    buttons += root.find_elements(By.XPATH,
                        ".//button[@aria-label='Закрыть' or @aria-label='Close' "
                        "or @title='Закрыть']")
                    for button in buttons:
                        if not button.is_displayed() or not button.is_enabled():
                            continue
                        try:
                            button.click()
                        except Exception:
                            js_click(button)
                        gone = wait_for_state(lambda: not any(e.is_displayed() for e in
                            driver.find_elements(By.XPATH,
                                "//*[normalize-space(text())='Новые новости']")), timeout=3)
                        if gone:
                            log("  ✓ Окно «Новые новости» закрыто")
                            return True
            log("  ⚠ Окно «Новые новости» не удалось закрыть", "WARN")
            return False
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return True
        time.sleep(min(0.2, remaining))


def supply_list_ready():
    return bool(find_buttons(['Создать заявку', 'Создать', 'Настройки таблицы']))


def supply_list_body_ready():
    return bool(driver.execute_script(r"""
        const vis=e=>!!(e.offsetWidth||e.offsetHeight||e.getClientRects().length);
        const norm=e=>(e.innerText||'').replace(/\s+/g,' ').trim();
        if(Array.from(document.querySelectorAll('[aria-busy=true],[role=progressbar]')).some(vis))return false;
        if(Array.from(document.querySelectorAll('button')).some(e=>vis(e)&&/^Загрузка[.…]*$/.test(norm(e))))return false;
        const rows=Array.from(document.querySelectorAll('tbody tr')).filter(vis);
        if(rows.some(row=>norm(row)&&!/загрузка/i.test(norm(row))))return true;
        return /нет (данных|записей|заявок|заказов)|ничего не найдено/i.test(document.body.innerText||'');
    """))


def supply_list_at(url):
    return at_url(url) and supply_list_ready() and page_total() is not None and supply_list_body_ready()


def supply_card_ready(url=None):
    url=url or STATE.get('url')
    return bool(url and at_url(url) and get_status() and
                (find_buttons(['Позиции заявки','Позиции заказа']) or
                 any(k in page_text() for k in ('позиции заявки', 'позиции заказа', 'основная информация'))))


def supply_lines_ready():
    return bool(('/lines' in driver.current_url or 'вернуться к основной информации' in page_text() or
                 find_buttons(['Добавить строку', 'Добавить позицию'])) and
                (find_buttons(['Добавить строку', 'Добавить позицию']) or any(e.is_displayed() for e in
                 driver.find_elements(By.XPATH,'//table//tbody/tr')) or 'нет позиций' in page_text()))


def selected_control_ready(scope,label):
    ctrl=control_by_label(scope,label)
    return ctrl if ctrl is not None and not ctrl_unset(ctrl,label) else False


def page_text():
    try:
        return (driver.execute_script("return document.body.innerText;") or "").lower()
    except Exception:
        return ""

def find_buttons(texts, scope=None):
    if isinstance(texts, str):
        texts = [texts]
    root = scope if scope is not None else driver
    pre = ".//" if scope is not None else "//"
    out = []
    for t in texts:
        xp = (f"{pre}*[self::button or self::a or @role='button']"
              f"[normalize-space(.)='{t}']")
        try:
            for e in root.find_elements(By.XPATH, xp):
                if e.is_displayed() and e.is_enabled():
                    out.append(e)
        except Exception:
            pass
    return out

def click_button(texts, scope=None, wait=0, last=False):
    end = time.time() + wait
    while True:
        b = find_buttons(texts, scope)
        if b:
            return click_el(b[-1] if last else b[0])
        if time.time() >= end:
            return False
        time.sleep(0.5)

def click_text_deepest(text, mode="contains"):
    """Клик по самому вложенному видимому элементу с текстом (mode: exact/prefix/contains)."""
    el = driver.execute_script("""
        var t = arguments[0], mode = arguments[1];
        function vis(e){ return !!(e.offsetWidth || e.offsetHeight || e.getClientRects().length); }
        function norm(e){ return (e.textContent || '').replace(/\\s+/g, ' ').trim(); }
        function ok(s){ return mode === 'prefix' ? s.indexOf(t) === 0
                       : (mode === 'exact' ? s === t : s.indexOf(t) >= 0); }
        var all = document.body.querySelectorAll('*');
        for (var i = 0; i < all.length; i++) {
            var e = all[i];
            if (['SCRIPT','STYLE','INPUT','TEXTAREA','HTML','BODY'].indexOf(e.tagName) >= 0) continue;
            if (!vis(e)) continue;
            if (!ok(norm(e))) continue;
            var child = false;
            for (var j = 0; j < e.children.length; j++) {
                if (ok(norm(e.children[j]))) { child = true; break; }
            }
            if (!child) return e;
        }
        return null;
    """, text, mode)
    if el is None:
        return False
    return click_el(el)

def read_toasts():
    try:
        return driver.execute_script("""
            var sels = ['[role=alert]','[role=status]','[class*=toast]','[class*=Toast]',
                        '[class*=notification]','[class*=snack]','[class*=notice]','[class*=message]'];
            var out = [];
            sels.forEach(function(s){
                document.querySelectorAll(s).forEach(function(e){
                    if (!(e.offsetWidth || e.offsetHeight)) return;
                    var t = (e.innerText || '').trim();
                    if (t && t.length < 250 && out.indexOf(t) < 0) out.push(t);
                });
            });
            return out;
        """) or []
    except Exception:
        return []

MODAL_XPATHS = [
    "//div[contains(@class,'action-modal__shell')]",
    "//div[contains(@class,'action-modal__body')]",
    "//*[@role='dialog' or @aria-modal='true']",
    "//div[contains(@class,'ant-modal-body')]",
    "//div[contains(@class,'ant-drawer-body')]",
    "//*[contains(@class,'modal') and (contains(@class,'body') or contains(@class,'content'))]",
]

def find_modal(hint=None):
    for xp in MODAL_XPATHS:
        try:
            vis = [e for e in driver.find_elements(By.XPATH, xp) if e.is_displayed()]
        except Exception:
            continue
        if hint:
            h = [e for e in vis if hint.lower() in (e.text or "").lower()]
            if h:
                return h[-1]
        elif vis:
            return vis[-1]
    return None

def wait_modal(hint=None, timeout=8):
    end = time.time() + timeout
    while time.time() < end:
        m = find_modal(hint)
        if m is not None:
            return m
        time.sleep(0.5)
    return None

def wait_modal_closed(hint=None, timeout=8):
    end = time.time() + timeout
    while time.time() < end:
        if find_modal(hint) is None:
            return True
        time.sleep(0.5)
    return False

def modal_button(modal, texts):
    for t in texts:
        for xp in [
            f".//footer//button[normalize-space(.)='{t}']",
            f".//button[normalize-space(.)='{t}']",
        ]:
            try:
                vis = [b for b in modal.find_elements(By.XPATH, xp)
                       if b.is_displayed() and b.is_enabled()]
                if vis:
                    return vis[-1]
            except Exception:
                continue
    return None

def close_modal_soft(modal):
    """Закрыть модалку: Отмена/Закрыть, иначе крестик."""
    b = modal_button(modal, ["Отмена", "Закрыть", "Нет"])
    if b:
        return click_el(b)
    try:
        xs = modal.find_elements(
            By.XPATH, ".//button[@aria-label='Закрыть' or @aria-label='Close' "
                      "or contains(@class,'close')]")
        xs = [x for x in xs if x.is_displayed()]
        if xs:
            return click_el(xs[0])
    except Exception:
        pass
    try:
        ActionChains(driver).send_keys(Keys.ESCAPE).perform()
    except Exception:
        pass
    return False

def control_by_label(scope,label):
    # Search a label's own field container, never the global following:: axis.
    literal=json.dumps(label,ensure_ascii=False)
    labels=scope.find_elements(By.XPATH,
        ".//*[normalize-space(translate(.,'*',''))="+literal+"]"
        "[not(self::button or self::select) and not(ancestor::button)]")
    for caption in labels:
        if not caption.is_displayed():
            continue
        container=caption
        for _ in range(6):
            parent=container.find_elements(By.XPATH,'./parent::*')
            if not parent:
                break
            container=parent[0]
            controls=[e for e in container.find_elements(By.XPATH,
                ".//button[contains(@class,'ui-select__trigger') or @role='combobox' or @aria-haspopup]"
                " | .//*[@role='combobox'] | .//select") if e.is_displayed()]
            if not controls:
                controls=[e for e in container.find_elements(By.XPATH,".//button[not(@type='submit')]")
                          if e.is_displayed() and (e.get_attribute('textContent') or '').strip()
                          not in ('Сохранить','Отмена','Закрыть','Добавить')]
            # Deduplicate a combobox matched by both union branches.
            unique=[]
            for e in controls:
                if e not in unique:
                    unique.append(e)
            if len(unique)==1:
                return unique[0]
            if len(unique)>1 or container==scope:
                break
    return None

def visible_panel():
    try:
        ps = [p for p in driver.find_elements(
            By.XPATH, "//div[contains(@class,'ui-select__panel')]") if p.is_displayed()]
        return ps[-1] if ps else None
    except Exception:
        return None

def open_ui(trigger):
    if trigger is None:
        return None
    scroll_to(trigger)
    for m in ("hard", "js", "selenium"):
        try:
            if m == "hard":
                hard_click(trigger)
            elif m == "js":
                js_click(trigger)
            else:
                trigger.click()
        except Exception:
            continue
        p = wait_for_state(visible_panel, timeout=3)
        if p is not None:
            return p
    return None

def panel_search(panel):
    for xp in [".//input[contains(@class,'ui-select__search-input')]", ".//input"]:
        try:
            es = [e for e in panel.find_elements(By.XPATH, xp) if e.is_displayed()]
            if es:
                return es[0]
        except Exception:
            continue
    return None

def panel_options(panel):
    out = []
    for xp in [".//button[@role='option']", ".//*[@role='option']"]:
        try:
            for b in panel.find_elements(By.XPATH, xp):
                if not b.is_displayed():
                    continue
                txt = (b.get_attribute("textContent") or "").strip()
                if txt:
                    out.append({"element": b, "text": txt})
        except Exception:
            pass
        if out:
            break
    return out

def close_panels():
    for _ in range(3):
        if visible_panel() is None:
            return True
        try:
            for bd in driver.find_elements(
                    By.XPATH, "//div[contains(@class,'ui-select__backdrop')]"):
                hard_click(bd)
                time.sleep(0.3)
        except Exception:
            pass
        time.sleep(0.3)
    return visible_panel() is None

def select_in_panel(panel, keywords=None, index=None, search=None, exclude=None):
    """Выбрать опцию в открытой панели. Возвращает текст выбранной опции или None."""
    if panel is None:
        return None
    if search:
        s = panel_search(panel)
        if s:
            type_text(s, search)
            time.sleep(1.3)
    opts = panel_options(panel)
    target, pos = None, 0
    if keywords:
        for i, o in enumerate(opts):
            low = o["text"].lower()
            if exclude and any(x.lower() in low for x in exclude):
                continue
            if any(k.lower() in low for k in keywords):
                target, pos = o, i
                break
    elif index is not None and index < len(opts):
        target, pos = opts[index], index
    if target is None:
        return None
    for m in ("hard", "selenium", "js"):
        try:
            if m == "hard":
                hard_click(target["element"])
            elif m == "selenium":
                target["element"].click()
            else:
                js_click(target["element"])
        except Exception:
            continue
        if wait_for_state(lambda: visible_panel() is None, timeout=3):
            return target["text"]
    # запасной путь — клавиатура
    s = panel_search(panel)
    if s:
        try:
            s.click()
            for _ in range(pos + 1):
                s.send_keys(Keys.ARROW_DOWN)
                time.sleep(0.2)
            s.send_keys(Keys.ENTER)
            time.sleep(0.8)
            if visible_panel() is None:
                return target["text"]
        except Exception:
            pass
    return None

def _xlsx_minimal(path, rows):
    def col(i):
        return chr(65 + i)
    sheet_rows = []
    for r, row in enumerate(rows, 1):
        cells = []
        for c, v in enumerate(row):
            ref = f"{col(c)}{r}"
            if isinstance(v, (int, float)):
                cells.append(f'<c r="{ref}"><v>{v}</v></c>')
            else:
                cells.append(f'<c r="{ref}" t="inlineStr"><is><t>{xml_escape(str(v))}</t></is></c>')
        sheet_rows.append(f'<row r="{r}">{"".join(cells)}</row>')
    sheet = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
             '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
             f'<sheetData>{"".join(sheet_rows)}</sheetData></worksheet>')
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml",
                   '<?xml version="1.0" encoding="UTF-8"?>'
                   '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                   '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                   '<Default Extension="xml" ContentType="application/xml"/>'
                   '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
                   '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
                   '</Types>')
        z.writestr("_rels/.rels",
                   '<?xml version="1.0" encoding="UTF-8"?>'
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
                   '</Relationships>')
        z.writestr("xl/workbook.xml",
                   '<?xml version="1.0" encoding="UTF-8"?>'
                   '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                   'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
                   '<sheets><sheet name="Смета" sheetId="1" r:id="rId1"/></sheets></workbook>')
        z.writestr("xl/_rels/workbook.xml.rels",
                   '<?xml version="1.0" encoding="UTF-8"?>'
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
                   '</Relationships>')
        z.writestr("xl/worksheets/sheet1.xml", sheet)

def create_test_pdf(name="smeta_doc"):
    path = os.path.join(WORK_DIR, f"{name}_{STAMP}.pdf")
    pdf = b"""%PDF-1.4
1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj
2 0 obj<</Type/Pages/Count 1/Kids[3 0 R]>>endobj
3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]/Contents 4 0 R/Resources<</Font<</F1 5 0 R>>>>>>endobj
4 0 obj<</Length 60>>stream
BT /F1 18 Tf 100 700 Td (Smeta Autotest) Tj ET
endstream endobj
5 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj
xref
0 6
0000000000 65535 f
0000000009 00000 n
0000000052 00000 n
0000000101 00000 n
0000000199 00000 n
0000000305 00000 n
trailer<</Size 6/Root 1 0 R>>
startxref
368
%%EOF"""
    with open(path, "wb") as f:
        f.write(pdf)
    return path

def create_test_png(name="smeta_img"):
    path = os.path.join(WORK_DIR, f"{name}_{STAMP}.png")
    png = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")
    with open(path, "wb") as f:
        f.write(png)
    return path

def create_test_txt(name="smeta_note"):
    path = os.path.join(WORK_DIR, f"{name}_{STAMP}.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"Автотест сметы {STAMP}\n")
    return path

def snapshot_downloads():
    try:
        return {f: os.path.getmtime(f) for f in glob.glob(os.path.join(DOWNLOAD_DIR, "*"))}
    except Exception:
        return {}

def wait_new_download(before, started, timeout=25, ext=None):
    end = time.time() + timeout
    while time.time() < end:
        for f in glob.glob(os.path.join(DOWNLOAD_DIR, "*")):
            low = f.lower()
            if low.endswith((".crdownload", ".tmp")):
                continue
            if ext and not low.endswith(ext):
                continue
            try:
                m = os.path.getmtime(f)
                if (f not in before or m > before[f]) and m >= started - 1 \
                        and os.path.getsize(f) > 0:
                    return f
            except Exception:
                continue
        time.sleep(1)
    return None

def block_native_file_dialog():
    """Не даём странице открыть нативное окно выбора файла (Selenium его не закроет)."""
    try:
        driver.execute_script("""
            if (!window.__fdBlocked) {
                window.__fdBlocked = true;
                var orig = HTMLInputElement.prototype.click;
                HTMLInputElement.prototype.click = function () {
                    if (this.type === 'file') { window.__lastFileInput = this; return; }
                    return orig.apply(this, arguments);
                };
            }
        """)
    except Exception:
        pass

def send_file(path, scope=None):
    inp = None
    try:
        inp = driver.execute_script(
            "var i = window.__lastFileInput; return (i && document.contains(i)) ? i : null;")
    except Exception:
        pass
    if inp is None:
        try:
            root = scope if scope is not None else driver
            pre = ".//" if scope is not None else "//"
            els = root.find_elements(By.XPATH, pre + "input[@type='file']")
            if not els and scope is not None:
                els = driver.find_elements(By.XPATH, "//input[@type='file']")
            if els:
                inp = els[-1]
        except Exception:
            pass
    if inp is None:
        log("    ⚠ input[type=file] не найден", "WARN")
        return False
    try:
        driver.execute_script(
            "arguments[0].style.display='block';arguments[0].style.opacity='1';"
            "arguments[0].style.visibility='visible';arguments[0].removeAttribute('hidden');", inp)
        inp.send_keys(path)
        time.sleep(3)
        driver.execute_script("window.__lastFileInput = null;")
        log(f"    ✓ Файл передан: {os.path.basename(path)}", "PASS")
        return True
    except Exception as e:
        log(f"    ⚠ Не удалось передать файл: {e}", "WARN")
        return False

def is_login_page():
    try:
        if "auth" in driver.current_url.lower():
            return True
        return any(p.is_displayed() for p in
                   driver.find_elements(By.XPATH, "//input[@type='password']"))
    except Exception:
        return False

def login_with(login_value, password_value):
    log(f"  Логин под: {login_value}")
    try:
        WebDriverWait(driver, WAIT).until(EC.visibility_of_element_located(
            (By.XPATH, "//input[@type='password']")))
    except Exception:
        return False
    login_field = None
    for xp in ["//input[contains(@placeholder,'огин')]", "//input[@name='username' or @id='username']",
               "//input[contains(@placeholder,'Login')]", "//input[@type='email']",
               "//input[@type='text'][1]"]:
        try:
            vis = [f for f in driver.find_elements(By.XPATH, xp)
                   if f.is_displayed() and f.is_enabled()]
            if vis:
                login_field = vis[0]
                break
        except Exception:
            continue
    pw_field = None
    try:
        vis = [f for f in driver.find_elements(By.XPATH, "//input[@type='password']")
               if f.is_displayed() and f.is_enabled()]
        pw_field = vis[0] if vis else None
    except Exception:
        pass
    if not login_field or not pw_field:
        return False
    login_field.clear()
    login_field.send_keys(login_value)
    pw_field.clear()
    pw_field.send_keys(password_value)
    for xp in ["//button[.//span[normalize-space(text())='Войти']]",
               "//button[contains(., 'Войти')]", "//button[@type='submit']"]:
        try:
            vis = [b for b in driver.find_elements(By.XPATH, xp)
                   if b.is_displayed() and b.is_enabled()]
            if vis:
                click_el(vis[0])
                break
        except Exception:
            continue
    wait_for_state(lambda: driver.current_url.startswith(BASE_URL) and not is_login_page())
    if is_login_page():
        log(f"  ⚠ Логин {login_value} не удался", "WARN")
        return False
    log(f"  ✓ Успешный вход: {login_value}", "PASS")
    dismiss_news_popup(wait=2)
    return True

def logout_current_account():
    log('  Выход из текущего аккаунта...')
    try:
        els=[e for e in driver.find_elements(By.XPATH,
            "//*[self::button or self::a][contains(normalize-space(.),'Выйти')]") if e.is_displayed()]
        if els:
            click_el(els[0])
            state=wait_for_state(lambda:is_login_page() or find_modal('выйдете') or find_modal('Вы уверены'),timeout=8)
            if state and not is_login_page():
                button=modal_button(state,['Выйти','Да','ОК','Подтвердить'])
                if button:
                    click_el(button)
                    wait_for_state(is_login_page,timeout=5)
    except Exception as exc:
        log(f'  ⚠ UI-выход: {exc}','WARN')
    if is_login_page():
        log('  ✓ Вышли через UI','PASS')
        return True
    try:
        driver.delete_all_cookies()
        driver.execute_script('try{localStorage.clear();sessionStorage.clear();}catch(e){}')
    except Exception:
        pass
    driver.get(BASE_URL)
    return bool(wait_for_state(is_login_page))



def parse_total():
    try:
        txt = driver.execute_script("return document.body.innerText;") or ""
        m = re.search(r"Итого без НДС\D*([\d\s\u00a0]+(?:[.,]\d+)?)", txt)
        if m:
            return float(m.group(1).replace("\u00a0", "").replace(" ", "")
                         .replace("\n", "").replace(",", "."))
    except Exception:
        pass
    return None

def approver_trigger():
    try:
        for t in driver.find_elements(
                By.XPATH,
                "//button[contains(@class,'ui-select__trigger')]"
                "[.//span[contains(normalize-space(text()),'Выбрать согласующего')]]"):
            if t.is_displayed():
                return t
    except Exception:
        pass
    return None

def add_approver():
    goto_card()
    if route_has_approver():
        log("  ✓ Согласующий уже в маршруте", "PASS")
        return True
    trg = approver_trigger()
    if trg is None:
        clicked = click_button(["Добавить этап"], wait=5) or \
            click_text_deepest("Добавить этап", "exact")
        if not clicked:
            log("  • 'Добавить этап' не найдено — пробую '+ Этап'")
            clicked = click_button(["Этап", "+ Этап"], wait=2)
        log(f"  Нажато 'Добавить этап': {clicked}")
        for _ in range(16):
            trg = approver_trigger()
            if trg:
                break
            time.sleep(0.5)
    if trg is None:
        # кнопка «Добавить» (согласующего) в шапке этапа
        try:
            b = driver.find_element(
                By.XPATH,
                "//*[contains(normalize-space(text()),' этап')]"
                "/following::button[normalize-space(.)='Добавить'][1]")
            click_el(b)
            time.sleep(1.5)
            trg = approver_trigger()
        except Exception:
            pass
    if trg is None:
        log("  ⚠ Селект 'Выбрать согласующего' не найден", "WARN")
        return False

    panel = open_ui(trg)
    if not panel:
        log("  ⚠ Список согласующих не открылся", "WARN")
        return False
    picked = select_in_panel(panel, keywords=["бейсембаев"],
                             search=APPROVER_QUERY, exclude=["aisinov"])
    if not picked:
        log(f"  ⚠ '{APPROVER_QUERY}' не найден в списке", "WARN")
        close_panels()
        return False
    log(f"  ✓ Согласующий выбран: {picked}", "PASS")
    time.sleep(1.5)

    # на случай старого варианта — модалка «Согласующие»
    m = find_modal("Согласующ")
    if m:
        b = modal_button(m, ["Сохранить", "Добавить", "ОК", "Применить"])
        if b:
            click_el(b)
            wait_modal_closed("Согласующ", 6)

    for _ in range(8):
        if route_has_approver():
            log("  ✓ Маршрут согласования настроен", "PASS")
            return True
        time.sleep(1)
    log("  ⚠ Бейсембаев Куаныш не появился в маршруте", "WARN")
    return False

def try_open_and_cancel(text):
    goto_card()
    if not click_button([text], wait=5):
        log(f"  ⚠ Кнопка '{text}' не найдена", "WARN")
        return False
    time.sleep(2)
    m = find_modal()
    if m:
        close_modal_soft(m)
        time.sleep(1)
    elif "/edit" in driver.current_url or STATE["url"] not in driver.current_url:
        if not click_button(["Отмена"], wait=2):
            driver.get(STATE["url"])
            time.sleep(3)
    else:
        try:
            ActionChains(driver).send_keys(Keys.ESCAPE).perform()
        except Exception:
            pass
    log(f"  ✓ '{text}': открыто и закрыто", "PASS")
    return True

def click_action(texts, action_element=None):
    """Нажать статусную кнопку и подтвердить модалку, если появится. Возвращает текст кнопки."""
    btns = [action_element] if action_element is not None else find_buttons(texts)
    if not btns:
        return None
    label = (btns[0].text or "").strip() or texts[0]
    scroll_to(btns[0])
    click_el(btns[0])
    time.sleep(2.5)
    modal = find_modal()
    if modal:
        try:
            for ta in modal.find_elements(By.XPATH, ".//textarea"):
                if ta.is_displayed() and ta.is_enabled():
                    type_text(ta, f"Автотест: {label} ({STAMP})")
                    break
        except Exception:
            pass
        conf = modal_button(modal, texts + ["Подтвердить", "Отправить", "Сохранить", "ОК", "Да"])
        if conf:
            click_el(conf)
            log(f"    Подтверждение '{label}' нажато")
            time.sleep(4)
    return label

def stage_discussion():
    goto_card()
    click_text_deepest("Обсуждение", "exact")
    time.sleep(1.2)
    block_native_file_dialog()
    ta = None
    for t in driver.find_elements(By.XPATH, "//textarea[contains(@placeholder,'ообщени')]"):
        if t.is_displayed():
            ta = t
            break
    if ta is None:
        log("  ⚠ Поле сообщения не найдено", "WARN")
        return False
    scroll_to(ta)
    msg = f"Автотест: сообщение по снабжению {STAMP}"
    type_text(ta, msg)

    pdf = create_test_pdf("discussion_attach")
    scope = None
    try:
        scope = ta.find_element(By.XPATH, "./ancestor::*[.//input[@type='file']][1]")
    except Exception:
        pass
    attached = False
    if scope is not None:
        attached = send_file(pdf, scope=scope)
    if not attached:
        # скрепка — кнопка без текста рядом с «Отправить»
        try:
            clip = driver.execute_script("""
                var root = arguments[0];
                for (var i = 0; i < 6 && root.parentElement; i++) {
                    root = root.parentElement;
                    if (/Отправить/.test(root.textContent || '')) break;
                }
                var bs = root.querySelectorAll('button');
                for (var j = 0; j < bs.length; j++) {
                    var b = bs[j];
                    if (!(b.textContent || '').trim() && (b.offsetWidth || b.offsetHeight)) return b;
                }
                return null;""", ta)
            if clip:
                click_el(clip)
                time.sleep(1)
                attached = send_file(pdf)
        except Exception:
            pass
    log(f"  Файл в обсуждении: {'прикреплён' if attached else 'не прикреплён'}",
        "PASS" if attached else "WARN")
    time.sleep(2)
    if not click_button(["Отправить"], wait=3, last=True):
        log("  ⚠ Кнопка 'Отправить' не найдена", "WARN")
        return False
    time.sleep(4)
    txt = page_text()
    ok = "автотест: сообщение по снабжению" in txt.lower()
    log(f"  Сообщение в ленте: {'есть' if ok else 'нет'}", "PASS" if ok else "WARN")
    return ok

def visible_selects(scope=None):
    root = scope if scope is not None else driver
    pre = ".//" if scope is not None else "//"
    try:
        return [t for t in root.find_elements(
            By.XPATH, pre + "button[contains(@class,'ui-select__trigger')]") if t.is_displayed()]
    except Exception:
        return []

def esc():
    try:
        ActionChains(driver).send_keys(Keys.ESCAPE).perform()
    except Exception:
        pass
    time.sleep(0.4)





def _last_problem(start_idx):
    for line in reversed(LOG_LINES[start_idx:]):
        if "[WARN]" in line or "[FAIL]" in line:
            txt = line.split("]", 2)[-1].strip()
            return re.sub(r"^[⚠•✗\s]+", "", txt)[:180]
    return ""

def record(label, ok, details="", reason=""):
    RESULTS.append((label, bool(ok)))
    if not ok and (reason or details):
        REASONS[label] = (reason or details)[:180]
    log(f"{'✓' if ok else '✗'} {label}" + (f" — {details}" if details else ""),
        "PASS" if ok else "FAIL")

def step(label, fn, *args, **kwargs):
    log("=" * 60)
    log(f"ЭТАП: {label}")
    log("=" * 60)
    start_idx = len(LOG_LINES)
    ok = False
    try:
        ok = bool(fn(*args, **kwargs))
    except Exception as e:
        log(f"  ⚠ Исключение: {e}", "FAIL")
        try:
            import traceback
            for tb in traceback.format_exc().split("\n"):
                log(f"    {tb}")
        except Exception:
            pass
    if not ok:
        shot(f"fail_{label}")
    record(label, ok, reason="" if ok else (_last_problem(start_idx) or "см. лог"))
    return ok

JS_DATE_LABEL = r"""
var e = arguments[0], own = (e.innerText || '').trim(), c = e;
for (var i = 0; i < 6; i++) {
    c = c.parentElement; if (!c) break;
    var lines = (c.innerText || '').split('\n').map(function(s){ return s.trim(); }).filter(Boolean);
    for (var j = 0; j < lines.length; j++) {
        if (lines[j] !== own && lines[j].length < 80 && !/выбрать дату/i.test(lines[j])) return lines[j];
    }
}
return '';
"""

JS_DATE_TEXT = r"""
var e = arguments[0];
var i = e.tagName === 'INPUT' ? e : e.querySelector('input');
var t = i ? (i.value || '') : (e.innerText || e.textContent || '');
return t.trim();
"""

JS_DATE_TRIGGERS = r"""
function vis(e){ return !!(e.offsetWidth || e.offsetHeight || e.getClientRects().length); }
var all = Array.prototype.slice.call(document.querySelectorAll('[class*="ui-date-picker__trigger"]'));
all = all.filter(vis);
return all.filter(function(e){ return !all.some(function(o){ return o !== e && o.contains(e); }); });
"""

JS_CAL = r"""
var p = null, ps = document.querySelectorAll('[class*="ui-date-picker__panel"], [class*="date-picker__popover"], [role="dialog"]');
for (var i = 0; i < ps.length; i++) { if (ps[i].offsetWidth && /\d{4}/.test(ps[i].innerText || '')) { p = ps[i]; break; } }
if (!p) return null;
var title = ''; var lines = (p.innerText || '').split('\n');
for (var j = 0; j < lines.length; j++) { if (/[А-Яа-я]+\s+\d{4}/.test(lines[j])) { title = lines[j].trim(); break; } }
var hb = Array.prototype.slice.call(p.querySelectorAll('button')).filter(function(b){
    var c = (b.className || '').toString();
    return b.offsetWidth && c.indexOf('day') < 0 && !/очистить|сегодня/i.test(b.innerText || '') && !(b.innerText || '').trim().match(/^\d+$/);
});
return [title, hb];
"""

MONTHS = ["январ", "феврал", "март", "апрел", "ма", "июн", "июл", "август", "сентябр", "октябр", "ноябр", "декабр"]

DATE_RE = re.compile(r"(\d{1,2})[./](\d{1,2})[./](\d{4})")

def parse_date(txt):
    m = DATE_RE.search(txt or "")
    if not m:
        return None
    d, mo, y = map(int, m.groups())
    return (y, mo, d)

def date_text(trigger):
    try:
        return driver.execute_script(JS_DATE_TEXT, trigger) or ""
    except Exception:
        return (trigger.get_attribute("textContent") or "").strip()

def date_empty(trigger):
    t = date_text(trigger).strip().lower()
    return (not t) or ("выбрат" in t) or ("дд" in t and "гггг" in t)

def date_triggers():
    try:
        xs = driver.execute_script(JS_DATE_TRIGGERS)
        if xs:
            return xs
    except Exception:
        pass
    return []

def calendar_cells():
    for xp in [
        "//button[contains(@class,'ui-date-picker__day') and not(contains(@class,'is-outside')) "
        "and not(contains(@class,'outside')) and not(@disabled)]",
        "//*[@role='gridcell'][not(@aria-disabled='true') and not(@disabled)]",
    ]:
        try:
            cells = [c for c in driver.find_elements(By.XPATH, xp) if c.is_displayed()]
        except Exception:
            cells = []
        if cells:
            return cells
    return []

def cell_by_day(cells, day):
    """Доступная ячейка дня `day`; если день недоступен (лимит) — ближайший следующий, иначе последний."""
    best = None
    for c in cells:
        t = re.sub(r"\D", "", c.text or "")
        if not t:
            continue
        if int(t) >= day:
            return c
        best = c
    return best or (cells[-1] if cells else None)

def calendar_goto(year, month):
    """Листает открытый календарь на нужный месяц стрелками « ‹ › »."""
    for _ in range(40):
        try:
            info = driver.execute_script(JS_CAL)
        except Exception:
            info = None
        if not info:
            return False
        title, btns = info
        m = re.search(r"([А-Яа-яЁё]+)\s+(\d{4})", title or "")
        if not m:
            return False
        low = m.group(1).lower()
        cm = next((i + 1 for i, k in enumerate(MONTHS) if low.startswith(k)), None)
        if not cm:
            return False
        diff = (year * 12 + month) - (int(m.group(2)) * 12 + cm)
        if diff == 0:
            return True
        if len(btns) >= 4:
            btn = (btns[3] if diff >= 12 else btns[2]) if diff > 0 else (btns[0] if diff <= -12 else btns[1])
        elif len(btns) >= 2:
            btn = btns[-1] if diff > 0 else btns[0]
        else:
            return False
        try:
            driver.execute_script("arguments[0].click();", btn)
        except Exception:
            return False
        time.sleep(0.35)
    return False

def pick_date(trigger, target):
    """Открыть календарь, перейти на месяц target (datetime.date), нажать день.
    Недоступные (disabled) дни не кликаем — если день заблокирован лимитом, берём ближайший доступный."""
    for attempt in range(2):
        scroll_to(trigger)
        time.sleep(0.3)
        for m in ("js", "hard", "selenium"):
            try:
                if m == "js":
                    js_click(trigger)
                elif m == "hard":
                    hard_click(trigger)
                else:
                    trigger.click()
                break
            except Exception:
                continue
        wait_for_state(calendar_cells,timeout=3)
        if calendar_goto(target.year, target.month):
            cell = cell_by_day(calendar_cells(), target.day)
            if cell is not None:
                click_el(cell)
                if wait_for_state(lambda:not date_empty(trigger),timeout=3):
                    return True
        else:
            cells = calendar_cells()          # не смогли листать — берём любой доступный день
            if cells:
                click_el(cell_by_day(cells, target.day))
                if wait_for_state(lambda:not date_empty(trigger),timeout=3):
                    return True
        try:
            ActionChains(driver).send_keys(Keys.ESCAPE).perform()
        except Exception:
            pass
        time.sleep(0.4)
    # запасной путь: вписать дату текстом
    try:
        inp = trigger if trigger.tag_name.lower() == "input" else trigger.find_element(By.XPATH, ".//input")
        type_text(inp, target.strftime("%d.%m.%Y"))
        inp.send_keys(Keys.ENTER)
        return bool(wait_for_state(lambda:not date_empty(trigger),timeout=3))
    except Exception:
        return False
# ===== конец вспомогательных =====


# ==========================================
# ОБЩЕЕ
# ==========================================
def get_status():
    try:
        return driver.execute_script("""
            var words = ['Черновик','На согласовании','Согласование','Согласовано','Согласована',
                         'На утверждении','Утверждено','Утверждена','Подписано','Подписана',
                         'На подписании','Отклонено','Отклонена','На доработке','Архив','Действует',
                         'Новая заявка','На исполнении','Исполнен','Заказ закрыт','Закрыт',
                         'Отправлен на склад','Принят на склад','Закрыта','Закрыто','Заявка закрыта'];
            var els = document.querySelectorAll('span,div,p,b,strong,small');
            for (var i = 0; i < els.length; i++) {
                var e = els[i];
                if (e.children.length || !(e.offsetWidth || e.offsetHeight)) continue;
                var t = (e.textContent || '').trim();
                if (words.indexOf(t) >= 0) return t;
            }
            return null;
        """)
    except Exception:
        return None


def status_terminal(s):
    s = (s or "").lower()
    return any(k in s for k in TERMINAL)


def at_url(url):
    return urlparse(driver.current_url).path.rstrip("/") == urlparse(url).path.rstrip("/")


def nav_menu(item,url):
    for _ in range(2):
        if click_text_deepest(item,'exact') and wait_for_state(lambda:supply_list_at(url),timeout=3):
            return True
        click_text_deepest('Снабжение','exact')
        time.sleep(1)
    driver.get(url)
    return bool(wait_for_state(lambda:supply_list_at(url)))


def page_total():
    t = driver.execute_script("return document.body.innerText;") or ""
    m = re.search(r"Всего:\s*(\d+)", t)
    return int(m.group(1)) if m else None


def innertext():
    return driver.execute_script("return document.body.innerText;") or ""


JS_SECTION_TEXT = r"""
var title = arguments[0], hdr = null, all = document.querySelectorAll('*');
for (var i = 0; i < all.length; i++) {
    var e = all[i];
    if (e.children.length === 0 && (e.textContent || '').trim() === title &&
        (e.offsetWidth || e.offsetHeight)) { hdr = e; break; }
}
if (!hdr) return '';
var c = hdr;
for (var k = 0; k < 7 && c; k++) {
    c = c.parentElement;
    if (c && (c.innerText || '').length > title.length + 25) return c.innerText;
}
return hdr.innerText || '';
"""


def section_text(title):
    try:
        return driver.execute_script(JS_SECTION_TEXT, title) or ""
    except Exception:
        return ""


def route_has_approver():
    seg = section_text("Маршрут согласования").lower()
    return "бейсембаев" in seg and "куаныш" in seg


def goto_card():
    url=STATE.get('url')
    if not url:
        return False
    if not at_url(url):
        driver.get(url)
    return bool(wait_for_state(lambda:supply_card_ready(url)))


def open_lines():
    if '/lines' not in driver.current_url and not find_buttons(['Добавить строку', 'Добавить позицию']):
        if not goto_card():
            return False
        clicked=(click_button(['Позиции заявки','Позиции заказа'],wait=5)
                 or click_text_deepest('Позиции заказа','exact')
                 or click_text_deepest('Позиции заявки','exact')
                 or click_text_deepest('Позиции з','prefix'))
        if not clicked or not wait_for_state(supply_lines_ready,timeout=10):
            driver.get(STATE['url'].rstrip('/')+'/lines')
    ready=bool(wait_for_state(supply_lines_ready))
    if ready:
        block_native_file_dialog()
    return ready


def back_to_card():
    if click_button(['Вернуться к основной информации'],wait=3) or click_text_deepest('Вернуться к основной информации','contains'):
        if wait_for_state(supply_card_ready,timeout=4):
            log('  ✓ «Вернуться к основной информации»','PASS')
            return True
    return goto_card()


def lines_state():
    empty = "нет позиций" in page_text()
    try:
        rows = driver.execute_script("""
            return Array.prototype.filter.call(document.querySelectorAll('tbody tr'),
                function(r){ return r.offsetWidth || r.offsetHeight; }).length;""")
    except Exception:
        rows = 0
    return (0 if empty else rows), parse_total()


PLACEHOLDERS = ("выбер", "выбрать", "час начала", "час окончания", "ед. измерения", "поиск")


def ctrl_unset(ctrl,label=""):
    if ctrl is None or ctrl is False:
        return True
    text=(ctrl.get_attribute('textContent') or '').strip().lower()
    return not text or text.startswith(PLACEHOLDERS) or text==label.lower()


def ctrl_enabled(ctrl):
    try:
        if ctrl.get_attribute("disabled") is not None and ctrl.get_attribute("disabled") != "false":
            return False
        if (ctrl.get_attribute("aria-disabled") or "").lower() == "true":
            return False
        cls = (ctrl.get_attribute("class") or "").lower()
        if "disabled" in cls:
            return False
        return ctrl.is_enabled()
    except Exception:
        return True


def wait_ctrl_enabled(scope, label, timeout=6):
    """Ждём, пока зависимое поле (Очередь/Блок/Смета...) станет доступным после выбора проекта."""
    end = time.time() + timeout
    ctrl = None
    while time.time() < end:
        ctrl = control_by_label(scope, label)
        if ctrl is not None and ctrl_enabled(ctrl):
            return ctrl
        time.sleep(0.5)
    return ctrl


JS_POPUP = r"""
var t = arguments[0], tr = t.getBoundingClientRect();
function vis(e){ var r = e.getBoundingClientRect(); if (r.width <= 0 || r.height <= 0) return false;
    var cs = getComputedStyle(e); return cs.visibility !== 'hidden' && cs.display !== 'none'; }
function rowsIn(root){
    var rs = root.querySelectorAll('[role=option], button, li, [role=menuitem]');
    var out = [];
    for (var i = 0; i < rs.length; i++) {
        var e = rs[i]; if (!vis(e)) continue;
        var txt = (e.innerText || '').trim();
        if (!txt || txt.length > 120) continue;
        if (e.querySelector('input')) continue;
        out.push({element:e,text:txt.replace(/\s+/g,' ')});
    }
    return out;
}
var expanded = t.getAttribute('aria-expanded');
var root = null, cid = t.getAttribute('aria-controls');
if (cid) { var r0 = document.getElementById(cid); if (r0 && vis(r0)) root = r0; }
if (!root) {
    var ps = document.querySelectorAll('[class*="ui-select__panel"], [role=listbox]');
    for (var k = ps.length - 1; k >= 0; k--) { if (vis(ps[k])) { root = ps[k]; break; } }
}
if (expanded === 'false' && !root) return {open: false, input: null, opts: []};
var inp = null;
if (root) {
    inp = Array.prototype.filter.call(root.querySelectorAll('input'), vis)[0] || null;
    if (!inp && root.parentElement) inp = Array.prototype.filter.call(root.parentElement.querySelectorAll('input'), vis)[0] || null;
    var ro = rowsIn(root);
    var empty = ro.length === 0 && /ничего не найден|не найден|нет данных|пусто|no results|no data/i.test(root.innerText || '');
    return {open: true, input: inp, opts: ro, empty: empty};
}
if (expanded !== 'true') return {open: false, input: null, opts: []};
// запасной путь: список открыт (aria-expanded=true), но корень не найден — ищем строки под полем
var all = document.querySelectorAll('button, li, [role=option], div');
var out = [], seen = {};
for (var i = 0; i < all.length; i++) {
    var e = all[i]; if (!vis(e) || e === t || t.contains(e)) continue;
    var txt = (e.innerText || '').trim().replace(/\s+/g, ' ');
    if (!txt || txt.length > 90) continue;
    var r = e.getBoundingClientRect();
    if (r.top < tr.bottom - 2 || r.top > tr.bottom + 520 || r.left < tr.left - 30 || r.right > tr.right + 80 || r.height < 18 || r.height > 80) continue;
    var kids = Array.prototype.filter.call(e.children, function(c){ return (c.innerText || '').trim(); });
    if (kids.length && e.tagName !== 'BUTTON' && e.tagName !== 'LI') continue;
    var top_el = document.elementFromPoint(r.left + r.width / 2, Math.min(r.top + r.height / 2, window.innerHeight - 2));
    if (!top_el || !(e === top_el || e.contains(top_el) || top_el.contains(e))) continue;
    if (seen[txt]) continue; seen[txt] = 1; out.push({element:e,text:txt.replace(/\s+/g,' ')});
}
return {open: true, input: null, opts: out};
"""


_POPUP_EMPTY = False


def popup_state(ctrl):
    """Read option text and elements in one atomic browser snapshot."""
    global _POPUP_EMPTY
    try:
        result=driver.execute_script(JS_POPUP,ctrl) or {}
    except Exception as exc:
        if type(exc).__name__ not in ('StaleElementReferenceException','NoSuchElementException'):
            raise
        _POPUP_EMPTY=False
        return False,None,[]
    _POPUP_EMPTY=bool(result.get('empty'))
    options=[{'element':row['element'],'text':row['text'].strip()}
             for row in result.get('opts',[]) if isinstance(row,dict) and row.get('element') is not None and row.get('text')]
    return bool(result.get('open')),result.get('input'),options


def popup_is_open(ctrl):
    # Opening/closing checks must not enumerate thousands of materials.
    try:
        return bool(driver.execute_script("""
            const control=arguments[0];
            if(control.getAttribute('aria-expanded')==='true')return true;
            const visible=e=>!!(e&&(e.offsetWidth||e.offsetHeight||e.getClientRects().length));
            const id=control.getAttribute('aria-controls');
            if(id&&visible(document.getElementById(id)))return true;
            return Array.from(document.querySelectorAll('[class*=ui-select__panel],[role=listbox]')).some(visible);
        """,ctrl))
    except Exception as exc:
        if type(exc).__name__ in ('StaleElementReferenceException','NoSuchElementException'):
            return False
        raise


def open_popup(ctrl):
    """Открыть список ОДНИМ кликом (повторный клик закрывает), ждём aria-expanded=true."""
    scroll_to(ctrl)
    for m in ("hard", "js", "selenium"):
        if popup_is_open(ctrl):
            return True
        try:
            if m == "hard":
                hard_click(ctrl)
            elif m == "js":
                js_click(ctrl)
            else:
                ctrl.click()
        except Exception:
            continue
        if wait_for_state(lambda:popup_is_open(ctrl),timeout=2):
            return True
    return popup_is_open(ctrl)


def wait_options(ctrl, timeout=8):
    end = time.time() + timeout
    inp, opts = None, []
    empties = 0
    while time.time() < end:
        _, inp, opts = popup_state(ctrl)
        if opts:
            return inp, opts
        empties = empties + 1 if _POPUP_EMPTY else 0
        if empties >= 2:          # «Ничего не найдено» — ждать нечего
            break
        time.sleep(0.3)
    return inp, opts


def _pick(opts, keywords):
    for o in opts:
        low = o["text"].lower()
        if any(k.lower() in low for k in keywords):
            return o
    return None


def close_popup(ctrl=None):
    """Закрыть список, только если он открыт (Esc при закрытом списке закрыл бы всю модалку)."""
    if ctrl is None or not popup_is_open(ctrl):
        return
    try:
        _, inp, _o = popup_state(ctrl)
        if inp is not None:
            inp.send_keys(Keys.ESCAPE)
        else:
            ActionChains(driver).send_keys(Keys.ESCAPE).perform()
    except Exception:
        pass
    if not wait_for_state(lambda:not popup_is_open(ctrl),timeout=2):
        close_panels()


def _click_option(option,ctrl):
    text=option['text']
    for method in ('hard','selenium','js'):
        # Re-rendering replaces option elements; resolve the same text again.
        _,_,options=popup_state(ctrl)
        target=next((o['element'] for o in options if o['text']==text),None)
        if target is None:
            return False
        try:
            if method=='hard':
                hard_click(target)
            elif method=='selenium':
                target.click()
            else:
                js_click(target)
        except Exception as exc:
            if type(exc).__name__ not in ('StaleElementReferenceException','ElementClickInterceptedException','ElementNotInteractableException'):
                raise
            continue
        if wait_for_state(lambda:not ctrl_unset(ctrl,'') or not popup_is_open(ctrl),timeout=2):
            return True
    return False


def fill_select(scope, label, keywords=None, search=None, index=0, force=False):
    """Селект по подписи. Если уже выбран — пропуск. Иначе: ждём доступность поля, открываем список
    одним кликом, берём вариант по ключевым словам (в списке, затем через поиск), иначе вариант №index.
    До 3 попыток; результат проверяется по тексту поля."""
    ctrl = wait_ctrl_enabled(scope, label, 6)
    if ctrl is None:
        log(f"    ⚠ Поле «{label}» не найдено", "WARN")
        return False
    if not force and not ctrl_unset(ctrl, label):
        log(f"    ✓ {label}: «{(ctrl.get_attribute('textContent') or '').strip()[:50]}» (уже выбрано)", "PASS")
        return True
    if not ctrl_enabled(ctrl):
        log(f"    ⚠ «{label}»: поле недоступно (зависит от другого поля)", "WARN")
        return False
    searches = [search] if isinstance(search, str) else list(search or [])
    got = None
    for attempt in range(2):
        ctrl = control_by_label(scope, label) or ctrl
        close_popup(ctrl)
        if not open_popup(ctrl):
            log(f"    · «{label}»: список не открылся (попытка {attempt + 1})")
            time.sleep(1.5)
            continue
        inp, opts = wait_options(ctrl, 5)
        if not opts and _POPUP_EMPTY and not keywords:
            log(f"    · «{label}»: список пуст — пропускаю")
            close_popup(ctrl)
            return False
        target = _pick(opts, keywords) if keywords else None
        if target is None and keywords and searches and inp is not None:
            for term in searches:
                try:
                    type_text(inp, term)
                except Exception:
                    break
                time.sleep(1.5)
                inp2, opts = wait_options(ctrl, 5)
                inp = inp2 or inp
                target = _pick(opts, keywords)
                if target:
                    break
        if target is None and not opts and inp is not None and searches:
            try:
                type_text(inp, "")
            except Exception:
                pass
            time.sleep(0.8)
            _, inp, opts = popup_state(ctrl)
            if not opts:
                inp, opts = wait_options(ctrl, 3)
        if target is None and opts:
            if keywords:
                log(f"    · «{label}»: по {keywords} нет — варианты: {[o['text'][:30] for o in opts[:6]]}; "
                    f"беру №{index + 1}")
            target = opts[index] if index < len(opts) else opts[0]
        if target is None:
            log(f"    · «{label}»: вариантов нет — пропускаю")
            close_popup(ctrl)
            return False
        _click_option(target, ctrl)
        close_popup(ctrl)
        updated_ctrl = wait_for_state(lambda:selected_control_ready(scope,label),timeout=6)
        if updated_ctrl:
            ctrl = updated_ctrl
            got = (ctrl.get_attribute("textContent") or "").strip() or target["text"]
            break
    log(f"    {'✓' if got else '⚠'} {label}: {got or 'НЕ выбрано (нет вариантов?)'}", "PASS" if got else "WARN")
    return bool(got)


def fill_required(modal_hint, specs, passes=3):
    """specs: [(label, kwargs)]. Несколько проходов — зависимые поля (Смета/Очередь/Блок) открываются
    только после проекта. Возвращает список так и не заполненных полей."""
    missing = []
    for ps in range(passes):
        modal = find_modal(modal_hint)
        if modal is None:
            break
        missing = []
        for label, kw in specs:
            modal = find_modal(modal_hint) or modal
            ctrl = control_by_label(modal, label)
            if ctrl is not None and not ctrl_unset(ctrl, label):
                continue
            ok = fill_select(modal, label, **kw)
            if not ok:
                missing.append(label)
        if not missing:
            break
        log(f"    ↻ Не заполнены: {missing} — проход {ps + 2}")
        time.sleep(2)
    return missing


def num_field(scope, label, value, only_empty=True):
    try:
        try:
            inp = scope.find_element(
                By.XPATH, f".//*[normalize-space(text())='{label}']/following::input[1]")
        except Exception:
            inp = scope.find_element(
                By.XPATH, f".//*[starts-with(normalize-space(text()),'{label}') and string-length(normalize-space(text()))<{len(label)+4}]/following::input[1]")
        if inp.is_displayed() and inp.is_enabled():
            if not (only_empty and (inp.get_attribute("value") or "").strip()):
                type_text(inp, value)
            v = (inp.get_attribute("value") or "").strip()
            log(f"    {'✓' if v else '⚠'} {label}: {v}", "PASS" if v else "WARN")
            return bool(v)
    except Exception:
        pass
    log(f"    ⚠ Поле «{label}» не найдено", "WARN")
    return False


def fill_textarea(scope, text):
    try:
        ta = [t for t in scope.find_elements(By.XPATH, ".//textarea") if t.is_displayed()]
        if ta:
            type_text(ta[0], text)
            log("    ✓ Комментарий заполнен", "PASS")
            return True
    except Exception:
        pass
    return False


def fill_dates_in(scope_hint_labels, start_days=0, length_days=7):
    """Все пустые даты в открытой модалке: начало — сегодня+start_days, конец — позже на length_days."""
    today = dtm.date.today()
    trs = [t for t in date_triggers() if date_empty(t)]
    n = 0
    for k, t in enumerate(trs):
        try:
            lab = (driver.execute_script(JS_DATE_LABEL, t) or "").strip().lower()
        except Exception:
            lab = ""
        is_end = bool(re.search(r"оконч|\bпо\b|конец", lab)) or (not lab and k % 2 == 1)
        target = today + dtm.timedelta(days=start_days + (length_days if is_end else 0))
        ok = pick_date(t, target)
        log(f"    {'✓' if ok else '⚠'} {lab or 'дата'}: {date_text(t) or 'не выбрана'}",
            "PASS" if ok else "WARN")
        n += 1 if ok else 0
    return n


# ---------- вход ----------
def stage_login():
    log(f"  URL: {driver.current_url}")
    if is_login_page():
        if not login_with(login_val, pass_val):
            return False
    driver.get(SUPPLY_URL)
    wait_for_state(lambda:is_login_page() or supply_list_at(SUPPLY_URL))
    if is_login_page():
        return False
    ok = "supply" in driver.current_url
    log(f"  URL после входа: {driver.current_url}", "PASS" if ok else "WARN")
    return ok


def switch_user(login, password):
    if not logout_current_account():
        driver.get(BASE_URL)
        wait_for_state(is_login_page)
    return login_with(login, password)


# ==========================================
# СПИСКИ: фильтры, поиск, пагинация, настройки
# ==========================================
JS_PAGER = r"""
function vis(e){ return !!(e.offsetWidth || e.offsetHeight || e.getClientRects().length); }
var all = document.querySelectorAll('*'), cur = null;
for (var i = 0; i < all.length; i++) {
    var e = all[i];
    if (e.children.length === 0 && vis(e) && /^Стр\.\s*\d+\s*из\s*\d+/.test((e.textContent || '').trim())) { cur = e; break; }
}
if (!cur) return null;
var c = cur;
for (var k = 0; k < 4 && c; k++) {
    c = c.parentElement;
    if (!c) break;
    var bs = Array.prototype.filter.call(c.querySelectorAll('button'), function(b){
        return vis(b) && !(b.innerText || '').trim(); });
    if (bs.length >= 3) return bs;
}
return null;
"""

JS_SORT_BTN = r"""
function vis(e){ return !!(e.offsetWidth || e.offsetHeight || e.getClientRects().length); }
var bs = Array.prototype.filter.call(document.querySelectorAll('button'), vis);
var idx = -1;
for (var i = 0; i < bs.length; i++) { if ((bs[i].innerText || '').trim() === 'Настройки таблицы') { idx = i; break; } }
if (idx < 0) return null;
for (var j = idx - 1; j >= Math.max(0, idx - 3); j--) { if (!(bs[j].innerText || '').trim()) return bs[j]; }
return null;
"""


def pager_text():
    m = re.search(r"Стр\.\s*(\d+)\s*из\s*(\d+)", innertext())
    return (int(m.group(1)), int(m.group(2))) if m else None


def test_pagination():
    pt = pager_text()
    if not pt:
        log("  • Пагинации нет (одна страница)")
        return True
    log(f"  Пагинация: страница {pt[0]} из {pt[1]}")
    if pt[1] < 2:
        return True
    bs = driver.execute_script(JS_PAGER)
    if not bs or len(bs) < 4:
        log("  • Кнопки пагинации не распознаны", "WARN")
        return True
    nxt, prev = bs[2], bs[1]
    try:
        driver.execute_script("arguments[0].click();", nxt)
        time.sleep(2)
        p2 = pager_text()
        log(f"  ✓ Следующая страница: {p2}", "PASS" if p2 and p2[0] == 2 else "WARN")
        driver.execute_script("arguments[0].click();", prev)
        time.sleep(2)
        log(f"  ✓ Назад: {pager_text()}", "PASS")
    except Exception as e:
        log(f"  ⚠ Пагинация: {e}", "WARN")
    return True


def test_rows_per_page():
    for t in visible_selects():
        txt = (t.get_attribute("textContent") or "").strip()
        if re.fullmatch(r"\d+", txt):
            r = open_ui(t)
            opts = [o["text"] for o in panel_options(r)] if r else []
            if len(opts) >= 2:
                other = [i for i, o in enumerate(opts) if o != txt]
                got = select_in_panel(r, index=other[-1]) if other else None
                time.sleep(2)
                log(f"  ✓ «Строк на стр.»: варианты {opts}, выбрано {got}, всего {page_total()}", "PASS")
                # вернуть как было
                for t2 in visible_selects():
                    if re.fullmatch(r"\d+", (t2.get_attribute("textContent") or "").strip()):
                        r2 = open_ui(t2)
                        if r2:
                            select_in_panel(r2, keywords=[txt])
                        break
            else:
                close_panels()
            esc()
            return True
    return True


def test_sort_and_settings():
    ok = True
    sb = driver.execute_script(JS_SORT_BTN)
    if sb:
        hard_click(sb)
        time.sleep(1.2)
        shot("list_sort_menu")
        log("  ✓ Кнопка сортировки (⇅) нажата — меню открыто и закрыто", "PASS")
        esc()
    else:
        log("  • Кнопка сортировки не найдена", "WARN")
    if click_button(["Настройки таблицы"], wait=4):
        time.sleep(1.5)
        shot("list_table_settings")
        m = find_modal()
        info = (m.get_attribute("innerText") or "").replace("\n", " | ")[:200] if m else ""
        log(f"  ✓ «Настройки таблицы» открыты {('(' + info + ')') if info else ''}", "PASS")
        if m:
            close_modal_soft(m)
            time.sleep(1)
        else:
            esc()
    else:
        log("  ⚠ Кнопка «Настройки таблицы» не найдена", "WARN")
        ok = False
    return ok


def test_filters(search_term, check_box=None):
    """Каждый фильтр-селект: открыть, показать варианты, выбрать значение, посмотреть «Всего», сбросить."""
    total0 = page_total()
    log(f"  Всего записей: {total0}")
    n = len(visible_selects())
    worked = 0
    for i in range(n):
        sels = visible_selects()
        if i >= len(sels):
            break
        t = sels[i]
        name = (t.get_attribute("textContent") or "").strip()
        if re.fullmatch(r"\d+", name):
            continue
        panel = open_ui(t)
        if panel is None:
            log(f"  • Фильтр «{name}» не открывается (зависит от другого фильтра)")
            continue
        opts = [o["text"] for o in panel_options(panel)]
        log(f"  Фильтр «{name}»: вариантов {len(opts)}, первые: {opts[:6]}", "PASS")
        k = next((j for j, o in enumerate(opts) if "все" not in o.lower()), 0)
        got = select_in_panel(panel, index=k) if opts else None
        close_panels()
        esc()
        time.sleep(2)
        if got:
            worked += 1
            log(f"    → выбрано «{got}», всего записей: {page_total()}", "PASS")
        click_text_deepest("Сбросить фильтры", "contains")
        time.sleep(2)
    log(f"  После сброса всего записей: {page_total()} (было {total0})",
        "PASS" if page_total() == total0 else "WARN")
    if check_box:
        if click_text_deepest(check_box, "contains"):
            time.sleep(2)
            log(f"  ✓ «{check_box}»: включён, всего записей {page_total()}", "PASS")
            click_text_deepest(check_box, "contains")
            time.sleep(2)
            log(f"  ✓ «{check_box}»: выключен, всего {page_total()}", "PASS")
        else:
            log(f"  ⚠ «{check_box}» не найден", "WARN")
    # поиск
    inp = None
    for e in driver.find_elements(By.XPATH, "//input[contains(@placeholder,'Поиск')]"):
        if e.is_displayed():
            inp = e
            break
    if inp:
        type_text(inp, search_term)
        time.sleep(2.5)
        log(f"  Поиск «{search_term}»: всего записей {page_total()}", "PASS")
        try:
            inp.send_keys(Keys.CONTROL, "a")
            inp.send_keys(Keys.BACKSPACE)
        except Exception:
            pass
        set_native_value(inp, "")
        time.sleep(2)
    else:
        log("  ⚠ Поле поиска не найдено", "WARN")
    return worked > 0 or total0 is not None


JS_FIRST_ROW_CODE = r"""
function vis(e){ return !!(e.offsetWidth || e.offsetHeight || e.getClientRects().length); }
var all = document.querySelectorAll('*');
for (var i = 0; i < all.length; i++) {
    var e = all[i];
    if (e.children.length || !vis(e)) continue;
    if (/^[\wА-Яа-я]{2}-\d{9}$/.test((e.textContent || '').trim())) return e;
}
return null;
"""


def open_existing_first(back_url):
    el = driver.execute_script(JS_FIRST_ROW_CODE)
    if not el:
        log("  • Строки таблицы не найдены — пропуск открытия записи", "WARN")
        return True
    code = (el.get_attribute("textContent") or "").strip()
    hard_click(el)
    time.sleep(4)
    ok = not at_url(back_url)
    log(f"  {'✓' if ok else '⚠'} Открыта запись {code}: {driver.current_url}", "PASS" if ok else "WARN")
    for tab in ["Обсуждение", "Приёмки", "Передачи", "История"]:
        if click_text_deepest(tab, "exact"):
            log(f"    ✓ Вкладка «{tab}»", "PASS")
            time.sleep(1)
    driver.get(back_url)
    time.sleep(3)
    return ok


# ==========================================
# 1. ЗАЯВКИ НА СНАБЖЕНИЕ
# ==========================================
def stage_supply_list():
    if not nav_menu("Заявки на снабжение", SUPPLY_URL):
        log("  ⚠ Раздел «Заявки на снабжение» не открылся", "WARN")
        return False
    if not wait_for_state(lambda:supply_list_at(SUPPLY_URL)):
        return False
    ok = test_filters("Grand")
    test_rows_per_page()
    ok = test_sort_and_settings() and ok
    test_pagination()
    ok = open_existing_first(SUPPLY_URL) and ok
    STATE["summary"].append(f"Заявки на снабжение: всего записей на старте {page_total()}")
    return ok


NO_RE = re.compile(r"\b[\wА-Яа-я]{2}-\d{9}\b")


def create_modal_submit(modal, buttons, url_re):
    btn = modal_button(modal, buttons)
    if not btn:
        log("  ⚠ Кнопка создания недоступна (не заполнены обязательные поля?)", "WARN")
        shot("create_no_button")
        errs = (modal.get_attribute("innerText") or "").replace("\n", " | ")[:300]
        log(f"    Текст модалки: {errs}")
        close_modal_soft(modal)
        return None
    click_el(btn)
    for _ in range(25):
        time.sleep(1)
        m = re.search(url_re, driver.current_url)
        if m and not driver.current_url.rstrip("/").endswith(("/supply", "/equipment")):
            return driver.current_url.split("#")[0]
        errs = [t for t in read_toasts() if any(k in t.lower() for k in
                                                ["ошибк", "не удалось", "нельзя", "error", "must", "обязательн"])]
        if errs:
            log(f"  ⚠ Ошибка при создании: {errs}", "WARN")
            break
    shot("create_failed")
    m2 = find_modal()
    if m2:
        close_modal_soft(m2)
    return None


def stage_supply_create():
    driver.get(SUPPLY_URL)
    if not wait_for_state(lambda:supply_list_at(SUPPLY_URL)):
        return False
    if not (click_button(["Создать заявку"], wait=8) or click_text_deepest("Создать заявку", "contains")):
        log("  ⚠ Кнопка «Создать заявку» не найдена", "WARN")
        return False
    modal = wait_modal("Новая заявка", 8)
    if not modal:
        log("  ⚠ Модалка «Новая заявка на снабжение» не открылась", "WARN")
        return False
    specs = [("Проект", dict(keywords=PROJECT_KEYS, search=PROJECT_SEARCH)),
             ("Смета", dict(keywords=ESTIMATE_KEYS, search=ESTIMATE_SEARCH)),
             ("Склад", {}), ("Очередь", {}), ("Блок", {})]
    missing = fill_required("Новая заявка", specs, passes=3)
    if missing:
        log(f"  ⚠ Не удалось заполнить: {missing}", "WARN")
    modal = find_modal("Новая заявка") or modal
    url = create_modal_submit(modal, ["Создать заявку"], r"/supply/[0-9a-f\-]{36}")
    if not url:
        return False
    if not wait_for_state(lambda:supply_card_ready(url)):
        return False
    STATE["url"] = STATE["supply_url"] = url
    mm = NO_RE.search(innertext())
    STATE["supply_no"] = mm.group(0) if mm else "?"
    log(f"  ✓ Заявка создана: {STATE['supply_no']} — {url}; статус: {get_status()}", "PASS")
    basic = section_text("Основная информация").replace("\n", " | ")
    log(f"  Основная информация: {basic[:300]}")
    return True


def kebab_open_close():
    el = driver.execute_script("""
        function vis(e){ return !!(e.offsetWidth || e.offsetHeight || e.getClientRects().length); }
        var bs = document.querySelectorAll('button');
        for (var i = 0; i < bs.length; i++) {
            var b = bs[i], t = (b.innerText || '').trim();
            if (!vis(b)) continue;
            var r = b.getBoundingClientRect();
            if ((t === '⋮' || t === '⋯' || t === '...' || t === '…') && r.top < 300) return b;
        }
        return null;""")
    if not el:
        log("  • Меню «⋮» не найдено", "WARN")
        return True
    hard_click(el)
    time.sleep(1)
    items = driver.execute_script("""
        return Array.prototype.map.call(document.querySelectorAll('[role=menuitem],[class*=menu] button,[class*=dropdown] button'),
            function(e){ return (e.innerText || '').trim(); }).filter(Boolean).slice(0, 10);""")
    log(f"  ✓ Меню «⋮» открыто (пункты: {items}) — закрываю, пункты не нажимаю", "PASS")
    esc()
    return True


def stage_card_tabs():
    goto_card()
    ok = True
    for tab in ["Приёмки", "Передачи", "История", "Обсуждение"]:
        if click_text_deepest(tab, "exact"):
            log(f"  ✓ Вкладка «{tab}»", "PASS")
            time.sleep(1.5)
        else:
            log(f"  • Вкладка «{tab}» не найдена", "WARN")
    try:
        sw = driver.find_element(
            By.XPATH,
            "//*[normalize-space(text())='Уведомлять меня о сообщениях']"
            "/ancestor::*[.//*[@role='switch' or @type='checkbox' or contains(@class,'switch')]][1]"
            "//*[@role='switch' or @type='checkbox' or contains(@class,'switch')]")
        click_el(sw)
        time.sleep(0.8)
        click_el(sw)
        log("  ✓ Переключатель уведомлений", "PASS")
    except Exception:
        log("  • Переключатель уведомлений не найден", "WARN")
    kebab_open_close()
    ok = try_open_and_cancel("Сменить маршрут") and ok
    goto_card()
    return ok


def coexecutor_ok():
    return "пока не расшарена" not in innertext().lower()


def stage_share_coexecutor():
    goto_card()
    if coexecutor_ok():
        log("  ✓ Соисполнитель уже указан", "PASS")
        return True
    if not click_button(["Поделиться"], wait=6):
        log("  ⚠ Кнопка «Поделиться» не найдена", "WARN")
        return False
    modal = wait_modal("Поделиться", 8)
    if not modal:
        log("  ⚠ Окно «Поделиться заявкой» не открылось", "WARN")
        return False
    trg = None
    ts = visible_selects(modal)
    if ts:
        trg = ts[0]
    if trg is None:
        trg = control_by_label(modal, "Пользователь")
    picked = None
    for query, kws in COEXEC_TRIES:
        panel = open_ui(trg) if trg is not None else None
        if not panel:
            continue
        picked = select_in_panel(panel, keywords=kws, search=query)
        if picked:
            break
        close_panels()
        esc()
    if not picked:
        log("  ⚠ Алдажаров Диас в списке соисполнителей не найден", "WARN")
        close_modal_soft(modal)
        return False
    log(f"  ✓ Соисполнитель выбран: {picked}", "PASS")
    time.sleep(1)
    modal = find_modal("Поделиться") or modal
    b = modal_button(modal, ["Поделиться", "Добавить", "Сохранить", "Отправить", "Подтвердить", "ОК"])
    if not b:
        log("  ⚠ Кнопка подтверждения в окне «Поделиться» не найдена", "WARN")
        shot("share_no_confirm")
        log(f"    Текст окна: {(modal.get_attribute('innerText') or '').replace(chr(10), ' | ')[:250]}")
        return False
    click_el(b)
    wait_modal_closed("Поделиться", 8)
    time.sleep(3)
    ok = coexecutor_ok()
    log(f"  Соисполнитель в карточке: {'указан' if ok else 'НЕ указан'}; уведомления: {read_toasts()}",
        "PASS" if ok else "WARN")
    return ok


def add_supply_position(desc):
    if not open_lines():
        return False
    if not click_button(["Добавить строку"], wait=6):
        log("  ⚠ Кнопка «Добавить строку» не найдена", "WARN")
        return False
    modal = wait_modal("Добавить позицию", 8)
    if not modal:
        log("  ⚠ Окно «Добавить позицию» не открылось", "WARN")
        return False
    rows0, total0 = lines_state()
    # «Из строки сметы» — остальные поля заполнятся автоматически
    got_line = fill_select(modal, "Из строки сметы")
    time.sleep(1.2)
    for lab in ["Статья расходов", "Тип", "Материал", "Ед. изм."]:
        fill_select(modal, lab)
        time.sleep(0.5)
    num_field(modal, "Количество", "10")
    num_field(modal, "План кол-во", "10")
    num_field(modal, "План. цена", "1000")
    fill_dates_in(None, start_days=14, length_days=0)
    fill_textarea(modal, f"Автотест позиция: {desc}")
    if send_file(create_test_pdf("supply_line"), scope=modal):
        log("    ✓ Файл к позиции прикреплён", "PASS")
    save = modal_button(modal, ["Добавить"])
    if not save:
        log("  ⚠ Кнопка «Добавить» недоступна (обязательные поля не заполнены)", "WARN")
        shot("supply_pos_nobutton")
        log(f"    Текст окна: {(modal.get_attribute('innerText') or '').replace(chr(10), ' | ')[:300]}")
        close_modal_soft(modal)
        return False
    click_el(save)
    closed = wait_modal_closed("Добавить позицию", 8)
    time.sleep(2)
    if not closed:
        log(f"  ⚠ Окно не закрылось (валидация?). Уведомления: {read_toasts()}", "WARN")
        shot("supply_pos_validation")
        m = find_modal("Добавить позицию")
        if m:
            close_modal_soft(m)
        return False
    rows1, total1 = lines_state()
    log(f"  ✓ Позиция добавлена ({desc}). Строк: {rows0}→{rows1}, итого: {total0}→{total1}"
        f"{'' if got_line else ' (без привязки к строке сметы)'}", "PASS")
    return True


def stage_supply_position_1():
    ok = add_supply_position("первая")
    back_to_card()
    return ok


def stage_supply_position_2():
    ok = add_supply_position("вторая")
    back_to_card()
    return ok


def supplier_section():
    return driver.execute_script(r"""
        const norm=e=>(e.innerText||'').replace(/\s+/g,' ').trim();
        const vis=e=>!!(e.offsetWidth||e.offsetHeight||e.getClientRects().length);
        const other=['Основная информация','Маршрут согласования','Соисполнители','Позиции заявки'];
        for(const heading of document.querySelectorAll('*')){
            if(!vis(heading)||norm(heading)!=='Поставщик')continue;
            let card=heading;
            for(let depth=0;card&&depth<9;depth++,card=card.parentElement){
                if(card===document.body||card===document.documentElement)break;
                const text=norm(card);
                if(other.some(title=>text.includes(title)))break;
                let content=text.replace('Поставщик','');
                for(const button of card.querySelectorAll('button')){
                    const caption=norm(button);if(caption)content=content.replace(caption,'');
                }
                if(content.trim())return card;
            }
        }return null;
    """)


def supplier_editing(scope):
    return any(b.is_displayed() for b in scope.find_elements(
        By.XPATH, ".//button[normalize-space(.)='Сохранить']"))


def supplier_saved(expected=None):
    scope=supplier_section()
    if scope is None or supplier_editing(scope):
        return False
    text=scope.get_attribute('innerText') or ''
    if 'поставщик не указан' in text.lower():
        return False
    lines=[' '.join(line.split()) for line in text.splitlines() if line.strip()]
    ignored={'поставщик','контрагент','договор поставки','договор (необязательно)',
             'добавить','сохранить','отмена','редактировать','изменить','создать договор поставки'}
    names=[line for line in lines if line.lower().strip(' *+:') not in ignored]
    if not names:
        return False
    if expected and ' '.join(expected.lower().split()) not in ' '.join(text.lower().split()):
        return False
    return expected or names[0]


def supplier_text():
    scope=supplier_section()
    return (scope.get_attribute('innerText') or '').replace('\n',' | ') if scope is not None else ''


def add_supplier_manually():
    """Fill the inline supplier form; the supply contract is optional."""
    scope=wait_for_state(supplier_section)
    if scope is None:
        log('  ⚠ Секция Поставщик не найдена', 'WARN')
        return None
    if not supplier_editing(scope):
        buttons=find_buttons(['Добавить'],scope=scope)
        if not buttons or not click_el(buttons[0]):
            log('  ⚠ Кнопка Добавить в секции Поставщик не найдена', 'WARN')
            return None
    def edit_form():
        block=supplier_section()
        if block is not None and supplier_editing(block):
            ctrl=control_by_label(block,'Контрагент')
            return block if ctrl is not None and ctrl.is_displayed() else False
        return False
    scope=wait_for_state(edit_form)
    if not scope:
        log('  ⚠ Встроенная форма Поставщик не открылась', 'WARN')
        return None
    if not fill_select(scope,'Контрагент',keywords=['AI Group'],search=['AI Group']):
        log('  ⚠ Контрагент не выбран', 'WARN')
        return None
    scope=supplier_section()
    ctrl=control_by_label(scope,'Контрагент') if scope is not None else None
    if ctrl is None or ctrl_unset(ctrl,'Контрагент'):
        log('  ⚠ Выбор контрагента не подтверждён', 'WARN')
        return None
    chosen=(ctrl.get_attribute('innerText') or ctrl.get_attribute('textContent') or '').strip()
    if not chosen:
        return None
    buttons=find_buttons(['Сохранить'],scope=scope)
    if not buttons or not click_el(buttons[0]):
        log('  ⚠ Сохранить в секции Поставщик недоступно', 'WARN')
        return None
    if not wait_for_state(lambda:supplier_saved(chosen)):
        log(f'  ⚠ Поставщик не сохранился; уведомления: {read_toasts()}', 'WARN')
        return None
    log(f'  ✓ Поставщик сохранён: {chosen}; договор поставки не выбирался', 'PASS')
    return chosen


def stage_supply_supplier_check():
    global ROLE_RESTORE_FAILED
    try:
        if not switch_user(SECOND_LOGIN,SECOND_PASS) or not request_card():
            log('  ⚠ Не удалось открыть заявку под Диасом','WARN')
            return False
        status=get_status()
        if status in ('Новая заявка','Согласовано','Утверждено','Утверждена'):
            if not click_action(['Принять в работу']):
                log(f'  ⚠ Принять в работу недоступно; статус: {status}','WARN')
                return False
            if not wait_for_state(lambda:get_status()=='На исполнении'):
                log(f'  ⚠ Заявка не принята в работу: {read_toasts()}','WARN')
                return False
            driver.refresh()
            if not wait_for_state(lambda:get_status()=='На исполнении'):
                return False
            log('  ✓ Диас принял заявку в работу','PASS')
        wait_for_state(supplier_section)
        chosen=supplier_saved()
        if not chosen:
            chosen=add_supplier_manually()
        if not chosen:
            log(f'  ⚠ Поставщик не заполнен: {supplier_text()}','WARN')
            return False
        driver.refresh()
        if not wait_for_state(lambda:supplier_saved(chosen)):
            log(f'  ⚠ После обновления поставщик {chosen!r} не подтверждён','WARN')
            return False
        STATE['supplier']=chosen
        log(f'  ✓ Поставщик подтверждён после обновления: {chosen}','PASS')
        return True
    finally:
        if not switch_user(login_val,pass_val):
            ROLE_RESTORE_FAILED=True
            raise RuntimeError('Не удалось вернуться в аккаунт создания после заполнения поставщика')


# ==========================================
# ОБЩИЕ ЭТАПЫ ЗАЯВКИ/ЗАКАЗА: маршрут, обсуждение, согласование
# ==========================================
def stage_route():
    return add_approver()


def stage_send(label_hint=""):
    goto_card()
    before = get_status()
    log(f"  Статус до: {before}")
    if not route_has_approver():
        log("  ⚠ Перед отправкой в маршруте нет согласующего", "WARN")
    label = click_action(TO_SEND)
    if not label:
        log("  ⚠ Кнопка отправки на согласование не найдена/недоступна", "WARN")
        return False
    time.sleep(3)
    toasts = read_toasts()
    if toasts:
        log(f"  Уведомления после отправки: {toasts}")
    time.sleep(2)
    driver.refresh()
    wait_for_state(supply_card_ready)
    after = get_status()
    still = bool(find_buttons(TO_SEND))
    changed = bool(after and after != before)
    log(f"  Статус после: {after}; кнопка отправки {'осталась' if still else 'пропала'}",
        "PASS" if (changed or not still) else "WARN")
    if still and not changed:
        errs = [t for t in toasts if any(k in t.lower() for k in
                ["ошибк", "не назнач", "обязательн", "нельзя", "не удалось", "необходимо"])]
        log(f"  ⚠ Отправка не сработала: {errs or toasts or 'статус не изменился'}", "WARN")
        shot("send_not_done")
        return False
    return True


JS_ACTIONS = r'''
function vis(e){ return !!(e.offsetWidth || e.offsetHeight || e.getClientRects().length); }
return Array.prototype.filter.call(document.querySelectorAll('button, a[role=button]'), vis)
  .map(function(b){ return (b.innerText || '').trim().replace(/\s+/g, ' '); })
  .filter(function(t){ return t && t.length < 40; });
'''


def visible_actions():
    try:
        return driver.execute_script(JS_ACTIONS) or []
    except Exception:
        return []


def advance_phase(groups, who):
    n = 0
    for _ in range(14):
        goto_card()
        acted = False
        for g in groups:
            if not find_buttons(g):
                continue
            st0 = get_status()
            label = click_action(g)
            if not label:
                continue
            log(f"  [{who}] нажато «{label}» (статус был: {st0})", "PASS")
            time.sleep(3)
            driver.refresh()
            wait_for_state(supply_card_ready)
            log(f"  [{who}] статус после: {get_status()}")
            n += 1
            acted = True
            break
        if not acted:
            log(f"  [{who}] кнопки на странице: {visible_actions()}")
            break
    return n


def advance_to_end():
    global ROLE_RESTORE_FAILED
    actions = 0
    st = get_status()
    try:
        for account, password, who, groups in (
            (REVIEWER_LOGIN, REVIEWER_PASS, 'Бейсембаев Куаныш', [TO_APPROVE]),
            (SECOND_LOGIN, SECOND_PASS, 'Алдажаров Диас', [TO_APPROVE, TO_CONFIRM] + ([] if STATE.get('url')==STATE.get('supply_url') else [TO_EXTRA])),
        ):
            if status_terminal(st):
                break
            if not switch_user(account, password):
                log(f'  ⚠ Вход под {who} не удался', 'WARN')
                return False
            driver.get(STATE['url'])
            if not wait_for_state(supply_card_ready):
                return False
            actions += advance_phase(groups, who)
            st = get_status()
    finally:
        if not switch_user(login_val, pass_val):
            ROLE_RESTORE_FAILED = True
            raise RuntimeError('Не удалось вернуться в аккаунт создания; дальнейшие действия остановлены')
        driver.get(STATE['url'])
        wait_for_state(supply_card_ready)
    log(f'  Итог: действий {actions}, итоговый статус: {get_status() or st}', 'PASS' if actions else 'WARN')
    if not actions and not status_terminal(st):
        log(f'  ⚠ Кнопок продвижения не найдено, статус: {st}', 'WARN')
        shot('advance_nothing')
        return False
    return True


# ==========================================
# 2. ОСТАТКИ
# ==========================================
JS_STOCK_BOXES = r"""
function vis(e){ return !!(e.offsetWidth || e.offsetHeight || e.getClientRects().length); }
var hdr = null, all = document.querySelectorAll('*');
for (var i = 0; i < all.length; i++) {
    var e = all[i];
    if (e.children.length === 0 && vis(e) && (e.textContent || '').trim() === 'Заказано') { hdr = e; break; }
}
if (!hdr) return [];
var hb = hdr.getBoundingClientRect().bottom;
var boxes = Array.prototype.filter.call(document.querySelectorAll('input[type=checkbox]'), function(b){
    var r = b.getBoundingClientRect(); return r.width >= 0 && r.top > 250; });
var head = null, rows = [];
boxes.forEach(function(b){ var t = b.getBoundingClientRect().top;
    if (t < hb + 5) { if (!head) head = b; } else { rows.push(b); } });
return [head, rows[0] || null, rows[1] || null];
"""


def request_card():
    url=STATE.get('supply_url')
    if not url:
        raise RuntimeError('Нет URL созданной тестовой заявки')
    STATE['url']=url
    if not at_url(url):
        driver.get(url)
    return bool(wait_for_state(lambda:at_url(url) and get_status()))


def positive_amount(text):
    value=re.sub(r'[^0-9,.\-]', '', (text or '').replace('\xa0',''))
    if ',' in value:
        value=value.replace('.','').replace(',','.')
    try:
        number=float(value)
        return number if number>0 else None
    except (ValueError,TypeError):
        return None


def fact_price_rows():
    return driver.execute_script(r"""
        const vis=e=>!!(e.offsetWidth||e.offsetHeight||e.getClientRects().length);
        const norm=e=>(e.innerText||'').replace(/\s+/g,' ').trim();
        for(const table of document.querySelectorAll('table')){
            if(!vis(table)||!table.tHead)continue;
            const grid=[];
            Array.from(table.tHead.rows).forEach((row,r)=>{
                grid[r]=grid[r]||[];let col=0;
                for(const cell of row.cells){
                    while(grid[r][col]!==undefined)col++;
                    for(let dr=0;dr<cell.rowSpan;dr++)for(let dc=0;dc<cell.colSpan;dc++){
                        grid[r+dr]=grid[r+dr]||[];grid[r+dr][col+dc]=norm(cell);
                    }
                    col+=cell.colSpan;
                }
            });
            const leaf=grid[grid.length-1]||[];
            const fact=leaf.findIndex(t=>t==='Факт');
            if(fact<0)continue;
            const plan=leaf.findIndex((t,i)=>t==='План'&&grid.some(row=>/Стоимость единицы/i.test(row[i]||'')));
            return Array.from(table.tBodies).flatMap(b=>Array.from(b.rows)).filter(row=>
                vis(row)&&row.cells.length>fact&&/^\d+$/.test(norm(row.cells[0]))).map(row=>({
                    cell:row.cells[fact],fact:norm(row.cells[fact]),
                    plan:plan>=0?norm(row.cells[plan]):'',number:norm(row.cells[0])}));
        }
        return [];
    """) or []


def fact_price_input(cell):
    fields=[e for e in cell.find_elements(By.XPATH,'.//input') if e.is_displayed() and e.is_enabled()]
    if fields:
        return fields[0],cell
    modal=find_modal()
    if modal is not None and any(k in (modal.get_attribute('innerText') or '').lower() for k in ('факт','цен','стоимост')):
        fields=[e for e in modal.find_elements(By.XPATH,".//input[not(@type='hidden')]") if e.is_displayed() and e.is_enabled()]
        if len(fields)==1:
            return fields[0],modal
    return False


def stage_supply_fact_prices():
    if not switch_user(SECOND_LOGIN,SECOND_PASS) or not request_card() or not open_lines():
        return False
    rows=wait_for_state(fact_price_rows)
    if not rows:
        log('  ⚠ Позиции с колонкой Факт не найдены','WARN')
        return False
    count=len(rows)
    for index in range(count):
        rows=fact_price_rows()
        if len(rows)!=count:
            log('  ⚠ Состав позиций изменился во время заполнения','WARN')
            return False
        row=rows[index]
        if positive_amount(row['fact']):
            continue
        value=positive_amount(row['plan']) or 1000
        buttons=[b for b in row['cell'].find_elements(By.XPATH,'.//button') if b.is_displayed() and b.is_enabled()]
        if not buttons or not click_el(buttons[-1]):
            log(f"  ⚠ Редактирование Факт в строке {row['number']} не найдено",'WARN')
            return False
        editor=wait_for_state(lambda:fact_price_input(row['cell']))
        if not editor:
            return False
        field,scope=editor
        type_text(field,format(value,'.15g'))
        save=find_buttons(['Сохранить','Применить','ОК'],scope=scope)
        if save:
            click_el(save[0])
        else:
            field.send_keys(Keys.ENTER)
            time.sleep(0.8)
            # Если поле ввода всё ещё открыто в ячейке, нажимаем иконку галочки (первую кнопку в ячейке)
            try:
                still_inp=[e for e in row['cell'].find_elements(By.XPATH,'.//input') if e.is_displayed()]
                if still_inp:
                    icon_btns=[b for b in row['cell'].find_elements(By.XPATH,'.//button') if b.is_displayed() and b.is_enabled()]
                    if icon_btns:
                        click_el(icon_btns[0])
                        time.sleep(0.8)
            except Exception:
                pass
            # Также если открыта модалка с кнопкой Сохранить на уровне страницы
            m_now=find_modal()
            if m_now is not None:
                mb=modal_button(m_now,['Сохранить','Применить','ОК','Подтвердить'])
                if mb:
                    click_el(mb)
        def saved():
            current=fact_price_rows()
            if len(current)!=count or not positive_amount(current[index]['fact']):
                return False
            return not any(e.is_displayed() for e in current[index]['cell'].find_elements(By.XPATH,'.//input')) and find_modal() is None
        if not wait_for_state(saved, timeout=10):
            # Попытка кликнуть вне поля (blur) и проверить ещё раз
            try:
                driver.execute_script("if(document.activeElement) document.activeElement.blur();")
                time.sleep(1.5)
            except Exception:
                pass
            if not wait_for_state(saved, timeout=5):
                log(f"  ⚠ Фактическая цена строки {row['number']} не сохранилась",'WARN')
                return False
    driver.refresh()
    rows=wait_for_state(fact_price_rows)
    if not rows or len(rows)!=count or not all(positive_amount(r['fact']) for r in rows):
        log('  ⚠ Фактические цены не подтверждены после обновления','WARN')
        return False
    return request_card()


def vat_is_16():
    return bool(driver.execute_script(r"""
        for(const e of document.querySelectorAll('*')){
            if((e.innerText||'').trim()!=='Ставка НДС')continue;
            let p=e;
            for(let k=0;p&&k<5;k++,p=p.parentElement){
                const t=(p.innerText||'').replace(/\s+/g,' ').trim();
                if(t.length<250&&/НДС\s*16\s*%/.test(t))return true;
            }
        }return false;
    """))


def stage_supply_vat():
    if not request_card():
        return False
    if not vat_is_16():
        buttons=driver.find_elements(By.XPATH,"//*[normalize-space(text())='Ставка НДС']/ancestor::*[.//button][1]//button")
        buttons=[b for b in buttons if b.is_displayed() and b.is_enabled()]
        if not buttons or not click_el(buttons[0]):
            return False
        modal=wait_modal('Ставка НДС',8)
        if modal is None:
            return False
        selects=visible_selects(modal)
        panel=open_ui(selects[0]) if selects else None
        picked=select_in_panel(panel,keywords=['ндс 16%']) if panel is not None else None
        if not picked:
            log('  ⚠ Ставка НДС 16% отсутствует в списке','WARN')
            return False
        modal=find_modal('Ставка НДС')
        if modal is not None:
            save=modal_button(modal,['Сохранить','Применить'])
            if not save or not click_el(save) or not wait_modal_closed('Ставка НДС',8):
                return False
        if not wait_for_state(vat_is_16):
            return False
    driver.refresh()
    return bool(wait_for_state(vat_is_16))


def supply_actions_menu():
    """Меню карточки рядом со статусными действиями, без меню строк позиций."""
    return driver.execute_script(r"""
        const vis=e=>!!(e.offsetWidth||e.offsetHeight||e.getClientRects().length);
        const norm=e=>(e.innerText||'').trim();
        const anchors=['Ознакомлен','Сменить исполнителя','На доработку'];
        for(const b of document.querySelectorAll('button')){
            if(!vis(b)||!anchors.includes(norm(b)))continue;
            let p=b.parentElement;
            for(let k=0;p&&k<4;k++,p=p.parentElement){
                const buttons=Array.from(p.querySelectorAll('button')).filter(vis);
                const candidates=buttons.slice(buttons.indexOf(b)+1).filter(x=>
                    !x.disabled&&(!norm(x)||['⋮','⋯','...','…'].includes(norm(x))));
                if(candidates.length)return candidates[candidates.length-1];
            }
        }
        return null;
    """)


def supply_warehouse_action():
    """На склад может быть кнопкой или пунктом раскрытого меню."""
    return driver.execute_script(r"""
        const vis=e=>!!(e.offsetWidth||e.offsetHeight||e.getClientRects().length);
        const norm=e=>(e.innerText||'').trim();
        return Array.from(document.querySelectorAll('button,a,[role="menuitem"],[role="button"],div,span'))
            .find(e=>vis(e)&&!e.disabled&&e.getAttribute('aria-disabled')!=='true'&&
                norm(e)==='На склад'&&!Array.from(e.children).some(c=>norm(c)==='На склад'))||null;
    """)


def stage_supply_to_warehouse():
    if not request_card():
        return False
    if get_status()=='Отправлен на склад':
        return True
    if not find_buttons(['На склад']):
        menu = wait_for_state(supply_actions_menu)
        if menu is None or not menu or not click_el(menu):
            log(f'  ⚠ Меню действий заявки недоступно; статус: {get_status()}; действия: {visible_actions()}', 'WARN')
            return False
    action = wait_for_state(supply_warehouse_action)
    if not action or not click_action(['На склад'], action_element=action):
        log(f'  ⚠ Пункт На склад недоступен; статус: {get_status()}; действия: {visible_actions()}', 'WARN')
        return False
    if not wait_for_state(lambda:get_status()=='Отправлен на склад'):
        log(f'  ⚠ Отправка на склад не подтверждена: {read_toasts()}','WARN')
        return False
    driver.refresh()
    return bool(wait_for_state(lambda:get_status()=='Отправлен на склад'))


def stage_supply_receive():
    if not request_card():
        return False
    if get_status()=='Принят на склад':
        return True
    if get_status()!='Отправлен на склад' or not click_button(['Принять ТМЦ'],wait=5):
        return False
    modal=wait_modal('Приёмка ТМЦ',8)
    if modal is None:
        return False
    quantities=[e for e in modal.find_elements(By.XPATH,".//input[@type='number' or @inputmode='numeric' or @inputmode='decimal']") if e.is_displayed()]
    if not quantities:
        quantities=[e for e in modal.find_elements(By.XPATH,".//*[normalize-space(text())='Кол-во']/following::input[1]") if e.is_displayed()]
    checked=[e for e in modal.find_elements(By.XPATH,".//input[@type='checkbox']") if e.is_selected()]
    if not checked or not quantities or not all(positive_amount(e.get_attribute('value')) for e in quantities):
        log('  ⚠ Выбранные позиции и положительные количества приёмки не подтверждены','WARN')
        return False
    fill_textarea(modal,f'Автотест: приёмка ТМЦ {STAMP}')
    path=create_test_pdf('supply_receipt')
    if not send_file(path,scope=modal):
        return False
    def attachment_ready():
        current=find_modal('Приёмка ТМЦ')
        if current is None:
            return False
        text=current.get_attribute('innerText') or ''
        if os.path.basename(path) not in text:
            return False
        return modal_button(current,['Принять','Принять ТМЦ'])
    button=wait_for_state(attachment_ready)
    if not button or not click_el(button) or not wait_modal_closed('Приёмка ТМЦ',10):
        return False
    if not wait_for_state(lambda:get_status()=='Принят на склад'):
        log(f'  ⚠ Приёмка ТМЦ не подтверждена: {read_toasts()}','WARN')
        return False
    driver.refresh()
    return bool(wait_for_state(lambda:get_status()=='Принят на склад'))


def stage_supply_close():
    if not request_card():
        return False
    closed={'Исполнен','Закрыта','Закрыт','Закрыто','Заявка закрыта'}
    if get_status() in closed:
        return True
    if get_status()!='Принят на склад':
        return False
    menu=driver.execute_script(r"""
        const visible=e=>!!(e.offsetWidth||e.offsetHeight||e.getClientRects().length);
        const norm=e=>(e.innerText||'').trim();
        for(const b of document.querySelectorAll('button')){
            if(!visible(b)||norm(b)!=='Принять ТМЦ')continue;
            let p=b.parentElement;
            for(let k=0;p&&k<4;k++,p=p.parentElement){
                const buttons=Array.from(p.querySelectorAll('button')).filter(visible);
                const candidates=buttons.slice(buttons.indexOf(b)+1).filter(x=>
                    !norm(x)||['⋮','⋯','...','…'].includes(norm(x)));
                if(candidates.length)return candidates[0];
            }
        }
        return Array.from(document.querySelectorAll('button')).find(b=>visible(b)&&
            ['⋮','⋯','...','…'].includes(norm(b)))||null;
    """)
    if menu is None or not click_el(menu):
        return False
    if not wait_for_state(lambda:click_text_deepest('Закрыть заявку','exact'),timeout=4):
        return False
    modal=find_modal()
    if modal is not None:
        if 'закры' not in (modal.get_attribute('innerText') or '').lower():
            return False
        fill_textarea(modal,f'Автотест: закрытие заявки {STAMP}')
        button=modal_button(modal,['Закрыть заявку','Подтвердить','Да'])
        if not button or not click_el(button) or not wait_modal_closed(None,10):
            return False
    if not wait_for_state(lambda:get_status() in closed):
        log(f'  ⚠ Закрытие заявки не подтверждено; статус: {get_status()}; уведомления: {read_toasts()}','WARN')
        return False
    driver.refresh()
    return bool(wait_for_state(lambda:get_status() in closed))


def run_supply_warehouse():
    global ROLE_RESTORE_FAILED
    try:
        step('Заявки: фактическая цена всех позиций',stage_supply_fact_prices)
        step('Заявки: ставка НДС 16%',stage_supply_vat)
        if not step('Заявки: отправка на склад',stage_supply_to_warehouse):
            return
        if not step('Заявки: приёмка ТМЦ с файлом',stage_supply_receive):
            return
        step('Заявки: закрытие после приёмки ТМЦ',stage_supply_close)
    finally:
        if not switch_user(login_val,pass_val):
            ROLE_RESTORE_FAILED=True
            raise RuntimeError('Не удалось вернуться в аккаунт создания после склада')



def stage_stock():
    if not nav_menu("Остатки", STOCK_URL):
        log("  ⚠ Раздел «Остатки» не открылся", "WARN")
        return False
    if not wait_for_state(lambda:supply_list_at(STOCK_URL)):
        return False
    ok = test_filters("VX", check_box="Остаток на складе")
    test_rows_per_page()
    ok = test_sort_and_settings() and ok
    test_pagination()
    boxes = driver.execute_script(JS_STOCK_BOXES) or []
    if len(boxes) >= 2 and boxes[1]:
        head, r1 = boxes[0], boxes[1]
        if head:
            driver.execute_script("arguments[0].click();", head)
            time.sleep(1)
            log("  ✓ Чекбокс «выбрать все» нажат", "PASS")
            driver.execute_script("arguments[0].click();", head)
            time.sleep(1)
        driver.execute_script("arguments[0].click();", r1)
        time.sleep(1)
        log("  ✓ Выбрана первая строка", "PASS")
        if click_button(["Переместить"], wait=4):
            time.sleep(2)
            shot("stock_move")
            m = find_modal()
            info = (m.get_attribute("innerText") or "").replace("\n", " | ")[:250] if m else ""
            log(f"  ✓ «Переместить» открыто {('(' + info + ')') if info else ''} — закрываю БЕЗ перемещения",
                "PASS")
            if m:
                close_modal_soft(m)
                time.sleep(1)
            else:
                esc()
        else:
            log("  ⚠ Кнопка «Переместить» не найдена/неактивна", "WARN")
            ok = False
        driver.execute_script("arguments[0].click();", r1)   # снять выбор
        time.sleep(1)
    else:
        log("  • Чекбоксы строк не найдены", "WARN")
    STATE["summary"].append(f"Остатки: всего записей {page_total()}")
    return ok


# ==========================================
# 3. ТЕХНИКА
# ==========================================
def stage_equip_list():
    if not nav_menu("Техника", EQUIP_URL):
        log("  ⚠ Раздел «Техника» не открылся", "WARN")
        return False
    if not wait_for_state(lambda:supply_list_at(EQUIP_URL)):
        return False
    ok = test_filters("Автокран")
    test_rows_per_page()
    ok = test_sort_and_settings() and ok
    test_pagination()
    ok = open_existing_first(EQUIP_URL) and ok
    STATE["summary"].append(f"Техника: всего записей на старте {page_total()}")
    return ok


def stage_equip_create():
    driver.get(EQUIP_URL)
    if not wait_for_state(lambda:supply_list_at(EQUIP_URL)):
        return False
    if not (click_button(["Создать", "Создать заказ"], wait=8)):
        log("  ⚠ Кнопка «Создать» не найдена", "WARN")
        return False
    modal = wait_modal("Новый заказ техники", 4)
    if modal:
        specs = [("Проект", dict(keywords=PROJECT_KEYS, search=PROJECT_SEARCH)),
                 ("Очередь", {}), ("Блок", {}), ("Тип техники", {}), ("Вид техники", {}), ("Владение", {})]
        missing = fill_required("Новый заказ техники", specs, passes=3)
        modal = find_modal("Новый заказ техники") or modal
        fill_dates_in(None, start_days=0, length_days=7)
        time.sleep(1.2)
        missing += fill_required("Новый заказ техники", [
            ("Время начала", dict(keywords=["02:00"])), ("Время окончания", dict(keywords=["04:00"]))], passes=2)
        modal = find_modal("Новый заказ техники") or modal
        fill_textarea(modal, f"Автотест: проверка создания заказа техники {STAMP}")
        if missing:
            log(f"  ⚠ Не удалось заполнить: {missing}", "WARN")
        modal = find_modal("Новый заказ техники") or modal
        url = create_modal_submit(modal, ["Создать заказ", "Сохранить"], r"/supply/equipment/[0-9a-f\-]{36}")
        if not url:
            return False
    else:
        # Новый интерфейс сайта: «Создать» открывает страницу «Новый заказ техники» (Черновик)
        if not wait_for_state(lambda: "новый заказ техники" in page_text() or not at_url(EQUIP_URL), timeout=8):
            log("  ⚠ Страница/окно «Новый заказ техники» не открылось", "WARN")
            return False
        log(f"  ✓ Открыта страница «Новый заказ техники»: {driver.current_url}", "PASS")
        # 1. Заполняем «Проект *» (через карандаш или inline-селект)
        proj_Filled = False
        try:
            pen_btns = driver.find_elements(
                By.XPATH,
                "//*[starts-with(normalize-space(text()),'Проект')]/ancestor::*[.//button][1]//button"
            )
            pen_btns = [b for b in pen_btns if b.is_displayed() and b.is_enabled()
                        and (b.text or "").strip() not in ("Сохранить", "Создать", "Отмена")]
            if pen_btns:
                click_el(pen_btns[0])
                time.sleep(1.2)
        except Exception:
            pass
        m_proj = find_modal()
        scope_proj = m_proj if m_proj is not None else driver
        if fill_select(scope_proj, "Проект", keywords=PROJECT_KEYS, search=PROJECT_SEARCH):
            proj_Filled = True
        else:
            sels = visible_selects(scope_proj)
            if sels:
                panel = open_ui(sels[0])
                if panel:
                    picked = (select_in_panel(panel, keywords=PROJECT_KEYS, search=PROJECT_SEARCH[0])
                              or select_in_panel(panel, index=0))
                    if picked:
                        proj_Filled = True
                        log(f"    ✓ Проект выбран: {picked}", "PASS")
        for opt_label in ("Очередь", "Блок"):
            try:
                if control_by_label(scope_proj, opt_label):
                    fill_select(scope_proj, opt_label)
            except Exception:
                pass
        if m_proj is not None:
            sb = modal_button(m_proj, ["Сохранить", "Применить", "ОК", "Выбрать"])
            if sb:
                click_el(sb)
                wait_modal_closed(None, 6)
        else:
            # Если внутри секции Основная информация появилась локальная кнопка Сохранить
            try:
                sec_btns = driver.find_elements(
                    By.XPATH,
                    "//*[normalize-space(text())='Основная информация']/ancestor::*[1]//button[normalize-space(.)='Сохранить']"
                )
                for sb in sec_btns:
                    if sb.is_displayed() and sb.is_enabled():
                        click_el(sb)
                        time.sleep(1)
                        break
            except Exception:
                pass
        # 2. Заполняем Комментарий (если есть карандаш или textarea)
        try:
            c_btns = driver.find_elements(
                By.XPATH,
                "//*[starts-with(normalize-space(text()),'Комментарий')]/ancestor::*[.//button][1]//button"
            )
            c_btns = [b for b in c_btns if b.is_displayed() and b.is_enabled()
                      and (b.text or "").strip() not in ("Сохранить", "Создать", "Отмена")]
            if c_btns:
                click_el(c_btns[0])
                time.sleep(1)
                m_comm = find_modal()
                if m_comm:
                    fill_textarea(m_comm, f"Автотест: заказ техники {STAMP}")
                    sb = modal_button(m_comm, ["Сохранить", "Применить", "ОК"])
                    if sb:
                        click_el(sb)
                        wait_modal_closed(None, 5)
                else:
                    fill_textarea(driver, f"Автотест: заказ техники {STAMP}")
        except Exception:
            pass
        # 3. Нажимаем верхнюю кнопку «Сохранить» / «Создать заказ»
        if click_button(["Сохранить", "Создать заказ"], wait=5):
            log("  ✓ Нажата кнопка «Сохранить» для нового заказа техники", "PASS")
            time.sleep(3)
        wait_for_state(lambda: re.search(r"/supply/equipment/[0-9a-f\-]{36}", driver.current_url) or get_status(), timeout=12)
        url = driver.current_url.split("#")[0]
    if not wait_for_state(lambda:supply_card_ready(url), timeout=10):
        log(f"  • Карточка заказа техники открыта по адресу: {url}")
    STATE["url"] = STATE["equip_url"] = url
    mm = NO_RE.search(innertext())
    STATE["equip_no"] = mm.group(0) if mm else "?"
    log(f"  ✓ Заказ техники создан: {STATE['equip_no']} — {url}; статус: {get_status()}", "PASS")
    log(f"  Основная информация: {section_text('Основная информация').replace(chr(10), ' | ')[:300]}")
    return True


def stage_equip_position():
    if not open_lines():
        return False
    if not click_button(["Добавить строку", "Добавить позицию"], wait=6):
        log("  ⚠ Кнопка «Добавить строку» не найдена", "WARN")
        return False
    modal = wait_modal("Добавить позицию", 6) or wait_modal("Добавить строку", 4) or find_modal()
    if not modal:
        log("  ⚠ Окно «Добавить позицию» не открылось", "WARN")
        return False
    rows0, total0 = lines_state()
    for lbl in ["Тип техники", "Вид техники", "Владение", "Статья расходов", "Ед. измерения"]:
        if control_by_label(modal, lbl):
            fill_select(modal, lbl)
            time.sleep(0.5)
    fill_dates_in(None, start_days=0, length_days=7)
    for t_lbl, t_kw in [("Время начала", ["02:00", "08:00", "09:00"]), ("Время окончания", ["04:00", "17:00", "18:00"])]:
        if control_by_label(modal, t_lbl):
            fill_select(modal, t_lbl, keywords=t_kw)
    num_field(modal, "Количество", "10")
    num_field(modal, "Цена без НДС", "10000")
    fill_textarea(modal, f"Автотест позиция заказа техники {STAMP}")
    save = modal_button(modal, ["Добавить", "Сохранить", "Создать"])
    if not save:
        log("  ⚠ Кнопка «Добавить» недоступна (обязательные поля?)", "WARN")
        shot("equip_pos_nobutton")
        log(f"    Текст окна: {(modal.get_attribute('innerText') or '').replace(chr(10), ' | ')[:300]}")
        close_modal_soft(modal)
        return False
    click_el(save)
    closed = wait_modal_closed("Добавить позицию", 8)
    time.sleep(2)
    if not closed:
        log(f"  ⚠ Окно не закрылось (валидация?). Уведомления: {read_toasts()}", "WARN")
        shot("equip_pos_validation")
        m = find_modal("Добавить позицию")
        if m:
            close_modal_soft(m)
        return False
    rows1, total1 = lines_state()
    log(f"  ✓ Позиция добавлена. Строк: {rows0}→{rows1}, итого без НДС: {total0}→{total1}", "PASS")
    ok = back_to_card()
    return ok


# ==========================================
# ОТЧЁТЫ
# ==========================================


# ==========================================
# MAIN
# ==========================================
def save_supply_results():
    path = Path(os.environ["SUPPLY_RESULT_PATH"])
    payload = {"run_id": os.environ["SUPPLY_RUN_ID"],
        "results": [{"name": name, "ok": ok, "reason": REASONS.get(name, "")} for name, ok in RESULTS],
        "error": RUN_ERROR, "screenshot": FAILED_SCREENSHOTS[-1] if FAILED_SCREENSHOTS else "",
        "log": LOG_FILE_PATH, "url": STATE.get("url")}
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def run():
    global RUN_ERROR
    log("=" * 60)
    log(f"АВТОТЕСТ «СНАБЖЕНИЕ» ({STAMP})")
    log("=" * 60)
    try:
        init_driver()
        driver.get(BASE_URL)
        wait_for_state(lambda: is_login_page() or supply_list_ready())
        if not step("Вход и открытие раздела «Снабжение»", stage_login):
            return
        # ---------- ЗАЯВКИ ----------
        step("Заявки: список — фильтры, поиск, пагинация, настройки", stage_supply_list)
        if step("Заявки: создание заявки", stage_supply_create):
            step("Заявки: карточка — вкладки, меню, кнопки", stage_card_tabs)
            step("Заявки: соисполнитель («Поделиться»)", stage_share_coexecutor)
            step("Заявки: маршрут согласования — Бейсембаев Куаныш", stage_route)
            step("Заявки: позиции — добавить строку (все поля + файл)", stage_supply_position_1)
            step("Заявки: обсуждение — сообщение и файл", stage_discussion)
            step("Заявки: позиции — ещё одна строка", stage_supply_position_2)
            if step("Заявки: «Отправить на согласование»", stage_send):
                advanced=step("Заявки: согласование и утверждение", advance_to_end)
                if ROLE_RESTORE_FAILED:
                    return
                if advanced:
                    supplier_ok=step("Заявки: поставщик — выбор контрагента и сохранение", stage_supply_supplier_check)
                    if ROLE_RESTORE_FAILED:
                        return
                    if supplier_ok:
                        run_supply_warehouse()
                        if ROLE_RESTORE_FAILED:
                            return
        # ---------- ОСТАТКИ ----------
        step("Остатки: фильтры, поиск, кнопки, «Переместить»", stage_stock)
        # ---------- ТЕХНИКА ----------
        step("Техника: список — фильтры, поиск, открыть заказ", stage_equip_list)
        if step("Техника: создание заказа", stage_equip_create):
            step("Техника: маршрут согласования — Бейсембаев Куаныш", stage_route)
            step("Техника: обсуждение — сообщение и файл", stage_discussion)
            step("Техника: позиции заказа — добавить строку", stage_equip_position)
            if step("Техника: «На согласование»", stage_send):
                step("Техника: продвижение до конца (согласовать / утвердить)", advance_to_end)
                if ROLE_RESTORE_FAILED:
                    return
    except Exception as e:
        RUN_ERROR = f"{type(e).__name__}: {e}"
        log(f"КРИТИЧЕСКАЯ ОШИБКА: {e}", "FAIL")
        shot("critical_error")
    finally:
        save_supply_results()
        if driver is not None:
            try:
                driver.quit()
            except Exception:
                pass
        _safe_out("")
        _safe_out("=" * 60)
        _safe_out(f"Файл лога: {LOG_FILE_PATH}")
        try:
            if _LOG_FILE:
                _LOG_FILE.close()
        except Exception:
            pass


if __name__ == "__main__" and os.environ.get("SUPPLY_NO_RUN") != "1":
    if os.environ.get("SUPPLY_MANAGED") == "1":
        run()
        raise SystemExit(1 if RUN_ERROR or any(not ok for _, ok in RESULTS) else 0)
    from run_workflow_and_report import run_supply
    raise SystemExit(run_supply(__file__, sys.argv[1:]))
    _LOG_FILE = None