# -*- coding: utf-8 -*-
"""
Контроль качества: предписания, БиОТ, инспекции скрытых работ.
35 сценариев по рабочим процессам: позитивные, отрицательные, границы, роли и сохранение данных.
Запуск: py run_workflow_and_report.py quality.py

Инициатор: Sh Margulan Ju; руководитель/согласующий: Бейсембаев Куаныш;
специалист/исполнитель/наблюдатель: Алдажаров Диас.
Отчёты Telegram и запись чек-листа выполняет только общий run_workflow_and_report.py.
Скриншоты: screens; логи и JSON результатов: logs.
Подпись условная: при наличии действия нужны QUALITY_P12_PATH и QUALITY_NCA_PASSWORD.
Без сертификата подпись не нажимается, причина попадает в отчёт.
Изменяются только записи с уникальной меткой текущего запуска. Возврат Не исполнено проверяется на своих записях. Удаление записей не выполняется.
Акт скрытых работ исключён из сценариев по просьбе пользователя.
Соответствие действий после публикации живому интерфейсу проверяется при запуске.
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

CURRENT_LOGIN = None
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

# Утверждающий / подписант 
SECOND_LOGIN = 'aldazarovdias@gmail.com'
SECOND_PASS = '12341234'
SECOND_NCA_PASSWORD = os.environ.get('QUALITY_NCA_PASSWORD', '')
SECOND_P12_PATH = os.environ.get('QUALITY_P12_PATH', '')

BASE_URL = "https://testportal.rgbgroup.kz/"
ISSUE_URL = BASE_URL + "quality/issue-registration"
BIOT_URL = BASE_URL + "quality/biot"
INSP_URL = BASE_URL + "quality/inspection"
WAIT = 15

STAMP = datetime.now().strftime('%d%m-%H%M%S')
PROJECT_QUERY = "Flagman"
REVIEWER_LOGIN = 'dias.aldazharov@bk.ru'
REVIEWER_PASS = 'h7WxqKIR'

APPROVER_QUERY = 'Margulan'
PROJECT_KEYS = ["flagman", "флагман", "flag", "флаг"]     # проект: Flagman/Флагман
PROJECT_SEARCH = ["Flag", "Флаг"]
CITY_PREFER = ["астан", "нур-султан", "astana"]          # сначала город, где обычно лежит Flagman

# Люди: первый аккаунт (Sh Margulan Ju) и второй (Талгат Ерланович / Ерланович Талгат)
P_MAIN = ["margulan", "маргулан"]
P_TALGAT = ['алдажаров', 'диас']
MAIN_FIRST = [P_MAIN, P_TALGAT]          # приоритет: Margulan, если нет — Талгат
TALGAT_FIRST = [P_TALGAT, P_MAIN]
PERSON_SEARCH_MAIN = ['Margulan', 'Маргулан']
PERSON_SEARCH_TALGAT = ['Алдажаров', 'Диас']

# Кнопки продвижения по статусам (в порядке приоритета). «Отклонить», «На доработку»,
# «Удалить», «Сменить исполнителя» — НЕ нажимаются.
ACTIONS = ["Назначить исполнителя", "Назначить", "Принять в работу", "Взять в работу", "Начать работу",
           "Начать исполнение", "Выполнить", "В работу", "Провести инспекцию", "Исполнить", "Отметить исполненным",
           "Исполнено", "Выполнено", "Отправить на проверку", "На проверку", "Отправить на подтверждение",
           "Подтвердить исполнение", "Подтвердить инспекцию", "Подтвердить", "Принять", "Принять работу",
           "Согласовать", "Утвердить", "Подписать", "Подписать ЭЦП", "Закрыть предписание", "Закрыть",
           "Завершить"]
TO_SIGN = ["Подписать", "Подписать ЭЦП", "Подписать с ЭЦП"]
MODAL_CONFIRM = ["Назначить", "Подтвердить", "Сохранить", "Отправить", "Исполнить", "Принять", "Готово",
                 "Применить", "Завершить", "Закрыть предписание", "Подписать", "Согласовать", "Утвердить",
                 "Да", "ОК", "Ок"]
TERMINAL = ('исполнен', 'исполнено', 'закрыт', 'закрыта', 'закрыто', 'выполнено', 'завершено', 'завершён', 'завершена', 'подтверждено', 'подписано', 'принято')

DOWNLOAD_DIR = os.environ.get("DOWNLOAD_DIR", os.path.join(os.path.expanduser("~"), "Downloads"))
WORK_DIR = os.path.join(tempfile.gettempdir(), f"quality_autotest_{STAMP}")
os.makedirs(WORK_DIR, exist_ok=True)

# ---- Telegram (как в run_workflow_and_report.py) ----
# ВАЖНО: токен секретный. Не выкладывайте файл в публичный репозиторий/общий чат.
# Можно не хранить в файле: задайте переменную окружения TG_TOKEN.

# ---- Google Sheets («Чек-лист») через ваш sheet_reporter.py ----
# Диапазон строк раздела «Контроль качества» в Чек-листе, например (180, 230). None — искать
# названия проверок во всём столбце B. Названия = названия этапов (с префиксом «Предписания:» /
# «БиОТ:» / «Инспекции:»).

STATE = {"url": None, "summary": [], "records": {}}     # records: модуль -> (номер, url, статус)
RESULTS = []        # (название, ok)
FAILED_SCREENSHOTS = []
RUN_ERROR = ""
ROLE_RESTORE_FAILED = False
REASONS = {}        # название -> причина провала
LOG_LINES = []
_RUN_STARTED = time.time()

LOG_FILE_PATH = log_path(f"quality_log_{STAMP}_{os.environ.get('QUALITY_RUN_ID', 'standalone')}.txt")
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
        path = screen_path(f"debug_quality_{safe}_{os.environ.get('QUALITY_RUN_ID', STAMP)}_{time.time_ns()}.png")
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
        literal=json.dumps(t,ensure_ascii=False)
        xp = (f"{pre}*[self::button or self::a or @role='button']"
              f"[normalize-space(.)={literal} or @aria-label={literal} or @title={literal}]")
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

def wait_modal(hint=None,timeout=8):
    result=wait_for_state(lambda:find_modal(hint),timeout=timeout,poll=.15)
    return result if result else None

def wait_modal_closed(hint=None,timeout=8):
    return bool(wait_for_state(lambda:find_modal(hint) is None,timeout=timeout,poll=.15))

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
        p = wait_for_state(visible_panel,timeout=3)
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
        if wait_for_state(lambda:visible_panel() is None,timeout=3):
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
            if wait_for_state(lambda:visible_panel() is None,timeout=3):
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

def send_file(path, scope=None, input_element=None):
    inp = input_element
    try:
        if inp is None:
            inp = driver.execute_script(
                "var i=window.__lastFileInput, root=arguments[0]||document; return i&&document.contains(i)&&root.contains(i)?i:null;",scope)
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
        def uploaded():
            current=scope if scope is not None else driver
            return os.path.basename(path) in (current.get_attribute('innerText') or '') if scope is not None else os.path.basename(path) in innertext()
        if not wait_for_state(uploaded):
            log(f"    ⚠ Загрузка файла не подтверждена: {os.path.basename(path)}", "WARN")
            return False
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
    global CURRENT_LOGIN
    CURRENT_LOGIN = None
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
    type_text(login_field, login_value)
    type_text(pw_field, password_value)
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
    wait_for_state(lambda: not is_login_page() and bool(find_buttons(['Выйти']) or driver.find_elements(By.CSS_SELECTOR, 'aside, nav')), timeout=30)
    if is_login_page():
        log(f"  ⚠ Логин {login_value} не удался", "WARN")
        return False
    log(f"  ✓ Успешный вход: {login_value}", "PASS")
    dismiss_news_popup(wait=2)
    CURRENT_LOGIN = login_value
    return True

def logout_current_account():
    global CURRENT_LOGIN
    CURRENT_LOGIN = None
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

def ncalayer_present(timeout=10):
    try:
        from pywinauto import Desktop
    except ImportError:
        return False
    for _ in range(int(timeout)):
        try:
            if Desktop(backend="uia").windows(title_re=".*NCALayer.*"):
                return True
        except Exception:
            pass
        time.sleep(1)
    return False

def sign_with_ncalayer(password, p12_path, appear_timeout=40):
    try:
        from pywinauto import Application, Desktop
        from pywinauto.keyboard import send_keys
    except ImportError:
        log("  ⚠ pywinauto не установлен: pip install pywinauto", "WARN")
        return False
    time.sleep(2)
    dialog = None
    for _ in range(appear_timeout):
        try:
            if Desktop(backend="uia").windows(title_re=".*NCALayer.*"):
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
    log("  ✓ NCALayer найден", "PASS")
    try:
        dialog.set_focus()
    except Exception:
        pass
    time.sleep(1)

    if p12_path:
        if not os.path.exists(p12_path):
            log(f"  ⚠ Файл ЭЦП не найден: {p12_path}", "WARN")
            return False
        file_re = "(Файлды таңдаңыз|Выберите файл|Open|Открыть|Открытие)"
        opened_dlg = False
        try:
            btns = dialog.descendants(control_type="Button")
            if len(btns) > 4:
                btns[4].click_input()
                opened_dlg = True
        except Exception:
            pass
        if not opened_dlg:
            try:
                for b in dialog.descendants(control_type="Button"):
                    try:
                        b.click_input()
                        time.sleep(1.5)
                        if Desktop(backend="win32").windows(title_re=file_re):
                            opened_dlg = True
                            break
                    except Exception:
                        continue
            except Exception:
                pass
        if not opened_dlg:
            log("  ⚠ Кнопка выбора файла ЭЦП не найдена", "WARN")
            return False
        time.sleep(1.5)
        try:
            fapp = Application(backend="win32").connect(title_re=file_re, timeout=30)
            fdlg = fapp.window(title_re=file_re)
            fdlg.wait("visible", timeout=10)
            fdlg.set_focus()
            edit = fdlg.child_window(class_name="Edit")
            edit.set_edit_text(p12_path)
            time.sleep(1)
            edit.type_keys("{ENTER}")
            time.sleep(2)
        except Exception as e:
            log(f"  ⚠ Диалог файла: {e}", "WARN")
            return False
        try:
            dialog.set_focus()
        except Exception:
            pass
        time.sleep(1)

    pw_ok = False
    for nm in ["ПарольEdit", "ҚұпиясөзEdit"]:
        try:
            dialog[nm].set_edit_text("")
            dialog[nm].type_keys(password, with_spaces=True)
            pw_ok = True
            break
        except Exception:
            continue
    if not pw_ok:
        try:
            edits = dialog.descendants(control_type="Edit")
            if edits:
                edits[-1].click_input()
                send_keys("^a{DELETE}")
                edits[-1].type_keys(password, with_spaces=True)
                pw_ok = True
        except Exception:
            pass
    if not pw_ok:
        log("  ⚠ Пароль ЭЦП не введён", "WARN")
        return False
    time.sleep(0.8)

    opened = False
    for nm in ["Ашу", "Открыть", "Open"]:
        try:
            b = dialog.child_window(title=nm, control_type="Button")
            if b.exists():
                b.click_input()
                opened = True
                break
        except Exception:
            continue
    if not opened:
        send_keys("{ENTER}")
    time.sleep(3)
    try:
        app = Application(backend="uia").connect(title_re=".*NCALayer.*", timeout=15)
        dialog = app.window(title_re=".*NCALayer.*")
        dialog.set_focus()
    except Exception:
        pass
    items = []
    for _ in range(10):
        try:
            items = dialog.descendants(control_type="ListItem")
            if items:
                break
        except Exception:
            pass
        time.sleep(1)
    if not items:
        log("  ⚠ Список ключей пуст — неверный пароль?", "WARN")
        return False
    try:
        items[0].click_input()
    except Exception:
        pass
    time.sleep(1)
    clicked = False
    for nm in ["Қол қою", "Подписать", "Sign"]:
        try:
            b = dialog.child_window(title=nm, control_type="Button")
            if b.exists():
                b.click_input()
                clicked = True
                break
        except Exception:
            continue
    if not clicked:
        send_keys("{ENTER}")
    time.sleep(4)
    try:
        if Desktop(backend="uia").windows(title_re=".*NCALayer.*"):
            log("  ⚠ NCALayer всё ещё открыт", "WARN")
            return False
    except Exception:
        pass
    log("  ✓ NCALayer закрылся — подписание выполнено", "PASS")
    return True

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
    from route_helper import setup_margulan_route
    goto_card()
    return setup_margulan_route(driver, log=log)

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

def click_action(texts):
    """Нажать статусную кнопку и подтвердить модалку, если появится. Возвращает текст кнопки."""
    btns = find_buttons(texts)
    if not btns:
        return None
    label = (btns[0].text or "").strip() or texts[0]
    scroll_to(btns[0])
    initial_status=get_status()
    click_el(btns[0])
    wait_for_state(lambda:find_modal() or get_status()!=initial_status,timeout=WAIT)
    modal = find_modal()
    if modal:
        try:
            for ta in modal.find_elements(By.XPATH, ".//textarea"):
                if ta.is_displayed() and ta.is_enabled():
                    type_text(ta, f"Автотест: {label} ({STAMP})")
                    break
        except Exception:
            pass
        confirm_names=texts+["Подтвердить", "Отправить", "Сохранить", "ОК", "Да"]
        if label=='Не исполнено':confirm_names=['Отклонить']+confirm_names
        conf = modal_button(modal, confirm_names)
        if conf:
            click_el(conf)
            log(f"    Подтверждение '{label}' нажато")
            wait_for_state(lambda:find_modal() is None or bool(field_errors()),timeout=WAIT)
    return label

def stage_discussion():
    if not quality_owned_card():return False
    click_text_deepest('Обсуждение','exact')
    def textarea():
        return next((e for e in driver.find_elements(By.XPATH,"//textarea[contains(@placeholder,'ообщени')]") if e.is_displayed()),None)
    ta=wait_for_state(textarea)
    if ta is None:
        log('  ⚠ Поле сообщения не найдено','WARN');return False
    marker=QUALITY_CASE.get('marker') or STAMP
    msg=f'Автотест: сообщение по контролю качества {marker}'
    block_native_file_dialog()
    type_text(ta,msg)
    pdf=create_test_pdf('discussion_'+marker)
    # Upload immediately adds a file message to the feed, outside the composer.
    # Confirm it in the whole chat, then never retry an already submitted upload.
    try:
        chat=ta.find_element(By.XPATH,"./ancestor::*[contains(concat(' ',normalize-space(@class),' '),' od-chat ')][1]")
    except Exception:
        log('  ⚠ Область обсуждения не найдена; файл не отправлен','WARN');return False
    if not send_file(pdf,scope=chat):
        log('  ⚠ Вложение обсуждения не подтверждено; повторная отправка исключена','WARN');return False
    if not click_button(['Отправить'],wait=3,last=True):
        log('  ⚠ Кнопка Отправить не найдена','WARN');return False
    def message_in_feed():
        return driver.execute_script("""
            const root=arguments[0], text=arguments[1];
            return Array.from(root.querySelectorAll('*')).some(e=>
                !e.children.length && !['TEXTAREA','INPUT'].includes(e.tagName) &&
                (e.innerText||'').trim()===text);
        """,chat,msg)
    ok=bool(wait_for_state(message_in_feed))
    log(f"  Сообщение в ленте: {'есть' if ok else 'нет'}",'PASS' if ok else 'WARN')
    return bool(ok and os.path.basename(pdf) in innertext())

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
        time.sleep(0.8)
        if calendar_goto(target.year, target.month):
            cell = cell_by_day(calendar_cells(), target.day)
            if cell is not None:
                click_el(cell)
                time.sleep(0.8)
                if not date_empty(trigger):
                    return True
        else:
            cells = calendar_cells()          # не смогли листать — берём любой доступный день
            if cells:
                click_el(cell_by_day(cells, target.day))
                time.sleep(0.8)
                if not date_empty(trigger):
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
        time.sleep(0.6)
        return not date_empty(trigger)
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
                         'Назначение исполнителя','Исполнено','Подтверждение инспекции','Подтверждено',
                         'В работе','На проверке','На подтверждении','Выполнено','Закрыто','Опубликовано',
                         'Новое','Новая','Просрочено','Устранение','На устранении','Устранено',
                         'Проверка исполнения','Приёмка работ','Формирование печатной версии','Принято','Завершено','Завершена','Ожидает'];
            var els = document.querySelectorAll('span,div,p,b,strong,small');
            for (var i = 0; i < els.length; i++) {
                var e = els[i];
                if (e.children.length || !(e.offsetWidth || e.offsetHeight) || e.closest('button,a,nav,aside,table,[role=button],[role=option],[role=dialog],[role=tab],[role=listbox]')) continue;
                var t = (e.textContent || '').trim();
                if (words.indexOf(t) >= 0) return t;
            }
            return null;
        """)
    except Exception:
        return None


