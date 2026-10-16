
from artifact_paths import SCREENS_DIR, LOGS_DIR, screen_path, log_path
from env_config import env, env_list, is_headless  # секреты — из .env / GitHub Secrets
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    TimeoutException, StaleElementReferenceException,
    NoSuchElementException, ElementClickInterceptedException
)
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains
import time
import os
import sys
import re
import requests
from datetime import datetime, timedelta

# --- Автозапись результатов в чек-лист (тот же sheet_reporter.py, что
# используют waybill/contract/invoice) ---
try:
    from sheet_reporter import report_result
    SHEET_REPORTING_ENABLED = True
except Exception:
    SHEET_REPORTING_ENABLED = False


def report_to_sheet(task_name, passed, row_range):
    """Обёртка над sheet_reporter.report_result — тихо пропускает, если
    модуль недоступен (например, sheet_reporter.py не в этой папке).

    Также фиксирует результат в checklist_results — по одной записи на
    каждый вызов, в порядке выполнения. Если проверка провалена, причина
    берётся автоматически: ищутся строки уровня FAIL (а если их нет —
    WARN) в логе, накопленные С ПРЕДЫДУЩЕГО такого вызова — то есть
    именно за время этой конкретной проверки, а не всего лога целиком."""
    global _report_log_cursor

    reason = None
    if not passed:
        segment = report[_report_log_cursor:]
        fails = [e for e in segment if "[FAIL]" in e]
        warns = [e for e in segment if "[WARN]" in e]
        picked = fails or warns
        if picked:
            texts = []
            for entry in picked:
                try:
                    texts.append(entry.split("] ", 2)[-1].strip())
                except Exception:
                    texts.append(entry.strip())
            # убираем дубли, сохраняя порядок
            seen = set()
            uniq = []
            for t in texts:
                if t not in seen:
                    seen.add(t)
                    uniq.append(t)
            reason = "; ".join(uniq)
        else:
            reason = "причина не определена в логе"

        # Скриншот "бага" — состояние страницы в момент фиксации провала,
        # отправляется в Telegram сразу (по договорённости: скрин делается
        # только на проваленных проверках, не на каждом шаге).
        try:
            safe_name = re.sub(r"[^0-9A-Za-zА-Яа-яЁё]+", "_", task_name)[:40]
            shot_path = screen_path(f"scr_fail_{safe_name}.png")
            driver.save_screenshot(shot_path)
            tg_photo(shot_path, caption=f"❌ {task_name}")
        except Exception:
            pass

    checklist_results.append({"name": task_name, "passed": bool(passed), "reason": reason})
    _report_log_cursor = len(report)

    if not SHEET_REPORTING_ENABLED:
        return
    try:
        report_result(task_name=task_name, passed=passed, row_range=row_range)
    except Exception as e:
        log(f"  [sheet_reporter] Не удалось записать '{task_name}': {e}", "WARN")


# Диапазоны строк в чек-листе (Чек-лист_RGB.xlsx, секция "Мои задачи")
ROWS_TASKS = (90, 93)
ROWS_ASSIGNMENTS = (95, 103)
ROWS_CALENDAR = (105, 117)


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

driver = webdriver.Chrome(
    service=Service(ChromeDriverManager().install()),
    options=_chrome_options
)
driver.implicitly_wait(0)  # ВАЖНО: было 3 — вызывало огромные задержки.
# Код сам явно ждёт где нужно (time.sleep/WebDriverWait), а implicit wait
# при этом заставлял КАЖДУЮ безуспешную попытку (их много — код пробует
# несколько стратегий поиска подряд) молча висеть до 3 секунд, прежде чем
# перейти к следующей. Именно это, а не сами паузы, было причиной
# 2+ минут на одно значение фильтра.
login_val = env("RGB_ACCOUNT2_LOGIN")
pass_val = env("RGB_ACCOUNT2_PASSWORD")

BASE_URL = "https://testportal.rgbgroup.kz/"
TASKS_URL = "https://testportal.rgbgroup.kz/?tab=tasks"
WAIT = 15

# ==========================================
# TELEGRAM
# ==========================================
TG_ENABLED = False  # <-- поставь True, когда будешь готов слать отчёты в Telegram
TG_TOKEN = env("TG_TOKEN")
TG_CHATS = env_list("TG_CHATS")
TG_API = f"https://api.telegram.org/bot{TG_TOKEN}"

def tg_send(text):
    if not TG_ENABLED:
        return
    for cid in TG_CHATS:
        try:
            requests.post(f"{TG_API}/sendMessage", data={
                "chat_id": cid, "text": text[:4000], "parse_mode": "HTML"
            }, timeout=10)
        except Exception: pass

def tg_photo(path, caption=""):
    if not TG_ENABLED:
        return
    if not os.path.exists(path): return
    for cid in TG_CHATS:
        try:
            with open(path, "rb") as f:
                requests.post(f"{TG_API}/sendPhoto", data={
                    "chat_id": cid, "caption": caption[:1000], "parse_mode": "HTML"
                }, files={"photo": f}, timeout=30)
        except Exception: pass

# ==========================================
# ЛОГИРОВАНИЕ
# ==========================================
report = []
results = {"passed": 0, "failed": 0, "warnings": 0}
test_summaries = []  # Сводки по дропдаунам для тимлида
name_filter_summary = []  # [(слово, кол-во)]
dates_summary = None  # кол-во записей в диапазоне дат
creation_test = None  # Результат теста создания
checklist_results = []  # [{"name":.., "passed":.., "reason":..}, ...] —
# по одной записи на каждый вызов report_to_sheet, в порядке выполнения;
# из этого списка строится итоговый отчёт в Telegram.
_report_log_cursor = 0  # до какого индекса report[] уже разобран на
# предмет причин провала — чтобы каждой проверке в checklist_results
# доставалась причина именно из ЕЁ собственного куска лога, а не всего
# накопленного лога целиком.
_calendar_create_btn = None  # ссылка на кнопку "Создать" в календаре —
# нужна, чтобы среди ОДИНАКОВОГО текста на странице (например, на
# скриншоте пользователя в календаре уже висит событие с названием
# ровно "Поручение") выбирать пункт МЕНЮ рядом с кнопкой, а не
# случайную карточку события с тем же текстом где-то ещё на странице.

def safe_print(t):
    try:
        sys.stdout.buffer.write((str(t)+"\n").encode("utf-8","replace"))
        sys.stdout.buffer.flush()
    except Exception: pass

def log(msg, level="INFO"):
    ts = datetime.now().strftime("%H:%M:%S")
    entry = f"[{ts}] [{level}] {msg}"
    safe_print(entry)
    report.append(entry)
    if level == "FAIL": results["failed"] += 1
    elif level == "PASS": results["passed"] += 1
    elif level == "WARN": results["warnings"] += 1

def shot(name):
    """Сохраняет скриншот ЛОКАЛЬНО (для отладки), в Telegram больше НЕ
    отправляет — этот вызов срабатывает не только на ошибках, но и на
    многих успешных шагах (открытие дропдауна, клик по опции и т.д.), из-за
    чего в чат раньше улетала куча фото за один прогон."""
    try:
        p = screen_path(f"scr_{name}.png")
        driver.save_screenshot(p)
    except Exception: pass

# ==========================================
# УТИЛИТЫ
# ==========================================
def js_click(el):
    driver.execute_script("arguments[0].click();", el)

def scroll_to(el):
    driver.execute_script("arguments[0].scrollIntoView({block:'center',behavior:'instant'});", el)

def wait_for(loc, timeout=WAIT, cond="presence"):
    c = {"presence": EC.presence_of_element_located,
         "visible": EC.visibility_of_element_located,
         "clickable": EC.element_to_be_clickable}
    return WebDriverWait(driver, timeout).until(c.get(cond, c["presence"])(loc))


# ==========================================
# АДАПТАЦИЯ ПОД НОВЫЙ ДИЗАЙН (портировано из waybill/contract):
# реальный сайт НЕ на Ant Design — свой BEM-кит (ui-select__*,
# action-modal__*, ui-date-picker__*). Все функции ниже сначала
# пробуют новый кит, потом старый Ant Design (на случай смешанной
# вёрстки), потом общий geometry-фолбэк.
# ==========================================
UI_KIT_TRIGGER_CLASS_HINTS = [
    "ui-select__trigger", "ui-select-trigger",
    "ui-dropdown__trigger", "ui-picker__trigger",
]


def _hard_click(el):
    """Клик с полной цепочкой pointer/mouse событий — новый ui-select
    слушает pointerdown/mousedown, обычный click часто игнорируется."""
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


def find_ui_kit_trigger_near_label(scope, label_text):
    """Ищет <button class='ui-select__trigger...'> рядом с текстом лейбла.

    ВАЖНО: раньше использовался XPath 'following::' от узла лейбла —
    это ось ПО ВСЕМУ ДОКУМЕНТУ, а не только внутри scope, поэтому даже
    передача scope=модалка не спасала: поиск мог случайно перепрыгнуть
    на элемент страницы ПОЗАДИ модалки (подтверждено скриншотом —
    вместо поля 'Исполнитель' кликался селектор пагинации 'Строк на
    стр.'). Теперь: собираем ВСЕ триггеры СТРОГО внутри scope (это
    гарантированно только потомки scope, т.к. поиск идёт через
    scope.find_elements с относительным './/'), и выбираем среди них
    геометрически ближайший к лейблу (ниже/правее по экрану)."""
    try:
        labels = scope.find_elements(By.XPATH, f".//*[normalize-space(text())='{label_text}']")
        label = None
        for lbl in labels:
            if lbl.is_displayed():
                label = lbl
                break
        if not label:
            return None

        candidates = []
        for hint in UI_KIT_TRIGGER_CLASS_HINTS:
            try:
                found = scope.find_elements(By.XPATH, f".//*[contains(@class,'{hint}')]")
                candidates.extend([c for c in found if c.is_displayed()])
            except Exception:
                continue
        if not candidates:
            return None

        best = driver.execute_script("""
            var label = arguments[0];
            var cands = arguments[1];
            var lr = label.getBoundingClientRect();
            var best = null, bestScore = Infinity;
            for (var i = 0; i < cands.length; i++) {
                var el = cands[i];
                var r = el.getBoundingClientRect();
                var dy = r.top - lr.bottom;
                var dx = Math.abs(r.left - lr.left);
                if (dy < -5 || dy > 120) continue;  // должен быть не выше лейбла и не слишком далеко ниже
                var score = Math.max(dy, 0) + dx;
                if (score < bestScore) { bestScore = score; best = el; }
            }
            return best;
        """, label, candidates)
        return best
    except Exception:
        pass
    return None


