# -*- coding: utf-8 -*-
"""
НАКЛАДНАЯ (waybills) — АДАПТИРОВАНО под новый дизайн портала.

Портированы ВСЕ наработки из отлаженного скрипта договоров:
  • сайт НЕ на Ant Design — свой BEM-кит (ui-select__*, action-modal__*,
    ui-date-picker__*, evd-route__*, signers-card__*, detail-right__tab);
  • выбор опций КЛАВИАТУРОЙ (ArrowDown+Enter) — клики мышью этот
    ui-select игнорирует;
  • _hard_click с полной цепочкой pointer/mouse событий;
  • НИКАКИХ кликов по координатам экрана (pyautogui) — старая версия
    так открывала случайные документы из списка;
  • маршрут: «Добавить этап» → строка этапа → выбор → модалка
    «Согласующие: Этап N» → «Сохранить»;
  • подписанты: signers-card__select-link → два ui-select → «Сохранить»;
  • корректный выход из аккаунта (модалка «Вы уверены? Вы выйдете
    из системы» + флаг _LOGOUT_IN_PROGRESS);
  • защита от ухода на чужой документ (ensure_on_our_document);
  • даты через ui-date-picker с ПРОВЕРКОЙ результата.
"""

import sys as _sys
from pathlib import Path as _Path
_ROOT = _Path(__file__).resolve().parent.parent.parent
for _d in (_ROOT, _ROOT / "core", _ROOT / "config", _Path(__file__).resolve().parent):
    if str(_d) not in _sys.path:
        _sys.path.insert(0, str(_d))
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

import time
import re
from datetime import datetime, timedelta
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains
from selenium.common.exceptions import NoSuchElementException

# ==========================================
# КОНФИГУРАЦИЯ
# ==========================================
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager

_chrome_options = Options()
_chrome_options.add_argument("--start-maximized")

# ПОСТОЯННЫЙ профиль Chrome (не временный, как раньше). Это нужно для
# разрешения "Доступ к другим приложениям и сервисам на этом устройстве"
# (Local Network Access) — им Chrome защищает подключение сайта к
# NCALayer через wss://127.0.0.1:13579. Без постоянного профиля это
# разрешение негде сохранить, и Chrome спрашивает его заново КАЖДЫЙ
# запуск, а окно этого разрешения не ловится через pywinauto (оно не
# отдельное окно ОС, а всплывающий элемент внутри самого Chrome).
# Реши один раз вручную ("Разрешить") — дальше во всех новых запусках
# с этим же профилем разрешение уже не будет запрашиваться.
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
driver.implicitly_wait(0)  # ВАЖНО: было 3 — при большом количестве
# "пробуй способ 1 → не нашёл → способ 2" (а их в этом файле много)
# каждая неудачная попытка молча ждала до 3 секунд лишних. Явные
# ожидания (time.sleep/WebDriverWait) в коде расставлены сами, этого
# достаточно.
login_val = env("RGB_ACCOUNT1_LOGIN", "jyktmargyplay2@gmail.com")
pass_val = env("RGB_ACCOUNT1_PASSWORD", env("RGB_ACCOUNT1_PASSWORD_ALT", "12341234"))

# ЭЦП первого подписанта
NCA_PASSWORD = env("NCA_KEY1_PASSWORD")
MAIN_P12_PATH = env("NCA_KEY1_PATH", r"C:\Program Files\NCALayer\GOST2015_13-02-2026-18_04.p12")

# --- Второй подписант (Талгат Ерланович) ---
TALGAT_LOGIN = env("RGB_ACCOUNT3_LOGIN", env("RGB_ACCOUNT2_LOGIN"))
TALGAT_PASS = env("RGB_ACCOUNT3_PASSWORD", env("RGB_ACCOUNT2_PASSWORD"))
TALGAT_NCA_PASSWORD = env("NCA_KEY2_PASSWORD")
TALGAT_P12_PATH = env("NCA_KEY2_PATH", r"C:\Program Files\NCALayer\GOST512_b2c2008a1d14dd3f6a531597fb334afc4b3c6e76.p12")

BASE_URL = "https://testportal.rgbgroup.kz/"
WAYBILLS_URL = "https://testportal.rgbgroup.kz/documents/waybills"
WAIT = 15

# ==========================================
# ВЫБОР СЦЕНАРИЯ — теперь ОДИН параметр вместо трёх, и его можно
# передать аргументом командной строки (для автоматического перебора
# через run_workflow_and_report.py), а не только руками менять
# константу в файле:
#     py waybill_workflow_new_design.py default
#     py waybill_workflow_new_design.py paper_mode
# Без аргумента — берётся WAYBILL_SCENARIO ниже (по умолчанию "default").
# ==========================================
# ==========================================
# ВЫБОР СЦЕНАРИЯ — теперь ОДИН параметр вместо трёх.
#     py waybill_workflow_new_design.py            → все сценарии подряд
#     py waybill_workflow_new_design.py paper_mode  → только этот один
# ==========================================
WAYBILL_SCENARIOS = {
    "default":    {"PAPER_MODE": False, "FORM_MODE": "Произвольно", "NDS_SCENARIO": "НДС 16%"},
    "paper_mode": {"PAPER_MODE": True,  "FORM_MODE": "Произвольно", "NDS_SCENARIO": "НДС 16%"},
    "nds_none":   {"PAPER_MODE": False, "FORM_MODE": "Произвольно", "NDS_SCENARIO": "Без НДС"},
    "nds_0":      {"PAPER_MODE": False, "FORM_MODE": "Произвольно", "NDS_SCENARIO": "НДС 0%"},
    # ВНИМАНИЕ: "По форме" может открыть СОВСЕМ ДРУГОЙ набор полей на
    # форме (структурированный режим вместо свободного) — остальной код
    # заточен под "Произвольно". Если сломает дальнейшие шаги — это
    # ожидаемо при первом прогоне, смотрим по логам/скриншотам.
    "form_mode":  {"PAPER_MODE": False, "FORM_MODE": "По форме",    "NDS_SCENARIO": "НДС 16%"},
}

_scenario_key = "default"  # актуальный сценарий текущего прогона (меняется в цикле в самом низу файла)


def _apply_scenario(key):
    """Переустанавливает все глобальные переменные сценария и создаёт
    СВЕЖИЙ workflow_result — вызывается перед каждым прогоном main(),
    когда сценариев несколько подряд в одном запуске процесса."""
    global PAPER_MODE, FORM_MODE, NDS_SCENARIO, WAYBILL_NUM, workflow_result, _scenario_key
    _scenario_key = key
    s = WAYBILL_SCENARIOS[key]
    PAPER_MODE = s["PAPER_MODE"]
    FORM_MODE = s["FORM_MODE"]
    NDS_SCENARIO = s["NDS_SCENARIO"]

    nds_tag = {"Без НДС": "БезНДС", "НДС 0%": "НДС0", "НДС 16%": ""}.get(NDS_SCENARIO, "")
    WAYBILL_NUM = (f"НАКЛАДНАЯ-{'БУМ-' if PAPER_MODE else ''}"
                   f"{nds_tag + '-' if nds_tag else ''}"
                   f"{datetime.now().strftime('%d%m-%H%M%S')}")

    workflow_result = {
        "number": WAYBILL_NUM,
        "url": None,
        "created": False,
        "materials": False,
        "signatories": False,
        "route": False,
        "ecp_signed": False,
        "nds_ok": False,
        "form_mode_ok": False,
        "fail_reasons": {},  # {"Название проверки": "короткая причина"}
        "final_status": None,
        "actions_done": []
    }


