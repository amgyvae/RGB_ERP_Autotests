# -*- coding: utf-8 -*-
"""
АВТОТЕСТ: «Финансы» — ДДС и ГФР (полный сценарий).

ЧАСТЬ 1. ДДС  (/finance/cashflow)
  1. Открываем раздел: до «Запросить» — пустая страница («Нет данных»)
  2. «Запросить» -> таблица «Статьи расхода». Разворачиваем/прокручиваем ВСЮ таблицу, считаем:
     сколько статей (по уровням), конечных статей, итого «Без НДС / С НДС», карточки
     «Итого / Услуги / Материалы», сверяем сумму статей 1-го уровня с «Итого».
     Анализ уходит в лог и в Telegram.
  3. Остальные кнопки: фильтры Проект / Очередь / Блок / Период оплаты / Статьи / Тип
     (открыть и посмотреть варианты, выбрать), «Сбросить», повторный «Запросить»
  4. «Выгрузить» — проверяем, что файл реально скачался

ЧАСТЬ 2. ГФР  (/finance/gfr)
  5. Главная ГФР: «Все этапы / Строительство / Проектирование / Завершённые», поиск,
     раскрытие карточки проекта (таблица графиков: этап, наименование, статус, версия...)
  6. «Создать ГФР»: Проект (Flagman) + Наименование + «Взять за основу» —
     создаются ВСЕ 4 вида: Без основания / Смета / ГПР / Файл Excel.
     Первый успешно созданный (по умолчанию «Без основания») идёт дальше по сценарию.
  7. Карточка ГФР: секции, вкладки, «Редактировать» / «Сменить маршрут» (открыть и закрыть)
  8. Маршрут согласования: «Добавить этап» -> Бейсембаев Куаныш Едилович
  9. Утверждающий: Алдажаров Диас
 10. Обсуждение: сообщение + файл
 11. «Открыть график»: Таблица / Диаграмма / Развернуть все / Обновить
 12. «Добавить строку»: Тип строки, Вид работ, Ед. изм., Количество, Дата С, Дата ПО,
     Сумма без НДС, Сумма с НДС, Примечание — ВСЁ заполняется
 13. «Выгрузить в Excel» (проверка скачанного файла), «Загрузить из Excel» (получится — супер,
     нет — в отчёте)
 14. «История графика», ещё одна строка (другой тип)
 15. «Отправить на согласование» -> «Согласовать» -> Диас: «Утвердить» -> «Подписать»

Кнопка «Удалить» НЕ нажимается нигде.

ОТЧЁТЫ: общий run_workflow_and_report.py передаёт результаты в sheet_reporter.py
и отправляет Telegram: краткий успех либо ошибки/пропуски со скриншотом текущего запуска.
Анализ ДДС сохраняется в локальных JSON и логах. Подробности — FINANCE_README.md.

ЗАВИСИМОСТИ: pip install openpyxl requests gspread google-auth
  (sheet_reporter.py и service_account.json — рядом со скриптом, как у остальных автотестов)

НЕ ПРОВЕРЕНО НА ЖИВОМ DOM (`# TODO VERIFY`): дерево «Вид работ», доп. поля в модалке
«Взять за основу = Смета / ГПР / Файл Excel», период оплаты в ДДС, названия кнопок
согласования/подписи. При сбое в логе будет ⚠ + скриншот debug_*.png.
"""

from artifact_paths import SCREENS_DIR, LOGS_DIR, screen_path, log_path
from env_config import env, env_list, is_headless  # секреты — из .env / GitHub Secrets

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
import base64
import zipfile
import tempfile
import shutil
import json
from pathlib import Path
import datetime
from datetime import datetime as _dt_cls
from xml.sax.saxutils import escape as xml_escape
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains

# `datetime` в хелперах из других скриптов — это КЛАСС (from datetime import datetime),
# а в этом файле нужен и модуль (для дат). Поэтому: модуль — dtm, класс — datetime.
dtm = datetime
datetime = _dt_cls


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
DDS_LOGIN = env("RGB_ACCOUNT2_LOGIN", env("RGB_ACCOUNT1_LOGIN"))
DDS_PASS = env("RGB_ACCOUNT2_PASSWORD", env("RGB_ACCOUNT1_PASSWORD"))


def init_driver():
    global driver
    driver = webdriver.Chrome(
        service=Service(ChromeDriverManager().install()), options=_chrome_options)
    driver.implicitly_wait(0)


# Согласующий (Ерлан Талгатович)
login_val = env("RGB_ACCOUNT2_LOGIN", env("RGB_ACCOUNT1_LOGIN"))
pass_val = env("RGB_ACCOUNT2_PASSWORD", env("RGB_ACCOUNT1_PASSWORD"))

# Утверждающий (Талгат Ерланович) 
SECOND_LOGIN = env("RGB_ACCOUNT3_LOGIN", env("RGB_ACCOUNT1_LOGIN"))
SECOND_PASS = env("RGB_ACCOUNT3_PASSWORD", env("RGB_ACCOUNT1_PASSWORD_ALT"))

BASE_URL = "https://testportal.rgbgroup.kz/"
CASHFLOW_URL = BASE_URL + "finance/cashflow"
GFR_URL = BASE_URL + "finance/gfr"
WAIT = 15

STAMP = datetime.now().strftime('%d%m-%H%M%S')
PROJECT_QUERY = "Flagman"
APPROVER_QUERY = env("RGB_APPROVER_QUERY", 'Ерлан')
UTV_QUERY = env("RGB_UTV_QUERY", 'Талгат')
UTV_KEYS = ['талгат ерланович', 'талгат', 'ерланович', 'алдажаров диас андреевич', 'алдaжаров диасс андреевичч']

# «Взять за основу»: порядок создания. ПЕРВЫЙ успешно созданный идёт по основному сценарию.
GFR_BASES = ["Без основания", "Смета", "ГПР", "Файл Excel"]

# Идти дальше после «Отправить на согласование» (Согласовать -> Утвердить)
CONTINUE_APPROVAL = True

TO_SEND = ["Отправить на согласование"]
TO_APPROVE = ["Согласовать", "Согласовать график", "Согласовать ГФР"]
TO_CONFIRM = ["Утвердить", "Утвердить график", "Утвердить ГФР"]

# Кнопку «Удалить» не нажимаем никогда (в этом скрипте её вообще нет в сценарии).
CLICK_DELETE_BUTTON = False

DOWNLOAD_DIR = os.environ.get("DOWNLOAD_DIR", os.path.join(os.path.expanduser("~"), "Downloads"))
WORK_DIR = os.path.join(tempfile.gettempdir(), f"finance_autotest_{STAMP}")
os.makedirs(WORK_DIR, exist_ok=True)

# Отчётность выполняет только run_workflow_and_report.py.
# Результаты сопоставляются с 27 названиями из finance_checks.json.
RUN_ERROR = ""
FAILED_SCREENSHOTS = []

STATE = {"url": None, "exported": None, "dds": {}, "created": [], "numbers": {}}
RESULTS = []        # (название, ok)
REASONS = {}        # название -> причина провала
LOG_LINES = []
_RUN_STARTED = time.time()

LOG_FILE_PATH = log_path(f"finance_log_{datetime.now().strftime('%d%m_%H%M%S')}.txt")
try:
    _LOG_FILE = open(LOG_FILE_PATH, "w", encoding="utf-8", buffering=1)
except Exception:
    _LOG_FILE = None


# ==========================================
# ПРОВЕРКИ / ЭТАПЫ (с причинами провала для Telegram)
# ==========================================
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
    if not ok:
        shot(f"fail_{label}")
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
    record(label, ok, reason="" if ok else (_last_problem(start_idx) or "см. лог"))
    return ok


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


def card_ready():
    return bool(find_buttons(["Открыть график"])) or "основная информация" in page_text()


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


def shot(name):
    try:
        safe = re.sub(r'[^\w\-]+', '_', name)[:40]
        run_tag = os.environ.get("FINANCE_RUN_ID", STAMP)
        path = screen_path(f"debug_{safe}_{run_tag}_{time.time_ns()}.png")
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
    # Login news may arrive after the first page has already loaded.
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

    # 1. UI logout
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

    # 2. Keycloak endpoint logout
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

    # 3. Clear cookies
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