def status_terminal(status):
    return (status or '').strip().lower() in TERMINAL


def at_url(url):
    return urlparse(driver.current_url).path.rstrip("/") == urlparse(url).path.rstrip("/")


def nav_menu(item,url):
    if not at_url(url):
        click_text_deepest('Контроль качества','exact')
        click_text_deepest(item,'exact')
        if not wait_for_state(lambda:at_url(url),timeout=3):
            driver.get(url)
    return quality_list_ready(url)


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
    return "margulan" in seg or "маргулан" in seg


def goto_card():
    url=STATE.get('url')
    if not url:
        return False
    if not at_url(url):
        driver.get(url)
    return bool(wait_for_state(lambda:at_url(url) and get_status()))


def open_lines():
    if "/lines" in driver.current_url:
        block_native_file_dialog()
        return True
    goto_card()
    if click_button(["Позиции заявки", "Позиции заказа"], wait=8) or \
            click_text_deepest("Позиции з", "prefix"):
        for _ in range(10):
            if "/lines" in driver.current_url:
                time.sleep(2)
                block_native_file_dialog()
                return True
            time.sleep(1)
    driver.get(STATE["url"].rstrip("/") + "/lines")
    time.sleep(4)
    block_native_file_dialog()
    return "/lines" in driver.current_url


def back_to_card():
    if click_button(["Вернуться к основной информации"], wait=3) or \
            click_text_deepest("Вернуться к основной информации", "contains"):
        time.sleep(2.5)
        log("  ✓ «Вернуться к основной информации»", "PASS")
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


def ctrl_unset(ctrl, label=""):
    """Не выбрано: пусто / текст-подсказка / у кнопки класс ui-select__trigger--placeholder
    (так выглядит, например, «Сдача/приёмка скрытых работ» в «Вид работ» — это подсказка, не значение)."""
    try:
        if "placeholder" in (ctrl.get_attribute("class") or "").lower():
            return True
    except Exception:
        pass
    t = (ctrl.get_attribute("textContent") or "").strip().lower()
    return (not t) or t.startswith(PLACEHOLDERS) or t == label.lower()


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
const control=arguments[0];
const visible=e=>!!(e&&(e.offsetWidth||e.offsetHeight||e.getClientRects().length));
const id=control.getAttribute('aria-controls');
let root=id?document.getElementById(id):null;
if(!visible(root))root=Array.from(document.querySelectorAll('[role="listbox"],.ui-select__panel')).filter(visible).pop();
if(!root)return {open:false,input:null,opts:[],empty:false};
const rows=Array.from(root.querySelectorAll('[role="option"],button.ui-select__option'));
const seen=new Set();
const opts=[];
for(const row of rows){
    if(!visible(row)||row.disabled||row.getAttribute('aria-disabled')==='true')continue;
    const label=row.querySelector('.ui-select__option-label');
    const text=((label||row).innerText||'').replace(/\s+/g,' ').trim();
    if(!text||/^(нет данных|ничего не найдено|загрузка[.…]*)$/i.test(text)||seen.has(text))continue;
    seen.add(text);opts.push({element:row,text});
}
const input=Array.from(root.querySelectorAll('input')).find(visible)||null;
const busy=/загрузка/i.test(root.innerText||'')||root.getAttribute('aria-busy')==='true';
return {open:true,input,opts,empty:!busy&&!opts.length&&/ничего не найден|не найден|нет данных|пусто|no results|no data/i.test(root.innerText||'')};
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
    """Wait only while the dropdown is opening; a ready dropdown returns immediately."""
    if ctrl is None:return False
    if popup_is_open(ctrl):return True
    scroll_to(ctrl)
    for method in ('hard','js','selenium'):
        if popup_is_open(ctrl):return True
        try:
            if method=='hard':hard_click(ctrl)
            elif method=='js':js_click(ctrl)
            else:ctrl.click()
        except Exception:
            continue
        if wait_for_state(lambda:popup_is_open(ctrl),timeout=1.8,poll=.1):return True
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
    """keywords: список слов ИЛИ список групп слов (по приоритету: сначала первая группа)."""
    if not keywords:
        return None
    groups = keywords if isinstance(keywords[0], (list, tuple)) else [keywords]
    for g in groups:
        for o in opts:
            low = o["text"].lower()
            if any(k.lower() in low for k in g):
                return o
    return None


def close_popup(ctrl=None):
    """Do not send Escape twice after a dropdown has already closed."""
    if ctrl is None or not popup_is_open(ctrl):return
    try:
        _,inp,_=popup_state(ctrl)
        if inp is not None:inp.send_keys(Keys.ESCAPE)
        else:ActionChains(driver).send_keys(Keys.ESCAPE).perform()
    except Exception:
        pass
    if not wait_for_state(lambda:not popup_is_open(ctrl),timeout=.8,poll=.1):
        close_panels()
        if not wait_for_state(lambda:not popup_is_open(ctrl),timeout=2,poll=.1):
            log('    ⚠ Список не закрылся после Escape','WARN')


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


def quality_pick_dias(ctrl,label):
    def selected():
        text=(ctrl.get_attribute('textContent') or '').strip()
        return bool(re.fullmatch(r'Алдажаров\s+Диас(?:\s+Андреевич)?',text,re.I))
    if selected():return 'Алдажаров Диас Андреевич'
    if not open_popup(ctrl):return None
    def target():
        _,_,options=popup_state(ctrl)
        return next((o for o in options if re.fullmatch(r'Алдажаров\s+Диас(?:\s+Андреевич)?',o['text'].strip(),re.I)),None)
    inp,options=wait_options(ctrl,5)
    option=target()
    if option is None and inp is not None:
        quality_keyboard_input(inp,'Алдажаров')
        option=wait_for_state(target,timeout=5)
    if option is None:
        close_popup(ctrl)
        log(f'    ⚠ {label}: Алдажаров Диас не найден; другой сотрудник не выбран','WARN')
        return None
    if not _click_option(option,ctrl):
        close_popup(ctrl);return None
    close_popup(ctrl)
    if not wait_for_state(selected,timeout=5):
        log(f"    ⚠ {label}: после выбора получено {(ctrl.get_attribute('textContent') or '').strip()!r}",'WARN')
        return None
    log(f'    ✓ {label}: Алдажаров Диас Андреевич','PASS')
    return 'Алдажаров Диас Андреевич'


def fill_select(scope, label, keywords=None, search=None, index=0, force=False):
    """Селект по подписи. Если уже выбран — пропуск. Иначе: ждём доступность поля, открываем список
    одним кликом, берём вариант по ключевым словам (в списке, затем через поиск), иначе вариант №index.
    До 3 попыток; результат проверяется по тексту поля."""
    if label in ('Начальник участка','Руководитель проекта'):
        ctrl=wait_ctrl_enabled(scope,label,6)
        return bool(ctrl is not None and ctrl_enabled(ctrl) and quality_pick_dias(ctrl,label))
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
        wait_for_state(lambda:control_by_label(scope,label) is not None and not ctrl_unset(control_by_label(scope,label),label),timeout=6)
        ctrl = control_by_label(scope, label)
        if ctrl is not None and not ctrl_unset(ctrl, label):
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
            if ok:
                time.sleep(1.0)
            else:
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
    if not wait_for_state(lambda: is_login_page() or bool(find_buttons(['Выйти'])), timeout=30):
        return False
    if is_login_page() and not login_with(login_val, pass_val):
        return False
    driver.get(ISSUE_URL)
    if wait_for_state(is_login_page, timeout=3):
        if not login_with(login_val, pass_val):
            return False
        driver.get(ISSUE_URL)
    return quality_list_ready(ISSUE_URL)


def switch_user(login,password):
    if CURRENT_LOGIN==login and not is_login_page():
        expected={login_val:['margulan','маргулан'],REVIEWER_LOGIN:['бейсембаев'],SECOND_LOGIN:['алдажаров','алдазаров']}.get(login,[])
        matched=driver.execute_script(r"""
            const expected=arguments[0];
            const exit=Array.from(document.querySelectorAll('button,a')).find(e=>
                (e.offsetWidth||e.offsetHeight)&&(e.innerText||'').trim()==='Выйти');
            if(!exit||!expected.length)return false;
            let p=exit.parentElement;
            for(let k=0;p&&k<3;k++,p=p.parentElement){
                const text=(p.innerText||'').toLowerCase();
                if(expected.some(name=>text.includes(name)))return true;
            }return false;
        """,expected)
        if matched:
            return True
    if not logout_current_account():
        driver.get(BASE_URL)
        if not wait_for_state(is_login_page):return False
    return login_with(login,password)


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
    pt=pager_text()
    if not pt:
        total=page_total()
        rows=driver.find_elements(By.XPATH,'//tbody/tr')
        shown=sum(1 for r in rows if r.is_displayed())
        return total is not None and (total==0 or 0<total<=shown)
    if pt[1]<2:
        log('  Одна страница: переход на следующую не требуется')
        return pt[0]==1
    if pt[0]!=1:
        log('  ⚠ Пагинация должна начинаться с первой страницы','WARN')
        return False
    def move(index,target):
        buttons=driver.execute_script(JS_PAGER)
        return bool(buttons and len(buttons)>=4 and click_el(buttons[index]) and
            wait_for_state(lambda:pager_text()==target))
    return move(2,(2,pt[1])) and move(1,pt)


