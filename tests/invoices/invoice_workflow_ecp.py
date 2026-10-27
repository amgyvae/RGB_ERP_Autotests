# -*- coding: utf-8 -*-
"""
ЗАЯВКА НА ОПЛАТУ (invoices) — ВАРИАНТ 1: ПОЛНОЕ ТЕСТИРОВАНИЕ С ЭЦП
(электронное подписание, НЕ бумажное).

Портированы все наработки из отлаженных скриптов договоров и накладных:
  • реальный UI-кит сайта: ui-select__*, action-modal__*,
    ui-date-picker__*, evd-route__*, detail-header, detail-right__tab
    (Ant Design на сайте НЕТ — старые ant-* селекторы не работают);
  • выбор опций КЛАВИАТУРОЙ (ArrowDown+Enter) — клики мышью этот
    ui-select игнорирует;
  • _hard_click с полной цепочкой pointer/mouse событий;
  • НИКАКИХ кликов по координатам экрана (pyautogui);
  • маршрут: «Добавить этап» → строка этапа → выбор согласующего →
    модалка «Согласующие: Этап N» → «Сохранить»;
  • действия статуса ищутся В ШАПКЕ документа, чтобы не нажать
    кнопку «Отправить» в панели обсуждения;
  • корректный выход из аккаунта (модалка подтверждения + флаг);
  • ensure_on_our_document — защита от работы с чужой заявкой;
  • даты через ui-date-picker с проверкой результата.

ФЛОУ: Логин → Список заявок → Создать → Форма → Предмет платежа →
Маршрут → На согласование → Согласовать → ПОДПИСАНИЕ ЭЦП (NCALayer) →
ПП → Оплачено → Загружено → Подтвердить.
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
# "пробуй способ 1 → не нашёл → способ 2" каждая неудачная попытка
# молча ждала до 3 секунд лишних. Явные ожидания (time.sleep/
# WebDriverWait) в коде расставлены сами, этого достаточно.
login_val = env("RGB_ACCOUNT1_LOGIN", "jyktmargyplay2@gmail.com")
pass_val = env("RGB_ACCOUNT1_PASSWORD", env("RGB_ACCOUNT1_PASSWORD_ALT", "12341234"))

# --- ЭЦП первого подписанта ---
NCA_PASSWORD = env("NCA_KEY1_PASSWORD")
MAIN_P12_PATH = env("NCA_KEY1_PATH", r"C:\Program Files\NCALayer\GOST2015_13-02-2026-18_04.p12")

# --- Аккаунт второй (Талгат Ерланович) ---
TALGAT_LOGIN = env("RGB_ACCOUNT3_LOGIN", env("RGB_ACCOUNT2_LOGIN"))
TALGAT_PASS = env("RGB_ACCOUNT3_PASSWORD", env("RGB_ACCOUNT2_PASSWORD"))
TALGAT_NCA_PASSWORD = env("NCA_KEY2_PASSWORD")
TALGAT_P12_PATH = env("NCA_KEY2_PATH", r"C:\Program Files\NCALayer\GOST512_b2c2008a1d14dd3f6a531597fb334afc4b3c6e76.p12")

BASE_URL = "https://testportal.rgbgroup.kz/"
CONTRACTS_URL = "https://testportal.rgbgroup.kz/documents/contracts"

BASE_URL = "https://testportal.rgbgroup.kz/"
INVOICES_URL = "https://testportal.rgbgroup.kz/documents/invoices"
WAIT = 15

# ==========================================
# ВЫБОР СЦЕНАРИЯ — можно прогнать ВСЕ 6 сценариев ОДНОЙ командой
# (по умолчанию), либо только один конкретный:
#     py invoice_workflow_ecp.py                → все сценарии подряд
#     py invoice_workflow_ecp.py "Предоплата (100%)" → только этот один
# ==========================================
PAYMENT_TYPE_SCENARIOS = [
    "Выдача наличных",
    "Постоплата",
    "Постоплата (под гарантию)",
    "Постоплата (под залог)",
    "Предоплата (100%)",
    "Частичные платежи",
]

PAYMENT_TYPE_SCENARIO = "Выдача наличных"  # актуальный сценарий текущего
                                            # прогона (переустанавливается
                                            # в цикле внизу файла)


def _apply_scenario(payment_type):
    """Переустанавливает сценарий и создаёт СВЕЖИЙ workflow_result —
    вызывается перед каждым прогоном main(), когда сценариев несколько
    подряд в одном запуске процесса."""
    global PAYMENT_TYPE_SCENARIO, INVOICE_NUM, workflow_result
    PAYMENT_TYPE_SCENARIO = payment_type
    tag = payment_type.replace(" ", "").replace("(", "").replace(")", "").replace("%", "пр")
    INVOICE_NUM = f"ЗАЯВКА-{tag}-{datetime.now().strftime('%d%m-%H%M%S')}"
    workflow_result = {
        "number": INVOICE_NUM,
        "url": None,
        "created": False,
        "subject": False,
        "route": False,
        "signed": False,
        "fail_reasons": {},
        "final_status": None,
        "actions_done": []
    }


# Инициализация "по умолчанию" — чтобы модуль парсился без ошибок ещё
# до цикла запуска внизу файла (там сценарий переустановится заново).
_apply_scenario("Выдача наличных")

LOG_FILE_PATH = log_path(f"invoice_log_{datetime.now().strftime('%d%m_%H%M%S')}.txt")
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
        path = screen_path(f"debug_invoice_{name}_{datetime.now().strftime('%H%M%S')}.png")
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


def fill_date_field(label, date_str):
    """Обёртка для дат на форме создания договора.

    ПЕРЕПИСАНО: раньше сначала перебирались устаревшие ant-picker
    селекторы и «геометрия», а в конце был фолбэк, который кликал
    ячейку 'today' — из-за него в карточку попадала СЕГОДНЯШНЯЯ дата
    вместо нужной (04.09 вместо +10 дней), и договор считался
    просроченным. Теперь основной (и подтверждённый DevTools) способ
    ui-date-picker идёт ПЕРВЫМ, а «кликнуть Сегодня» убрано совсем.
    """
    try:
        date_obj = datetime.strptime(date_str, "%d.%m.%Y")
    except Exception as e:
        log(f"  ⚠ {label}: некорректная дата '{date_str}' ({e})", "WARN")
        return False

    # 1. Основной способ — ui-date-picker (с проверкой результата)
    if fill_popup_date_field(label, date_obj):
        return True

    # 2. Запасной — обычный текстовый input рядом с лейблом
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
# ПОДПИСАНТЫ — Заказчик=Бейсембаев Куаныш, Контрагент=Алдажаров Диас Талгатович
# В новом дизайне секция "Подписанты" видна прямо на главной вкладке
# карточки договора (см. скрин 9) — карточки Заказчик/Контрагент с
# кнопкой "Редактировать" у заголовка секции. Логика внутри модалки
# редактирования, судя по всему, не поменялась (dropdown-поиск).
# ==========================================
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

        _click_option_robustly(target["element"], target["text"], panel=panel)
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
# НОВОЕ: универсальный переход между вкладками карточки договора
# (Обсуждение / Финансы / Акты и накладные / Заказы / Документы /
# Доп.соглашения / История / Общая информация)
# ==========================================
def go_to_tab(tab_name):
    for xp in [
        # ТОЧНЫЙ класс сайта (подтверждено инспектором): detail-right__tab
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


# ==========================================
# МАРШРУТ СОГЛАСОВАНИЯ — Margulan Sh (структура похожа на прежнюю,
# теперь видна прямо под "Спецификация..." на главной вкладке;
# добавились кнопки "Сменить маршрут" и "+ Этап" сверху таблицы)
# ==========================================
def add_approval_route(approver_query="Margulan"):
    """МАРШРУТ СОГЛАСОВАНИЯ — строгая последовательность (как просил
    пользователь):
        ШАГ 1: нажать «Добавить этап» (button.evd-empty-stub__action)
               или «+ Этап» (button.evd-route__add-badge)
        ШАГ 2: дождаться появления строки этапа с селектом
        ШАГ 3: открыть селект «Выбрать согласующего»
        ШАГ 4: найти и выбрать «Sh Margulan Ju»
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
            span.ui-select__option-label «Sh Margulan Ju»
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
             td.evd-route__td (см. скриншот: в таблице '1 | Margulan Sh')
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
                if txt and "выбрать" not in txt.lower():
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

    # ---------- ШАГ 4: найти и выбрать Sh Margulan ----------
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

    # ---------- ШАГ 4.5: подтвердить модалку «Согласующие: Этап N» ----------
    # После выбора открывается модалка (action-modal) со списком
    # выбранных согласующих и кнопками «Отмена» / «Сохранить».
    # Без нажатия «Сохранить» маршрут НЕ сохраняется и скрипт зависает
    # на этом экране (подтверждено скриншотом пользователя).
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
                        # успех = модалка закрылась
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
        time.sleep(2.5)
        modal = find_visible_modal_container(hint_text=button_text)
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
                    ca.send_keys(f"Автоподтверждение '{button_text}' для {INVOICE_NUM}")
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
# NCALayer (без изменений — внешнее приложение, дизайн сайта не влияет)
# ==========================================
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
        """Засчитываем успех ТОЛЬКО если перешли на карточку заявки
        (/invoices/<uuid>), а не на любой другой URL. Раньше любая
        смена адреса считалась успехом — из-за этого случайный переход
        (например, обратно в список или на чужой договор) принимался
        за 'договор создан'."""
        for _ in range(8):
            time.sleep(1)
            cur = driver.current_url
            if cur == initial_url:
                continue
            if "/invoices/" not in cur or "/create" in cur:
                continue
            tail = cur.rstrip("/").split("/invoices/")[-1].split("/")[0]
            # UUID карточки, а не пустой список
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
    _LOGOUT_IN_PROGRESS = False  # вход выполнен — защита снова активна
    log(f"  ✓ Успешный вход: {login_value}", "PASS")
    return True




