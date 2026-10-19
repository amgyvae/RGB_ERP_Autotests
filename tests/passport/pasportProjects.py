# -*- coding: utf-8 -*-
"""
АВТОТЕСТ: раздел «Паспорта проектов» — полный сценарий.

Этапы:
  1. Вход (если нужен), открытие /projects
  2. Список: фильтры (Все этапы / Строительство / Проектирование /
     Завершенные), переключатель Карточки/Список, поиск, открытие карточки
     проекта (Каусар), фильтры Статус/Очередь/Блок, «Сбросить фильтры»
  3. «Создать паспорт» -> «Отмена» -> снова «Создать паспорт»
  4. Форма (все 9 секций заполняются значениями по умолчанию):
       1 О проекте        — Проект (Flagman), Очередь, Блок, Тип, Статус, Адрес
       2 Площади          — все 14 полей
       3 Атрибуты         — 7 вкладок (Основная информация, Электроэнергия,
                            Водоснабжение, Канализация, Тепловые сети,
                            Услуги связи, Конструктив) + даты ТУ + файлы
       4 Документация     — обе вкладки: файл в каждую строку + комментарии
       5 Земельный участок— поля, файл, «+ Добавить участок»
       6 Сроки            — плановые и фактические даты
       7 Ответственные    — 10 селектов «Выбрать лицо»
       8 Доп. характеристики — селекты, поля, 7 переключателей
       9 Фотографии/рендеры — 6 зон загрузки (png/jpg/jpeg), «+ Добавить еще»
  5. «Сохранить» (если такой паспорт уже есть и появляется ошибка —
     автоматически перебираются другие Очередь/Блок/Проект)
  6. Карточка паспорта: проверка статуса, «Редактировать» -> меняем
     поля -> «Сохранить». Кнопку «Удалить паспорт» НЕ нажимаем.

ЗАВИСИМОСТИ: pip install requests pillow (pillow — необязательно, для картинок)

НЕ ПРОВЕРЕНО НА ЖИВОМ DOM (место для правок, если что-то не нажмётся):
  переключатели (toggle), зоны загрузки фото, вкладки «Участок 1»,
  поведение страницы после «Сохранить» и режим «Редактировать».
  В логе будут ⚠ и скриншоты debug_*.png — пришлите их, доработаю.
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
from artifact_paths import screen_path, log_path
from env_config import env, env_list, is_headless  # секреты — из .env / GitHub Secrets
import base64
import tempfile
from datetime import datetime
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
    # Раскомментировать для запуска без UI (headless):
    # Включается переменной окружения HEADLESS=1 (CI / сервер без монитора)
    if is_headless():
        _chrome_options.add_argument("--headless=new")
        _chrome_options.add_argument("--window-size=1920,1080")
    
    driver = webdriver.Chrome(
        service=Service(ChromeDriverManager().install()),
        options=_chrome_options
    )
    driver.implicitly_wait(0)

login_val = env("RGB_ACCOUNT1_LOGIN", env("RGB_ACCOUNT3_LOGIN"))
pass_val = env("RGB_ACCOUNT1_PASSWORD", env("RGB_ACCOUNT3_PASSWORD"))

BASE_URL = "https://testportal.rgbgroup.kz/"
PROJECTS_URL = BASE_URL + "projects"
CREATE_URL = PROJECTS_URL + "/create"
WAIT = 15

STAMP = datetime.now().strftime('%d%m-%H%M%S')
PROJECT_KW = "Flagman"            # проект, для которого создаём паспорт
CARD_KW = "Каусар"                # карточка проекта на списке (для проверки кнопок)
STATUS_PREF = ["строительств", "проектирован"]   # предпочтительный статус
PREFS = {"Статус": STATUS_PREF, "Статус проекта": STATUS_PREF}
SAVE_MAX_COMBOS = 14              # сколько комбинаций Проект/Очередь/Блок пробовать
NEW_ADDRESS = "г. Алматы, ул. Изменённая, 2"

WORK_DIR = os.path.join(tempfile.gettempdir(), f"passport_autotest_{STAMP}")
os.makedirs(WORK_DIR, exist_ok=True)


STATE = {"url": None, "status": None, "address": None, "combo": None}
RESULTS = []
REASONS = {}
FAILED_SCREENSHOTS = []
RUN_ERROR = ""
LOG_LINES = []

LOG_FILE_PATH = log_path(f"passport_log_{STAMP}_{os.environ.get('PASSPORT_RUN_ID', 'standalone')}.txt")
try:
    _LOG_FILE = open(LOG_FILE_PATH, "w", encoding="utf-8", buffering=1)
except Exception:
    _LOG_FILE = None

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
        path = screen_path(f"debug_passport_{safe}_{os.environ.get('PASSPORT_RUN_ID', STAMP)}_{time.time_ns()}.png")
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

def _last_problem(start_idx):
    for line in reversed(LOG_LINES[start_idx:]):
        if "[WARN]" in line or "[FAIL]" in line:
            txt = line.split("]", 2)[-1].strip()
            return re.sub(r"^[⚠•✗\s]+", "", txt)[:180]
    return ""


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


def passport_list_ready():
    return '/projects' in driver.current_url and (bool(find_buttons(['Создать паспорт', 'Создать'])) or 'паспорт' in page_text() or 'проект' in page_text())


def passport_form_ready():
    return ('/projects/create' in driver.current_url or 'создание' in page_text()) and (control_by_label(driver, 'Проект') is not None or bool(find_buttons(['Сохранить'])))


def selected_option_changed(trigger, before):
    now = (trigger.get_attribute('textContent') or '').strip()
    return bool(now and now != before and not now.lower().startswith('выбр'))


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
            if wait_for_state(lambda: visible_panel() is None, timeout=3):
                return target["text"]
        except Exception:
            pass
    return None

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
    dismiss_news_popup(wait=3)
    return True


def dismiss_news_popup(wait=0):
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
        scrims = [s for s in driver.find_elements(By.CSS_SELECTOR, "button.ui-kit-modal__scrim") if s.is_displayed()]
        for s in scrims:
            try: js_click(s)
            except Exception: pass
        if time.monotonic() >= deadline:
            break
        time.sleep(0.3)
    return True


# ==========================================
# ФАЙЛЫ
# ==========================================
def create_test_image(i):
    """Картинка для зон «Фотографии/рендеры»: png / jpg / jpeg по кругу."""
    exts = ["png", "jpg", "jpeg"]
    ext = exts[i % 3]
    colors = [(30, 90, 160), (160, 60, 60), (40, 130, 80),
              (120, 80, 160), (200, 130, 40), (60, 60, 60)]
    path = os.path.join(WORK_DIR, f"render_{i + 1}_{STAMP}.{ext}")
    try:
        from PIL import Image, ImageDraw
        img = Image.new("RGB", (640, 480), colors[i % 6])
        ImageDraw.Draw(img).text((20, 20), f"Autotest render {i + 1}", fill=(255, 255, 255))
        img.save(path, "PNG" if ext == "png" else "JPEG")
        return path
    except Exception:
        png = os.path.join(WORK_DIR, f"render_{i + 1}_{STAMP}.png")
        with open(png, "wb") as f:
            f.write(base64.b64decode(
                "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="))
        return png


JS_FILE_INPUT_FOR = r"""
var e = arguments[0];
for (var i = 0; i < 10 && e; i++) {
    e = e.parentElement; if (!e) break;
    var f = e.querySelector('input[type=file]');
    if (f) return f;
}
return null;
"""

JS_NEXT_FILE_LINK = r"""
function vis(e){ return !!(e.offsetWidth || e.offsetHeight || e.getClientRects().length); }
function norm(e){ return (e.textContent || '').replace(/\s+/g, ' ').trim(); }
var all = document.body.querySelectorAll('*');
for (var i = 0; i < all.length; i++) {
    var e = all[i];
    if (e.__up || !vis(e) || e.children.length > 3) continue;
    if (norm(e) !== 'Файл') continue;
    var child = false;
    for (var j = 0; j < e.children.length; j++) {
        if (norm(e.children[j]) === 'Файл') { child = true; break; }
    }
    if (child) continue;
    e.__up = true;
    return e;
}
return null;
"""


def upload_to_element(el, path):
    """Загрузка файла в input[type=file] рядом с элементом (без нативного окна)."""
    inp = None
    try:
        inp = driver.execute_script(JS_FILE_INPUT_FOR, el)
    except Exception:
        pass
    if inp is None:
        block_native_file_dialog()
        try:
            hard_click(el)
        except Exception:
            pass
        time.sleep(1)
        try:
            inp = driver.execute_script(
                "var i = window.__lastFileInput; return (i && document.contains(i)) ? i : null;")
        except Exception:
            inp = None
    if inp is None:
        log("    ⚠ input[type=file] для этого элемента не найден", "WARN")
        return False
    try:
        driver.execute_script(
            "arguments[0].style.display='block';arguments[0].style.opacity='1';"
            "arguments[0].style.visibility='visible';arguments[0].removeAttribute('hidden');", inp)
        inp.send_keys(path)
        time.sleep(2.5)
        driver.execute_script("window.__lastFileInput = null;")
        log(f"    ✓ Файл загружен: {os.path.basename(path)}", "PASS")
        return True
    except Exception as e:
        log(f"    ⚠ Не удалось загрузить файл: {e}", "WARN")
        return False


def upload_visible_file_links(path, limit=25):
    """Нажимает/заполняет каждую видимую ссылку «Файл» (строки Электроэнергия, ПДП и т.д.)."""
    n = 0
    for _ in range(limit):
        link = driver.execute_script(JS_NEXT_FILE_LINK)
        if link is None:
            break
        scroll_to(link)
        if upload_to_element(link, path):
            n += 1
    return n


def find_all_deepest(text, mode="prefix"):
    try:
        return driver.execute_script(r"""
            var t = arguments[0], mode = arguments[1];
            function vis(e){ return !!(e.offsetWidth || e.offsetHeight || e.getClientRects().length); }
            function norm(e){ return (e.textContent || '').replace(/\s+/g, ' ').trim(); }
            function ok(s){ return mode === 'prefix' ? s.indexOf(t) === 0
                           : (mode === 'exact' ? s === t : s.indexOf(t) >= 0); }
            var out = [], all = document.body.querySelectorAll('*');
            for (var i = 0; i < all.length; i++) {
                var e = all[i];
                if (['SCRIPT','STYLE','INPUT','TEXTAREA','HTML','BODY'].indexOf(e.tagName) >= 0) continue;
                if (!vis(e) || !ok(norm(e))) continue;
                var child = false;
                for (var j = 0; j < e.children.length; j++) {
                    if (ok(norm(e.children[j]))) { child = true; break; }
                }
                if (!child) out.push(e);
            }
            return out;""", text, mode) or []
    except Exception:
        return []


# ==========================================
# УМНОЕ ЗАПОЛНЕНИЕ ПОЛЕЙ
# ==========================================
NUM_RE = re.compile(r"площад|количеств|мощност|высот|этажност|подъезд|очередей|\(га\)|\(квт\)|гкал|куб\.?\s?м|кв\.?\s?м|квт|/\s?сут|/\s?час|расход|плат[аы]|стоимост|цена|сумм|тариф|теплопотреблен|отоплен|вентиляц|горяче[ею] водоснаб", re.I)


def value_for(label, ph, maxlen=0, maxnum=None, numeric=False):
    v = _value_for(label, ph, numeric)
    # лимиты поля: maxlength и max (для чисел)
    try:
        if maxnum is not None and re.fullmatch(r"\d+(\.\d+)?", v) and float(v) > float(maxnum):
            v = str(int(float(maxnum))) if float(maxnum) >= 1 else v
    except Exception:
        pass
    if maxlen and maxlen > 0 and len(v) > maxlen:
        v = v[:maxlen]
    return v


def _value_for(label, ph, numeric_hint=False):
    l = (label or "").strip().lower()
    p = (ph or "").strip().lower()
    if "кадастр" in l or "кадастр" in p:
        return "05-040-001-123"          # лимит сервера: кадастровый номер <= 20 символов
    if "телефон" in l:
        return "+77001234567"
    if "email" in l or "почт" in l:
        return "autotest@example.com"
    if "инн" in l or "бин" in l:
        return "123456789012"
    if "комнатност" in l:
        return "1-3 комнаты"
    if l.startswith("№"):
        return f"ТУ-{STAMP}"
    if "адрес" in l:
        return "г. Алматы, ул. Автотестовая, 1"
    if l == "наименование проекта":
        return f"Автотест паспорт {STAMP}"
    if "комментар" in l or "комментар" in p:
        return "Автотест комментарий"
    numeric = numeric_hint or bool(NUM_RE.search(l)) or "площад" in p or "количеств" in p
    if numeric:
        if re.search(r"плат|стоимост|цена|сумм", l):
            return "100000"
        if "(га)" in l:
            return "2"
        if "на площадке" in l:
            return "4"
        if "высот" in l:
            return "3"
        if "этажност" in l:
            return "9"
        if "очередей" in l:
            return "2"
        if "мощност" in l:
            return "500"
        if "площад" in l:
            return "1000"
        return "10"
    return f"Автотест {label}"[:20] if label else "Автотест"


JS_NEXT_CONTROL = r"""
function vis(e){ return !!(e.offsetWidth || e.offsetHeight || e.getClientRects().length); }
function labelOf(e){
    var own = ((e.innerText || '')).trim();
    var c = e;
    for (var i = 0; i < 6; i++) {
        c = c.parentElement; if (!c) break;
        var lines = (c.innerText || '').split('\n').map(function(s){ return s.trim(); }).filter(Boolean);
        for (var j = 0; j < lines.length; j++) {
            if (lines[j] !== own && lines[j].length < 80) return lines[j];
        }
    }
    return '';
}
var els = document.querySelectorAll('input, textarea, button.ui-select__trigger');
for (var i = 0; i < els.length; i++) {
    var e = els[i];
    if (!vis(e) || e.disabled || (e.__af || 0) >= 2) continue;
    if (e.tagName === 'BUTTON') {
        var txt = (e.innerText || '').trim().toLowerCase();
        var cls = (e.className || '').toString();
        if (!(cls.indexOf('placeholder') >= 0 || /^выбр/.test(txt))) continue;
        if (e.closest('.ui-select__panel')) continue;
        e.__af = (e.__af || 0) + 1;
        return ['select', e, labelOf(e), txt];
    }
    var type = (e.type || '').toLowerCase();
    if (['file','checkbox','radio','hidden','search','submit','button'].indexOf(type) >= 0) continue;
    if (e.readOnly) continue;
    if (e.closest('.ui-select, .ui-select__panel, .ui-date-picker')) continue;
    if ((e.value || '').trim()) continue;
    var ph = e.getAttribute('placeholder') || '';
    if (/поиск/i.test(ph)) continue;
    e.__af = (e.__af || 0) + 1;
    return ['input', e, labelOf(e), ph];
}
return null;
"""


def pick_option_for(trigger, keywords=None):
    """Открыть ui-select и выбрать опцию (по ключевым словам, иначе первую)."""
    before = (trigger.get_attribute("textContent") or "").strip()
    panel = open_ui(trigger)
    if panel is None:
        return False
    opts = panel_options(panel)
    if not opts:
        close_panels()
        return False
    target = None
    if keywords:
        for o in opts:
            if any(k in o["text"].lower() for k in keywords):
                target = o
                break
    if target is None:
        target = opts[0]
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
        wait_for_state(lambda: selected_option_changed(trigger, before), timeout=3)
        now = (trigger.get_attribute("textContent") or "").strip()
        if now and now != before and not now.lower().startswith("выбр"):
            close_panels()
            try:
                ActionChains(driver).send_keys(Keys.ESCAPE).perform()
            except Exception:
                pass
            return True
    try:
        trigger.send_keys(Keys.ARROW_DOWN)
        trigger.send_keys(Keys.ENTER)
        wait_for_state(lambda: selected_option_changed(trigger, before), timeout=3)
        now = (trigger.get_attribute("textContent") or "").strip()
        if now and now != before and not now.lower().startswith("выбр"):
            close_panels()
            return True
    except Exception:
        pass
    close_panels()
    return False


def fill_visible_controls(prefs=None, tag="", skip_labels=(), max_items=120):
    """Заполняет ВСЕ видимые пустые поля и селекты. Возвращает (заполнено, не_удалось)."""
    prefs = prefs or PREFS
    filled = failed = 0
    skip = [s.lower() for s in skip_labels]
    for _ in range(max_items):
        item = driver.execute_script(JS_NEXT_CONTROL)
        if not item:
            break
        kind, el, label, ph = item
        if (label or "").lower() in skip:
            continue
        try:
            scroll_to(el)
            if kind == "input":
                try:
                    ml = int(el.get_attribute("maxlength") or 0)
                except Exception:
                    ml = 0
                mx = el.get_attribute("max") or None
                is_num = ((el.get_attribute("type") or "").lower() == "number"
                          or (el.get_attribute("inputmode") or "").lower() in ("numeric", "decimal"))
                val = value_for(label, ph, ml, mx, is_num)
                type_text(el, val)
                ok = bool((el.get_attribute("value") or "").strip())
                if not ok:                       # поле приняло только числа -> вводим число
                    val = "10"
                    type_text(el, val)
                    ok = bool((el.get_attribute("value") or "").strip())
                log(f"    [{tag}] поле '{label}' = '{val}' {'✓' if ok else '✗'}",
                    "PASS" if ok else "WARN")
            else:
                kws = None
                for k, v in prefs.items():
                    if k.lower() == (label or "").lower():
                        kws = v
                ok = pick_option_for(el, kws)
                shown = (el.get_attribute("textContent") or "").strip()[:40]
                log(f"    [{tag}] селект '{label}' → '{shown}' {'✓' if ok else '✗'}",
                    "PASS" if ok else "WARN")
        except Exception as e:
            ok = False
            log(f"    [{tag}] '{label}': {e}", "WARN")
        if ok:
            filled += 1
        else:
            failed += 1
    return filled, failed


# ---------- даты ----------
def date_triggers():
    try:
        xs = [x for x in driver.find_elements(
            By.XPATH, "//*[contains(@class,'ui-date-picker__trigger')]") if x.is_displayed()]
        if xs:
            return xs
    except Exception:
        pass
    return find_all_deepest("Выбрать дату", "exact")


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
    return find_all_deepest("Выбрать дату", "exact")


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
        wait_for_state(calendar_cells, timeout=3)
        if calendar_goto(target.year, target.month):
            cell = cell_by_day(calendar_cells(), target.day)
            if cell is not None:
                click_el(cell)
                if wait_for_state(lambda: not date_empty(trigger), timeout=3):
                    return True
        else:
            cells = calendar_cells()          # не смогли листать — берём любой доступный день
            if cells:
                click_el(cell_by_day(cells, target.day))
                if wait_for_state(lambda: not date_empty(trigger), timeout=3):
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
        return bool(wait_for_state(lambda: not date_empty(trigger), timeout=3))
    except Exception:
        return False


def fill_all_dates(mode="late"):
    """Заполняет все пустые даты на видимой вкладке по порядку.
    Каждая следующая дата на 10 дней позже предыдущей (окончание всегда позже начала).
    late: от сегодня+30 дней (плановые), early: от сегодня-90 дней (фактические).
    «Срок действия ТУ» / «Срок аренды» — через год."""
    import datetime
    today = datetime.date.today()
    cur = today + datetime.timedelta(days=30 if mode == "late" else -90)
    n = 0
    for _ in range(14):
        empties = [t for t in date_triggers() if date_empty(t)
                   and not driver.execute_script("return !!arguments[0].__dp;", t)]
        if not empties:
            break
        trg = empties[0]
        driver.execute_script("arguments[0].__dp = true;", trg)
        try:
            lab = driver.execute_script(JS_DATE_LABEL, trg) or ""
        except Exception:
            lab = ""
        if re.search(r"срок\s+(действия|аренды)", lab, re.I):
            target = today + datetime.timedelta(days=365)
        else:
            target = cur
            cur = cur + datetime.timedelta(days=10)
        if pick_date(trg, target):
            n += 1
            log(f"    ✓ Дата [{lab or '?'}] = {date_text(trg)}", "PASS")
        else:
            log(f"    ⚠ Дату [{lab or '?'}] выбрать не удалось", "WARN")
    return n


# ---------- переключатели ----------
JS_FIND_TOGGLE = r"""
var lab = arguments[0], c = lab;
var sel = "[role=switch], input[type=checkbox], button[class*=switch], [class*=switch], [class*=toggle]";
for (var i = 0; i < 4 && c; i++) {
    c = c.parentElement; if (!c) break;
    var f = c.querySelector(sel);
    if (f && f !== lab && !lab.contains(f)) return f;
}
return null;
"""


def toggle_on(label):
    labs = [e for e in driver.find_elements(
        By.XPATH, f"//*[normalize-space(text())='{label}']") if e.is_displayed()]
    if not labs:
        return False
    sw = driver.execute_script(JS_FIND_TOGGLE, labs[0])
    if sw is None:
        return False

    def is_on():
        return bool(driver.execute_script("""
            var e = arguments[0];
            if (e.getAttribute('aria-checked') === 'true' || e.checked === true) return true;
            var c = ((e.className || '') + ' ' + (e.parentElement ? e.parentElement.className : '')).toString();
            return /checked|active|--on|is-on/.test(c);""", sw))

    if is_on():
        return True
    scroll_to(sw)
    for m in ("hard", "js", "selenium"):
        try:
            if m == "hard":
                hard_click(sw)
            elif m == "js":
                js_click(sw)
            else:
                sw.click()
        except Exception:
            continue
        time.sleep(0.6)
        if is_on():
            return True
    return False


# ---------- секции ----------
SECTIONS = {
    "Площади": "Общая площадь",
    "Атрибуты": "Наименование проекта",
    "Документация": "ПДП, ген.план",
    "Земельный участок": "Способ привлечения денег",
    "Сроки": "Начало СМР",
    "Ответственные": "Руководитель строительного комплекса",
    "Дополнительные характеристики": "Отделка квартир",
    "Фотографии/рендеры": "Перетащите файлы сюда",
}


def marker_visible(marker):
    try:
        return any(e.is_displayed() for e in driver.find_elements(
            By.XPATH, f"//*[contains(normalize-space(text()),'{marker}')]"))
    except Exception:
        return False


def expand_section(title):
    marker = SECTIONS.get(title, title)
    if marker_visible(marker):
        return True
    for _ in range(3):
        click_text_deepest(title, "exact")
        if wait_for_state(lambda: marker_visible(marker), timeout=3):
            log(f"  ✓ Секция '{title}' раскрыта", "PASS")
            return True
    log(f"  ⚠ Секция '{title}' не раскрылась", "WARN")
    return False


def click_tab(name, mode="exact"):
    ok = click_text_deepest(name, mode)
    time.sleep(1.2)
    return ok


def validation_errors():
    try:
        return driver.execute_script(r"""
            var out = [];
            document.querySelectorAll('[class*=error], [class*=invalid], [class*=helper--err]').forEach(function(e){
                if (!(e.offsetWidth || e.offsetHeight)) return;
                var t = (e.innerText || '').trim();
                if (t && t.length < 120 && out.indexOf(t) < 0) out.push(t);
            });
            return out;""") or []
    except Exception:
        return []


# ==========================================
# ЭТАП 1: ВХОД
# ==========================================
def stage_login():
    log(f"  URL: {driver.current_url}")
    if is_login_page():
        if not login_with(login_val, pass_val):
            return False
    time.sleep(2)
    dismiss_news_popup(wait=2)
    if "/projects" not in driver.current_url:
        driver.get(PROJECTS_URL)
        time.sleep(2)
    wait_for_state(lambda: is_login_page() or passport_list_ready(), timeout=25)
    dismiss_news_popup(wait=2)
    if is_login_page():
        return False
    if "/projects" not in driver.current_url:
        try:
            click_text_deepest("Паспорта проектов", "exact")
            time.sleep(2)
        except Exception:
            pass
        if "/projects" not in driver.current_url:
            driver.get(PROJECTS_URL)
            time.sleep(2)
    ok = "/projects" in driver.current_url
    log(f"  URL: {driver.current_url}", "PASS" if ok else "WARN")
    return ok


# ==========================================
# ЭТАП 2: СПИСОК ПАСПОРТОВ
# ==========================================
def parse_counts():
    txt = page_text()
    res = {}
    for name in ["строительство", "проектирование", "завершенные"]:
        m = re.search(name + r"\s*·\s*(\d+)", txt)
        if m:
            res[name] = int(m.group(1))
    return res


def stage_list_page():
    driver.get(PROJECTS_URL)
    if not wait_for_state(passport_list_ready):
        return False
    ok = True
    counts = parse_counts()
    log(f"  Количество паспортов по этапам: {counts} (всего {sum(counts.values())})")

    for prefix in ["Строительство", "Проектирование", "Завершенные", "Все этапы"]:
        if click_text_deepest(prefix, "prefix"):
            log(f"  ✓ Фильтр '{prefix}'", "PASS")
            time.sleep(1.2)
        else:
            log(f"  ⚠ Фильтр '{prefix}' не найден", "WARN")
            ok = False
    for view in ["Список", "Карточки"]:
        if click_text_deepest(view, "exact"):
            log(f"  ✓ Вид '{view}'", "PASS")
            time.sleep(1.2)
        else:
            log(f"  ⚠ Переключатель '{view}' не найден", "WARN")
            ok = False

    inp = None
    for e in driver.find_elements(By.XPATH, "//input[contains(@placeholder,'Поиск')]"):
        if e.is_displayed():
            inp = e
            break
    if inp:
        type_text(inp, PROJECT_KW)
        time.sleep(2)
        found = PROJECT_KW.lower() in page_text()
        log(f"  Поиск '{PROJECT_KW}': {'найдено' if found else 'не найдено'}",
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

    # карточка проекта -> внутренняя страница
    opened = click_text_deepest(CARD_KW, "contains") or click_text_deepest(PROJECT_KW, "contains")
    if not opened:
        for c in driver.find_elements(By.XPATH, "//div[contains(@class,'project-card') or contains(@class,'card')]//h3 | //table//tbody//tr//a | //div[contains(@class,'cursor-pointer')]"):
            if c.is_displayed() and c.text.strip():
                opened = click_el(c)
                break
    if opened:
        time.sleep(3)
        log(f"  ✓ Открыта карточка проекта: {driver.current_url}", "PASS")
        log(f"  Внутри: {parse_counts()}")
        for name in ["Статус", "Очередь", "Блок"]:
            try:
                trg = None
                for t in driver.find_elements(
                        By.XPATH, f"//button[contains(@class,'ui-select__trigger')]"
                                  f"[contains(normalize-space(.),'{name}')]"):
                    if t.is_displayed():
                        trg = t
                        break
                if trg is None:
                    log(f"  • Фильтр '{name}' не найден", "INFO")
                    continue
                panel = open_ui(trg)
                if panel and len(panel_options(panel)) > 1:
                    select_in_panel(panel, index=1)
                    log(f"  ✓ Фильтр '{name}': выбрано значение", "PASS")
                    time.sleep(1.5)
                else:
                    close_panels()
            except Exception as e:
                log(f"  ⚠ Фильтр '{name}': {e}", "WARN")
        if click_text_deepest("Сбросить фильтры", "contains"):
            log("  ✓ 'Сбросить фильтры'", "PASS")
            time.sleep(1.5)
        for prefix in ["Строительство", "Все этапы"]:
            click_text_deepest(prefix, "prefix")
            time.sleep(1)
        # открыть первую внутреннюю карточку и вернуться
        if click_text_deepest("Сроки СМР", "contains"):
            time.sleep(3)
            log(f"  Внутренняя карточка: {driver.current_url}")
            shot("inner_passport")
        driver.get(PROJECTS_URL)
        if not wait_for_state(passport_list_ready):
            return False
    else:
        log("  • Карточки проектов на странице пока отсутствуют", "INFO")
    return ok


# ==========================================
# ЭТАП 3: СОЗДАТЬ ПАСПОРТ / ОТМЕНА
# ==========================================
def open_create_page():
    dismiss_news_popup(wait=1)
    try:
        driver.switch_to.alert.accept()
    except Exception:
        pass
    driver.get(PROJECTS_URL)
    wait_for_state(passport_list_ready, timeout=10)
    created = click_button(["Создать паспорт", "Создать", "+ Создать", "+ Паспорт"], wait=8)
    if not created:
        created = click_text_deepest("Создать паспорт", "contains") or click_text_deepest("Создать", "exact")
    if created:
        wait_for_state(passport_form_ready, timeout=10)
    if "/projects/create" not in driver.current_url:
        driver.get(CREATE_URL)
        wait_for_state(passport_form_ready, timeout=10)
    block_native_file_dialog()
    return "/projects/create" in driver.current_url or any(w in page_text() for w in ("создание", "о проекте", "площади", "сохранить"))


def confirm_leave_if_asked():
    try:
        driver.switch_to.alert.accept()
        time.sleep(1)
    except Exception:
        pass
    m = find_modal()
    if m:
        b = modal_button(m, ["Да", "Выйти", "Покинуть", "Не сохранять", "Подтвердить", "ОК"])
        if b:
            click_el(b)
            time.sleep(2)


def stage_cancel_create():
    if not open_create_page():
        log("  ⚠ Страница создания не открылась", "WARN")
        return False
    log("  ✓ Страница 'Создание паспорта проекта' открыта", "PASS")
    if not click_button(["Отмена"], wait=5):
        log("  ⚠ Кнопка 'Отмена' не найдена", "WARN")
        return False
    time.sleep(2)
    confirm_leave_if_asked()
    time.sleep(2)
    left = "/projects/create" not in driver.current_url
    log(f"  После 'Отмена': {driver.current_url} ({'ушли со страницы' if left else 'осталась'})",
        "PASS" if left else "WARN")
    return open_create_page()


# ==========================================
# ЭТАП 4: ФОРМА
# ==========================================
def choose_pqb(project_kw=None, project_idx=None, q=0, b=0):
    ctrl = control_by_label(driver, "Проект")
    panel = open_ui(ctrl)
    if not panel:
        log("  ⚠ Список 'Проект' не открылся", "WARN")
        return None
    if project_kw:
        picked = select_in_panel(panel, keywords=[project_kw], search=project_kw)
    else:
        picked = select_in_panel(panel, index=project_idx or 0)
    if not picked:
        close_panels()
        log("  ⚠ Проект не выбран", "WARN")
        return None
    time.sleep(1.5)
    res = {"project": picked, "queue": None, "block": None}
    for label, idx, key in [("Очередь", q, "queue"), ("Блок", b, "block")]:
        c = control_by_label(driver, label)
        p = open_ui(c)
        if not p:
            continue
        n = len(panel_options(p))
        if n:
            res[key] = select_in_panel(p, index=min(idx, n - 1))
        else:
            close_panels()
        time.sleep(1.2)
    log(f"  ✓ Проект='{res['project']}', Очередь='{res['queue']}', Блок='{res['block']}'", "PASS")
    return res


def stage_form_basic():
    combo = choose_pqb(project_kw=PROJECT_KW)
    if not combo:
        return False
    STATE["combo"] = combo
    st = control_by_label(driver, "Статус")
    if st is not None and "выбр" in (st.get_attribute("textContent") or "").lower():
        pick_option_for(st, STATUS_PREF)
    if st is not None:
        STATE["status"] = (st.get_attribute("textContent") or "").strip()
        log(f"  Статус паспорта: '{STATE['status']}'")
    expand_section("Площади")
    filled, failed = fill_visible_controls(tag="О проекте+Площади")
    log(f"  Заполнено: {filled}, не удалось: {failed}")
    try:
        STATE["address"] = driver.find_element(
            By.XPATH, "//*[normalize-space(text())='Адрес']/following::input[1]").get_attribute("value")
    except Exception:
        pass
    return failed == 0 and filled >= 14


def stage_form_attributes():
    if not expand_section("Атрибуты"):
        return False
    pdf = create_test_pdf("passport_tu")
    tabs = [("Основная информация", "exact"), ("Электроэнергия (№", "prefix"),
            ("Водоснабжение (№", "prefix"), ("Канализация (№", "prefix"),
            ("Тепловые сети (№", "prefix"), ("Услуги связи", "exact"), ("Конструктив", "exact")]
    ok = True
    for name, mode in tabs:
        if not click_tab(name, mode):
            log(f"  ⚠ Вкладка '{name}' не найдена", "WARN")
            ok = False
            continue
        log(f"  Вкладка '{name}'")
        f, bad = fill_visible_controls(tag=name)
        d = fill_all_dates("late")
        u = upload_visible_file_links(pdf)
        log(f"    → заполнено {f}, ошибок {bad}, дат {d}, файлов {u}")
        ok = ok and bad == 0
    return ok


def stage_form_docs():
    if not expand_section("Документация"):
        return False
    pdf = create_test_pdf("passport_doc")
    ok = True
    for tab in ["Разрешительная документация", "Исходная документация"]:
        if not click_tab(tab, "exact"):
            log(f"  ⚠ Вкладка '{tab}' не найдена", "WARN")
            ok = False
            continue
        f, bad = fill_visible_controls(tag=tab)
        u = upload_visible_file_links(pdf)
        log(f"  Вкладка '{tab}': комментариев/полей {f}, файлов {u}")
        ok = ok and u > 0 and bad == 0
    return ok


def stage_form_land():
    if not expand_section("Земельный участок"):
        return False
    pdf = create_test_pdf("passport_land")
    ok = True
    f, bad = fill_visible_controls(tag="Земельный участок")
    fill_all_dates("late")
    u = upload_visible_file_links(pdf)
    log(f"  Основной участок: заполнено {f}, файлов {u}")
    ok = ok and bad == 0
    if click_tab("Участок 1", "prefix"):
        f, bad = fill_visible_controls(tag="Участок 1")
        fill_all_dates("late")
        u = upload_visible_file_links(pdf)
        log(f"  Участок 1: заполнено {f}, файлов {u}")
    if click_text_deepest("Добавить участок", "contains"):
        time.sleep(1.5)
        log("  ✓ '+ Добавить участок' нажато", "PASS")
        f, bad = fill_visible_controls(tag="Новый участок")
        fill_all_dates("late")
        u = upload_visible_file_links(pdf)
        log(f"  Новый участок: заполнено {f}, файлов {u}")
    else:
        log("  ⚠ '+ Добавить участок' не найдено", "WARN")
        ok = False
    return ok


def stage_form_dates():
    if not expand_section("Сроки"):
        return False
    ok = True
    if click_tab("Плановые даты", "exact"):
        n = fill_all_dates("late")
        log(f"  Плановые даты: {n}")
        ok = ok and n >= 5
    else:
        ok = False
    if click_tab("Фактические даты", "exact"):
        n = fill_all_dates("early")
        log(f"  Фактические даты: {n}")
    click_tab("Плановые даты", "exact")
    return ok


PERSON_KW = ["margulan", "маргулан"]
JS_SECTION_SELECTS = r"""
function vis(e){ return !!(e.offsetWidth || e.offsetHeight || e.getClientRects().length); }
var title = arguments[0], hdr = null;
var all = document.querySelectorAll('*');
for (var i = 0; i < all.length; i++) {
    var e = all[i];
    if (e.children.length === 0 && (e.textContent || '').trim() === title && vis(e)) { hdr = e; break; }
}
if (!hdr) return [];
var c = hdr;
for (var k = 0; k < 8 && c; k++) {
    c = c.parentElement;
    if (c && c.querySelectorAll('button.ui-select__trigger').length) break;
}
if (!c) return [];
return Array.prototype.slice.call(c.querySelectorAll('button.ui-select__trigger')).filter(vis);
"""


def select_person(trigger):
    """Выбрать в селекте ответственного 'Sh Margulan Ju' (через поиск по панели)."""
    for search in ("Margulan", "Sh Margulan", "Маргулан", None):
        panel = open_ui(trigger)
        if panel is None:
            continue
        got = select_in_panel(panel, keywords=PERSON_KW, search=search)
        if got:
            close_panels()
            return True
        close_panels()
        try:
            ActionChains(driver).send_keys(Keys.ESCAPE).perform()
        except Exception:
            pass
    return False


def stage_form_people():
    if not expand_section("Ответственные"):
        return False
    time.sleep(0.8)
    trs = driver.execute_script(JS_SECTION_SELECTS, "Ответственные") or []
    log(f"  Селектов ответственных: {len(trs)}")
    done = bad = 0
    for i in range(len(trs)):
        # список перечитываем: DOM мог перерисоваться после выбора
        cur = driver.execute_script(JS_SECTION_SELECTS, "Ответственные") or []
        if i >= len(cur):
            break
        t = cur[i]
        try:
            lab = driver.execute_script(JS_DATE_LABEL, t) or "?"
        except Exception:
            lab = "?"
        shown = (t.get_attribute("textContent") or "").strip()
        if "margulan" in shown.lower():
            done += 1
            continue
        scroll_to(t)
        ok = select_person(t)
        shown = (t.get_attribute("textContent") or "").strip()[:40]
        ok = ok and "margulan" in shown.lower()
        log(f"    [{lab}] → '{shown}' {'✓' if ok else '✗'}", "PASS" if ok else "WARN")
        if ok:
            done += 1
        else:
            bad += 1
    f2, bad2 = fill_visible_controls(tag="Ответственные (прочее)")
    log(f"  Ответственных выбрано (Sh Margulan Ju): {done}, ошибок: {bad}")
    return bad == 0 and done >= 1


def stage_form_extra():
    if not expand_section("Дополнительные характеристики"):
        return False
    f, bad = fill_visible_controls(tag="Доп. характеристики")
    log(f"  Полей/селектов заполнено: {f}, ошибок: {bad}")
    ok = bad == 0
    for lab in ["Кладовки", "Паркинг отапливаемый", "Видеонаблюдение",
                "Шумоизоляция между этажами", "Технический этаж",
                "Электроразводка", "Клапан приточного воздуха"]:
        r = toggle_on(lab)
        log(f"    Переключатель '{lab}': {'включён' if r else 'НЕ включён'}",
            "PASS" if r else "WARN")
        ok = ok and r
    return ok


def stage_form_photos():
    if not expand_section("Фотографии/рендеры"):
        return False
    start = len(find_all_deepest("Перетащите файлы сюда", "prefix"))
    log(f"  Зон загрузки на странице: {start}")
    if start == 0:
        return False
    done = 0
    skip = 0
    for i in range(6):
        zones = find_all_deepest("Перетащите файлы сюда", "prefix")
        if not zones:
            break
        zone = zones[min(skip, len(zones) - 1)]
        scroll_to(zone)
        img = create_test_image(i)
        if upload_to_element(zone, img):
            time.sleep(1.5)
            now = len(find_all_deepest("Перетащите файлы сюда", "prefix"))
            if now < len(zones):
                done += 1
                log(f"  ✓ Рендер {i + 1}/6 загружен ({os.path.basename(img)}), зон осталось {now}", "PASS")
            else:
                done += 1
                skip += 1
                log(f"  • Рендер {i + 1}/6 передан (зона не исчезла — иду к следующей)")
        else:
            skip += 1
    # «+ Добавить еще»: изображения, PDF, документы
    if click_text_deepest("Добавить еще", "contains"):
        time.sleep(1.5)
        extra = driver.execute_script(
            "var i = window.__lastFileInput; return (i && document.contains(i)) ? i : null;")
        pdf = create_test_pdf("passport_extra")
        if extra is not None:
            try:
                driver.execute_script("arguments[0].style.display='block';", extra)
                extra.send_keys(pdf)
                time.sleep(2.5)
                driver.execute_script("window.__lastFileInput = null;")
                log("  ✓ '+ Добавить еще': PDF загружен", "PASS")
            except Exception as e:
                log(f"  ⚠ '+ Добавить еще': {e}", "WARN")
        else:
            zs = find_all_deepest("Перетащите файлы сюда", "prefix")
            if zs and upload_to_element(zs[0], pdf):
                log("  ✓ '+ Добавить еще': PDF загружен в новую зону", "PASS")
    log(f"  Загружено рендеров: {done}/6")
    return done >= 6


# ==========================================
# ЭТАП 5: СОХРАНЕНИЕ
# ==========================================
def wait_save_result(timeout=15):
    end = time.time() + timeout
    while time.time() < end:
        if "/projects/create" not in driver.current_url and "/edit" not in driver.current_url:
            return "saved", ""
        for t in read_toasts():
            low = t.lower()
            if any(k in low for k in ["ошибк", "не удалось", "уже ", "существует",
                                      "обязательн", "заполните", "нельзя", "must be", "must not",
                                      "should", "invalid", "required", "cannot", "too long",
                                      "too short", "exceed"]):
                return "error", t
            if any(k in low for k in ["создан", "сохранен", "сохранён", "успешно"]):
                time.sleep(3)
                return "saved", t
        time.sleep(0.5)
    return "timeout", ""


def fix_limit_errors(msg):
    """Серверные лимиты вида 'X must be shorter than or equal to N characters' /
    'must not be greater than N' — подрезаем длинные значения полей до лимита."""
    m = re.search(r"(?:shorter|longer|less)\s+than\s+or\s+equal\s+to\s+(\d+)", msg or "", re.I) \
        or re.search(r"(?:не\s+более|не\s+длиннее|максимум)\D{0,20}(\d+)", msg or "", re.I)
    if not m:
        return 0
    n = int(m.group(1))
    cnt = driver.execute_script(
        """var n = arguments[0], c = 0;
        var els = document.querySelectorAll('input[type=text], input:not([type]), textarea');
        for (var i = 0; i < els.length; i++) {
            var e = els[i];
            if (e.readOnly || e.disabled) continue;
            if ((e.value || '').length > n) {
                var proto = e.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
                Object.getOwnPropertyDescriptor(proto, 'value').set.call(e, e.value.slice(0, n));
                e.dispatchEvent(new Event('input', {bubbles: true}));
                e.dispatchEvent(new Event('change', {bubbles: true}));
                c++;
            }
        }
        return c;""", n)
    log(f"  Лимит {n} симв.: подрезано полей: {cnt}", "INFO")
    return cnt


def combos():
    seq = [(PROJECT_KW, None, 0, 1), (PROJECT_KW, None, 1, 0), (PROJECT_KW, None, 0, 2),
           (PROJECT_KW, None, 1, 1), (PROJECT_KW, None, 2, 0)]
    for idx in range(6):
        seq.append((None, idx, 0, 0))
    return seq[:SAVE_MAX_COMBOS]


def stage_save():
    attempts = [None] + combos()
    for n, combo in enumerate(attempts, 1):
        if combo is not None:
            kw, idx, q, b = combo
            log(f"  Повторная попытка #{n}: проект={kw or idx}, очередь#{q}, блок#{b}")
            driver.execute_script("window.scrollTo(0,0);")
            res = choose_pqb(project_kw=kw, project_idx=idx, q=q, b=b)
            if not res:
                continue
            STATE["combo"] = res
            fill_visible_controls(tag=f"повтор{n}")
        if not click_button(["Сохранить"], wait=5):
            log("  ⚠ Кнопка 'Сохранить' не найдена", "WARN")
            return False
        result, msg = wait_save_result(15)
        for _fix in range(3):                      # серверный лимит -> подрезать и пересохранить
            if result == "error" and fix_limit_errors(msg):
                time.sleep(1)
                click_button(["Сохранить"], wait=5)
                result, msg = wait_save_result(15)
            else:
                break
        if result == "saved":
            time.sleep(3)
            STATE["url"] = driver.current_url.split("#")[0]
            log(f"  ✓ Паспорт сохранён: {STATE['url']} ({msg})", "PASS")
            return True
        errs = validation_errors()
        log(f"  ✗ Не сохранилось ({result}): {msg or '—'}; ошибки формы: {errs[:8]}", "WARN")
        shot(f"save_fail_{n}")
        time.sleep(3)
    return False


# ==========================================
# ЭТАП 6: КАРТОЧКА И РЕДАКТИРОВАНИЕ
# ==========================================
def edit_input_by_label(label, value):
    for e in driver.find_elements(
            By.XPATH, f"//*[normalize-space(text())='{label}']/following::input[1]"):
        if e.is_displayed() and e.is_enabled():
            scroll_to(e)
            type_text(e, value)
            return True
    return False


def stage_view_and_edit():
    time.sleep(2)
    txt = page_text()
    ok = True
    if STATE["status"]:
        has = STATE["status"].lower() in txt
        log(f"  Статус '{STATE['status']}' на карточке: {'есть' if has else 'нет'}",
            "PASS" if has else "WARN")
        ok = ok and has
    shot("passport_card")
    log(f"  Кнопка 'Удалить паспорт' на странице: "
        f"{'есть (не нажимаю)' if find_buttons(['Удалить паспорт', 'Удалить']) else 'не найдена'}")

    if not click_button(["Редактировать"], wait=8):
        log("  ⚠ Кнопка 'Редактировать' не найдена", "WARN")
        return False
    time.sleep(3)
    block_native_file_dialog()
    log(f"  Режим редактирования: {driver.current_url}")

    changed = 0
    if edit_input_by_label("Адрес", NEW_ADDRESS):
        changed += 1
        log(f"  ✓ Адрес изменён: {NEW_ADDRESS}", "PASS")
    if expand_section("Площади") and edit_input_by_label("Общая площадь", "2000"):
        changed += 1
        log("  ✓ Общая площадь = 2000", "PASS")
    if expand_section("Атрибуты") and click_tab("Основная информация", "exact"):
        if edit_input_by_label("Этажность", "12"):
            changed += 1
            log("  ✓ Этажность = 12", "PASS")
    if changed == 0:
        log("  ⚠ Ничего изменить не удалось", "WARN")
        shot("edit_nothing")
        return False

    if not click_button(["Сохранить"], wait=5):
        log("  ⚠ Кнопка 'Сохранить' в режиме редактирования не найдена", "WARN")
        return False
    result, msg = wait_save_result(12)
    log(f"  Сохранение после редактирования: {result} {msg}",
        "PASS" if result != "error" else "WARN")
    time.sleep(3)
    driver.refresh()
    time.sleep(4)
    saved = NEW_ADDRESS.lower() in page_text()
    log(f"  Новый адрес после обновления страницы: {'есть' if saved else 'не найден'}",
        "PASS" if saved else "WARN")
    shot("passport_after_edit")
    return ok and result != "error" and saved


# ==========================================
# ОТЧЁТ
# ==========================================
def save_passport_results():
    path = Path(os.environ["PASSPORT_RESULT_PATH"])
    payload = {"run_id": os.environ["PASSPORT_RUN_ID"],
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
    log(f"АВТОТЕСТ «ПАСПОРТ ПРОЕКТОВ» {STAMP}")
    log("=" * 60)
    try:
        init_driver()
        driver.get(PROJECTS_URL)
        wait_for_state(lambda: is_login_page() or passport_list_ready())
        if not step("Вход и открытие «Паспорта проектов»", stage_login):
            return
        step("Список: фильтры, вид, поиск, карточка проекта", stage_list_page)
        if not step("Создать паспорт → Отмена → снова открыть", stage_cancel_create):
            return
        step("Форма 1-2: О проекте и Площади", stage_form_basic)
        step("Форма 3: Атрибуты (7 вкладок, даты ТУ, файлы)", stage_form_attributes)
        step("Форма 4: Документация (файлы + комментарии)", stage_form_docs)
        step("Форма 5: Земельный участок", stage_form_land)
        step("Форма 6: Сроки (плановые/фактические даты)", stage_form_dates)
        step("Форма 7: Ответственные", stage_form_people)
        step("Форма 8: Дополнительные характеристики", stage_form_extra)
        step("Форма 9: Фотографии/рендеры (6 штук)", stage_form_photos)
        if step("Сохранение паспорта", stage_save):
            step("Карточка паспорта: статус и редактирование", stage_view_and_edit)
    except Exception as e:
        RUN_ERROR = f"{type(e).__name__}: {e}"
        log(f"КРИТИЧЕСКАЯ ОШИБКА: {e}", "FAIL")
        shot("critical_error")
    finally:
        save_passport_results()
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


if __name__ == "__main__" and os.environ.get("PASSPORT_NO_RUN") != "1":
    if os.environ.get("PASSPORT_MANAGED") == "1":
        run()
        raise SystemExit(1 if RUN_ERROR or any(not ok for _, ok in RESULTS) else 0)
    from run_workflow_and_report import run_passport
    raise SystemExit(run_passport(__file__, sys.argv[1:]))