def test_rows_per_page():
    for trigger in visible_selects():
        original=(trigger.get_attribute('textContent') or '').strip()
        if not re.fullmatch(r'\d+',original):
            continue
        panel=open_ui(trigger)
        options=[o['text'] for o in panel_options(panel)] if panel is not None else []
        alternate=next((o for o in reversed(options) if o!=original and re.fullmatch(r'\d+',o)),None)
        if alternate is None:
            close_panels()
            return False
        def current():
            return next((t for t in visible_selects() if re.fullmatch(r'\d+', (t.get_attribute('textContent') or '').strip())),None)
        def selected(text):
            item=current()
            return item is not None and (item.get_attribute('textContent') or '').strip()==text
        picked=select_in_panel(panel,keywords=[alternate])
        ok=bool(picked and wait_for_state(lambda:selected(alternate)))
        trigger=current()
        if trigger is None:
            return False
        panel=open_ui(trigger)
        restored=select_in_panel(panel,keywords=[original]) if panel is not None else None
        return bool(ok and restored and wait_for_state(lambda:selected(original)))
    return False


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
        ok = False
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
# КОНТРОЛЬ КАЧЕСТВА: общие инструменты
# ==========================================
CODE_RE = re.compile(r"#\d{6,10}")
CODE_ANY_RE = re.compile(r"#\d{6,10}|(?<![\d.])2\d{7}(?![\d.])")

JS_LABEL_OF = r"""
var e = arguments[0], own = (e.innerText || '').trim(), c = e;
for (var i = 0; i < 5; i++) {
    c = c.parentElement; if (!c) break;
    var lines = (c.innerText || '').split('\n').map(function(s){ return s.trim(); }).filter(Boolean);
    for (var j = 0; j < lines.length; j++) {
        if (lines[j] !== own && lines[j].length < 60) return lines[j];
    }
}
return '';
"""


def label_of(el):
    try:
        return (driver.execute_script(JS_LABEL_OF, el) or "").strip()
    except Exception:
        return ""


def person_pref(label):
    label=(label or '').lower()
    if 'руковод' in label or 'начальник участка' in label:
        return [P_TALGAT], PERSON_SEARCH_TALGAT
    if any(k in label for k in ('специалист','дтн','наблюдат','получател','исполнител')):
        return [P_TALGAT], PERSON_SEARCH_TALGAT
    if any(k in label for k in ('начальник','инженер','ответствен')):
        return [P_MAIN], PERSON_SEARCH_MAIN
    return None,None


def pick_in(ctrl, keywords=None, search=None, label=""):
    """Открыть конкретный селект и выбрать (ключевые слова с приоритетом, иначе первый)."""
    if label in ('Начальник участка','Руководитель проекта'):
        return quality_pick_dias(ctrl,label)
    if not open_popup(ctrl):
        return None
    inp, opts = wait_options(ctrl, 5)
    if not opts:
        close_popup(ctrl)
        return None
    target = _pick(opts, keywords) if keywords else None
    if target is None and keywords and search and inp is not None:
        for term in search:
            try:
                type_text(inp, term)
            except Exception:
                break
            time.sleep(1.2)
            _i, opts2 = wait_options(ctrl, 3)
            target = _pick(opts2, keywords)
            if target:
                break
        if target is None:
            try:
                type_text(inp, "")
            except Exception:
                pass
            time.sleep(0.8)
            _i, opts = wait_options(ctrl, 3)
    if target is None and opts:
        target = opts[0]
    if target is None:
        close_popup(ctrl)
        return None
    _click_option(target, ctrl)
    close_popup(ctrl)
    return target["text"]


def fill_all_unset(scope=None, tag=""):
    """Все видимые незаполненные селекты на странице/в окне: люди — по приоритету, прочее — первый вариант."""
    n = 0
    for _ in range(2):
        changed = False
        for ctrl in visible_selects(scope):
            try:
                if not ctrl_enabled(ctrl) or not ctrl_unset(ctrl, ""):
                    continue
                lab = label_of(ctrl)
                if re.search(r"строк на стр|^\d+$", lab.lower()):
                    continue
                kw, srch = person_pref(lab)
                got = pick_in(ctrl, kw, srch, lab)
                if got:
                    n += 1
                    changed = True
                    log(f"    ✓ {lab or 'поле'}: {got}{(' ' + tag) if tag else ''}", "PASS")
                time.sleep(0.6)
            except Exception:
                continue
        if not changed:
            break
    return n


def fill_page_selects(specs, passes=2):
    """specs: [(label, kwargs)] на странице создания (не в модалке). Несколько проходов —
    зависимые поля открываются только после родителя."""
    missing = []
    for ps in range(passes):
        missing = []
        for label, kw in specs:
            ctrl = control_by_label(driver, label)
            if ctrl is None:
                missing.append(label)
                continue
            if not ctrl_unset(ctrl, label):
                continue
            if not fill_select(driver, label, **kw):
                missing.append(label)

        if not missing:
            break
        log(f"    ↻ Не заполнены: {missing} — проход {ps + 2}")
        time.sleep(1.5)
    return missing


def person_select(label, prefer="main"):
    kw,srch=person_pref(label)
    if kw is None:
        kw,srch=([P_MAIN],PERSON_SEARCH_MAIN) if prefer=='main' else ([P_TALGAT],PERSON_SEARCH_TALGAT)
    return label,dict(keywords=kw,search=srch)


def pick_city_project(city_label="Город", project_label="Проект"):
    """Город -> Проект Flagman. Если в первом городе Flagman нет — пробуем другие города."""
    city = control_by_label(driver, city_label)
    if city is None:
        return fill_select(driver, project_label, keywords=PROJECT_KEYS, search=PROJECT_SEARCH)
    if not open_popup(city):
        log("    ⚠ Список «Город» не открылся", "WARN")
        return False
    _i, opts = wait_options(city, 5)
    cities = list(dict.fromkeys(o["text"] for o in opts))[:10]
    close_popup(city)
    cities.sort(key=lambda c: 0 if any(k in c.lower() for k in CITY_PREFER) else 1)
    log(f"    Города: {cities}")
    for c in cities:
        if not fill_select(driver, city_label, keywords=[c.lower()], force=True):
            continue
        pctrl = wait_ctrl_enabled(driver, project_label, 6)
        if pctrl is None or not ctrl_enabled(pctrl):
            continue
        if not open_popup(pctrl):
            continue
        _i, popts = wait_options(pctrl, 5)
        t = _pick(popts, PROJECT_KEYS)
        if t:
            _click_option(t, pctrl)
            close_popup(pctrl)
            pctrl = control_by_label(driver, project_label)
            if pctrl is not None and not ctrl_unset(pctrl, project_label):
                log(f"    ✓ {city_label}: {c}; {project_label}: {t['text']}", "PASS")
                return True
        else:
            log(f"    · В городе «{c}» проекта Flagman нет: {[o['text'][:25] for o in popts[:5]]}")
            close_popup(pctrl)
    # Flagman не нашёлся ни в одном городе — берём первый доступный проект
    log("    ⚠ Flagman не найден ни в одном городе — беру первый проект", "WARN")
    if cities:
        fill_select(driver, city_label, keywords=[cities[0].lower()], force=True)
    return fill_select(driver, project_label)


def _base_fill_ph(placeholder, value, tag="*", exact=False):
    """Поле ввода/текст по placeholder (точное совпадение или «содержит»)."""
    cond = f"@placeholder='{placeholder}'" if exact else f"contains(@placeholder,'{placeholder}')"
    try:
        els = [e for e in driver.find_elements(By.XPATH, f"//{tag}[{cond}]") if e.is_displayed()]
    except Exception:
        els = []
    if not els:
        log(f"    ⚠ Поле «{placeholder}» не найдено", "WARN")
        return False
    el = els[0]
    scroll_to(el)
    type_text(el, value)
    v = (el.get_attribute("value") or "").strip()
    log(f"    {'✓' if v else '⚠'} «{placeholder}»: {v[:60]}", "PASS" if v else "WARN")
    return bool(v)


def fill_ph(placeholder,value,tag='*',exact=False):
    ok=_base_fill_ph(placeholder,value,tag,exact)
    if ok and QUALITY_CASE:
        item={'placeholder':placeholder,'value':str(value)}
        if item not in QUALITY_CASE['expected']:QUALITY_CASE['expected'].append(item)
    return ok


def ensure_section(title,probe_label=None):
    """Open a collapsed section once, then wait for its actual state."""
    def probe_visible():
        if not probe_label:return False
        return any(e.is_displayed() for e in driver.find_elements(By.XPATH,
            "//*[normalize-space(text())="+json.dumps(probe_label,ensure_ascii=False)+"] | //*[@placeholder="+json.dumps(probe_label,ensure_ascii=False)+"]"))
    def button():
        return next((e for e in driver.find_elements(By.XPATH,
            "//button[contains(normalize-space(.),"+json.dumps(title,ensure_ascii=False)+")]") if e.is_displayed()),None)
    if probe_visible():return True
    control=button()
    if control is None:
        log(f'    ⚠ Секция «{title}» не найдена','WARN');return False
    if control.get_attribute('aria-expanded')!='true' and not click_el(control):return False
    def ready():
        if probe_label:return probe_visible()
        current=button()
        return current is not None and current.get_attribute('aria-expanded')=='true'
    ok=bool(wait_for_state(ready))
    log(f"    {'✓' if ok else '⚠'} Секция «{title}» {'раскрыта' if ok else 'не раскрылась'}",'PASS' if ok else 'WARN')
    return ok


def _base_choose_chip(names):
    """Чипы «Тип замечания»: прокликать все и оставить последний из names."""
    last = None
    for n in names:
        b = find_buttons([n])
        if b:
            click_el(b[0])
            time.sleep(0.5)
            last = n
    if last:
        log(f"    ✓ Тип замечания: проверены {names}, выбран «{last}»", "PASS")
        return True
    log("    ⚠ Чипы «Тип замечания» не найдены", "WARN")
    return False


def choose_chip(names):
    return _base_choose_chip([QUALITY_CASE['kind']] if QUALITY_CASE else names)


JS_CHECKBOX_BY_LABEL = r"""
var t = arguments[0], all = document.querySelectorAll('label, span, div, p');
function vis(e){ return !!(e.offsetWidth || e.offsetHeight || e.getClientRects().length); }
for (var i = 0; i < all.length; i++) {
    var e = all[i];
    if (!vis(e) || (e.textContent || '').trim() !== t) continue;
    var c = e;
    for (var k = 0; k < 4 && c; k++) {
        var cb = c.querySelector('input[type=checkbox]');
        if (cb) return [c, cb];
        c = c.parentElement;
    }
    return [e, null];
}
return null;
"""


def tick(label):
    try:
        r = driver.execute_script(JS_CHECKBOX_BY_LABEL, label)
    except Exception:
        r = None
    if not r:
        log(f"    ⚠ Галочка «{label}» не найдена", "WARN")
        return False
    holder, cb = r[0], r[1]
    if cb is not None and cb.is_selected():
        log(f"    ✓ «{label}» уже отмечено", "PASS")
        return True
    target = cb if (cb is not None and cb.is_displayed()) else holder
    click_el(target)
    time.sleep(0.5)
    if cb is not None and not cb.is_selected():
        hard_click(holder)
        time.sleep(0.5)
    ok = cb.is_selected() if cb is not None else True
    log(f"    {'✓' if ok else '⚠'} Галочка «{label}»", "PASS" if ok else "WARN")
    return ok


def fill_dates_any(start_days):
    """Все пустые даты на странице; если ui-date-picker не распознан — ищем «Выбрать дату»."""
    n = fill_dates_in(None, start_days=start_days, length_days=0)
    if n:
        return n
    target = dtm.date.today() + dtm.timedelta(days=start_days)
    try:
        trs = driver.find_elements(By.XPATH, "//*[normalize-space(text())='Выбрать дату']/ancestor::*"
                                             "[self::button or contains(@class,'trigger') or @role='button'][1]")
    except Exception:
        trs = []
    for t in trs:
        if t.is_displayed() and pick_date(t, target):
            n += 1
            log(f"    ✓ Дата: {date_text(t)}", "PASS")
    if not n:
        log("    ⚠ Поле даты не заполнено", "WARN")
    return n


def set_time_inputs(value="10:00"):
    n = 0
    for el in driver.find_elements(By.XPATH, "//input[@type='time']"):
        try:
            if not el.is_displayed():
                continue
            if not el.is_enabled():
                time.sleep(1)
            set_native_value(el, value)
            if not (el.get_attribute("value") or ""):
                el.send_keys("1000AM")
            v = el.get_attribute("value") or ""
            log(f"    {'✓' if v else '⚠'} Время: {v or 'не задано'}", "PASS" if v else "WARN")
            n += 1 if v else 0
        except Exception:
            continue
    return n