# ==========================================
# TREE-SELECT ЛИСТ (для «Статьи расходов», если она деревом)
# ==========================================
def click_tree_leaf():
    """Разворачивает узлы дерева и кликает первый конечный лист.
    Используется, когда «Статья расходов» — не плоский список,
    а иерархическое дерево."""
    time.sleep(1.2)
    for _ in range(4):
        try:
            expanded = driver.execute_script("""
                var sw = document.querySelectorAll(
                    '.ui-tree__switcher, .ui-tree__toggle, ' +
                    '.ant-select-tree-switcher_close, .ant-select-tree-switcher-close');
                var c = 0;
                sw.forEach(function(s){ if (s.offsetParent !== null) { s.click(); c++; } });
                return c;
            """)
        except Exception:
            expanded = 0
        if not expanded:
            break
        time.sleep(0.6)

    time.sleep(0.4)
    leaves = driver.find_elements(
        By.XPATH,
        "//*[contains(@class,'ui-tree__leaf') or "
        "(@role='treeitem' and contains(@class,'leaf'))] | "
        "//div[@role='treeitem' and contains(@class,'ant-select-tree-treenode-leaf')]")
    vis = [l for l in leaves if l.is_displayed()]
    if not vis:
        return None

    target = vis[0]
    try:
        txt = (target.get_attribute("textContent") or "").strip()[:40]
    except Exception:
        txt = ""
    scroll_to(target)
    time.sleep(0.3)
    for method in ["hard", "actions", "selenium", "js"]:
        try:
            if method == "hard":
                _hard_click(target)
            elif method == "actions":
                ActionChains(driver).move_to_element(target).pause(0.2).click().perform()
            elif method == "selenium":
                target.click()
            else:
                js_click(target)
            time.sleep(1.0)
            open_trees = driver.find_elements(
                By.XPATH, "//*[contains(@class,'ui-tree') or "
                          "contains(@class,'ant-select-tree-list')]")
            if not any(t.is_displayed() for t in open_trees):
                return txt
        except Exception:
            continue
    return txt or None


# ==========================================
# НАВИГАЦИЯ / ЗАЩИТА
# ==========================================
def ensure_on_our_document(context=""):
    """Защита от ухода на чужую заявку: сверяет UUID в URL."""
    target = workflow_result.get("url")
    if not target:
        return False
    try:
        target_id = target.rstrip("/").split("/invoices/")[-1].split("/")[0]
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


# ==========================================
# ВЫБОР В ui-select ФОРМЫ ЗАЯВКИ
# ==========================================
def select_invoice_dropdown(label, allow_missing=False, target_option=None):
    """Заказчик → AI Group, Контрагент → ИП Алдажаров,
    Ставка НДС → 16%, остальные → первый доступный."""
    if "Заказчик" in label:
        target_option = "AI Group"
    elif "Контрагент" in label:
        target_option = "ИП Алдажаров"

    trigger = find_ui_kit_trigger_near_label(label)
    if not trigger:
        if not allow_missing:
            log(f"  ⚠ {label}: поле не найдено", "WARN")
            dump_field_html(label)
        return None

    scroll_to(trigger)
    time.sleep(0.25)

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
            time.sleep(0.85)
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

    # если есть поиск — фильтруем по целевому значению
    if target_option:
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
            sinp.send_keys(target_option.split()[0])
            time.sleep(1.2)
        except Exception:
            pass

    opts = panel_options()
    if not opts:
        try:
            sinp = panel.find_element(
                By.XPATH, ".//input[contains(@class,'ui-select__search-input')]")
            sinp.send_keys(Keys.CONTROL + "a")
            sinp.send_keys(Keys.BACKSPACE)
            time.sleep(1.0)
        except Exception:
            pass
        opts = panel_options()

    if not opts:
        log(f"  ⚠ {label}: опции не найдены", "WARN")
        _close_any_ui_select_panel()
        return None

    picked = None
    if "НДС" in label:
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
    if not picked and ("Контрагент" in label or "Заказчик" in label or (label == "Получатель" and target)):
        raise RuntimeError(f'{label}: компания {target_option!r} не найдена')
    if not picked:
        picked = opts[0]

    _click_option_robustly(picked["element"], picked["text"], panel=panel)
    time.sleep(0.7)
    _close_any_ui_select_panel()
    log(f"  ✓ {label}: '{picked['text'][:40]}'", "PASS")
    return "Success"


