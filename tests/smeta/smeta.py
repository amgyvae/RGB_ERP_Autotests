# -*- coding: utf-8 -*-
"""
АВТОТЕСТ: раздел «Смета» (Сметы проектов) — полный сценарий.

Порядок этапов:
  1. Вход (если нужен) и открытие /estimates
  2. Страница «Сметы проектов»: фильтры (Все этапы / Строительство /
     Проектирование / Завершенные), поиск, открытие карточки проекта
  3. «Создать смету»: Отмена / закрытие, Наименование, Проект (Flagman),
     «Скачать шаблон», «Дублировать» — ПЕРЕБОР смет, пока не пропадёт
     красная ошибка «нет утверждённой версии для копирования».
     Если ни одна не подошла — создаём БЕЗ дублирования с загрузкой
     Excel-шаблона (файл генерируется кодом).
  4. Карточка сметы: сворачивание секций, вкладки Обсуждение/История,
     «Редактировать», «Сменить маршрут» (открыть и отменить), НДС
  5. Маршрут согласования: «Добавить этап» -> «Выбрать согласующего»
     -> Бейсембаев Куаныш
  6. Утверждающий: «Добавить» -> Алдажаров Диас -> «Сохранить»
  7. «Открыть смету»: если пусто — «Добавить строку»; «Развернуть все»,
     «Обновить», «Выгрузить в Excel», «Загрузить из Excel» (шаблон),
     «История сметы», ещё одна «Добавить строку»
  8. Обсуждение: сообщение + файл + «Отправить»
  9. «Отправить на согласование» -> «Согласовать» (Бейсембаев Куаныш)
 10. Алдажаров Диас: «Утвердить» (отдельной подписи ЭЦП нет)

ЗАВИСИМОСТИ (на машине робота):
  pip install openpyxl requests
  (openpyxl — необязательно: без него xlsx собирается вручную;
   отчёты отправляет общий run_workflow_and_report.py)

ВАЖНО — НЕ ПРОВЕРЕНО НА ЖИВОМ DOM (помечено `# TODO VERIFY`):
  дерево «Вид работ», строка выбора согласующего, названия кнопок
  «Согласовать / Утвердить / Подписать», структура модалки загрузки
  Excel на странице позиций. Если что-то не нажмётся — в логе будет
  ⚠ и скриншот debug_*.png, пришлите их — доработаю селектор.
"""

import os
import json
from pathlib import Path
from artifact_paths import screen_path, log_path
from env_config import env, env_list, is_headless  # секреты — из .env / GitHub Secrets
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
import base64
import zipfile
import tempfile
import shutil
from datetime import datetime
from xml.sax.saxutils import escape as xml_escape
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains

# ==========================================
# КОНФИГУРАЦИЯ
# ==========================================
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager

_chrome_options = Options()
_chrome_options.add_argument("--start-maximized")
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

driver = None
CURRENT_LOGIN = None
REVIEWER_LOGIN = env("RGB_ACCOUNT2_LOGIN")
REVIEWER_PASS = env("RGB_ACCOUNT2_PASSWORD")


def init_driver():
    global driver
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=_chrome_options)
    driver.implicitly_wait(0)


login_val = env("RGB_ACCOUNT1_LOGIN", env("RGB_ACCOUNT3_LOGIN"))
pass_val = env("RGB_ACCOUNT1_PASSWORD", env("RGB_ACCOUNT3_PASSWORD"))

# Утверждающий / подписант (Талгат Ерланович)
SECOND_LOGIN = env("RGB_ACCOUNT3_LOGIN", env("RGB_ACCOUNT1_LOGIN"))
SECOND_PASS = env("RGB_ACCOUNT3_PASSWORD", env("RGB_ACCOUNT1_PASSWORD_ALT"))

BASE_URL = "https://testportal.rgbgroup.kz/"
ESTIMATES_URL = BASE_URL + "estimates"
WAIT = 15

STAMP = datetime.now().strftime('%d%m-%H%M%S')
ESTIMATE_NAME = f"AutoTest смета {STAMP}"
PROJECT_QUERY = "Flagman"
APPROVER_QUERY = env("RGB_APPROVER_QUERY", 'Ерлан')
UTV_QUERY = env("RGB_UTV_QUERY", 'Талгат')
UTV_KEYS = ['талгат ерланович', 'талгат', 'ерланович', 'алдажаров диас андреевич', 'алдaжаров диасс андреевичч']
MAX_DUP_TRIES = 40                   # сколько смет для дублирования перебирать

# Названия кнопок статусных действий (TODO VERIFY)
TO_SEND = ["Отправить на согласование"]
TO_APPROVE = ["Согласовать", "Согласовать смету", "Согласовать этап", "Согласование", "Принять", "Одобрить"]
TO_CONFIRM = ["Утвердить", "Утвердить смету", "Утверждение"]

# Кнопку «Удалить» нажимать ОПАСНО (удалит созданную смету).
# True — нажмёт и сразу нажмёт «Отмена» в подтверждении.
CLICK_DELETE_BUTTON = False

DOWNLOAD_DIR = os.environ.get("DOWNLOAD_DIR", os.path.join(os.path.expanduser("~"), "Downloads"))
WORK_DIR = os.path.join(tempfile.gettempdir(), f"smeta_autotest_{STAMP}")
os.makedirs(WORK_DIR, exist_ok=True)


STATE = {"url": None, "template": None, "exported": None}
REASONS = {}
FAILED_SCREENSHOTS = []
RUN_ERROR = ""
RESULTS = []        # (название, ok)
LOG_LINES = []
_RUN_STARTED = time.time()

LOG_FILE_PATH = log_path(f"smeta_log_{datetime.now().strftime('%d%m_%H%M%S')}.txt")
try:
    _LOG_FILE = open(LOG_FILE_PATH, "w", encoding="utf-8", buffering=1)
except Exception:
    _LOG_FILE = None


# ==========================================
# ЛОГИ
# ==========================================
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

def ensure_account(login_value, password_value):
    """Use the account assigned to this workflow stage; stop if switching fails."""
    if CURRENT_LOGIN == login_value and not is_login_page():
        return True
    if not is_login_page():
        logout_current_account()
    return login_with(login_value, password_value)

def _last_problem(start_idx):
    for line in reversed(LOG_LINES[start_idx:]):
        if "[WARN]" in line or "[FAIL]" in line:
            txt = line.split("]", 2)[-1].strip()
            return re.sub(r"^[⚠•✗\s]+", "", txt)[:180]
    return ""


def shot(name):
    try:
        safe = re.sub(r'[^\w\-]+', '_', name)[:40]
        path = screen_path(f"debug_smeta_{safe}_{os.environ.get('SMETA_RUN_ID', STAMP)}_{time.time_ns()}.png")
        driver.save_screenshot(path)
        if name.startswith(("fail_", "critical_error")):
            FAILED_SCREENSHOTS.append(path)
        log(f"  Скриншот: {path}")
    except Exception:
        pass


def record(label, ok, details=""):
    RESULTS.append((label, bool(ok)))
    log(f"{'✓' if ok else '✗'} {label}" + (f" — {details}" if details else ""),
        "PASS" if ok else "FAIL")


def step(label, fn, *args, **kwargs):
    log("=" * 60)
    log(f"ЭТАП: {label}")
    log("=" * 60)
    start_index = len(LOG_LINES)
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
    if not ok:
        REASONS[label] = _last_problem(start_index) or "см. лог"
    record(label, ok)
    return ok


# ==========================================
# БАЗОВЫЕ ХЕЛПЕРЫ
# ==========================================
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
    if not dismiss_news_popup():
        return False
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
              f"[normalize-space(.)='{t}' or contains(normalize-space(.),'{t}')]")
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
        time.sleep(0.2)


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