def attach_files(prefix):
    block_native_file_dialog()
    paths=[create_test_pdf(prefix+'_doc'),create_test_png(prefix+'_photo')]
    ok=True
    for path in paths:
        if not send_file(path) or not wait_for_state(lambda:os.path.basename(path) in innertext()):ok=False
    if QUALITY_CASE:
        QUALITY_CASE['uploads']=[os.path.basename(p) for p in paths]
        QUALITY_CASE['uploads_ok']=ok
    return ok


JS_FIELD_ERRORS = r"""
function vis(e){ return !!(e.offsetWidth || e.offsetHeight || e.getClientRects().length); }
var out = [];
document.querySelectorAll('[class*="error"], [class*="invalid"], [role=alert]').forEach(function(e){
    if (!vis(e)) return; var t = (e.innerText || '').trim();
    if (t && t.length < 120 && out.indexOf(t) < 0) out.push(t);
});
return out.slice(0, 10);
"""


def field_errors():
    try:
        return driver.execute_script(JS_FIELD_ERRORS) or []
    except Exception:
        return []


def list_codes():
    return [int(c[1:]) for c in CODE_RE.findall(innertext())]


def open_code(code_text):
    el = driver.execute_script("""
        var t = arguments[0], all = document.querySelectorAll('*');
        for (var i = 0; i < all.length; i++) { var e = all[i];
            if (!e.children.length && (e.offsetWidth || e.offsetHeight) && (e.textContent || '').trim() === t) return e; }
        return null;""", code_text)
    if el is None:
        return False
    hard_click(el)
    return bool(wait_for_state(lambda:get_status() and (code_text in innertext() or code_text.lstrip("#") in innertext())))


def publish(list_url):
    raise RuntimeError('Публикация допускается только сценарием с проверкой уникальной метки')


def record_card(module):
    t = innertext()
    m = CODE_RE.search(t) or CODE_ANY_RE.search(t)
    code = m.group(0) if m else "?"
    if code != "?" and not code.startswith("#"):
        code = "#" + code
    if code == "?" and STATE.get("new_code", {}).get(module):
        code = STATE["new_code"][module]
    st = get_status()
    STATE["records"][module] = [code, STATE["url"], st]
    return code, st


# ---------- список ----------
JS_ROW_MENU = r"""
function vis(e){ return !!(e.offsetWidth || e.offsetHeight || e.getClientRects().length); }
var all = document.querySelectorAll('*'), code = null;
for (var i = 0; i < all.length; i++) { var e = all[i];
    if (!e.children.length && vis(e) && /^#\d{6,10}$/.test((e.textContent || '').trim())) { code = e; break; } }
if (!code) return null;
var row = code;
for (var k = 0; k < 8 && row; k++) {
    row = row.parentElement;
    if (!row) break;
    if (row.tagName === 'TR' || row.getAttribute('role') === 'row') break;
    if (row.getBoundingClientRect().width > 900 && row.getBoundingClientRect().height < 90) break;
}
if (!row) return null;
var bs = Array.prototype.filter.call(row.querySelectorAll('button, [role=button]'), function(b){
    var t = (b.innerText || '').trim(); return vis(b) && (!t || /^[.⋯…•·⋮]+$/.test(t)); });
return bs.length ? bs[bs.length - 1] : null;
"""


def test_row_menu():
    try:
        b = driver.execute_script(JS_ROW_MENU)
    except Exception:
        b = None
    if b is None:
        log("  • Кнопка «⋯» в строке не найдена")
        return page_total() == 0
    hard_click(b)
    time.sleep(1)
    items = [t for t in visible_actions() if t]
    shot("row_menu")
    log(f"  ✓ Меню «⋯» строки открыто (пункты НЕ нажимаются). Видимые кнопки: {items[-8:]}", "PASS")
    esc()
    time.sleep(0.5)
    if find_modal():
        close_modal_soft(find_modal())
    return True


def test_date_filter(label):
    if not click_text_deepest(label, "exact"):
        log(f"  • Фильтр по дате «{label}» не найден")
        return False
    time.sleep(1)
    selected = False
    cells = calendar_cells()
    if cells:
        try:
            click_el(cells[0])
            time.sleep(0.5)
            cells = calendar_cells()
            if cells:
                click_el(cells[-1])
            time.sleep(2)
            selected = True
            log(f"  ✓ Фильтр «{label}»: выбран период, всего записей {page_total()}", "PASS")
        except Exception as e:
            log(f"  • Фильтр «{label}»: {e}")
    else:
        log(f"  • «{label}»: календарь не распознан")
    esc()
    click_text_deepest("Сбросить фильтры", "contains")
    time.sleep(2)
    return selected


def open_existing_code(back_url):
    codes = CODE_RE.findall(innertext())
    if not codes:
        log("  • Строки таблицы не найдены — пропуск открытия записи", "WARN")
        return True
    code = codes[0]
    open_code(code)
    time.sleep(1.5)
    ok = not at_url(back_url)
    log(f"  {'✓' if ok else '⚠'} Открыта запись {code}: {driver.current_url}", "PASS" if ok else "WARN")
    if ok:
        log(f"    Кнопки карточки: {visible_actions()[:15]}")
        for tab in ["Обсуждение", "История", "Комментарии", "Файлы"]:
            if click_text_deepest(tab, "exact"):
                log(f"    ✓ Вкладка «{tab}»", "PASS")
                time.sleep(0.8)
    driver.get(back_url)
    time.sleep(3)
    return ok


def test_create_cancel(create_btn, heading):
    if not click_button([create_btn], wait=6):
        log(f"  ⚠ Кнопка «{create_btn}» не найдена", "WARN")
        return False
    time.sleep(2.5)
    ok = heading.lower() in innertext().lower()
    log(f"  {'✓' if ok else '⚠'} Открыта форма «{heading}» ({driver.current_url})", "PASS" if ok else "WARN")
    url0 = driver.current_url
    back = False
    if click_button(["Отмена"], wait=4):
        time.sleep(1.5)
        m = find_modal()
        if m is not None:
            b = modal_button(m, ["Да", "Выйти", "Подтвердить", "ОК", "Отменить"])
            if b:
                click_el(b)
                time.sleep(1.5)
        back = driver.current_url != url0
        log(f"  {'✓' if back else '⚠'} «Отмена» — возврат: {driver.current_url}", "PASS" if back else "WARN")
    return ok and back


def quality_list_ready(url):
    def ready():
        if not at_url(url) or is_login_page():
            return False
        return driver.execute_script(r"""
            const vis=e=>!!(e.offsetWidth||e.offsetHeight||e.getClientRects().length);
            if(Array.from(document.querySelectorAll('[aria-busy="true"],[role="progressbar"]')).some(vis))return false;
            const text=document.body.innerText||'';
            if(/Загрузка\s*[…\.]/i.test(text))return false;
            return /Всего:\s*\d+|Нет данных|Ничего не найдено|Список пуст/i.test(text)||
                Array.from(document.querySelectorAll('table tbody tr')).some(e=>vis(e)&&(e.innerText||'').trim());
        """)
    return bool(wait_for_state(ready))


def stage_list(menu_item,url):
    if not nav_menu(menu_item,url):
        log(f'  ⚠ Раздел {menu_item} не открылся','WARN')
        return False
    STATE.setdefault('max_before',{})[url]=max(list_codes() or [0])
    return True


# ---------- карточка ----------
def stage_card(module):
    goto_card()
    code, st = record_card(module)
    log(f"  Номер: {code}; статус: {st}; URL: {STATE['url']}")
    log(f"  Кнопки: {visible_actions()[:20]}")
    info = innertext()[:600].replace("\n", " | ")
    log(f"  Текст карточки: {info}")
    for tab in ["Обсуждение", "История", "Комментарии", "Файлы", "Документы"]:
        if click_text_deepest(tab, "exact"):
            log(f"    ✓ Вкладка «{tab}»", "PASS")
            time.sleep(0.8)
    has_chat = any(t.is_displayed() for t in driver.find_elements(
        By.XPATH, "//textarea[contains(@placeholder,'ообщени')]"))
    discussion_ok = True
    if has_chat:
        discussion_ok = stage_discussion()
        if discussion_ok:
            log("  ✓ Обсуждение: сообщение и файл отправлены", "PASS")
        else:
            log("  ⚠ Обсуждение: отправка не подтвердилась", "WARN")
    else:
        log("  • Поля обсуждения в карточке нет — пропуск")
    if code == "?":
        log("  ⚠ Номер записи на карточке не найден", "WARN")
    return code != "?" and bool(st) and discussion_ok


def stage_in_list(module,url):
    rec=STATE['records'].get(module)
    if not rec or rec[0]=='?':
        log('  ⚠ Номер своей записи неизвестен','WARN');return False
    code=rec[0]
    driver.get(url)
    if not quality_list_ready(url):return False
    inp=quality_search_input()
    if inp is None:
        log('  ⚠ Поиск записи: поле поиска отсутствует','WARN');return False
    type_text(inp,code.lstrip('#'))
    inp.send_keys(Keys.ENTER)
    found=bool(wait_for_state(lambda:int(code.lstrip('#')) in list_codes()))
    log(f"  {'✓' if found else '⚠'} Запись {code} {'найдена' if found else 'не найдена'} по номеру в реестре",'PASS' if found else 'WARN')
    type_text(inp,'')
    inp.send_keys(Keys.ENTER)
    quality_list_ready(url)
    return found


# ---------- продвижение по статусам ----------
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


def prefill_inline():
    """Незаполненные селекты прямо в карточке (например, «Исполнитель» рядом с «Назначить»)."""
    for ctrl in visible_selects():
        try:
            if not ctrl_enabled(ctrl) or not ctrl_unset(ctrl, ""):
                continue
            lab = label_of(ctrl)
            if re.search(r"исполнител|ответствен|назнач|инженер|специалист", lab.lower()):
                kw, srch = person_pref(lab)
                got = pick_in(ctrl, kw or MAIN_FIRST, srch or PERSON_SEARCH_MAIN, lab)
                log(f"    {'✓' if got else '⚠'} {lab}: {got or 'не выбрано'}", "PASS" if got else "WARN")
        except Exception:
            continue


def quality_execution_upload_target(modal,labels=None):
    return driver.execute_script(r"""
        const root=arguments[0];
        const visible=e=>!!(e&&(e.offsetWidth||e.offsetHeight||e.getClientRects().length));
        for(const title of arguments[1]){
            const caption=Array.from(root.querySelectorAll('*')).find(e=>visible(e)&&
                (e.textContent||'').trim().replace(/\s+/g,' ')===title &&
                !Array.from(e.children).some(c=>(c.textContent||'').trim()===title));
            if(!caption)continue;
            for(let parent=caption.parentElement;parent&&root.contains(parent);parent=parent.parentElement){
                const inputs=parent.querySelectorAll('input[type=file]');
                if(inputs.length===1)return {input:inputs[0],scope:parent,label:title};
                if(inputs.length>1)break;
            }
        }
        return null;
    """,modal,labels or ['Документы исполнения','Фотографии'])


def quality_action_attachment(modal):
    inputs=modal.find_elements(By.XPATH,".//input[@type='file']")
    if not inputs:return True
    target=quality_execution_upload_target(modal)
    if target:
        inp=target['input'];scope=target['scope'];label=target['label']
    elif len(inputs)==1:
        inp=inputs[0];scope=modal;label='Вложение действия'
    else:
        log('    ⚠ Несколько полей вложений; поле исполнения не распознано, файл не отправлен','WARN');return False
    accepts=(inp.get_attribute('accept') or '').lower()
    image_only=label=='Фотографии' or ('image/' in accepts and not any(x in accepts for x in ('pdf','application/','*/*')))
    path=create_test_png('action_photo') if image_only else create_test_pdf('action_execution')
    log(f"    Вложение действия: {label}; {'PNG' if image_only else 'PDF'}")
    if not send_file(path,scope=scope,input_element=inp):return False
    for label,stem in [('Штрафной талон','action_ticket'),('Дефектный акт','action_defect_act')]:
        additional=quality_execution_upload_target(modal,[label])
        if additional:
            log(f'    Вложение действия: {label}; PDF')
            if not send_file(create_test_pdf(stem),scope=additional['scope'],input_element=additional['input']):return False
    return True