def ensure_account(login_value, password_value):
    """Use the account assigned to this workflow stage; stop if switching fails."""
    if CURRENT_LOGIN == login_value and not is_login_page():
        return True
    if not is_login_page():
        logout_current_account()
    return login_with(login_value, password_value)




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

def route_has_approver():
    txt = page_text().lower()
    m = re.search(r"маршрут согласования(.*?)утверждающий", txt, re.S)
    seg = m.group(1) if m else txt
    return any(word in seg for word in ("ерлан", "талгатович", "бейсембаев", "куаныш", "едилович"))

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
    picked = select_in_panel(panel, keywords=["ерлан талгатович", "ерлан", "талгатович", "бейсембаев куаныш едилович"],
                             search=APPROVER_QUERY)
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
    log(f"  ⚠ Согласующий ({APPROVER_QUERY}) не появился в маршруте", "WARN")
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
    msg = f"Автотест: сообщение по ГФР {STAMP}"
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
    ok = "автотест: сообщение по гфр" in txt.lower()
    log(f"  Сообщение в ленте: {'есть' if ok else 'нет'}", "PASS" if ok else "WARN")
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


# ==========================================
# ОБЩЕЕ: ВХОД, НАВИГАЦИЯ, ДЕНЬГИ
# ==========================================
def stage_login():
    log(f"  URL: {driver.current_url}")
    accounts_to_try = [
        (DDS_LOGIN, DDS_PASS),
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

    for login_user, pass_user in creds:
        if is_login_page():
            if not login_with(login_user, pass_user):
                continue
        elif CURRENT_LOGIN != login_user:
            logout_current_account()
            if not login_with(login_user, pass_user):
                continue
        time.sleep(2)
        dismiss_news_popup(wait=2)
        if "finance" not in driver.current_url and "cashflow" not in driver.current_url:
            driver.get(CASHFLOW_URL)
            time.sleep(2)
            dismiss_news_popup(wait=1)
        wait_for_state(lambda: is_login_page() or bool(find_buttons(["Запросить"])) or "finance" in driver.current_url or "cashflow" in driver.current_url, timeout=20)
        dismiss_news_popup(wait=1)
        if is_login_page():
            continue
        if "cashflow" not in driver.current_url and "finance" not in driver.current_url:
            nav_finance("ДДС", "cashflow", CASHFLOW_URL)
            time.sleep(2)
        ok = "finance" in driver.current_url or "cashflow" in driver.current_url or "gfr" in driver.current_url or bool(find_buttons(["Запросить"])) or any(w in page_text().lower() for w in ("ддс", "гфр", "статьи расхода", "график финансирования"))
        if ok:
            log(f"  URL после входа ({login_user}): {driver.current_url}", "PASS")
            return True
        else:
            log(f"  ⚠ Аккаунт {login_user} перенаправлен на {driver.current_url}, пробуем резервный аккаунт...", "WARN")

    ok = "finance" in driver.current_url or "cashflow" in driver.current_url or "gfr" in driver.current_url or bool(find_buttons(["Запросить"])) or any(w in page_text().lower() for w in ("ддс", "гфр", "статьи расхода", "график финансирования"))
    log(f"  URL после входа: {driver.current_url}", "PASS" if ok else "WARN")
    return ok


def open_sidebar_finance():
    """Раскрывает пункт 'Финансы' в боковом меню."""
    try:
        clicked = driver.execute_script("""
            var aside = document.querySelector('aside') || document.body;
            var els = aside.querySelectorAll('button, a, span, div, li');
            for (var i = 0; i < els.length; i++) {
                var e = els[i];
                if (!(e.offsetWidth || e.offsetHeight)) continue;
                var t = (e.textContent || '').trim();
                if (t.indexOf('Финансы') >= 0 && e.children.length <= 2) {
                    e.click();
                    return true;
                }
            }
            return false;
        """)
        if clicked:
            time.sleep(1.5)
            return True
    except Exception:
        pass
    if click_text_deepest("Финансы", "contains"):
        time.sleep(1.5)
        return True
    return False


def nav_finance(item, url_part, url):
    """Меню «Финансы» -> пункт (ДДС / ГФР). Если по меню не вышло — прямой URL."""
    if url_part in driver.current_url:
        return True

    # 1. Прямые ссылки на странице
    try:
        links = [a for a in driver.find_elements(By.XPATH, f"//a[contains(@href, '{url_part}')]") if a.is_displayed()]
        if links:
            click_el(links[0])
            time.sleep(3)
            if url_part in driver.current_url or bool(find_buttons(["Запросить"])):
                return True
    except Exception:
        pass

    # 2. Раскрываем «Финансы» в боковом меню
    open_sidebar_finance()

    # 3. Кликаем нужный подраздел через DOM и хелперы с поддержкой синонимов
    search_terms = [item.lower()]
    if "ддс" in item.lower():
        search_terms.extend(["движение", "cashflow", "средств", "денег"])
    elif "гфр" in item.lower():
        search_terms.extend(["финансирован", "график", "gfr"])

    try:
        clicked = driver.execute_script("""
            var aside = document.querySelector('aside') || document.body;
            var links = aside.querySelectorAll('a, button, span, div, li');
            var terms = arguments[0];
            var urlPart = arguments[1];
            for (var i = 0; i < links.length; i++) {
                var a = links[i];
                if (!(a.offsetWidth || a.offsetHeight)) continue;
                var t = (a.textContent || '').trim().toLowerCase();
                var h = (a.getAttribute('href') || '').toLowerCase();
                if (urlPart && h.indexOf(urlPart) >= 0) {
                    a.click();
                    return true;
                }
                for (var j = 0; j < terms.length; j++) {
                    if (t.indexOf(terms[j]) >= 0 && a.children.length <= 1) {
                        a.click();
                        return true;
                    }
                }
            }
            return false;
        """, search_terms, url_part)
        if clicked:
            time.sleep(3)
            if url_part in driver.current_url or bool(find_buttons(["Запросить"])):
                return True
    except Exception:
        pass

    for t in search_terms:
        if click_button([t]) or click_text_deepest(t, "contains"):
            time.sleep(3)
            if url_part in driver.current_url or bool(find_buttons(["Запросить"])):
                return True

    # 4. Fallback: прямой переход по URL
    driver.get(url)
    time.sleep(3)
    dismiss_news_popup(wait=2)
    return url_part in driver.current_url or bool(find_buttons(["Запросить"])) or any(t in page_text().lower() for t in search_terms)


def money(s):
    return float(s.replace("\u00a0", "").replace(" ", "").replace("\n", "").replace(",", "."))


def fmt(x):
    return f"{x:,.2f}".replace(",", " ").replace(".", ",")


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


# ==========================================
# ЧАСТЬ 1. ДДС
# ==========================================
MONEY_RE = re.compile(r"^-?\d[\d\s\u00a0]*[.,]\d{2}$")
ART_RE = re.compile(r"^(\d+(?:\.\d+)*)\.?\s+(\S.*)$")

JS_SCROLL_STEP = r"""
var step = arguments[0];
var best = null, bh = 0, els = document.querySelectorAll('*');
for (var i = 0; i < els.length; i++) {
    var e = els[i], cs = getComputedStyle(e);
    if ((cs.overflowY === 'auto' || cs.overflowY === 'scroll') && e.scrollHeight > e.clientHeight + 40
        && e.clientHeight > 200 && e.scrollHeight > bh) { bh = e.scrollHeight; best = e; }
}
if (!best) { best = document.scrollingElement || document.documentElement; }
if (step === 0) { best.scrollTop = 0; return [0, best.scrollHeight, best.clientHeight, 0]; }
var before = best.scrollTop;
best.scrollTop = before + best.clientHeight * 0.8;
return [best.scrollTop, best.scrollHeight, best.clientHeight, before];
"""


CODE_ONLY_RE = re.compile(r"^\d+(?:\.\d+)*\.?$")


def parse_articles(text, acc):
    """Из innerText вытаскивает статьи расхода: код + название + две суммы (без НДС / с НДС).
    Ячейки таблицы могут идти и через перевод строки, и через TAB в одной строке."""
    toks = [t.strip() for t in re.split(r"[\n\t\r]+", text) if t.strip()]
    i = 0
    while i < len(toks):
        s_ = toks[i]
        code = name = None
        if not MONEY_RE.match(s_):
            m = ART_RE.match(s_)
            if m:
                code, name, j = m.group(1), m.group(2).strip(), i + 1
            elif CODE_ONLY_RE.match(s_) and i + 1 < len(toks) and not MONEY_RE.match(toks[i + 1]):
                code, name, j = s_.rstrip("."), toks[i + 1], i + 2
        if code:
            nums = []
            while j < len(toks) and len(nums) < 2 and MONEY_RE.match(toks[j]):
                nums.append(money(toks[j]))
                j += 1
            if len(nums) == 2:
                acc.setdefault(code, (name, nums[0], nums[1]))
                i = j
                continue
        i += 1


def parse_cards(text):
    out = {}
    for name in ("Итого", "Услуги", "Материалы"):
        mm = re.search(name + r"\s.*?БЕЗ НДС\s+(-?[\d\s\u00a0]+[.,]\d{2})\s+С НДС\s+(-?[\d\s\u00a0]+[.,]\d{2})",
                       text, re.S | re.I)
        if mm:
            out[name] = (money(mm.group(1)), money(mm.group(2)))
    return out


def collect_dds_table():
    """Прокручивает всю таблицу, собирает статьи (устойчиво к виртуализации списка)."""
    acc = {}
    cards = {}
    driver.execute_script(JS_SCROLL_STEP, 0)
    time.sleep(0.8)
    for n in range(60):
        txt = driver.execute_script("return document.body.innerText;") or ""
        parse_articles(txt, acc)
        if not cards:
            cards = parse_cards(txt)
        pos, height, client, before = driver.execute_script(JS_SCROLL_STEP, 1)
        time.sleep(0.5)
        if pos + client >= height - 5 or pos == before:
            txt = driver.execute_script("return document.body.innerText;") or ""
            parse_articles(txt, acc)
            break
    driver.execute_script(JS_SCROLL_STEP, 0)
    return acc, cards


def analyze_dds(acc, cards, title="ДДС"):
    codes = list(acc.keys())
    by_level = {}
    for c in codes:
        by_level.setdefault(c.count(".") + 1, []).append(c)
    leaves = [c for c in codes if not any(o != c and o.startswith(c + ".") for o in codes)]
    top = by_level.get(1, [])
    sum_wo = sum(acc[c][1] for c in top)
    sum_w = sum(acc[c][2] for c in top)
    lines = [f"{title}: статей расхода всего {len(codes)} "
             f"(" + ", ".join(f"{k}-й ур.: {len(v)}" for k, v in sorted(by_level.items())) + f"), "
             f"конечных статей: {len(leaves)}",
             f"{title}: сумма групп 1-го уровня: без НДС {fmt(sum_wo)} / с НДС {fmt(sum_w)}"]
    for name, (a, b) in cards.items():
        lines.append(f"{title}: карточка «{name}»: без НДС {fmt(a)} / с НДС {fmt(b)}")
    for c in top:
        lines.append(f"    {c}. {acc[c][0]}: {fmt(acc[c][1])} / {fmt(acc[c][2])}")
    for l in lines:
        log("  " + l)
    return {"count": len(codes), "levels": {k: len(v) for k, v in by_level.items()},
            "leaves": len(leaves), "sum_wo": sum_wo, "sum_w": sum_w, "cards": cards,
            "top": [(c, acc[c][0], acc[c][1], acc[c][2]) for c in top], "lines": lines}


def click_query():
    if click_button(["Запросить"], wait=5):
        time.sleep(5)
        return True
    return False


def stage_dds_open():
    if not nav_finance("ДДС", "cashflow", CASHFLOW_URL):
        log("  ⚠ Раздел ДДС не открылся", "WARN")
        return False
    time.sleep(2)
    txt = page_text()
    ok = "дds" in txt or "ддс" in txt
    empty = "нет данных" in txt
    log(f"  ✓ ДДС открыт: {driver.current_url}", "PASS")
    log(f"  До «Запросить»: {'пусто («Нет данных»)' if empty else 'данные уже есть'}",
        "PASS" if empty else "INFO")
    for b in ["Запросить", "Выгрузить", "Сбросить"]:
        has = bool(find_buttons([b])) or ("сбросить" in txt if b == "Сбросить" else False)
        log(f"  Кнопка «{b}»: {'есть' if has else 'нет'}", "PASS" if has else "WARN")
        ok = ok and has
    return ok


def stage_dds_query_analysis():
    if not click_query():
        log("  ⚠ Кнопка «Запросить» не найдена", "WARN")
        return False
    acc, cards = {}, {}
    for _wait in range(8):                      # ждём, пока загрузится таблица (до ~40 сек)
        acc, cards = collect_dds_table()
        if acc:
            break
        log(f"  Таблица ещё не загрузилась (попытка {_wait + 1}/8)...")
        time.sleep(4)
    if not acc:
        log("  ⚠ Статьи расхода не найдены после «Запросить»", "WARN")
        shot("dds_no_articles")
        return False
    res = analyze_dds(acc, cards)
    STATE["dds"] = res
    # проверки сумм
    ok_total = True
    if "Итого" in cards:
        d = abs(res["sum_wo"] - cards["Итого"][0])
        ok_total = d < 0.06
        record("ДДС: сумма статей 1-го уровня = «Итого»", ok_total,
               f"статьи {fmt(res['sum_wo'])} vs карточка {fmt(cards['Итого'][0])}",
               reason=f"разница {fmt(d)}")
    if all(k in cards for k in ("Итого", "Услуги", "Материалы")):
        d = abs(cards["Услуги"][0] + cards["Материалы"][0] - cards["Итого"][0])
        record("ДДС: «Услуги» + «Материалы» = «Итого»", d < 0.06,
               f"{fmt(cards['Услуги'][0])} + {fmt(cards['Материалы'][0])} vs {fmt(cards['Итого'][0])}",
               reason=f"разница {fmt(d)}")
    return res["count"] > 0


def stage_dds_toggle_rows():
    """Свернуть/развернуть первую группу статей (кружок-шеврон слева от названия)."""
    acc = STATE["dds"]
    if not acc or not acc.get("top"):
        return True
    code, name = acc["top"][0][0], acc["top"][0][1]
    label = f"{code}. {name}"
    el = driver.execute_script("""
        var t = arguments[0], all = document.querySelectorAll('*');
        for (var i = 0; i < all.length; i++) {
            var e = all[i];
            if (e.children.length || !(e.offsetWidth || e.offsetHeight)) continue;
            if ((e.textContent || '').trim() === t) return e;
        }
        return null;""", label)
    if not el:
        log("  • Строка первой группы не найдена — сворачивание пропускаю", "WARN")
        return True
    tog = driver.execute_script("""
        var e = arguments[0];
        for (var k = 0; k < 4 && e; k++) {
            e = e.parentElement;
            if (!e) break;
            var b = e.querySelector('button, [role=button], svg');
            if (b) return b;
        }
        return null;""", el)
    if not tog:
        log("  • Кнопка сворачивания не найдена", "WARN")
        return True
    rows_before = len(re.findall(r"\n\d+(?:\.\d+)+\s", driver.execute_script(
        "return document.body.innerText;") or ""))
    hard_click(tog)
    time.sleep(1)
    rows_mid = len(re.findall(r"\n\d+(?:\.\d+)+\s", driver.execute_script(
        "return document.body.innerText;") or ""))
    hard_click(tog)
    time.sleep(1)
    rows_after = len(re.findall(r"\n\d+(?:\.\d+)+\s", driver.execute_script(
        "return document.body.innerText;") or ""))
    log(f"  Группа «{label}»: видимых вложенных строк {rows_before} → {rows_mid} → {rows_after}",
        "PASS" if rows_mid != rows_before else "INFO")
    return True


def list_select_options(trigger, limit=8):
    panel = open_ui(trigger)
    if panel is None:
        return None
    opts = [o["text"] for o in panel_options(panel)]
    return opts[:limit], len(opts)


def stage_dds_filters_and_buttons():
    ok = True
    trs = visible_selects()
    log(f"  Фильтров-селектов на странице: {len(trs)}")
    for t in trs:
        name = (t.get_attribute("textContent") or "").strip()
        try:
            r = list_select_options(t)
            if r:
                log(f"  Фильтр «{name}»: вариантов {r[1]}, первые: {r[0]}", "PASS")
            else:
                log(f"  • Фильтр «{name}» не открывается (возможно, отключён)", "INFO")
        except Exception as e:
            log(f"  ⚠ Фильтр «{name}»: {e}", "WARN")
        close_panels()
        esc()

    # Период оплаты: открыть календарь, выбрать диапазон (первый/последний доступный день)
    if click_text_deepest("Период оплаты", "contains"):
        time.sleep(1.2)
        cells = calendar_cells()
        if cells:
            log(f"  ✓ «Период оплаты»: календарь открыт, дней доступно {len(cells)}", "PASS")
            try:
                click_el(cells[0])
                time.sleep(0.6)
                cells = calendar_cells() or cells
                click_el(cells[-1])
                time.sleep(1)
                log("  ✓ Период выбран (с первого по последний доступный день)", "PASS")
            except Exception as e:
                log(f"  • Выбор периода: {e}", "WARN")
        else:
            log("  • «Период оплаты»: календарь не распознан", "WARN")
        esc()
    else:
        log("  ⚠ «Период оплаты» не найден", "WARN")
        ok = False

    # Проект -> Очередь -> Блок -> Тип, затем «Запросить»
    def pick_first(prefix, kw=None):
        for t in visible_selects():
            tx = (t.get_attribute("textContent") or "").strip()
            if tx.lower().startswith(prefix.lower()):
                panel = open_ui(t)
                if not panel:
                    return None
                got = select_in_panel(panel, keywords=kw, index=None if kw else 0) if kw \
                    else select_in_panel(panel, index=0)
                close_panels()
                esc()
                return got
        return None

    for pref, kw in [("Проект", ["flagman"]), ("Очередь", None), ("Блок", None), ("Тип", None)]:
        got = pick_first(pref, kw)
        log(f"  Фильтр «{pref}» → {got or 'не выбран (отключён / нет вариантов)'}",
            "PASS" if got else "INFO")
        time.sleep(0.8)
    if click_query():
        acc, cards = collect_dds_table()
        log(f"  «Запросить» с фильтрами: статей {len(acc)}, карточки: "
            f"{ {k: fmt(v[0]) for k, v in cards.items()} }", "PASS")
    else:
        ok = False
    # Сбросить
    if click_button(["Сбросить"], wait=3) or click_text_deepest("Сбросить", "exact"):
        time.sleep(2)
        log("  ✓ «Сбросить» нажато", "PASS")
        txt = page_text()
        log(f"  После сброса фильтров: {'«Проект: все»' if 'проект: все' in txt else 'фильтры могли не сброситься'}",
            "PASS" if "проект: все" in txt else "WARN")
    else:
        log("  ⚠ «Сбросить» не найдено", "WARN")
        ok = False
    return ok


def stage_dds_export():
    if not (re.search(r"\n\d+\.\s", driver.execute_script("return document.body.innerText;") or "")):
        click_query()
    before = snapshot_downloads()
    t0 = time.time()
    if not click_button(["Выгрузить"], wait=5):
        log("  ⚠ Кнопка «Выгрузить» не найдена", "WARN")
        return False
    f = wait_new_download(before, t0, timeout=40, ext=(".xlsx", ".xls", ".csv", ".pdf"))
    if f:
        STATE["dds_file"] = f
        log(f"  ✓ Файл скачан: {f} ({os.path.getsize(f)} байт)", "PASS")
        return True
    log(f"  ⚠ Файл не появился в {DOWNLOAD_DIR}. Уведомления: {read_toasts()}", "WARN")
    return False


# ==========================================
# ЧАСТЬ 2. ГФР: СПИСОК
# ==========================================
NUM_GFR_RE = re.compile(r"ГФР-\d{4}-\d{2}-\d+/\d+")


def stage_gfr_list():
    # The ДДС account has creation rights for ГФР as well.
    if not ensure_account(DDS_LOGIN, DDS_PASS):
        return False
    if not nav_finance("ГФР", "gfr", GFR_URL):
        log("  ⚠ Раздел ГФР не открылся", "WARN")
        return False
    time.sleep(2)
    ok = True
    for prefix in ["Строительство", "Проектирование", "Завершенные", "Все этапы"]:
        if click_text_deepest(prefix, "prefix"):
            time.sleep(1.4)
            txt = driver.execute_script("return document.body.innerText;") or ""
            m = re.search(prefix + r"\s*·\s*(\d+)", txt)
            cards = len(re.findall(r"\d+\s+график", txt))
            log(f"  ✓ Фильтр «{prefix}»" + (f" (счётчик: {m.group(1)})" if m else "")
                + f", карточек с графиками на экране: {cards}", "PASS")
        else:
            log(f"  ⚠ Фильтр «{prefix}» не найден", "WARN")
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
        log(f"  Поиск «{PROJECT_QUERY}»: {'найдено' if found else 'не найдено'}",
            "PASS" if found else "WARN")
        ok = ok and found
        # раскрыть карточку проекта: таблица графиков
        if click_text_deepest(PROJECT_QUERY, "contains"):
            time.sleep(3)
            txt = driver.execute_script("return document.body.innerText;") or ""
            nums = NUM_GFR_RE.findall(txt)
            statuses = {}
            for w in ["Черновик", "На согласовании", "Архив", "Утвержден", "Согласован"]:
                c = txt.count(w)
                if c:
                    statuses[w] = c
            log(f"  ✓ Карточка проекта раскрыта: графиков в таблице {len(set(nums))}, статусы: {statuses}",
                "PASS")
            click_text_deepest(PROJECT_QUERY, "contains")   # свернуть обратно
            time.sleep(1.2)
        else:
            log("  ⚠ Карточка проекта не найдена", "WARN")
            ok = False
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
    return ok


# ==========================================
# ЧАСТЬ 2. ГФР: СОЗДАНИЕ (4 вида основания)
# ==========================================
def create_gfr_excel(path=None):
    path = path or os.path.join(WORK_DIR, f"gfr_import_{STAMP}.xlsx")
    d0 = datetime.now()
    rows = [
        ["№", "Наименование", "Ед. изм.", "Кол-во", "Дата С", "Дата ПО", "Сумма без НДС", "Сумма с НДС"],
        [1, f"Автотест работа {STAMP}", "усл", 10,
         (d0 + dtm.timedelta(days=5)).strftime("%d.%m.%Y"),
         (d0 + dtm.timedelta(days=35)).strftime("%d.%m.%Y"), 100000, 116000],
        [2, f"Автотест материал {STAMP}", "шт", 5,
         (d0 + dtm.timedelta(days=10)).strftime("%d.%m.%Y"),
         (d0 + dtm.timedelta(days=40)).strftime("%d.%m.%Y"), 50000, 58000],
    ]
    try:
        import openpyxl
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "ГФР"
        for r in rows:
            ws.append(r)
        wb.save(path)
    except ImportError:
        _xlsx_minimal(path, rows)
    log(f"    Excel для ГФР создан: {path}")
    return path


def fill_gfr_template(src, dst):
    """Preserve the site's merged header and formulas; fill writable data rows."""
    try:
        import openpyxl
        wb = openpyxl.load_workbook(src)
        ws = wb.active
        header = None
        columns = {}
        for row in ws.iter_rows(min_row=1, max_row=min(ws.max_row, 30)):
            names = {str(c.value or "").strip().casefold(): c.column for c in row}
            if "наименование" in names and "тип строки" in names:
                header = row[0].row
                columns = names
                break
        if header is None:
            raise ValueError("В шаблоне не найдены заголовки «Наименование» и «Тип строки»")
        start = header + 1
        for merged in ws.merged_cells.ranges:
            if merged.min_row <= header <= merged.max_row:
                start = max(start, merged.max_row + 1)
        # The downloaded template has an ИТОГО row immediately after its header.
        while any(str(c.value or "").strip().casefold() == "итого" for c in ws[start]):
            start += 1
        today = dtm.date.today()
        for index in range(2):
            row_number = start + index
            values = {
                "№ п/п": index + 1, "№": index + 1, "тип строки": "Работа",
                "код вида работ": "1.1.1", "наименование по справочнику": "Налоги ТОО",
                "наименование": f"Автотест позиция {index + 1} {STAMP}",
                "ед. изм.": "усл", "объём": 10, "объем": 10, "кол-во": 10,
                "дата с": (today + dtm.timedelta(days=5)).strftime("%d.%m.%Y"),
                "дата по": (today + dtm.timedelta(days=35)).strftime("%d.%m.%Y"),
                "сумма без ндс": 100000, "сумма с ндс": 116000,
                "комментарий": "Автотест: импорт из шаблона сайта",
            }
            for name, value in values.items():
                if name in columns:
                    target = ws.cell(row_number, columns[name])
                    if isinstance(target, openpyxl.cell.cell.MergedCell):
                        raise ValueError(f"Строка данных {row_number} содержит объединённую ячейку")
                    target.value = value
        wb.save(dst)
        log(f"    Шаблон заполнен: заголовки {header}, данные {start}–{start + 1}")
        return dst
    except Exception as exc:
        log(f"    ⚠ Не удалось заполнить шаблон: {exc}", "WARN")
        return None


def open_create_gfr_modal():
    if not find_buttons(["Создать ГФР"]):
        # The main list shows project cards; creation is inside an expanded project.
        searches = [e for e in driver.find_elements(By.XPATH,
            "//input[contains(@placeholder,'Поиск')]") if e.is_displayed()]
        if searches:
            type_text(searches[0], PROJECT_QUERY)
            time.sleep(0.8)
        if not wait_for_state(lambda: PROJECT_QUERY.lower() in page_text()):
            log(f"  ⚠ Проект «{PROJECT_QUERY}» отсутствует в списке ГФР", "WARN")
            return None
        if not click_text_deepest(PROJECT_QUERY, "contains"):
            log(f"  ⚠ Карточка проекта «{PROJECT_QUERY}» не раскрылась", "WARN")
            return None
        if not wait_for_state(lambda: bool(find_buttons(["Создать ГФР"])), timeout=8):
            log(f"  ⚠ После раскрытия «{PROJECT_QUERY}» кнопка «Создать ГФР» не появилась", "WARN")
            return None
    if not (click_button(["Создать ГФР"], wait=8) or click_text_deepest("Создать ГФР", "contains")):
        return None
    return wait_modal("Создать график", 8)


def fill_modal_extras(modal):
    """Доп. поля, которые могут появиться после выбора основания (смета / ГПР / файл)."""
    n = 0
    for _ in range(3):
        progressed = False
        for t in visible_selects(modal):
            tx = (t.get_attribute("textContent") or "").strip().lower()
            if tx.startswith(("выбер", "выбрать")):
                panel = open_ui(t)
                got = select_in_panel(panel, index=0) if panel else None
                close_panels()
                log(f"    Доп. поле «{tx}» → {got or 'не выбрано'}", "PASS" if got else "WARN")
                if got:
                    progressed = True
                    n += 1
                time.sleep(0.8)
        if not progressed:
            break
    return n


def create_gfr(basis):
    """Создаёт один ГФР с указанным основанием. Возвращает URL карточки или None."""
    driver.get(GFR_URL)
    if not wait_for_state(lambda: "гфр" in page_text() and bool(driver.find_elements(
            By.XPATH, "//input[contains(@placeholder,'Поиск')]"))):
        log(f"  ⚠ Список ГФР не загрузился: {driver.current_url}", "WARN")
        return None
    block_native_file_dialog()
    name = f"Автотест ГФР {basis} {STAMP}"
    modal = open_create_gfr_modal()
    if not modal:
        log("  ⚠ Модалка «Создать ГФР» не открылась", "WARN")
        return None
    # Проект
    trg = control_by_label(modal, "Проект")
    panel = open_ui(trg) if trg is not None else None
    got = select_in_panel(panel, keywords=[PROJECT_QUERY.lower()], search=PROJECT_QUERY) if panel else None
    if not got:
        close_panels()
        panel = open_ui(trg) if trg is not None else None
        got = select_in_panel(panel, index=0) if panel else None
    log(f"    Проект: {got or 'НЕ выбран'}", "PASS" if got else "WARN")
    # Наименование
    inp = None
    for xp in [".//input[contains(@placeholder,'ГФР')]",
               ".//*[normalize-space(text())='Наименование графика']/following::input[1]"]:
        try:
            es = [e for e in modal.find_elements(By.XPATH, xp) if e.is_displayed()]
            if es:
                inp = es[0]
                break
        except Exception:
            pass
    if inp is not None:
        type_text(inp, name)
        log(f"    Наименование: {name}", "PASS")
    else:
        log("    ⚠ Поле «Наименование графика» не найдено", "WARN")
    # Взять за основу
    ctrl = control_by_label(modal, "Взять за основу")
    if ctrl is not None:
        cur = (ctrl.get_attribute("textContent") or "").strip().lower()
        if basis.lower() not in cur:
            panel = open_ui(ctrl)
            picked = select_in_panel(panel, keywords=[basis.lower()]) if panel else None
            if not picked and panel:
                close_panels()
            log(f"    Основание: {picked or 'НЕ выбрано'}", "PASS" if picked else "WARN")
            time.sleep(1.2)
        else:
            log(f"    Основание: {basis} (по умолчанию)", "PASS")
    else:
        log("    ⚠ Контрол «Взять за основу» не найден", "WARN")
    # доп. поля / файл
    fill_modal_extras(modal)
    if basis.lower().startswith("файл"):
        xl = None
        # если в модалке есть «Скачать шаблон» — берём шаблон сайта и дописываем в него строки
        try:
            tpl = [e for e in modal.find_elements(
                By.XPATH, ".//*[self::button or self::a][contains(translate(normalize-space(.),"
                          "'ШАБЛОН','шаблон'),'шаблон')]") if e.is_displayed()]
        except Exception:
            tpl = []
        if tpl:
            before = snapshot_downloads()
            t0 = time.time()
            click_el(tpl[0])
            f = wait_new_download(before, t0, timeout=20, ext=(".xlsx", ".xls"))
            if f:
                log(f"    ✓ Шаблон основания скачан: {f}", "PASS")
                xl = fill_gfr_template(f, os.path.join(WORK_DIR, f"gfr_basis_{STAMP}.xlsx"))
                if not xl:
                    log("  ⚠ Шаблон сайта не заполнен; произвольным Excel его не заменяю", "WARN")
                    close_modal_soft(modal)
                    return None
        if not xl:
            xl = create_gfr_excel()
        if send_file(xl, scope=modal):
            log("    ✓ Excel-файл основания передан", "PASS")
        time.sleep(3)
        try:
            log("    Модалка после загрузки файла: "
                + (modal.get_attribute("innerText") or "").replace("\n", " | ")[:300])
        except Exception:
            pass
        shot("gfr_basis_excel_modal")
    modal = find_modal("Создать график") or modal
    btn = modal_button(modal, ["Создать"])
    if not btn:
        log("  ⚠ Кнопка «Создать» недоступна", "WARN")
        shot(f"gfr_create_nobtn_{basis}")
        close_modal_soft(modal)
        return None
    click_el(btn)
    url = None
    for _ in range(25):
        time.sleep(1)
        if "/financing-schedules/versions/" in driver.current_url:
            url = driver.current_url.split("#")[0]
            break
        errs = [t for t in read_toasts() if any(k in t.lower() for k in
                                                ["ошибк", "не удалось", "нельзя", "error", "must"])]
        if errs:
            log(f"  ⚠ Ошибка при создании ({basis}): {errs}", "WARN")
            break
    if not url:
        shot(f"gfr_create_fail_{basis}")
        m = find_modal("Создать график")
        if m:
            close_modal_soft(m)
        return None
    wait_for_state(card_ready)
    txt = driver.execute_script("return document.body.innerText;") or ""
    mnum = NUM_GFR_RE.search(txt)
    STATE["numbers"][basis] = mnum.group(0) if mnum else "?"
    log(f"  ✓ ГФР создан ({basis}): {STATE['numbers'][basis]} — {url}", "PASS")
    return url


def stage_create_all():
    main = None
    for basis in GFR_BASES:
        log("-" * 50)
        log(f"  Создание ГФР: основание «{basis}»")
        url = None
        try:
            url = create_gfr(basis)
        except Exception as e:
            log(f"  ⚠ Исключение при создании ({basis}): {e}", "WARN")
        record(f"ГФР: создание — основание «{basis}»", bool(url),
               STATE["numbers"].get(basis, ""), reason="не создался (см. скриншот/лог)")
        if url:
            STATE["created"].append((basis, url))
            if main is None:
                main = (basis, url)
    if main:
        STATE["url"] = main[1]
        STATE["main_basis"] = main[0]
        log(f"  Основной ГФР для дальнейших шагов: «{main[0]}» — {main[1]}", "PASS")
    return main is not None


# ==========================================
# ГФР: КАРТОЧКА
# ==========================================
def on_positions_view():
    return "вернуться к основной информации" in page_text()


def goto_card():
    url = STATE.get("url")
    if not url:
        try:
            driver.get(GFR_URL)
            time.sleep(3)
            for link in driver.find_elements(By.XPATH, "//table//tr//a[contains(@href, '/finance/gfr/')] | //a[contains(@href, '/finance/gfr/') and not(contains(@href, '/create'))]"):
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
    if url.split("?")[0] not in driver.current_url:
        driver.get(url)
        return bool(wait_for_state(card_ready))
    elif on_positions_view():
        if not (click_button(["Вернуться к основной информации"], wait=3)
                or click_text_deepest("Вернуться к основной информации", "contains")):
            driver.get(url)
        return bool(wait_for_state(card_ready))
    return bool(wait_for_state(card_ready))


def open_positions():
    if on_positions_view():
        block_native_file_dialog()
        return True
    goto_card()
    if click_button(["Открыть график"], wait=8) or click_text_deepest("Открыть график", "contains"):
        if wait_for_state(lambda: on_positions_view() and bool(find_buttons(["Добавить строку"])), timeout=15):
            block_native_file_dialog()
            return True
    log("  ⚠ «Открыть график» не открыл позиции", "WARN")
    return False


def rows_state():
    txt = page_text()
    empty = "нет позиций графика" in txt
    try:
        rows = driver.execute_script("""
            return Array.prototype.filter.call(document.querySelectorAll('tbody tr'),
                function(r){ return r.offsetWidth || r.offsetHeight; }).length;""")
    except Exception:
        rows = 0
    return (0 if empty else rows), parse_total()


def stage_card_buttons():
    goto_card()
    ok = True
    for h in ["Основная информация", "Период графика"]:
        for _ in range(2):
            if not click_text_deepest(h, "exact"):
                log(f"  ⚠ Секция «{h}» не найдена", "WARN")
                ok = False
                break
            time.sleep(0.8)
        else:
            log(f"  ✓ Секция «{h}»: свернуть/развернуть", "PASS")
    for tab in ["История", "Обсуждение"]:
        if click_text_deepest(tab, "exact"):
            log(f"  ✓ Вкладка «{tab}»", "PASS")
            time.sleep(1.5)
        else:
            log(f"  ⚠ Вкладка «{tab}» не найдена", "WARN")
            ok = False
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
    try:
        pen = driver.find_element(
            By.XPATH, "//*[normalize-space(text())='Ставка НДС']/following::button[1]")
        hard_click(pen)
        time.sleep(1.2)
        esc()
        log("  ✓ Карандаш ставки НДС нажат", "PASS")
        driver.get(STATE["url"])
        time.sleep(3)
    except Exception:
        log("  • Карандаш НДС не найден", "WARN")
    ok = try_open_and_cancel("Редактировать") and ok
    if find_buttons(["Сменить маршрут"]):
        ok = try_open_and_cancel("Сменить маршрут") and ok
    goto_card()
    return ok


# ==========================================
# ГФР: ПОЗИЦИИ (строки)
# ==========================================
def num_field(scope, label, value):
    try:
        inp = scope.find_element(
            By.XPATH, f".//*[normalize-space(text())='{label}']/following::input[1]")
        if inp.is_displayed() and inp.is_enabled():
            type_text(inp, value)
            v = (inp.get_attribute("value") or "").strip()
            log(f"    {'✓' if v else '⚠'} {label}: {v}", "PASS" if v else "WARN")
            return bool(v)
    except Exception:
        pass
    log(f"    ⚠ Поле «{label}» не найдено", "WARN")
    return False


def pick_work_kind_gfr(modal):
    """«Вид работ» (плоский список или дерево) — выбираем первое доступное значение. TODO VERIFY."""
    ctrl = control_by_label(modal, "Вид работ")
    if ctrl is None:
        log("    ⚠ Контрол «Вид работ» не найден", "WARN")
        return False

    def changed():
        t = (ctrl.get_attribute("textContent") or "").strip().lower()
        return bool(t) and not t.startswith(("выберите", "выбрать"))

    panel = open_ui(ctrl)
    if panel is None:
        return False
    for attempt in range(10):
        panel = visible_panel() or open_ui(ctrl)
        if panel is None:
            break
        opts = panel_options(panel)
        if not opts:
            # дерево без role=option: берём листовой элемент вида 1.2.3
            el = driver.execute_script("""
                var all = document.querySelectorAll('*');
                for (var i = 0; i < all.length; i++) {
                    var e = all[i];
                    if (e.children.length || !(e.offsetWidth || e.offsetHeight)) continue;
                    if (/^\\d+\\.\\d+(\\.\\d+)*\\s/.test((e.textContent || '').trim())) return e;
                }
                return null;""")
            if el is None:
                break
            hard_click(el)
        else:
            leaf = [o for o in opts if re.match(r"^\d+(\.\d+){2,}", o["text"])]
            cands = leaf or opts
            cand = cands[attempt % len(cands)]
            hard_click(cand["element"])
        time.sleep(0.9)
        if changed():
            break
    close_panels()
    try:
        title = modal.find_element(By.XPATH, ".//*[normalize-space(text())='Добавить строку']")
        hard_click(title)
        time.sleep(0.5)
    except Exception:
        pass
    ok = changed()
    log(f"    {'✓' if ok else '⚠'} Вид работ: {(ctrl.get_attribute('textContent') or '').strip()[:50]}",
        "PASS" if ok else "WARN")
    return ok


def add_gfr_row(desc, type_idx=0):
    if not click_button(["Добавить строку"], wait=6):
        log("  ⚠ Кнопка «Добавить строку» не найдена", "WARN")
        return False
    modal = wait_modal("Добавить строку", 8)
    if not modal:
        log("  ⚠ Модалка «Добавить строку» не открылась", "WARN")
        return False
    rows0, total0 = rows_state()

    # Тип строки
    tctrl = control_by_label(modal, "Тип строки")
    if tctrl is not None:
        cur = (tctrl.get_attribute("textContent") or "").strip()
        if type_idx > 0:
            panel = open_ui(tctrl)
            opts = panel_options(panel) if panel else []
            if opts:
                names = [o["text"] for o in opts]
                got = select_in_panel(panel, index=min(type_idx, len(opts) - 1))
                log(f"    Тип строки: варианты {names} → {got}", "PASS" if got else "WARN")
            else:
                close_panels()
                log(f"    Тип строки: вариантов нет, оставляю «{cur}»")
        else:
            log(f"    Тип строки: «{cur}»", "PASS")
    time.sleep(0.8)

    pick_work_kind_gfr(modal)
    time.sleep(0.8)

    # Ед. измерения
    unit = control_by_label(modal, "Ед. измерения") or control_by_label(modal, "Ед.изм")
    if unit is not None:
        utxt = (unit.get_attribute("textContent") or "").strip().lower()
        if not utxt or utxt.startswith(("выбрать", "выберите")):
            panel = open_ui(unit)
            picked = select_in_panel(panel, keywords=["усл"], search="усл") if panel else None
            if not picked and panel:
                close_panels()
                panel = open_ui(unit)
                picked = select_in_panel(panel, index=0) if panel else None
            log(f"    Ед. измерения: {picked or 'НЕ выбрана (поле неактивно?)'}",
                "PASS" if picked else "WARN")
        else:
            log(f"    Ед. измерения: «{utxt}» (подставилась сама)", "PASS")

    num_field(modal, "Количество", "10")

    # Дата С / Дата ПО (С — раньше, ПО — чуть позже)
    today = dtm.date.today()
    trs = date_triggers()
    for t in trs:
        try:
            lab = (driver.execute_script(JS_DATE_LABEL, t) or "").strip().lower()
        except Exception:
            lab = ""
        is_end = bool(re.search(r"\bпо\b", lab)) or (not lab and t is trs[-1])
        target = today + dtm.timedelta(days=35 if is_end else 5)
        if not date_empty(t):
            continue
        okd = pick_date(t, target)
        log(f"    {'✓' if okd else '⚠'} {'Дата ПО' if is_end else 'Дата С'}: {date_text(t) or 'не выбрана'}",
            "PASS" if okd else "WARN")

    num_field(modal, "Сумма без НДС", "100000")
    time.sleep(0.5)
    wv = ""
    try:
        inp = modal.find_element(By.XPATH, ".//*[normalize-space(text())='Сумма с НДС']/following::input[1]")
        wv = (inp.get_attribute("value") or "").strip()
    except Exception:
        pass
    if not wv or wv in ("0,00", "0"):
        num_field(modal, "Сумма с НДС", "116000")
    else:
        log(f"    ✓ Сумма с НДС посчиталась сама: {wv}", "PASS")

    try:
        ta = [t for t in modal.find_elements(By.XPATH, ".//textarea") if t.is_displayed()]
        if ta:
            type_text(ta[0], f"Автотест строка: {desc}")
            log("    ✓ Примечание заполнено", "PASS")
    except Exception:
        pass

    save = modal_button(modal, ["Добавить"])
    if not save:
        log("  ⚠ Кнопка «Добавить» недоступна", "WARN")
        shot("gfr_row_nobutton")
        close_modal_soft(modal)
        return False
    click_el(save)
    closed = wait_modal_closed("Добавить строку", 8)
    time.sleep(2)
    if not closed:
        log(f"  ⚠ Модалка не закрылась (ошибки валидации?). Уведомления: {read_toasts()}", "WARN")
        shot("gfr_row_validation")
        m = find_modal("Добавить строку")
        if m:
            close_modal_soft(m)
        return False
    rows1, total1 = rows_state()
    log(f"  ✓ Строка добавлена ({desc}). Строк: {rows0}→{rows1}, итого без НДС: {total0}→{total1}", "PASS")
    return True


def stage_positions_buttons():
    if not open_positions():
        return False
    ok = True
    rows, total = rows_state()
    log(f"  Позиции сейчас: строк={rows}, итого={total}")
    for text in ["Диаграмма", "Таблица"]:
        if click_text_deepest(text, "exact"):
            log(f"  ✓ Переключатель «{text}»", "PASS")
            time.sleep(1.5)
        else:
            log(f"  ⚠ «{text}» не найден", "WARN")
            ok = False
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
            log(f"  ✓ Кнопка «{text}»", "PASS")
            time.sleep(1.5)
        elif text in ["Свернуть все", "Обновить"]:
            log(f"  • Кнопка «{text}» не найдена (не критично)", "INFO")
        else:
            log(f"  ⚠ Кнопка «{text}» не найдена", "WARN")
            ok = False
    for text in ["Выгрузить в Excel", "Загрузить из Excel", "Добавить строку", "История графика"]:
        has = bool(find_buttons([text]))
        log(f"  Кнопка «{text}»: {'есть' if has else 'НЕТ'}", "PASS" if has else "WARN")
        ok = ok and has
    return ok


def stage_add_row_full():
    if not open_positions():
        return False
    return add_gfr_row("все поля", type_idx=0)


def stage_export_excel():
    if not open_positions():
        return False
    before = snapshot_downloads()
    t0 = time.time()
    if not click_button(["Выгрузить в Excel"], wait=5):
        log("  ⚠ Кнопка «Выгрузить в Excel» не найдена", "WARN")
        return False
    f = wait_new_download(before, t0, timeout=30, ext=(".xlsx", ".xls", ".csv"))
    if f:
        STATE["exported"] = f
        log(f"  ✓ Выгрузка скачана: {f} ({os.path.getsize(f)} байт)", "PASS")
        return True
    log(f"  ⚠ Файл не появился в {DOWNLOAD_DIR}. Уведомления: {read_toasts()}", "WARN")
    return False


def stage_import_excel():
    if not open_positions():
        return False
    src = STATE.get("exported")
    if src and os.path.exists(src):
        xlsx = os.path.join(WORK_DIR, f"gfr_reimport_{STAMP}.xlsx")
        shutil.copy(src, xlsx)
        log("    Для импорта беру только что выгруженный файл (формат сайта)")
    else:
        xlsx = create_gfr_excel()
    block_native_file_dialog()
    rows0, total0 = rows_state()
    if not click_button(["Загрузить из Excel"], wait=5):
        log("  ⚠ Кнопка «Загрузить из Excel» не найдена", "WARN")
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
    rows1, total1 = rows_state()
    log(f"  Импорт: строк {rows0}→{rows1}, итого {total0}→{total1}, уведомления: {toasts}")
    if errs:
        shot("gfr_import_error")
        return False
    m = find_modal()
    if m:
        close_modal_soft(m)
    return True


def stage_history_and_back():
    if not open_positions():
        return False
    url_before = driver.current_url
    if not click_button(["История графика"], wait=5):
        log("  ⚠ Кнопка «История графика» не найдена", "WARN")
        return False
    time.sleep(3)
    shot("gfr_history")
    m = find_modal()
    if m:
        close_modal_soft(m)
        time.sleep(1)
    elif driver.current_url != url_before:
        driver.back()
        time.sleep(3)
    else:
        esc()
    log("  ✓ «История графика» открыта и закрыта", "PASS")
    if not on_positions_view():
        open_positions()
    return True


def stage_add_row_final():
    if not open_positions():
        return False
    ok = add_gfr_row("после настройки маршрута", type_idx=1)
    if not ok:
        log("  • Повтор с типом строки по умолчанию")
        ok = add_gfr_row("после настройки маршрута (2)", type_idx=0)
    goto_card()
    return ok


# ==========================================
# ГФР: УТВЕРЖДАЮЩИЙ (inline-форма: «Добавить» -> селект -> «Сохранить»)
# ==========================================
def utv_assigned():
    t = (driver.execute_script("return document.body.innerText;") or "").lower()
    m = re.search(r"утверждающий(.{0,400})", t, re.S)
    seg = m.group(1) if m else ""
    return any(word in seg for word in ("талгат", "ерланович", "алд", "диас")) and "не назначен" not in seg and "выберите утверждающего" not in seg


def utv_trigger():
    try:
        for t in driver.find_elements(
                By.XPATH, "//button[contains(@class,'ui-select__trigger')]"
                          "[contains(normalize-space(.),'тверждающего')]"):
            if t.is_displayed():
                return t
    except Exception:
        pass
    return None


def add_approver_final():
    goto_card()
    if utv_assigned():
        log("  ✓ Утверждающий уже назначен", "PASS")
        return True
    trg = utv_trigger()
    if trg is None:
        btn = None
        for xp in [
            "//*[normalize-space(text())='Утверждающий']/following::button[normalize-space(.)='Добавить'][1]",
            "//*[contains(normalize-space(text()),'Утверждающий не назначен')]"
            "/following::*[self::button or self::a][normalize-space(.)='Добавить'][1]",
            "//*[contains(normalize-space(text()),'Утверждающий не назначен')]"
            "/following::*[normalize-space(text())='Добавить'][1]",
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
            log("  • Утверждающий уже задан либо кнопка «Добавить» скрыта", "INFO")
            return True
        scroll_to(btn)
        click_el(btn)
        time.sleep(1.5)
    modal = find_modal("Утверждающий")
    for _ in range(10):
        trg = utv_trigger()
        if trg is not None:
            break
        if modal is None:
            modal = find_modal("Утверждающий")
        if modal is not None:
            ts = visible_selects(modal)
            if ts:
                trg = ts[0]
                break
        time.sleep(0.6)
    if trg is None:
        log("  ⚠ Селект «Выберите утверждающего» не появился", "WARN")
        shot("gfr_utv_no_select")
        return False
    panel = open_ui(trg)
    picked = select_in_panel(panel, keywords=UTV_KEYS, search=UTV_QUERY) if panel else None
    if not picked:
        log(f"  ⚠ Утверждающий не выбран; варианты: {[o['text'] for o in panel_options(panel)] if panel else []}", "WARN")
        close_panels()
        return False
    log(f"  ✓ Утверждающий выбран: {picked}", "PASS")
    time.sleep(1)
    save = None
    if modal is not None:
        save = modal_button(modal, ["Сохранить"])
    if save is None:
        for xp in ["//*[normalize-space(text())='Утверждающий']/following::button[normalize-space(.)='Сохранить'][1]",
                   "//button[normalize-space(.)='Сохранить']"]:
            try:
                bs = [b for b in driver.find_elements(By.XPATH, xp) if b.is_displayed()]
            except Exception:
                bs = []
            if bs:
                save = bs[0]
                break
    if save is None:
        log("  ⚠ Кнопка «Сохранить» утверждающего не найдена", "WARN")
        return False
    click_el(save)
    time.sleep(3)
    log(f"  Уведомления: {read_toasts()}")
    driver.get(STATE["url"])
    ok = bool(wait_for_state(utv_assigned))
    log(f"  Утверждающий в карточке после сохранения: {'да' if ok else 'нет'}", "PASS" if ok else "WARN")
    if not ok:
        shot("gfr_utv_not_saved")
    return ok


# ==========================================
# ГФР: СОГЛАСОВАНИЕ
# ==========================================
def stage_send_for_approval():
    goto_card()
    if not utv_assigned():
        log("  ⚠ Отправка заблокирована: утверждающий Диас не назначен", "WARN")
        return False
    before = get_status()
    log(f"  Статус до: {before}")
    if not route_has_approver():
        log("  ⚠ Перед отправкой в маршруте нет согласующего", "WARN")
    label = click_action(TO_SEND)
    if not label:
        log("  ⚠ Кнопка «Отправить на согласование» не найдена/недоступна", "WARN")
        return False
    time.sleep(3)
    toasts = read_toasts()
    if toasts:
        log(f"  Уведомления после отправки: {toasts}")
    time.sleep(2)
    driver.refresh()
    if not wait_for_state(card_ready):
        return False
    after = get_status()
    still = bool(find_buttons(TO_SEND))
    changed = bool(after and after != before)
    log(f"  Статус после: {after}; кнопка отправки {'осталась' if still else 'пропала'}",
        "PASS" if (changed or not still) else "WARN")
    if still and not changed:
        errs = [t for t in toasts if any(k in t.lower() for k in
                ["ошибк", "не назнач", "обязательн", "нельзя", "не удалось", "необходимо"])]
        log(f"  ⚠ Отправка не сработала: {errs or toasts or 'статус не изменился'}", "WARN")
        shot("gfr_send_not_done")
        return False
    return True


def stage_approve_main():
    accounts_to_try = [
        (env("RGB_ACCOUNT2_LOGIN", login_val), env("RGB_ACCOUNT2_PASSWORD", pass_val)),
        (SECOND_LOGIN, SECOND_PASS),
        (DDS_LOGIN, DDS_PASS),
        (env("RGB_ACCOUNT1_LOGIN"), env("RGB_ACCOUNT1_PASSWORD")),
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
            log(f"  ✓ ГФР уже согласован ({acc_l}): {status}", "PASS")
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
                for r in driver.find_elements(By.XPATH, "//*[contains(normalize-space(.),'Согласовать') or contains(normalize-space(.),'ГФР')]"):
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
            wait_for_state(card_ready)
            log(f"  Статус после согласования ({acc_l}): {get_status()}", "PASS")
            return True

    log(f"  ⚠ Кнопки {TO_APPROVE} не найдены ни под одним аккаунтом", "WARN")
    return False


def stage_confirm_by_talgat():
    accounts_to_try = [
        (SECOND_LOGIN, SECOND_PASS),
        (env("RGB_ACCOUNT3_LOGIN"), env("RGB_ACCOUNT3_PASSWORD")),
        (DDS_LOGIN, DDS_PASS),
        (env("RGB_ACCOUNT1_LOGIN"), env("RGB_ACCOUNT1_PASSWORD")),
        (login_val, pass_val),
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
        if not wait_for_state(card_ready):
            continue
        status = get_status()
        if status and "утвержд" in status.lower():
            log(f"  ✓ ГФР уже утверждён ({acc_l}): {status}", "PASS")
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
                for r in driver.find_elements(By.XPATH, "//*[contains(normalize-space(.),'Утвердить') or contains(normalize-space(.),'ГФР')]"):
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
            wait_for_state(card_ready)
            log(f"  Статус после утверждения ({acc_l}): {get_status()}", "PASS")
            return True

    log(f"  ⚠ Кнопки {TO_CONFIRM} не найдены ни под одним аккаунтом", "WARN")
    return False




# ==========================================
# ОТЧЁТЫ: Telegram + Google Sheets
# ==========================================
def save_finance_results():
    """Persist only this run; the parent process owns Sheets and Telegram."""
    output = os.environ.get("FINANCE_RESULT_PATH")
    if not output:
        raise RuntimeError("Запустите через run_workflow_and_report.py")
    payload = {
        "run_id": os.environ["FINANCE_RUN_ID"],
        "results": [{"name": name, "ok": ok, "reason": REASONS.get(name, "")}
                    for name, ok in RESULTS],
        "error": RUN_ERROR,
        "screenshot": FAILED_SCREENSHOTS[-1] if FAILED_SCREENSHOTS else "",
        "url": STATE.get("url"),
        "dds": STATE.get("dds"),
        "log": LOG_FILE_PATH,
    }
    path = Path(output)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


# ==========================================
# MAIN
# ==========================================
def run():
    global RUN_ERROR
    log("=" * 60)
    log(f"АВТОТЕСТ «ФИНАНСЫ: ДДС + ГФР» ({STAMP})")
    log("=" * 60)
    try:
        init_driver()
        driver.get(CASHFLOW_URL)
        # Этап 1: Вход и открытие раздела «Финансы»
        step("Вход и открытие раздела «Финансы»", stage_login)

        # ---------- ДДС ----------
        # Этап 2: ДДС открытие раздела
        step("ДДС: открытие раздела (пусто до запроса)", stage_dds_open)

        # Этап 3: ДДС «Запросить» и анализ статей расхода
        step("ДДС: «Запросить» и анализ статей расхода", stage_dds_query_analysis)

        # Этап 4: ДДС сворачивание/разворачивание статей
        step("ДДС: сворачивание/разворачивание статей", stage_dds_toggle_rows)

        # Этап 5: ДДС фильтры, период, «Сбросить»
        step("ДДС: фильтры, период, «Сбросить»", stage_dds_filters_and_buttons)

        # Этап 6: ДДС «Выгрузить»
        step("ДДС: «Выгрузить» (файл скачался)", stage_dds_export)

        # ---------- ГФР ----------
        # Этап 7: ГФР главная
        step("ГФР: главная — фильтры, поиск, карточка проекта", stage_gfr_list)

        # Этап 8: ГФР создание
        step("ГФР: создание (все виды основания)", stage_create_all)

        # Этап 9: ГФР карточка
        step("ГФР: карточка — секции, вкладки, кнопки", stage_card_buttons)

        # Этап 10: ГФР согласующий
        step("ГФР: маршрут согласования — Ерлан Талгатович", add_approver)

        # Этап 11: ГФР утверждающий
        step("ГФР: утверждающий — Талгат Ерланович", add_approver_final)

        # Этап 12: ГФР обсуждение
        step("ГФР: обсуждение — сообщение и файл", stage_discussion)

        # Этап 13: ГФР открыть график
        step("ГФР: «Открыть график» — кнопки", stage_positions_buttons)

        # Этап 14: ГФР добавление строки
        step("ГФР: добавление строки (все поля)", stage_add_row_full)

        # Этап 15: ГФР выгрузка в Excel
        step("ГФР: «Выгрузить в Excel»", stage_export_excel)

        # Этап 16: ГФР загрузка из Excel
        step("ГФР: «Загрузить из Excel»", stage_import_excel)

        # Этап 17: ГФР история графика
        step("ГФР: «История графика»", stage_history_and_back)

        # Этап 18: ГФР добавление строки после маршрута
        step("ГФР: добавление строки (после маршрута)", stage_add_row_final)

        # Этап 19: ГФР отправка на согласование
        step("ГФР: «Отправить на согласование»", stage_send_for_approval)

        if CONTINUE_APPROVAL:
            # Этап 20: ГФР согласование
            step("ГФР: «Согласовать» (Ерлан Талгатович)", stage_approve_main)

            # Этап 21: ГФР утверждение
            step("ГФР: «Утвердить» (Талгат Ерланович)", stage_confirm_by_talgat)
    except Exception as e:
        RUN_ERROR = f"{type(e).__name__}: {e}"
        log(f"КРИТИЧЕСКАЯ ОШИБКА: {e}", "FAIL")
        shot("critical_error")
    finally:
        save_finance_results()
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


if __name__ == "__main__" and os.environ.get("FINANCE_NO_RUN") != "1":
    if os.environ.get("FINANCE_MANAGED") == "1":
        run()
        raise SystemExit(1 if RUN_ERROR or any(not ok for _, ok in RESULTS) else 0)
    else:
        from run_workflow_and_report import run_finance
        raise SystemExit(run_finance(__file__, sys.argv[1:]))