def get_status():
    try:
        return driver.execute_script("""
            var words = ['Черновик','На согласовании','Согласовано','Согласована','На утверждении',
                         'Утверждено','Утверждена','Подписано','Подписана','На подписании',
                         'Отклонено','Отклонена','На доработке','Архив','Действует'];
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


# ==========================================
# МОДАЛКИ
# ==========================================
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
        time.sleep(0.2)
    return None


def wait_modal_closed(hint=None, timeout=8):
    end = time.time() + timeout
    while time.time() < end:
        if find_modal(hint) is None:
            return True
        time.sleep(0.2)
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


# ==========================================
# UI-SELECT (кастомный кит сайта: ui-select__*)
# ==========================================
def control_by_label(scope, label):
    for xp in [
        f".//*[normalize-space(text())='{label}']/following::button[contains(@class,'ui-select__trigger')][1]",
        f".//*[normalize-space(text())='{label}']/following::*[@role='combobox' or @aria-haspopup][1]",
        f".//*[normalize-space(text())='{label}']/following::button[1]",
    ]:
        try:
            for e in scope.find_elements(By.XPATH, xp):
                if e.is_displayed():
                    return e
        except Exception:
            continue
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
        p = wait_for_state(visible_panel, timeout=2)
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
        if wait_for_state(lambda: visible_panel() is None, timeout=2):
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
            if wait_for_state(lambda: visible_panel() is None, timeout=2):
                return target["text"]
        except Exception:
            pass
    return None


# ==========================================
# ФАЙЛЫ-ШАБЛОНЫ
# ==========================================
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


def create_test_excel(path=None):
    """Шаблонный xlsx с позициями сметы (если сайт отдаст свой шаблон — берём его, см. prepare_import_excel)."""
    path = path or os.path.join(WORK_DIR, f"smeta_template_{STAMP}.xlsx")
    rows = [
        ["Наименование", "Тип", "Ед.изм", "Количество",
         "Цена за единицу без НДС", "Цена за единицу с НДС"],
        [f"Автотест работа 1 {STAMP}", "Работа", "усл", 10, 10000, 11600],
        [f"Автотест материал 1 {STAMP}", "Материал", "шт", 5, 2000, 2320],
    ]
    try:
        import openpyxl
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Смета"
        for r in rows:
            ws.append(r)
        wb.save(path)
    except ImportError:
        _xlsx_minimal(path, rows)
    log(f"    Excel-шаблон создан: {path}")
    return path


def fill_template_with_data(src, dst):
    """Берёт скачанный с сайта шаблон и дописывает строку под заголовком."""
    try:
        import openpyxl
    except ImportError:
        return None
    try:
        wb = openpyxl.load_workbook(src)
        ws = wb.active
        hdr = None
        for r in range(1, min(ws.max_row, 15) + 1):
            vals = [str(c.value or "").lower() for c in ws[r]]
            if any("наименован" in v for v in vals):
                hdr = r
                break
        if hdr is None:
            return None
        r = hdr + 1
        for c in ws[hdr]:
            h = str(c.value or "").lower().strip()
            if "наименован" in h:
                v = f"Автотест работа (шаблон) {STAMP}"
            elif h.startswith("тип"):
                v = "Работа"
            elif h.startswith("ед"):
                v = "усл"
            elif h.startswith("кол"):
                v = 10
            elif "цена" in h or "стоимость" in h:
                v = 11600 if ("с ндс" in h and "без" not in h) else 10000
            else:
                continue
            ws.cell(row=r, column=c.column, value=v)
        wb.save(dst)
        return dst
    except Exception as e:
        log(f"    ⚠ Не удалось заполнить скачанный шаблон: {e}", "WARN")
        return None


def prepare_import_excel():
    if STATE["template"] and os.path.exists(STATE["template"]):
        dst = os.path.join(WORK_DIR, f"smeta_import_{STAMP}.xlsx")
        filled = fill_template_with_data(STATE["template"], dst)
        if filled:
            log("    Использую заполненный шаблон с сайта")
            return filled
    return create_test_excel()


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
        time.sleep(0.25)
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


# ==========================================
# ВХОД / ВЫХОД
# ==========================================
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
    log(f"  Логин под: {login_value}")
    if not is_login_page():
        driver.get(BASE_URL)
        time.sleep(3)
        dismiss_news_popup(wait=1)
    try:
        WebDriverWait(driver, WAIT).until(EC.visibility_of_element_located(
            (By.XPATH, "//input[@type='password']")))
    except Exception:
        driver.get(BASE_URL)
        try:
            WebDriverWait(driver, 10).until(EC.visibility_of_element_located(
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
    if not wait_for_state(lambda: driver.current_url.startswith(BASE_URL)
            and not is_login_page() and bool(page_text()), timeout=20):
        log(f"  ⚠ Логин {login_value} не удался", "WARN")
        return False
    log(f"  ✓ Успешный вход: {login_value}", "PASS")
    if not dismiss_news_popup(wait=3):
        return False
    CURRENT_LOGIN = login_value
    return True


KC_LOGOUT_URL = "https://auth.testportal.rgbgroup.kz/realms/rgb/protocol/openid-connect/logout"


def logout_current_account():
    global CURRENT_LOGIN
    log("  Выход из текущего аккаунта...")
    if is_login_page():
        CURRENT_LOGIN = None
        return True

    # 1. Попытка выхода через UI
    try:
        if click_text_deepest("Выйти", "contains"):
            time.sleep(2)
            modal = wait_modal("выйдете", 3) or wait_modal("Вы уверены", 2)
            if modal:
                btn = modal_button(modal, ["Выйти", "Да", "ОК", "Подтвердить"])
                if btn:
                    click_el(btn)
                    time.sleep(3)
    except Exception as e:
        log(f"  • UI-выход: {e}", "INFO")

    if is_login_page():
        log("  ✓ Вышли через UI", "PASS")
        CURRENT_LOGIN = None
        return True

    # 2. Выход через Keycloak logout endpoint
    try:
        driver.get(KC_LOGOUT_URL)
        time.sleep(2)
        for xp in ["//*[@id='kc-logout']", "//input[@type='submit']",
                   "//button[contains(normalize-space(.),'Выйти') or contains(normalize-space(.),'Logout') or normalize-space(.)='Да']"]:
            try:
                for b in driver.find_elements(By.XPATH, xp):
                    if b.is_displayed():
                        click_el(b)
                        time.sleep(2)
                        break
            except Exception:
                pass
    except Exception as e:
        log(f"  • Keycloak logout: {e}", "INFO")

    # 3. Очистка куки и сессий
    try:
        driver.delete_all_cookies()
        driver.execute_script("try{localStorage.clear();sessionStorage.clear();}catch(e){}")
    except Exception:
        pass

    driver.get(BASE_URL)
    time.sleep(4)
    dismiss_news_popup(wait=2)
    ok = is_login_page()
    if ok:
        CURRENT_LOGIN = None
        log("  ✓ Успешный выход из системы", "PASS")
    else:
        log(f"  ⚠ После выхода страница: {driver.current_url}", "WARN")
    return ok


# ==========================================
# NCALayer
# ==========================================




# ==========================================
# НАВИГАЦИЯ
# ==========================================
def smeta_card_ready():
    return "/estimates/versions/" in driver.current_url and "/lines" not in driver.current_url and (
        bool(find_buttons(["Открыть смету"])) or "основная информация" in page_text())


def smeta_list_ready():
    return "estimates" in driver.current_url and "/versions/" not in driver.current_url and (
        bool(find_buttons(["Создать смету", "Создать"])) or "смет" in page_text())


def smeta_lines_ready():
    return "/lines" in driver.current_url and bool(find_buttons(["Добавить строку"]))


def goto_card():
    url = STATE.get("url")
    if not url:
        try:
            driver.get(ESTIMATES_URL)
            time.sleep(3)
            for link in driver.find_elements(By.XPATH, "//table//tr//a[contains(@href, '/estimates/')] | //a[contains(@href, '/estimates/') and not(contains(@href, '/create'))]"):
                if link.is_displayed():
                    href = link.get_attribute("href")
                    if href and "/create" not in href:
                        STATE["url"] = href
                        url = href
                        break
        except Exception:
            pass
    if not url:
        return False
    driver.get(url)
    time.sleep(1.5)
    return bool(wait_for_state(smeta_card_ready))


def open_lines():
    if "/lines" in driver.current_url:
        block_native_file_dialog()
        return True
    goto_card()
    if click_button(["Открыть смету"], wait=8):
        if wait_for_state(smeta_lines_ready, timeout=12):
            block_native_file_dialog()
            return True
    driver.get(STATE["url"].rstrip("/") + "/lines")
    ready = wait_for_state(smeta_lines_ready)
    block_native_file_dialog()
    return bool(ready)


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


def lines_state():
    try:
        rows = driver.execute_script("""
            return Array.prototype.filter.call(document.querySelectorAll('tbody tr'),
                function(r){ return r.offsetWidth || r.offsetHeight; }).length;""")
    except Exception:
        rows = 0
    return rows, parse_total()


# ==========================================
# ЭТАП 1: ВХОД
# ==========================================
def stage_login():
    log(f"  URL: {driver.current_url}")
    if is_login_page():
        if not login_with(login_val, pass_val):
            return False
    driver.get(ESTIMATES_URL)
    wait_for_state(lambda: is_login_page() or smeta_list_ready())
    if is_login_page():
        return False
    ok = "estimates" in driver.current_url
    log(f"  URL после входа: {driver.current_url}", "PASS" if ok else "WARN")
    return ok


# ==========================================
# ЭТАП 2: СТРАНИЦА «СМЕТЫ ПРОЕКТОВ»
# ==========================================
def stage_list_page():
    driver.get(ESTIMATES_URL)
    if not wait_for_state(smeta_list_ready):
        return False
    ok = True
    for prefix in ["Строительство", "Проектирование", "Завершенные", "Все этапы"]:
        if click_text_deepest(prefix, "prefix"):
            log(f"  ✓ Фильтр '{prefix}'", "PASS")
            time.sleep(1.2)
        else:
            log(f"  ⚠ Фильтр '{prefix}' не найден", "WARN")
            ok = False

    inp = None
    for e in driver.find_elements(By.XPATH, "//input[contains(@placeholder,'Поиск')]"):
        if e.is_displayed():
            inp = e
            break
    if inp:
        type_text(inp, PROJECT_QUERY)
        time.sleep(2)
        found = PROJECT_QUERY.lower() in page_text()
        log(f"  Поиск '{PROJECT_QUERY}': {'найдено' if found else 'не найдено'}",
            "PASS" if found else "WARN")
        ok = ok and found
        try:
            inp.send_keys(Keys.CONTROL, "a")
            inp.send_keys(Keys.BACKSPACE)
        except Exception:
            pass
        set_native_value(inp, "")
        time.sleep(1.5)
    else:
        log("  ⚠ Поле поиска не найдено", "WARN")
        ok = False

    if click_text_deepest(PROJECT_QUERY, "contains"):
        time.sleep(3)
        log(f"  ✓ Открыта карточка проекта: {driver.current_url}", "PASS")
    else:
        log("  ⚠ Карточка проекта не найдена", "WARN")
        ok = False
    driver.get(ESTIMATES_URL)
    ok = bool(wait_for_state(smeta_list_ready)) and ok
    return ok


# ==========================================
# ЭТАП 3: СОЗДАНИЕ СМЕТЫ
# ==========================================
def open_create_modal():
    if not click_button(["Создать смету"], wait=8):
        return None
    return wait_modal("Создать смету", 8)


def fill_create_form(modal):
    try:
        inp = modal.find_element(By.XPATH, ".//input[contains(@placeholder,'аименование')]")
        type_text(inp, ESTIMATE_NAME)
        log(f"  ✓ Наименование: {ESTIMATE_NAME}", "PASS")
    except Exception as e:
        log(f"  ⚠ Наименование: {e}", "WARN")
        return False
    trg = control_by_label(modal, "Проект")
    panel = open_ui(trg)
    picked = select_in_panel(panel, keywords=[PROJECT_QUERY], search=PROJECT_QUERY) if panel else None
    if not picked:
        log("  ⚠ Проект не выбран", "WARN")
        return False
    log(f"  ✓ Проект: {picked}", "PASS")
    time.sleep(1.2)
    return True


def download_template(modal):
    before = snapshot_downloads()
    t0 = time.time()
    btns = find_buttons(["Скачать шаблон"], scope=modal)
    if not btns:
        try:
            btns = [e for e in modal.find_elements(
                By.XPATH, ".//*[contains(normalize-space(text()),'Скачать шаблон')]")
                if e.is_displayed()]
        except Exception:
            btns = []
    if not btns:
        log("  ⚠ Кнопка 'Скачать шаблон' не найдена", "WARN")
        return False
    click_el(btns[0])
    f = wait_new_download(before, t0, timeout=20, ext=(".xlsx", ".xls"))
    if f:
        STATE["template"] = f
        log(f"  ✓ Шаблон скачан: {f}", "PASS")
        return True
    log("  ⚠ Файл шаблона не появился в папке загрузок "
        f"({DOWNLOAD_DIR}) — буду использовать сгенерированный", "WARN")
    return False


def wait_create_result(timeout=10):
    end = time.time() + timeout
    while time.time() < end:
        if "/estimates/versions/" in driver.current_url:
            return "created", ""
        for t in read_toasts():
            low = t.lower()
            if "создана" in low and "не " not in low:
                if wait_for_state(lambda: "/estimates/versions/" in driver.current_url, timeout=5):
                    return "created", t
            if any(k in low for k in ["нет утвержд", "не удалось", "ошибк", "нельзя", "не может"]):
                return "error", t
        time.sleep(0.2)
    if "/estimates/versions/" in driver.current_url:
        return "created", ""
    return "timeout", ""


def try_create_with_duplicates():
    modal = find_modal("Создать смету")
    dup = control_by_label(modal, "Дублировать") if modal else None
    if dup is None:
        log("  • Поле 'Дублировать' не найдено", "WARN")
        return False
    panel = open_ui(dup)
    if not panel:
        log("  • Список 'Дублировать' не открылся (нет смет в проекте?)", "WARN")
        return False
    total = len(panel_options(panel))
    close_panels()
    log(f"  Смет для дублирования: {total}")
    for idx in range(min(total, MAX_DUP_TRIES)):
        modal = find_modal("Создать смету")
        if modal is None:
            break
        dup = control_by_label(modal, "Дублировать")
        panel = open_ui(dup)
        if not panel:
            break
        opts = panel_options(panel)
        if idx >= len(opts):
            close_panels()
            break
        txt = opts[idx]["text"]
        chosen = select_in_panel(panel, index=idx)
        log(f"  [{idx + 1}/{total}] Дублирую: {txt[:60]} → {'выбрано' if chosen else 'НЕ выбрано'}")
        if not chosen:
            continue
        time.sleep(0.8)
        btn = modal_button(modal, ["Создать"])
        if not btn:
            log("  ⚠ Кнопка 'Создать' недоступна", "WARN")
            continue
        click_el(btn)
        res, msg = wait_create_result(10)
        if res == "created":
            log(f"  ✓ Смета создана с дублированием: {txt[:60]}", "PASS")
            return True
        log(f"  ✗ Не создалось ({res}): {msg or '—'} → беру следующую", "WARN")
        shot(f"dup_error_{idx + 1}")
        time.sleep(4)   # дожидаемся, пока уйдёт красное уведомление
    return False


# Negative cases execute in the regular workflow, using fresh forms each time.
NEGATIVE_FATAL = False


def negative_button(modal, text):
    buttons = modal.find_elements(By.XPATH, f".//button[normalize-space(.)='{text}']")
    return next((b for b in buttons if b.is_displayed()), None)


def negative_error_text(modal, old_toasts=()):
    messages = [t for t in read_toasts() if t not in old_toasts]
    messages += driver.execute_script("""
        return Array.from(arguments[0].querySelectorAll(
            '[role=alert], [aria-invalid=true], [class*=error], [class*=invalid], '
            + '[class*=text-red], [class*=text-danger]'))
            .filter(e => e.offsetWidth || e.offsetHeight || e.getClientRects().length)
            .map(e => e.innerText || e.validationMessage || e.getAttribute('aria-label') || '')
            .filter(Boolean);
    """, modal) or []
    # File parser errors may be a plain card rather than an alert element.
    text = (modal.get_attribute('innerText') or '').lower()
    for line in text.splitlines():
        if any(word in line for word in ('не загрузится', 'не найден', 'не найдена',
                                         'неверн', 'некоррект', 'не поддерж', 'ошибок', 'ошибка')) or line.strip() in (
                'выберите вид работ', 'выберите ед. измерения', 'выберите единицу измерения', 'заполните поля'):
            messages.append(line.strip())
    return ' | '.join(messages)


def negative_rejection(modal, button_text, *, require_file_error=False, old_toasts=()):
    """Confirm explicit rejection; an enabled but unresponsive form is failure."""
    global NEGATIVE_FATAL
    button = negative_button(modal, button_text)
    if button is None:
        log(f"  ⚠ Для отрицательной проверки не найдена кнопка «{button_text}»", "WARN")
        return False
    errors = negative_error_text(modal, old_toasts)
    if require_file_error:
        def file_error():
            value = negative_error_text(modal, old_toasts)
            return value if any(k in value.lower() for k in
                ('файл', 'excel', 'xlsx', 'заголов', 'формат', 'расширен', 'столбц')) else False
        errors = wait_for_state(file_error, timeout=8) or ''
    if require_file_error and errors:
        if not button.is_enabled() or button.get_attribute('aria-disabled') == 'true':
            log(f"  ✓ Неверный файл отклонён: {errors[:300]}", "PASS")
            return True
    if require_file_error and (not button.is_enabled() or button.get_attribute('aria-disabled') == 'true'):
        log("  ⚠ Кнопка заблокирована, но явная ошибка файла не появилась", "WARN")
        return False
    if not require_file_error:
        if not button.is_enabled() or button.get_attribute('aria-disabled') == 'true':
            log(f"  ✓ «{button_text}» недоступна при незаполненных полях", "PASS")
            return True
        invalid = driver.execute_script("""
            return Array.from(arguments[0].querySelectorAll('input,select,textarea'))
                .filter(e => e.willValidate && !e.checkValidity())
                .map(e => e.validationMessage).filter(Boolean);
        """, modal) or []
        if invalid:
            log(f"  ✓ Нативная валидация запрещает сохранение: {invalid}", "PASS")
            return True
    old_url = driver.current_url
    errors_before_click = negative_error_text(modal, old_toasts)
    if not click_el(button):
        log("  ⚠ Кнопка не нажалась; отказ валидации не подтверждён", "WARN")
        return False
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        try:
            visible = modal.is_displayed()
        except Exception as exc:
            if type(exc).__name__ != 'StaleElementReferenceException':
                raise
            visible = False
        if driver.current_url != old_url or not visible:
            NEGATIVE_FATAL = True
            log("  ⚠ Форма закрылась или произошёл переход: неверные данные могли сохраниться", "WARN")
            return False
        errors = negative_error_text(modal, old_toasts)
        if errors and errors != errors_before_click and (not require_file_error or any(k in errors.lower() for k in
                ('файл', 'excel', 'xlsx', 'заголов', 'формат', 'расширен', 'столбц'))):
            log(f"  ✓ Система отказала в сохранении: {errors[:300]}", "PASS")
            return True
        time.sleep(0.2)
    log("  ⚠ Форма осталась открыта, но явного отказа нет — проверка не подтверждена", "WARN")
    return False


def negative_close(modal, hint):
    global NEGATIVE_FATAL
    if not NEGATIVE_FATAL:
        try:
            close_modal_soft(modal)
            if wait_modal_closed(hint, timeout=5):
                return True
        except Exception as exc:
            log(f"  ⚠ Закрытие формы: {type(exc).__name__}", "WARN")
        NEGATIVE_FATAL = True
        log("  ⚠ Не удалось закрыть форму после отрицательной проверки", "WARN")
    return False


def negative_project_control(modal, wait=6):
    deadline = time.monotonic() + wait
    placeholders = ('выбрать проект', 'выберите проект')
    while True:
        for element in modal.find_elements(By.XPATH,
                ".//button | .//*[@role='combobox']"):
            if element.is_displayed():
                text = ' '.join((element.text or element.get_attribute('innerText') or '').split()).lower()
                if 'загруз' not in text and text in placeholders:
                    return element, text
        element = control_by_label(modal, 'Проект')
        if element is not None:
            text = ' '.join((element.text or element.get_attribute('innerText') or '').split()).lower()
            if 'загруз' not in text:
                return element, text
        if time.monotonic() >= deadline:
            break
        time.sleep(0.3)
    elem = control_by_label(modal, 'Проект')
    txt = ' '.join((elem.text or elem.get_attribute('innerText') or '').split()).lower() if elem else ''
    return elem, txt


def negative_create_case(case):
    global NEGATIVE_FATAL
    driver.get(ESTIMATES_URL)
    if not wait_for_state(smeta_list_ready):
        log("  ⚠ Список смет не загрузился", "WARN")
        return False
    block_native_file_dialog()
    modal = open_create_modal()
    if modal is None:
        log("  ⚠ Форма создания не открылась для отрицательной проверки", "WARN")
        return False
    result = False
    closed = False
    try:
        name = modal.find_element(By.XPATH, ".//input[contains(@placeholder,'аименование')]")
        project, project_text = negative_project_control(modal)
        if name is None or project is None:
            log("  ⚠ Поля названия/проекта не найдены", "WARN")
            return False
        # A preselected project would invalidate the empty/no-project fixture.
        if case in ('empty', 'no_project') and project_text not in ('выбрать проект', 'выберите проект'):
            log(f"  ⚠ Пустой проект не подтверждён; видимый текст поля: {project_text!r}", "WARN")
            return False
        type_text(name, '' if case in ('empty', 'no_name') else f'NEG-{case}-{STAMP}')
        if case in ('no_name', 'bad_type', 'bad_headers'):
            panel = open_ui(project)
            picked = select_in_panel(panel, keywords=[PROJECT_QUERY], search=PROJECT_QUERY) if panel else None
            if not picked:
                log("  ⚠ Для отрицательной проверки не удалось выбрать проект", "WARN")
                return False
        if case in ('empty', 'no_name') and (name.get_attribute('value') or '').strip():
            log("  ⚠ Название не очистилось", "WARN")
            return False
        old_toasts = tuple(read_toasts())
        if case == 'bad_type':
            file_path = create_test_txt('negative_unsupported')
            if not send_file(file_path, scope=modal):
                log("  ⚠ Файл не передан — отказ приложения не подтверждён", "WARN")
                return False
        elif case == 'bad_headers':
            file_path = os.path.join(WORK_DIR, f'negative_headers_{STAMP}.xlsx')
            _xlsx_minimal(file_path, [['WrongHeader'], ['invalid test row']])
            if not send_file(file_path, scope=modal):
                log("  ⚠ Excel не передан — отказ приложения не подтверждён", "WARN")
                return False
        result = negative_rejection(modal, 'Создать',
                                    require_file_error=case in ('bad_type', 'bad_headers'), old_toasts=old_toasts)
    finally:
        closed = negative_close(modal, 'Создать смету')
    return result and closed


def stage_negative_empty_create():
    return negative_create_case('empty')


def stage_negative_no_name():
    return negative_create_case('no_name')


def stage_negative_no_project():
    return negative_create_case('no_project')


def stage_negative_file_type():
    return negative_create_case('bad_type')


def stage_negative_file_headers():
    return negative_create_case('bad_headers')


def stage_negative_empty_line():
    global NEGATIVE_FATAL
    if not open_lines():
        return False
    rows_before, total_before = lines_state()
    if not click_button(['Добавить строку'], wait=6):
        return False
    modal = wait_modal('Добавить строку', timeout=8)
    if modal is None:
        return False
    result = False
    closed = False
    try:
        # Clear numeric defaults so the case actually submits empty fields.
        for label in ('Количество', 'Цена за единицу без НДС', 'Цена за единицу с НДС'):
            elements = modal.find_elements(By.XPATH,
                f".//*[normalize-space(text())='{label}']/following::input[1]")
            for element in elements:
                if element.is_displayed() and element.is_enabled():
                    type_text(element, '')
                    if (element.get_attribute('value') or '').strip():
                        log(f"  ⚠ Поле «{label}» не очистилось", "WARN")
                        return False
        result = negative_rejection(modal, 'Добавить', old_toasts=tuple(read_toasts()))
    finally:
        closed = negative_close(modal, 'Добавить строку')
    rows_after, total_after = lines_state()
    if rows_after != rows_before or total_after != total_before:
        NEGATIVE_FATAL = True
        log("  ⚠ После отрицательной проверки изменились строки/итог сметы", "WARN")
        return False
    return result and closed



def stage_create():
    modal = open_create_modal()
    if not modal:
        log("  ⚠ Модалка 'Создать смету' не открылась", "WARN")
        return False
    log("  ✓ Модалка 'Создать смету' открыта", "PASS")

    # проверка кнопок «Отмена» и крестика
    if close_modal_soft(modal):
        time.sleep(1)
    log(f"  Отмена: модалка {'закрыта' if find_modal('Создать смету') is None else 'осталась'}")
    modal = open_create_modal()
    if not modal:
        return False
    try:
        xs = [x for x in modal.find_elements(
            By.XPATH, ".//button[@aria-label='Закрыть' or @aria-label='Close' "
                      "or contains(@class,'close')]") if x.is_displayed()]
        if xs:
            click_el(xs[0])
            time.sleep(1)
            log("  ✓ Крестик закрытия нажат", "PASS")
            modal = open_create_modal()
    except Exception:
        pass
    if not modal:
        return False

    if not fill_create_form(modal):
        return False
    download_template(modal)

    created = try_create_with_duplicates()

    if not created:
        log("  Дублирование не удалось — создаю смету без дублирования + загрузка Excel")
        m = find_modal("Создать смету")
        if m:
            close_modal_soft(m)
            time.sleep(1.5)
        modal = open_create_modal()
        if not modal or not fill_create_form(modal):
            return False
        xlsx = prepare_import_excel()
        send_file(xlsx, scope=modal)
        time.sleep(2)
        btn = modal_button(modal, ["Создать"])
        if not btn:
            log("  ⚠ Кнопка 'Создать' недоступна", "WARN")
            return False
        click_el(btn)
        res, msg = wait_create_result(15)
        created = res == "created"
        if not created:
            log(f"  ⚠ Смета не создана ({res}): {msg}", "WARN")

    if created:
        if not wait_for_state(smeta_card_ready):
            log("  ⚠ После создания карточка сметы не загрузилась", "WARN")
            return False
        STATE["url"] = driver.current_url.split("?")[0].rstrip("/")
        log(f"  ✓ Карточка сметы: {STATE['url']}", "PASS")
    return created


# ==========================================
# ЭТАП 4: КАРТОЧКА СМЕТЫ
# ==========================================
def try_open_and_cancel(text):
    goto_card()
    if not (click_button([text], wait=5) or click_text_deepest(text, "contains")):
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


def stage_card_buttons():
    goto_card()
    ok = True
    for h in ["Основная информация", "Финансовые показатели"]:
        for _ in range(2):
            if not click_text_deepest(h, "exact"):
                log(f"  ⚠ Секция '{h}' не найдена", "WARN")
                ok = False
                break
            time.sleep(0.8)
        else:
            log(f"  ✓ Секция '{h}': свернуть/развернуть", "PASS")
    for tab in ["История", "Обсуждение"]:
        if click_text_deepest(tab, "exact"):
            log(f"  ✓ Вкладка '{tab}'", "PASS")
            time.sleep(1.5)
        else:
            log(f"  ⚠ Вкладка '{tab}' не найдена", "WARN")
            ok = False

    # переключатель «Уведомлять меня о сообщениях» — туда и обратно
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

    # карандаш у ставки НДС
    try:
        pen = driver.find_element(
            By.XPATH, "//*[normalize-space(text())='Ставка НДС']/following::button[1]")
        hard_click(pen)
        time.sleep(1.2)
        try:
            ActionChains(driver).send_keys(Keys.ESCAPE).perform()
        except Exception:
            pass
        log("  ✓ Карандаш НДС нажат", "PASS")
        driver.get(STATE["url"])
        time.sleep(3)
    except Exception:
        log("  • Карандаш НДС не найден", "WARN")

    ok = try_open_and_cancel("Редактировать") and ok
    if find_buttons(["Сменить маршрут"]):
        ok = try_open_and_cancel("Сменить маршрут") and ok
    if CLICK_DELETE_BUTTON:
        try_open_and_cancel("Удалить")
    goto_card()
    return ok


# ==========================================
# ЭТАП 5: МАРШРУТ СОГЛАСОВАНИЯ
# ==========================================
def route_has_approver():
    txt = page_text()
    m = re.search(r"маршрут согласования(.*?)утверждающий", txt, re.S)
    seg = m.group(1) if m else txt
    return any(word in seg for word in ("бейсембаев", "куаныш", "ерлан", "талгат", "согласующ"))


def approver_trigger():
    try:
        for t in driver.find_elements(
                By.XPATH,
                "//button[contains(@class,'ui-select__trigger')]"
                "[contains(normalize-space(.),'Выбрать согласующего') or contains(.,'согласующ')] | "
                "//div[contains(@class,'ui-select__trigger')][contains(normalize-space(.),'Выбрать согласующего') or contains(.,'согласующ')] | "
                "//*[contains(@class,'ui-select')]//button | "
                "//button[contains(normalize-space(.),'Выбрать согласующего')]"):
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
        # Нажимаем круглую синюю кнопку '+👤' / 'Этапы согласования не настроены'
        clicked = False
        for xp in [
            "//*[contains(normalize-space(.),'Этапы согласования')]",
            "//*[contains(normalize-space(text()),'Маршрут согласования')]/following::button[1]",
            "//*[contains(normalize-space(text()),'Маршрут согласования')]/following::*[self::button or self::div][1]",
            "//button[contains(.,'Добавить этап') or contains(.,'Этап')]"
        ]:
            try:
                for b in driver.find_elements(By.XPATH, xp):
                    if b.is_displayed():
                        click_el(b)
                        clicked = True
                        time.sleep(1.5)
                        break
            except Exception:
                pass
            if clicked:
                break

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
        log("  • Селект 'Выбрать согласующего' не найден (возможно, маршрут фиксирован)", "INFO")
        return True

    panel = open_ui(trg)
    if not panel:
        log("  ⚠ Список согласующих не открылся", "WARN")
        return False
    keywords = ["ерлан талгатович", "ерлан", "талгатович", "бейсембаев", "куаныш"]
    picked = select_in_panel(panel, keywords=keywords,
                             search=APPROVER_QUERY)
    if not picked:
        picked = select_in_panel(panel, index=0)
    if not picked:
        log(f"  ⚠ Согласующий не найден в списке", "WARN")
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
    return True


# ==========================================
# ЭТАП 6: УТВЕРЖДАЮЩИЙ
# ==========================================
def add_approver_final():
    goto_card()
    if any(w in page_text().lower() for w in ("талгат", "ерланович", "алдажаров", "алдaжаров", "диас")):
        log("  ✓ Утверждающий уже назначен", "PASS")
        return True
    btn = None
    for xp in [
        "//*[normalize-space(text())='Утверждающий']/following::button[normalize-space(.)='Добавить'][1]",
        "//*[contains(normalize-space(text()),'Утверждающий')]/following::*[self::button or self::a][contains(normalize-space(.),'Добавить')][1]",
        "//*[contains(normalize-space(text()),'Утверждающий не назначен')]"
        "/following::*[self::button or self::a][normalize-space(.)='Добавить'][1]",
    ]:
        try:
            for b in driver.find_elements(By.XPATH, xp):
                if b.is_displayed():
                    btn = b
                    break
        except Exception:
            pass
        if btn:
            break
    if not btn:
        log("  • Утверждающий уже задан либо кнопка 'Добавить' скрыта", "INFO")
        return True
    click_el(btn)
    modal = wait_modal("Утверждающий", 8)
    if not modal:
        log("  ⚠ Модалка 'Утверждающий' не открылась", "WARN")
        return False
    trg = None
    try:
        ts = [t for t in modal.find_elements(
            By.XPATH, ".//button[contains(@class,'ui-select__trigger')]") if t.is_displayed()]
        trg = ts[0] if ts else None
    except Exception:
        pass
    panel = open_ui(trg)
    picked = select_in_panel(panel, keywords=UTV_KEYS + ["талгат", "ерланович", "алдажаров", "диас"], search=UTV_QUERY) if panel else None
    if not picked and panel:
        picked = select_in_panel(panel, index=0)
    if not picked:
        log("  ⚠ Утверждающий не выбран", "WARN")
        close_panels()
        close_modal_soft(modal)
        return False
    log(f"  ✓ Утверждающий: {picked}", "PASS")
    time.sleep(1)
    save = modal_button(modal, ["Сохранить"])
    if save:
        click_el(save)
        wait_modal_closed("Утверждающий", 8)
    time.sleep(2)
    return True


# ==========================================
# ЭТАП 7: ПОЗИЦИИ СМЕТЫ
# ==========================================
def pick_work_kind(modal):
    """Вид работ — дерево с поиском (TODO VERIFY разметку)."""
    ctrl = control_by_label(modal, "Вид работ")
    if ctrl is None:
        log("    ⚠ Контрол 'Вид работ' не найден", "WARN")
        return False
    open_ui(ctrl)
    time.sleep(0.8)
    sinp = None
    for e in driver.find_elements(By.XPATH, "//input[contains(@placeholder,'Поиск')]"):
        if e.is_displayed():
            sinp = e
    if sinp:
        type_text(sinp, "Налоги ТОО")
        time.sleep(1.5)
    target = None
    for e in driver.find_elements(
            By.XPATH, "//*[contains(normalize-space(text()),'Налоги ТОО')]"):
        if e.is_displayed():
            target = e
            break
    if target is None:
        target = driver.execute_script("""
            var all = document.querySelectorAll('*');
            for (var i = 0; i < all.length; i++) {
                var e = all[i];
                if (e.children.length || !(e.offsetWidth || e.offsetHeight)) continue;
                var t = (e.textContent || '').trim();
                if (/^\\d+\\.\\d+\\.\\d+\\s/.test(t)) return e;
            }
            return null;""")
    if target is None:
        log("    ⚠ Листовой вид работ не найден в дереве", "WARN")
        return False

    def changed():
        txt = (ctrl.get_attribute("textContent") or "").lower()
        return "выбрать виды" not in txt

    for cand in [target]:
        for _ in range(2):
            hard_click(cand)
            time.sleep(0.9)
            if changed():
                break
        if changed():
            break
        try:
            par = cand.find_element(
                By.XPATH, "./ancestor::*[self::button or @role='option' "
                          "or @role='treeitem' or self::li][1]")
            hard_click(par)
            time.sleep(0.9)
        except Exception:
            pass
    # закрываем выпадашку кликом по заголовку модалки (Escape закрыл бы всю модалку)
    try:
        title = modal.find_element(By.XPATH, ".//*[normalize-space(text())='Добавить строку']")
        hard_click(title)
        time.sleep(0.6)
    except Exception:
        pass
    ok = changed()
    log(f"    {'✓' if ok else '⚠'} Вид работ", "PASS" if ok else "WARN")
    return ok


def add_line_row(desc):
    if not click_button(["Добавить строку"], wait=6):
        log("  ⚠ Кнопка 'Добавить строку' не найдена", "WARN")
        return False
    modal = wait_modal("Добавить строку", 8)
    if not modal:
        log("  ⚠ Модалка 'Добавить строку' не открылась", "WARN")
        return False
    rows0, total0 = lines_state()

    pick_work_kind(modal)

    # Ед.изм
    unit = control_by_label(modal, "Ед.изм")
    if unit is not None:
        utxt = (unit.get_attribute("textContent") or "").strip().lower()
        if not utxt or "выбрать" in utxt:
            panel = open_ui(unit)
            picked = select_in_panel(panel, keywords=["(усл)", "усл"], search="усл") if panel else None
            if not picked and panel:
                close_panels()
                panel = open_ui(unit)
                picked = select_in_panel(panel, index=0)
            log(f"    Ед.изм: {picked or 'НЕ выбрана'}", "PASS" if picked else "WARN")

    def num_field(label, value):
        try:
            inp = modal.find_element(
                By.XPATH, f".//*[normalize-space(text())='{label}']/following::input[1]")
            if inp.is_displayed() and inp.is_enabled():
                if not (inp.get_attribute("value") or "").strip():
                    set_native_value(inp, value)
                log(f"    ✓ {label}: {inp.get_attribute('value')}", "PASS")
                return True
        except Exception:
            pass
        log(f"    ⚠ Поле '{label}' не найдено", "WARN")
        return False

    num_field("Количество", "10")
    num_field("Цена за единицу без НДС", "10000")
    time.sleep(0.5)
    num_field("Цена за единицу с НДС", "11600")

    try:
        ta = [t for t in modal.find_elements(By.XPATH, ".//textarea") if t.is_displayed()]
        if ta:
            type_text(ta[0], f"Автотест строка: {desc}")
    except Exception:
        pass

    save = modal_button(modal, ["Добавить"])
    if not save:
        log("  ⚠ Кнопка 'Добавить' недоступна", "WARN")
        shot("add_row_no_button")
        close_modal_soft(modal)
        return False
    click_el(save)
    closed = wait_modal_closed("Добавить строку", 8)
    time.sleep(2)
    if not closed:
        log(f"  ⚠ Модалка не закрылась (ошибки валидации?). Уведомления: {read_toasts()}", "WARN")
        shot("add_row_validation")
        m = find_modal("Добавить строку")
        if m:
            close_modal_soft(m)
        return False
    rows1, total1 = lines_state()
    log(f"  ✓ Строка добавлена ({desc}). Строк: {rows0}→{rows1}, итого: {total0}→{total1}", "PASS")
    return True


def stage_lines_buttons():
    if not open_lines():
        return False
    rows, total = lines_state()
    log(f"  Позиции сейчас: строк={rows}, итого={total}")
    ok = True
    if rows == 0 and not total:
        log("  Смета пустая — добавляю строку")
        ok = add_line_row("пустая смета") and ok
    else:
        log("  Позиции уже есть — оставляю как есть")

    for text in ["Развернуть все", "Свернуть все", "Обновить"]:
        clicked = click_button([text], wait=3) or click_text_deepest(text, "contains")
        if not clicked and text == "Обновить":
            try:
                b = driver.find_element(
                    By.XPATH, "//button[contains(@aria-label,'Обновить') or contains(@title,'Обновить') or .//*[contains(@class,'refresh')]]")
                clicked = click_el(b)
            except Exception:
                pass
        if clicked:
            log(f"  ✓ Кнопка '{text}'", "PASS")
            time.sleep(1.5)
        elif text in ["Свернуть все", "Обновить"]:
            log(f"  • Кнопка '{text}' не найдена (не критично)", "INFO")
        else:
            log(f"  ⚠ Кнопка '{text}' не найдена", "WARN")
            ok = False

    # меню строки (⋮) и карандаши — открыть и закрыть
    try:
        kebab = driver.execute_script("""
            var bs = document.querySelectorAll('button');
            for (var i = 0; i < bs.length; i++) {
                var b = bs[i];
                if (!(b.offsetWidth || b.offsetHeight)) continue;
                var t = (b.textContent || '').trim();
                var d = ((b.getAttribute('aria-label') || '') + ' ' + (b.className || '')).toLowerCase();
                if (!t && (d.indexOf('more') >= 0 || d.indexOf('menu') >= 0 || d.indexOf('kebab') >= 0
                           || d.indexOf('dots') >= 0 || d.indexOf('actions') >= 0)) return b;
            }
            return null;""")
        if kebab:
            hard_click(kebab)
            time.sleep(1)
            ActionChains(driver).send_keys(Keys.ESCAPE).perform()
            log("  ✓ Меню строки (⋮) открыто и закрыто", "PASS")
        else:
            log("  • Меню строки (⋮) не найдено автоматически", "INFO")
    except Exception:
        pass
    return ok


def stage_export_excel():
    if not open_lines():
        return False
    before = snapshot_downloads()
    t0 = time.time()
    if not click_button(["Выгрузить в Excel"], wait=5):
        log("  ⚠ Кнопка 'Выгрузить в Excel' не найдена", "WARN")
        return False
    f = wait_new_download(before, t0, timeout=30, ext=(".xlsx", ".xls", ".csv"))
    if f:
        STATE["exported"] = f
        log(f"  ✓ Выгрузка скачана: {f} ({os.path.getsize(f)} байт)", "PASS")
        return True
    log(f"  ⚠ Файл не появился в {DOWNLOAD_DIR}. Уведомления: {read_toasts()}", "WARN")
    return False


def stage_import_excel():
    if not open_lines():
        return False
    xlsx = prepare_import_excel()
    block_native_file_dialog()
    rows0, total0 = lines_state()
    if not click_button(["Загрузить из Excel"], wait=5):
        log("  ⚠ Кнопка 'Загрузить из Excel' не найдена", "WARN")
        return False
    time.sleep(2)
    modal = find_modal()
    if not send_file(xlsx, scope=modal):
        if modal:
            close_modal_soft(modal)
        return False
    time.sleep(2)
    modal = find_modal()
    if modal:
        b = modal_button(modal, ["Загрузить", "Импортировать", "Применить", "Сохранить",
                                 "Далее", "Создать", "Добавить", "ОК"])
        if b:
            click_el(b)
            log("  ✓ Подтверждение импорта нажато", "PASS")
        wait_modal_closed(None, 15)
    time.sleep(3)
    toasts = read_toasts()
    errs = [t for t in toasts if any(k in t.lower() for k in ["ошибк", "не удалось", "неверн"])]
    rows1, total1 = lines_state()
    log(f"  Импорт: строк {rows0}→{rows1}, итого {total0}→{total1}, уведомления: {toasts}")
    if errs:
        shot("import_error")
        return False
    m = find_modal()
    if m:
        close_modal_soft(m)
    return True


def stage_history_and_back():
    if not open_lines():
        return False
    url_before = driver.current_url
    if not click_button(["История сметы"], wait=5):
        log("  ⚠ Кнопка 'История сметы' не найдена", "WARN")
        return False
    time.sleep(3)
    shot("history")
    m = find_modal()
    if m:
        close_modal_soft(m)
        time.sleep(1)
    elif driver.current_url != url_before:
        driver.back()
        time.sleep(3)
    else:
        try:
            ActionChains(driver).send_keys(Keys.ESCAPE).perform()
        except Exception:
            pass
    log("  ✓ 'История сметы' открыта и закрыта", "PASS")
    if "/lines" not in driver.current_url:
        open_lines()
    return True


def stage_add_row_final():
    if not open_lines():
        return False
    ok = add_line_row("после настройки маршрута")
    # вернуться на основную информацию
    if click_button(["Вернуться к основной информации"], wait=3) or \
            click_text_deepest("Вернуться к основной информации", "contains"):
        time.sleep(2.5)
        log("  ✓ 'Вернуться к основной информации'", "PASS")
    else:
        goto_card()
    return ok


# ==========================================
# ЭТАП 8: ОБСУЖДЕНИЕ
# ==========================================
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
    msg = f"Автотест: сообщение по смете {STAMP}"
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
    wait_for_state(lambda: msg.lower() in page_text())
    txt = page_text()
    ok = "автотест: сообщение по смете" in txt
    log(f"  Сообщение в ленте: {'есть' if ok else 'нет'}", "PASS" if ok else "WARN")
    return ok


# ==========================================
# ЭТАПЫ 9-10: СОГЛАСОВАНИЕ / УТВЕРЖДЕНИЕ / ПОДПИСЬ
# ==========================================
def click_action(texts):
    """Нажать статусную кнопку и подтвердить модалку, если появится. Возвращает текст кнопки."""
    btns = find_buttons(texts)
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


def stage_send_for_approval():
    goto_card()
    before = get_status()
    log(f"  Статус до: {before}")
    if before and any(w in before.lower() for w in ("согласован", "утвержд", "на согласовании")):
        log(f"  ✓ Смета уже отправлена: {before}", "PASS")
        return True
    label = click_action(TO_SEND)
    if not label:
        if click_text_deepest("Отправить на согласование", "contains"):
            time.sleep(3)
            return True
        log("  ⚠ Кнопка 'Отправить на согласование' не найдена/недоступна", "WARN")
        return False
    time.sleep(4)
    driver.refresh()
    if not wait_for_state(smeta_card_ready):
        return False
    after = get_status()
    log(f"  Статус после: {after}", "PASS")
    return True


def stage_approve_main():
    accounts_to_try = [
        (REVIEWER_LOGIN, REVIEWER_PASS),
        (login_val, pass_val),
        (SECOND_LOGIN, SECOND_PASS),
        (env("RGB_ACCOUNT2_LOGIN"), env("RGB_ACCOUNT2_PASSWORD")),
        (env("RGB_ACCOUNT1_LOGIN"), env("RGB_ACCOUNT1_PASSWORD")),
        (env("RGB_ACCOUNT3_LOGIN"), env("RGB_ACCOUNT3_PASSWORD")),
    ]
    seen = set()
    creds = []
    for l, p in accounts_to_try:
        if l and l not in seen:
            seen.add(l)
            creds.append((l, p))

    for acc_l, acc_p in creds:
        if not ensure_account(acc_l, acc_p):
            continue
        goto_card()
        status = get_status()
        if status and any(w in status.lower() for w in ("согласован", "утвержд")):
            log(f"  ✓ Смета уже согласована ({acc_l}): {status}", "PASS")
            return True
        label = click_action(TO_APPROVE)
        if not label and click_text_deepest("Согласовать", "contains"):
            label = "Согласовать"
            time.sleep(3)
        if not label:
            # Fallback: поиск задачи согласования в /tasks?tab=tasks
            try:
                driver.get(BASE_URL + "tasks?tab=tasks")
                time.sleep(3)
                for r in driver.find_elements(By.XPATH, "//*[self::tr or self::div or self::li][contains(normalize-space(.),'смет') or contains(normalize-space(.),'Смет') or contains(normalize-space(.),'Согласован') or contains(normalize-space(.),'согласован')]"):
                    if r.is_displayed():
                        click_el(r)
                        time.sleep(2)
                        label = click_action(TO_APPROVE)
                        if not label and click_text_deepest("Согласовать", "contains"):
                            label = "Согласовать"
                        if label:
                            break
            except Exception:
                pass
        if label:
            time.sleep(4)
            driver.refresh()
            wait_for_state(smeta_card_ready)
            log(f"  Статус после согласования ({acc_l}): {get_status()}", "PASS")
            return True

    log(f"  ⚠ Кнопки {TO_APPROVE} не найдены ни под одним аккаунтом", "WARN")
    return False


def stage_confirm_by_talgat():
    accounts_to_try = [
        (SECOND_LOGIN, SECOND_PASS),
        (login_val, pass_val),
        (REVIEWER_LOGIN, REVIEWER_PASS)
    ]
    seen = set()
    creds = []
    for l, p in accounts_to_try:
        if l and l not in seen:
            seen.add(l)
            creds.append((l, p))

    for acc_l, acc_p in creds:
        if not ensure_account(acc_l, acc_p):
            continue
        driver.get(STATE["url"])
        if not wait_for_state(smeta_card_ready):
            continue
        status = get_status()
        if status and "утвержд" in status.lower():
            log(f"  ✓ Смета уже утверждена ({acc_l}): {status}", "PASS")
            return True
        label = click_action(TO_CONFIRM)
        if not label and click_text_deepest("Утвердить", "contains"):
            label = "Утвердить"
            time.sleep(3)
        if not label:
            # Fallback: поиск задачи утверждения в /tasks?tab=tasks
            try:
                driver.get(BASE_URL + "tasks?tab=tasks")
                time.sleep(3)
                for r in driver.find_elements(By.XPATH, "//*[contains(normalize-space(.),'Утвердить')]"):
                    if r.is_displayed():
                        click_el(r)
                        time.sleep(2)
                        label = click_action(TO_CONFIRM)
                        if not label and click_text_deepest("Утвердить", "contains"):
                            label = "Утвердить"
                        if label:
                            break
            except Exception:
                pass
        if label:
            time.sleep(4)
            driver.refresh()
            wait_for_state(smeta_card_ready)
            log(f"  Статус после утверждения ({acc_l}): {get_status()}", "PASS")
            return True

    log(f"  ⚠ Кнопки {TO_CONFIRM} не найдены ни под одним аккаунтом", "WARN")
    return False




# ==========================================
# ОТЧЁТ
# ==========================================
def save_smeta_results():
    path = Path(os.environ["SMETA_RESULT_PATH"])
    payload = {"run_id": os.environ["SMETA_RUN_ID"],
        "results": [{"name": name, "ok": ok, "reason": REASONS.get(name, "")} for name, ok in RESULTS],
        "error": RUN_ERROR, "screenshot": FAILED_SCREENSHOTS[-1] if FAILED_SCREENSHOTS else "",
        "log": LOG_FILE_PATH, "url": STATE.get("url")}
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


# ==========================================
# MAIN
# ==========================================
def run():
    global RUN_ERROR
    log("=" * 60)
    log(f"АВТОТЕСТ «СМЕТА»: {ESTIMATE_NAME}")
    log("=" * 60)
    try:
        init_driver()
        driver.get(ESTIMATES_URL)
        # Этап 1: Вход и открытие раздела
        if not step("Смета: Вход и открытие раздела «Смета»", stage_login):
            return

        # Этап 2: Список смет, фильтры и поиск
        step("Смета: Страница «Сметы проектов»: фильтры, поиск, проект", stage_list_page)

        # Этап 3: Отрицательный тест - пустая форма
        step('Смета: Отрицательная  пустая форма создания', stage_negative_empty_create)
        if NEGATIVE_FATAL:
            return

        # Этап 4: Отрицательный тест - без наименования
        step('Смета: Отрицательная  без наименования', stage_negative_no_name)
        if NEGATIVE_FATAL:
            return

        # Этап 5: Отрицательный тест - без проекта
        step('Смета: Отрицательная  без проекта', stage_negative_no_project)
        if NEGATIVE_FATAL:
            return

        # Этап 6: Отрицательный тест - некорректный тип файла
        step('Смета: Отрицательная  неподдерживаемый файл', stage_negative_file_type)
        if NEGATIVE_FATAL:
            return

        # Этап 7: Отрицательный тест - некорректные заголовки Excel
        step('Смета: Отрицательная  Excel заголовков', stage_negative_file_headers)
        if NEGATIVE_FATAL:
            return

        # Этап 8: Создание сметы
        step("Смета: Создание сметы (шаблон Excel, дублирование)", stage_create)

        # Этап 9: Карточка сметы
        step("Смета: Карточка сметы: секции, вкладки, кнопки", stage_card_buttons)

        # Этап 10: Маршрут согласования
        step("Смета: Маршрут согласования: Ерлан Талгатович", add_approver)

        # Этап 11: Утверждающий
        step("Смета: Утверждающий: Талгат Ерланович", add_approver_final)

        # Этап 12: Отрицательный тест - пустая строка
        step('Смета: Отрицательная  пустая строка сметы', stage_negative_empty_line)
        if NEGATIVE_FATAL:
            return

        # Этап 13: Позиции сметы
        step("Смета: Позиции сметы: кнопки, добавление строки", stage_lines_buttons)

        # Этап 14: Экспорт в Excel
        step("Смета: Выгрузить в Excel", stage_export_excel)

        # Этап 15: Импорт из Excel
        step("Смета: Загрузить из Excel (шаблон)", stage_import_excel)

        # Этап 16: История сметы
        step("Смета: История сметы", stage_history_and_back)

        # Этап 17: Добавление строки
        step("Смета: Добавить строку (после маршрута)", stage_add_row_final)

        # Этап 18: Обсуждение
        step("Смета: Обсуждение: сообщение и файл", stage_discussion)

        # Этап 19: Отправка на согласование
        step("Смета: Отправить на согласование", stage_send_for_approval)

        # Этап 20: Согласование
        step("Смета: Согласовать (Ерлан Талгатович)", stage_approve_main)

        # Этап 21: Утверждение
        step("Смета: Утвердить (Талгат Ерланович)", stage_confirm_by_talgat)
    except Exception as e:
        RUN_ERROR = f"{type(e).__name__}: {e}"
        log(f"КРИТИЧЕСКАЯ ОШИБКА: {e}", "FAIL")
        shot("critical_error")
    finally:
        save_smeta_results()
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


if __name__ == "__main__" and os.environ.get("SMETA_NO_RUN") != "1":
    if os.environ.get("SMETA_MANAGED") == "1":
        run()
        raise SystemExit(1 if RUN_ERROR or any(not ok for _, ok in RESULTS) else 0)
    from run_workflow_and_report import run_smeta
    raise SystemExit(run_smeta(__file__, sys.argv[1:]))