def fill_action_modal(modal, label):
    """Окно действия: люди -> Sh Margulan Ju (иначе Талгат), даты, комментарий, файл; затем подтверждение."""
    fill_all_unset(modal, "(окно действия)")
    try:
        for ta in modal.find_elements(By.XPATH, ".//textarea"):
            if ta.is_displayed() and ta.is_enabled() and not (ta.get_attribute("value") or "").strip():
                type_text(ta, f"Автотест: {label} ({STAMP})")
        for inp in modal.find_elements(By.XPATH, ".//input[not(@type) or @type='text' or @type='number']"):
            ph = (inp.get_attribute("placeholder") or "").lower()
            if inp.is_displayed() and inp.is_enabled() and not (inp.get_attribute("value") or "") \
                    and "поиск" not in ph and "дд" not in ph and "дат" not in ph:
                type_text(inp, "10" if (inp.get_attribute("type") == "number" or "сумм" in ph) else f"Автотест {STAMP}")
    except Exception:
        pass
    fill_dates_in(None, start_days=3, length_days=0)
    if not quality_action_attachment(modal):
        log(f'    ⚠ Окно {label}: вложение не подтверждено, действие не отправлено','WARN');return False
    modal = find_modal() or modal
    btn = modal_button(modal, [label] + MODAL_CONFIRM)
    if btn is None:
        log(f"    ⚠ В окне «{label}» нет активной кнопки подтверждения. Текст: "
            f"{(modal.get_attribute('innerText') or '').replace(chr(10), ' | ')[:250]}", "WARN")
        shot("action_modal_nobutton")
        close_modal_soft(modal)
        return False
    btxt = (btn.text or "").strip()
    click_el(btn)
    wait_for_state(lambda:find_modal() is None or bool(field_errors()),timeout=WAIT)
    still = find_modal()
    if still is not None and btxt and modal_button(still, [btxt]) is not None:
        log(f"    ⚠ Окно не закрылось: {field_errors()} {read_toasts()}", "WARN")
        shot("action_modal_open")
        close_modal_soft(still)
        return False
    log(f"    Окно «{label}»: нажато «{btxt}»")
    return True


EXCLUDE_ACT = ["не исполн", "отклон", "доработ", "удал", "сменить исполн", "отмен", "редакт", "выйти", "вернуть",
               "поделит", "скачать", "печать", "экспорт", "копир"]

JS_CLICKABLES = r"""
function vis(e){ return !!(e.offsetWidth || e.offsetHeight || e.getClientRects().length); }
var out = [];
document.querySelectorAll('button, a, [role=button], [role=menuitem], [role=option], li').forEach(function(e){
    if (!vis(e)) return;
    if (e.closest('aside, nav, [class*="sidebar"], [class*="Sidebar"]')) return;
    var t = (e.innerText || '').trim().replace(/\s+/g, ' ');
    if (!t || t.length > 45) return;
    if (e.disabled || e.getAttribute('aria-disabled') === 'true') return;
    out.push([e, t]);
});
return out;
"""


def find_action(tried, st0):
    """Первая доступная кнопка из ACTIONS (совпадение по вхождению, без «Отклонить/Удалить/...»)."""
    try:
        items = driver.execute_script(JS_CLICKABLES) or []
    except Exception:
        items = []
    for a in ACTIONS:
        al = a.lower()
        for el, t in items:
            tl = t.lower()
            if al == tl and not any(x in tl for x in EXCLUDE_ACT) and (t, st0) not in tried:
                return t, el
    return None, None


JS_KEBABS = r"""
function vis(e){ return !!(e.offsetWidth || e.offsetHeight || e.getClientRects().length); }
return Array.prototype.filter.call(document.querySelectorAll('button, [role=button]'), function(b){
    if (!vis(b) || b.closest('aside, nav, table, [role=row]')) return false;
    var t = (b.innerText || '').trim(); var r = b.getBoundingClientRect();
    return (!t || /^[.⋯…•·⋮]+$/.test(t)) && r.top < 420 && r.left > window.innerWidth * 0.45;
});
"""


def try_kebab_action(tried, st0):
    """Меню «⋮» в шапке карточки: открыть и взять подходящий пункт (без удаления/отклонения)."""
    try:
        kebabs = driver.execute_script(JS_KEBABS) or []
    except Exception:
        kebabs = []
    for kb in kebabs[:3]:
        hard_click(kb)
        time.sleep(1)
        label, el = find_action(tried, st0)
        if el is not None:
            log(f"    В меню «⋮» найден пункт «{label}»")
            return label, el
        esc()
        time.sleep(0.4)
    return None, None


def try_row_menu_action(list_url, code, tried, st0):
    """Меню «⋯» строки нашей записи в списке (иногда «Назначить исполнителя» именно там)."""
    if not code or code == "?":
        return None, None
    driver.get(list_url)
    time.sleep(3)
    try:
        btn = driver.execute_script("""
            var t = arguments[0], all = document.querySelectorAll('*'), code = null;
            for (var i = 0; i < all.length; i++) { var e = all[i];
                if (!e.children.length && (e.offsetWidth || e.offsetHeight) && (e.textContent || '').trim() === t) { code = e; break; } }
            if (!code) return null;
            var row = code;
            for (var k = 0; k < 8 && row; k++) { row = row.parentElement; if (!row) break;
                if (row.tagName === 'TR' || row.getAttribute('role') === 'row') break; }
            if (!row) return null;
            var bs = Array.prototype.filter.call(row.querySelectorAll('button, [role=button]'), function(b){
                var x = (b.innerText || '').trim(); return (b.offsetWidth || b.offsetHeight) && (!x || /^[.⋯…•·⋮]+$/.test(x)); });
            return bs.length ? bs[bs.length - 1] : null;""", code)
    except Exception:
        btn = None
    if btn is None:
        return None, None
    hard_click(btn)
    time.sleep(1)
    label, el = find_action(tried, st0)
    if el is None:
        log(f"    Меню «⋯» строки {code}: {visible_actions()[-10:]}")
        esc()
    return label, el


def advance_loop(who, max_steps=12):
    n = 0
    tried = set()
    for _ in range(max_steps):
        if not quality_owned_card():
            return n
        driver.refresh()
        wait_for_state(get_status)
        st0 = get_status()
        if status_terminal(st0):
            log(f"  [{who}] статус «{st0}» — конечный")
            break
        if (QUALITY_CASE.get('want_rework') and not QUALITY_CASE.get('reworked') and
                st0=='Проверка исполнения' and find_buttons(['Не исполнено'])):
            if not click_action(['Не исполнено']):
                raise RuntimeError('Не удалось нажать доступное действие Не исполнено')
            if not wait_for_state(lambda:quality_changed_status(st0) and not status_terminal(get_status())):
                raise RuntimeError('Возврат Не исполнено не подтверждён сменой статуса')
            QUALITY_CASE['reworked']=True
            n+=1
            continue
        prefill_inline()
        label, btn = find_action(tried, st0)
        where = "карточка"
        if btn is None:
            label, btn = try_kebab_action(tried, st0)
            where = "меню «⋮»"
        if btn is None:
            code = next((r[0] for r in STATE["records"].values() if r[1] == STATE["url"]), None)
            label, btn = try_row_menu_action(STATE.get("list_url"), code, tried, st0)
            where = "меню строки в списке"
        if btn is None:
            goto_card()
            log(f"  [{who}] доступных действий нет. Кнопки на странице: {visible_actions()[:25]}")
            shot(f"no_actions_{who}")
            break
        if label in TO_SIGN and (not os.path.isfile(SECOND_P12_PATH) or not SECOND_NCA_PASSWORD):
            log('  ⚠ Для подписи требуется настроенный сертификат; действие не нажато','WARN')
            break
        tried.add((label, st0))
        log(f"  [{who}] действие «{label}» ({where})")
        scroll_to(btn)
        click_el(btn)
        if label not in TO_SIGN:
            wait_for_state(lambda:find_modal() or quality_changed_status(st0),timeout=WAIT)
        m = find_modal()
        if m is not None:
            if not fill_action_modal(m, label):
                break
        if label in TO_SIGN and ncalayer_present(15):
            sign_with_ncalayer(SECOND_NCA_PASSWORD, SECOND_P12_PATH)
        wait_for_state(lambda:quality_changed_status(st0),timeout=WAIT)
        toasts = read_toasts()
        goto_card()
        wait_for_state(get_status)
        st1 = get_status()
        changed=bool(st1 and st1!=st0)
        log(f"  [{who}] «{label}»: статус {st0} → {st1 or 'не распознан'} {toasts if toasts else ''}",
            "PASS" if changed else "WARN")
        if not changed:
            shot('action_status_not_changed')
            break
        n += 1
    return n


def stage_advance():
    global ROLE_RESTORE_FAILED
    if not quality_owned_card():return False
    total=0
    status=get_status()
    try:
        for cycle in range(4):
            before=total
            for account,password,who in (
                (login_val,pass_val,'Sh Margulan Ju'),
                (REVIEWER_LOGIN,REVIEWER_PASS,'Бейсембаев Куаныш'),
                (SECOND_LOGIN,SECOND_PASS,'Алдажаров Диас'),
            ):
                if status_terminal(status):break
                if not switch_user(account,password) or not quality_owned_card():return False
                total+=advance_loop(who)
                status=get_status()
            if status_terminal(status) or total==before:break
    finally:
        quality_restore_creator('после продвижения по ролям')
    status=get_status() or status
    for rec in STATE['records'].values():
        if rec[1]==STATE['url']:rec[2]=status
    ok=status_terminal(status)
    log(f'  Итог: действий {total}, статус {status}', 'PASS' if ok else 'WARN')
    return ok


# ==========================================
# 1. РЕГИСТРАЦИЯ ПРЕДПИСАНИЙ
# ==========================================
def _base_open_create(list_url,create_btn,heading):
    if not at_url(list_url):
        driver.get(list_url)
    if not quality_list_ready(list_url):
        return False
    if not click_button([create_btn],wait=6):
        driver.get(list_url.rstrip('/')+'/create')
    ok=bool(wait_for_state(lambda:heading.lower() in innertext().lower()))
    block_native_file_dialog()
    return ok


def open_create(list_url,create_btn,heading):
    if not at_url(list_url):driver.get(list_url)
    if not quality_list_ready(list_url):return False
    STATE['case_codes_before']=list_codes()
    return _base_open_create(list_url,create_btn,heading)


def finish_create(module,list_url):
    return quality_finish_create(module,list_url)


def stage_issue_create():
    if not open_create(ISSUE_URL, "Создать предписание", "Создание предписания"):
        return False
    pick_city_project("Город", "Проект")
    missing = fill_page_selects([
        ("Очередь (тип объекта)", {}), ("Блок (подъезд)", {}), ("Этаж", {}), ("Тип помещения", {}),
        person_select("Начальник участка", "main"), person_select("Руководитель проекта", "talgat"),
        ("Контрагент", {}), ("Шаблон", {}), person_select("Наблюдатели (необязательно)", "talgat"),
    ])
    choose_chip(["Критичное", "Приостановка", "Простое"])
    fill_ph("Ввести текст", f"Автотест: описание замечания {STAMP}. Нарушение технологии работ, "
                            f"требуется устранение.", tag="textarea", exact=True)
    ensure_section("Детализация работ", "Ввести местоположение")
    fill_ph("Ввести местоположение", "Ось А-Б / 1-2, отм. +3.600")
    missing += fill_page_selects([("Вид работ", {}), ("Конструктив", {})])
    fill_ph("Ввести сумму", "50000")
    fill_dates_any(7)
    ensure_section("Документы и файлы")
    attach_files("issue")
    ensure_section("Дополнительно", "Ввести текст рекомендации")
    fill_ph("Ввести текст рекомендации", f"Автотест: усилить входной контроль, провести инструктаж ({STAMP})",
            tag="textarea")
    for c in ["Несоблюдение рабочего проекта", "Дефектный акт", "Повторное замечание", "Операционный контроль"]:
        tick(c)
    if missing:
        log(f"  ⚠ Не заполнены: {missing}", "WARN")
    return finish_create("Предписание", ISSUE_URL)


# ==========================================
# 2. БиОТ
# ==========================================
def stage_biot_create():
    if not open_create(BIOT_URL, "Создать БиОТ", "Создание БиОТ"):
        return False
    pick_city_project("Город", "Проект")
    missing = fill_page_selects([
        ("Очередь", {}), ("Блок (секция)", {}), ("Этаж", {}), ("Контрагент", {}), ("Вид работ", {}),
        person_select("Начальник участка", "main"), person_select("Руководитель проекта", "talgat"),
        person_select("Наблюдатель / Получатель", "talgat"),
    ])
    choose_chip(["Критичное", "Приостановка", "Простое"])
    fill_ph("Опишите меры", f"Автотест: провести инструктаж по ОТ, установить ограждения ({STAMP})",
            tag="textarea")
    ensure_section("Детализация работ", "Вид нарушения")
    missing += fill_page_selects([("Вид нарушения", {})])
    time.sleep(1)
    try:
        ref = next((e for e in driver.find_elements(By.XPATH, "//textarea[contains(@placeholder,'Заполняется автоматически')]")
                    if e.is_displayed()), None)
        val = (ref.get_attribute("value") or "").strip() if ref is not None else ""
        log(f"    {'✓' if val else '•'} Нормативные ссылки (автоматически): {val[:80] or 'пусто'}",
            "PASS" if val else "INFO")
    except Exception:
        pass
    fill_ph("Ввести сумму", "30000")
    fill_dates_any(7)
    tick("Штрафной талон")
    fill_ph("Краткое описание", f"Автотест: работа на высоте без страховки ({STAMP})", tag="textarea")
    ensure_section("Документы и файлы")
    attach_files("biot")
    if missing:
        log(f"  ⚠ Не заполнены: {missing}", "WARN")
    return finish_create("БиОТ", BIOT_URL)