# Инициализация "по умолчанию" — чтобы модуль импортировался/парсился
# без ошибок ещё до цикла запуска внизу файла (там же сценарий будет
# переустановлен заново на каждой итерации).
_apply_scenario("default")

LOG_FILE_PATH = log_path(f"waybill_log_{datetime.now().strftime('%d%m_%H%M%S')}.txt")
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
        path = screen_path(f"debug_waybill_{name}_{datetime.now().strftime('%H%M%S')}.png")
        driver.save_screenshot(path)
        log(f"  Скриншот: {path}")
    except Exception:
        pass


# ==========================================
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
    try:
        ActionChains(driver).send_keys(Keys.ESCAPE).perform()
        time.sleep(0.2)
    except Exception:
        pass
    try:
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
# EXIT EDIT MODE
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


def find_visible_modal_container(hint_text=None):
    strategies = [
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
            if modal is not None:
                xp = (f".//button[.//span[normalize-space(text())='{t}'] "
                      f"or normalize-space(text())='{t}']")
            else:
                xp = (f"//button[.//span[normalize-space(text())='{t}'] "
                      f"or normalize-space(text())='{t}']"
                      f"[not(ancestor::*[contains(@class,'detail-right')])]"
                      f"[not(ancestor::*[contains(@class,'chat')])]"
                      f"[not(ancestor::*[contains(@class,'discussion')])]")
            btns = scope.find_elements(By.XPATH, xp)
            visible = [b for b in btns if b.is_displayed() and b.is_enabled()]
            if visible:
                return visible[-1] if prefer_last else visible[0]
        except Exception:
            continue
    return None


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
    return None


def dismiss_logout_confirm_if_present():
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

    log(f"    ⚠ {label_text}: не удалось выбрать дату ни одним способом", "WARN")
    dump_field_html(label_text)
    return False



def find_dropdown_in_scope(scope, label_text):
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


def fill_date_field(label, date_str):
    try:
        date_obj = datetime.strptime(date_str, "%d.%m.%Y")
    except Exception as e:
        log(f"  ⚠ {label}: некорректная дата '{date_str}' ({e})", "WARN")
        return False

    if fill_popup_date_field(label, date_obj):
        return True

    try:
        labels = driver.find_elements(By.XPATH, f"//*[normalize-space(text())='{label}']")
        if not labels:
            labels = driver.find_elements(By.XPATH, f"//*[contains(text(),'{label}')]")
        for lbl in labels:
            if not lbl.is_displayed():
                continue
            try:
                inp = lbl.find_element(
                    By.XPATH,
                    "./following::input[contains(@placeholder,'дату') "
                    "or contains(@placeholder,'Выберите дату')][1]")
            except Exception:
                continue
            if not inp.is_displayed() or not inp.is_enabled():
                continue
            try:
                inp.click()
            except Exception:
                js_click(inp)
            time.sleep(0.3)
            try:
                inp.send_keys(Keys.CONTROL + "a")
                inp.send_keys(Keys.DELETE)
            except Exception:
                pass
            inp.send_keys(date_str)
            time.sleep(0.3)
            inp.send_keys(Keys.ENTER)
            time.sleep(0.6)
            current = inp.get_attribute("value") or ""
            if date_str in current:
                log(f"  ✓ {label}: {date_str} [input]", "PASS")
                return True
    except Exception as e:
        log(f"  ⚠ {label}: {e}", "WARN")

    log(f"  ⚠ {label}: НЕ УДАЛОСЬ выставить {date_str} "
        f"(значение по умолчанию оставлено как есть)", "WARN")
    dump_field_html(label)
    return False




# ==========================================
# ПЕРЕКЛЮЧАТЕЛИ (role="switch") — подтверждено DevTools:
#   <span class="ccp-toggle__label">Название</span>
#   ...
#   <button type="button" role="switch" aria-checked="true/false"
#           class="ui-switch ui-switch--checked">
# Подпись и сама кнопка — РАЗНЫЕ элементы, не вложены друг в друга.
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
    """Приводит переключатель label_text к состоянию desired_on
    (True=включён, False=выключен). Возвращает True/False успеха."""
    switch = find_toggle_switch(label_text)
    if not switch:
        log(f"  ⚠ Переключатель '{label_text}' не найден", "WARN")
        return False

    current = get_toggle_state(switch)
    if current is None:
        log(f"  ⚠ Не удалось прочитать состояние '{label_text}'", "WARN")
        return False

    if current == desired_on:
        log(f"  • '{label_text}' уже в состоянии {'вкл' if desired_on else 'выкл'}", "PASS")
        return True

    if not _hard_click(switch):
        js_click(switch)
    time.sleep(0.6)

    switch = find_toggle_switch(label_text)  # элемент мог перерендериться
    new_state = get_toggle_state(switch) if switch else None
    ok = (new_state == desired_on)
    log(f"  {'✓' if ok else '⚠'} '{label_text}': "
        f"{'вкл' if new_state else 'выкл'} (ожидали {'вкл' if desired_on else 'выкл'})",
        "PASS" if ok else "FAIL")
    return ok


def _hard_click(el):
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
    if panel is not None and _select_option_by_keyboard(panel):
        return True

    try:
        scroll_to(el)
        time.sleep(0.25)
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
            time.sleep(0.8)
            panels = driver.find_elements(
                By.XPATH, "//div[contains(@class,'ui-select__panel')]")
            if not any(p.is_displayed() for p in panels):
                log(f"      • опция '{label[:30]}' выбрана ({method})")
                return True
        except Exception:
            continue
    return False


def _close_any_ui_select_panel():
    for _ in range(3):
        try:
            panels = driver.find_elements(
                By.XPATH, "//div[contains(@class,'ui-select__panel')]")
            if not any(p.is_displayed() for p in panels):
                return True
        except Exception:
            return True

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

        try:
            ActionChains(driver).send_keys(Keys.ESCAPE).perform()
            time.sleep(0.35)
        except Exception:
            pass

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

        _click_option_robustly(target["element"], target["text"], panel=panel)
        time.sleep(0.6)

        _close_any_ui_select_panel()

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


def go_to_tab(tab_name):
    for xp in [
        f"//button[contains(@class,'detail-right__tab') and normalize-space(text())='{tab_name}']",
        f"//div[contains(@class,'ant-segmented-item-label') and @title='{tab_name}']",
        f"//label[contains(@class,'ant-segmented-item')]//div[normalize-space(text())='{tab_name}']",
        f"//*[normalize-space(text())='{tab_name}'][not(ancestor::div[contains(@class,'ant-modal')])]",
    ]:
        try:
            tabs = driver.find_elements(By.XPATH, xp)
            visible = [t for t in tabs if t.is_displayed()]
            if visible:
                try:
                    visible[0].click()
                except Exception:
                    js_click(visible[0])
                time.sleep(2)
                return True
        except Exception:
            continue
    return False


def add_approval_route(approver_query="Бейсембаев"):
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
        try:
            vals = driver.find_elements(
                By.XPATH,
                "//div[contains(@class,'evd-route__stages')]"
                "//span[contains(@class,'ui-select__value')]")
            for v in vals:
                if not v.is_displayed():
                    continue
                txt = (v.get_attribute("textContent") or "").strip()
                if txt and "выбрать" not in txt.lower():
                    return True
        except Exception:
            pass

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
                if len(txt) > 2 and any(ch.isalpha() for ch in txt):
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
        if "margulan" in txt and "aisinov" not in txt:
            option = opt
            break
    if not option:
        for opt in options:
            txt = (opt["text"] or "").lower()
            if approver_query.lower() in txt:
                option = opt
                break
    if not option and options:
        option = options[0]
        log(f"  ⚠ '{approver_query}' не найден — беру первого: '{option['text']}'", "WARN")

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
    _click_option_robustly(option["element"], option["text"], panel=panel)
    time.sleep(0.8)

    _close_any_ui_select_panel()

    try:
        modal = None
        for _ in range(6):
            modal = find_visible_modal_container(hint_text="Согласующие")
            if modal:
                break
            time.sleep(0.5)

        if modal:
            log("  Шаг 4.5: модалка «Согласующие» открыта — жму «Сохранить»")
            save_btn = find_modal_button(modal, ["Сохранить", "Добавить", "ОК", "Применить"])
            if not save_btn:
                save_btn = find_modal_button(
                    None, ["Сохранить", "Добавить", "ОК", "Применить"])

            if save_btn:
                saved = False
                for method in ["hard", "js", "selenium", "actions"]:
                    try:
                        if method == "hard":
                            _hard_click(save_btn)
                        elif method == "js":
                            js_click(save_btn)
                        elif method == "selenium":
                            save_btn.click()
                        else:
                            ActionChains(driver).move_to_element(save_btn) \
                                .pause(0.3).click().perform()
                        time.sleep(1.5)
                        if not find_visible_modal_container(hint_text="Согласующие"):
                            saved = True
                            log(f"  ✓ Модалка «Согласующие» сохранена ({method})", "PASS")
                            break
                    except Exception:
                        continue
                if not saved:
                    log("  ⚠ Не удалось нажать «Сохранить» в модалке согласующих", "WARN")
                    shot("approvers_modal_not_saved")
            else:
                log("  ⚠ Кнопка «Сохранить» в модалке согласующих не найдена", "WARN")
                shot("approvers_modal_no_save_btn")
        else:
            log("  • Модалка «Согласующие» не появилась — вероятно, "
                "выбор применился сразу")
    except Exception as e:
        log(f"  ⚠ Обработка модалки согласующих: {e}", "WARN")

    time.sleep(1.0)

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
    if workflow_result.get("url") and not ensure_on_our_document(f"click_card_action:{button_text}"):
        log(f"  ⚠ '{button_text}' пропущен — не удалось открыть наш документ", "WARN")
        return False

    candidates = []
    header_xps = [
        f"//div[contains(@class,'detail-header')]"
        f"//button[.//span[normalize-space(text())='{button_text}']]",
        f"//div[contains(@class,'detail-header')]"
        f"//button[normalize-space(text())='{button_text}']",
        f"//section[contains(@class,'detail-hero')]"
        f"//button[.//span[normalize-space(text())='{button_text}']]",
    ]
    for xp in header_xps:
        try:
            btns = driver.find_elements(By.XPATH, xp)
            for b in btns:
                if b.is_displayed() and b.is_enabled():
                    candidates.append(b)
            if candidates:
                log(f"    (кнопка '{button_text}' найдена в шапке документа)")
                break
        except Exception:
            continue

    if not candidates:
        try:
            btns = driver.find_elements(By.XPATH,
                f"//button[.//span[normalize-space(text())='{button_text}']]"
                f"[not(ancestor::*[contains(@class,'detail-right')])]"
                f"[not(ancestor::*[contains(@class,'chat')])]"
                f"[not(ancestor::*[contains(@class,'discussion')])]"
                f"[not(ancestor::form)]")
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
        time.sleep(2.5)
        modal = find_visible_modal_container(hint_text=button_text)
        if not modal:
            return False

        log(f"    Модалка подтверждения '{button_text}'", "PASS")

        try:
            comment_areas = modal.find_elements(By.XPATH, ".//textarea")
            for ca in comment_areas:
                if ca.is_displayed() and ca.is_enabled():
                    ca.clear()
                    ca.send_keys(f"Автоподтверждение '{button_text}' для {WAYBILL_NUM}")
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
                time.sleep(4)
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
            time.sleep(2)
            handle_confirmation_modal()
            return True
        except Exception:
            continue
    return False


def get_current_status():
    known = ["Черновик", "На согласовании", "На подписании",
             "Подписан", "Действует", "Исполнен", "Отменён", "Архив"]
    for status in known:
        try:
            els = driver.find_elements(By.XPATH,
                f"//*[contains(@class,'ant-tag')][normalize-space(text())='{status}']")
            for el in els:
                if el.is_displayed():
                    return status
        except Exception:
            continue
    return None


# ==========================================
# NCALayer
# ==========================================
def _dismiss_external_protocol_dialog():
    """Chrome при вызове NCALayer через внешний протокол показывает
    нативное окно-разрешение вида 'testportal.rgbgroup.kz запрашивает
    разрешение на: Доступ к другим приложениям...' с кнопками
    'Разрешить'/'Блокировать'. Пока никто не жмёт 'Разрешить' —
    процесс подписания не двигается вообще.

    ВАЖНО: кликаем ТОЛЬКО если окно реально содержит текст про запрос
    разрешения — иначе можно случайно нажать постороннюю кнопку
    (например 'Представление задач' на панели задач Windows)."""
    try:
        from pywinauto import Desktop
    except Exception:
        return False

    exact_button_texts = {"разрешить", "allow", "открыть", "open"}
    found_any_window_with_buttons = []

    for backend in ["uia", "win32"]:
        try:
            desktop = Desktop(backend=backend)
            for w in desktop.windows():
                try:
                    title = (w.window_text() or "")
                    full_text = ""
                    try:
                        texts = w.descendants(control_type="Text") if backend == "uia" else []
                        full_text = " ".join((t.window_text() or "") for t in texts).lower()
                    except Exception:
                        pass
                    is_permission_popup = (
                        "запрашивает разрешение" in full_text
                        or "requesting permission" in full_text
                        or "wants to" in full_text
                    )

                    btns = w.descendants(control_type="Button") if backend == "uia" \
                        else w.descendants(class_name="Button")
                    if not btns:
                        continue
                    btn_texts = [(b.window_text() or "").strip() for b in btns]
                    btn_texts = [t for t in btn_texts if t]
                    if btn_texts:
                        found_any_window_with_buttons.append(
                            f"[{backend}] '{title[:40]}' permission={is_permission_popup} -> {btn_texts}")

                    if not is_permission_popup:
                        continue

                    for b, btxt in zip(btns, btn_texts):
                        if btxt.strip().lower() in exact_button_texts:
                            b.click_input()
                            log(f"  ✓ Разрешение подтверждено: окно='{title[:50]}', "
                                f"кнопка='{btxt}' (backend={backend})", "PASS")
                            return True
                except Exception:
                    continue
        except Exception:
            continue

    if found_any_window_with_buttons:
        log("  [DIAG] Окна с кнопками на экране (разрешение не найдено среди них):", "DIAG")
        for line in found_any_window_with_buttons[:15]:
            log(f"    {line}", "DIAG")
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
            _dismiss_external_protocol_dialog()

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

        # ПРОВЕРКА: NCALayer часто ЗАПОМИНАЕТ путь к ключу с прошлого
        # раза и сам подставляет его в поле "Место хранения" — тогда
        # весь блок ниже (открытие проводника/диалога) не нужен вовсе.
        path_already_set = False
        try:
            fname = os.path.basename(p12_path)
            texts = dialog.descendants(control_type="Text") + dialog.descendants(control_type="Edit")
            for t in texts:
                cur = (t.window_text() or "")
                if fname[:20] in cur:
                    path_already_set = True
                    log(f"    ✓ Путь к ключу уже подставлен NCALayer сам: '{cur[:60]}'", "PASS")
                    break
        except Exception:
            pass

        if path_already_set:
            pass
        else:
            try:
                before_handles = {w.handle for w in Desktop(backend="uia").windows()}
            except Exception:
                before_handles = set()

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
                            after = Desktop(backend="uia").windows()
                            new_windows = [w for w in after if w.handle not in before_handles]
                            if new_windows:
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
                file_win = None
                for _ in range(10):
                    after = Desktop(backend="uia").windows()
                    new_windows = [w for w in after if w.handle not in before_handles]
                    visible = [w for w in new_windows if w.is_visible()]
                    if visible:
                        file_win = visible[-1]
                        break
                    time.sleep(0.5)

                if file_win is None:
                    log("  ⚠ Новое окно выбора файла не появилось", "WARN")
                    shot("file_dialog_not_found")
                    return False

                win_class = ""
                try:
                    win_class = file_win.element_info.class_name or ""
                except Exception:
                    pass
                log(f"    Новое окно: '{file_win.window_text()}' (класс: {win_class})")

                if win_class == "CabinetWClass":
                    file_win.set_focus()
                    time.sleep(0.5)
                    file_win.type_keys("^l")
                    time.sleep(0.5)
                    file_win.type_keys(p12_path.replace(" ", "{SPACE}"), with_spaces=True)
                    time.sleep(0.5)
                    file_win.type_keys("{ENTER}")
                    time.sleep(2)
                    log("    ✓ Путь введён через адресную строку Проводника", "PASS")
                else:
                    file_win.set_focus()
                    time.sleep(0.5)
                    edit = file_win.child_window(class_name="Edit")
                    edit.set_edit_text(p12_path)
                    time.sleep(1)
                    edit.type_keys("{ENTER}")
                    time.sleep(2)
                    log("    ✓ Путь введён в диалог выбора файла", "PASS")
            except Exception as e:
                import traceback
                log(f"  ⚠ Ошибка в диалоге файла: {repr(e)}", "WARN")
                for tb_line in traceback.format_exc().split("\n"):
                    log(f"    {tb_line}")
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
            labels = dialog.descendants(control_type="Text")
            label_rect = None
            for lbl in labels:
                txt = (lbl.window_text() or "").strip().lower()
                if txt in ("пароль", "құпия сөз", "құпиясөз"):
                    label_rect = lbl.rectangle()
                    break
            if label_rect:
                edits = dialog.descendants(control_type="Edit")
                best, best_dy = None, 10 ** 9
                for e in edits:
                    r = e.rectangle()
                    dy = r.top - label_rect.bottom
                    if -5 <= dy <= 80 and abs(dy) < best_dy:
                        best, best_dy = e, abs(dy)
                if best:
                    best.click_input()
                    time.sleep(0.3)
                    try:
                        best.set_edit_text("")
                    except Exception:
                        pass
                    time.sleep(0.2)
                    best.type_keys(password, with_spaces=True)
                    password_ok = True
                    log("  ✓ Пароль введён (поиск по подписи 'Пароль')", "PASS")
        except Exception as e:
            log(f"  ⚠ Поиск поля по подписи 'Пароль' не удался: {e}", "WARN")

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
# КНОПКА "СОЗДАТЬ"
# ==========================================
def click_create_button():
    candidates = []
    try:
        btns = driver.find_elements(By.XPATH,
            "//button[.//span[normalize-space(text())='Создать']]")
        for b in btns:
            try:
                if b.is_displayed() and b.is_enabled() and b.text.strip() == "Создать":
                    candidates.append(b)
            except Exception:
                continue
    except Exception:
        pass

    if not candidates:
        return False

    target = candidates[-1]
    initial_url = driver.current_url
    try:
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", target)
        time.sleep(0.5)
    except Exception:
        pass

    def url_changed():
        for _ in range(8):
            time.sleep(1)
            cur = driver.current_url
            if cur == initial_url:
                continue
            if "/waybills/" not in cur or "/create" in cur:
                continue
            tail = cur.rstrip("/").split("/waybills/")[-1].split("/")[0]
            if len(tail) >= 8:
                return True
        return False

    strategies = [
        ("selenium", lambda: target.click()),
        ("js", lambda: driver.execute_script("arguments[0].click();", target)),
        ("actions", lambda: ActionChains(driver).move_to_element(target).pause(0.3).click().perform()),
        ("enter", lambda: target.send_keys(Keys.ENTER)),
    ]

    for name, action in strategies:
        try:
            action()
            if url_changed():
                log(f"  ✓ Клик 'Создать' — {name}", "PASS")
                return True
        except Exception:
            continue
    return False


# ==========================================
# LOGOUT / LOGIN
# ==========================================
def logout_current_account():
    global _LOGOUT_IN_PROGRESS
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


def login_with(login_value, password_value):
    log(f"  Логин под: {login_value}")
    try:
        WebDriverWait(driver, WAIT).until(
            EC.visibility_of_element_located((By.XPATH,
                "//input[contains(@placeholder,'огин') or contains(@placeholder,'Login') "
                "or @type='email' or @name='username' or @id='username' or @type='text']"))
        )
    except Exception:
        return False

    login_field = None
    for xp in [
        "//input[contains(@placeholder,'огин')]",
        "//input[@name='username' or @id='username']",
        "//input[contains(@placeholder,'Login')]",
        "//input[@type='email']",
        "//input[@type='text'][1]",
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

    login_field.clear()
    login_field.send_keys(login_value)

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

    password_field.clear()
    password_field.send_keys(password_value)

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

    time.sleep(6)
    dismiss_chrome_password_popup()

    try:
        pw = driver.find_elements(By.XPATH, "//input[@type='password']")
        if any(p.is_displayed() for p in pw):
            log(f"  ⚠ Логин {login_value} не удался", "WARN")
            return False
    except Exception:
        pass

    global _LOGOUT_IN_PROGRESS
    _LOGOUT_IN_PROGRESS = False
    log(f"  ✓ Успешный вход: {login_value}", "PASS")
    return True



def ensure_on_our_document(context=""):
    target = workflow_result.get("url")
    if not target:
        return False
    try:
        target_id = target.rstrip("/").split("/waybills/")[-1].split("/")[0]
    except Exception:
        target_id = ""
    cur = driver.current_url
    if target_id and target_id in cur:
        return True
    log(f"  ⚠ Открыт не наш документ{(' (' + context + ')') if context else ''}: "
        f"{cur} — возвращаюсь на {target}", "WARN")
    try:
        driver.get(target)
        time.sleep(4)
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


def select_dogovor_sharipzhan():
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
    time.sleep(0.3)

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

    if not panel:
        log("  ⚠ Список договоров не открылся", "WARN")
        shot("dogovor_panel_not_open")
        return False

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
            time.sleep(1.3)
        except Exception:
            pass
        options = [o for o in panel_options()
                   if re.search(r"(?<![0-9])ДГ-2026-10-000013(?![0-9])", o["text"], re.IGNORECASE)]
        if options:
            log(f"    Поиск '{query}': найдено {len(options)}")
            break

    if not options:
        options = panel_options()
        log(f"  [DIAG] Договоров в списке: {len(options)} → "
            f"{[o['text'][:45] for o in options][:10]}", "DIAG")
        options = [o for o in options
                   if re.search(r"(?<![0-9])ДГ-2026-10-000013(?![0-9])", o["text"], re.IGNORECASE)]

    if not options:
        log("  ⚠ Договоры не найдены в списке", "WARN")
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
    _click_option_robustly(best["element"], best["text"], panel=panel)
    time.sleep(1.2)
    _close_any_ui_select_panel()

    try:
        vals = driver.find_elements(
            By.XPATH, "//span[contains(@class,'ui-select__value')]")
        for v in vals:
            txt = (v.get_attribute("textContent") or "").strip()
            if txt and "выбрать" not in txt.lower() and "оговор" in txt.lower():
                log(f"  ✓ Договор: '{txt[:50]}'", "PASS")
                return True
    except Exception:
        pass
    log("  ✓ Договор выбран (значение не подтверждено явно)", "PASS")
    return True


def select_radio_option(group_label, option_text):
    try:
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
                    time.sleep(0.6)
                    if radio is not None:
                        try:
                            if radio.is_selected():
                                log(f"  ✓ {group_label}: '{option_text}' ({method})", "PASS")
                                return True
                        except Exception:
                            pass
                    errs = driver.find_elements(
                        By.XPATH, f"//*[contains(normalize-space(text()),"
                                  f"'Выберите режим формирования')]")
                    if not any(e.is_displayed() for e in errs):
                        log(f"  ✓ {group_label}: '{option_text}' ({method})", "PASS")
                        return True
                except Exception:
                    continue

        log(f"  ⚠ {group_label}: не удалось выбрать '{option_text}'", "WARN")
        dump_field_html(group_label)
        return False
    except Exception as e:
        log(f"  ⚠ {group_label}: {e}", "WARN")
        return False


def select_waybill_dropdown(label, allow_missing=False, target_option=None):
    trigger = find_ui_kit_trigger_near_label(label)
    if not trigger:
        if not allow_missing:
            log(f"  ⚠ {label}: поле не найдено", "WARN")
            dump_field_html(label)
        return None

    scroll_to(trigger)
    time.sleep(0.25)

    panel = None
    for method in ["hard", "js", "selenium"]:
        try:
            if method == "hard":
                _hard_click(trigger)
            elif method == "js":
                js_click(trigger)
            else:
                trigger.click()
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
        if not allow_missing:
            log(f"  ⚠ {label}: список не открылся", "WARN")
        return None

    opts = []
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
                opts.append({"element": b, "text": txt})
    except Exception:
        pass

    if not opts:
        _close_any_ui_select_panel()
        return None

    picked = None
    if "НДС" in label:
        # NDS_SCENARIO задаёт, какой именно вариант выбрать (сценарий
        # для теста НДС) — раньше всегда брали 16% жёстко.
        for o in opts:
            if NDS_SCENARIO.lower() in o["text"].lower():
                picked = o
                break
        if not picked:
            for o in opts:
                if "16" in o["text"] and "%" in o["text"]:
                    picked = o
                    break
        if not picked:
            for o in opts:
                t = o["text"].lower()
                if "%" in t and "без" not in t:
                    picked = o
                    break
    elif target_option:
        for o in opts:
            if target_option.lower() in o["text"].lower():
                picked = o
                break
    if not picked:
        picked = opts[0]

    _click_option_robustly(picked["element"], picked["text"], panel=panel)
    time.sleep(0.8)
    _close_any_ui_select_panel()
    log(f"  ✓ {label}: '{picked['text'][:40]}'", "PASS")
    return "Success"


def fill_materials():
    result = {"qty": False, "reference": False}

    try:
        rows = driver.find_elements(By.XPATH, "//table//tbody//tr")
        visible_rows = [r for r in rows if r.is_displayed()]
        set_qty = False
        if visible_rows:
            first_row = visible_rows[0]
            headers = driver.find_elements(By.XPATH, "//table//thead//th")
            qty_col_idx = None
            contract_col_idx = None
            for i, h in enumerate(headers):
                htext = (h.text or "").lower().replace("\n", " ").strip()
                if "количество по договору" in htext:
                    contract_col_idx = i + 1
                elif htext == "кол-во" or (htext.startswith("кол") and "договору" not in htext):
                    qty_col_idx = i + 1

            max_qty = 1
            if contract_col_idx:
                try:
                    cell = first_row.find_element(By.XPATH, f".//td[{contract_col_idx}]")
                    m = re.search(r'\d+', (cell.text or "").replace(" ", ""))
                    if m:
                        max_qty = int(m.group())
                except Exception:
                    pass
            log(f"    Остаток по договору: {max_qty}")
            qty_value = str(max_qty)

            qty_input = None
            if qty_col_idx:
                try:
                    qty_input = first_row.find_element(By.XPATH, f".//td[{qty_col_idx}]//input")
                except Exception:
                    pass
            if not qty_input:
                for inp in first_row.find_elements(By.XPATH, ".//input"):
                    if inp.is_displayed() and inp.is_enabled():
                        val = (inp.get_attribute("value") or "").strip()
                        if val in ["0", ""]:
                            qty_input = inp
                            break

            if qty_input:
                set_number_native(qty_input, qty_value)
                time.sleep(0.5)
                if qty_value in (qty_input.get_attribute("value") or ""):
                    set_qty = True
                    log(f"    ✓ Кол-во в строке: {qty_value}", "PASS")

        result["qty"] = set_qty
        if not set_qty:
            log("    ⚠ Поле 'Кол-во' не заполнено", "WARN")
    except Exception as e:
        log(f"    ⚠ Кол-во: {e}", "WARN")

    try:
        ref_btns = driver.find_elements(By.XPATH,
            "//button[contains(normalize-space(.),'Из справочника')]")
        vis = [b for b in ref_btns if b.is_displayed() and b.is_enabled()]
        if not vis:
            log("    • Кнопка 'Из справочника' не найдена — пропускаю")
            return result["qty"] or result["reference"]

        scroll_to(vis[0])
        time.sleep(0.3)
        _hard_click(vis[0])
        time.sleep(2.0)

        modal = find_visible_modal_container(hint_text="Добавить материал")
        if not modal:
            log("    ⚠ Модалка 'Добавить материал' не открылась", "WARN")
            return result["qty"] or result["reference"]

        log("    Модалка 'Добавить материал' открыта", "PASS")

        for field in ["Материал", "Статья расходов", "Тип"]:
            try:
                sel = find_dropdown_in_scope(modal, field)
                if not sel:
                    continue
                txt = (sel.text or "").strip().lower()
                if txt and "выбер" not in txt:
                    continue
                _hard_click(sel)
                time.sleep(0.8)
                panels = driver.find_elements(
                    By.XPATH, "//div[contains(@class,'ui-select__panel')]")
                vp = [p for p in panels if p.is_displayed()]
                if not vp:
                    continue
                p = vp[-1]
                opts = []
                for b in p.find_elements(By.XPATH, ".//button[@role='option']"):
                    if not b.is_displayed():
                        continue
                    t = (b.get_attribute("textContent") or "").strip()
                    if t:
                        opts.append({"element": b, "text": t})
                if opts:
                    _click_option_robustly(opts[0]["element"], opts[0]["text"], panel=p)
                    log(f"    ✓ {field}: '{opts[0]['text'][:30]}'", "PASS")
                    time.sleep(0.6)
                _close_any_ui_select_panel()
            except Exception as e:
                log(f"    ⚠ {field}: {e}", "WARN")

        try:
            name_inp = modal.find_element(By.XPATH,
                ".//*[contains(text(),'Наименование')]/following::input[1]")
            name_inp.send_keys(f"Материал RPA {datetime.now().strftime('%H%M')}")
        except Exception:
            pass
        try:
            qty_inp = modal.find_element(By.XPATH,
                ".//*[normalize-space(text())='Количество']/following::input[1]")
            set_number_native(qty_inp, "50")
            log("    ✓ Количество: 50", "PASS")
        except Exception:
            pass
        try:
            price_inp = modal.find_element(By.XPATH,
                ".//*[contains(text(),'Цена за единицу без НДС')]/following::input[1]")
            set_number_native(price_inp, "2000")
            log("    ✓ Цена без НДС: 2000", "PASS")
        except Exception:
            pass

        blur_focus()
        time.sleep(0.5)

        save_btn = find_modal_button(modal, ["Добавить", "Сохранить"]) or \
                   find_modal_button(None, ["Добавить", "Сохранить"])
        if save_btn:
            for method in ["hard", "js", "selenium"]:
                try:
                    if method == "hard":
                        _hard_click(save_btn)
                    elif method == "js":
                        js_click(save_btn)
                    else:
                        save_btn.click()
                    time.sleep(2.0)
                    if not find_visible_modal_container(hint_text="Добавить материал"):
                        result["reference"] = True
                        log("    ✓ Материал из справочника добавлен", "PASS")
                        break
                except Exception:
                    continue
    except Exception as e:
        log(f"    ⚠ Материал из справочника: {e}", "WARN")

    return result["qty"] or result["reference"]


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
        time.sleep(1.2)
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
        ["Бейсембаев Куаныш Едилович", "Куаныш Едилович Бейсембаев", "Бейсембаев"], "Заказчик")
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
                time.sleep(2.0)
                break
            except Exception:
                continue
        log("  ✓ Кнопка 'Сохранить' подписантов нажата", "PASS")
    else:
        log("  ⚠ Кнопка 'Сохранить' подписантов не найдена", "WARN")

    result = bool(ok_zakazchik) and bool(ok_kontragent)
    log(f"  Подписанты: Заказчик={'OK' if ok_zakazchik else 'FAIL'}, "
        f"Контрагент={'OK' if ok_kontragent else 'FAIL'}",
        "PASS" if result else "WARN")
    if not result:
        shot("signatories_incomplete")
    return result


def sign_waybill_by_talgat(waybill_url):
    log("=" * 60)
    log("Талгат подписывает накладную (marshar244, GOST512)")
    log("=" * 60)

    if not waybill_url:
        log("  ⚠ URL накладной неизвестен", "WARN")
        return False

    if not logout_current_account():
        driver.get(BASE_URL)
        time.sleep(4)

    if not login_with(TALGAT_LOGIN, TALGAT_PASS):
        log("  ⚠ Не удалось войти под Талгатом", "WARN")
        return False

    dismiss_chrome_password_popup()
    driver.get(waybill_url)
    time.sleep(5)
    dismiss_chrome_password_popup()

    try:
        target_id = waybill_url.rstrip("/").split("/waybills/")[-1].split("/")[0]
    except Exception:
        target_id = ""
    if target_id and target_id not in driver.current_url:
        log(f"  ⚠ Под Талгатом накладная не открылась ({driver.current_url})", "WARN")
        shot("wrong_page_talgat")
        return False

    time.sleep(2)
    shot("talgat_opened_waybill")
    log(f"  Статус накладной: '{get_current_status()}'")

    for sign_btn in ["Подписать заказчиком", "Подписать", "Подтвердить подписание"]:
        if click_card_action(sign_btn):
            log(f"  Нажата '{sign_btn}', жду NCALayer...")
            signed = sign_with_ncalayer(
                password=TALGAT_NCA_PASSWORD, p12_path=TALGAT_P12_PATH)
            if signed:
                workflow_result["actions_done"].append("Талгат: ЭЦП OK")
            time.sleep(8)
            status = get_current_status()
            log(f"  Талгат: '{sign_btn}' → '{status}'", "PASS" if signed else "WARN")
            workflow_result["actions_done"].append(f"Талгат: {sign_btn} → {status}")
            workflow_result["final_status"] = status
            return signed

    log("  ⚠ Кнопка подписания не найдена под Талгатом", "WARN")
    shot("no_talgat_sign_btn")
    return False



# ==========================================
# ГЛАВНЫЙ WORKFLOW
# ==========================================
def main():
    log("=" * 60)
    log(f"НАКЛАДНАЯ: {WAYBILL_NUM}")
    log("=" * 60)

    # --- ЭТАП 0: Открытие сайта (иначе браузер остаётся на data:, и логин-форма никогда не появляется) ---
    driver.get(BASE_URL)
    time.sleep(3)

    # --- ЭТАП 1: Логин ---
    log("ЭТАП 1: Логин (основной аккаунт)")
    log(f"  URL: {driver.current_url}")
    try:
        WebDriverWait(driver, WAIT).until(
            EC.visibility_of_element_located((By.XPATH,
                "//input[contains(@placeholder,'огин') or @type='email' "
                "or @name='username' or @id='username']")))
    except Exception:
        log("  • Поле логина не появилось (возможно уже авторизованы)")

    login_field = None
    for xp in [
        "//input[contains(@placeholder,'огин')]",
        "//input[@name='username' or @id='username']",
        "//input[@type='email']",
        "//input[@type='text'][1]",
    ]:
        try:
            fields = driver.find_elements(By.XPATH, xp)
            vis = [f for f in fields if f.is_displayed() and f.is_enabled()]
            if vis:
                login_field = vis[0]
                break
        except Exception:
            continue

    if login_field:
        try:
            login_field.clear()
            login_field.send_keys(login_val)
        except Exception:
            pass
        pw_field = None
        for xp in ["//input[@type='password']", "//input[contains(@placeholder,'ароль')]"]:
            try:
                fields = driver.find_elements(By.XPATH, xp)
                vis = [f for f in fields if f.is_displayed() and f.is_enabled()]
                if vis:
                    pw_field = vis[0]
                    break
            except Exception:
                continue
        if pw_field:
            try:
                pw_field.clear()
                pw_field.send_keys(pass_val)
            except Exception:
                pass
        for xp in [
            "//button[.//span[normalize-space(text())='Войти']]",
            "//button[contains(., 'Войти')]",
            "//button[@type='submit']",
        ]:
            try:
                btns = driver.find_elements(By.XPATH, xp)
                vis = [b for b in btns if b.is_displayed() and b.is_enabled()]
                if vis:
                    try:
                        vis[0].click()
                    except Exception:
                        js_click(vis[0])
                    break
            except Exception:
                continue
        time.sleep(6)
        log(f"  ✓ После логина URL: {driver.current_url}", "PASS")
        dismiss_chrome_password_popup()

    # --- ЭТАП 2: Накладные ---
    log("ЭТАП 2: Переход в 'Накладные'")

    def on_waybills_list():
        cur = driver.current_url
        if "/documents/waybills" not in cur:
            return False
        tail = cur.split("/documents/waybills", 1)[1].strip("/")
        return tail == "" or tail.startswith("?")

    if not on_waybills_list():
        log(f"  Текущий URL не список накладных ({driver.current_url}) — перехожу")
        driver.get(WAYBILLS_URL)
        time.sleep(4)
    else:
        time.sleep(2)
    dismiss_chrome_password_popup()
    log(f"  URL перед созданием: {driver.current_url}")

    # --- ЭТАП 3: Создать ---
    log("ЭТАП 3: Открытие формы создания")
    create_btn = None
    for attempt in range(2):
        for xp in [
            "//button[.//span[normalize-space(text())='Создать накладную']]",
            "//button[.//span[normalize-space(text())='Создать']]",
        ]:
            try:
                btns = WebDriverWait(driver, 5).until(
                    lambda d: [b for b in d.find_elements(By.XPATH, xp) if b.is_displayed()])
                if btns:
                    create_btn = btns[0]
                    break
            except Exception:
                continue
        if create_btn:
            break
        log(f"  Кнопка создания не найдена (попытка {attempt+1}) — иду в список", "WARN")
        driver.get(WAYBILLS_URL)
        time.sleep(5)
        dismiss_chrome_password_popup()

    if not create_btn:
        log(f"  ⚠ Не удалось открыть форму создания. URL: {driver.current_url}", "WARN")
        shot("no_create_button")
        return

    js_click(create_btn)
    time.sleep(3)
    log("  ✓ Форма открыта", "PASS")

    # --- ЭТАП 4: Форма ---
    log("ЭТАП 4: Заполнение формы накладной")
    dismiss_chrome_password_popup()
    time.sleep(0.5)

    dogovor_ok = select_dogovor_sharipzhan()
    log(f"  Договор выбран: {dogovor_ok}")
    time.sleep(3)
    dismiss_chrome_password_popup()

    nds_ok = select_waybill_dropdown("Ставка НДС", allow_missing=True)
    workflow_result["nds_ok"] = bool(nds_ok)
    if not nds_ok:
        workflow_result["fail_reasons"][f"Ставка НДС: {NDS_SCENARIO}"] = (
            f"не удалось выбрать вариант '{NDS_SCENARIO}' в списке ставок НДС")
    time.sleep(0.4)

    form_mode_ok = select_radio_option("Режим формирования", FORM_MODE)
    workflow_result["form_mode_ok"] = bool(form_mode_ok)
    if not form_mode_ok:
        workflow_result["fail_reasons"][f"Режим формирования: {FORM_MODE}"] = (
            f"не удалось выбрать радиокнопку '{FORM_MODE}'")
    time.sleep(0.5)

    if PAPER_MODE:
        log("СЦЕНАРИЙ: 'Бумажное подписание' — включаю переключатель")
        set_toggle_state("Бумажное подписание", True)
        workflow_result["actions_done"].append("Сценарий: Бумажное подписание = ВКЛ")
        time.sleep(0.5)

    fill_text_field("номер накладной", WAYBILL_NUM, "Номер документа")
    time.sleep(0.3)
    select_waybill_dropdown("Очередь", allow_missing=True)
    time.sleep(0.3)
    select_waybill_dropdown("Блок", allow_missing=True)
    time.sleep(0.3)

    # --- ЭТАП 5: Материалы ---
    log("ЭТАП 5: Материалы")
    if fill_materials():
        workflow_result["materials"] = True
    else:
        workflow_result["fail_reasons"]["Заполнение материалов"] = (
            "не удалось заполнить кол-во и/или добавить материал из справочника")
    time.sleep(1)

    # --- ЭТАП 6: Создать накладную ---
    log("ЭТАП 6: Сохранение накладной")
    blur_focus()
    if click_create_button():
        time.sleep(4)
        new_url = driver.current_url
        if "/waybills/" in new_url and "/create" not in new_url:
            workflow_result["url"] = new_url
            workflow_result["created"] = True
            log(f"  ✓ Накладная создана: {new_url}", "PASS")

    if not workflow_result["created"]:
        workflow_result["fail_reasons"]["Создание документа"] = (
            "кнопка 'Создать' не сработала или URL не сменился на карточку накладной")
        log("Прерываю — накладная не создана", "FAIL")
        shot("not_created")
        return

    exit_edit_mode()
    time.sleep(2)
    dismiss_chrome_password_popup()
    clean_url = driver.current_url.replace("/edit", "").rstrip("/")
    workflow_result["url"] = clean_url
    log(f"  URL карточки: {clean_url}", "PASS")
    driver.get(clean_url)
    time.sleep(4)
    dismiss_chrome_password_popup()

    # --- ЭТАП 7: Маршрут согласования ---
    log("ЭТАП 7: Маршрут согласования (Margulan)")
    dismiss_chrome_password_popup()
    for retry in range(3):
        go_to_details_tab()
        dismiss_chrome_password_popup()
        time.sleep(1)
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
                if txt and "выбрать" not in txt.lower():
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
                    if (txt and txt not in {"—", "-"} and not low.isdigit()
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
        else:
            workflow_result["fail_reasons"]["Маршрут согласования"] = (
                "не удалось создать этап или выбрать согласующего в маршруте")
            try:
                for _ in range(4):
                    ActionChains(driver).send_keys(Keys.ESCAPE).perform()
                    time.sleep(0.5)
            except Exception:
                pass
            time.sleep(3)
    time.sleep(2)

    # --- ЭТАП 8: Подписанты ---
    log("ЭТАП 8: Подписанты (Заказчик=Бейсембаев, Контрагент=Алдажаров Диас)")
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
                time.sleep(0.5)
        except Exception:
            pass
        exit_edit_mode()
        go_to_details_tab()
        time.sleep(3)
    time.sleep(2)

    # --- ЭТАП 9: Отправить / Подписать и отправить (основной + ЭЦП/бумага) ---
    if PAPER_MODE:
        log("ЭТАП 9: 'Отправить' (бумажное подписание — NCALayer НЕ используется)")
    else:
        log("ЭТАП 9: 'Отправить' + NCALayer (основной аккаунт)")
    go_to_details_tab()
    time.sleep(2)
    for btn in ["Подписать и отправить", "Подписать", "Отправить"]:
        if click_card_action(btn):
            if PAPER_MODE:
                # В режиме бумажного подписания ЭЦП не нужен — просто
                # смотрим, что происходит после клика по кнопке.
                time.sleep(3)
                shot("paper_mode_after_send")
            else:
                signed = sign_with_ncalayer(password=NCA_PASSWORD, p12_path=MAIN_P12_PATH)
                if signed:
                    workflow_result["actions_done"].append("Основной: ЭЦП OK")
                    workflow_result["ecp_signed"] = True
                else:
                    workflow_result["fail_reasons"]["Подписание ЭЦП"] = (
                        "sign_with_ncalayer() вернул неуспех — см. лог NCALayer выше "
                        "(окно не появилось / пароль не введён / ИИН не совпал и т.п.)")
            time.sleep(8)
            status = get_current_status()
            log(f"  '{btn}' → статус: '{status}'", "PASS")
            workflow_result["actions_done"].append(f"{btn} → {status}")
            workflow_result["final_status"] = status
            if PAPER_MODE:
                # Успех сценария — документ реально продвинулся по
                # статусу БЕЗ участия NCALayer.
                workflow_result["ecp_signed"] = status is not None and status != "Черновик"
                if not workflow_result["ecp_signed"]:
                    workflow_result["fail_reasons"]["Бумажное подписание (без ЭЦП)"] = (
                        f"после отправки статус остался '{status}' — документ не продвинулся")
            break
    else:
        workflow_result["fail_reasons"][
            "Бумажное подписание (без ЭЦП)" if PAPER_MODE else "Подписание ЭЦП"
        ] = "кнопка 'Подписать и отправить'/'Подписать'/'Отправить' не найдена в шапке документа"

    # --- ЭТАП 10: Согласовать ---
    log("ЭТАП 10: 'Согласовать'")
    time.sleep(3)
    go_to_details_tab()
    time.sleep(2)
    for approve_btn in ["Согласовать", "Подтвердить согласование", "Утвердить"]:
        if click_card_action(approve_btn):
            time.sleep(5)
            status = get_current_status()
            log(f"  '{approve_btn}' → '{status}'", "PASS")
            workflow_result["actions_done"].append(f"{approve_btn} → {status}")
            workflow_result["final_status"] = status
            break

    # --- ЭТАП 11: Талгат подписывает (не применимо в режиме бумаги) ---
    if PAPER_MODE:
        log("ЭТАП 11: пропущен — при бумажном подписании ЭЦП второго подписанта не требуется")
    else:
        log("=" * 60)
        log("ЭТАП 11: Талгат Ерланович подписывает накладную (заказчик)")
        log("=" * 60)
        time.sleep(3)
        try:
            if sign_waybill_by_talgat(workflow_result["url"]):
                log("  ✓✓ Талгат подписал", "PASS")
            else:
                log("  ⚠ Талгат не подписал", "WARN")
        except Exception as e:
            log(f"  ⚠ Ошибка Талгата: {e}", "WARN")
            try:
                import traceback
                for tb in traceback.format_exc().split("\n"):
                    log(f"    {tb}")
            except Exception:
                pass
            shot("talgat_error")

    # --- ЭТАП 12: Итоги ---
    log("=" * 60)
    log("ИТОГИ (НАКЛАДНАЯ)")
    log("=" * 60)
    log(f"Сценарий: '{_scenario_key}' (PAPER_MODE={PAPER_MODE}, FORM_MODE={FORM_MODE}, НДС={NDS_SCENARIO})")
    log(f"Накладная: {WAYBILL_NUM}")
    log(f"URL: {workflow_result['url']}")
    log(f"Создана: {'✓' if workflow_result['created'] else '✗'}")
    log(f"Материалы: {'✓' if workflow_result['materials'] else '✗'}")
    log(f"Маршрут: {'✓' if workflow_result['route'] else '✗'}")
    log(f"Подписанты: {'✓' if workflow_result['signatories'] else '✗'}")
    if PAPER_MODE:
        log(f"Бумажное подписание (без ЭЦП): {'✓' if workflow_result['ecp_signed'] else '✗'}")
    else:
        log(f"Подписание ЭЦП: {'✓' if workflow_result['ecp_signed'] else '✗'}")
    if NDS_SCENARIO != "НДС 16%":
        log(f"Ставка НДС: {NDS_SCENARIO}: {'✓' if workflow_result['nds_ok'] else '✗'}")
    if FORM_MODE != "Произвольно":
        log(f"Режим формирования: {FORM_MODE}: {'✓' if workflow_result['form_mode_ok'] else '✗'}")
    log(f"Финальный статус: {workflow_result['final_status'] or 'Неизвестно'}")

    # Причины отказов — отдельным парсируемым форматом для
    # run_workflow_and_report.py: "[ПРИЧИНА] <Название проверки>: <текст>"
    for _reason_key, _reason_text in workflow_result["fail_reasons"].items():
        log(f"[ПРИЧИНА] {_reason_key}: {_reason_text}")

    for action in workflow_result["actions_done"]:
        log(f"  • {action}")


# ==========================================
# ЗАПУСК
# Без аргумента — прогоняются ВСЕ сценарии подряд, один за другим,
# в одном и том же браузере (по одной накладной на сценарий).
# С аргументом — только этот один сценарий, как раньше.
#     py waybill_workflow_new_design.py             → все 5 сценариев
#     py waybill_workflow_new_design.py paper_mode   → только один
# ==========================================
_scenarios_to_run = [sys.argv[1]] if len(sys.argv) > 1 else list(WAYBILL_SCENARIOS.keys())
_scenarios_to_run = [s for s in _scenarios_to_run if s in WAYBILL_SCENARIOS] or ["default"]

for _run_idx, _run_key in enumerate(_scenarios_to_run, 1):
    _apply_scenario(_run_key)
    log("#" * 60)
    log(f"СЦЕНАРИЙ {_run_idx}/{len(_scenarios_to_run)}: '{_run_key}'")
    log("#" * 60)
    try:
        main()
    except Exception as e:
        log(f"КРИТИЧЕСКАЯ ОШИБКА в сценарии '{_run_key}': {e}", "FAIL")
        try:
            import traceback
            for tb_line in traceback.format_exc().split("\n"):
                log(f"  {tb_line}")
        except Exception:
            pass
        try:
            shot(f"critical_error_{_run_key}")
        except Exception:
            pass

_safe_out("")
_safe_out("=" * 60)
_safe_out("ПОЛНЫЙ ЛОГ (НАКЛАДНАЯ):")
_safe_out("=" * 60)
for line in LOG_LINES:
    _safe_out(line)
_safe_out("=" * 60)
_safe_out(f"Файл лога: {LOG_FILE_PATH}")

try:
    if _LOG_FILE:
        _LOG_FILE.close()
except Exception:
    pass