def ensure_electronic_signing():
    """ВАРИАНТ С ЭЦП: тумблер «Бумажное подписание» должен быть ВЫКЛЮЧЕН.
    Если он включён — документ подписывается сканом, и NCALayer не
    вызывается. Проверяем и при необходимости выключаем."""
    try:
        toggles = driver.find_elements(
            By.XPATH,
            "//*[contains(text(),'Бумажное подписание')]"
            "/ancestor::*[self::div][1]//button[@role='switch' "
            "or contains(@class,'switch') or contains(@class,'toggle')] | "
            "//*[contains(text(),'Бумажное подписание')]"
            "/following::button[@role='switch' or contains(@class,'switch') "
            "or contains(@class,'toggle')][1]")
        vis = [t for t in toggles if t.is_displayed()]
        if not vis:
            log("  • Тумблер 'Бумажное подписание' не найден "
                "(вероятно, его нет в заявке) — продолжаю электронно")
            return True
        tg = vis[0]
        checked = (tg.get_attribute("aria-checked") == "true") or \
                  ("checked" in (tg.get_attribute("class") or "").lower())
        if checked:
            log("  Бумажное подписание ВКЛЮЧЕНО — выключаю (нужен ЭЦП)")
            _hard_click(tg)
            time.sleep(0.6)
            checked_after = (tg.get_attribute("aria-checked") == "true")
            if checked_after:
                log("  ⚠ Не удалось выключить бумажное подписание", "WARN")
                return False
            log("  ✓ Бумажное подписание выключено — режим ЭЦП", "PASS")
        else:
            log("  ✓ Бумажное подписание выключено (режим ЭЦП)", "PASS")
        return True
    except Exception as e:
        log(f"  ⚠ Проверка режима подписания: {e}", "WARN")
        return True