# ==========================================
# 3. ИНСПЕКЦИИ СКРЫТЫХ РАБОТ
# ==========================================
def stage_insp_create():
    if not open_create(INSP_URL, "Создать инспекцию", "Создание инспекции"):
        return False
    fill_select(driver, "Проект", keywords=PROJECT_KEYS, search=PROJECT_SEARCH)
    time.sleep(1)
    missing = fill_page_selects([("Блок (секция)", {}), ("Контрагент", {}), ("Вид работ", {})])
    fill_ph("Например: ПД", f"ПД-{STAMP}")
    fill_dates_any(1)
    time.sleep(0.8)
    set_time_inputs("10:00")
    fill_ph("Например: А-Б", "А-Б / 1-2")
    fill_ph("Например: +3", "+3.600")
    ensure_section("Ответственные лица", "Инженер по качеству")
    missing += fill_page_selects([
        person_select("Инженер по качеству", "main"),
        person_select("Принимающий специалист ДТН", "talgat"),
        person_select("Наблюдатели", "talgat"),
    ])
    ensure_section("Документы и файлы")
    attach_files("inspection")
    if missing:
        log(f"  ⚠ Не заполнены: {missing}", "WARN")
    return finish_create("Инспекция", INSP_URL)


# ==========================================
# ОТЧЁТЫ
# ==========================================


# ==========================================
# MAIN
# ==========================================
# Business scenarios. Every mutating card action requires proof of ownership.
QUALITY_FATAL = False
QUALITY_CASE = {}
QUALITY_OWNED = {}


def quality_path(url):
    return urlparse(url or '').path.rstrip('/')


def quality_owned_card():
    url=STATE.get('url')
    owned=QUALITY_OWNED.get(quality_path(url))
    if not owned:
        raise RuntimeError('Изменение запрещено: карточка не зарегистрирована как созданная этим запуском')
    if not goto_card() or quality_path(driver.current_url)!=quality_path(url):
        return False
    if owned['marker'] not in innertext():
        # Return to the default details tab before checking the unique case marker.
        driver.get(url)
        if not wait_for_state(lambda:owned['marker'] in innertext()):
            raise RuntimeError('Изменение запрещено: уникальная метка созданной записи не найдена')
    return True


def quality_fresh_form(config):
    driver.get(config['url'])
    return open_create(config['url'],config['create'],config['heading'])


def quality_cancel_form(config):
    if '/create' not in driver.current_url and '/edit' not in driver.current_url:
        return True
    if not click_button(['Отмена'],wait=3):
        return False
    modal=find_modal()
    if modal is not None:
        button=modal_button(modal,['Да','Выйти','Подтвердить','Отменить'])
        if button is not None:
            click_el(button)
    return bool(wait_for_state(lambda:at_url(config['url'])))


def quality_table_rows():
    return driver.execute_script(r"""
        const vis=e=>!!(e.offsetWidth||e.offsetHeight||e.getClientRects().length);
        const table=Array.from(document.querySelectorAll('table')).find(vis);
        if(!table)return [];
        const heads=Array.from(table.querySelectorAll('thead th,thead td')).map(e=>(e.innerText||'').trim());
        const fallback=Array.from(table.rows[0]?.cells||[]).map(e=>(e.innerText||'').trim());
        const names=heads.length?heads:fallback;
        return Array.from(table.querySelectorAll('tbody tr')).filter(vis).map(row=>{
            const values=Array.from(row.cells).map(e=>(e.innerText||'').trim());
            return Object.fromEntries(names.map((n,i)=>[n,values[i]||'']));
        }).filter(row=>Object.values(row).some(v=>/#\d+/.test(v)));
    """) or []


def quality_search_input():
    return next((e for e in driver.find_elements(By.XPATH,"//input[not(@type) or @type='text' or @type='search']")
                 if e.is_displayed() and e.is_enabled()),None)


def quality_filter_value_matches(name,expected,actual,available):
    def normalized(value):return ' '.join(value.split()).casefold()
    expected=normalized(expected);actual=normalized(actual)
    if actual==expected:return True
    if name!='Исполнитель':return False
    short=actual.split();full=expected.split()
    if len(short)!=2 or len(full)<3 or full[:2]!=short:return False
    # The UI omits a patronymic. Accept only an unambiguous surname/name pair.
    candidates={normalized(value) for value in available if normalized(value).split()[:2]==short}
    return candidates=={expected}


def quality_list_scenario(config):
    if not stage_list(config['menu'],config['url']):
        return False
    ok=True
    # Validate visible row values, not merely that the filter can be clicked.
    for name in ('Тип замечания','Исполнитель','Проект','Статус'):
        trigger=next((e for e in visible_selects() if (e.get_attribute('aria-label') or '').strip()==name),None)
        if trigger is None:
            if name=='Тип замечания' and config['module']=='Инспекция':
                continue
            log(f'  ⚠ Фильтр {name} не найден','WARN');ok=False;continue
        if not open_popup(trigger):
            ok=False;continue
        _,options=wait_options(trigger,5)
        values=list(dict.fromkeys(o['text'] for o in options if o['text'] and 'все' not in o['text'].lower()))
        close_popup(trigger)
        if not values:
            log(f'  ⚠ У фильтра {name} нет вариантов','WARN');ok=False;continue
        # All available values, with row comparison on every returned page.
        for value in values:
            trigger=next((e for e in visible_selects() if (e.get_attribute('aria-label') or '').strip()==name),None)
            if trigger is None or not open_popup(trigger):
                ok=False;break
            _,options=wait_options(trigger,5)
            target=next((o for o in options if o['text']==value),None)
            if target is None or not _click_option(target,trigger):
                ok=False;break
            close_popup(trigger)
            if not quality_list_ready(config['url']):
                ok=False;break
            seen=set()
            while True:
                rows=quality_table_rows()
                for row in rows:
                    actual=row.get(name,'').replace('\n',' ').strip()
                    if not quality_filter_value_matches(name,value,actual,values):
                        log(f'  ⚠ {name}: выбрано {value}, в строке {actual}','WARN');ok=False
                page=pager_text()
                if not page or page in seen or page[0]>=page[1]:break
                seen.add(page)
                if not click_button(['Следующая'],wait=2) or not wait_for_state(lambda:pager_text() and pager_text()!=page):
                    ok=False;break
            click_button(['Сбросить фильтры'],wait=2)
            quality_list_ready(config['url'])
    inp=quality_search_input()
    if inp is None:
        return False
    total_before_search=page_total()
    # This registry searches registration numbers; alphabetic text is ignored by the portal.
    type_text(inp,'99999999')
    inp.send_keys(Keys.ENTER)
    empty=wait_for_state(lambda:page_total()==0 and not quality_table_rows())
    type_text(inp,'')
    inp.send_keys(Keys.ENTER)
    restored=wait_for_state(lambda:page_total()==total_before_search and quality_list_ready(config['url']))
    outcomes=[('фильтры и строки',ok),('пустой поиск',bool(empty)),('восстановление списка',bool(restored))]
    for name,action in [('период',lambda:quality_date_scenario(config)),
                        ('число строк',test_rows_per_page),
                        ('сортировка и столбцы',lambda:quality_sort_columns_scenario(config)),
                        ('переходы страниц',test_pagination)]:
        result=bool(action())
        log(f"  {'✓' if result else '⚠'} Реестр: {name}",'PASS' if result else 'WARN')
        outcomes.append((name,result))
    failed=[name for name,result in outcomes if not result]
    if failed:log('  ⚠ Не пройдены части реестра: '+', '.join(failed),'WARN')
    return not failed


def quality_date_scenario(config):
    trigger=next((e for e in driver.find_elements(By.XPATH,"//button[@aria-label="+json.dumps(config['date'],ensure_ascii=False)+"]") if e.is_displayed()),None)
    if trigger is None:return False
    begin=dtm.date.today();end=begin+dtm.timedelta(days=7)
    try:
        if not click_el(trigger) or not calendar_goto(begin.year,begin.month):return False
        cell=cell_by_day(calendar_cells(),begin.day)
        if cell is None or not click_el(cell):return False
        if not calendar_goto(end.year,end.month):return False
        cell=cell_by_day(calendar_cells(),end.day)
        if cell is None or not click_el(cell):return False
        esc()
        if not quality_list_ready(config['url']):return False
        for row in quality_table_rows():
            value=parse_date(row.get(config['date'],''))
            if not value or not ((begin.year,begin.month,begin.day)<=value<=(end.year,end.month,end.day)):
                log(f'  ⚠ Дата строки не соответствует выбранному периоду: {row}','WARN');return False
        return True
    finally:
        esc();click_button(['Сбросить фильтры'],wait=2);quality_list_ready(config['url'])


def quality_sort_columns_scenario(config):
    def sort_button():
        return next((e for e in driver.find_elements(By.XPATH,"//button[@aria-label='Сортировка']") if e.is_displayed()),None)
    button=sort_button()
    if button is None or not click_el(button):return False
    options=wait_for_state(lambda:[e for e in driver.find_elements(By.XPATH,"//*[@role='menuitemradio']") if e.is_displayed()]) or []
    original=next(((e.text or '').split('\n')[0] for e in options if e.get_attribute('aria-checked')=='true'),None)
    target=next((e for e in options if re.search(r'Номер (инспекции|предписания|БиОТ)|Рег.*номер',e.text or '',re.I)),None)
    if target is None:
        esc();return False
    try:
        if not click_el(target) or not quality_list_ready(config['url']):return False
        codes=list_codes()
        if codes!=sorted(codes):
            log(f'  ⚠ Номера не отсортированы по возрастанию: {codes}','WARN');return False
    finally:
        if original and sort_button() is not None and click_el(sort_button()):
            options=wait_for_state(lambda:[e for e in driver.find_elements(By.XPATH,"//*[@role='menuitemradio']") if e.is_displayed()]) or []
            old=next((e for e in options if (e.text or '').split('\n')[0]==original),None)
            if old is not None:click_el(old)
            esc();quality_list_ready(config['url'])
    if not click_button(['Настройки таблицы'],wait=3):return False
    def project_box():
        return next((e for e in driver.find_elements(By.XPATH,
            "//*[@role='menu']//*[@role='menuitemcheckbox'][normalize-space(.)='Проект']")
            if e.is_displayed() and e.is_enabled()),None)
    box=wait_for_state(project_box)
    if box is None:
        log('  ⚠ В настройках таблицы не найден пункт Проект','WARN')
        esc();return False
    def header_visible():
        return bool(driver.execute_script("return Array.from(document.querySelectorAll('thead th,thead td')).some(e=>(e.innerText||'').trim()==='Проект');"))
    before=header_visible()
    try:
        if not click_el(box):return False
        changed=bool(wait_for_state(lambda:header_visible()!=before))
        return changed
    finally:
        # Resolve the checkbox anew because the settings menu can be re-rendered.
        current=project_box()
        if current is None:
            click_button(['Настройки таблицы'],wait=2)
            current=wait_for_state(project_box)
        if header_visible()!=before:
            if current is None or not click_el(current) or not wait_for_state(lambda:header_visible()==before):
                raise RuntimeError('Не удалось восстановить исходный набор столбцов')
        esc()


def quality_keyboard_input(field,value):
    # Real keyboard events update controlled React fields; never bypass input validation.
    field.click()
    field.send_keys(Keys.CONTROL,'a')
    field.send_keys(Keys.BACKSPACE)
    if value:field.send_keys(value)


def quality_form_contract(config):
    if not quality_fresh_form(config):return False
    ok=True
    try:
        project=control_by_label(driver,'Проект')
        child=control_by_label(driver,config['block'])
        if child is None or ctrl_enabled(child):
            log('  ⚠ Блок должен быть недоступен до выбора проекта','WARN');ok=False
        if config['module']!='Инспекция' and (project is None or ctrl_enabled(project)):
            log('  ⚠ Проект должен быть недоступен до выбора города','WARN');ok=False
        selected=pick_city_project() if config['module']!='Инспекция' else fill_select(driver,'Проект',keywords=PROJECT_KEYS,search=PROJECT_SEARCH)
        child=wait_ctrl_enabled(driver,config['block'],6)
        if not selected or child is None or not ctrl_enabled(child):
            log(f'  ⚠ Зависимые поля: проект выбран={selected}; блок найден={child is not None}; доступен={child is not None and ctrl_enabled(child)}','WARN');ok=False
        # Actual HTML maxlength limits; enter through Selenium rather than bypassing the UI.
        for section in ('Детализация работ','Дополнительно','Ответственные лица'):
            buttons=driver.find_elements(By.XPATH,"//button[contains(normalize-space(.),"+json.dumps(section,ensure_ascii=False)+")]")
            button=next((e for e in buttons if e.is_displayed()),None)
            if button is not None and button.get_attribute('aria-expanded')=='false':
                click_el(button)
        fields=[e for e in driver.find_elements(By.XPATH,"//textarea[@maxlength]") if e.is_displayed() and e.is_enabled()]
        for field in fields:
            maximum=int(field.get_attribute('maxlength'))
            quality_keyboard_input(field,'Я'*(maximum+1))
            length=len(field.get_attribute('value') or '')
            if length!=maximum:
                log(f'  ⚠ Ограничение длины {maximum}: получено {length}','WARN');ok=False
            quality_keyboard_input(field,'')
        amounts=[e for e in driver.find_elements(By.XPATH,"//input[contains(@placeholder,'Ввести сумму')]") if e.is_displayed()]
        for field in amounts:
            quality_keyboard_input(field,'abc-1')
            value=(field.get_attribute('value') or '').strip()
            if re.search(r'[A-Za-zА-Яа-я-]',value):
                log('  ⚠ Поле штрафа принимает буквы/отрицательное значение','WARN');ok=False
            quality_keyboard_input(field,'0')
            zero=(field.get_attribute('value') or '').strip()
            if zero not in ('0','0,00','0.00'):
                log(f'  ⚠ Нулевая сумма: получено {zero!r}','WARN');ok=False
        if config['module']=='Инспекция':
            times=driver.find_elements(By.XPATH,"//input[@type='time']")
            if not times or any(e.is_enabled() for e in times):ok=False
            if not fill_dates_any(1) or not set_time_inputs('10:00'):ok=False
        return ok
    finally:
        if not quality_cancel_form(config):
            raise RuntimeError('После проверки формы не удалось выйти без публикации')