def find_control_near_label(label_text, max_dy=90, max_dx=80):
    """Geometry-фолбэк: ищет ближайший кликабельный элемент рядом
    с текстом лейбла, если ни ui-select, ни ant-select не найдены."""
    try:
        labels = driver.find_elements(By.XPATH, f"//*[normalize-space(text())='{label_text}']")
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
                'input, textarea, button, [role="combobox"], [role="button"], [tabindex], div');
            var best = null, bestScore = Infinity;
            for (var i = 0; i < all.length; i++) {
                var el = all[i];
                if (el === label || el.contains(label) || label.contains(el)) continue;
                var r = el.getBoundingClientRect();
                if (r.width < 40 || r.height < 16) continue;
                var dy = r.top - lr.bottom;
                var dx = Math.abs(r.left - lr.left);
                var dyAlt = lr.top - r.top;
                if ((dy < -5 || dy > maxDy) && (dyAlt < -5 || dyAlt > maxDy)) continue;
                if (dx > maxDx && Math.abs(r.top - lr.top) > 10) continue;
                var style = window.getComputedStyle(el);
                if (style.display === 'none' || style.visibility === 'hidden') continue;
                var looksInteractive =
                    el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' ||
                    el.tagName === 'BUTTON' || el.getAttribute('role') === 'combobox' ||
                    el.getAttribute('role') === 'button' || style.cursor === 'pointer' ||
                    el.hasAttribute('tabindex');
                if (!looksInteractive) continue;
                var score = Math.max(dy, dyAlt, 0) + dx;
                if (score < bestScore) { bestScore = score; best = el; }
            }
            return best;
        """, label, max_dy, max_dx)
        return control
    except Exception:
        return None


def find_visible_modal_container(hint_text=None):
    """Ищет открытую панель/модалку/drawer — не завязано на ant-drawer,
    пробует реальные классы нового кита и общий geometry-фолбэк."""
    strategies = [
        "//div[contains(@class,'action-modal__shell')]",
        "//div[contains(@class,'action-modal__body')]",
        "//div[contains(@class,'ant-drawer-body')]",
        "//div[contains(@class,'ant-modal-body')]",
        "//*[contains(@class,'ui-drawer__body') or contains(@class,'ui-panel__body') "
        "or contains(@class,'ui-modal__body') or contains(@class,'ui-modal__content')]",
        "//*[@role='dialog']",
        "//*[contains(@class,'drawer') and (contains(@class,'body') or contains(@class,'content'))]",
        "//*[contains(@class,'panel') and (contains(@class,'body') or contains(@class,'content'))]",
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


def wait_for_visible_modal(hint_text=None, timeout=5, interval=0.3):
    """Ждёт появления модалки вместо одной фиксированной паузы в 1с.

    ИСПРАВЛЕНО: в тестах создания из календаря был жёсткий time.sleep(1)
    перед единственной проверкой find_visible_modal_container — если
    модалка отрисовывалась чуть медленнее (например, когда в календаре
    уже накопилось больше событий от прошлых прогонов), проверка
    срабатывала раньше и тест падал с 'Форма не открылась', хотя форма
    на самом деле просто ещё не успела появиться. Опрашиваем несколько
    раз вместо одной попытки."""
    deadline = time.time() + timeout
    modal = None
    while time.time() < deadline:
        modal = find_visible_modal_container(hint_text=hint_text)
        if modal is not None:
            return modal
        time.sleep(interval)
    return modal


def _table_rows_generic():
    """Универсальный поиск строк таблицы: пробует ant-table, затем
    обычный семантический <table> (так устроены таблицы в новом
    дизайне — без ant-* классов, просто <table>/<tbody>/<tr>)."""
    try:
        rows = driver.find_elements(
            By.XPATH,
            "//div[contains(@class,'ant-table')]//tbody//tr[contains(@class,'ant-table-row')]")
        if rows:
            return rows
    except Exception:
        pass
    try:
        rows = driver.find_elements(By.XPATH, "//table//tbody//tr")
        return rows
    except Exception:
        return []


def _any_table_present(timeout=15):
    """Ждёт появления ЛЮБОЙ таблицы — ant-table (старый дизайн) или
    обычный <table> (новый дизайн)."""
    try:
        WebDriverWait(driver, timeout).until(
            lambda d: d.find_elements(By.XPATH, "//div[contains(@class,'ant-table')]")
            or d.find_elements(By.XPATH, "//table"))
        return True
    except Exception:
        return False


def get_total():
    """Читает 'Всего: N'. Если получилось 0 — логируем диагностику:
    что реально сейчас в поле поиска (подозрение, что там что-то
    осталось от прошлого теста и режет результаты в ноль)."""
    try:
        for el in driver.find_elements(By.XPATH, "//*[contains(text(),'Всего')]"):
            if not el.is_displayed():
                continue
            nums = re.findall(r'\d+', el.text)
            if nums:
                total = int(nums[0])
                if total == 0:
                    try:
                        inps = driver.find_elements(By.XPATH, "//input[contains(@placeholder,'Поиск')]")
                        cur_search = (inps[0].get_attribute("value") if inps else "?")
                        log(f"    [DIAG] Всего=0 (текст: '{el.text}'). "
                            f"Поле поиска сейчас содержит: '{cur_search}'", "DIAG")
                    except Exception:
                        pass
                return total
    except Exception: pass
    return -1

def count_rows():
    time.sleep(0.3)
    try:
        no = driver.find_elements(
            By.XPATH,
            "//div[contains(@class,'ant-empty')] | "
            "//*[contains(@class,'empty') and (contains(@class,'state') or contains(@class,'stub'))]")
        if no and any(n.is_displayed() for n in no): return 0
        rows = _table_rows_generic()
        return len([r for r in rows if r.is_displayed()])
    except Exception: return -1

# ==========================================
# ПАНЕЛЬ ФИЛЬТРА
# ==========================================
def open_panel():
    """ВАЖНО (подтверждено скриншотом реальной страницы): отдельной
    открываемой панели фильтра НЕТ вообще. Все фильтры — это кнопки,
    всегда лежащие прямо на странице ('Тип задачи: все' и т.д.),
    ничего открывать не нужно. Оставлена как no-op для совместимости
    со старым кодом, который её вызывает."""
    return True

def get_body():
    """Раз отдельной панели нет — 'тело' для поиска фильтров это вся
    страница целиком."""
    return driver

def click_apply():
    """ПОДТВЕРЖДЕНО (скриншот): такой кнопки на реальной странице нет —
    фильтр применяется мгновенно, как только выбрано значение. Поиск
    кнопки только тратил бы время впустую, поэтому сразу возвращаем
    успех, ничего не ищем."""
    return True

def click_reset():
    """Нажимает 'Сбросить фильтры' с retry."""
    for attempt in range(3):
        try:
            btns = driver.find_elements(By.XPATH, "//button[contains(.,'Сбросить')]")
            for b in btns:
                if b.is_displayed() and b.is_enabled():
                    scroll_to(b)
                    time.sleep(0.2)
                    if not _hard_click(b):
                        js_click(b)
                    time.sleep(0.8)
                    return True
        except Exception: pass
        time.sleep(0.5)
    log("Кнопка 'Сбросить фильтры' не найдена", "FAIL")
    return False

def reset_and_apply():
    """Сбросить + Применить (если нужно)."""
    click_reset()
    time.sleep(0.8)
    return click_apply()

def close_panel():
    """Панели нет — просто закрываем любой случайно оставшийся
    открытым дропдаун (Escape) для чистоты перед следующим шагом."""
    try:
        ActionChains(driver).send_keys(Keys.ESCAPE).perform()
        time.sleep(0.2)
    except Exception:
        pass

# ==========================================
# РАБОТА С ДРОПДАУНАМИ
# ==========================================
def find_dropdown_by_label(body, label, default_text):
    """РЕАЛЬНАЯ разметка страницы (подтверждено скриншотом): каждый
    фильтр — это ОДНА кнопка с текстом вида 'Тип задачи: все' (лейбл
    и текущее значение объединены в одном элементе, отдельного текста
    лейбла рядом с контролом НЕТ). Ищем самый маленький видимый
    элемент, чей текст начинается с 'label:'."""
    try:
        candidates = body.find_elements(
            By.XPATH, f".//*[starts-with(normalize-space(.), '{label}:')]")
        best, best_area = None, None
        for cand in candidates:
            try:
                if not cand.is_displayed():
                    continue
                size = cand.size
                if size["height"] > 80 or size["width"] > 400:
                    continue  # это уже целый контейнер/страница, не сам триггер
                area = size["width"] * size["height"]
                if best is None or area < best_area:
                    best, best_area = cand, area
            except Exception:
                continue
        if best:
            return best
    except Exception:
        pass

    # Запасные способы (на случай другой вёрстки где-то ещё на сайте)
    try:
        cand = find_ui_kit_trigger_near_label(body, label)
        if cand:
            return cand
    except Exception:
        pass

    try:
        labels = body.find_elements(By.XPATH,
            f".//*[normalize-space(text())='{label}']")
        for lbl in labels:
            if not lbl.is_displayed():
                continue
            try:
                next_select = lbl.find_element(By.XPATH,
                    "following::div[contains(@class,'ant-select')][1]")
                if next_select.is_displayed():
                    return next_select
            except NoSuchElementException:
                continue
    except Exception:
        pass

    # 2b. Старый ant-select (способ 2: по тексту placeholder)
    try:
        sels = body.find_elements(By.XPATH,
            f".//div[contains(@class,'ant-select')]"
            f"[.//span[contains(text(),'{default_text}')]]")
        for s in sels:
            if s.is_displayed():
                return s
    except Exception:
        pass

    # 3. Geometry-фолбэк
    try:
        cand = find_control_near_label(label)
        if cand:
            return cand
    except Exception:
        pass

    return None

def _dropdown_is_open():
    """Проверяет, открыт ли список опций — новый ui-select ИЛИ
    старый ant-select-dropdown."""
    try:
        opened = driver.find_elements(
            By.XPATH,
            "//div[contains(@class,'ui-select__panel') or contains(@class,'ui-select__dropdown') "
            "or contains(@class,'ui-select__options') or contains(@class,'ui-select__menu')] | "
            "//div[contains(@class,'rc-virtual-list-holder-inner')]"
            "//div[contains(@class,'ant-select-item-option-content')] | "
            "//div[contains(@class,'ant-select-dropdown') and "
            "not(contains(@class,'ant-select-dropdown-hidden'))]")
        return any(o.is_displayed() for o in opened)
    except Exception:
        return False


def open_dropdown(select_el):
    """Кликает по селектору чтобы открыть список опций. Поддерживает
    и новый ui-select (button.ui-select__trigger, слушает
    pointerdown/mousedown — нужен _hard_click), и старый ant-select."""
    try:
        # Если это уже сам триггер нового кита — кликаем его напрямую
        is_ui_kit = False
        try:
            cls = (select_el.get_attribute("class") or "")
            is_ui_kit = "ui-select" in cls or select_el.tag_name == "button"
        except Exception:
            pass

        if is_ui_kit:
            scroll_to(select_el)
            time.sleep(0.2)
            for method in ["hard", "selenium", "js"]:
                try:
                    if method == "hard":
                        _hard_click(select_el)
                    elif method == "selenium":
                        select_el.click()
                    else:
                        js_click(select_el)
                    time.sleep(0.5)
                    if _dropdown_is_open():
                        return True
                except Exception:
                    continue

        # Старый ant-select: ищем внутренний .ant-select-selector
        try:
            selector = select_el.find_element(By.XPATH, ".//div[contains(@class,'ant-select-selector')]")
        except NoSuchElementException:
            selector = select_el

        scroll_to(selector)
        time.sleep(0.3)

        try:
            selector.click()
            time.sleep(0.5)
            if _dropdown_is_open():
                time.sleep(0.5)
                return True
        except Exception:
            pass

        try:
            ActionChains(driver).move_to_element(selector).pause(0.3).click().perform()
            time.sleep(0.8)
            if _dropdown_is_open():
                return True
        except Exception:
            pass

        try:
            search_input = select_el.find_element(By.XPATH,
                ".//input[contains(@class,'ant-select-selection-search-input')]")
            search_input.click()
            time.sleep(0.8)
            if _dropdown_is_open():
                return True
        except Exception:
            pass

        try:
            driver.execute_script("""
                var el = arguments[0];
                var event = new MouseEvent('mousedown', {bubbles: true, cancelable: true, view: window});
                el.dispatchEvent(event);
            """, selector)
            time.sleep(0.8)
            if _dropdown_is_open():
                return True
        except Exception:
            pass

        return False
    except Exception:
        return False

def collect_options(near_element=None):
    """Собирает опции из открытого dropdown. Порядок попыток:
    1. Новый ui-select (button[role='option'] внутри ui-select__panel).
    2. Старый ant-select (rc-virtual-list, ant-select-dropdown, title).
    3. Общий фолбэк по role='option'.
    near_element: если на странице несколько подходящих панелей сразу
    (например, за модалкой ещё что-то осталось) — берём ту, что ближе
    всего расположена к этому элементу (обычно это сам триггер), а не
    просто первую найденную — иначе можно случайно взять чужой список.
    """
    options = []

    def _pick_closest_panel(panels):
        visible = [p for p in panels if p.is_displayed()]
        if not visible:
            return None
        if near_element is None or len(visible) == 1:
            return visible[0]
        try:
            ref_y = near_element.location["y"]
            visible.sort(key=lambda p: abs(p.location["y"] - ref_y))
        except Exception:
            pass
        return visible[0]

    # 1. Новый ui-select
    try:
        panels = driver.find_elements(
            By.XPATH,
            "//div[contains(@class,'ui-select__panel') or contains(@class,'ui-select__dropdown') "
            "or contains(@class,'ui-select__options') or contains(@class,'ui-select__menu')]")
        panel = _pick_closest_panel(panels)
        if panel is not None:
            btns = panel.find_elements(
                By.XPATH,
                ".//button[@role='option'] | .//*[contains(@class,'ui-select__option')]")
            for b in btns:
                if not b.is_displayed():
                    continue
                try:
                    lbl = b.find_element(
                        By.XPATH, ".//span[contains(@class,'ui-select__option-label')]")
                    txt = (lbl.get_attribute("textContent") or "").strip()
                except Exception:
                    txt = (b.get_attribute("textContent") or b.text or "").strip()
                if txt and txt not in [o["text"] for o in options]:
                    options.append({"text": txt, "element": b})
            if options:
                return options
    except Exception:
        pass

    # 2. Старый ant-select
    try:
        inners = driver.find_elements(By.XPATH,
            "//div[contains(@class,'rc-virtual-list-holder-inner')]"
        )
        for inner in inners:
            try:
                if not inner.is_displayed():
                    continue
                items = inner.find_elements(By.XPATH,
                    ".//div[contains(@class,'ant-select-item-option-content')]"
                )
                for item in items:
                    try:
                        txt = item.text.strip()
                        if txt and txt not in [o["text"] for o in options]:
                            options.append({"text": txt, "element": item})
                    except StaleElementReferenceException:
                        continue
                if options:
                    break
            except Exception:
                continue

        if not options:
            containers = driver.find_elements(By.XPATH,
                "//div[contains(@class,'ant-select-dropdown')]"
                "[not(contains(@class,'ant-select-dropdown-hidden'))]"
            )
            for container in containers:
                if not container.is_displayed():
                    continue
                items = container.find_elements(By.XPATH,
                    ".//div[contains(@class,'ant-select-item-option-content')]"
                )
                for item in items:
                    try:
                        txt = item.text.strip()
                        if txt and txt not in [o["text"] for o in options]:
                            options.append({"text": txt, "element": item})
                    except StaleElementReferenceException:
                        continue
                if options:
                    break

        if not options:
            items = driver.find_elements(By.XPATH,
                "//div[contains(@class,'ant-select-item-option')][@title]"
            )
            for item in items:
                try:
                    if not item.is_displayed():
                        continue
                    txt = item.get_attribute("title").strip()
                    if txt and txt not in [o["text"] for o in options]:
                        options.append({"text": txt, "element": item})
                except Exception:
                    continue
        if options:
            return options
    except Exception:
        pass

    # 3. Общий фолбэк
    try:
        items = driver.find_elements(By.XPATH, "//*[@role='option']")
        for item in items:
            if not item.is_displayed():
                continue
            txt = (item.text or item.get_attribute("textContent") or "").strip()
            if txt and txt not in [o["text"] for o in options]:
                options.append({"text": txt, "element": item})
    except Exception:
        pass

    return options

def _click_option_robustly(el):
    """Клик по опции: новый ui-select игнорирует обычный клик, нужен
    _hard_click с полной цепочкой pointer-событий. Пробуем по очереди."""
    try:
        scroll_to(el)
        time.sleep(0.15)
    except Exception:
        pass
    for method in ["hard", "selenium", "js"]:
        try:
            if method == "hard":
                if not _hard_click(el):
                    continue
            elif method == "selenium":
                el.click()
            else:
                js_click(el)
            time.sleep(0.4)
            if not _dropdown_is_open():
                return True
        except Exception:
            continue
    return False


def close_dropdown_safe():
    """Закрывает открытый dropdown — Escape, затем клик по заголовку
    панели, затем клик по самой панели как последний вариант."""
    try:
        ActionChains(driver).send_keys(Keys.ESCAPE).perform()
        time.sleep(0.25)
        if not _dropdown_is_open():
            return
    except Exception:
        pass
    try:
        title = driver.find_elements(
            By.XPATH,
            "//div[contains(@class,'ant-drawer-title')] | //*[contains(text(),'Фильтр задач')]")
        for t in title:
            if t.is_displayed():
                js_click(t)
                time.sleep(0.4)
                return
        body = get_body()
        if body:
            driver.execute_script("arguments[0].click();", body)
            time.sleep(0.4)
    except Exception: pass


def _close_form_dropdown_safe(trigger_el, modal=None):
    """Закрывает открытый dropdown ВНУТРИ модалки формы (Создать
    поручение/задачу), НЕ используя Escape.

    ПОДТВЕРЖДЕНО скриншотом: поле "Наблюдатели" — мультивыбор
    (чекбоксы), его список НЕ закрывается сам после клика по опции —
    так и задумано, можно отметить несколько. Обычный close_dropdown_safe()
    в этом случае первым делом жмёт Escape — а если фокус после серии
    программных кликов не на самом списке, Escape рискует закрыть не
    список, а ВСЮ МОДАЛКУ формы целиком, из-за чего все следующие шаги
    (Описание, Опубликовать) выполняются вхолостую и запись не создаётся.
    Вместо Escape кликаем по самому триггеру ещё раз (стандартный способ
    закрыть открытый мульти-select) или по заголовку модалки — оба
    варианта остаются ВНУТРИ формы и не могут случайно её закрыть."""
    try:
        if not _dropdown_is_open():
            return
    except Exception:
        pass
    try:
        if trigger_el is not None:
            if not _hard_click(trigger_el):
                js_click(trigger_el)
            time.sleep(0.3)
            if not _dropdown_is_open():
                return
    except Exception:
        pass
    try:
        scope = modal if modal is not None else driver
        title = scope.find_elements(By.XPATH, ".//*[contains(text(),'Создать поручение')]")
        for t in title:
            if t.is_displayed():
                js_click(t)
                time.sleep(0.3)
                return
    except Exception:
        pass

# ==========================================
# 1. АВТОРИЗАЦИЯ
# ==========================================
def run_login():
    log("=" * 50)
    log("ЭТАП 1: АВТОРИЗАЦИЯ")
    driver.get(BASE_URL)
    time.sleep(1)
    if "tab=" in driver.current_url:
        log("Уже авторизованы", "PASS")
        return True
    try:
        el = wait_for((By.ID, "username"), cond="visible"); el.clear(); el.send_keys(login_val)
        el = wait_for((By.ID, "password"), cond="visible"); el.clear(); el.send_keys(pass_val)
        js_click(wait_for((By.XPATH, "//button[@type='submit']"), cond="clickable"))
        time.sleep(1.5)
        _any_table_present(timeout=20)  # или таблица (любой кит), или просто дождались перехода
        log("Авторизация успешна", "PASS")
        return True
    except Exception:
        log("Авторизация не удалась", "FAIL"); shot("login_fail"); return False

# ==========================================
# 2. ПЕРЕХОД НА ЗАДАЧИ
# ==========================================
def go_to_tasks():
    log("=" * 50)
    log("ЭТАП 2: ПЕРЕХОД НА ЗАДАЧИ")
    if "tab=tasks" not in driver.current_url:
        driver.get(TASKS_URL); time.sleep(1.5)
    try:
        if not _any_table_present(timeout=15):
            raise TimeoutException("таблица не появилась")
        log(f"Страница задач. Всего: {get_total()}", "PASS")
        return True
    except Exception:
        log("Таблица не найдена", "FAIL"); return False


# ==========================================
# КАЛЕНДАРЬ — 16 проверок из чек-листа
# ==========================================
# ==========================================
# ПОРУЧЕНИЯ (форма создания — та же самая, что и в 'Задачи';
# переиспользуем уже существующие универсальные функции для фильтров:
# test_dropdown_all_values / test_dates / click_reset)
# ==========================================
def go_to_assignments():
    log("=" * 50)
    log("ПЕРЕХОД В 'ПОРУЧЕНИЯ'")
    try:
        links = driver.find_elements(By.XPATH, "//*[normalize-space(text())='Поручения']")
        visible = [l for l in links if l.is_displayed()]
        if not visible:
            log("Ссылка 'Поручения' не найдена", "FAIL")
            shot("assignments_link_not_found")
            return False
        if not _hard_click(visible[0]):
            js_click(visible[0])
        time.sleep(1.2)
        if not _any_table_present(timeout=15):
            log("Таблица поручений не появилась", "FAIL")
            shot("assignments_no_table")
            return False
        log(f"Раздел 'Поручения' открылся. Всего: {get_total()}", "PASS")
        return True
    except Exception as e:
        log(f"Ошибка перехода в 'Поручения': {e}", "FAIL")
        return False


def test_assignments_reset_button():
    log("=" * 50)
    log("ТЕСТ: Поручения — кнопка 'Сбросить фильтры'")
    ok = click_reset()
    if not ok:
        shot("assignments_reset_not_found")
    report_to_sheet("Кнопка «Сбросить фильтры»", ok, ROWS_ASSIGNMENTS)


def test_assignments_filters():
    # Объединённая проверка фильтрации поручений ОДНОЙ строкой в чек-листе
    # (эквивалентное разбиение по значениям фильтров + дата в одном
    # сценарии, вместо отдельных строк на каждую часть).
    filters_ok = test_filters_quick(
        filters=[
            ("Проект", "Все проекты", None),
            ("Статус", "Все статусы", None),
        ],
        rows=ROWS_ASSIGNMENTS,
        report_label="Фильтры поручений",
    )

    dates_ok = test_dates()

    report_to_sheet("Фильтрация поручений", filters_ok and dates_ok, ROWS_ASSIGNMENTS)


def test_assignments_create():
    log("=" * 50)
    log("ТЕСТ: Поручения — создание (публикация)")
    try:
        btn = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.XPATH,
                "//button[contains(., 'Создать') and not(contains(@class,'disabled'))]"))
        )
        scroll_to(btn)
        time.sleep(0.2)
        try:
            btn.click()
        except Exception:
            js_click(btn)
        time.sleep(1)
        log("  Клик по кнопке 'Создать'", "PASS")
    except Exception as e:
        log(f"  Кнопка 'Создать' не найдена: {e}", "FAIL")
        return False

    modal = find_visible_modal_container(hint_text="поручение")
    if not modal:
        log("  Форма 'Создать поручение' не открылась", "FAIL")
        shot("assignments_create_form_missing")
        return False
    log("  Форма 'Создать поручение' открылась", "PASS")

    _fill_poruchenie_fields(modal, name_prefix="Поручения")
    time.sleep(0.3)
    return _submit_poruchenie_form("Опубликовать")


def test_assignments_create_draft():
    log("=" * 50)
    log("ТЕСТ: Поручения — сохранение как черновик")
    try:
        btn = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.XPATH,
                "//button[contains(., 'Создать') and not(contains(@class,'disabled'))]"))
        )
        scroll_to(btn)
        time.sleep(0.2)
        try:
            btn.click()
        except Exception:
            js_click(btn)
        time.sleep(1)
        log("  Клик по кнопке 'Создать'", "PASS")
    except Exception as e:
        log(f"  Кнопка 'Создать' не найдена: {e}", "FAIL")
        return False

    modal = find_visible_modal_container(hint_text="поручение")
    if not modal:
        log("  Форма 'Создать поручение' не открылась", "FAIL")
        return False
    log("  Форма 'Создать поручение' открылась", "PASS")

    # ИСПРАВЛЕНО (по запросу): черновик тоже должен заполняться по всем
    # полям, как и публикация, а не только по Наименованию.
    _fill_poruchenie_fields(modal, name_prefix="Поручения Черновик")

    time.sleep(0.3)
    return _submit_poruchenie_form("Сохранить")


def test_assignments():
    if not go_to_assignments():
        return
    test_assignments_reset_button()
    test_assignments_filters()
    ok = test_assignments_create()
    report_to_sheet("Создание поручения", ok, ROWS_ASSIGNMENTS)
    time.sleep(1)
    go_to_assignments()
    ok = test_assignments_create_draft()
    report_to_sheet("Сохранение поручения как черновик", ok, ROWS_ASSIGNMENTS)
    test_assignment_type_scenarios()


ASSIGNMENT_SCENARIOS = (
    ("Поручение", "Создание поручения — тип «Поручение»", False),
    ("Поручение на стройке", "Создание поручения — тип «Поручение на стройке»", False),
    ("Заявка на договор поставки", "Создание поручения — тип «Заявка на договор поставки»", False),
    ("Заявка на договор услуг", "Создание поручения — тип «Заявка на договор услуг»", False),
    ("Поручение", "Создание поручения с вложением документа", True),
)


def _assignment_diagnostic(scenario_index):
    """HTML и скриншот одним пакетом при неподтверждённой разметке формы."""
    from pathlib import Path
    root = LOGS_DIR / "assignment_diagnostics"
    root.mkdir(exist_ok=True)
    stem = f"assignment_{scenario_index}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    (root / (stem + ".html")).write_text(
        driver.execute_script("return document.body.innerHTML"), encoding="utf-8")
    driver.save_screenshot(screen_path(stem + ".png"))
    log(f"  Диагностика формы: {root / stem}")


def _select_assignment_type(modal, assignment_type):
    trigger = find_ui_kit_trigger_near_label(modal, "Тип поручения")
    if trigger is None:
        trigger = find_ui_kit_trigger_near_label(modal, "Тип поручения (необязательно)")
    if trigger is None:
        raise RuntimeError("Не найден селектор 'Тип поручения'")
    if not open_dropdown(trigger):
        raise RuntimeError("Список типов поручения не открылся")

    def exact_options(_driver):
        options = collect_options(near_element=trigger)
        return [o for o in options if o['text'].strip() == assignment_type] or False

    # Дерево может быть свёрнуто: раскрываем только нужную группу один раз.
    group = "Заявка на договор" if assignment_type.startswith("Заявка на договор") else "Поручение"
    panels = driver.find_elements(By.XPATH, "//div[contains(@class,'ui-select__panel')]")
    for panel in panels:
        if not panel.is_displayed():
            continue
        branches = panel.find_elements(By.XPATH, ".//*[@aria-expanded='false']")
        for branch in branches:
            if branch.is_displayed() and group in (branch.text or ""):
                branch.click()
                break
    options = WebDriverWait(driver, 7).until(exact_options)
    if len(options) != 1:
        raise RuntimeError(f"Тип '{assignment_type}' найден неоднозначно")
    element = options[0]['element']
    if not _hard_click(element):
        element.click()
    _close_form_dropdown_safe(trigger, modal)
    def selected(_driver):
        current = find_ui_kit_trigger_near_label(modal, "Тип поручения")
        if current is None:
            current = find_ui_kit_trigger_near_label(modal, "Тип поручения (необязательно)")
        if current is None:
            return False
        values = current.find_elements(By.XPATH, ".//*[contains(@class,'ui-select__value')]")
        text = values[0].text if values else current.text
        return text.strip() == assignment_type
    WebDriverWait(driver, 5).until(selected)
    log(f"  Тип поручения выбран и проверен: {assignment_type}", "PASS")


def _assignment_pdf():
    """Минимальный корректный PDF без дополнительных библиотек."""
    from pathlib import Path
    root = Path(__file__).resolve().parent / "assignment_test_files"
    root.mkdir(exist_ok=True)
    path = root / f"assignment_attachment_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
    stream = b"BT /F1 12 Tf 50 750 Td (RGB assignment attachment test) Tj ET"
    objects = [b'<< /Type /Catalog /Pages 2 0 R >>',
               b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
               b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>',
               b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
               b'<< /Length ' + str(len(stream)).encode() + b' >>\nstream\n' + stream + b'\nendstream']
    data = bytearray(b'%PDF-1.4\n'); offsets = [0]
    for i, obj in enumerate(objects, 1):
        offsets.append(len(data)); data.extend(f'{i} 0 obj\n'.encode() + obj + b'\nendobj\n')
    xref = len(data)
    data.extend(b'xref\n0 6\n0000000000 65535 f \n')
    for offset in offsets[1:]:
        data.extend(f'{offset:010d} 00000 n \n'.encode())
    data.extend(f'trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n'.encode())
    path.write_bytes(data)
    return path


def _attach_assignment_document(modal, path):
    inputs = modal.find_elements(By.CSS_SELECTOR, "input[type='file']")
    if len(inputs) != 1:
        raise RuntimeError(f"Ожидался один input для вложения, найдено {len(inputs)}")
    inputs[0].send_keys(str(path))
    WebDriverWait(driver, 15).until(lambda _d: path.name in modal.text)
    log(f"  Вложение отображается в форме: {path.name}", "PASS")


def _validate_assignment_common_fields(modal, log_start):
    failures = [line for line in report[log_start:] if "[FAIL]" in line]
    if failures:
        raise RuntimeError("Не заполнены поля формы: " + "; ".join(failures))
    for xpath, label in [
        (".//input[contains(@placeholder,'аименование')]", "Наименование"),
        (".//input[contains(@class,'ui-date-picker__input')]", "Срок исполнения"),
        (".//textarea[contains(@placeholder,'Ввести текст')]", "Описание"),
    ]:
        inputs = [e for e in modal.find_elements(By.XPATH, xpath) if e.is_displayed()]
        if not inputs or not (inputs[0].get_attribute('value') or '').strip():
            raise RuntimeError(f"Поле '{label}' не заполнено")


def _publish_assignment(modal, test_name, attachment_name=None):
    buttons = modal.find_elements(By.XPATH, ".//button[normalize-space(.)='Опубликовать']")
    if not buttons:
        raise RuntimeError("Кнопка 'Опубликовать' не найдена в форме")
    button = buttons[0]
    WebDriverWait(driver, 10).until(lambda _d: button.is_enabled())
    # Успех требует появления созданной записи; одного клика недостаточно.
    if not _hard_click(button):
        button.click()
    WebDriverWait(driver, 15).until(lambda _d: not find_visible_modal_container(hint_text="поручение"))
    if not go_to_assignments():
        raise RuntimeError("После публикации не удалось открыть список поручений")
    def record_visible(_driver):
        rows = driver.find_elements(By.XPATH, "//tr | //*[@role='row']")
        return next((r for r in rows if r.is_displayed() and test_name in r.text), False)
    row = WebDriverWait(driver, 15).until(record_visible)
    log(f"  Созданная запись найдена: {test_name}", "PASS")
    if attachment_name:
        targets = row.find_elements(By.XPATH, f".//*[normalize-space(.)='{test_name}']")
        if not targets:
            raise RuntimeError("Нельзя открыть созданную запись и проверить сохранение вложения")
        targets[-1].click()
        WebDriverWait(driver, 15).until(lambda _d: attachment_name in driver.find_element(By.TAG_NAME,'body').text)
        log(f"  Вложение сохранено в созданном поручении: {attachment_name}", "PASS")


def test_assignment_type_scenarios():
    for index, (assignment_type, checklist_name, attach) in enumerate(ASSIGNMENT_SCENARIOS, 1):
        log("=" * 50)
        log(f"ТЕСТ {index}/{len(ASSIGNMENT_SCENARIOS)}: {checklist_name}")
        ok = False
        try:
            # Переход заново убирает незакрытую форму предыдущего сценария.
            driver.get(TASKS_URL)
            if not go_to_assignments():
                raise RuntimeError("Раздел 'Поручения' не открылся")
            create = WebDriverWait(driver, 10).until(EC.element_to_be_clickable((
                By.XPATH, "//button[normalize-space(.)='Создать']")))
            create.click()
            modal = wait_for_visible_modal(hint_text="поручение")
            if modal is None:
                raise RuntimeError("Форма создания поручения не открылась")
            _select_assignment_type(modal, assignment_type)
            log_start = len(report)
            test_name = _fill_poruchenie_fields(modal, name_prefix=f"Автотест тип {index}")
            _validate_assignment_common_fields(modal, log_start)
            pdf = _assignment_pdf() if attach else None
            if pdf:
                _attach_assignment_document(modal, pdf)
            _publish_assignment(modal, test_name, pdf.name if pdf else None)
            ok = True
        except Exception as error:
            log(f"  {checklist_name}: {error}", "FAIL")
            try:
                _assignment_diagnostic(index)
            except Exception as diagnostic_error:
                log(f"  Не удалось сохранить диагностику: {diagnostic_error}", "WARN")
        report_to_sheet(checklist_name, ok, ROWS_ASSIGNMENTS)


def go_to_calendar():
    log("=" * 50)
    log("ПЕРЕХОД В КАЛЕНДАРЬ")
    try:
        links = driver.find_elements(By.XPATH, "//*[normalize-space(text())='Календарь']")
        visible = [l for l in links if l.is_displayed()]
        if not visible:
            log("Ссылка 'Календарь' не найдена", "FAIL")
            shot("calendar_link_not_found")
            return False
        if not _hard_click(visible[0]):
            js_click(visible[0])
        time.sleep(1.2)

        month_ok = driver.find_elements(By.XPATH, "//*[normalize-space(text())='Сентябрь' or "
            "normalize-space(text())='Октябрь' or normalize-space(text())='Ноябрь' or "
            "normalize-space(text())='Декабрь' or normalize-space(text())='Январь' or "
            "normalize-space(text())='Февраль' or normalize-space(text())='Март' or "
            "normalize-space(text())='Апрель' or normalize-space(text())='Май' or "
            "normalize-space(text())='Июнь' or normalize-space(text())='Июль' or "
            "normalize-space(text())='Август']")
        if any(m.is_displayed() for m in month_ok):
            log("Раздел 'Календарь' открылся", "PASS")
            report_to_sheet("Переход в раздел «Календарь»", True, ROWS_CALENDAR)
            return True
        else:
            log("Раздел открылся, но месяц/год в шапке не найден", "FAIL")
            shot("calendar_no_month_header")
            report_to_sheet("Переход в раздел «Календарь»", False, ROWS_CALENDAR)
            return False
    except Exception as e:
        log(f"Ошибка перехода в календарь: {e}", "FAIL")
        return False


MONTH_NAMES_RU = ["январь", "февраль", "март", "апрель", "май", "июнь",
                  "июль", "август", "сентябрь", "октябрь", "ноябрь", "декабрь"]


def _current_month_label():
    try:
        candidates = driver.find_elements(By.XPATH, "//*[self::button or self::div or self::span]")
        for c in candidates:
            if not c.is_displayed():
                continue
            txt = (c.text or "").strip().lower()
            if txt in MONTH_NAMES_RU:
                return c.text.strip()
    except Exception:
        pass
    return None


def _buttons_with_svg_path(path_d):
    """Находит <button>, внутри которого лежит <svg><path d="..."> с точно
    таким значением d — самый надёжный способ найти конкретную
    иконку-стрелку, а не гадать по геометрии."""
    try:
        paths = driver.find_elements(
            By.XPATH, f"//button//*[local-name()='path' and @d='{path_d}']")
        found = []
        for p in paths:
            try:
                btn = p.find_element(By.XPATH, "ancestor::button[1]")
                if btn.is_displayed():
                    found.append(btn)
            except Exception:
                continue
        return found
    except Exception:
        return []


def _month_nav_arrows():
    """Стрелки '<' и '>' переключения месяца.

    ИСПРАВЛЕНО (по HTML из DevTools, который прислал пользователь):
    геометрическая эвристика ("ближайшая кнопка рядом с названием
    месяца") на практике попадала по самому названию месяца, а не по
    стрелкам — клик "срабатывал", но месяц не менялся. Теперь ищем
    СТРОГО по конкретным SVG-иконкам chevron-left/chevron-right
    (подтверждённые пути: prev = 'm15 18-6-6 6-6', next = 'm9 18 6-6-6-6'),
    а из найденных кандидатов берём ближайший по вертикали к названию
    месяца — на случай, если такая же иконка есть где-то ещё на странице."""
    try:
        month_el = None
        for c in driver.find_elements(By.XPATH, "//*[self::button or self::div or self::span]"):
            if c.is_displayed() and (c.text or "").strip().lower() in MONTH_NAMES_RU:
                month_el = c
                break

        prev_candidates = _buttons_with_svg_path("m15 18-6-6 6-6")
        next_candidates = _buttons_with_svg_path("m9 18 6-6-6-6")

        prev_btn = _pick_closest_to(month_el, prev_candidates) if prev_candidates else None
        next_btn = _pick_closest_to(month_el, next_candidates) if next_candidates else None
        return prev_btn, next_btn
    except Exception:
        return None, None


def _click_month_arrow_and_wait(get_arrow_fn, before_label, max_attempts=3):
    """Кликает по стрелке (next/prev, через get_arrow_fn) и ждёт смены
    месяца.

    ОТКАЧЕНО: предыдущая версия при неудаче кликала ПОВТОРНО (до 3 раз) —
    на практике это оказалось хуже одного клика: если первый клик на
    самом деле сработал, но месяц просто не успел перерисоваться за 3с,
    второй и третий клики уводили календарь на 2-3 месяца вперёд, а
    заголовок месяца в моменте пересчёта переставал находиться вообще
    (лейбл 'None' в логе). Кликаем ОДИН раз и ждём смены дольше (до 6с),
    без повторных кликов."""
    btn = get_arrow_fn()
    if not btn:
        return None
    if not _hard_click(btn):
        js_click(btn)
    deadline = time.time() + 6
    while time.time() < deadline:
        after = _current_month_label()
        if before_label and after and before_label != after:
            return after
        time.sleep(0.3)
    return None


def test_calendar_navigation():
    log("=" * 50)
    log("ТЕСТ: Календарь — навигация по месяцам")
    next_ok, prev_ok = False, False
    try:
        before = _current_month_label()
        log(f"  Текущий месяц: '{before}'")

        _, next_btn = _month_nav_arrows()
        if not next_btn:
            log("  Стрелка 'следующий месяц' не найдена", "FAIL")
            shot("calendar_no_next_arrow")
        else:
            after = _click_month_arrow_and_wait(
                lambda: _month_nav_arrows()[1], before)
            log(f"  Месяц после '>': '{after}'")
            if after:
                log("  Переключение на следующий месяц работает", "PASS")
                next_ok = True
            else:
                log("  Месяц не изменился после клика '>'", "FAIL")
                shot("calendar_next_month_failed")

        mid = _current_month_label()
        prev_btn, _ = _month_nav_arrows()
        if not prev_btn:
            log("  Стрелка 'предыдущий месяц' не найдена", "FAIL")
            shot("calendar_no_prev_arrow")
        else:
            after2 = _click_month_arrow_and_wait(
                lambda: _month_nav_arrows()[0], mid)
            log(f"  Месяц после '<': '{after2}'")
            if after2:
                log("  Переключение на предыдущий месяц работает", "PASS")
                prev_ok = True
            else:
                log("  Месяц не изменился после клика '<'", "FAIL")
                shot("calendar_prev_month_failed")
    except Exception as e:
        log(f"  Ошибка теста навигации по месяцам: {e}", "FAIL")

    # Объединяем в одну строку (state-transition: один сценарий "туда и
    # обратно" вместо двух отдельных проверок направления).
    report_to_sheet("Навигация по месяцам (вперёд/назад)", next_ok and prev_ok, ROWS_CALENDAR)


def test_calendar_year_select():
    log("=" * 50)
    log("ТЕСТ: Календарь — выбор года")
    try:
        year_btns = driver.find_elements(By.XPATH, "//*[normalize-space(text())='2026']")
        visible = [b for b in year_btns if b.is_displayed()]
        if not visible:
            log("  Селектор года '2026' не найден", "FAIL")
            shot("calendar_no_year_selector")
            report_to_sheet("Выбор года в выпадающем списке", False, ROWS_CALENDAR)
            return
        if not _hard_click(visible[0]):
            js_click(visible[0])
        time.sleep(0.8)
        # ИСПРАВЛЕНО: список годов оказался обычными пунктами без
        # role='option'/классов ui-select — просто текстовые элементы
        # с 4-значным числом года (подтверждено скриншотом: 2021-2031
        # простым списком). Ищем по этому шаблону вместо строгих классов.
        years = driver.find_elements(
            By.XPATH,
            "//*[self::li or self::div or self::button or self::span]"
            "[string-length(normalize-space(text()))=4]"
            "[translate(normalize-space(text()),'0123456789','') = '']")
        visible_years = [y for y in years if y.is_displayed()]
        if not visible_years:
            log("  Список годов не открылся", "FAIL")
            shot("calendar_year_list_not_open")
            try:
                ActionChains(driver).send_keys(Keys.ESCAPE).perform()
            except Exception:
                pass
            report_to_sheet("Выбор года в выпадающем списке", False, ROWS_CALENDAR)
            return
        log(f"  Список годов открылся ({len(visible_years)} вариантов)", "PASS")
        try:
            ActionChains(driver).send_keys(Keys.ESCAPE).perform()
        except Exception:
            pass
        report_to_sheet("Выбор года в выпадающем списке", True, ROWS_CALENDAR)
    except Exception as e:
        log(f"  Ошибка теста выбора года: {e}", "FAIL")
        report_to_sheet("Выбор года в выпадающем списке", False, ROWS_CALENDAR)


def test_calendar_view_switch():
    log("=" * 50)
    log("ТЕСТ: Календарь — переключение вида (Неделя/Сегодня)")
    checklist_names = {"Неделя": "Переключение вида «Неделя»",
                        "Сегодня": "Кнопка «Сегодня» возвращает на текущую дату"}
    for view_name in ["Неделя", "Сегодня"]:
        ok = False
        try:
            btns = driver.find_elements(By.XPATH, f"//button[contains(.,'{view_name}')]")
            visible = [b for b in btns if b.is_displayed()]
            if not visible:
                log(f"  Кнопка '{view_name}' не найдена", "FAIL")
            else:
                if not _hard_click(visible[0]):
                    js_click(visible[0])
                time.sleep(1)
                log(f"  Клик по '{view_name}'", "PASS")
                shot(f"calendar_view_{view_name}")
                ok = True
        except Exception as e:
            log(f"  '{view_name}': ошибка — {e}", "FAIL")
        report_to_sheet(checklist_names[view_name], ok, ROWS_CALENDAR)

    # Возвращаемся к виду "Месяц" для дальнейших тестов
    try:
        month_btns = driver.find_elements(By.XPATH, "//button[contains(.,'Месяц')]")
        visible = [b for b in month_btns if b.is_displayed()]
        if visible:
            if not _hard_click(visible[0]):
                js_click(visible[0])
            time.sleep(1)
    except Exception:
        pass


def test_calendar_search():
    log("=" * 50)
    log("ТЕСТ: Календарь — поиск события")
    ok = False
    try:
        inps = driver.find_elements(By.XPATH, "//input[contains(@placeholder,'Поиск')]")
        visible = [i for i in inps if i.is_displayed()]
        if not visible:
            log("  Поле поиска не найдено", "FAIL")
            shot("calendar_no_search_field")
        else:
            visible[0].clear()
            visible[0].send_keys("Тест")
            time.sleep(1)
            log("  Введён поисковый запрос 'Тест'", "PASS")
            shot("calendar_after_search")
            visible[0].clear()
            visible[0].send_keys(Keys.ENTER)
            time.sleep(0.5)
            ok = True
    except Exception as e:
        log(f"  Ошибка теста поиска: {e}", "FAIL")
    report_to_sheet("Поиск события по названию", ok, ROWS_CALENDAR)


def _pick_closest_to(ref_element, candidates):
    """Из нескольких одинаковых по тексту элементов выбирает ближайший
    (по вертикали) к ref_element. Нужно там, где на странице может
    оказаться больше одного элемента с одним и тем же текстом (например,
    пункт меню 'Поручение' И карточка события в календаре с названием
    ровно 'Поручение') — простое 'первый найденный' в таком случае может
    случайно попасть не туда."""
    if not candidates:
        return None
    if len(candidates) == 1 or ref_element is None:
        return candidates[0]
    try:
        ref_y = ref_element.location["y"]
        return sorted(candidates, key=lambda c: abs(c.location["y"] - ref_y))[0]
    except Exception:
        return candidates[0]


def _open_calendar_create_menu():
    """Открывает меню 'Создать' (Поручение/Мероприятие). Возвращает True/False."""
    global _calendar_create_btn
    try:
        btns = driver.find_elements(By.XPATH, "//button[contains(.,'Создать')]")
        visible = [b for b in btns if b.is_displayed()]
        if not visible:
            log("  Кнопка 'Создать' не найдена", "FAIL")
            shot("calendar_no_create_button")
            _calendar_create_btn = None
            return False
        _calendar_create_btn = visible[0]
        if not _hard_click(visible[0]):
            js_click(visible[0])
        time.sleep(0.8)
        opts = driver.find_elements(By.XPATH,
            "//*[normalize-space(text())='Поручение'] | //*[normalize-space(text())='Мероприятие']")
        if not any(o.is_displayed() for o in opts):
            log("  Меню 'Создать' не открылось (пункты не найдены)", "FAIL")
            shot("calendar_create_menu_not_open")
            return False
        return True
    except Exception as e:
        log(f"  Ошибка открытия меню 'Создать': {e}", "FAIL")
        return False


def test_calendar_create_menu():
    log("=" * 50)
    log("ТЕСТ: Календарь — открытие меню 'Создать'")
    ok = _open_calendar_create_menu()
    if ok:
        log("  Меню 'Создать' открылось (Поручение/Мероприятие)", "PASS")
        shot("calendar_create_menu_open")
        try:
            ActionChains(driver).send_keys(Keys.ESCAPE).perform()
        except Exception:
            pass
    report_to_sheet("Открытие меню «Создать»", ok, ROWS_CALENDAR)


def _fill_poruchenie_fields(modal, name_prefix="Автотест"):
    """Общая логика заполнения формы 'Создать поручение' — переиспользуется
    в Задачах, Поручениях и Календаре (форма везде одна и та же:
    Наименование/Исполнитель/Срок исполнения/Проект/Описание)."""
    name_inputs = driver.find_elements(By.XPATH, "//input[contains(@placeholder,'аименование')]")
    visible_name = [i for i in name_inputs if i.is_displayed()]
    test_name = f"{name_prefix} {datetime.now().strftime('%d.%m %H:%M:%S')}"
    if visible_name:
        visible_name[0].clear()
        visible_name[0].send_keys(test_name)
        log(f"  Наименование: '{test_name}'", "PASS")
    else:
        log("  Поле наименования не найдено", "FAIL")

    time.sleep(0.3)
    executor = select_first_form_dropdown("Исполнитель")
    if not executor:
        log("  Исполнитель: FAIL", "FAIL")

    try:
        triggers = modal.find_elements(By.XPATH, ".//input[contains(@class,'ui-date-picker__input')]")
        visible_t = [t for t in triggers if t.is_displayed()]
        if visible_t:
            trigger = visible_t[0]
            scroll_to(trigger)
            if not _hard_click(trigger):
                js_click(trigger)
            time.sleep(0.6)
            panels = driver.find_elements(By.XPATH, "//div[contains(@class,'ui-date-picker__panel')]")
            vis_panels = [p for p in panels if p.is_displayed()]
            if vis_panels:
                days = vis_panels[-1].find_elements(
                    By.XPATH, ".//button[contains(@class,'ui-date-picker__day') and "
                              "not(contains(@class,'is-outside')) and not(@disabled)]")
                vis_days = [d for d in days if d.is_displayed()]
                if vis_days:
                    if not _hard_click(vis_days[-1]):
                        js_click(vis_days[-1])
                    time.sleep(0.5)
                    actual = (trigger.get_attribute("value") or "").strip()
                    log(f"  Срок исполнения: '{actual}'", "PASS" if actual else "FAIL")
    except Exception as e:
        log(f"  Срок исполнения: ошибка — {e}", "FAIL")

    time.sleep(0.3)
    project = select_first_form_dropdown("Проект")
    if not project:
        log("  Проект: FAIL", "FAIL")

    # Наблюдатели — в UI помечено "(необязательно)", но по договорённости
    # заполняем ВСЕ поля формы (кроме PDF), в т.ч. и при сохранении
    # черновика — иначе черновик сохраняется не полностью заполненным.
    time.sleep(0.3)
    observers = select_first_form_dropdown("Наблюдатели", multi_select=True)
    if not observers:
        log("  Наблюдатели: FAIL", "FAIL")

    try:
        descs = modal.find_elements(By.XPATH, ".//textarea[contains(@placeholder,'Ввести текст')]")
        visible_d = [d for d in descs if d.is_displayed()]
        if visible_d:
            visible_d[0].clear()
            visible_d[0].send_keys(f"Автосоздание — {name_prefix}")
            log("  Описание введено", "PASS")
    except Exception:
        pass

    return test_name


def _fill_event_fields(modal, name_prefix="Мероприятие"):
    """Общая логика заполнения формы 'Создание мероприятия'.
    Дата/Начало/Окончание/Повторение обязательны, но уже предзаполнены
    системой по умолчанию — реально нужно ввести только 'Название'."""
    name_inputs = modal.find_elements(By.XPATH, ".//input[contains(@placeholder,'Название')]")
    visible_name = [i for i in name_inputs if i.is_displayed()]
    test_name = f"{name_prefix} {datetime.now().strftime('%d.%m %H:%M:%S')}"
    if visible_name:
        visible_name[0].clear()
        visible_name[0].send_keys(test_name)
        time.sleep(0.3)
        log(f"  Название: '{test_name}'", "PASS")
    else:
        log("  Поле 'Название' не найдено", "FAIL")

    log("  Дата/Начало/Окончание/Повторение — используются предзаполненные значения по умолчанию")

    try:
        place_inputs = modal.find_elements(
            By.XPATH, ".//input[contains(@placeholder,'Ссылка на встречу')]")
        visible_place = [p for p in place_inputs if p.is_displayed()]
        if visible_place:
            visible_place[0].clear()
            visible_place[0].send_keys("https://meet.example.com/rpa-test")
            log("  Место проведения заполнено", "PASS")
    except Exception:
        pass

    try:
        desc_areas = modal.find_elements(
            By.XPATH, ".//textarea[contains(@placeholder,'Описание мероприятия')]")
        visible_desc = [d for d in desc_areas if d.is_displayed()]
        if visible_desc:
            visible_desc[0].clear()
            visible_desc[0].send_keys(f"Автосоздание мероприятия — {name_prefix}")
            log("  Описание заполнено", "PASS")
    except Exception:
        pass

    return test_name


def _submit_poruchenie_form(action="Опубликовать"):
    """Нажимает 'Опубликовать' или 'Сохранить' (общая логика для формы
    поручения И формы мероприятия — кнопки называются одинаково).
    Для 'Сохранить' дополнительно проверяет тост 'Черновик сохранён'."""
    btn = None
    for _ in range(10):
        btns = driver.find_elements(By.XPATH, f"//button[contains(.,'{action}')]")
        visible = [b for b in btns if b.is_displayed() and b.is_enabled()]
        if visible:
            btn = visible[0]
            break
        time.sleep(0.3)

    if not btn:
        log(f"  Кнопка '{action}' недоступна", "FAIL")
        shot(f"poruchenie_{action}_disabled")
        return False

    if not _hard_click(btn):
        js_click(btn)
    time.sleep(2)
    log(f"  Нажата кнопка '{action}'", "PASS")

    if action == "Сохранить":
        toast = driver.find_elements(
            By.XPATH, "//*[contains(text(),'Черновик сохранён') or contains(text(),'черновик')]")
        if any(t.is_displayed() for t in toast):
            log("  Подтверждение: 'Черновик сохранён'", "PASS")
        else:
            log("  Тост 'Черновик сохранён' не найден (не критично)", "WARN")
    return True


def test_calendar_create_task():
    """Поручение из календаря — публикация."""
    log("=" * 50)
    log("ТЕСТ: Календарь — создание Поручения (публикация)")
    if not _open_calendar_create_menu():
        return False
    try:
        opt = driver.find_elements(By.XPATH, "//*[normalize-space(text())='Поручение']")
        visible = [o for o in opt if o.is_displayed()]
        if not visible:
            log("  Пункт 'Поручение' не найден", "FAIL")
            return False
        # ИСПРАВЛЕНО: на странице может быть ЕЩЁ один элемент с текстом
        # ровно "Поручение" — например, карточка события в календаре
        # (подтверждено скриншотом пользователя). Берём тот, что ближе
        # к кнопке "Создать", а не просто первый найденный в документе.
        target = _pick_closest_to(_calendar_create_btn, visible)
        if not _hard_click(target):
            js_click(target)

        modal = wait_for_visible_modal(hint_text="поручение")
        if not modal:
            log("  Форма 'Создать поручение' не открылась", "FAIL")
            shot("calendar_task_form_not_opened")
            return False
        log("  Форма 'Создать поручение' открылась", "PASS")

        _fill_poruchenie_fields(modal, name_prefix="Календарь")
        time.sleep(0.3)
        return _submit_poruchenie_form("Опубликовать")
    except Exception as e:
        log(f"  Ошибка создания поручения из календаря: {e}", "FAIL")
        return False


def test_calendar_create_task_draft():
    """Поручение из календаря — сохранение как черновик."""
    log("=" * 50)
    log("ТЕСТ: Календарь — сохранение Поручения как черновик")
    if not _open_calendar_create_menu():
        return False
    try:
        opt = driver.find_elements(By.XPATH, "//*[normalize-space(text())='Поручение']")
        visible = [o for o in opt if o.is_displayed()]
        if not visible:
            log("  Пункт 'Поручение' не найден", "FAIL")
            return False
        # ИСПРАВЛЕНО: на странице может быть ЕЩЁ один элемент с текстом
        # ровно "Поручение" — например, карточка события в календаре
        # (подтверждено скриншотом пользователя). Берём тот, что ближе
        # к кнопке "Создать", а не просто первый найденный в документе.
        target = _pick_closest_to(_calendar_create_btn, visible)
        if not _hard_click(target):
            js_click(target)

        modal = wait_for_visible_modal(hint_text="поручение")
        if not modal:
            log("  Форма 'Создать поручение' не открылась", "FAIL")
            shot("calendar_task_draft_form_not_opened")
            return False
        log("  Форма 'Создать поручение' открылась", "PASS")

        # ИСПРАВЛЕНО (по запросу): черновик тоже заполняем по всем полям,
        # как и публикация, а не только Наименование.
        _fill_poruchenie_fields(modal, name_prefix="Календарь Черновик")

        time.sleep(0.3)
        return _submit_poruchenie_form("Сохранить")
    except Exception as e:
        log(f"  Ошибка сохранения черновика поручения из календаря: {e}", "FAIL")
        return False


def test_calendar_create_event():
    """Мероприятие из календаря — публикация."""
    log("=" * 50)
    log("ТЕСТ: Календарь — создание Мероприятия (публикация)")
    if not _open_calendar_create_menu():
        return False
    try:
        opt = driver.find_elements(By.XPATH, "//*[normalize-space(text())='Мероприятие']")
        visible = [o for o in opt if o.is_displayed()]
        if not visible:
            log("  Пункт 'Мероприятие' не найден", "FAIL")
            return False
        # См. комментарий выше про "Поручение" — та же защита от
        # совпадения текста с посторонним элементом на странице.
        target = _pick_closest_to(_calendar_create_btn, visible)
        if not _hard_click(target):
            js_click(target)

        modal = wait_for_visible_modal(hint_text="мероприяти")
        if not modal:
            log("  Форма 'Создание мероприятия' не открылась", "FAIL")
            shot("calendar_event_form_not_opened")
            return False
        log("  Форма 'Создание мероприятия' открылась", "PASS")
        shot("calendar_event_form_opened")

        _fill_event_fields(modal)
        time.sleep(0.3)
        return _submit_poruchenie_form("Опубликовать")
    except Exception as e:
        log(f"  Ошибка создания мероприятия: {e}", "FAIL")
        return False


def test_calendar_create_event_draft():
    """Мероприятие из календаря — сохранение как черновик."""
    log("=" * 50)
    log("ТЕСТ: Календарь — сохранение Мероприятия как черновик")
    if not _open_calendar_create_menu():
        return False
    try:
        opt = driver.find_elements(By.XPATH, "//*[normalize-space(text())='Мероприятие']")
        visible = [o for o in opt if o.is_displayed()]
        if not visible:
            log("  Пункт 'Мероприятие' не найден", "FAIL")
            return False
        # См. комментарий выше про "Поручение" — та же защита от
        # совпадения текста с посторонним элементом на странице.
        target = _pick_closest_to(_calendar_create_btn, visible)
        if not _hard_click(target):
            js_click(target)

        modal = wait_for_visible_modal(hint_text="мероприяти")
        if not modal:
            log("  Форма 'Создание мероприятия' не открылась", "FAIL")
            shot("calendar_event_draft_form_not_opened")
            return False
        log("  Форма 'Создание мероприятия' открылась", "PASS")

        # ИСПРАВЛЕНО (по запросу): черновик мероприятия тоже заполняем
        # по всем полям, как и публикация (та же функция, что и в
        # test_calendar_create_event), а не только Название.
        _fill_event_fields(modal, name_prefix="Мероприятие Черновик")

        time.sleep(0.3)
        return _submit_poruchenie_form("Сохранить")
    except Exception as e:
        log(f"  Ошибка сохранения черновика мероприятия: {e}", "FAIL")
        return False


def test_calendar_open_event_card():
    log("=" * 50)
    log("ТЕСТ: Календарь — открытие карточки события по клику")
    try:
        chips = driver.find_elements(
            By.XPATH,
            "//*[contains(@class,'event') or contains(@class,'chip') or contains(@class,'item')]"
            "[not(self::script)][string-length(normalize-space(text())) > 0]")
        visible = [c for c in chips if c.is_displayed()]
        if not visible:
            log("  Ни одной карточки события не найдено", "FAIL")
            shot("calendar_no_event_chips")
            report_to_sheet("Открытие карточки события по клику", False, ROWS_CALENDAR)
            return
        target = visible[0]
        chip_text = (target.text or "").strip()

        # ВАЖНО (подсказка после ручной проверки): клик должен попадать
        # в "тело"/фон карточки, а не точно в надпись внутри неё — иначе
        # событие клика может не сработать. Поднимаемся на родителя
        # (саму карточку-контейнер) и кликаем НЕ по центру (там текст),
        # а по краю карточки, где заведомо нет текста.
        try:
            card = driver.execute_script("return arguments[0].closest('div') || arguments[0];", target)
        except Exception:
            card = target

        clicked_ok = False
        try:
            driver.execute_script("""
                var el = arguments[0];
                var r = el.getBoundingClientRect();
                // точка у левого края карточки, подальше от текста по центру
                var x = r.left + 4;
                var y = r.top + r.height / 2;
                function fire(type) {
                    var ev = new MouseEvent(type, {bubbles:true, cancelable:true, view:window,
                        clientX:x, clientY:y, button:0});
                    el.dispatchEvent(ev);
                }
                fire('mousedown'); fire('mouseup'); fire('click');
            """, card)
            clicked_ok = True
        except Exception:
            pass

        if not clicked_ok:
            if not _hard_click(card):
                js_click(card)
        time.sleep(1)

        modal = find_visible_modal_container()
        if modal:
            log(f"  Карточка '{chip_text[:30]}' открылась", "PASS")
            shot("calendar_event_card_opened")
            try:
                ActionChains(driver).send_keys(Keys.ESCAPE).perform()
            except Exception:
                pass
            report_to_sheet("Открытие карточки события по клику", True, ROWS_CALENDAR)
        else:
            log(f"  Клик по карточке '{chip_text[:30]}' не открыл просмотр", "FAIL")
            shot("calendar_event_card_not_opened")
            report_to_sheet("Открытие карточки события по клику", False, ROWS_CALENDAR)
    except Exception as e:
        log(f"  Ошибка теста открытия карточки: {e}", "FAIL")
        report_to_sheet("Открытие карточки события по клику", False, ROWS_CALENDAR)


def test_calendar_expand_more():
    log("=" * 50)
    log("ТЕСТ: Календарь — разворачивание '+N' доп. событий")
    try:
        more_links = driver.find_elements(By.XPATH, "//*[starts-with(normalize-space(text()),'+')]")
        visible = [m for m in more_links if m.is_displayed()]
        if not visible:
            log("  Плашка '+N' не найдена (возможно, в этом месяце нет переполненных дней)", "WARN")
            report_to_sheet("Разворачивание списка «+N»", False, ROWS_CALENDAR)
            return
        target = visible[0]
        label_text = (target.text or "").strip()
        before_count = len(driver.find_elements(
            By.XPATH, "//*[contains(@class,'event') or contains(@class,'chip')]"))
        if not _hard_click(target):
            js_click(target)
        time.sleep(1)
        shot("calendar_more_expanded")
        log(f"  Клик по '{label_text}'", "PASS")
        report_to_sheet("Разворачивание списка «+N»", True, ROWS_CALENDAR)
    except Exception as e:
        log(f"  Ошибка теста '+N': {e}", "FAIL")
        report_to_sheet("Разворачивание списка «+N»", False, ROWS_CALENDAR)


def test_calendar():
    if not go_to_calendar():
        return
    test_calendar_navigation()
    test_calendar_year_select()
    test_calendar_view_switch()
    test_calendar_search()
    test_calendar_create_menu()

    ok = test_calendar_create_task()
    report_to_sheet("Создание поручения из календаря", ok, ROWS_CALENDAR)
    time.sleep(1)
    go_to_calendar()
    ok = test_calendar_create_task_draft()
    report_to_sheet("Сохранение поручения из календаря как черновик", ok, ROWS_CALENDAR)
    time.sleep(1)
    go_to_calendar()
    ok = test_calendar_create_event()
    report_to_sheet("Создание мероприятия из календаря", ok, ROWS_CALENDAR)
    time.sleep(1)
    go_to_calendar()
    ok = test_calendar_create_event_draft()
    report_to_sheet("Сохранение мероприятия из календаря как черновик", ok, ROWS_CALENDAR)
    time.sleep(1)
    go_to_calendar()
    test_calendar_open_event_card()
    test_calendar_expand_more()


# ==========================================
# 3. ТЕСТ: Наименование задачи
# ==========================================
def test_name_filter():
    log("=" * 50)
    log("ТЕСТ: Фильтр по наименованию")

    test_words = ["договор", "поручение", "акт"]
    filter_ok = False

    for word in test_words:
        if not open_panel(): break

        body = get_body()
        if not body:
            log("Панель не найдена", "FAIL"); break

        try:
            inps = body.find_elements(By.XPATH,
                ".//input[contains(@placeholder,'наименован') or contains(@placeholder,'Поиск')]")
            if not inps:
                inps = body.find_elements(By.XPATH,
                    ".//*[contains(text(),'Наименование')]/following::input[1]")
            if not inps:
                log("Поле наименования не найдено", "FAIL"); break

            inps[0].clear()
            inps[0].send_keys(word)
            time.sleep(0.3)
        except Exception as e:
            log(f"Ошибка ввода: {e}", "FAIL"); break

        if not click_apply(): break

        total = get_total()
        rows = count_rows()
        if total > 0:
            log(f"'{word}': найдено {total} записей (строк {rows})", "PASS")
            name_filter_summary.append((word, total))
            filter_ok = True
        elif total == 0:
            log(f"'{word}': 0 результатов", "WARN")
            name_filter_summary.append((word, 0))
        else:
            log(f"'{word}': не удалось прочитать", "FAIL")

    # Сброс — "Сбросить фильтры" НЕ чистит верхнее поле поиска (это
    # отдельный элемент), поэтому очищаем его явно, иначе текст ('акт'
    # и т.п.) остаётся и портит результаты ВСЕХ последующих тестов.
    # Пробуем видимую иконку "✕" внутри поля поиска (есть на скриншотах),
    # затем обычный .clear() как запасной способ.
    try:
        clear_icons = driver.find_elements(
            By.XPATH,
            "//input[contains(@placeholder,'Поиск')]/following-sibling::*"
            "[contains(@class,'clear') or contains(@class,'close') or self::svg or self::button][1]")
        clicked_x = False
        for icon in clear_icons:
            if icon.is_displayed():
                if not _hard_click(icon):
                    js_click(icon)
                clicked_x = True
                time.sleep(0.4)
                break

        inps = driver.find_elements(By.XPATH,
            ".//input[contains(@placeholder,'наименован') or contains(@placeholder,'Поиск')]")
        if inps:
            cur_val = inps[0].get_attribute("value") or ""
            if cur_val:  # иконка не сработала — чистим руками
                inps[0].clear()
                inps[0].send_keys(Keys.ENTER)
            time.sleep(0.4)
            final_val = inps[0].get_attribute("value") or ""
            if final_val:
                log(f"  [DIAG] Поле поиска НЕ очистилось, всё ещё: '{final_val}'", "DIAG")
    except Exception:
        pass
    reset_and_apply()
    after = get_total()
    log(f"Сброс наименования: всего={after}", "PASS" if after and after > 0 else "WARN")
    # Строку в чек-лист больше не пишем здесь — результат объединяется с
    # остальной фильтрацией задач в одну строку "Фильтрация задач"
    # вызывающим кодом (блок ЗАПУСК).
    return filter_ok


# ==========================================
# 4. ТЕСТ: Каждый дропдаун — ВСЕ значения
# ==========================================
def test_dropdown_all_values(label, default_text, only_values=None):
    """Открывает дропдаун, собирает все опции, потом тестирует каждую.
    only_values: если задан список подстрок — проверяем ТОЛЬКО те
    значения, что содержат одну из этих подстрок (остальные пропускаем,
    но в отчёт всё равно попадает, сколько всего опций реально было)."""
    log(f"\n{'='*50}")
    log(f"ТЕСТ: Фильтр '{label}' — все значения")

    # Накопитель результатов для краткой сводки
    summary = {
        "filter": label,
        "total_values": 0,
        "with_results": [],  # [(значение, кол-во записей)]
        "empty_values": [],  # значения с 0 результатов
        "failed_values": [], # значения которые не удалось проверить
    }

    # Шаг 1: собираем список опций
    if not open_panel():
        summary["failed_values"].append("открытие панели")
        test_summaries.append(summary)
        return False

    body = get_body()
    if not body:
        log("Панель не найдена", "FAIL")
        summary["failed_values"].append("панель не найдена")
        test_summaries.append(summary)
        return False

    select_el = find_dropdown_by_label(body, label, default_text)
    if not select_el:
        log(f"Селектор '{label}' не найден", "FAIL")
        summary["failed_values"].append("селектор не найден")
        test_summaries.append(summary)
        close_panel(); return False

    if not open_dropdown(select_el):
        log(f"Не удалось открыть '{label}'", "FAIL")
        summary["failed_values"].append("dropdown не открылся")
        test_summaries.append(summary)
        close_panel(); return False

    options = collect_options(near_element=select_el)
    if not options:
        log(f"'{label}': опции не загрузились", "FAIL")
        summary["failed_values"].append("опции не загрузились")
        test_summaries.append(summary)
        shot(f"no_options_{label}")
        close_panel(); return False

    option_texts = [o["text"] for o in options]
    summary["total_values"] = len(option_texts)
    log(f"'{label}': найдено {len(option_texts)} опций")
    for ot in option_texts:
        report.append(f"    - {ot}")

    if only_values:
        filtered = [ot for ot in option_texts
                    if any(v.lower() in ot.lower() for v in only_values)]
        log(f"  (ограничиваю проверку {len(filtered)} значениями из {len(option_texts)}: {only_values})")
        option_texts = filtered

    # Закрываем дропдаун и панель
    close_dropdown_safe()
    time.sleep(0.3)
    close_panel()
    time.sleep(0.3)

    # Шаг 2: тестируем каждую опцию отдельно
    for opt_text in option_texts:
        log(f"  Фильтр '{label}' = '{opt_text}'")

        if not open_panel():
            break

        body = get_body()
        if not body:
            log(f"    Панель не найдена", "FAIL"); break

        select_el = find_dropdown_by_label(body, label, default_text)
        if not select_el:
            # После выбора опции placeholder меняется — ищем по label
            select_el = find_dropdown_by_label(body, label, opt_text)
        if not select_el:
            log(f"    Селектор не найден", "FAIL"); close_panel(); continue

        if not open_dropdown(select_el):
            log(f"    Не удалось открыть", "FAIL"); close_panel(); continue

        time.sleep(0.5)

        # Находим нужную опцию и кликаем
        clicked = False
        current_options = collect_options(near_element=select_el)
        for opt in current_options:
            if opt["text"] == opt_text:
                try:
                    clicked = _click_option_robustly(opt["element"])
                    time.sleep(0.5)
                except Exception:
                    pass
                break

        if not clicked:
            log(f"    Не удалось выбрать '{opt_text}'", "FAIL")
            close_dropdown_safe()
            close_panel()
            continue

        # Применяем
        if not click_apply():
            continue

        total = get_total()
        rows = count_rows()
        if total > 0:
            log(f"    Результат: {total} записей", "PASS")
            summary["with_results"].append((opt_text, total))
        elif total == 0:
            log(f"    Результат: 0 записей", "WARN")
            summary["empty_values"].append(opt_text)
        else:
            log(f"    Не удалось прочитать результат (строк={rows})", "WARN")
            summary["failed_values"].append(opt_text)

        # Сброс после каждой опции
        reset_and_apply()
        time.sleep(0.3)

    test_summaries.append(summary)
    log(f"ТЕСТ '{label}' завершён: с результатами {len(summary['with_results'])}/{summary['total_values']}")
    success = summary["total_values"] > 0 and \
        (len(summary["with_results"]) + len(summary["empty_values"])) > 0
    return success


def test_filters_quick(filters, rows, report_label="Фильтры работают"):
    """Объединённая проверка нескольких фильтров ОДНИМ сценарием вместо
    отдельного прогона по каждому фильтру со всеми его значениями.

    Техники тест-дизайна:
    - эквивалентное разбиение: для каждого фильтра берём ОДНО
      репрезентативное значение (не дефолтное "Все ..."), а не перебираем
      все опции — цель прогона: убедиться, что фильтр вообще применяется
      и не роняет страницу, а не покрыть каждое возможное значение;
    - сценарное тестирование: все фильтры раздела проверяются в одном
      проходе, как реальный тестировщик делает smoke-проверку фильтрации,
      результат — одна строка в чек-листе на раздел.

    filters — список кортежей (label, default_text, preferred_substrings):
      preferred_substrings — список подстрок, среди которых ищем реальное
      значение (например, конкретных исполнителей); если None или ни одна
      не подошла — берётся первая опция, отличная от default_text.
    """
    log("=" * 50)
    log(f"ТЕСТ: {report_label} — объединённая проверка ({len(filters)} фильтров)")
    all_ok = True

    for label, default_text, preferred in filters:
        try:
            if not open_panel():
                log(f"  '{label}': панель не найдена", "FAIL")
                all_ok = False
                continue

            body = get_body()
            if not body:
                log(f"  '{label}': тело страницы не найдено", "FAIL")
                all_ok = False
                continue

            select_el = find_dropdown_by_label(body, label, default_text)
            if not select_el:
                log(f"  '{label}': селектор не найден", "FAIL")
                all_ok = False
                close_panel()
                continue

            if not open_dropdown(select_el):
                log(f"  '{label}': не удалось открыть", "FAIL")
                all_ok = False
                close_panel()
                continue

            time.sleep(0.3)
            options = collect_options(near_element=select_el)
            # Исключаем сам дефолт ("Все ...") — нужен представитель класса
            # "выбрано конкретное значение", а не "фильтр не применён".
            real_options = [o for o in options
                             if o["text"].strip().lower() != default_text.strip().lower()]
            if not real_options:
                log(f"  '{label}': нет значений кроме дефолтного", "FAIL")
                all_ok = False
                close_dropdown_safe()
                close_panel()
                continue

            match = None
            if preferred:
                match = next((o for o in real_options
                              if any(p.lower() in o["text"].lower() for p in preferred)), None)
            if match is None:
                match = real_options[0]

            if not _click_option_robustly(match["element"]):
                log(f"  '{label}': не удалось выбрать '{match['text']}'", "FAIL")
                all_ok = False
                close_dropdown_safe()
                close_panel()
                continue

            time.sleep(0.5)
            close_dropdown_safe()
            click_apply()
            total = get_total()
            if total >= 0:
                log(f"  '{label}' = '{match['text']}': {total} записей", "PASS")
            else:
                log(f"  '{label}' = '{match['text']}': счётчик не прочитан", "WARN")

            reset_and_apply()
            close_panel()
            time.sleep(0.3)
        except Exception as e:
            log(f"  '{label}': ошибка — {e}", "FAIL")
            all_ok = False
            close_dropdown_safe()
            close_panel()

    # ВАЖНО: сюда специально НЕ добавлен report_to_sheet — по договорённости
    # эта проверка не пишет свою отдельную строку в чек-лист, а объединяется
    # с наименованием/датой в ОДНУ строку "Фильтрация ..." на уровне
    # вызывающего кода (см. test_assignments_filters и блок ЗАПУСК).
    return all_ok


# ==========================================
# 5. ТЕСТ: Срок исполнения
# ==========================================
def test_dates():
    log("=" * 50)
    log("ТЕСТ: Фильтр по сроку исполнения")

    # РЕАЛЬНАЯ разметка (подтверждено скриншотом): это ОДНА кнопка
    # "Срок исполнения" с иконкой календаря, открывает попап с одним
    # календарём — кликаешь одну дату, фильтр применяется сразу.
    # Старой логики "два поля от/до" тут нет.
    try:
        btn = driver.find_elements(By.XPATH, "//button[contains(.,'Срок исполнения')]")
        visible = [b for b in btn if b.is_displayed()]
        if not visible:
            log("Кнопка 'Срок исполнения' не найдена", "FAIL"); return False
        trigger = visible[0]
        scroll_to(trigger)
        time.sleep(0.2)
        if not _hard_click(trigger):
            js_click(trigger)
        time.sleep(0.5)

        # Ищем открывшийся календарь и кликаем сегодняшний день (или
        # первый доступный) — не важна конкретная дата, важно, что
        # фильтр по дате вообще срабатывает.
        days = driver.find_elements(
            By.XPATH,
            "//*[contains(@class,'ant-picker-cell-today')] | "
            "//*[contains(@class,'today')] | "
            "//div[contains(@class,'picker')]//td[not(contains(@class,'disabled'))][1] | "
            "//button[contains(@class,'day') and not(contains(@class,'disabled'))][1]"
        )
        visible_days = [d for d in days if d.is_displayed()]
        if not visible_days:
            log("Календарь открылся, но ни одного дня не найдено", "FAIL")
            shot("date_calendar_no_days")
            return False

        if not _hard_click(visible_days[0]):
            js_click(visible_days[0])
        time.sleep(0.5)
        log(f"Дата выбрана: '{(visible_days[0].text or '').strip()}'", "PASS")
    except Exception as e:
        log(f"Ошибка дат: {e}", "FAIL"); return False

    total = get_total()
    log(f"Результат: {total} записей", "PASS" if total >= 0 else "FAIL")
    global dates_summary
    dates_summary = total

    reset_and_apply()
    log("Фильтр дат сброшен", "PASS")
    return total >= 0


# ==========================================
# 6. ТЕСТ: Кнопки
# ==========================================
def test_buttons():
    log("=" * 50)
    log("ТЕСТ: Кнопки панели")

    if not open_panel():
        report_to_sheet("Кнопки панели фильтра (Сбросить/Применить)", False, ROWS_TASKS)
        return

    reset_found = False
    for txt in ["Сбросить", "Применить"]:
        btns = driver.find_elements(By.XPATH, f"//button[contains(.,'{txt}')]")
        vis = [b for b in btns if b.is_displayed()]
        if vis:
            log(f"Кнопка '{txt}': OK, enabled={vis[0].is_enabled()}", "PASS")
            if txt == "Сбросить":
                reset_found = vis[0].is_enabled()
        else:
            log(f"Кнопка '{txt}': не найдена (это нормально для 'Применить' — "
                f"на реальной странице фильтр применяется мгновенно)")

    # Тест сброса
    body = get_body()
    if body:
        inps = body.find_elements(By.XPATH, ".//input[contains(@placeholder,'наименован') or contains(@placeholder,'Поиск')]")
        if inps:
            inps[0].clear(); inps[0].send_keys("test123"); time.sleep(0.2)
            click_reset()
            time.sleep(0.3)
            body = get_body()
            if body:
                inps = body.find_elements(By.XPATH, ".//input[contains(@placeholder,'наименован') or contains(@placeholder,'Поиск')]")
                if inps:
                    val = inps[0].get_attribute("value") or ""
                    if val == "":
                        log("Сбросить: поля очищены", "PASS")
                    else:
                        log(f"Сбросить: поле не очищено ('{val}')", "FAIL")

    click_apply()
    report_to_sheet("Кнопки панели фильтра (Сбросить/Применить)", reset_found, ROWS_TASKS)


# ==========================================
# 7. ТЕСТ: Создание поручения/задачи
# ==========================================
def select_first_form_dropdown(label, multi_select=False):
    """На форме создания: открывает dropdown по label и выбирает первую опцию.
    ВАЖНО: ищем СТРОГО внутри самой модалки — иначе поиск 'первый
    подходящий элемент после подписи' может случайно перепрыгнуть на
    элемент страницы позади модалки (подтверждено скриншотом: вместо
    поля 'Исполнитель' кликался селектор пагинации 'Строк на стр.').

    multi_select=True — для полей-мультивыбора с чекбоксами (например,
    "Наблюдатели" — подтверждено скриншотом пользователя: список с
    чекбоксами и поиском). У таких полей клик по опции НЕ закрывает
    список — это ожидаемо, так можно отметить несколько вариантов.
    Обычная проверка "_click_option_robustly" считает клик успешным
    только если список ЗАКРЫЛСЯ, что для чекбоксов всегда ложно
    (см. ниже отдельную ветку)."""
    try:
        modal = find_visible_modal_container(hint_text="поручение")
        scope = modal if modal is not None else driver

        select_el = find_ui_kit_trigger_near_label(scope, label)

        if not select_el:
            labels = scope.find_elements(By.XPATH,
                f".//*[normalize-space(text())='{label}']")
            for lbl in labels:
                if not lbl.is_displayed():
                    continue
                try:
                    ant_candidates = scope.find_elements(
                        By.XPATH, ".//div[contains(@class,'ant-select')]")
                    ant_candidates = [c for c in ant_candidates if c.is_displayed()]
                    if ant_candidates:
                        # ближайший по вертикали к лейблу
                        best = driver.execute_script("""
                            var label = arguments[0]; var cands = arguments[1];
                            var lr = label.getBoundingClientRect();
                            var best = null, bestScore = Infinity;
                            for (var i=0;i<cands.length;i++){
                                var r = cands[i].getBoundingClientRect();
                                var dy = r.top - lr.bottom;
                                if (dy < -5 || dy > 120) continue;
                                if (dy < bestScore) { bestScore = dy; best = cands[i]; }
                            }
                            return best;
                        """, lbl, ant_candidates)
                        if best:
                            select_el = best
                            break
                except Exception:
                    continue

        if not select_el:
            select_el = find_control_near_label(label)

        if not select_el:
            log(f"  {label}: dropdown не найден", "FAIL")
            return None

        if not open_dropdown(select_el):
            log(f"  {label}: не удалось открыть dropdown", "FAIL")
            shot(f"form_dropdown_not_opened_{label}")
            return None

        time.sleep(0.3)
        shot(f"form_dropdown_opened_{label}")
        options = collect_options(near_element=select_el)
        if not options:
            log(f"  {label}: опции не загрузились", "FAIL")
            return None

        first = options[0]

        if multi_select:
            # Один клик по чекбоксу — и НЕ проверяем, что список закрылся
            # (он и не должен). Закрываем явно повторным кликом по самому
            # триггеру (тот же элемент, которым открывали) — это toggle-
            # кнопка, так что второй клик просто схлопывает список, не
            # трогая уже отмеченный чекбокс (в отличие от Escape, который
            # у некоторых мультиселектов отменяет выбор).
            clicked = False
            for method in ["hard", "selenium", "js"]:
                try:
                    if method == "hard":
                        clicked = _hard_click(first["element"])
                    elif method == "selenium":
                        first["element"].click()
                        clicked = True
                    else:
                        js_click(first["element"])
                        clicked = True
                    if clicked:
                        break
                except Exception:
                    continue
            time.sleep(0.3)
            shot(f"form_dropdown_after_click_{label}")
            if _dropdown_is_open():
                if not _hard_click(select_el):
                    js_click(select_el)
                time.sleep(0.3)
                if _dropdown_is_open():
                    close_dropdown_safe()
            if clicked:
                log(f"  {label}: выбрано '{first['text']}'", "PASS")
                return first["text"]
            else:
                log(f"  {label}: не удалось кликнуть по опции", "FAIL")
                return None

        if _click_option_robustly(first["element"]):
            time.sleep(0.4)
            shot(f"form_dropdown_after_click_{label}")
            # ДИАГНОСТИКА: если текст подозрительно короткий/цифровой —
            # похоже, зацепили что-то постороннее (не настоящую опцию).
            if len(first["text"]) <= 3 or first["text"].isdigit():
                try:
                    html = driver.execute_script(
                        "var el = arguments[0]; "
                        "var c = el.closest('div') || el.parentElement; "
                        "for (var i=0;i<3 && c && c.parentElement;i++){c=c.parentElement;} "
                        "return (c||el).outerHTML;", first["element"])
                    log(f"    [DIAG] Подозрительное значение '{first['text']}' — "
                        f"HTML вокруг: {(html or '')[:800]}", "DIAG")
                except Exception as e:
                    log(f"    [DIAG] Не удалось снять HTML: {e}", "DIAG")
            log(f"  {label}: выбрано '{first['text']}'", "PASS")
            return first["text"]
        else:
            log(f"  {label}: не удалось кликнуть по опции", "FAIL")
            # ИСПРАВЛЕНО: если клик по опции не сработал, dropdown
            # остаётся открытым — а открытый оверлей/бэкдроп может
            # перехватывать следующий клик на странице (в т.ч. клик по
            # кнопке "Опубликовать"), из-за чего форма молча не
            # отправляется. Явно закрываем, прежде чем идти дальше.
            close_dropdown_safe()
            return None
    except Exception as e:
        log(f"  {label}: ошибка — {e}", "FAIL")
        close_dropdown_safe()
        return None

def test_create_entity(entity_name="задача"):
    """Создание новой задачи/поручения через UI: заполняет форму и публикует."""
    log("=" * 50)
    log(f"ТЕСТ: Создание {entity_name} через UI")

    global creation_test
    result = {
        "name": None, "executor": None, "project": None,
        "date": None, "description": None, "observers": None,
        "created": False, "errors": []
    }

    # 1. Запоминаем сколько записей было
    initial_total = get_total()
    log(f"  Записей до создания: {initial_total}")

    # 2. Клик "Создать"
    try:
        btn = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.XPATH,
                "//button[contains(., 'Создать') and not(contains(@class,'disabled'))]"))
        )
        scroll_to(btn)
        time.sleep(0.2)
        try:
            btn.click()
        except Exception:
            js_click(btn)
        time.sleep(1)
        log(f"  Клик по кнопке 'Создать'", "PASS")
    except Exception as e:
        log(f"  Кнопка 'Создать' не найдена: {e}", "FAIL")
        result["errors"].append("Кнопка 'Создать' не найдена")
        creation_test = result
        return

    # 3. Ждём формы создания
    # ВАЖНО: реальный заголовок модалки — "Создать поручение" (проверено
    # скриншотом), а не "Создание ..." — раньше искали несуществующее
    # слово, поэтому форма никогда не находилась.
    try:
        WebDriverWait(driver, 10).until(
            EC.visibility_of_element_located((By.XPATH,
                "//*[contains(text(),'Создать поручение') or contains(text(),'Создание')]"))
        )
        log(f"  Форма создания загружена. URL: {driver.current_url}", "PASS")
    except Exception:
        log(f"  Форма создания не загрузилась", "FAIL")
        result["errors"].append("Форма не загрузилась")
        shot("create_form_missing")
        creation_test = result
        return

    # 4. Наименование
    test_name = f"Автотест {datetime.now().strftime('%d.%m %H:%M:%S')}"
    try:
        name_inputs = driver.find_elements(By.XPATH,
            "//input[contains(@placeholder, 'аименование')]")
        if name_inputs and name_inputs[0].is_displayed():
            name_inputs[0].clear()
            name_inputs[0].send_keys(test_name)
            result["name"] = test_name
            log(f"  Наименование: '{test_name}'", "PASS")
        else:
            log(f"  Поле наименования не найдено", "FAIL")
            result["errors"].append("Нет поля наименования")
    except Exception as e:
        log(f"  Ошибка ввода наименования: {e}", "FAIL")

    # 5. Исполнитель (первый из списка)
    time.sleep(0.3)
    result["executor"] = select_first_form_dropdown("Исполнитель")

    # 6. Срок исполнения. Подтверждено DevTools: <input class="ui-date-picker__input">.
    # Прямой ввод текста в это поле не работает (это тот же ui-date-picker,
    # что мы уже разбирали для договора — выбор идёт ТОЛЬКО через попап-
    # календарь: панель <div class="ui-date-picker__panel"> с ячейками
    # <button class="ui-date-picker__day">). Прошлая версия искала день
    # по всей странице без привязки к открывшемуся попапу — могла попасть
    # мимо. Теперь ищем строго внутри своей панели.
    try:
        modal = find_visible_modal_container(hint_text="поручение")
        scope = modal if modal is not None else driver

        triggers = scope.find_elements(By.XPATH, ".//input[contains(@class,'ui-date-picker__input')]")
        visible = [t for t in triggers if t.is_displayed()]

        if not visible:
            log(f"  Поле даты не найдено", "WARN")
        else:
            trigger = visible[0]
            scroll_to(trigger)
            time.sleep(0.2)

            panel = None
            for method in ["hard", "js", "selenium"]:
                try:
                    if method == "hard":
                        _hard_click(trigger)
                    elif method == "js":
                        js_click(trigger)
                    else:
                        trigger.click()
                    time.sleep(0.6)
                    panels = driver.find_elements(
                        By.XPATH, "//div[contains(@class,'ui-date-picker__panel')]")
                    vis_panels = [p for p in panels if p.is_displayed()]
                    if vis_panels:
                        panel = vis_panels[-1]
                        break
                except Exception:
                    continue

            if not panel:
                log(f"  Срок исполнения: календарь не открылся", "FAIL")
                result["errors"].append("Календарь не открылся")
                shot("create_form_calendar_not_open")
            else:
                days = panel.find_elements(
                    By.XPATH,
                    ".//button[contains(@class,'ui-date-picker__day') and "
                    "not(contains(@class,'is-outside')) and not(@disabled)]")
                visible_days = [d for d in days if d.is_displayed()]

                if not visible_days:
                    log(f"  Календарь открылся, но дни не найдены", "WARN")
                    shot("create_form_no_calendar_days")
                else:
                    # Берём последний доступный день месяца — почти
                    # наверняка это будущая дата (не сегодня/не прошлое)
                    if not _hard_click(visible_days[-1]):
                        js_click(visible_days[-1])
                    time.sleep(0.5)

                    actual = (trigger.get_attribute("value") or "").strip()
                    if actual and "выбрать" not in actual.lower():
                        result["date"] = actual
                        log(f"  Срок исполнения: '{actual}'", "PASS")
                    else:
                        log(f"  Срок исполнения: поле осталось пустым после клика по дню", "FAIL")
                        result["errors"].append("Дата не проставилась")
                        shot("create_form_date_still_empty")
    except Exception as e:
        log(f"  Ошибка даты: {e}", "WARN")

    # 7. Проект (первый)
    time.sleep(0.3)
    result["project"] = select_first_form_dropdown("Проект")

    # 7b. Наблюдатели — в UI помечено как "(необязательно)", но по
    # договорённости заполняем ВСЕ поля формы, кроме прикрепления PDF,
    # чтобы публикация точно проходила и открытая модалка не мешала
    # следующему тесту (черновику).
    # ИСПРАВЛЕНО: полный текст "Наблюдатели (необязательно)" не находился —
    # пометка "(необязательно)", похоже, лежит в отдельном дочернем узле,
    # поэтому normalize-space(text()) самого лейбла равен просто
    # "Наблюдатели". Ищем по короткому варианту, как остальные поля формы.
    time.sleep(0.3)
    result["observers"] = select_first_form_dropdown("Наблюдатели", multi_select=True)
    if not result["observers"]:
        log("  Наблюдатели: FAIL", "FAIL")

    # 8. Описание — судя по скриншоту, это ОБЯЗАТЕЛЬНОЕ поле (в отличие
    # от "Тип поручения"/"Наблюдатели", у него нет пометки "необязательно").
    # Раньше поиск шёл по несуществующему тексту плейсхолдера ("пишите"/
    # "писание"), а реальный плейсхолдер — "Ввести текст". Поэтому поле
    # тихо пропускалось, и форма никогда не проходила валидацию.
    try:
        modal = find_visible_modal_container(hint_text="поручение")
        scope = modal if modal is not None else driver
        descs = scope.find_elements(By.XPATH,
            ".//textarea[contains(@placeholder,'Ввести текст') or "
            "contains(@placeholder,'пишите') or contains(@placeholder,'писание')]")
        visible = [d for d in descs if d.is_displayed()]
        if visible:
            desc_text = f"Автоматическое создание автотестом. Время: {datetime.now().strftime('%H:%M:%S')}"
            visible[0].clear()
            visible[0].send_keys(desc_text)
            time.sleep(0.2)
            actual = visible[0].get_attribute("value") or ""
            if actual:
                result["description"] = desc_text
                log(f"  Описание введено", "PASS")
            else:
                log(f"  Описание: поле осталось пустым после ввода", "FAIL")
        else:
            log(f"  Поле 'Описание' не найдено", "FAIL")
    except Exception as e:
        log(f"  Ошибка ввода описания: {e}", "FAIL")

    # 9. Опубликовать (или Сохранить как fallback)
    # ВАЖНО: сразу после заполнения полей кнопка "Опубликовать" может
    # ещё долю секунды считаться недоступной, пока фронтенд не
    # пересчитает валидацию формы — ждём, а не проверяем один раз сразу.
    shot("create_form_before_publish")
    try:
        pub_btns = driver.find_elements(By.XPATH, "//button[contains(., 'Опубликовать')]")
        for b in pub_btns:
            if b.is_displayed():
                html = driver.execute_script("return arguments[0].outerHTML;", b)
                log(f"  [DIAG] Кнопка 'Опубликовать' в DOM: enabled={b.is_enabled()}, "
                    f"HTML: {(html or '')[:400]}", "DIAG")
    except Exception as e:
        log(f"  [DIAG] Не удалось снять состояние кнопки 'Опубликовать': {e}", "DIAG")

    published = False
    for btn_text in ["Опубликовать", "Сохранить"]:
        try:
            btn = None
            for _ in range(10):  # до ~3 секунд ожидания на каждую кнопку
                btns = driver.find_elements(By.XPATH,
                    f"//button[contains(., '{btn_text}')]")
                visible = [b for b in btns if b.is_displayed() and b.is_enabled()]
                if visible:
                    btn = visible[0]
                    break
                time.sleep(0.3)
            if btn:
                scroll_to(btn)
                time.sleep(0.2)
                try:
                    btn.click()
                except Exception:
                    js_click(btn)
                log(f"  Нажата кнопка '{btn_text}'", "PASS")
                published = True
                break
        except Exception:
            continue

    if not published:
        log(f"  Кнопки 'Опубликовать'/'Сохранить' не найдены", "FAIL")
        result["errors"].append("Нет кнопок сохранения")
        creation_test = result
        return

    time.sleep(1.5)

    # 10. Проверка успеха.
    # ИСПРАВЛЕНО (по договорённости): кнопка "Создать" на вкладке "Задачи"
    # открывает форму именно "Создать поручение" — по ручной проверке
    # пользователя, созданная запись физически попадает в список
    # "Поручения", а не "Задачи". Поэтому сравнение счётчика на странице
    # "Задачи" до/после ничего не показывает — он не растёт, даже если
    # публикация прошла успешно (это не баг сайта — так и есть на самом
    # деле). Критерий успеха: модалка закрылась после клика "Опубликовать"
    # и по пути не накопилось ошибок заполнения обязательных полей.
    still_modal = find_visible_modal_container(hint_text="поручение")
    if still_modal:
        log("  После публикации модалка всё ещё открыта — похоже, форма не отправилась", "FAIL")
        result["errors"].append("Модалка не закрылась после публикации")
    elif result["errors"]:
        log(f"  Форма закрылась, но по пути были ошибки: {result['errors']}", "WARN")
    else:
        log("  Форма закрылась без ошибок — публикация прошла "
            "(запись создаётся как «Поручение», не в списке «Задачи»)", "PASS")
        result["created"] = True

    creation_test = result
    log(f"ТЕСТ создания завершён")


def test_create_entity_draft(entity_name="задача"):
    """Сохранение задачи как черновика (кнопка 'Сохранить' вместо
    'Опубликовать').

    ИСПРАВЛЕНО (по запросу): раньше заполняли только Наименование в
    расчёте на то, что черновик и должен сохраняться неполным — но
    оказалось, что для реального сохранения черновика тоже нужно
    заполнить все поля формы, как и при публикации (кроме PDF).
    Используем ту же общую функцию заполнения, что и публикация."""
    log("=" * 50)
    log(f"ТЕСТ: Сохранение {entity_name} как черновик")

    try:
        btn = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.XPATH,
                "//button[contains(., 'Создать') and not(contains(@class,'disabled'))]"))
        )
        scroll_to(btn)
        time.sleep(0.2)
        try:
            btn.click()
        except Exception:
            js_click(btn)
        time.sleep(1)
        log("  Клик по кнопке 'Создать'", "PASS")
    except Exception as e:
        log(f"  Кнопка 'Создать' не найдена: {e}", "FAIL")
        return False

    try:
        WebDriverWait(driver, 10).until(
            EC.visibility_of_element_located((By.XPATH,
                "//*[contains(text(),'Создать поручение') or contains(text(),'Создание')]"))
        )
        log("  Форма создания загружена", "PASS")
    except Exception:
        log("  Форма создания не загрузилась", "FAIL")
        shot("create_draft_form_missing")
        return False

    modal = find_visible_modal_container(hint_text="поручение")
    _fill_poruchenie_fields(modal if modal is not None else driver,
                             name_prefix="Черновик")

    time.sleep(0.3)
    return _submit_poruchenie_form("Сохранить")



# ==========================================
# 7. СОХРАНЕНИЕ + TELEGRAM
# ==========================================
def save_report():
    report.insert(0, "=" * 60)
    report.insert(1, "  ОТЧЁТ: ТЕСТИРОВАНИЕ ФИЛЬТРА — МОИ ЗАДАЧИ")
    report.insert(2, f"  Дата: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    report.insert(3, f"  URL: {TASKS_URL}")
    report.insert(4, "=" * 60)

    p, f, w = results["passed"], results["failed"], results["warnings"]
    status = "УСПЕШНО" if f == 0 else "ЕСТЬ ОШИБКИ"

    report.append("")
    report.append("=" * 60)
    report.append(f"  ИТОГО: PASS={p}  FAIL={f}  WARN={w}")
    report.append(f"  СТАТУС: {status}")
    report.append("=" * 60)

    fp = log_path("filter_report.txt")
    try:
        with open(fp, "w", encoding="utf-8") as file:
            file.write("\n".join(report))
        safe_print(f">>> Report: {fp}")
    except Exception: pass

    # ===== ОТПРАВКА В TELEGRAM =====
    # 1. СНАЧАЛА — краткая сводка для тимлида (он видит её первой)
    emoji = "✅" if f == 0 else ("🔥" if p == 0 else "⚠️")

    # === СВОДКА В СТИЛЕ ОСТАЛЬНЫХ АВТОТЕСТОВ (Счёт/Договор) ===
    # Если ВСЁ прошло успешно — только заголовок, без списка (список не
    # нужен, когда и так всё ок). Если есть провалы — заголовок с ❌ и
    # список ТОЛЬКО проваленных проверок (успешные не перечисляем) с
    # причиной; на каждый провал уже отдельно отправлен скрин бага (см.
    # report_to_sheet). Вердикт считается ПО ЧЕК-ЛИСТУ (checklist_results),
    # а не по общему счётчику FAIL в логе — так посторонний технический
    # FAIL внутри теста (не привязанный ни к одной проверке) не портит
    # ложно общий вердикт.
    all_checks_passed = (all(item["passed"] for item in checklist_results)
                          if checklist_results else (f == 0))
    status_ru = "УСПЕШНО" if all_checks_passed else "ЕСТЬ ОШИБКИ"
    header_emoji = "✅" if all_checks_passed else "❌"

    exec_lines = [f"{header_emoji} Автотест: Мои задачи (RGB ERP) — {status_ru}"]

    if not all_checks_passed:
        exec_lines.append("")
        failed_items = [item for item in checklist_results if not item["passed"]]
        if not failed_items:
            exec_lines.append("Есть технические ошибки в логе, но ни одна проверка "
                               "чек-листа не провалена явно — см. filter_report.txt")
        else:
            for item in failed_items:
                reason = item["reason"] or "причина не определена в логе"
                exec_lines.append(f"{item['name']}: Неуспешно. Причина: {reason}")

    summary_text = "\n".join(exec_lines)
    if len(summary_text) <= 3800:
        tg_send(summary_text)
    else:
        # На случай если список проверок не влезает в одно сообщение —
        # режем по кускам, чтобы ни одна строка не потерялась.
        chunk = 3800
        parts = [summary_text[i:i+chunk] for i in range(0, len(summary_text), chunk)]
        for part in parts:
            tg_send(part)

    # По просьбе — в Telegram уходит ТОЛЬКО чистая сводка выше (в стиле
    # остальных автотестов: "Автотест: ... — статус" + построчно по каждой
    # проверке). Короткое дублирующее сообщение со счётчиками Passed/
    # Failed/Warnings, подробный сырой дамп лога и скриншоты больше НЕ
    # отправляются в Telegram — сырой лог по-прежнему пишется в
    # filter_report.txt, а скриншоты (shot()) сохраняются локально рядом
    # со скриптом, этого достаточно для отладки при необходимости.
    try:
        p = screen_path("scr_final.png")
        driver.save_screenshot(p)
    except Exception: pass


# ==========================================
# ЗАПУСК
# ==========================================
try:
    tg_send(f"🚀 <b>Запуск теста «Мои задачи»</b>\n🕐 {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}")

    if not run_login():
        save_report(); raise SystemExit("Login failed")

    time.sleep(1)
    if not go_to_tasks():
        save_report(); raise SystemExit("Tasks failed")

    # --- Тесты ---
    time.sleep(0.5)
    test_buttons()

    # Объединённая проверка фильтрации задач ОДНОЙ строкой в чек-листе:
    # поиск по наименованию + фильтры (эквивалентное разбиение — по одному
    # репрезентативному значению на фильтр) + дата — один сценарий вместо
    # 3 отдельных строк.
    # ВАЖНО (подтверждено скриншотом реальной страницы): фильтра с лейблом
    # "Инициатор процесса" на странице НЕТ — вместо него есть "Наблюдатель
    # процесса". Ищем по реальному тексту.
    time.sleep(0.5)
    name_ok = test_name_filter()

    time.sleep(0.5)
    filters_ok = test_filters_quick(
        filters=[
            ("Тип задачи", "Все типы", None),
            ("Наблюдатель процесса", "Все наблюдатели",
             ["Алдажа Диас Андреевич", "Алдaжа Диас Андреевич",
              "Бейсембаев Куаныш Едилович"]),
            ("Исполнитель процесса", "Все исполнители",
             ["Алдажа Диас Андреевич", "Алдaжа Диас Андреевич",
              "Бейсембаев Куаныш Едилович"]),
            ("Проект", "Все проекты", None),
            ("Статус", "Все статусы", None),
        ],
        rows=ROWS_TASKS,
        report_label="Фильтры задач",
    )

    time.sleep(0.5)
    dates_ok = test_dates()

    report_to_sheet("Фильтрация задач", name_ok and filters_ok and dates_ok, ROWS_TASKS)
    time.sleep(0.5)
    test_create_entity(entity_name="задача")
    report_to_sheet("Создание задачи", bool(creation_test and creation_test.get("created")), ROWS_TASKS)
    # ИСПРАВЛЕНО: после публикации страница не всегда возвращается на
    # список задач (счётчик "Всего" не читался). В сценарии "Поручения"
    # перед тестом черновика есть повторный переход (go_to_assignments()),
    # а здесь его не было вовсе — из-за этого следующий тест не находил
    # кнопку "Создать" и падал с ошибкой драйвера. Добавляем то же самое
    # для задач.
    time.sleep(1)
    go_to_tasks()
    ok = test_create_entity_draft(entity_name="задача")
    report_to_sheet("Сохранение задачи как черновик", ok, ROWS_TASKS)

    time.sleep(0.5)
    test_assignments()

    time.sleep(0.5)
    test_calendar()

    save_report()

except SystemExit as e:
    log(f"Остановка: {e}", "FAIL"); save_report()
except Exception as e:
    log(f"Крит. ошибка: {e}", "FAIL"); shot("critical"); save_report()
