# -*- coding: utf-8 -*-
"""
АВТОТЕСТ №4: «WIKI» (/wiki) — только чтение, ничего не создаётся и не добавляется.

  • главная: «Разделов / Папок» (и файлов, если выводятся), сверка со структурой
  • дерево слева: раскрыть все узлы, вывести иерархию, найти дубли и тестовые названия
  • обход: открыть каждый раздел/папку (до 30 страниц, глубина 3), записать счётчики и содержимое,
    найти пустые папки; структура сохраняется в wiki_structure_*.txt и шлётся в Telegram
  • поиск, режимы «Сетка/Список», сортировка ⇅, меню «⋮» плитки и «Создать ▾» — только открыть/закрыть

ОТЧЁТЫ: Telegram («Проверка: Успешно / Неуспешно — причина», блок «Замечания по данным/багам»,
скриншот при ошибках, файлы с данными) и Google Sheets (ваш sheet_reporter.py).

ЗАВИСИМОСТИ: pip install requests pillow pywinauto gspread google-auth
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
import random
import json
import time





import glob
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
    _chrome_options.set_capability("goog:loggingPrefs", {"performance":"ALL"})
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


BASE_URL = "https://testportal.rgbgroup.kz/"
WIKI_URL = BASE_URL + "wiki"
WAIT = 15
STAMP = datetime.now().strftime('%d%m-%H%M%S')+'-'+os.environ.get('WIKI_RUN_ID','local')[:12]
SCRIPT_TITLE = "WIKI (только чтение)"
START_URL = BASE_URL + "wiki"
START_KEY = "wiki"
MENU_PARENT = None

# Люди: основной аккаунт (Sh Margulan Ju) и второй (Ерланович Диас / Диас Ерланович)
P_MAIN = ["margulan", "маргулан"]
P_TALGAT = ['алдажаров', 'диас']
TERMINAL = ("исполнено", "закрыт", "выполнено", "завершен", "завершён", "подтверждено", "подписан")

DOWNLOAD_DIR = os.environ.get("DOWNLOAD_DIR", os.path.join(os.path.expanduser("~"), "Downloads"))
WORK_DIR = os.path.join(tempfile.gettempdir(), f"wiki_autotest_{STAMP}")
os.makedirs(WORK_DIR, exist_ok=True)

# ---- Telegram (как в run_workflow_and_report.py) ----
# ВАЖНО: токен секретный. Не выкладывайте файл в публичный репозиторий/общий чат.
# Можно не хранить в файле: задайте переменную окружения TG_TOKEN.
APPROVER_QUERY = "Margulan"

# ---- Google Sheets («Чек-лист») через ваш sheet_reporter.py ----
# Названия проверок = названия этапов. Если их нет в таблице — просто не запишутся.

STATE = {"url": None, "summary": [], "records": {}, "attachments": []}
RESULTS = []        # (название, ok)
REASONS = {}        # название -> причина провала
LOG_LINES = []
_RUN_STARTED = time.time()

LOG_FILE_PATH = log_path(f'wiki_log_{STAMP}.txt')
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
        path = screen_path(f"debug_wiki_{safe}_{os.environ.get('WIKI_RUN_ID', STAMP)}_{time.time_ns()}.png")
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

def control_by_label(scope, label):
    for xp in [
        f".//*[normalize-space(text())='{label}']/following::button[contains(@class,'ui-select__trigger')][1]",
        f".//*[normalize-space(text())='{label}']/following::*[@role='combobox' or @aria-haspopup][1]",
        f".//*[normalize-space(text())='{label}']/following::button[1]",
        f".//*[starts-with(normalize-space(text()),'{label}') and string-length(normalize-space(text()))<{len(label)+4}]/following::button[contains(@class,'ui-select__trigger')][1]",
        f".//*[starts-with(normalize-space(text()),'{label}') and string-length(normalize-space(text()))<{len(label)+4}]/following::*[@role='combobox' or @aria-haspopup][1]",
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
        time.sleep(0.8)
        p = visible_panel()
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
            wait_idle(5, .5)
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
        time.sleep(0.8)
        if visible_panel() is None:
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
        wait_idle(5, .5)
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
    wait_for_state(lambda:driver.current_url.startswith(BASE_URL) and not is_login_page())
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
            wait_idle(5, .5)
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
    picked = select_in_panel(panel, keywords=["margulan", "маргулан"],
                             search=APPROVER_QUERY, exclude=["aisinov"])
    if not picked:
        log(f"  ⚠ '{APPROVER_QUERY}' не найден в списке", "WARN")
        close_panels()
        return False
    log(f"  ✓ Согласующий выбран: {picked}", "PASS")
    wait_idle(5, .5)

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
    log("  ⚠ Sh Margulan не появился в маршруте", "WARN")
    return False

def try_open_and_cancel(text):
    goto_card()
    if not click_button([text], wait=5):
        log(f"  ⚠ Кнопка '{text}' не найдена", "WARN")
        return False
    wait_idle(5, .5)
    m = find_modal()
    if m:
        close_modal_soft(m)
        time.sleep(1)
    elif "/edit" in driver.current_url or STATE["url"] not in driver.current_url:
        if not click_button(["Отмена"], wait=2):
            driver.get(STATE["url"])
            wait_idle(5, .5)
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
    click_el(btns[0])
    wait_idle(5, .5)
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
            wait_idle(5, .5)
    return label

def stage_discussion():
    goto_card()
    click_text_deepest("Обсуждение", "exact")
    wait_idle(5, .5)
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
    msg = f"Автотест: сообщение по контролю качества {STAMP}"
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
    wait_idle(5, .5)
    if not click_button(["Отправить"], wait=3, last=True):
        log("  ⚠ Кнопка 'Отправить' не найдена", "WARN")
        return False
    wait_idle(5, .5)
    txt = page_text()
    ok = "автотест: сообщение по контролю качества" in txt.lower()
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
                         'Проверка исполнения','Принято','Завершено','Ожидает'];
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


def nav_menu(item, url):
    """Пункт меню; если по меню не вышло — прямой URL."""
    for _ in range(2):
        if click_text_deepest(item, "exact"):
            wait_idle(5, .5)
            if at_url(url):
                return True
        if MENU_PARENT:
            click_text_deepest(MENU_PARENT, "exact")
            time.sleep(1)
    driver.get(url)
    wait_idle(5, .5)
    return at_url(url)


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
    url = STATE["url"]
    if not url:
        return False
    if not at_url(url):
        driver.get(url)
        wait_idle(5, .5)
    return True


def open_lines():
    if "/lines" in driver.current_url:
        block_native_file_dialog()
        return True
    goto_card()
    if click_button(["Позиции заявки", "Позиции заказа"], wait=8) or \
            click_text_deepest("Позиции з", "prefix"):
        for _ in range(10):
            if "/lines" in driver.current_url:
                wait_idle(5, .5)
                block_native_file_dialog()
                return True
            time.sleep(1)
    driver.get(STATE["url"].rstrip("/") + "/lines")
    wait_idle(5, .5)
    block_native_file_dialog()
    return "/lines" in driver.current_url


def back_to_card():
    if click_button(["Вернуться к основной информации"], wait=3) or \
            click_text_deepest("Вернуться к основной информации", "contains"):
        wait_idle(5, .5)
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
        for _ in range(6):
            time.sleep(0.3)
            if popup_is_open(ctrl):
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
    time.sleep(0.5)
    if popup_is_open(ctrl):
        close_panels()
    time.sleep(0.3)


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
            wait_idle(5, .5)
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
                wait_idle(5, .5)
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
        time.sleep(0.6)
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
        wait_idle(5, .5)
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


def switch_user(login, password):
    if not logout_current_account():
        driver.get(BASE_URL)
        wait_idle(5, .5)
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
        wait_idle(5, .5)
        p2 = pager_text()
        log(f"  ✓ Следующая страница: {p2}", "PASS" if p2 and p2[0] == 2 else "WARN")
        driver.execute_script("arguments[0].click();", prev)
        wait_idle(5, .5)
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
                wait_idle(5, .5)
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
        wait_idle(5, .5)
        shot("list_sort_menu")
        log("  ✓ Кнопка сортировки (⇅) нажата — меню открыто и закрыто", "PASS")
        esc()
    else:
        log("  • Кнопка сортировки не найдена", "WARN")
    if click_button(["Настройки таблицы"], wait=4):
        wait_idle(5, .5)
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
        wait_idle(5, .5)
        if got:
            worked += 1
            log(f"    → выбрано «{got}», всего записей: {page_total()}", "PASS")
        click_text_deepest("Сбросить фильтры", "contains")
        wait_idle(5, .5)
    log(f"  После сброса всего записей: {page_total()} (было {total0})",
        "PASS" if page_total() == total0 else "WARN")
    if check_box:
        if click_text_deepest(check_box, "contains"):
            wait_idle(5, .5)
            log(f"  ✓ «{check_box}»: включён, всего записей {page_total()}", "PASS")
            click_text_deepest(check_box, "contains")
            wait_idle(5, .5)
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
        wait_idle(5, .5)
        log(f"  Поиск «{search_term}»: всего записей {page_total()}", "PASS")
        try:
            inp.send_keys(Keys.CONTROL, "a")
            inp.send_keys(Keys.BACKSPACE)
        except Exception:
            pass
        set_native_value(inp, "")
        wait_idle(5, .5)
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
    wait_idle(5, .5)
    ok = not at_url(back_url)
    log(f"  {'✓' if ok else '⚠'} Открыта запись {code}: {driver.current_url}", "PASS" if ok else "WARN")
    for tab in ["Обсуждение", "Приёмки", "Передачи", "История"]:
        if click_text_deepest(tab, "exact"):
            log(f"    ✓ Вкладка «{tab}»", "PASS")
            time.sleep(1)
    driver.get(back_url)
    wait_idle(5, .5)
    return ok


# ==========================================
# ОБЩИЕ ИНСТРУМЕНТЫ ПРОВЕРКИ (данные, баги, отчёты)
# ==========================================
FINDINGS = []      # найденные замечания/баги: (где, что)

BAD_PATTERNS = [
    (r"\bNaN\b", "значение NaN"),
    (r"\bundefined\b", "текст «undefined»"),
    (r"\[object Object\]", "«[object Object]»"),
    (r"Invalid Date", "«Invalid Date»"),
    (r"\{\{[^}]*\}\}", "неподставленный шаблон {{…}}"),
    (r"(?<![\w.])null(?![\w.])", "текст «null»"),
    (r"Internal Server Error|Bad Gateway|Service Unavailable", "ошибка сервера"),
    (r"Страница не найдена|Page not found|404 Not Found", "страница не найдена"),
    (r"Не удалось загрузить|Ошибка загрузки|Something went wrong|Что-то пошло не так", "ошибка загрузки"),
    (r"-\d+\s*[₸%]|[₸]\s*-\d", "отрицательная сумма/процент"),
]


def finding(where, what):
    item = (where, what)
    if item not in FINDINGS:
        FINDINGS.append(item)
    log(f"  🐞 [{where}] {what}", "WARN")


JS_MAIN_TEXT = r"""
// innerText у ЖИВОГО DOM (у клона нет переносов строк) минус строки бокового меню
var side = {};
document.querySelectorAll('aside, nav, [class*="sidebar"], [class*="Sidebar"]').forEach(function(e){
    (e.innerText || '').split('\n').forEach(function(l){ l = l.trim(); if (l) side[l] = (side[l] || 0) + 1; });
});
var out = [];
(document.body.innerText || '').split('\n').forEach(function(l){
    var t = l.trim();
    if (side[t] > 0) { side[t]--; return; }
    out.push(l);
});
return out.join('\n');
"""


def main_text():
    try:
        return driver.execute_script(JS_MAIN_TEXT) or ""
    except Exception:
        return innertext()


def scan_bugs(where, text=None):
    t = text if text is not None else main_text()
    bad = []
    for rx, name in BAD_PATTERNS:
        m = re.search(rx, t)
        if m:
            bad.append(name)
            finding(where, f"{name}: …{t[max(0, m.start() - 25): m.end() + 25]!r}…".replace("\n", " "))
    return bad


JS_BROKEN_IMG = r"""
function vis(e){ return !!(e.offsetWidth || e.offsetHeight || e.getClientRects().length); }
var bad = [];
document.querySelectorAll('img').forEach(function(i){
    if (!vis(i)) return;
    if (i.complete && i.naturalWidth === 0) bad.push((i.currentSrc || i.src || '').slice(0, 90));
});
return bad;
"""


def broken_images(where):
    try:
        bad = driver.execute_script(JS_BROKEN_IMG) or []
    except Exception:
        bad = []
    for b in bad[:5]:
        finding(where, f"картинка не загрузилась: {b}")
    return bad


_CONSOLE_SEEN = set()


def console_errors(where):
    out = []
    try:
        for e in driver.get_log("browser"):
            if e.get("level") == "SEVERE":
                raw = (e.get("message") or "")
                st = re.search(r"status of (\d+)\s*(\([^)]*\))?", raw)
                um = re.search(r"https?://\S+", raw)
                if st and um:
                    path = re.sub(r"https?://[^/]+", "", um.group(0)).rstrip(" -")
                    msg = f"HTTP {st.group(1)} {st.group(2) or ''} {path}".replace("  ", " ")
                else:
                    msg = raw[:200]
                if msg not in _CONSOLE_SEEN:
                    _CONSOLE_SEEN.add(msg)
                    out.append(msg)
    except Exception:
        return []
    for m in out[:5]:
        finding(where, f"ошибка в консоли браузера: {m}")
    return out


def page_health(where):
    """Текстовые баги + битые картинки + ошибки консоли. True — всё чисто."""
    a = scan_bugs(where)
    b = broken_images(where)
    c = console_errors(where)
    ok = not (a or b)
    log(f"  {'✓' if ok else '⚠'} Проверка страницы «{where}»: "
        f"{'ошибок в данных нет' if ok else 'найдены замечания'}"
        f"{'; в консоли ошибок: ' + str(len(c)) if c else ''}", "PASS" if ok else "WARN")
    return ok


def wait_idle(timeout=8, settle=1.2):
    """Ждём, пока страница перестанет меняться и исчезнут «Загрузка…»/спиннеры."""
    end = time.time() + timeout
    last, stable = None, 0
    while time.time() < end:
        try:
            cur = driver.execute_script("""
                var t = document.body.innerText.length;
                var sp = document.querySelectorAll('[class*="spinner"], [class*="skeleton"], [class*="loading"], [aria-busy="true"]');
                var n = 0; sp.forEach(function(e){ if (e.offsetWidth || e.offsetHeight) n++; });
                return t + ':' + n;""")
        except Exception:
            cur = None
        if cur == last and cur and cur.endswith(":0"):
            stable += 1
            if stable * 0.5 >= settle:
                return True
        else:
            stable = 0
        last = cur
        time.sleep(0.5)
    return False


JS_SCROLL_ALL = r"""
var els = document.querySelectorAll('*'), n = 0;
for (var i = 0; i < els.length; i++) {
    var e = els[i];
    if (e.scrollHeight > e.clientHeight + 40) {
        var cs = getComputedStyle(e);
        if (/(auto|scroll)/.test(cs.overflowY)) { e.scrollTop = e.scrollHeight; n++; }
    }
}
window.scrollTo(0, document.body.scrollHeight);
return n;
"""
JS_SCROLL_TOP = r"""
document.querySelectorAll('*').forEach(function(e){ if (e.scrollTop) e.scrollTop = 0; });
window.scrollTo(0, 0);
"""


def scroll_all():
    for _ in range(3):
        try:
            driver.execute_script(JS_SCROLL_ALL)
        except Exception:
            pass
        time.sleep(0.8)
    try:
        driver.execute_script(JS_SCROLL_TOP)
    except Exception:
        pass


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


JS_CLICK_CHIP = r"""
var t = arguments[0];
function vis(e){ return !!(e.offsetWidth || e.offsetHeight || e.getClientRects().length); }
var cands = Array.prototype.filter.call(document.querySelectorAll('button, [role=tab], a, [role=button]'), function(b){
    if (!vis(b)) return false;
    if ((b.innerText || '').trim().replace(/\s+/g, ' ') !== t) return false;
    if (b.closest('aside, nav, [class*="sidebar"], [class*="Sidebar"]')) return false;
    return true; });