def quality_rejected_publication():
    global QUALITY_FATAL
    initial=driver.current_url
    buttons=driver.find_elements(By.XPATH,"//button[normalize-space(.)='Опубликовать']")
    if not buttons:return False
    if not buttons[0].is_enabled():return True
    if not click_el(buttons[0]):return False
    deadline=time.monotonic()+WAIT
    while time.monotonic()<deadline:
        if quality_path(driver.current_url)!=quality_path(initial):
            QUALITY_FATAL=True
            raise RuntimeError('Отрицательный сценарий неожиданно создал/опубликовал запись; модуль остановлен')
        errors=field_errors()
        if errors:
            log(f'  ✓ Публикация отклонена: {errors}','PASS')
            return True
        time.sleep(.2)
    log('  ⚠ Отказ публикации не подтверждён сообщением валидации','WARN')
    return False


def quality_negative_form(config):
    if not quality_fresh_form(config):return False
    try:
        blank=quality_rejected_publication()
    finally:
        if not QUALITY_FATAL:quality_cancel_form(config)
    if QUALITY_FATAL or not quality_fresh_form(config):return False
    try:
        marker='NEG-no-project-'+os.environ.get('QUALITY_RUN_ID',STAMP)
        fields=[e for e in driver.find_elements(By.XPATH,"//textarea|//input[@type='text' or not(@type)]")
                if e.is_displayed() and e.is_enabled() and 'дат' not in (e.get_attribute('placeholder') or '').lower()]
        if fields:type_text(fields[0],marker)
        project=control_by_label(driver,'Проект')
        if project is None or not ctrl_unset(project,'Проект'):return False
        return quality_rejected_publication() and blank
    finally:
        if not QUALITY_FATAL:quality_cancel_form(config)


def quality_files_form(config):
    if not quality_fresh_form(config):return False
    try:
        ensure_section('Документы и файлы')
        paths=[create_test_pdf('quality_valid'),create_test_png('quality_valid')]
        for path in paths:
            if not send_file(path) or not wait_for_state(lambda:os.path.basename(path) in innertext()):return False
        # The fresh form owns these attachments; remove only its generated test file.
        name=os.path.basename(paths[1])
        remove=driver.execute_script(r"""
            const name=arguments[0],vis=e=>!!(e.offsetWidth||e.offsetHeight||e.getClientRects().length);
            const leaf=Array.from(document.querySelectorAll('*')).find(e=>vis(e)&&!e.children.length&&(e.textContent||'').trim()===name);
            for(let p=leaf,k=0;p&&k<5;k++,p=p.parentElement){
                const candidates=Array.from(p.querySelectorAll('button')).filter(b=>vis(b)&&
                    /удалить|убрать|remove/i.test((b.getAttribute('aria-label')||'')+' '+(b.title||'')+' '+(b.innerText||'')));
                if(candidates.length===1)return candidates[0];
            }return null;
        """,name)
        if remove is None:
            log('  ⚠ Удаление вложения формы не распознано; сценарий не засчитан','WARN');return False
        if not click_el(remove) or not wait_for_state(lambda:name not in innertext()):return False
        if not send_file(paths[1]) or not wait_for_state(lambda:name in innertext()):return False
        inputs=driver.find_elements(By.XPATH,"//input[@type='file']")
        accepted=next((i.get_attribute('accept') for i in inputs if i.get_attribute('accept')),None)
        if accepted:
            bad=os.path.join(WORK_DIR,'quality_invalid.exe')
            Path(bad).write_bytes(b'RGB QA harmless upload validation fixture')
            send_file(bad)
            if not wait_for_state(lambda:bool(field_errors() or read_toasts())) or 'quality_invalid.exe' in innertext():return False
        else:
            log('  В интерфейсе не задан список запрещённых расширений; запрет произвольного файла не предполагается')
        return True
    finally:
        quality_cancel_form(config)


def quality_begin_case(config,kind='Простое',draft=False):
    global STAMP
    marker='QA-'+os.environ.get('QUALITY_RUN_ID',STAMP)[:12]+'-'+config['key']+'-'+('draft' if draft else 'publish')+'-'+kind
    QUALITY_CASE.clear()
    QUALITY_CASE.update(config=config,kind=kind,marker=marker,draft=draft,expected=[],uploads=[],selected=[],base_stamp=STAMP)
    STAMP=marker
    STATE['url']=None
    STATE['list_url']=config['url']
    return marker


def quality_create_case(config,kind='Простое',draft=False):
    global STAMP
    quality_begin_case(config,kind,draft)
    try:
        ok=config['create_fn']()
        return bool(ok and quality_owned_card())
    finally:
        STAMP=QUALITY_CASE['base_stamp']


def quality_next_registry_page(url):
    """A changed pager alone does not prove that the next page's rows have arrived."""
    previous_page=pager_text()
    previous_codes=tuple(list_codes())
    if not previous_page or previous_page[0]>=previous_page[1]:return False
    if not click_button(['Следующая'],wait=2):
        log('  ⚠ Поиск записи: кнопка следующей страницы недоступна','WARN');return False
    target=(previous_page[0]+1,previous_page[1])
    def arrived():
        if pager_text()!=target:return False
        codes=tuple(list_codes())
        return bool(codes and codes!=previous_codes)
    if not wait_for_state(arrived):
        log(f'  ⚠ Поиск записи: строки страницы {target[0]} не обновились','WARN');return False
    return quality_list_ready(url)


def quality_registry_page(url,target):
    """Navigate from the actual restored page; the portal retains pagination on return."""
    seen=set()
    while True:
        page=pager_text()
        if not page or not 1<=target<=page[1]:
            log(f'  ⚠ Реестр: некорректная страница {page}, запрошена {target}','WARN');return False
        if page[0]==target:return quality_list_ready(url)
        if page in seen:
            log(f'  ⚠ Реестр: переход зациклился на {page}','WARN');return False
        seen.add(page)
        if target==page[1]:label='Последняя страница';expected=target
        elif target==1:label='Первая страница';expected=1
        elif target>page[0]:label='Следующая';expected=page[0]+1
        else:label='Предыдущая';expected=page[0]-1
        previous_codes=tuple(list_codes())
        if not click_button([label],wait=2):
            log(f'  ⚠ Реестр: кнопка {label} недоступна; страница {page}','WARN');return False
        def arrived():
            current=pager_text()
            codes=tuple(list_codes())
            return bool(current and current[0]==expected and codes and codes!=previous_codes)
        if not wait_for_state(arrived) or not quality_list_ready(url):
            log(f'  ⚠ Реестр: не загрузились строки страницы {expected}','WARN');return False


def quality_register_created(config,initial_codes):
    marker=QUALITY_CASE['marker']
    if '/create' not in driver.current_url and not at_url(config['url']):
        if wait_for_state(lambda:marker in innertext(),timeout=5):return driver.current_url
    driver.get(config['url'])
    if not quality_list_ready(config['url']):return None
    codes=list_codes()
    page=pager_text()
    backwards=bool(codes and codes==sorted(codes))
    if page and not quality_registry_page(config['url'],page[1] if backwards else 1):return None
    visited=set()
    while True:
        page=pager_text()
        key=tuple(page) if page else (1,1)
        if key in visited:break
        visited.add(key)
        candidates=sorted(set(list_codes())-set(initial_codes),reverse=True)
        log(f'  Поиск своей записи: страница {key[0]}/{key[1]}, кандидаты {candidates}')
        for code in candidates:
            if open_code('#'+str(code)):
                if wait_for_state(lambda:marker in innertext(),timeout=3):
                    log(f'  ✓ Запись #{code} найдена по метке {marker}','PASS')
                    return driver.current_url
            driver.get(config['url'])
            if not quality_list_ready(config['url']):return None
            if not quality_registry_page(config['url'],key[0]):return None
        target=key[0]+(-1 if backwards else 1)
        if not 1<=target<=key[1]:break
        if not quality_registry_page(config['url'],target):return None
    return None


def quality_finish_create(module,list_url):
    config=QUALITY_CASE['config']
    fill_all_unset(None,'(доп. поле)')
    if module in ('Предписание','БиОТ'):
        for label in ('Начальник участка','Руководитель проекта'):
            if not fill_select(driver,label):
                log(f'  ⚠ Сохранение остановлено: {label} должен быть Алдажаров Диас','WARN');return False
    if not QUALITY_CASE.get('uploads_ok'):
        log('  ⚠ Не подтверждены оба вложения PDF и PNG','WARN');return False
    before=set(STATE.get('case_codes_before',[]))
    if QUALITY_CASE.get('draft'):
        if not click_button(['Сохранить'],wait=4):return False
        saved=wait_for_state(lambda:'/create' not in driver.current_url or bool(read_toasts()) or bool(field_errors()))
        errors=field_errors()
        if errors:
            log(f'  ⚠ Черновик не сохранён, ошибки формы: {errors}','WARN');return False
        log(f'  Сохранение черновика: URL={driver.current_url}; сообщения={read_toasts()}')
        url=quality_register_created(config,before)
        if not url:
            log('  ⚠ Сохранённый черновик не найден по уникальной метке','WARN');return False
        STATE['url']=url
        QUALITY_OWNED[quality_path(url)]={'marker':QUALITY_CASE['marker'],'module':module}
        if not quality_owned_card() or get_status()!='Черновик':return False
        driver.refresh()
        if not wait_for_state(lambda:get_status()=='Черновик' and QUALITY_CASE['marker'] in innertext()):return False
        # Continue only through an edit/publish control actually exposed for this owned draft.
        if click_button(['Редактировать','Изменить'],wait=2):
            if not wait_for_state(lambda:bool(find_buttons(['Сохранить','Опубликовать']))):return False
        if not find_buttons(['Опубликовать']):
            log('  ⚠ В собственном черновике нет доступного продолжения публикации','WARN');return False
    if not click_button(['Опубликовать'],wait=4):return False
    initial_url=driver.current_url
    modal=wait_for_state(lambda:find_modal() or driver.current_url!=initial_url or get_status()!='Черновик' and '/create' not in driver.current_url,timeout=WAIT)
    if modal and not isinstance(modal,bool):
        button=modal_button(modal,['Опубликовать','Подтвердить','Да','ОК'])
        if button is not None:click_el(button)
        wait_for_state(lambda:driver.current_url!=initial_url or get_status()!='Черновик' and '/create' not in driver.current_url)
    url=quality_register_created(config,before)
    if not url:
        log(f'  ⚠ Публикация не подтверждена: {field_errors()} {read_toasts()}','WARN');return False
    STATE['url']=url
    QUALITY_OWNED[quality_path(url)]={'marker':QUALITY_CASE['marker'],'module':module}
    if not quality_owned_card():return False
    code,status=record_card(module)
    return code!='?' and bool(status) and status!='Черновик'


def quality_download_buttons():
    # Icon-only download buttons expose their name through aria-label.
    return [e for e in driver.find_elements(By.XPATH,
        "//button[@aria-label='Скачать' or @title='Скачать' or normalize-space(.)='Скачать'] | //a[@download or @aria-label='Скачать']")
        if e.is_displayed() and e.is_enabled()]