# ==========================================
# PDF ДЛЯ ВЛОЖЕНИЙ
# ==========================================
def create_test_pdf(suffix="doc"):
    try:
        import tempfile
        tmpdir = tempfile.gettempdir()
        path = os.path.join(tmpdir, f"invoice_{suffix}_{datetime.now().strftime('%H%M%S')}.pdf")
        pdf = b"""%PDF-1.4
1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj
2 0 obj<</Type/Pages/Count 1/Kids[3 0 R]>>endobj
3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]/Contents 4 0 R/Resources<</Font<</F1 5 0 R>>>>>>endobj
4 0 obj<</Length 60>>stream
BT /F1 18 Tf 100 700 Td (Invoice Document RPA) Tj ET
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
        log(f"    PDF создан: {path}")
        return path
    except Exception as e:
        log(f"    ⚠ Ошибка PDF: {e}", "WARN")
        return None




# ==========================================
# СОЗДАНИЕ ЗАЯВКИ — ЧЕРЕЗ МОДАЛКУ (подтверждено скриншотами)
# ==========================================
def create_invoice_via_modal():
    """ВАЖНО: заявка создаётся НЕ на отдельной странице, а в МОДАЛКЕ
    «Создание заявки на оплату» (открывается кнопкой «Создать заявку»
    в списке). Именно поэтому прежняя версия «стояла» — она искала
    страницу формы и кнопку «Создать» в шапке.

    Поля модалки (по скриншоту):
      Инициатор*              — авто (Sh Margulan Ju), disabled
      Ответственный за оплату*
      Тип оплаты*             → «Выдача наличных»
      Заказчик*               → AI Group
      Контрагент* ЛИБО «Выдать сотруднику»* — поле МЕНЯЕТСЯ от типа
                              оплаты: при «Выдача наличных» вместо
                              Контрагента появляется «Выдать сотруднику»
      Проект*, Очередь, Блок, Валюта* (KZT), Наблюдатели
      Футер: «Отмена» / «Создать»
    """
    log("  Открываю модалку создания заявки...")

    modal = None
    for _ in range(8):
        modal = find_visible_modal_container(hint_text="Создание заявки")
        if modal:
            break
        time.sleep(0.7)

    if not modal:
        log("  ⚠ Модалка 'Создание заявки на оплату' не открылась", "WARN")
        shot("no_create_modal")
        return False
    log("  ✓ Модалка создания открыта", "PASS")

    def pick_in_modal(label, target=None, required=True):
        trigger = None
        try:
            lbl = modal.find_element(
                By.XPATH, ".//*[normalize-space(text())='" + label + "']")
            for hint in UI_KIT_TRIGGER_CLASS_HINTS:
                try:
                    cand = lbl.find_element(
                        By.XPATH, "following::*[contains(@class,'" + hint + "')][1]")
                    if cand.is_displayed():
                        trigger = cand
                        break
                except Exception:
                    continue
        except Exception:
            pass

        if not trigger:
            if required:
                log("    ⚠ " + label + ": поле не найдено в модалке", "WARN")
            return False

        try:
            cur = (trigger.get_attribute("textContent") or "").strip()
            if cur and "выбер" not in cur.lower():
                log("    • " + label + ": уже заполнено ('" + cur[:30] + "')")
                return True
        except Exception:
            pass

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
                time.sleep(0.85)
                panels = driver.find_elements(
                    By.XPATH, "//div[contains(@class,'ui-select__panel')]")
                vis = [p for p in panels if p.is_displayed()]
                if vis:
                    panel = vis[-1]
                    break
            except Exception:
                continue

        if not panel:
            log("    ⚠ " + label + ": список не открылся", "WARN")
            return False

        def opts_of(p):
            out = []
            try:
                for b in p.find_elements(By.XPATH, ".//button[@role='option']"):
                    if not b.is_displayed():
                        continue
                    try:
                        lb = b.find_element(
                            By.XPATH, ".//span[contains(@class,'ui-select__option-label')]")
                        t = (lb.get_attribute("textContent") or "").strip()
                    except Exception:
                        t = (b.get_attribute("textContent") or "").strip()
                    if t:
                        out.append({"element": b, "text": t})
            except Exception:
                pass
            return out

        if target:
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
                sinp.send_keys(target.split()[0])
                time.sleep(1.2)
            except Exception:
                pass

        options = opts_of(panel)
        if not options:
            try:
                sinp = panel.find_element(
                    By.XPATH, ".//input[contains(@class,'ui-select__search-input')]")
                sinp.send_keys(Keys.CONTROL + "a")
                sinp.send_keys(Keys.BACKSPACE)
                time.sleep(1.0)
            except Exception:
                pass
            options = opts_of(panel)

        if not options:
            log("    ⚠ " + label + ": опции не найдены", "WARN")
            _close_any_ui_select_panel()
            return False

        picked = None
        if target:
            for o in options:
                if target.lower() in o["text"].lower():
                    picked = o
                    break
        if not picked and ("Контрагент" in label or "Заказчик" in label or (label == "Получатель" and target)):
            raise RuntimeError(f'{label}: компания {target!r} не найдена')
        if not picked:
            picked = options[0]

        _click_option_robustly(picked["element"], picked["text"], panel=panel)
        time.sleep(0.6)
        _close_any_ui_select_panel()
        log("    ✓ " + label + ": '" + picked["text"][:35] + "'", "PASS")
        return True

    pick_in_modal("Ответственный за оплату")
    time.sleep(0.3)
    pick_in_modal("Тип оплаты", target=PAYMENT_TYPE_SCENARIO)
    time.sleep(0.8)
    pick_in_modal("Заказчик", target="AI Group")
    time.sleep(0.3)
    # ВАЖНО: поле "Получатель" — обязательное (со звёздочкой в форме),
    # но раньше не заполнялось вообще, из-за чего кнопка "Создать"
    # оставалась неактивной. Старые варианты "Выдать сотруднику"/
    # "Контрагент" оставлены как запасные — похоже на устаревшие
    # названия того же поля в предыдущей версии формы.
    if not pick_in_modal("Получатель", target="ИП Алдажаров", required=False):
        if not pick_in_modal("Выдать сотруднику", required=False):
            pick_in_modal("Контрагент", target="ИП Алдажаров", required=False)
    time.sleep(0.3)
    pick_in_modal("Проект")
    time.sleep(0.3)
    pick_in_modal("Очередь", required=False)
    time.sleep(0.3)
    pick_in_modal("Блок", required=False)
    time.sleep(0.3)
    pick_in_modal("Наблюдатели", required=False)
    time.sleep(0.3)

    blur_focus()
    time.sleep(0.6)

    create_btn = find_modal_button(modal, ["Создать"])
    if not create_btn:
        create_btn = find_modal_button(None, ["Создать"])
    if not create_btn:
        workflow_result["fail_reasons"]["Создание документа"] = (
            "кнопка 'Создать' в модалке не найдена/недоступна — вероятно, "
            "не заполнено одно из обязательных полей (Получатель/Проект/Заказчик и т.п.)")
        log("  ⚠ Кнопка 'Создать' в модалке не найдена", "WARN")
        shot("no_modal_create_btn")
        return False

    for method in ["hard", "js", "selenium", "actions"]:
        try:
            if method == "hard":
                _hard_click(create_btn)
            elif method == "js":
                js_click(create_btn)
            elif method == "selenium":
                create_btn.click()
            else:
                ActionChains(driver).move_to_element(create_btn).pause(0.3).click().perform()
            log("  Клик 'Создать' (" + method + ")")
            for _ in range(10):
                time.sleep(1)
                cur = driver.current_url
                if "/invoices/" in cur and "/create" not in cur:
                    tail = cur.rstrip("/").split("/invoices/")[-1].split("/")[0]
                    if len(tail) >= 8:
                        workflow_result["url"] = cur
                        workflow_result["created"] = True
                        log("  ✓ Заявка создана: " + cur, "PASS")
                        return True
                if not find_visible_modal_container(hint_text="Создание заявки"):
                    log("  • Модалка закрылась — ищу созданную заявку в списке")
                    break
            if workflow_result["created"]:
                return True
        except Exception:
            continue

    try:
        time.sleep(2)
        rows = driver.find_elements(
            By.XPATH, "//table//tbody//tr[1]//a | //table//tbody//tr[1]")
        vis = [r for r in rows if r.is_displayed()]
        if vis:
            _hard_click(vis[0])
            time.sleep(4)
            cur = driver.current_url
            if "/invoices/" in cur and "/create" not in cur:
                tail = cur.rstrip("/").split("/invoices/")[-1].split("/")[0]
                if len(tail) >= 8:
                    workflow_result["url"] = cur
                    workflow_result["created"] = True
                    log("  ✓ Открыта созданная заявка: " + cur, "PASS")
                    return True
    except Exception as e:
        log("  ⚠ Открытие созданной заявки: " + str(e), "WARN")

    log("  ⚠ Не удалось подтвердить создание заявки", "WARN")
    shot("create_not_confirmed")
    return False

# ==========================================
# ПРЕДМЕТ ПЛАТЕЖА
# ==========================================
def add_payment_subject():
    """ПРЕДМЕТ ПЛАТЕЖА — путь подтверждён скриншотами:
      1) в ШАПКЕ заявки кнопка «Добавить предмет» (именно так, БЕЗ
         слова «платежа») → переход на отдельную страницу
         /invoices/<uuid>/subjects «Предметы платежа»;
      2) на этой странице кнопка «Добавить предмет» справа сверху →
         открывается МОДАЛКА «Добавить предмет платежа»;
      3) поля модалки:
           Договор           — часто disabled («Сначала укажите
                               контрагента в реквизитах заявки») → пропускаем
           Описание*         — textarea
           Ставка НДС        — обычно уже «НДС 16%»
           Сумма без НДС*    — число (Сумма с НДС считается сама)
           Номер счёта*      — текст
           Дата счёта*       — ui-date-picker («Выбрать дату»)
           Статья расходов*  — ui-select
           Тип*              — ui-select
           Файлы счёта / Вложения — input[type=file] (ниже по скроллу)
         Футер: «Отмена» / «Добавить»
      4) возврат по ссылке «Вернуться к основной информации».
    """
    exit_edit_mode()
    ensure_on_our_document("add_payment_subject")

    # ---------- ШАГ 1: переход на страницу предметов ----------
    on_subjects = "/subjects" in driver.current_url
    if not on_subjects:
        head_btn = None
        for xp in [
            "//button[.//span[normalize-space(text())='Добавить предмет']]",
            "//button[contains(normalize-space(.),'Добавить предмет')]",
            "//*[self::a or self::button][contains(normalize-space(.),'Предмет')]",
        ]:
            els = driver.find_elements(By.XPATH, xp)
            vis = [b for b in els if b.is_displayed() and b.is_enabled()]
            if vis:
                head_btn = vis[0]
                break

        if head_btn:
            scroll_to(head_btn)
            time.sleep(0.3)
            _hard_click(head_btn)
            time.sleep(2.5)
            on_subjects = "/subjects" in driver.current_url
        if not on_subjects:
            # прямой переход по URL как надёжный запасной путь
            base = (workflow_result.get("url") or driver.current_url).rstrip("/")
            base = base.replace("/subjects", "")
            try:
                driver.get(base + "/subjects")
                time.sleep(3.5)
                on_subjects = "/subjects" in driver.current_url
            except Exception:
                pass

    if not on_subjects:
        log("  ⚠ Не удалось перейти на страницу предметов платежа", "WARN")
        shot("no_subjects_page")
        return False
    log("  ✓ Страница 'Предметы платежа' открыта", "PASS")
    dismiss_chrome_password_popup()

    # ---------- ШАГ 2: кнопка «Добавить предмет» на странице ----------
    add_btn = None
    for xp in [
        "//button[.//span[normalize-space(text())='Добавить предмет']]",
        "//button[contains(normalize-space(.),'Добавить предмет')]",
        "//button[.//span[normalize-space(text())='Добавить']]",
    ]:
        els = driver.find_elements(By.XPATH, xp)
        vis = [b for b in els if b.is_displayed() and b.is_enabled()]
        if vis:
            add_btn = vis[-1]
            break

    if not add_btn:
        log("  ⚠ Кнопка 'Добавить предмет' на странице не найдена", "WARN")
        shot("no_add_subject_btn")
        return False

    scroll_to(add_btn)
    time.sleep(0.3)
    _hard_click(add_btn)
    time.sleep(2.2)

    modal = None
    for _ in range(7):
        modal = find_visible_modal_container(hint_text="предмет платежа")
        if modal:
            break
        time.sleep(0.6)

    if not modal:
        log("  ⚠ Модалка 'Добавить предмет платежа' не открылась", "WARN")
        shot("no_subject_modal")
        return False
    log("  ✓ Модалка 'Добавить предмет платежа' открыта", "PASS")

    # ---------- ШАГ 3: заполнение ----------
    # Описание* (textarea)
    try:
        ta = None
        for xp in [
            ".//*[contains(text(),'Описание')]/following::textarea[1]",
            ".//textarea[contains(@placeholder,'писание')]",
            ".//textarea",
        ]:
            els = modal.find_elements(By.XPATH, xp)
            vis = [t for t in els if t.is_displayed() and t.is_enabled()]
            if vis:
                ta = vis[0]
                break
        if ta:
            ta.clear()
            ta.send_keys(f"Оплата по заявке {INVOICE_NUM} (RPA)")
            log("    ✓ Описание заполнено", "PASS")
        else:
            log("    ⚠ Поле 'Описание' не найдено", "WARN")
    except Exception as e:
        log(f"    ⚠ Описание: {e}", "WARN")

    # Ставка НДС — оставляем, если уже 16%
    try:
        nds = find_dropdown_in_scope(modal, "Ставка НДС")
        if nds:
            cur = (nds.get_attribute("textContent") or "").strip()
            if "16" in cur:
                log("    • Ставка НДС уже 16%")
            else:
                _hard_click(nds)
                time.sleep(0.8)
                panels = driver.find_elements(
                    By.XPATH, "//div[contains(@class,'ui-select__panel')]")
                vp = [p for p in panels if p.is_displayed()]
                if vp:
                    p = vp[-1]
                    opts = []
                    for b in p.find_elements(By.XPATH, ".//button[@role='option']"):
                        if b.is_displayed():
                            t = (b.get_attribute("textContent") or "").strip()
                            if t:
                                opts.append({"element": b, "text": t})
                    pick = None
                    for o in opts:
                        if "16" in o["text"]:
                            pick = o
                            break
                    if not pick and opts:
                        pick = opts[0]
                    if pick:
                        _click_option_robustly(pick["element"], pick["text"], panel=p)
                        log(f"    ✓ Ставка НДС: '{pick['text'][:20]}'", "PASS")
                    _close_any_ui_select_panel()
    except Exception as e:
        log(f"    ⚠ Ставка НДС: {e}", "WARN")

    # Сумма без НДС*
    try:
        s = None
        for xp in [
            ".//*[contains(text(),'Сумма без НДС')]/following::input[1]",
            ".//input[@type='number'][1]",
        ]:
            els = modal.find_elements(By.XPATH, xp)
            vis = [i for i in els if i.is_displayed() and i.is_enabled()]
            if vis:
                s = vis[0]
                break
        if s:
            set_number_native(s, "5000")
            log("    ✓ Сумма без НДС: 5000", "PASS")
        else:
            log("    ⚠ Поле 'Сумма без НДС' не найдено", "WARN")
    except Exception as e:
        log(f"    ⚠ Сумма без НДС: {e}", "WARN")

    # Номер счёта*
    try:
        n = None
        for xp in [
            ".//*[contains(text(),'Номер счёта') or contains(text(),'Номер счета')]"
            "/following::input[1]",
            ".//input[contains(@placeholder,'Номер')]",
        ]:
            els = modal.find_elements(By.XPATH, xp)
            vis = [i for i in els if i.is_displayed() and i.is_enabled()]
            if vis:
                n = vis[0]
                break
        if n:
            n.clear()
            n.send_keys(f"СЧ-{datetime.now().strftime('%d%m%H%M')}")
            log("    ✓ Номер счёта заполнен", "PASS")
        else:
            log("    ⚠ Поле 'Номер счёта' не найдено", "WARN")
    except Exception as e:
        log(f"    ⚠ Номер счёта: {e}", "WARN")

    # Дата счёта* — ui-date-picker
    try:
        fill_popup_date_field("Дата счёта", datetime.now(), modal=modal)
    except Exception as e:
        log(f"    ⚠ Дата счёта: {e}", "WARN")

    # Статья расходов* и Тип*
    for field in ["Статья расходов", "Тип"]:
        try:
            # прокручиваем модалку, чтобы поле стало видимым
            try:
                driver.execute_script(
                    "arguments[0].scrollTop = arguments[0].scrollTop + 220;", modal)
                time.sleep(0.3)
            except Exception:
                pass

            sel = find_dropdown_in_scope(modal, field)
            if not sel:
                log(f"    ⚠ {field}: контрол не найден", "WARN")
                continue
            cur = (sel.get_attribute("textContent") or "").strip().lower()
            if cur and "выбер" not in cur:
                log(f"    • {field}: уже заполнено")
                continue

            _hard_click(sel)
            time.sleep(0.9)
            panels = driver.find_elements(
                By.XPATH, "//div[contains(@class,'ui-select__panel')]")
            vp = [p for p in panels if p.is_displayed()]
            if not vp:
                leaf = click_tree_leaf()
                if leaf:
                    log(f"    ✓ {field} (tree): '{leaf[:30]}'", "PASS")
                continue
            p = vp[-1]
            opts = []
            for b in p.find_elements(By.XPATH, ".//button[@role='option']"):
                if b.is_displayed():
                    t = (b.get_attribute("textContent") or "").strip()
                    if t:
                        opts.append({"element": b, "text": t})
            if opts:
                _click_option_robustly(opts[0]["element"], opts[0]["text"], panel=p)
                log(f"    ✓ {field}: '{opts[0]['text'][:30]}'", "PASS")
            else:
                log(f"    ⚠ {field}: опции не найдены", "WARN")
            _close_any_ui_select_panel()
        except Exception as e:
            log(f"    ⚠ {field}: {e}", "WARN")

    # Файлы счёта / Вложения
    try:
        pdf_invoice = create_test_pdf("schet")
        pdf_attach = create_test_pdf("attach")
        try:
            driver.execute_script(
                "arguments[0].scrollTop = arguments[0].scrollHeight;", modal)
            time.sleep(0.4)
        except Exception:
            pass
        file_inputs = modal.find_elements(By.XPATH, ".//input[@type='file']")
        log(f"    Файловых input в модалке: {len(file_inputs)}")
        for idx, pdf in [(0, pdf_invoice), (1, pdf_attach)]:
            if idx < len(file_inputs) and pdf:
                try:
                    driver.execute_script(
                        "arguments[0].style.display='block';"
                        "arguments[0].style.opacity='1';"
                        "arguments[0].style.visibility='visible';"
                        "arguments[0].removeAttribute('hidden');",
                        file_inputs[idx])
                    file_inputs[idx].send_keys(pdf)
                    time.sleep(3)
                    log(f"    ✓ Файл #{idx+1} загружен", "PASS")
                except Exception as e:
                    log(f"    ⚠ Файл #{idx+1}: {e}", "WARN")
    except Exception as e:
        log(f"    ⚠ Загрузка файлов: {e}", "WARN")

    blur_focus()
    time.sleep(0.8)

    # ---------- ШАГ 4: кнопка «Добавить» ----------
    save_btn = find_modal_button(modal, ["Добавить", "Сохранить"])
    if not save_btn:
        save_btn = find_modal_button(None, ["Добавить", "Сохранить"])
    if not save_btn:
        log("  ⚠ Кнопка 'Добавить' в модалке не найдена", "WARN")
        shot("no_subject_save_btn")
        return False

    for method in ["hard", "js", "selenium", "actions"]:
        try:
            if method == "hard":
                _hard_click(save_btn)
            elif method == "js":
                js_click(save_btn)
            elif method == "selenium":
                save_btn.click()
            else:
                ActionChains(driver).move_to_element(save_btn).pause(0.3).click().perform()
            time.sleep(2.5)
            if not find_visible_modal_container(hint_text="предмет платежа"):
                log("  ✓ Предмет платежа добавлен", "PASS")
                # возврат к основной информации
                try:
                    backs = driver.find_elements(
                        By.XPATH,
                        "//*[self::a or self::button]"
                        "[contains(normalize-space(.),'Вернуться к основной информации')]")
                    vb = [b for b in backs if b.is_displayed()]
                    if vb:
                        _hard_click(vb[0])
                        time.sleep(2.5)
                        log("  ✓ Возврат к основной информации", "PASS")
                except Exception:
                    pass
                return True
        except Exception:
            continue

    log("  ⚠ Модалка не закрылась — вероятно, не все обязательные поля", "WARN")
    shot("subject_modal_still_open")
    try:
        ActionChains(driver).send_keys(Keys.ESCAPE).perform()
    except Exception:
        pass
    return False




# ==========================================
# ПЛАТЁЖНОЕ ПОРУЧЕНИЕ
# ==========================================
def add_payment_order():
    """Модалка «Платёжное поручение»: Номер, Дата, файл → «Сохранить»."""
    exit_edit_mode()
    ensure_on_our_document("add_payment_order")
    log("  Добавление платёжного поручения (ПП)...")

    pp_btn = None
    for xp in [
        "//button[.//span[normalize-space(text())='Добавить ПП']]",
        "//button[contains(normalize-space(.),'Добавить ПП')]",
    ]:
        els = driver.find_elements(By.XPATH, xp)
        vis = [b for b in els if b.is_displayed() and b.is_enabled()]
        if vis:
            pp_btn = vis[0]
            break

    if not pp_btn:
        log("  ⚠ Кнопка 'Добавить ПП' не найдена", "WARN")
        shot("no_add_pp_btn")
        return False

    scroll_to(pp_btn)
    time.sleep(0.4)
    _hard_click(pp_btn)
    time.sleep(2.2)

    modal = None
    for _ in range(6):
        modal = find_visible_modal_container(hint_text="платёжное поручение") or \
                find_visible_modal_container(hint_text="платежное поручение")
        if modal:
            break
        time.sleep(0.6)

    if not modal:
        log("  ⚠ Модалка ПП не открылась", "WARN")
        shot("no_pp_modal")
        return False
    log("  ✓ Модалка 'Платёжное поручение' открыта", "PASS")

    try:
        n = None
        try:
            n = modal.find_element(
                By.XPATH,
                ".//*[contains(text(),'Номер платёжного поручения') "
                "or contains(text(),'Номер платежного')]/following::input[1]")
        except Exception:
            n = modal.find_element(By.XPATH, ".//input[not(@type='file')][1]")
        n.clear()
        n.send_keys(f"ПП-{datetime.now().strftime('%d%m%H%M')}")
        log("    ✓ Номер ПП заполнен", "PASS")
    except Exception as e:
        log(f"    ⚠ Номер ПП: {e}", "WARN")

    try:
        fill_popup_date_field("Дата платёжного поручения", datetime.now(), modal=modal)
    except Exception:
        try:
            fill_popup_date_field("Дата", datetime.now(), modal=modal)
        except Exception as e:
            log(f"    ⚠ Дата ПП: {e}", "WARN")

    try:
        pp_pdf = create_test_pdf("pp")
        finputs = modal.find_elements(By.XPATH, ".//input[@type='file']")
        if finputs and pp_pdf:
            driver.execute_script(
                "arguments[0].style.display='block';"
                "arguments[0].style.opacity='1';"
                "arguments[0].style.visibility='visible';"
                "arguments[0].removeAttribute('hidden');",
                finputs[-1])
            finputs[-1].send_keys(pp_pdf)
            time.sleep(3)
            log("    ✓ Файл ПП загружен", "PASS")
    except Exception as e:
        log(f"    ⚠ Файл ПП: {e}", "WARN")

    blur_focus()
    time.sleep(0.8)

    save_btn = find_modal_button(modal, ["Сохранить", "Добавить"]) or \
               find_modal_button(None, ["Сохранить", "Добавить"])
    if not save_btn:
        log("  ⚠ Кнопка 'Сохранить' в модалке ПП не найдена", "WARN")
        return False

    for method in ["hard", "js", "selenium"]:
        try:
            if method == "hard":
                _hard_click(save_btn)
            elif method == "js":
                js_click(save_btn)
            else:
                save_btn.click()
            time.sleep(2.5)
            if not (find_visible_modal_container(hint_text="платёжное поручение") or
                    find_visible_modal_container(hint_text="платежное поручение")):
                log("  ✓ ПП сохранено", "PASS")
                return True
        except Exception:
            continue
    log("  ⚠ Модалка ПП не закрылась", "WARN")
    return False


# ==========================================
# ПОДПИСАНИЕ ЭЦП (вариант 1 — электронный)
# ==========================================
def sign_invoice_with_ecp():
    """Ищет кнопку подписания в ШАПКЕ заявки и подписывает через
    NCALayer основным сертификатом (GOST2015)."""
    ensure_on_our_document("sign_invoice")
    go_to_details_tab()
    time.sleep(1.5)

    for btn in ["Подписать и отправить", "Подписать", "Подписать ЭЦП"]:
        if click_card_action(btn):
            log(f"  Нажата '{btn}', жду NCALayer...")
            ok = sign_with_ncalayer(password=NCA_PASSWORD, p12_path=MAIN_P12_PATH)
            if ok:
                workflow_result["signed"] = True
                workflow_result["actions_done"].append("ЭЦП основного аккаунта: OK")
                log("  ✓ Заявка подписана ЭЦП", "PASS")
            else:
                log("  ⚠ Подписание ЭЦП не завершилось", "WARN")
            time.sleep(8)
            status = get_current_status()
            log(f"  '{btn}' → статус: '{status}'", "PASS" if ok else "WARN")
            workflow_result["actions_done"].append(f"{btn} → {status}")
            workflow_result["final_status"] = status
            return ok

    log("  • Кнопка подписания в шапке не найдена — возможно, для "
        "заявки ЭЦП не требуется на этом статусе", "WARN")
    shot("no_sign_button_invoice")
    return False


def click_header_button(button_texts, with_modal=True):
    """Клик по кнопке в шапке заявки (Оплачено / Загружено / Подтвердить)
    с обработкой модалки подтверждения. Использует click_card_action,
    который ищет кнопки строго в шапке (не в панели обсуждения)."""
    if isinstance(button_texts, str):
        button_texts = [button_texts]
    for bt in button_texts:
        if click_card_action(bt):
            time.sleep(3)
            status = get_current_status()
            log(f"  '{bt}' → статус: '{status}'", "PASS")
            workflow_result["actions_done"].append(f"{bt} → {status}")
            workflow_result["final_status"] = status
            return True
    log(f"  ⚠ Кнопка {button_texts} не найдена/не активна", "WARN")
    shot(f"no_btn_{button_texts[0]}")
    return False



# ==========================================
# ГЛАВНЫЙ WORKFLOW — ВАРИАНТ 1: С ЭЦП
# ==========================================
def main():
    log("=" * 60)
    log(f"ЗАЯВКА НА ОПЛАТУ (с ЭЦП): {INVOICE_NUM}")
    log("=" * 60)

    # --- ЭТАП 1: Логин ---
    log("ЭТАП 1: Логин")
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
        pw = None
        for xp in ["//input[@type='password']", "//input[contains(@placeholder,'ароль')]"]:
            try:
                fields = driver.find_elements(By.XPATH, xp)
                vis = [f for f in fields if f.is_displayed() and f.is_enabled()]
                if vis:
                    pw = vis[0]
                    break
            except Exception:
                continue
        if pw:
            try:
                pw.clear()
                pw.send_keys(pass_val)
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

    # --- ЭТАП 2: Заявки на оплату ---
    # URL КАРТОЧКИ тоже содержит '/documents/invoices', поэтому проверка
    # «содержит подстроку» ошибочно считала карточку списком.
    log("ЭТАП 2: Переход в 'Заявки на оплату'")

    def on_invoices_list():
        cur = driver.current_url
        if "/documents/invoices" not in cur:
            return False
        tail = cur.split("/documents/invoices", 1)[1].strip("/")
        return tail == "" or tail.startswith("?")

    if not on_invoices_list():
        log(f"  Текущий URL не список заявок ({driver.current_url}) — перехожу")
        driver.get(INVOICES_URL)
        time.sleep(4)
    else:
        time.sleep(2)
    dismiss_chrome_password_popup()
    log(f"  URL перед созданием: {driver.current_url}")

    # --- ЭТАП 3: Создать заявку (МОДАЛКА) ---
    # Кнопка в списке называется «Создать заявку» и открывает МОДАЛКУ
    # «Создание заявки на оплату» (не отдельную страницу).
    log("ЭТАП 3: Открытие модалки создания заявки")
    create_btn = None
    for attempt in range(2):
        for xp in [
            "//button[.//span[normalize-space(text())='Создать заявку']]",
            "//button[contains(normalize-space(.),'Создать заявку')]",
            "//button[.//span[normalize-space(text())='Создать']]",
        ]:
            els = driver.find_elements(By.XPATH, xp)
            vis = [b for b in els if b.is_displayed() and b.is_enabled()]
            if vis:
                create_btn = vis[0]
                break
        if create_btn:
            break
        log(f"  Кнопка 'Создать заявку' не найдена (попытка {attempt+1})", "WARN")
        driver.get(INVOICES_URL)
        time.sleep(5)
        dismiss_chrome_password_popup()

    if not create_btn:
        log(f"  ⚠ Не удалось открыть создание. URL: {driver.current_url}", "WARN")
        shot("no_create_button")
        return

    _hard_click(create_btn)
    time.sleep(2.5)

    # --- ЭТАП 4-5: Заполнение модалки и создание ---
    log("ЭТАП 4-5: Заполнение модалки и создание заявки")
    dismiss_chrome_password_popup()
    if not create_invoice_via_modal():
        log("Прерываю — заявка не создана", "FAIL")
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

    # --- ЭТАП 6: Предмет платежа ---
    log("ЭТАП 6: Предмет платежа")
    for retry in range(2):
        if add_payment_subject():
            workflow_result["subject"] = True
            break
        try:
            for _ in range(3):
                ActionChains(driver).send_keys(Keys.ESCAPE).perform()
                time.sleep(0.5)
        except Exception:
            pass
        go_to_details_tab()
        time.sleep(2)
    time.sleep(2)

    # --- ЭТАП 7: Маршрут согласования ---
    log("ЭТАП 7: Маршрут согласования (Margulan)")
    for retry in range(3):
        go_to_details_tab()
        dismiss_chrome_password_popup()
        time.sleep(1)
        try:
            # ТОЛЬКО внутри секции маршрута: имя 'Sh Margulan Ju' есть
            # в шапке страницы (залогиненный пользователь) и раньше
            # ложно засчитывало шаг выполненным.
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
        try:
            for _ in range(4):
                ActionChains(driver).send_keys(Keys.ESCAPE).perform()
                time.sleep(0.5)
        except Exception:
            pass
        time.sleep(3)
    time.sleep(2)

    # --- ЭТАП 8: На согласование ---
    log("ЭТАП 8: 'На согласование'")
    go_to_details_tab()
    time.sleep(1.5)
    if click_card_action("На согласование"):
        time.sleep(4)
        status = get_current_status()
        log(f"  Статус: '{status}'", "PASS")
        workflow_result["actions_done"].append(f"На согласование → {status}")
        workflow_result["final_status"] = status
    else:
        log("  ⚠ Не удалось отправить на согласование", "WARN")

    # --- ЭТАП 9: Согласовать ---
    log("ЭТАП 9: 'Согласовать'")
    time.sleep(3)
    go_to_details_tab()
    time.sleep(1.5)
    for approve_btn in ["Согласовать", "Подтвердить согласование", "Утвердить"]:
        if click_card_action(approve_btn):
            time.sleep(5)
            status = get_current_status()
            log(f"  '{approve_btn}' → '{status}'", "PASS")
            workflow_result["actions_done"].append(f"{approve_btn} → {status}")
            workflow_result["final_status"] = status
            break

    # --- ЭТАП 10: ПОДПИСАНИЕ ЭЦП (вариант 1) ---
    log("=" * 60)
    log("ЭТАП 10: ПОДПИСАНИЕ ЭЦП через NCALayer")
    log("=" * 60)
    time.sleep(3)
    try:
        sign_invoice_with_ecp()
    except Exception as e:
        log(f"  ⚠ Подписание ЭЦП: {e}", "WARN")
        shot("ecp_error")

    # --- ЭТАП 11: Добавить ПП ---
    log("ЭТАП 11: Добавить ПП (платёжное поручение)")
    time.sleep(3)
    go_to_details_tab()
    time.sleep(2)
    try:
        if add_payment_order():
            workflow_result["actions_done"].append("ПП добавлено")
    except Exception as e:
        log(f"  ⚠ Добавить ПП: {e}", "WARN")
        shot("add_pp_error")

    # --- ЭТАП 12: Оплачено ---
    log("ЭТАП 12: 'Оплачено'")
    time.sleep(3)
    go_to_details_tab()
    time.sleep(2)
    try:
        click_header_button(["Оплачено", "Оплатить"])
    except Exception as e:
        log(f"  ⚠ Оплачено: {e}", "WARN")

    # --- ЭТАП 13: Загружено ---
    log("ЭТАП 13: 'Загружено'")
    time.sleep(3)
    go_to_details_tab()
    time.sleep(2)
    try:
        click_header_button(["Загружено", "Загрузить"])
    except Exception as e:
        log(f"  ⚠ Загружено: {e}", "WARN")

    # --- ЭТАП 14: Подтвердить ---
    log("ЭТАП 14: 'Подтвердить'")
    time.sleep(3)
    go_to_details_tab()
    time.sleep(2)
    try:
        click_header_button(["Подтвердить", "Подтвердить получение"])
    except Exception as e:
        log(f"  ⚠ Подтвердить: {e}", "WARN")

    # --- ИТОГИ ---
    log("=" * 60)
    log("ИТОГИ (ЗАЯВКА НА ОПЛАТУ, ЭЦП)")
    log("=" * 60)
    log(f"Заявка: {INVOICE_NUM}")
    log(f"URL: {workflow_result['url']}")
    log(f"Создана: {'✓' if workflow_result['created'] else '✗'}")
    log(f"Предмет платежа: {'✓' if workflow_result['subject'] else '✗'}")
    log(f"Маршрут: {'✓' if workflow_result['route'] else '✗'}")
    log(f"Подписано ЭЦП: {'✓' if workflow_result['signed'] else '✗'}")
    log(f"Финальный статус: {workflow_result['final_status'] or 'Неизвестно'}")

    # Строка под конкретный сценарий "Тип оплаты" (для автозаписи в
    # чек-лист) — успех приравнивается к тому, что заявка в этих
    # условиях реально создалась.
    _payment_checklist_text = {
        "Постоплата": "Тип оплаты: Постоплата",
        "Постоплата (под гарантию)": "Тип оплаты: Постоплата (под гарантию)",
        "Постоплата (под залог)": "Тип оплаты: Постоплата (под залог)",
        "Предоплата (100%)": "Тип оплаты: Предоплата (100%)",
        "Частичные платежи": "Тип оплаты: Частичные платежи",
    }.get(PAYMENT_TYPE_SCENARIO)
    if _payment_checklist_text:
        log(f"{_payment_checklist_text}: {'✓' if workflow_result['created'] else '✗'}")
        if not workflow_result["created"] and _payment_checklist_text not in workflow_result["fail_reasons"]:
            workflow_result["fail_reasons"][_payment_checklist_text] = (
                workflow_result["fail_reasons"].get(
                    "Создание документа", "заявка в этих условиях не создалась"))

    # Общий fallback для остальных проверок, если конкретная причина
    # не была записана по ходу выполнения (см. WARN-строки в логе выше).
    _base_checks = {
        "Создание документа": workflow_result["created"],
        "Указание предмета/платежа": workflow_result["subject"],
        "Маршрут согласования": workflow_result["route"],
    }
    for _name, _ok in _base_checks.items():
        if not _ok and _name not in workflow_result["fail_reasons"]:
            workflow_result["fail_reasons"][_name] = "шаг не выполнен, см. WARN в логе выше"

    # Причины отказов — отдельным парсируемым форматом для
    # run_workflow_and_report.py: "[ПРИЧИНА] <Название проверки>: <текст>"
    for _reason_key, _reason_text in workflow_result["fail_reasons"].items():
        log(f"[ПРИЧИНА] {_reason_key}: {_reason_text}")

    for action in workflow_result["actions_done"]:
        log(f"  • {action}")


# ==========================================
# ЗАПУСК
# Без аргумента — прогоняются ВСЕ 6 сценариев подряд, один за другим,
# в одном и том же браузере (по одной заявке на сценарий).
# С аргументом — только этот один сценарий, как раньше.
#     py invoice_workflow_ecp.py                     → все 6 сценариев
#     py invoice_workflow_ecp.py "Постоплата"          → только один
# ==========================================
_scenarios_to_run = [sys.argv[1]] if len(sys.argv) > 1 else list(PAYMENT_TYPE_SCENARIOS)
_scenarios_to_run = [s for s in _scenarios_to_run if s in PAYMENT_TYPE_SCENARIOS] or ["Выдача наличных"]

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
_safe_out("ПОЛНЫЙ ЛОГ (ЗАЯВКА):")
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