return cands.length ? cands[0] : null;
"""


def click_chip(name):
    """Кнопка-вкладка в основной части страницы (не в левом меню)."""
    try:
        el = driver.execute_script(JS_CLICK_CHIP, name)
    except Exception:
        el = None
    if el is None:
        return False
    click_el(el)
    time.sleep(1.0)
    return True


def chip_active(name):
    try:
        return bool(driver.execute_script("""
            var t = arguments[0];
            var b = Array.prototype.filter.call(document.querySelectorAll('button, [role=tab]'), function(x){
                return (x.innerText || '').trim() === t && !x.closest('aside, nav'); })[0];
            if (!b) return false;
            var cs = getComputedStyle(b);
            var cls = (b.className || '').toString().toLowerCase();
            return b.getAttribute('aria-selected') === 'true' || /active|selected|current/.test(cls) ||
                   b.getAttribute('data-state') === 'active' || b.getAttribute('data-state') === 'on' ||
                   (cs.backgroundColor && cs.backgroundColor !== 'rgba(0, 0, 0, 0)' && cs.backgroundColor !== 'rgb(255, 255, 255)');""", name))
    except Exception:
        return False


def search_box():
    for e in driver.find_elements(By.XPATH, "//input[contains(@placeholder,'Поиск') or contains(@placeholder,'поиск')]"):
        if e.is_displayed():
            return e
    return None


def do_search(text):
    inp = search_box()
    if inp is None:
        return False
    type_text(inp, text)
    wait_idle(5, .5)
    wait_idle(5, 0.8)
    return True


def clear_search():
    inp = search_box()
    if inp is None:
        return
    try:
        inp.send_keys(Keys.CONTROL, "a")
        inp.send_keys(Keys.BACKSPACE)
    except Exception:
        pass
    set_native_value(inp, "")
    wait_idle(5, .5)
    wait_idle(5, 0.8)


JS_ICON_BTNS = r"""
function vis(e){ return !!(e.offsetWidth || e.offsetHeight || e.getClientRects().length); }
return Array.prototype.filter.call(document.querySelectorAll('button, [role=button]'), function(b){
    if (!vis(b) || b.closest('aside, nav, [class*="sidebar"], [class*="Sidebar"]')) return false;
    var r = b.getBoundingClientRect();
    return !(b.innerText || '').trim() && r.top > 120 && r.top < 420 && r.width < 80;
});
"""


def click_sort_icon():
    """Кнопка сортировки ⇅ (без текста, в строке фильтров)."""
    try:
        bs = driver.execute_script(JS_ICON_BTNS) or []
    except Exception:
        bs = []
    if not bs:
        return False
    bs.sort(key=lambda b: -b.location["x"])
    hard_click(bs[0])
    time.sleep(1.0)
    return True


JS_STAT_TABLE = r"""
function vis(e){ return !!(e.offsetWidth || e.offsetHeight || e.getClientRects().length); }
var out = [];
document.querySelectorAll('table').forEach(function(t){
    if (!vis(t)) return;
    var head = Array.prototype.map.call(t.querySelectorAll('thead th, tr:first-child th'), function(x){ return x.innerText.trim(); });
    out.push({head: head, rows: t.querySelectorAll('tbody tr').length});
});
return out;
"""


def new_check(label):
    log(f"  → {label}")


# ---------- генерация изображений (не просто заливка цветом) ----------
def _noise_png(path, w=1200, h=675):
    """Запасной вариант без Pillow: диагональный градиент с волнами, чистый Python."""
    import zlib
    import struct
    import math
    rnd = random.Random(STAMP)
    p1, p2, p3 = rnd.random() * 6, rnd.random() * 6, rnd.random() * 6
    raw = bytearray()
    for y in range(h):
        raw.append(0)
        for x in range(w):
            v = math.sin(x / 90 + p1) + math.sin(y / 70 + p2) + math.sin((x + y) / 140 + p3)
            r = int(120 + 100 * math.sin(v + 0.0))
            g = int(110 + 100 * math.sin(v + 2.1))
            b = int(150 + 90 * math.sin(v + 4.2))
            raw += bytes((max(0, min(255, r)), max(0, min(255, g)), max(0, min(255, b))))

    def chunk(tag, data):
        c = struct.pack(">I", len(data)) + tag + data
        return c + struct.pack(">I", zlib.crc32(tag + data) & 0xffffffff)
    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) + \
        chunk(b"IDAT", zlib.compress(bytes(raw), 6)) + chunk(b"IEND", b"")
    with open(path, "wb") as f:
        f.write(png)
    return path


def generate_image(name="cover", kind="city", w=1600, h=900):
    """Сгенерировать настоящую картинку (а не однотонный фон).
    kind='city'  — вечерний город: небо-градиент, солнце со свечением, горы, силуэты зданий с окнами, звёзды.
    kind='art'   — абстракция: полупрозрачные круги/дуги на градиенте.
    Нужен Pillow (pip install pillow); без него — волновой градиент на чистом Python."""
    path = os.path.join(WORK_DIR, f"{name}_{STAMP}.jpg")
    try:
        from PIL import Image, ImageDraw, ImageFilter, ImageFont
    except Exception:
        log("  • Pillow не установлен — картинка строится запасным способом (pip install pillow)", "WARN")
        return _noise_png(os.path.join(WORK_DIR, f"{name}_{STAMP}.png"), 1200, 675)
    rnd = random.Random(f"{STAMP}-{name}")
    img = Image.new("RGB", (w, h))
    px = ImageDraw.Draw(img)
    c_top, c_bot = ((18, 24, 66), (255, 140, 90)) if kind == "city" else \
        ((rnd.randint(10, 90), rnd.randint(10, 90), rnd.randint(90, 200)),
         (rnd.randint(150, 255), rnd.randint(60, 200), rnd.randint(60, 200)))
    for y in range(h):
        t = y / (h - 1)
        px.line([(0, y), (w, y)], fill=tuple(int(c_top[i] + (c_bot[i] - c_top[i]) * t) for i in range(3)))
    if kind == "city":
        for _ in range(160):                                  # звёзды в верхней трети
            x, y = rnd.randint(0, w), rnd.randint(0, int(h * 0.38))
            r = rnd.choice([1, 1, 2])
            px.ellipse([x - r, y - r, x + r, y + r], fill=(255, 255, 235))
        glow = Image.new("RGB", (w, h), (0, 0, 0))             # солнце + свечение
        gd = ImageDraw.Draw(glow)
        cx, cy = int(w * 0.72), int(h * 0.58)
        gd.ellipse([cx - 230, cy - 230, cx + 230, cy + 230], fill=(255, 170, 90))
        glow = glow.filter(ImageFilter.GaussianBlur(70))
        img = Image.blend(img, Image.composite(glow, img, glow.convert("L")), 0.7)
        px = ImageDraw.Draw(img)
        px.ellipse([cx - 95, cy - 95, cx + 95, cy + 95], fill=(255, 236, 190))
        for layer, (base, col) in enumerate([(0.66, (58, 46, 92)), (0.74, (40, 32, 70)), (0.82, (26, 22, 52))]):
            pts, x = [(0, h)], 0
            ph = rnd.random() * 6
            while x <= w + 40:
                import math as _m
                y = int(h * base - 80 * _m.sin(x / (210 - 40 * layer) + ph) - rnd.randint(0, 14))
                pts.append((x, y))
                x += 40
            pts.append((w, h))
            px.polygon(pts, fill=col)
        x = 0
        while x < w:                                             # силуэты зданий + светящиеся окна
            bw, bh = rnd.randint(70, 150), rnd.randint(150, 460)
            top = h - bh
            px.rectangle([x, top, x + bw, h], fill=(14, 14, 30))
            for wy in range(top + 18, h - 18, 30):
                for wx in range(x + 12, x + bw - 14, 22):
                    if rnd.random() < 0.42:
                        px.rectangle([wx, wy, wx + 9, wy + 14], fill=rnd.choice([(255, 214, 120), (255, 236, 170), (150, 200, 255)]))
            x += bw + rnd.randint(2, 14)
    else:
        ov = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        od = ImageDraw.Draw(ov)
        for _ in range(38):
            r = rnd.randint(40, 260)
            x, y = rnd.randint(-50, w + 50), rnd.randint(-50, h + 50)
            col = (rnd.randint(40, 255), rnd.randint(40, 255), rnd.randint(40, 255), rnd.randint(40, 120))
            if rnd.random() < 0.5:
                od.ellipse([x - r, y - r, x + r, y + r], fill=col)
            else:
                od.arc([x - r, y - r, x + r, y + r], rnd.randint(0, 180), rnd.randint(181, 360), fill=col, width=rnd.randint(6, 28))
        img = Image.alpha_composite(img.convert("RGBA"), ov.filter(ImageFilter.GaussianBlur(2))).convert("RGB")
    d2 = ImageDraw.Draw(img)
    font = None
    for fp in ["arial.ttf", "DejaVuSans-Bold.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
               "C:\\Windows\\Fonts\\arialbd.ttf"]:
        try:
            font = ImageFont.truetype(fp, 54)
            break
        except Exception:
            continue
    d2.text((48, 40), f"RGB Group · Автотест {STAMP}", fill=(255, 255, 255), font=font or ImageFont.load_default())
    img.save(path, "JPEG", quality=90)
    log(f"    ✓ Сгенерировано изображение ({kind}, {w}x{h}): {os.path.basename(path)}", "PASS")
    return path


# ---------- отчёты ----------






def dump_file(name, text):
    p = os.path.join(WORK_DIR, f"{name}_{STAMP}.txt")
    try:
        with open(p, "w", encoding="utf-8") as f:
            f.write(text)
        STATE.setdefault("attachments", []).append(p)
    except Exception as e:
        log(f"  ⚠ Не удалось сохранить {name}: {e}", "WARN")
    return p


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


# ==========================================
# WIKI (только чтение: структура, счётчики, файлы; ничего не создаём)
# ==========================================
WIKI_TREE = []       # (уровень, название)
WIKI_PAGES = {}      # путь -> {"sections": n, "folders": m, "files": k, "items": [...]}

JS_WK_CARDS = r"""
return Array.prototype.map.call(document.querySelectorAll('.wk-content-panel .wk-card'), function(c){
    var m = (c.className.match(/wk-card--(folder|base|file|section|doc\w*)\b/) || [])[1] || 'other';
    var ti = c.querySelector('.wk-card__title');
    var txt = (c.innerText || '').split('\n').map(function(x){ return x.trim(); }).filter(Boolean);
    return {kind: m, title: ti ? ti.innerText.trim() : (txt[0] || ''), text: txt.join(' | ')};
});
"""

JS_WK_CRUMBS = r"""
return Array.prototype.map.call(document.querySelectorAll('.wk-breadcrumbs__item'), function(e){ return (e.innerText || '').trim(); });
"""

KIND_RU = {"base": "раздел", "folder": "папка", "file": "файл"}






def wiki_cards():
    try:
        return driver.execute_script(JS_WK_CARDS) or []
    except Exception:
        return []


def wiki_title():
    try:
        return driver.execute_script(
            "var e = document.querySelector('.wk-content-header__title'); return e ? e.innerText.trim() : '';") or ""
    except Exception:
        return ""


def stage_wiki_open():
    ok = wiki_open()
    sec, fol, fil, doc = read_counters()
    cards = wiki_cards()
    log(f"  Главная: Разделов {sec}, Папок {fol}, Файлов {fil}; карточек на экране {len(cards)}: "
        f"{[(c['kind'], c['title']) for c in cards]}")
    STATE["summary"].append(f"WIKI, главная: разделов {sec}, папок {fol}, файлов {fil}")
    if not driver.find_elements(By.CSS_SELECTOR, ".wk-content-header__counts"):
        finding("WIKI", "на главной не найдены счётчики «Разделов/Папок»")
        ok = False
    n_sec = sum(1 for c in cards if c["kind"] == "base")
    n_fol = sum(1 for c in cards if c["kind"] == "folder")
    n_fil = sum(1 for c in cards if c["kind"] == "file")
    if (n_sec, n_fol, n_fil) != (sec, fol, fil):
        finding("WIKI", f"счётчики главной (разделов {sec}, папок {fol}, файлов {fil}) не совпадают с карточками "
                        f"({n_sec}/{n_fol}/{n_fil})")
    txt = main_text()
    for need in ["WIKI", "Создать"]:
        if need not in txt:
            finding("WIKI", f"на странице нет «{need}»")
    shot("wiki_home")
    return page_health("WIKI/главная") and ok


JS_TREE_COLLECT = r"""
function lvl(n){ var d = 0, p = n; while ((p = p.parentElement && p.parentElement.closest('.wk-tree__node'))) d++; return d; }
return Array.prototype.map.call(document.querySelectorAll('.wk-tree__node'), function(n){
    var l = n.querySelector('.wk-tree__label');
    return [lvl(n), l ? l.innerText.trim() : '', n.classList.contains('wk-tree__node--leaf') ? 1 : 0];
});
"""


def expand_tree(max_clicks=60):
    n = 0
    for _ in range(max_clicks):
        tg = driver.find_elements(By.CSS_SELECTOR, ".wk-tree__toggle[aria-expanded='false']")
        tg = [t for t in tg if t.is_displayed()]
        if not tg:
            break
        hard_click(tg[0])
        time.sleep(0.6)
        n += 1
    return n




def wiki_crumbs():
    try:
        return driver.execute_script(JS_WK_CRUMBS) or []
    except Exception:
        return []






def inspect_level(path, depth, budget):
    """Прочитать текущую страницу, затем открыть каждый раздел/папку (файлы НЕ открываем), вернуться."""
    sec, fol, fil, doc = read_counters()
    cards = wiki_cards()
    n_sec = sum(1 for c in cards if c["kind"] == "base")
    n_fol = sum(1 for c in cards if c["kind"] == "folder")
    n_fil = sum(1 for c in cards if c["kind"] == "file")
    WIKI_PAGES[path] = {"sections": sec, "folders": fol, "files": fil,
                        "items": [(c["kind"], c["title"]) for c in cards]}
    where = path or "Главная"
    log(f"  [{where}] разделов {sec}, папок {fol}, файлов {fil}; карточек: "
        f"{[(KIND_RU.get(c['kind'], c['kind']), c['title']) for c in cards]}")
    if (n_sec, n_fol, n_fil) != (sec, fol, fil):
        finding("WIKI", f"«{where}»: счётчики (разделов {sec}, папок {fol}, файлов {fil}) ≠ карточки ({n_sec}/{n_fol}/{n_fil})")
    for c in cards:
        if c["kind"] == "file":
            if not c["title"] or len(c["title"]) < 2:
                finding("WIKI", f"«{where}»: файл без названия: {c['text'][:60]}")
            if re.fullmatch(r"[\W\d_]{0,3}|[a-zа-я]{1,4}", c["title"].strip().lower()) and len(c["title"].strip()) <= 4:
                finding("WIKI", f"«{where}»: подозрительное название файла «{c['title']}»")
            if "опубликовано" not in c["text"].lower() and "черновик" not in c["text"].lower():
                log(f"    · у файла «{c['title']}» нет статуса: {c['text'][:80]}")
    if depth >= 4:
        return
    for i, c in enumerate(cards):
        if c["kind"] not in ("base", "folder"):
            continue
        if budget[0] <= 0:
            return
        budget[0] -= 1
        if not wiki_open_card(i):
            continue
        sub = f"{path}/{c['title']}" if path else c["title"]
        crumbs = wiki_crumbs()
        log(f"    → открыто «{c['title']}» ({KIND_RU[c['kind']]}); путь: {' > '.join(crumbs)}")
        if wiki_title() != c["title"]:
            finding("WIKI", f"открыта «{c['title']}», а заголовок страницы «{wiki_title()}»")
        page_health(f"WIKI/{sub}")
        inspect_level(sub, depth + 1, budget)
        wiki_go_up()
        if wiki_title() != (path.split("/")[-1] if path else "Главная"):
            # не вернулись — открыть заново и дойти до нужного уровня
            wiki_open()
            for part in path.split("/") if path else []:
                for j, cc in enumerate(wiki_cards()):
                    if cc["title"] == part:
                        wiki_open_card(j)
                        break




def stage_wiki_controls():
    wiki_open()
    ok = True
    # режимы просмотра
    for name in ["Список", "Сетка"]:
        bs = driver.find_elements(By.CSS_SELECTOR, f".wk-view-toggle__trigger[aria-label='{name}']")
        if bs:
            hard_click(bs[0])
            wait_idle(5, .5)
            cnt = len(wiki_cards())
            log(f"  ✓ Режим «{name}»: переключён; карточек {cnt}", "PASS")
            if cnt != len(wiki_cards()) or cnt == 0:
                finding("WIKI", f"в режиме «{name}» не видно карточек")
            page_health(f"WIKI/режим {name}")
            shot(f"wiki_view_{name}")
        else:
            log(f"  • Переключатель «{name}» не найден")
    # сортировка: открыть меню и закрыть
    sb = driver.find_elements(By.CSS_SELECTOR, ".wk-sort-button")
    if sb:
        hard_click(sb[0])
        time.sleep(0.8)
        log(f"  ✓ Сортировка открыта: aria-expanded={sb[0].get_attribute('aria-expanded')}", "PASS")
        shot("wiki_sort")
        esc()
    else:
        log("  ⚠ Кнопка сортировки не найдена", "WARN")
    # поиск по дереву
    inp = driver.find_elements(By.CSS_SELECTOR, "input.wk-search__input")
    if inp:
        before = len(driver.find_elements(By.CSS_SELECTOR, ".wk-tree__node"))
        type_text(inp[0], "акт")
        wait_idle(5, .5)
        after = [e.text for e in driver.find_elements(By.CSS_SELECTOR, ".wk-tree__label") if e.is_displayed()]
        res = main_text()
        log(f"  ✓ Поиск «акт»: узлов дерева было {before}, после {len(after)}: {after[:6]}", "PASS")
        page_health("WIKI/поиск")
        type_text(inp[0], "zzzqqq-нет-такого")
        wait_idle(5, .5)
        log(f"  Поиск несуществующего: узлов {len(driver.find_elements(By.CSS_SELECTOR, '.wk-tree__label'))}")
        type_text(inp[0], "")
        time.sleep(1)
    else:
        log("  ⚠ Поле поиска не найдено", "WARN")
        ok = False
    # меню «⋮» первой карточки: открыть и закрыть
    wiki_open()
    kb = [k for k in driver.find_elements(By.CSS_SELECTOR, ".wk-card__more") if k.is_displayed()]
    if kb:
        hard_click(kb[0])
        time.sleep(1)
        items = driver.execute_script("""
            return Array.prototype.map.call(document.querySelectorAll('[role=menu] [role=menuitem], [role=menu] button'),
                function(e){ return (e.innerText || '').trim(); }).filter(Boolean);""") or []
        log(f"  ✓ Меню «⋮» карточки открыто (пункты НЕ нажимаются): {items}", "PASS")
        shot("wiki_card_menu")
        esc()
    # «Создать ▾» — только раскрыть
    tg = driver.find_elements(By.CSS_SELECTOR, ".wk-split-button__toggle")
    if tg:
        hard_click(tg[0])
        time.sleep(1)
        items = driver.execute_script("""
            return Array.prototype.map.call(document.querySelectorAll('[role=menu] [role=menuitem], [role=menu] button'),
                function(e){ return (e.innerText || '').trim(); }).filter(Boolean);""") or []
        log(f"  ✓ Список «Создать ▾» раскрыт (создание НЕ выполняется): {items}", "PASS")
        shot("wiki_create_menu")
        esc()
        m = find_modal()
        if m is not None:
            close_modal_soft(m)
    wiki_open()
    return ok






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


WIKI_CHECKS = [
 'Вход и открытие раздела «WIKI»',
 'WIKI: главная — счётчики и карточки',
 'WIKI: дерево — раскрытие, иерархия и названия',
 'WIKI: обход разделов и папок, путь и возврат',
 'WIKI: счётчики на посещённых уровнях',
 'WIKI: снимок структуры, файлов и пустых ветвей',
 'WIKI: режимы «Список» и «Сетка» сохраняют содержимое',
 'WIKI: поиск существующего файла и очистка',
 'WIKI: поиск без результатов и восстановление списка',
 'WIKI: открытие и закрытие меню сортировки',
 'WIKI: меню карточки и «Создать» без изменения данных',
]
CURRENT_LOGIN = None
RUN_ERROR = ''
FAILED_SCREENSHOTS = []
WIKI_NAV_ERRORS = []
WIKI_COUNT_ERRORS = []
WIKI_META_ERRORS = []
WIKI_LIMIT_REACHED = False
WIKI_SNAPSHOT_PATH = ''


JS_WK_CARDS = r'''
const cards=Array.from(document.querySelectorAll('.wk-content-panel .wk-card')).filter(c=>c.offsetWidth||c.offsetHeight);
if(!cards.length)return Array.from(document.querySelectorAll('.wk-content-panel .wk-table__row:not(.wk-table__row--head)')).filter(c=>c.offsetWidth||c.offsetHeight).map(c=>({kind:(c.querySelector('.wk-table__kind')?.className.match(/wk-table__kind--(folder|base|file|section|doc\w*)\b/)||[])[1]||'other',title:(c.querySelector('.wk-table__name')?.innerText||'').trim(),text:c.innerText.trim(),status:'',date:''}));
return cards.map(c=>{
 const kind=(c.className.match(/wk-card--(folder|base|file|section|doc\w*)\b/)||[])[1]||'other';
 const title=c.querySelector('.wk-card__title,.wk-card__name');
 return {kind,title:title?(title.innerText||'').trim():'',text:c.innerText.trim(),
    status:(c.querySelector('.wk-badge')?.innerText||'').trim(),
    date:(c.querySelector('.wk-card__date')?.innerText||'').trim()};
});'''


def wiki_settled(timeout=WAIT):
    deadline=time.monotonic()+timeout
    last=None;since=None
    while time.monotonic()<deadline:
        state=driver.execute_script('''const p=document.querySelector('.wk-content-panel');
            if(!p||!p.querySelector('.wk-content-header__title'))return null;
            if(/Загрузка[.…]/i.test(p.innerText)||Array.from(p.querySelectorAll('[aria-busy=true],[role=progressbar]')).some(e=>e.offsetWidth))return null;
            return [p.querySelector('.wk-content-header__title').innerText,p.querySelector('.wk-content-header__counts')?.innerText||'',
              Array.from(p.querySelectorAll('.wk-card,.wk-table__row:not(.wk-table__row--head)')).map(e=>e.innerText).join('|')].join('::');''')
        if state and state==last:
            if time.monotonic()-since>=.8:return True
        else:last=state;since=time.monotonic()
        time.sleep(.15)
    return False


def wiki_open():
    driver.get(WIKI_URL)
    return bool(wait_for_state(lambda:wiki_title()=='Главная')) and wiki_settled()


def stage_login():
    if not wait_for_state(lambda:is_login_page() or driver.current_url.startswith(BASE_URL)):return False
    if is_login_page() and not login_with(login_val,pass_val):return False
    return wiki_open()


def read_counters():
    text=driver.execute_script("return document.querySelector('.wk-content-header__counts')?.innerText||'';") or ''
    def count(prefix):
        match=re.search(prefix+r'\w*:\s*(\d+)',text,re.I)
        return int(match.group(1)) if match else None
    return tuple(count(prefix) for prefix in ('Раздел','Папок','Файл','Документ'))


def wiki_snapshot():
    return dict(title=wiki_title(),crumbs=wiki_crumbs(),counts=list(read_counters()),cards=wiki_cards())


def wiki_content_signature(snapshot):
    return snapshot['title'],tuple(snapshot['counts']),tuple((c['kind'],c['title']) for c in snapshot['cards'])


def wiki_counter_errors(snapshot):
    cards=snapshot['cards'];counts=snapshot['counts']
    actual=[sum(c['kind'] in ('base','section') for c in cards),sum(c['kind']=='folder' for c in cards),
            sum(c['kind']=='file' or c['kind'].startswith('doc') for c in cards),sum(c['kind'].startswith('doc') for c in cards)]
    errors=[]
    if not any(value is not None for value in counts):errors.append('счётчики отсутствуют')
    for name,shown,found in zip(('Разделов','Папок','Файлов','Документов'),counts,actual):
        if shown is not None and shown!=found:errors.append(f'{name}: показано {shown}, карточек {found}')
    return errors


def stage_wiki_home():
    if not wiki_open():return False
    snapshot=wiki_snapshot();errors=wiki_counter_errors(snapshot)
    log(f"  Главная: счётчики {snapshot['counts']}; карточки {[(c['kind'],c['title']) for c in snapshot['cards']]}")
    for error in errors:log('  '+error,'WARN')
    return not errors and page_health('WIKI/главная')


def stage_wiki_tree():
    if not wiki_open():return False
    expanded=0
    for _ in range(60):
        buttons=[e for e in driver.find_elements(By.CSS_SELECTOR,".wk-tree__toggle[aria-expanded='false']") if e.is_displayed()]
        if not buttons:break
        if not click_el(buttons[0]):return False
        expanded+=1
        wait_idle(4,.4)
    remaining=[e for e in driver.find_elements(By.CSS_SELECTOR,".wk-tree__toggle[aria-expanded='false']") if e.is_displayed()]
    rows=driver.execute_script(JS_TREE_COLLECT) or []
    WIKI_TREE[:]=[(r[0],r[1]) for r in rows]
    roots=[name for level,name in WIKI_TREE if level==0]
    root_cards=[c['title'] for c in wiki_cards() if c['kind'] in ('base','folder','section')]
    valid=bool(WIKI_TREE) and not remaining and all(name for _,name in WIKI_TREE) and sorted(roots)==sorted(root_cards)
    log(f'  Дерево: раскрыто {expanded}, узлов {len(WIKI_TREE)}, корневых узлов {len(roots)}, закрытых узлов осталось {len(remaining)}')
    for level,name in WIKI_TREE:
        log(f'    {"  "*level}{name}')
        if re.search(r'^(test|тест|new|новый|без названия|untitled|asd|qwe)\b',name,re.I):
            finding('WIKI/данные',f'тестовое название: {name}')
    # Repeated names in different branches are observations, not failed navigation.
    return valid


def wiki_open_card(index):
    cards=wiki_cards()
    if not 0<=index<len(cards) or cards[index]['kind'] not in ('base','section','folder'):return False
    wanted=cards[index]['title']
    elements=[e for e in driver.find_elements(By.CSS_SELECTOR,'.wk-content-panel .wk-card') if e.is_displayed()]
    if index>=len(elements) or not click_el(elements[index]):return False
    return bool(wait_for_state(lambda:wiki_title()==wanted)) and wiki_settled()


def wiki_go_up():
    crumbs=wiki_crumbs()
    elements=driver.find_elements(By.CSS_SELECTOR,'.wk-breadcrumbs__item')
    if len(crumbs)<2 or len(elements)<2:return False
    wanted=crumbs[-2]
    targets=elements[-2].find_elements(By.CSS_SELECTOR,'a,button,[role=button],.wk-breadcrumbs__crumb')
    if not click_el(targets[0] if targets else elements[-2]):return False
    return bool(wait_for_state(lambda:wiki_title()==wanted)) and wiki_settled()


def wiki_restore_path(path):
    if not wiki_open():return False
    for kind,title in path:
        matches=[i for i,c in enumerate(wiki_cards()) if c['kind']==kind and c['title']==title]
        if len(matches)!=1 or not wiki_open_card(matches[0]):return False
    return True


def wiki_inspect_level(path,depth,budget):
    global WIKI_LIMIT_REACHED
    snapshot=wiki_snapshot()
    key=' / '.join(title for _,title in path) or 'Главная'
    if key in WIKI_PAGES:
        WIKI_NAV_ERRORS.append(f'Повтор пути: {key}');return
    WIKI_PAGES[key]=snapshot
    errors=wiki_counter_errors(snapshot)
    WIKI_COUNT_ERRORS.extend(f'{key}: {error}' for error in errors)
    for card in snapshot['cards']:
        if not card['title']:WIKI_META_ERRORS.append(f'{key}: карточка без названия')
        if card['kind']=='other':WIKI_META_ERRORS.append(f'{key}: неизвестный тип карточки')
    children=[(i,c) for i,c in enumerate(snapshot['cards']) if c['kind'] in ('base','section','folder')]
    log(f"  {key}: счётчики {snapshot['counts']}, карточек {len(snapshot['cards'])}")
    if depth>=4:
        if children:WIKI_LIMIT_REACHED=True
        return
    for index,card in children:
        if budget[0]<=0:WIKI_LIMIT_REACHED=True;return
        budget[0]-=1
        if not wiki_open_card(index):
            WIKI_NAV_ERRORS.append(f'{key}: не открыт {card["title"]}')
            if not wiki_restore_path(path):return
            continue
        crumbs=wiki_crumbs()
        if not crumbs or crumbs[-1]!=card['title']:
            WIKI_NAV_ERRORS.append(f'{key}: неверный путь после открытия {card["title"]}')
        wiki_inspect_level(path+[(card['kind'],card['title'])],depth+1,budget)
        restored=wiki_go_up()
        if not restored or wiki_content_signature(wiki_snapshot())!=wiki_content_signature(snapshot):
            WIKI_NAV_ERRORS.append(f'{key}: возврат не восстановил заголовок, счётчики и карточки')
            if not wiki_restore_path(path):return


def stage_wiki_walk():
    global WIKI_LIMIT_REACHED
    WIKI_PAGES.clear();WIKI_NAV_ERRORS.clear();WIKI_COUNT_ERRORS.clear();WIKI_META_ERRORS.clear();WIKI_LIMIT_REACHED=False
    if not wiki_open():return False
    budget=[40]
    wiki_inspect_level([],0,budget)
    log(f'  Посещено страниц: {len(WIKI_PAGES)}; переходов {40-budget[0]}/40; глубина до 4; достигнут лимит: {WIKI_LIMIT_REACHED}')
    for error in WIKI_NAV_ERRORS:log('  '+error,'WARN')
    return bool(WIKI_PAGES) and not WIKI_NAV_ERRORS and wiki_open()


def stage_wiki_visited_counts():
    if not WIKI_PAGES:return False
    for error in WIKI_COUNT_ERRORS:log('  '+error,'WARN')
    log(f'  Сверено уровней: {len(WIKI_PAGES)}, несоответствий счётчиков: {len(WIKI_COUNT_ERRORS)}')
    return not WIKI_COUNT_ERRORS


def stage_wiki_structure():
    global WIKI_SNAPSHOT_PATH
    if not WIKI_PAGES:return False
    for error in WIKI_META_ERRORS:log('  '+error,'WARN')
    lines=[];files=0;empty=0
    for path,snapshot in WIKI_PAGES.items():
        lines.append(f"{path}  [счётчики: {snapshot['counts']}]")
        if not snapshot['cards']:empty+=1;lines.append('    (пустая ветвь)')
        for card in snapshot['cards']:
            lines.append(f"    - {card['kind']}: {card['title']} | {card.get('status','')} | {card.get('date','')}")
            if card['kind']=='file' or card['kind'].startswith('doc'):files+=1
    WIKI_SNAPSHOT_PATH=log_path(f'wiki_structure_{STAMP}.txt')
    Path(WIKI_SNAPSHOT_PATH).write_text('\n'.join(lines),encoding='utf-8')
    data_path=Path(log_path(f'wiki_structure_{STAMP}.json'))
    data_path.write_text(json.dumps(dict(pages=WIKI_PAGES,tree=WIKI_TREE,limits=dict(transitions=40,depth=4,reached=WIKI_LIMIT_REACHED)),ensure_ascii=False,indent=2),encoding='utf-8')
    valid=json.loads(data_path.read_text(encoding='utf-8'))['pages']==WIKI_PAGES
    log(f'  Файлов: {files}; пустых ветвей: {empty}; снимок: {WIKI_SNAPSHOT_PATH}')
    return valid and not WIKI_META_ERRORS


def stage_wiki_views():
    if not wiki_open():return False
    before=wiki_snapshot()
    for name,mode in [('Список','list'),('Сетка','grid')]:
        buttons=driver.find_elements(By.CSS_SELECTOR,f'.wk-view-toggle__trigger[aria-label="{name}"]')
        if len(buttons)!=1 or not click_el(buttons[0]) or not wiki_settled():return False
        active=driver.execute_script('''const b=arguments[0],mode=arguments[1];
            return ['aria-pressed','aria-selected','aria-checked'].some(a=>b.getAttribute(a)==='true')||
              /--active|--selected|is-active/.test(b.className)||
              (document.querySelectorAll('.wk-content-panel .wk-card').length>0&&Array.from(document.querySelectorAll('.wk-content-panel .wk-card')).every(c=>c.classList.contains('wk-card--'+mode)));''',buttons[0],mode)
        if not active or wiki_content_signature(wiki_snapshot())!=wiki_content_signature(before):return False
    return True


def wiki_set_search(query):
    inputs=driver.find_elements(By.CSS_SELECTOR,'input.wk-search__input')
    if len(inputs)!=1:return False
    type_text(inputs[0],query)
    if query:
        if not wait_for_state(lambda:'Результаты поиска' in wiki_title()):return False
    else:
        if not wait_for_state(lambda:'Результаты поиска' not in wiki_title()):return False
    return wiki_settled()


def stage_wiki_search_existing():
    candidates=[(path,c) for path,s in WIKI_PAGES.items() for c in s['cards'] if c['kind']=='file' or c['kind'].startswith('doc')]
    candidates.sort(key=lambda pair:0 if 'опубликован' in pair[1].get('status','').casefold() else 1)
    if not candidates:
        log('  Нет файлов: положительный поиск файла не проверен','WARN');return False
    path,card=candidates[0]
    if not wiki_open():return False
    before=wiki_snapshot()
    if not wiki_set_search(card['title']):return False
    found=wiki_cards()
    success=any(c['title']==card['title'] for c in found)
    log(f'  Поиск {card["title"]!r}: найдено карточек {len(found)}, исходный файл найден: {success}')
    return wiki_set_search('') and wiki_content_signature(wiki_snapshot())==wiki_content_signature(before) and success


def stage_wiki_search_empty():
    if not wiki_open():return False
    before=wiki_snapshot()
    if not wiki_set_search('wiki-no-match-'+os.environ['WIKI_RUN_ID']):return False
    text=driver.execute_script("return document.querySelector('.wk-content-panel')?.innerText||'';") or ''
    empty=not wiki_cards() and 'Ничего не найдено' in text and bool(re.search(r'Найдено:\s*0',text))
    return wiki_set_search('') and wiki_content_signature(wiki_snapshot())==wiki_content_signature(before) and empty


def wiki_menu_items():
    return driver.execute_script('''return Array.from(document.querySelectorAll('[role=menu] [role^=menuitem],[role=menu] button'))
      .filter(e=>e.offsetWidth||e.offsetHeight).map(e=>e.innerText.trim()).filter(Boolean);''') or []


def wiki_inspect_menu(selector):
    buttons=[b for b in driver.find_elements(By.CSS_SELECTOR,selector) if b.is_displayed()]
    if not buttons:return False
    button=buttons[0]
    if not click_el(button):return False
    items=wait_for_state(wiki_menu_items,timeout=4)
    log(f'  Меню {selector}: {items}; пункты не нажимаются')
    esc()
    closed=wait_for_state(lambda:not wiki_menu_items(),timeout=3)
    return bool(items and closed and find_modal() is None)


def stage_wiki_sort_menu():
    if not wiki_open():return False
    before=wiki_snapshot()
    return wiki_inspect_menu('.wk-sort-button') and wiki_settled() and wiki_content_signature(wiki_snapshot())==wiki_content_signature(before)


def stage_wiki_safe_menus():
    if not wiki_open():return False
    before=wiki_snapshot()
    for selector in ('.wk-card__more','.wk-split-button__toggle'):
        if not wiki_inspect_menu(selector):return False
        if not wiki_settled() or wiki_content_signature(wiki_snapshot())!=wiki_content_signature(before):return False
    return True


def save_wiki_results():
    path=Path(os.environ['WIKI_RESULT_PATH'])
    payload=dict(run_id=os.environ['WIKI_RUN_ID'],results=[dict(name=n,ok=ok,reason=REASONS.get(n,'')) for n,ok in RESULTS],error=RUN_ERROR,
        screenshot=FAILED_SCREENSHOTS[-1] if FAILED_SCREENSHOTS else '',log=LOG_FILE_PATH,structure=WIKI_SNAPSHOT_PATH,
        coverage=dict(pages=len(WIKI_PAGES),max_transitions=40,max_depth=4,limit_reached=WIKI_LIMIT_REACHED))
    temporary=path.with_suffix('.tmp');temporary.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8');temporary.replace(path)


def run():
    global RUN_ERROR
    try:
        init_driver();driver.get(BASE_URL)
        if not step(WIKI_CHECKS[0],stage_login):return
        functions=[stage_wiki_home,stage_wiki_tree,stage_wiki_walk,stage_wiki_visited_counts,stage_wiki_structure,stage_wiki_views,
                   stage_wiki_search_existing,stage_wiki_search_empty,stage_wiki_sort_menu,stage_wiki_safe_menus]
        for name,fn in zip(WIKI_CHECKS[1:],functions):step(name,fn)
    except Exception as exc:
        RUN_ERROR=f'{type(exc).__name__}: {exc}';log(RUN_ERROR,'FAIL');shot('critical_error')
    finally:
        save_wiki_results()
        if driver is not None:driver.quit()
        if _LOG_FILE:_LOG_FILE.close()


if __name__=='__main__' and os.environ.get('WIKI_NO_RUN')!='1':
    if os.environ.get('WIKI_MANAGED')=='1':
        run()
        raise SystemExit(1 if RUN_ERROR or any(not ok for _,ok in RESULTS) else 0)
    from run_workflow_and_report import run_wiki
    raise SystemExit(run_wiki(__file__,sys.argv[1:]))