def quality_card_scenario(config):
    if not quality_owned_card():return False
    marker=QUALITY_CASE['marker']
    code,status=record_card(config['module'])
    ok=code!='?' and bool(status) and marker in innertext()
    # Data used in creation must remain visible after a fresh reload, not merely before submit.
    for tab in ('Детали предписания','Детали БиОТ','Детали инспекции'):
        click_text_deepest(tab,'exact')
    for item in QUALITY_CASE.get('expected',[]):
        expected=item['value']
        actual=innertext()
        if 'сумм' in item['placeholder'].lower():actual=re.sub(r'\s+','',actual)
        if expected not in actual:
            log(f'  ⚠ Сохранённое поле отсутствует в карточке: {item["placeholder"]}: {expected[:80]}','WARN');ok=False
    if config['module']!='Инспекция' and QUALITY_CASE['kind'] not in innertext():
        log('  ⚠ Сохранённый тип замечания отличается от выбранного','WARN');ok=False
    if not click_text_deepest('Ответственные','exact'):
        ok=False
    if not click_text_deepest('История','exact') or not wait_for_state(lambda:bool(innertext().strip())):ok=False
    docs=next((e for e in driver.find_elements(By.XPATH,"//*[@role='tab']") if e.is_displayed() and (e.text or '').startswith('Документы')),None)
    if docs is None or not click_el(docs):return False
    for name in QUALITY_CASE.get('uploads',[]):
        if not wait_for_state(lambda:name in innertext()):
            log(f'  ⚠ В документах не найдено вложение {name}','WARN');ok=False
    downloads=wait_for_state(quality_download_buttons) or []
    if not downloads:
        log('  ⚠ Скачивание вложения не найдено','WARN');ok=False
    else:
        before=snapshot_downloads();started=time.time()
        if not click_el(downloads[0]) or not wait_new_download(before,started):ok=False
    if not click_text_deepest('Обсуждение','exact'):
        return False
    if not stage_discussion():ok=False
    driver.refresh()
    if not wait_for_state(get_status):return False
    click_text_deepest('Обсуждение','exact')
    if not wait_for_state(lambda:'Автотест: сообщение по контролю качества' in innertext()):ok=False
    return bool(ok)


def quality_auth_scenario(config):
    global ROLE_RESTORE_FAILED
    if not quality_owned_card():return False
    url=STATE['url']
    try:
        if not logout_current_account():return False
        driver.get(url)
        return bool(wait_for_state(is_login_page))
    finally:
        if not login_with(login_val,pass_val) or not quality_owned_card():
            ROLE_RESTORE_FAILED=True
            raise RuntimeError('Не удалось восстановить авторизованный доступ к своей карточке')


def quality_final_scenario(config):
    if not quality_owned_card():return False
    driver.refresh()
    if not wait_for_state(lambda:status_terminal(get_status())):return False
    forbidden=['Назначить исполнителя','Принять в работу','Исполнить','Провести инспекцию','Не исполнено']
    if find_buttons(forbidden):
        log('  ⚠ У завершённой записи доступны повторные действия жизненного цикла','WARN');return False
    return stage_in_list(config['module'],config['url'])




def quality_case_data(config):
    if not STATE.get('url') or quality_path(STATE['url']) not in QUALITY_OWNED or get_status()=='Черновик':
        if not quality_create_case(config):return False
    return quality_card_scenario(config)


def quality_execution_action(names):
    """Find only the requested execution action, including the card header menu."""
    buttons=find_buttons(names)
    if buttons:return buttons[0]
    allowed={name.casefold() for name in names}
    for kebab in (driver.execute_script(JS_KEBABS) or [])[:3]:
        if not click_el(kebab):continue
        def matching_item():
            return next((el for el,text in (driver.execute_script(JS_CLICKABLES) or [])
                         if text.casefold() in allowed),None)
        item=wait_for_state(matching_item,timeout=2)
        if item is not None:return item
        esc()
    return None


def quality_restore_creator(context):
    global ROLE_RESTORE_FAILED
    if not switch_user(login_val,pass_val):
        ROLE_RESTORE_FAILED=True
        raise RuntimeError('Не удалось войти в аккаунт инициатора: '+context)
    if not quality_owned_card():
        ROLE_RESTORE_FAILED=True
        raise RuntimeError('Вход инициатора успешен, но собственная карточка не открылась: '+context)


def quality_changed_status(previous):
    current=get_status()
    return current if current and current!=previous else None


def quality_assignment_and_empty_execution(config):
    global ROLE_RESTORE_FAILED
    if not quality_owned_card():return False
    try:
        if config['module']!='Инспекция':
            if not switch_user(SECOND_LOGIN,SECOND_PASS) or not quality_owned_card():return False
            prefill_inline()
            buttons=find_buttons(['Назначить исполнителя','Назначить'])
            if buttons:
                if not click_el(buttons[0]):return False
                modal=wait_for_state(find_modal,timeout=4)
                if modal:
                    selects=visible_selects(modal)
                    for select in selects:
                        if not ctrl_enabled(select):continue
                        if not quality_pick_dias(select,'Исполнитель'):return False
                    if not fill_action_modal(modal,'Назначить'):return False
                driver.refresh()
                if not wait_for_state(get_status):return False
            if get_status()=='Назначение исполнителя':
                log('  ⚠ Диас не назначен исполнителем: статус остался Назначение исполнителя','WARN');return False
            # The intended executor must actually be present in the responsible tab.
            click_text_deepest('Ответственные','exact')
            if not wait_for_state(lambda:'диас' in innertext().lower()):return False
        if not switch_user(SECOND_LOGIN,SECOND_PASS) or not quality_owned_card():return False
        names=['Отправить на проверку','На проверку','Исполнить','Выполнить','Провести инспекцию','Подтвердить инспекцию']
        if config['module']=='Инспекция':
            click_text_deepest('Ответственные','exact')
            if not wait_for_state(lambda:'алдажаров диас' in innertext().casefold()):
                log('  ⚠ Диас не найден среди ответственных инспекции','WARN');return False
            names=names+['Подтвердить']
        button=quality_execution_action(names)
        if button is None:
            log(f'  ⚠ У назначенного участника не найдено действие исполнения: {visible_actions()}','WARN')
            return False
        if config['module']=='Инспекция' and (button.text or '').strip()=='Подтвердить':
            # This menu command changes the status directly; it has no empty execution form.
            esc()
            log('  ✓ Диас указан в ответственных; доступно ⋮ → Подтвердить. Проверка пустой формы к этому действию не применяется','PASS')
            return True
        status=get_status()
        if not click_el(button):return False
        modal=wait_for_state(find_modal,timeout=4)
        if not modal:
            log('  ⚠ Действие не открыло форму; отрицательная проверка пустого исполнения не выполнена','WARN')
            return False
        confirm=modal_button(modal,names+MODAL_CONFIRM)
        required=modal.find_elements(By.XPATH,".//*[@required or @aria-required='true']")
        declared_required=bool(required or re.search(r'обязатель|минимум один|прикрепите.+файл',modal.get_attribute('innerText') or '',re.I))
        if not declared_required and confirm is not None:
            log('  Форма исполнения не заявляет обязательных полей; запрет пустого подтверждения не предполагается')
            return True
        # An empty action may be rejected by disabled controls or visible validation.
        rejected=confirm is None
        if confirm is not None:
            click_el(confirm)
            rejected=bool(wait_for_state(lambda:find_modal() is not None and bool(field_errors()),timeout=5))
        if not rejected or get_status()!=status:
            log('  ⚠ Пустое исполнение не было подтверждённо отклонено','WARN')
            return False
        return True
    finally:
        modal=find_modal()
        if modal is not None:close_modal_soft(modal)
        quality_restore_creator('после проверки исполнения')


def quality_advance_case(config,rework=True):
    QUALITY_CASE['want_rework']=bool(rework and config['module']!='Инспекция')
    QUALITY_CASE['reworked']=False
    if not stage_advance():return False
    if QUALITY_CASE['want_rework'] and not QUALITY_CASE['reworked']:
        log('  ⚠ Ветка Не исполнено → повторное исполнение не пройдена','WARN')
        return False
    return quality_final_scenario(config)


def quality_variant_scenario(config,kind):
    if not quality_create_case(config,kind):return False
    if not quality_card_scenario(config):return False
    return quality_advance_case(config,rework=False)


def module_flow(prefix,menu_item,url,create_btn,heading,date_label,create_fn,module):
    config=dict(prefix=prefix,menu=menu_item,url=url,create=create_btn,heading=heading,date=date_label,
        create_fn=create_fn,module=module,key={'Предписание':'issue','БиОТ':'biot','Инспекция':'inspection'}[module],
        block='Блок (подъезд)' if module=='Предписание' else 'Блок (секция)')
    from quality_selection import fixed_only
    import sys
    if fixed_only(sys.argv[1:]):
        if module!='Предписание':return
        step(f'{prefix}: отбор, поиск и навигация по реестру',quality_list_scenario,config)
        step(f'{prefix}: зависимые поля, ограничения ввода и отмена формы',quality_form_contract,config)
        step(f'{prefix}: сохранение черновика и продолжение публикации',quality_create_case,config,'Простое',True)
        if QUALITY_FATAL or ROLE_RESTORE_FAILED:return
        if step(f'{prefix}: создание, данные карточки, документы и обсуждение',quality_case_data,config):
            step(f'{prefix}: назначение участника и обязательные данные исполнения',quality_assignment_and_empty_execution,config)
            if QUALITY_FATAL or ROLE_RESTORE_FAILED:return
            step(f'{prefix}: исполнение, возврат и завершение по ролям',quality_advance_case,config)
            if QUALITY_FATAL or ROLE_RESTORE_FAILED:return
            step(f'{prefix}: завершённая запись — повторные действия и сохранение в реестре',quality_final_scenario,config)
        return
    if not step(f'{prefix}: отбор, поиск и навигация по реестру',quality_list_scenario,config):
        if not quality_list_ready(url):return
    step(f'{prefix}: зависимые поля, ограничения ввода и отмена формы',quality_form_contract,config)
    step(f'{prefix}: отклонение некорректной публикации',quality_negative_form,config)
    if QUALITY_FATAL:return
    step(f'{prefix}: добавление, удаление и повторная загрузка вложений',quality_files_form,config)
    draft_ok=step(f'{prefix}: сохранение черновика и продолжение публикации',quality_create_case,config,'Простое',True)
    if QUALITY_FATAL or ROLE_RESTORE_FAILED:return
    if not draft_ok:STATE['url']=None
    if step(f'{prefix}: создание, данные карточки, документы и обсуждение',quality_case_data,config):
        step(f'{prefix}: доступ к записи без авторизации и восстановление сессии',quality_auth_scenario,config)
        if ROLE_RESTORE_FAILED:return
        step(f'{prefix}: назначение участника и обязательные данные исполнения',quality_assignment_and_empty_execution,config)
        if ROLE_RESTORE_FAILED:return
        step(f'{prefix}: исполнение, возврат и завершение по ролям',quality_advance_case,config)
        if ROLE_RESTORE_FAILED:return
        step(f'{prefix}: завершённая запись — повторные действия и сохранение в реестре',quality_final_scenario,config)
    if module!='Инспекция':
        for kind in ('Критичное','Приостановка'):
            step(f'{prefix}: полный цикл типа «{kind}»',quality_variant_scenario,config,kind)
            if QUALITY_FATAL or ROLE_RESTORE_FAILED:return


def save_quality_results():
    path = Path(os.environ["QUALITY_RESULT_PATH"])
    payload = {"run_id": os.environ["QUALITY_RUN_ID"],
        "results": [{"name": name, "ok": ok, "reason": REASONS.get(name, "")} for name, ok in RESULTS],
        "error": RUN_ERROR, "screenshot": FAILED_SCREENSHOTS[-1] if FAILED_SCREENSHOTS else "",
        "log": LOG_FILE_PATH, "url": STATE.get("url")}
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def run():
    global RUN_ERROR
    log("=" * 60)
    log(f"АВТОТЕСТ «КОНТРОЛЬ КАЧЕСТВА» ({STAMP})")
    log("=" * 60)
    try:
        init_driver()
        driver.get(BASE_URL)
        if not step("Вход и открытие раздела «Контроль качества»", stage_login):
            return
        module_flow("Предписания", "Регистрация предписаний", ISSUE_URL, "Создать предписание",
                    "Создание предписания", "Срок исполнения", stage_issue_create, "Предписание")
        from quality_selection import fixed_only
        if fixed_only(sys.argv[1:]) or ROLE_RESTORE_FAILED or QUALITY_FATAL:
            return
        module_flow("БиОТ", "БиОТ", BIOT_URL, "Создать БиОТ", "Создание БиОТ", "Срок исполнения",
                    stage_biot_create, "БиОТ")
        if ROLE_RESTORE_FAILED or QUALITY_FATAL:
            return
        module_flow("Инспекции", "Инспекции", INSP_URL, "Создать инспекцию",
                    "Создание инспекции", "Дата инспекции", stage_insp_create, "Инспекция")
    except Exception as e:
        RUN_ERROR=f"{type(e).__name__}: {e}"
        log(f"КРИТИЧЕСКАЯ ОШИБКА: {e}", "FAIL")
        shot("critical_error")
    finally:
        save_quality_results()
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


if __name__ == '__main__' and os.environ.get('QUALITY_NO_RUN') != '1':
    if os.environ.get('QUALITY_MANAGED') == '1':
        run()
        raise SystemExit(1 if RUN_ERROR or any(not ok for _,ok in RESULTS) else 0)
    from run_workflow_and_report import run_quality
    raise SystemExit(run_quality(__file__,sys.argv[1:]))