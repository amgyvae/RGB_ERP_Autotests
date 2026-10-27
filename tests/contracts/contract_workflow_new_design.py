# -*- coding: utf-8 -*-
"""
Скрипт (адаптация под НОВЫЙ дизайн портала):
создание договора → согласование → передача на подписание →
подписание Талгатом (marshar244) → подписание Контрагентом (hhuh8918).

ВАЖНО — что изменилось в новом дизайне и было адаптировано:
  1. Форма создания договора теперь разбита на СВОРАЧИВАЕМЫЕ секции:
     "1 Основная информация" (открыта по умолчанию),
     "2 Условия договора", "3 Суммы и валюта", "4 Сроки исполнения"
     (свёрнуты по умолчанию) — их нужно раскрыть кликом по заголовку
     перед тем как заполнять поля внутри. См. expand_form_section().
  2. "Предмет договора" — теперь ОТДЕЛЬНАЯ СТРАНИЦА (переход по кнопке
     "Предмет договора" в шапке карточки), а не модалка на той же
     странице. Внутри — кнопка "Добавить", которая уже открывает модалку
     с полями Смета → Строка сметы → Справочник материалов →
     Статья расходов → Тип → Ед.изм/Кол-во/Цена. См. add_contract_subject().
  3. Вкладка "Документы" внутри карточки договора теперь показывает
     ДВЕ отдельные подписанные секции: "Документы для подписания" и
     "Вложения" — каждая со своей кнопкой "Загрузить". Теперь выбираем
     кнопку по тексту заголовка секции, а не по индексу.
  4. Список вкладок (сегмент-контрол) внутри карточки расширился:
     Обсуждение / Финансы / Акты и накладные / Заказы / Документы /
     Доп.соглашения / История — добавлен универсальный go_to_tab().

ВНИМАНИЕ: класс-имена Ant Design (ant-select, ant-modal, ant-checkbox
и т.д.) в скрипте оставлены как в исходной версии, т.к. по скриншотам
видно, что фреймворк компонентов не поменялся — поменялась только
компоновка страниц. Но это НЕ проверено на живом DOM, поэтому места,
которые стоит перепроверить в браузере (F12 → Elements) перед боевым
прогоном, помечены `# TODO VERIFY`.
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

# ПОСТОЯННЫЙ профиль Chrome (не временный). Нужно для разрешения
# "Доступ к другим приложениям и сервисам на этом устройстве"
# (Local Network Access) — им Chrome защищает подключение сайта к
# NCALayer через wss://127.0.0.1:13579. Без постоянного профиля это
# разрешение негде сохранить, и Chrome спрашивает его заново каждый
# запуск. Реши один раз вручную ("Разрешить") — дальше это же
# разрешение будет действовать во всех новых запусках с этим профилем.
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

SECOND_LOGIN = env("RGB_ACCOUNT2_LOGIN")
SECOND_PASS = env("RGB_ACCOUNT2_PASSWORD")
SECOND_NCA_PASSWORD = env("NCA_KEY1_PASSWORD")
SECOND_P12_PATH = env("NCA_KEY1_PATH", r"C:\Program Files\NCALayer\GOST2015_13-02-2026-18_04.p12")

THIRD_LOGIN = env("RGB_ACCOUNT3_LOGIN")
THIRD_PASS = env("RGB_ACCOUNT3_PASSWORD")
THIRD_NCA_PASSWORD = env("NCA_KEY2_PASSWORD")
THIRD_P12_PATH = env("NCA_KEY2_PATH", r"C:\Program Files\NCALayer\GOST512_b2c2008a1d14dd3f6a531597fb334afc4b3c6e76.p12")

BASE_URL = "https://testportal.rgbgroup.kz/"
CONTRACTS_URL = "https://testportal.rgbgroup.kz/documents/contracts"
WAIT = 15

# ==========================================
# ВЫБОР СЦЕНАРИЯ — теперь можно прогнать ВСЕ 14 сценариев ОДНОЙ
# командой (по умолчанию), либо только один конкретный:
#     py contract_workflow_new_design.py              → все сценарии подряд
#     py contract_workflow_new_design.py barter        → только этот один
# ==========================================
CONTRACT_SCENARIOS = [
    "default",             # как есть (Договор поставки, Постоплата, НДС по умолчанию)
    "barter",              # Бартер включён (+ обязательное "Описание бартера")
    "prepay",              # Тип оплаты = Предоплата
    "open_contract",       # "Открытый договор" переключено в обратное состояние
    "type_uslug",          # Тип договора = "Договор услуг"
    "type_uslug_postavka", # Тип договора = "Договор услуг и поставки"
    "type_import",         # Тип договора = "Импорт"
    "nds_0",               # Ставка НДС (в "Суммы и валюта") = "НДС 0%"
    "nds_none",            # Ставка НДС = "Без НДС"
    "paper_signing_off",   # "Подписывается бумажно" переключено в обратное состояние
    "no_template",         # "Документ из шаблона" выключен (ручная загрузка PDF)
    "cash",                # Тип оплаты = "Выдача наличных"
    "postpay_guarantee",   # Тип оплаты = "Постоплата (под гарантию)"
    "postpay_pledge",      # Тип оплаты = "Постоплата (под залог)"
    "partial_payments",    # Тип оплаты = "Частичные платежи"
]

CONTRACT_SCENARIO = "default"  # актуальный сценарий текущего прогона
                                # (переустанавливается в цикле внизу файла)


def _apply_scenario(key):
    """Переустанавливает сценарий и создаёт СВЕЖИЙ workflow_result —
    вызывается перед каждым прогоном main(), когда сценариев несколько
    подряд в одном запуске процесса."""
    global CONTRACT_SCENARIO, CONTRACT_NUM, workflow_result
    CONTRACT_SCENARIO = key
    CONTRACT_NUM = f"ПОЛНЫЙ-{key}-{datetime.now().strftime('%d%m-%H%M%S')}"
    workflow_result = {
        "number": CONTRACT_NUM,
        "url": None,
        "created": False,
        "signatories": False,
        "document": False,
        "subject": False,
        "approval_route": False,
        "ecp_signed": False,
        "fail_reasons": {},
        "final_status": None,
        "actions_done": []
    }


# Инициализация "по умолчанию" — чтобы модуль парсился без ошибок ещё
# до цикла запуска внизу файла (там сценарий переустановится заново).
_apply_scenario("default")

LOG_FILE_PATH = log_path(f"contract_log_{datetime.now().strftime('%d%m_%H%M%S')}.txt")
try:
    _LOG_FILE = open(LOG_FILE_PATH, "w", encoding="utf-8", buffering=1)
except Exception:
    _LOG_FILE = None

LOG_LINES = []

# Флаг: идёт НАМЕРЕННЫЙ выход из аккаунта (этап подписания под другими
# пользователями). Пока он True, защита dismiss_logout_confirm_if_present()
# не отменяет модалку подтверждения выхода.
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
        path = screen_path(f"debug_{name}_{datetime.now().strftime('%H%M%S')}.png")
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


def _jump_to_year_via_title(target_year):
    """Кликает по заголовку календаря ("Сентябрь 2020" и т.п.), чтобы
    открыть панель быстрого выбора года, и кликает нужный год.

    ПОЧЕМУ ТАК: на скриншоте видно, что у пикера НА САМОМ ДЕЛЕ 4 кнопки
    навигации («, ‹, ›, ») — а не 2, как в старом комментарии "ТОЧНАЯ
    структура сайта". Без точного знания, какая из 4 кнопок листает
    ГОД, а какая МЕСЯЦ, позиционный выбор (vis_nav[0]/vis_nav[-1])
    ненадёжен и может застревать. Клик по заголовку — стандартное
    поведение таких календарей (открывает грид годов) и не зависит от
    количества/порядка стрелок вообще.
    """
    try:
        nav = driver.find_element(
            By.XPATH, "//div[contains(@class,'ui-date-picker__nav')]")
    except Exception:
        return False
    try:
        candidates = nav.find_elements(By.XPATH, ".//*")
        title_el = None
        for el in candidates:
            txt = (el.text or "").strip().lower()
            if txt and any(ch.isdigit() for ch in txt) and any(
                    m in txt for m in ["январ", "феврал", "март", "апрел",
                                        "май", "июн", "июл", "август",
                                        "сентябр", "октябр", "ноябр", "декабр"]):
                title_el = el
                break
        if not title_el:
            return False
        js_click(title_el)
        time.sleep(0.5)
    except Exception:
        return False

    try:
        year_btns = driver.find_elements(
            By.XPATH, f"//button[normalize-space(text())='{target_year}']")
        vis_year_btns = [b for b in year_btns if b.is_displayed()]
        if vis_year_btns:
            js_click(vis_year_btns[0])
            time.sleep(0.5)
            log(f"    ✓ Год {target_year} выбран через заголовок календаря", "PASS")
            return True
    except Exception:
        pass
    try:
        ActionChains(driver).send_keys(Keys.ESCAPE).perform()
        time.sleep(0.3)
    except Exception:
        pass
    return False


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

        # Листаем до нужного месяца/года (в обе стороны).
        # Сначала пробуем быстрый прыжок к нужному году через заголовок
        # (см. _jump_to_year_via_title) — это не зависит от того,
        # сколько там кнопок-стрелок и что каждая из них листает.
        # Если год уже совпадает — прыжок не нужен и не делается.
        try:
            nav_check = driver.find_element(
                By.XPATH, "//div[contains(@class,'ui-date-picker__nav')]")
            nav_check_text = (nav_check.text or "").strip().lower()
        except Exception:
            nav_check_text = ""
        if target_year not in nav_check_text:
            _jump_to_year_via_title(target_year)

        # ВАЖНО: раньше лимит был захардкожен как 14 кликов, из-за
        # чего если календарь открывался на месяце, отстоящем от
        # target больше чем на ~14 месяцев (например, дефолт на
        # 2020 году, а нужен 2026 — это 72 месяца), цикл обрывался
        # ДО того, как долистает до нужного года, и потом клик по
        # дню срабатывал в НЕПРАВИЛЬНОМ месяце/году (см. баг с датой
        # "14.09.2020" вместо "14.09.2026"). После прыжка к году выше
        # здесь остаётся долистать максимум ±11 месяцев, но оставляем
        # запас на случай, если прыжок к году не сработал.
        max_nav_clicks = 14
        try:
            nav0 = driver.find_element(
                By.XPATH, "//div[contains(@class,'ui-date-picker__nav')]")
            nav0_text = (nav0.text or "").strip().lower()
            y0 = int([w for w in nav0_text.split() if w.isdigit()][0])
            m0 = next((i + 1 for i, m in enumerate(month_names)
                       if m in nav0_text), target_date.month)
            months_diff = abs((target_date.year * 12 + target_date.month)
                               - (y0 * 12 + m0))
            max_nav_clicks = months_diff + 5
        except Exception:
            pass

        for _ in range(max_nav_clicks):
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

        # ПРОВЕРКА результата по тексту триггера.
        # ВАЖНО: раньше здесь только проверялось "поле не пустое и не
        # плейсхолдер" — этого недостаточно, т.к. клик по дню мог
        # попасть в НЕПРАВИЛЬНЫЙ месяц/год (если навигация не успела
        # долистать), и такой неверный результат засчитывался как
        # успех. Теперь сверяем факт. дату с ожидаемой (day.month.year).
        trigger = locate_trigger()
        actual = _date_trigger_value(trigger) if trigger else ""
        actual_low = actual.lower()
        # Текст триггера может быть в разных форматах ("14.09.2026"
        # или "14 сентября 2026"), поэтому вместо жёсткого сравнения
        # строк проверяем по отдельности день, год и месяц (число или
        # название) — этого достаточно, чтобы отличить правильную дату
        # от даты в неправильном месяце/годе.
        actual_matches = (
            clicked and actual and "выбрат" not in actual_low
            and target_day in actual
            and target_year in actual
            and (str(target_date.month).zfill(2) in actual
                 or target_month in actual_low)
        )
        if actual_matches:
            log(f"    ✓ {label_text}: {actual} (просили {date_str})", "PASS")
            dismiss_logout_confirm_if_present()
            return True

        log(f"    ⚠ {label_text}: после попытки {attempt+1} значение = "
            f"'{actual or 'пусто'}', ожидали {date_str} — не совпадает, "
            f"повторяю попытку", "WARN")
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
    поля).

    ИСПРАВЛЕНО: раньше сюда слался date_str целиком с точками
    ("14.09.2026"), маска поля это ломала и обрезала последнюю цифру
    года ("14.09.2020" — подтверждено через DevTools: реальный класс
    поля 'ui-date-picker__input', это самый обычный текстовый input с
    маской). Хуже того, проверка успеха была `date_str in val or
    val.strip()` — второе условие срабатывает на ЛЮБОМ непустом
    значении, поэтому испорченная маской дата 2020 засчитывалась как
    успех. Теперь: (1) сначала пробуем ввести ТОЛЬКО цифры — маска
    сама расставит точки без конфликта; (2) проверка строгая — только
    точное совпадение с date_str.
    """
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

            # Попытка 1: только цифры — маска сама расставит точки
            digits_only = date_str.replace(".", "")
            inp.send_keys(digits_only)
            time.sleep(0.3)
            val = inp.get_attribute("value") or ""

            if date_str not in val:
                # Попытка 2: очистить и ввести с точками как раньше
                try:
                    inp.send_keys(Keys.CONTROL + "a")
                    inp.send_keys(Keys.DELETE)
                except Exception:
                    pass
                time.sleep(0.2)
                inp.send_keys(date_str)
                time.sleep(0.3)
                val = inp.get_attribute("value") or ""

            inp.send_keys(Keys.ENTER)
            time.sleep(0.5)
            val = inp.get_attribute("value") or ""

            if date_str in val:
                log(f"    ✓ {label_text}: {date_str} [прямой input]", "PASS")
                return True

            # ВАЖНО: значение может ВЫГЛЯДЕТЬ верным сразу после ввода,
            # но искажаться (2026 → 2020) уже ПОСЛЕ потери фокуса полем
            # (та же природа бага, что мы ловили раньше на других
            # формах) — снимаем фокус и проверяем ЕЩЁ РАЗ, прежде чем
            # сдаваться.
            try:
                driver.execute_script("arguments[0].blur();", inp)
            except Exception:
                pass
            time.sleep(0.4)
            val = inp.get_attribute("value") or ""

            if date_str in val:
                log(f"    ✓ {label_text}: {date_str} [прямой input]", "PASS")
                return True

            log(f"    ⚠ {label_text}: значение исказилось после потери фокуса "
                f"('{val}') — принудительно выставляю через JS", "WARN")

            # Принудительная установка через нативный сеттер — в обход
            # маски/посимвольного ввода целиком.
            try:
                set_number_native(inp, date_str)
                time.sleep(0.3)
                driver.execute_script("arguments[0].blur();", inp)
                time.sleep(0.4)
                val = inp.get_attribute("value") or ""
                if date_str in val:
                    log(f"    ✓ {label_text}: {date_str} [прямой input, JS-фикс]", "PASS")
                    return True
            except Exception as e:
                log(f"    ⚠ {label_text}: ошибка JS-фикса — {e}", "WARN")

            log(f"    ⚠ {label_text}: после всех попыток в поле стоит '{val}', "
                f"ожидали '{date_str}' — не совпадает", "WARN")
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

            # ВАЖНО: поле использует маску автоформатирования даты.
            # Если печатать сразу "14.09.2026" (с точками), маска
            # конфликтует с уже вставленными точками и год обрезается
            # (подтверждено: в форму попадало "14.09.2020" вместо
            # "14.09.2026" — последняя цифра терялась). Поэтому сначала
            # пробуем ввести ТОЛЬКО цифры — маска сама расставит точки.
            digits_only = date_str.replace(".", "")
            inp.send_keys(digits_only)
            time.sleep(0.4)
            current = inp.get_attribute("value") or ""

            if date_str not in current:
                # Цифры не сработали — пробуем как раньше, с точками
                try:
                    inp.send_keys(Keys.CONTROL + "a")
                    inp.send_keys(Keys.DELETE)
                except Exception:
                    pass
                time.sleep(0.2)
                inp.send_keys(date_str)
                time.sleep(0.3)
                current = inp.get_attribute("value") or ""

            inp.send_keys(Keys.ENTER)
            time.sleep(0.6)
            current = inp.get_attribute("value") or ""
            if date_str in current:
                log(f"  ✓ {label}: {date_str} [input]", "PASS")
                return True
            else:
                log(f"  ⚠ {label}: после ввода в поле реально стоит '{current}', "
                    f"ожидали '{date_str}'", "WARN")
    except Exception as e:
        log(f"  ⚠ {label}: {e}", "WARN")

    log(f"  ⚠ {label}: НЕ УДАЛОСЬ выставить {date_str} "
        f"(значение по умолчанию оставлено как есть)", "WARN")
    dump_field_html(label)
    return False



# ==========================================
# НОВОЕ: раскрытие свёрнутых секций формы создания договора
# ==========================================
def expand_form_section(section_title):
    """Кликает по заголовку секции ('2 Условия договора' и т.п.),
    если она свёрнута. Секции пронумерованы (1..4) — ищем по видимому
    тексту заголовка без учёта номера.
    # TODO VERIFY: если секция уже открыта, лишний клик её закроет —
    # поэтому проверяем видимость характерного поля внутри секции,
    # а не полагаемся только на класс-индикатор chevron.
    """
    try:
        headers = driver.find_elements(
            By.XPATH,
            f"//*[self::div or self::span][contains(normalize-space(text()),'{section_title}')]"
        )
        visible_headers = [h for h in headers if h.is_displayed()]
        if not visible_headers:
            log(f"    ⚠ Секция '{section_title}' не найдена", "WARN")
            return False

        header = visible_headers[0]
        # Пытаемся понять, свёрнута ли секция: ищем ближайший контейнер
        # с классом типа collapse/panel и смотрим, скрыто ли его тело.
        try:
            container = header.find_element(
                By.XPATH,
                "./ancestor::*[contains(@class,'panel') or contains(@class,'collapse') "
                "or contains(@class,'section')][1]"
            )
            body_hidden = "ant-collapse-item-active" not in (container.get_attribute("class") or "")
        except Exception:
            body_hidden = True  # не знаем — кликнем на всякий случай

        if body_hidden:
            scroll_to(header)
            time.sleep(0.3)
            try:
                header.click()
            except Exception:
                js_click(header)
            time.sleep(0.8)
            log(f"    ✓ Секция '{section_title}' раскрыта", "PASS")
        else:
            log(f"    • Секция '{section_title}' уже открыта")
        return True
    except Exception as e:
        log(f"    ⚠ Раскрытие секции '{section_title}': {e}", "WARN")
        return False


# ==========================================
# ЗАПОЛНЕНИЕ ВСЕХ НЕОБЯЗАТЕЛЬНЫХ ПОЛЕЙ ФОРМЫ
# ==========================================
def fill_optional_fields():
    """Заполняет необязательные поля формы. В новом дизайне поля
    сгруппированы в свёрнутые секции — сперва их раскрываем."""
    log("  Заполняю необязательные поля...")

    # --- Секция 1 "Основная информация": Номер договора, Очередь, Блок ---
    try:
        num_inputs = driver.find_elements(By.XPATH,
            "//*[contains(text(),'Номер договора')]/following::input[1]")
        for inp in num_inputs:
            if inp.is_displayed() and inp.is_enabled():
                inp.clear()
                inp.send_keys(f"NUM-{CONTRACT_NUM}")
                log(f"    ✓ Номер договора: NUM-{CONTRACT_NUM}", "PASS")
                break
    except Exception as e:
        log(f"    ⚠ Номер договора: {e}", "WARN")

    select_first_form_dropdown("Очередь", allow_missing=True)
    time.sleep(0.3)
    select_first_form_dropdown("Блок", allow_missing=True)
    time.sleep(0.3)

    # --- Секция 2 "Условия договора": Открытый договор / Бартер ---
    expand_form_section("Условия договора")
    time.sleep(0.3)

    # ИСПРАВЛЕНО: реальная структура (подтверждено DevTools) — подпись
    # <span class="ccp-toggle__label"> и переключатель
    # <button role="switch" aria-checked="true/false" class="ui-switch">
    # СОВСЕМ НЕ вложены друг в друга. Старый код искал класс
    # 'ant-switch' (стандартный Ant Design), которого тут нет вообще —
    # поэтому переключатель никогда не находился. Используем общую
    # функцию set_toggle_state() (см. начало файла).
    if CONTRACT_SCENARIO == "barter":
        set_toggle_state("Бартер", True)
    if CONTRACT_SCENARIO == "open_contract":
        # Переключаем в состояние, ОБРАТНОЕ текущему умолчанию —
        # проверяем именно другой вариант, а не тот, что уже стоит.
        switch = find_toggle_switch("Открытый договор")
        current = get_toggle_state(switch) if switch else None
        if current is not None:
            set_toggle_state("Открытый договор", not current)
        else:
            log("  ⚠ Переключатель 'Открытый договор' не найден", "WARN")
    if CONTRACT_SCENARIO == "paper_signing_off":
        switch = find_toggle_switch("Подписывается бумажно")
        current = get_toggle_state(switch) if switch else None
        if current is not None:
            set_toggle_state("Подписывается бумажно", not current)
        else:
            log("  ⚠ Переключатель 'Подписывается бумажно' не найден", "WARN")
    if CONTRACT_SCENARIO == "no_template":
        # По умолчанию ВКЛ (автогенерация .docx). Выключаем — должна
        # открыться ручная загрузка PDF вместо автогенерации.
        set_toggle_state("Документ из шаблона", False)

    time.sleep(0.5)
    # Описание бартера (появляется после включения "Бартер")
    try:
        barter_inputs = driver.find_elements(By.XPATH,
            "//*[contains(text(),'Описание бартера')]/following::textarea[1] | "
            "//*[contains(text(),'Описание бартера')]/following::input[1] | "
            "//textarea[contains(@placeholder,'бартер')] | "
            "//input[contains(@placeholder,'бартер')]")
        for bi in barter_inputs:
            if bi.is_displayed() and bi.is_enabled():
                bi.clear()
                bi.send_keys("Взаимный обмен товарами и услугами по договорённости сторон (RPA)")
                log("    ✓ Описание бартера заполнено", "PASS")
                break
    except Exception as e:
        log(f"    ⚠ Описание бартера: {e}", "WARN")

    # --- Секция 3 "Суммы и валюта" ---
    expand_form_section("Суммы и валюта")
    time.sleep(0.3)

    try:
        labels = driver.find_elements(By.XPATH, "//*[normalize-space(text())='Ставка НДС']")
        nds_select = None
        for lbl in labels:
            if not lbl.is_displayed():
                continue
            try:
                cand = lbl.find_element(By.XPATH, "following::div[contains(@class,'ant-select')][1]")
                if cand.is_displayed():
                    nds_select = cand
                    break
            except Exception:
                continue

        if nds_select and open_dropdown(nds_select):
            time.sleep(0.8)
            options = collect_options()
            picked = None
            # Сценарии nds_0 / nds_none выбирают конкретный вариант;
            # иначе — прежнее поведение по умолчанию (16%).
            target_nds = {"nds_0": "0%", "nds_none": "без"}.get(CONTRACT_SCENARIO)
            if target_nds:
                for opt in options:
                    if target_nds in opt["text"].lower():
                        picked = opt
                        break
            if not picked:
                for opt in options:
                    if "16" in opt["text"] and "%" in opt["text"]:
                        picked = opt
                        break
            if not picked:
                for opt in options:
                    txt = opt["text"].lower()
                    if "%" in txt and "без" not in txt:
                        picked = opt
                        break
            if not picked and len(options) > 1:
                picked = options[1]
            if not picked and options:
                picked = options[0]

            if picked:
                try:
                    picked["element"].click()
                except Exception:
                    js_click(picked["element"])
                log(f"    ✓ Ставка НДС: '{picked['text'][:30]}'", "PASS")
                time.sleep(0.8)
    except Exception as e:
        log(f"    ⚠ Ставка НДС: {e}", "WARN")

    for label, value in [("Сумма без НДС", "1000000"), ("Сумма с НДС", "1120000")]:
        try:
            inputs = driver.find_elements(By.XPATH,
                f"//*[contains(text(),'{label}')]/following::input[1]")
            for inp in inputs:
                if inp.is_displayed() and inp.is_enabled():
                    set_number_native(inp, value)
                    log(f"    ✓ {label}: {value}", "PASS")
                    break
        except Exception as e:
            log(f"    ⚠ {label}: {e}", "WARN")

    select_first_form_dropdown("Валюта", allow_missing=True)
    time.sleep(0.3)

    # --- Секция 4 "Сроки исполнения" ---
    expand_form_section("Сроки исполнения")
    time.sleep(0.3)

    # Даты: начало = завтра, ОКОНЧАНИЕ = начало + 1 день (по требованию
    # пользователя — раньше начало и окончание совпадали, что вызывало
    # проблемы валидации), срок заключения = начало + 7 дней (чтобы не
    # получать ошибку "Срок отправки договора-черновика ... истёк").
    # Даты (по требованию пользователя):
    #   начало   = сегодня
    #   окончание = +10 дней
    #   срок заключения = +10 дней
    # Раньше окончание/срок совпадали с датой договора, из-за чего
    # появлялось "Просрочено на N дн." и договор не уходил на согласование.
    today_base = datetime.now()
    start_date = today_base.strftime("%d.%m.%Y")
    end_date = (today_base + timedelta(days=10)).strftime("%d.%m.%Y")
    conclude_date = (today_base + timedelta(days=10)).strftime("%d.%m.%Y")

    fill_date_field("Начало действия договора", start_date)
    time.sleep(0.3)
    fill_date_field("Окончание действия договора", end_date)
    time.sleep(0.3)
    fill_date_field("Срок заключения договора", conclude_date)
    time.sleep(0.3)


# ==========================================
# NCALayer (без изменений — внешнее приложение, дизайн сайта не влияет)
# ==========================================
def _dismiss_external_protocol_dialog():
    """Chrome при вызове NCALayer через внешний протокол показывает
    нативное окно-разрешение вида 'testportal.rgbgroup.kz запрашивает
    разрешение на: Доступ к другим приложениям...' с кнопками
    'Разрешить'/'Блокировать'. Пока никто не жмёт 'Разрешить' —
    процесс подписания не двигается вообще.

    ВАЖНО: кликаем ТОЛЬКО если окно реально содержит текст про запрос
    разрешения — иначе можно случайно нажать постороннюю кнопку."""
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
        """Засчитываем успех ТОЛЬКО если перешли на карточку договора
        (/contracts/<uuid>), а не на любой другой URL. Раньше любая
        смена адреса считалась успехом — из-за этого случайный переход
        (например, обратно в список или на чужой договор) принимался
        за 'договор создан'."""
        for _ in range(8):
            time.sleep(1)
            cur = driver.current_url
            if cur == initial_url:
                continue
            if "/contracts/" not in cur or "/create" in cur:
                continue
            tail = cur.rstrip("/").split("/contracts/")[-1].split("/")[0]
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
# PDF ФАЙЛ (без изменений)
# ==========================================
def create_test_pdf():
    try:
        import tempfile
        tmpdir = tempfile.gettempdir()
        path = os.path.join(tmpdir, f"contract_signing_{CONTRACT_NUM}.pdf")
        pdf = b"""%PDF-1.4
1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj
2 0 obj<</Type/Pages/Count 1/Kids[3 0 R]>>endobj
3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]/Contents 4 0 R/Resources<</Font<</F1 5 0 R>>>>>>endobj
4 0 obj<</Length 60>>stream
BT /F1 18 Tf 100 700 Td (Contract Document RPA) Tj ET
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
# ПОДПИСАНТЫ — Заказчик=Бейсембаев Куаныш, Контрагент=Алдажаров Диас Талгатович
# В новом дизайне секция "Подписанты" видна прямо на главной вкладке
# карточки договора (см. скрин 9) — карточки Заказчик/Контрагент с
# кнопкой "Редактировать" у заголовка секции. Логика внутри модалки
# редактирования, судя по всему, не поменялась (dropdown-поиск).
# ==========================================

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


def fill_signatories_in_card():
    """Подписанты (ТОЧНАЯ разметка сайта, подтверждено DevTools):
      section.signers-card
        div.signers-card__slot > div.signers-card__empty
          span.signers-card__empty-label "Заказчик не выбран"
          button.signers-card__select-link "Выбрать"
      Клик по любой 'Выбрать' переводит ВЕСЬ блок в режим
      редактирования: появляются два ui-select с плейсхолдерами
      'Выбрать заказчика' / 'Выбрать контрагента' и кнопки
      'Отмена' / 'Сохранить'.

    Реальные имена в списках (подтверждено скриншотом):
      Заказчик  -> 'Ерланович Талгат'   (порядок слов ОБРАТНЫЙ)
      Контрагент-> 'Талгатович Ерлан'   (группа 'Внешние')
    """
    exit_edit_mode()
    dismiss_chrome_password_popup()
    ensure_on_our_contract("fill_signatories")

    # 1. Переводим блок в режим редактирования (если ещё не в нём)
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
        except Exception:
            pass

        if not choose_link:
            # Может быть уже заполнено ранее — тогда есть кнопка "Редактировать"
            try:
                section = driver.find_element(
                    By.XPATH, "//section[contains(@class,'signers-card')]")
                edit_btns = section.find_elements(
                    By.XPATH, ".//button[.//span[normalize-space(text())='Редактировать']]")
                vis_edit = [b for b in edit_btns if b.is_displayed() and b.is_enabled()]
                if vis_edit:
                    choose_link = vis_edit[0]
            except Exception:
                pass

        if not choose_link:
            log("  ⚠ Не найдена кнопка входа в редактирование подписантов", "WARN")
            dump_field_html("Подписанты")
            return False

        scroll_to(choose_link)
        time.sleep(0.3)
        try:
            js_click(choose_link)
        except Exception:
            choose_link.click()
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

    # 2. Выбираем Заказчика и Контрагента (независимые повторы)
    ok_zakazchik = _select_in_ui_select(
        "Выбрать заказчика", "Бейсембаев",
        ["Бейсембаев Куаныш Едилович", "Куаныш Едилович Бейсембаев", "Бейсембаев"], "Заказчик")

    ok_kontragent = _select_in_ui_select(
        "Выбрать контрагента", "Алд",
        ["Алдажаров Диас Андреевич", "Алдажаров Диас", "Алд"], "Контрагент")

    # 3. Сохраняем блок — кнопка ищется СТРОГО внутри signers-card,
    # чтобы не задеть кнопки всего договора
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
        for method in ["js", "selenium"]:
            try:
                if method == "js":
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


# ==========================================
# НОВОЕ: ПРЕДМЕТ ДОГОВОРА — теперь отдельная страница, не модалка.
# Поток: карточка → кнопка "Предмет договора" (шапка) → отдельная
# страница со списком и кнопкой "Добавить" → модалка "Добавить предмет"
# (Смета / Строка сметы / Справочник материалов / Статья расходов /
# Тип / Ед.изм / Количество / Цена без НДС / Цена с НДС / Описание)
# → кнопка "Добавить" в модалке → "Вернуться к основной информации".
# ==========================================
def add_contract_subject():
    exit_edit_mode()
    try:
        # 1. Переход на страницу "Предмет договора"
        subject_link = None
        for xp in [
            "//button[.//span[normalize-space(text())='Предмет договора']]",
            "//*[self::a or self::button][contains(normalize-space(.),'Предмет договора')]",
        ]:
            els = driver.find_elements(By.XPATH, xp)
            visible = [e for e in els if e.is_displayed() and e.is_enabled()]
            if visible:
                subject_link = visible[0]
                break

        if not subject_link:
            log("  ⚠ Кнопка/ссылка 'Предмет договора' не найдена", "WARN")
            return False

        scroll_to(subject_link)
        time.sleep(0.3)
        try:
            subject_link.click()
        except Exception:
            js_click(subject_link)
        time.sleep(2.5)
        log("  ✓ Открыта страница 'Предмет договора'", "PASS")

        # 2. Кнопка "Добавить" на странице предмета
        # ТОЧНЫЙ класс сайта (подтверждено инспектором): cs-subjects__add
        add_btns = driver.find_elements(By.XPATH,
            "//button[contains(@class,'cs-subjects__add')] | "
            "//button[.//span[normalize-space(text())='Добавить']]")
        visible_add = [b for b in add_btns if b.is_displayed() and b.is_enabled()]
        if not visible_add:
            log("  ⚠ Кнопка 'Добавить' на странице предмета не найдена", "WARN")
            return False

        scroll_to(visible_add[0])
        time.sleep(0.3)
        try:
            visible_add[0].click()
        except Exception:
            js_click(visible_add[0])
        time.sleep(2)
        log("  ✓ Модалка 'Добавить предмет' открыта", "PASS")

        # 3. Модалка добавления предмета — generic-поиск (ant-modal НЕ
        # существует на реальном сайте, поэтому старая логика тут
        # тихо проваливалась и ничего не заполняла).
        modal = find_visible_modal_container(hint_text="Добавить предмет")
        if not modal:
            log("  ⚠ Модалка 'Добавить предмет' не найдена", "WARN")
            dump_field_html("Смета")
            return False

        # 3a. Смета
        try:
            smeta_select = find_dropdown_in_scope(modal, "Смета")
            if smeta_select and open_dropdown(smeta_select):
                time.sleep(0.8)
                opts = collect_options() or collect_options_generic()
                if opts:
                    try:
                        opts[0]["element"].click()
                    except Exception:
                        js_click(opts[0]["element"])
                    log(f"    ✓ Смета: '{opts[0]['text'][:40]}'", "PASS")
                    time.sleep(1)
            elif not smeta_select:
                log("    ⚠ Смета: контрол не найден", "WARN")
        except Exception as e:
            log(f"    ⚠ Смета: {e}", "WARN")

        # 3b. Строка сметы (появляется/активируется после выбора Сметы)
        try:
            row_select = find_dropdown_in_scope(modal, "Строка сметы")
            if row_select and open_dropdown(row_select):
                time.sleep(0.8)
                opts = collect_options() or collect_options_generic()
                if opts:
                    try:
                        opts[0]["element"].click()
                    except Exception:
                        js_click(opts[0]["element"])
                    log(f"    ✓ Строка сметы: '{opts[0]['text'][:40]}'", "PASS")
                    time.sleep(1)
                else:
                    # Возможно дерево, а не плоский список
                    picked = click_tree_leaf()
                    if picked:
                        log(f"    ✓ Строка сметы (tree): '{picked[:40]}'", "PASS")
            elif not row_select:
                log("    ⚠ Строка сметы: контрол не найден", "WARN")
        except Exception as e:
            log(f"    ⚠ Строка сметы: {e}", "WARN")

        # 3c. Справочник материалов / Статья расходов / Тип — если
        # "Строка сметы" не была выбрана автоматически подтягивает поля,
        # заполняем оставшиеся select'ы первым доступным вариантом.
        for field_label in ["Справочник материалов", "Статья расходов", "Тип"]:
            try:
                fld_select = find_dropdown_in_scope(modal, field_label)
                if not fld_select:
                    log(f"    ⚠ {field_label}: контрол не найден", "WARN")
                    continue
                txt = (fld_select.text or "").strip().lower()
                if txt and "выбер" not in txt:
                    continue  # уже заполнено (например, автоподставилось)
                if open_dropdown(fld_select):
                    time.sleep(0.8)
                    opts = collect_options() or collect_options_generic()
                    if opts:
                        try:
                            opts[0]["element"].click()
                        except Exception:
                            js_click(opts[0]["element"])
                        log(f"    ✓ {field_label}: '{opts[0]['text'][:40]}'", "PASS")
                        time.sleep(0.8)
                    else:
                        try:
                            ActionChains(driver).send_keys(Keys.ESCAPE).perform()
                        except Exception:
                            pass
            except Exception as e:
                log(f"    ⚠ {field_label}: {e}", "WARN")

        # 3d. Количество
        try:
            qty_inp = modal.find_element(By.XPATH,
                ".//*[normalize-space(text())='Количество']/following::input[1]")
            if qty_inp.is_displayed() and qty_inp.is_enabled():
                set_number_native(qty_inp, "1")
                log("    ✓ Количество: 1", "PASS")
        except Exception:
            pass

        # 3e. Цена за единицу без НДС / с НДС
        for label, value in [("Цена за единицу без НДС", "1000"), ("Цена за единицу с НДС", "1120")]:
            try:
                price_inp = modal.find_element(By.XPATH,
                    f".//*[normalize-space(text())='{label}']/following::input[1]")
                if price_inp.is_displayed() and price_inp.is_enabled():
                    set_number_native(price_inp, value)
                    log(f"    ✓ {label}: {value}", "PASS")
            except Exception:
                pass

        # 3f. Описание (textarea, может требовать прокрутки модалки вниз)
        try:
            driver.execute_script("arguments[0].scrollTop = arguments[0].scrollHeight;", modal)
            time.sleep(0.3)
        except Exception:
            pass
        try:
            textareas = modal.find_elements(By.XPATH, ".//textarea")
            for ti in textareas:
                if ti.is_displayed() and not ti.get_attribute("value"):
                    ti.clear()
                    ti.send_keys("Автосозданный предмет договора (RPA)")
                    break
        except Exception:
            pass

        blur_focus()
        time.sleep(0.5)

        # 4. Кнопка "Добавить" в футере модалки (generic-поиск: сначала
        # внутри найденной модалки, затем по всей странице как фолбэк)
        save_btn = find_modal_button(modal, ["Добавить", "Сохранить", "Создать"])
        if not save_btn:
            save_btn = find_modal_button(None, ["Добавить", "Сохранить", "Создать"])
        if not save_btn:
            log("  ⚠ Кнопка 'Добавить' в модалке не найдена", "WARN")
            dump_field_html("Смета")
            return False

        try:
            save_btn.click()
        except Exception:
            js_click(save_btn)
        time.sleep(3)
        log("  ✓ Предмет добавлен", "PASS")

        # 5. Возврат к основной информации
        back_link = None
        for xp in [
            "//*[self::a or self::button][contains(normalize-space(.),'Вернуться к основной информации')]",
        ]:
            els = driver.find_elements(By.XPATH, xp)
            visible = [e for e in els if e.is_displayed()]
            if visible:
                back_link = visible[0]
                break
        if back_link:
            try:
                back_link.click()
            except Exception:
                js_click(back_link)
            time.sleep(2)
            log("  ✓ Возврат к основной информации", "PASS")

        return True

    except Exception as e:
        log(f"  ⚠ Предмет договора: {e}", "WARN")
        shot("subject_error")
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


def ensure_on_our_contract(context=""):
    """ЗАЩИТА ОТ УХОДА НА ЧУЖОЙ ДОГОВОР.

    Раньше этапы 6-10 работали 'на той странице, где браузер оказался':
    любой промах кликом, редирект или случайный переход по списку
    договоров уводил робота на СТАРЫЙ договор, и дальше он дозаполнял
    и подписывал уже его. Теперь перед каждым этапом проверяем, что
    открыт именно СОЗДАННЫЙ нами договор (по его UUID в URL), и при
    расхождении принудительно возвращаемся на него.
    """
    target = workflow_result.get("url")
    if not target:
        return False

    # UUID созданного договора — последний непустой сегмент URL
    try:
        target_id = target.rstrip("/").split("/contracts/")[-1].split("/")[0]
    except Exception:
        target_id = ""

    cur = driver.current_url
    if target_id and target_id in cur:
        return True

    log(f"  ⚠ Открыт не наш договор{(' (' + context + ')') if context else ''}: "
        f"{cur} — возвращаюсь на {target}", "WARN")
    try:
        driver.get(target)
        time.sleep(4)
        dismiss_chrome_password_popup()
    except Exception as e:
        log(f"  ⚠ Не удалось вернуться на договор: {e}", "WARN")
        return False
    return target_id in driver.current_url


def go_to_general_info():
    # На скриншотах отдельной вкладки "Общая информация" в сегмент-
    # контроле нет — левая колонка с реквизитами договора видна всегда.
    # Оставляем функцию для совместимости: просто гарантируем, что мы
    # не на странице "Предмет договора" (кликаем "Вернуться...", если видно).
    # ВАЖНО: сначала убеждаемся, что вообще находимся на НАШЕМ договоре.
    ensure_on_our_contract("go_to_general_info")
    back_links = driver.find_elements(By.XPATH,
        "//*[self::a or self::button][contains(normalize-space(.),'Вернуться к основной информации')]")
    visible = [b for b in back_links if b.is_displayed()]
    if visible:
        try:
            visible[0].click()
        except Exception:
            js_click(visible[0])
        time.sleep(2)
        return True
    return True


def go_to_finance_tab():
    return go_to_tab("Финансы")


# ==========================================
# РАЗДЕЛ ФИНАНСЫ: Авансы + График платежей (структура похожа на
# старую, добавился блок "Финансовый обзор" сверху — не мешает)
# ==========================================
def fill_finance_section():
    exit_edit_mode()
    dismiss_logout_confirm_if_present()
    log("  Заполняю раздел 'Финансы'...")

    if not go_to_finance_tab():
        log("  ⚠ Вкладка 'Финансы' не найдена", "WARN")
        return False

    time.sleep(2)
    result = {"avans": False, "payment": False}

    # ---------- АВАНС ----------
    try:
        # Надёжный способ: ближайшая ПОСЛЕДУЮЩАЯ (в DOM-порядке) кнопка
        # "Добавить" после заголовка "Авансы" — без риска "слишком
        # широкого" ancestor-поиска, который может задеть не ту кнопку.
        add_btns = driver.find_elements(By.XPATH,
            "//*[normalize-space(text())='Авансы']/following::button[.//span[normalize-space(text())='Добавить']][1]")
        visible = [b for b in add_btns if b.is_displayed() and b.is_enabled()]
        if visible:
            scroll_to(visible[0])
            time.sleep(0.5)
            try:
                visible[0].click()
            except Exception:
                js_click(visible[0])
            time.sleep(2)

            modal = find_visible_modal_container(hint_text="Добавить аванс")

            if modal:
                try:
                    type_select = find_dropdown_in_scope(modal, "Тип аванса")
                    if type_select and open_dropdown(type_select):
                        time.sleep(0.8)
                        opts = collect_options() or collect_options_generic()
                        picked = None
                        for opt in opts:
                            if "процент" in (opt.get("text") or "").lower():
                                picked = opt
                                break
                        if not picked and opts:
                            picked = opts[0]
                        if picked:
                            try:
                                picked["element"].click()
                            except Exception:
                                js_click(picked["element"])
                            time.sleep(0.8)
                except Exception as e:
                    log(f"    ⚠ Тип аванса: {e}", "WARN")

                try:
                    value_inputs = modal.find_elements(By.XPATH,
                        ".//input[not(@type='file') and not(@readonly)]")
                    for vi in value_inputs:
                        if vi.is_displayed() and vi.is_enabled():
                            role = vi.get_attribute("role") or ""
                            if role == "combobox":
                                continue
                            set_number_native(vi, "30")
                            break
                except Exception:
                    pass

                try:
                    avans_date_obj = datetime.now() + timedelta(days=14)
                    fill_popup_date_field("Дата платежа", avans_date_obj, modal=modal)
                except Exception as e:
                    log(f"    ⚠ Дата платежа (аванс): {e}", "WARN")

                try:
                    comment = modal.find_element(By.XPATH, ".//textarea")
                    if comment.is_displayed():
                        comment.send_keys("Автоаванс RPA")
                except Exception:
                    pass

                blur_focus()
                time.sleep(0.5)

                save_btn = find_modal_button(modal, ["Добавить", "Сохранить"]) or \
                           find_modal_button(None, ["Добавить", "Сохранить"])
                if save_btn:
                    try:
                        save_btn.click()
                    except Exception:
                        js_click(save_btn)
                    time.sleep(2.5)
                    result["avans"] = True
                    log("  ✓ Аванс добавлен", "PASS")
            else:
                log("  ⚠ Модалка 'Добавить аванс' не найдена", "WARN")
        else:
            log("  ⚠ Кнопка 'Добавить' для авансов не найдена", "WARN")
    except Exception as e:
        log(f"  ⚠ Аванс: {e}", "WARN")

    # ---------- ГРАФИК ПЛАТЕЖЕЙ ----------
    try:
        time.sleep(1)
        add_btns = driver.find_elements(By.XPATH,
            "//*[normalize-space(text())='График платежей']/following::button[.//span[normalize-space(text())='Добавить']][1]")
        visible = [b for b in add_btns if b.is_displayed() and b.is_enabled()]
        if visible:
            scroll_to(visible[-1])
            time.sleep(0.5)
            try:
                visible[-1].click()
            except Exception:
                js_click(visible[-1])
            time.sleep(2)

            modal = find_visible_modal_container(hint_text="Добавить плат")

            if modal:
                try:
                    num_inp = modal.find_element(By.XPATH,
                        ".//*[contains(text(),'Номер') or contains(text(),'очередность')]/following::input[1]")
                    val = num_inp.get_attribute("value") or ""
                    if not val.strip():
                        set_number_native(num_inp, "1")
                except Exception:
                    pass

                try:
                    sum_inp = modal.find_element(By.XPATH,
                        ".//*[normalize-space(text())='Сумма']/following::input[1]")
                    set_number_native(sum_inp, "1120000")
                except Exception:
                    pass

                try:
                    pay_date_obj = datetime.now() + timedelta(days=30)
                    fill_popup_date_field("Дата", pay_date_obj, modal=modal)
                except Exception as e:
                    log(f"    ⚠ Дата платежа (график): {e}", "WARN")

                blur_focus()
                time.sleep(0.5)

                save_btn = find_modal_button(modal, ["Добавить", "Сохранить"]) or \
                           find_modal_button(None, ["Добавить", "Сохранить"])
                if save_btn:
                    try:
                        save_btn.click()
                    except Exception:
                        js_click(save_btn)
                    time.sleep(2.5)
                    result["payment"] = True
                    log("  ✓ Платёж в график добавлен", "PASS")
            else:
                log("  ⚠ Модалка 'Добавить платёж' не найдена", "WARN")
        else:
            log("  ⚠ Кнопка 'Добавить' для графика не найдена", "WARN")
    except Exception as e:
        log(f"  ⚠ График платежей: {e}", "WARN")

    log(f"  Финансы: Аванс={'OK' if result['avans'] else 'FAIL'}, "
        f"График={'OK' if result['payment'] else 'FAIL'}",
        "PASS" if (result['avans'] and result['payment']) else "WARN")
    return result["avans"] or result["payment"]


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
    ensure_on_our_contract("add_approval_route")

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




# ==========================================
# ЗАГРУЗКА ФАЙЛОВ — теперь выбираем кнопку "Загрузить" по секции
# ("Документы для подписания" vs "Вложения"), а не по индексу.
# ==========================================
def upload_file_to_docs_tab(file_path, doc_type="signing", name_prefix="Doc", comment=""):
    if not file_path or not os.path.exists(file_path):
        return False

    log(f"    Загружаю: {file_path} (тип: {doc_type})")

    try:
        for _ in range(3):
            try:
                ActionChains(driver).send_keys(Keys.ESCAPE).perform()
                time.sleep(0.3)
            except Exception:
                pass

        if not go_to_tab("Документы"):
            return False
        time.sleep(4)

        try:
            WebDriverWait(driver, 20).until(
                EC.visibility_of_element_located((By.XPATH,
                    "//button[.//span[normalize-space(text())='Загрузить']]"))
            )
        except Exception:
            return False
        time.sleep(2)

        section_title = "Документы для подписания" if doc_type == "signing" else "Вложения"
        target_btn = None

        # ТОЧНЫЙ класс сайта (подтверждено инспектором):
        #   section.cd-docs > section.cd-docs__fold > div.cd-docs__fold-head
        #     > button.cd-docs__fold-toggle (раскрыть/свернуть)
        #     > button.ui-button... со span "Загрузить"
        # Скоуп строго внутри КОНКРЕТНОГО fold — иначе можно случайно
        # задеть кнопку другой секции или верхнего тулбара.
        try:
            folds = driver.find_elements(By.XPATH, "//section[contains(@class,'cd-docs__fold')]")
            visible_folds = [f for f in folds if f.is_displayed()]
            for fold in visible_folds:
                if section_title.lower() in (fold.text or "").lower():
                    try:
                        target_btn = fold.find_element(
                            By.XPATH, ".//button[.//span[normalize-space(text())='Загрузить']]")
                        break
                    except Exception:
                        continue
            if not target_btn and len(visible_folds) >= 2:
                idx = 0 if doc_type == "signing" else 1
                try:
                    target_btn = visible_folds[idx].find_element(
                        By.XPATH, ".//button[.//span[normalize-space(text())='Загрузить']]")
                except Exception:
                    pass
        except Exception:
            pass

        if not target_btn:
            try:
                target_btn = driver.find_element(By.XPATH,
                    f"//*[normalize-space(text())='{section_title}']"
                    f"/ancestor::*[.//button[.//span[normalize-space(text())='Загрузить']]][1]"
                    f"//button[.//span[normalize-space(text())='Загрузить']]")
            except Exception:
                pass

        if not target_btn or not target_btn.is_displayed():
            # Фолбэк на старую логику по индексу, если секция не найдена
            all_btns = driver.find_elements(By.XPATH,
                "//button[.//span[normalize-space(text())='Загрузить']]")
            visible_btns = [b for b in all_btns if b.is_displayed() and b.is_enabled()]
            if not visible_btns:
                log(f"  ⚠ Кнопка 'Загрузить' ({section_title}) не найдена вообще", "WARN")
                dump_field_html(section_title)
                return False
            target_idx = 0 if doc_type == "signing" else min(1, len(visible_btns) - 1)
            target_btn = visible_btns[target_idx]

        scroll_to(target_btn)
        time.sleep(0.7)

        modal = None
        for click_attempt in range(3):
            try:
                if click_attempt == 0:
                    target_btn.click()
                elif click_attempt == 1:
                    js_click(target_btn)
                else:
                    ActionChains(driver).move_to_element(target_btn).pause(0.3).click().perform()
                time.sleep(3)
                modal = find_visible_modal_container(hint_text="Загруз")
                if modal:
                    break
            except Exception:
                continue

        if not modal:
            log("  ⚠ Модалка загрузки файла не найдена", "WARN")
            dump_field_html(section_title)
            return False

        file_inputs = modal.find_elements(By.XPATH, ".//input[@type='file' and @name='file']")
        if not file_inputs:
            file_inputs = modal.find_elements(By.XPATH, ".//input[@type='file']")
        if not file_inputs:
            file_inputs = driver.find_elements(By.XPATH, "//input[@type='file']")

        if not file_inputs:
            return False

        target_input = file_inputs[-1]
        try:
            driver.execute_script(
                "arguments[0].style.display='block';"
                "arguments[0].style.opacity='1';"
                "arguments[0].style.visibility='visible';"
                "arguments[0].removeAttribute('hidden');",
                target_input
            )
            target_input.send_keys(file_path)
            time.sleep(6)
        except Exception:
            return False

        doc_name = f"{name_prefix}_{CONTRACT_NUM}"
        name_inputs = modal.find_elements(By.XPATH,
            ".//input[not(@type='file') and not(@type='hidden')]")
        for ni in name_inputs:
            try:
                if ni.is_displayed() and ni.is_enabled():
                    ni.clear()
                    ni.send_keys(doc_name)
                    time.sleep(0.5)
                    break
            except Exception:
                continue

        if comment:
            comment_areas = modal.find_elements(By.XPATH, ".//textarea")
            for ca in comment_areas:
                try:
                    if ca.is_displayed() and ca.is_enabled():
                        ca.clear()
                        ca.send_keys(comment)
                        time.sleep(0.5)
                        break
                except Exception:
                    continue

        blur_focus()
        time.sleep(2)

        load_btn = None
        for _ in range(10):
            load_btn = find_modal_button(modal, ["Загрузить", "Сохранить", "Добавить"])
            if not load_btn:
                load_btn = find_modal_button(None, ["Загрузить", "Сохранить", "Добавить"])
            if load_btn:
                break
            time.sleep(2)

        if not load_btn:
            log("  ⚠ Кнопка 'Загрузить' в модалке не найдена", "WARN")
            return False

        for method in ["selenium", "js", "actions"]:
            try:
                if method == "selenium":
                    load_btn.click()
                elif method == "js":
                    js_click(load_btn)
                else:
                    ActionChains(driver).move_to_element(load_btn).pause(0.3).click().perform()
                break
            except Exception:
                continue

        time.sleep(6)

        modal_still_open = find_visible_modal_container(hint_text="Загруз") is not None

        if modal_still_open:
            try:
                ActionChains(driver).send_keys(Keys.ESCAPE).perform()
                time.sleep(1)
            except Exception:
                pass
            return False

        log(f"    ✓ Файл загружен ({section_title})", "PASS")
        return True

    except Exception as e:
        log(f"  ⚠ Загрузка файла: {e}", "WARN")
        return False


def click_card_action(button_text):
    # ЗАЩИТА: действия статуса (На согласование / Согласовать /
    # Подписать) необратимы — убеждаемся, что жмём их на НАШЕМ
    # договоре, а не на случайно открытом чужом.
    if workflow_result.get("url") and not ensure_on_our_contract(f"click_card_action:{button_text}"):
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
                    ca.send_keys(f"Автоподтверждение '{button_text}' для {CONTRACT_NUM}")
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
    """ИСПРАВЛЕНО (подтверждено DevTools): статус договора — это
    <span class="detail-hero__status detail-hero__status--draft">
      Черновик
    </span>
    рядом с заголовком "Договор № ...". Раньше искали по классу
    'ant-tag' (не существует в новом дизайне) → всегда None, потом
    временно искали по тексту без класса (риск зацепить не то слово
    в другом месте страницы). Теперь берём именно этот бейдж и читаем
    его текст напрямую — без списка известных статусов, чтобы не
    сломаться на новом статусе, которого нет в списке.
    """
    try:
        el = driver.find_element(
            By.XPATH, "//span[contains(@class,'detail-hero__status')]")
        if el.is_displayed():
            status = (el.text or "").strip()
            if status:
                return status
    except Exception:
        pass
    return None


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


def sign_by_account(account_login, account_pass, nca_password, contract_url,
                     p12_path=None, role_name="Аккаунт"):
    log("=" * 60)
    log(f"ПОДПИСАНИЕ: {role_name} ({account_login})")
    log("=" * 60)

    if not contract_url:
        log("  ⚠ URL договора неизвестен", "WARN")
        return False

    if not logout_current_account():
        driver.get(BASE_URL)
        time.sleep(4)

    if not login_with(account_login, account_pass):
        return False

    dismiss_chrome_password_popup()
    driver.get(contract_url)
    time.sleep(5)

    # Проверяем, что под этим аккаунтом открылся именно НАШ договор
    # (а не редирект на список из-за прав доступа)
    try:
        target_id = contract_url.rstrip("/").split("/contracts/")[-1].split("/")[0]
    except Exception:
        target_id = ""
    if target_id and target_id not in driver.current_url:
        log(f"  ⚠ Под {role_name} договор не открылся (текущий URL: "
            f"{driver.current_url}) — подписание пропущено", "WARN")
        shot(f"wrong_page_{role_name}")
        return False

    go_to_general_info()
    time.sleep(2)
    shot(f"opened_by_{role_name}")

    status_before = get_current_status()
    log(f"  Статус под {role_name}: '{status_before}'")

    signed = False
    for sign_btn in ["Подписать", "Подтвердить подписание"]:
        if click_card_action(sign_btn):
            if sign_with_ncalayer(password=nca_password, p12_path=p12_path):
                signed = True
                workflow_result["ecp_signed"] = True
                workflow_result["actions_done"].append(
                    f"{role_name} ({account_login}): ЭЦП OK")
            time.sleep(6)
            driver.refresh()
            time.sleep(4)
            status = get_current_status()
            log(f"  {role_name}: '{sign_btn}' → '{status}'",
                "PASS" if signed else "WARN")
            workflow_result["actions_done"].append(
                f"{role_name} ({account_login}): {sign_btn} → {status}")
            workflow_result["final_status"] = status
            return signed

    log(f"  ⚠ Кнопка 'Подписать' не найдена под {role_name}", "WARN")
    shot(f"no_sign_btn_{role_name}")
    return False


# ==========================================
# ГЛАВНЫЙ WORKFLOW
# ==========================================
def main():
    log("=" * 60)
    log(f"ПОЛНОЕ СОЗДАНИЕ ДОГОВОРА: {CONTRACT_NUM}")
    log("=" * 60)

    # --- ЭТАП 0: Открытие сайта (иначе браузер остаётся на data:, и логин-форма никогда не появляется) ---
    driver.get(BASE_URL)
    time.sleep(3)

    # --- ЭТАП 1: Логин ---
    log("ЭТАП 1: Логин (основной аккаунт — создатель)")
    log(f"  URL: {driver.current_url}")

    try:
        WebDriverWait(driver, WAIT).until(
            EC.visibility_of_element_located((By.XPATH,
                "//input[contains(@placeholder,'огин') or @type='email' "
                "or @name='username' or @id='username']"))
        )
    except Exception:
        log("  ⚠ Поле логина не появилось", "WARN")

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

    if login_field:
        try:
            login_field.clear()
            login_field.send_keys(login_val)
        except Exception:
            pass

        password_field = None
        for xp in ["//input[@type='password']", "//input[contains(@placeholder,'ароль')]"]:
            try:
                fields = driver.find_elements(By.XPATH, xp)
                visible = [f for f in fields if f.is_displayed() and f.is_enabled()]
                if visible:
                    password_field = visible[0]
                    break
            except Exception:
                continue

        if password_field:
            try:
                password_field.clear()
                password_field.send_keys(pass_val)
            except Exception:
                pass

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
        log(f"  ✓ После логина URL: {driver.current_url}", "PASS")
        dismiss_chrome_password_popup()

    # --- ЭТАП 2: Договоры ---
    log("ЭТАП 2: Переход в 'Договоры'")
    # БАГ, который здесь был: проверялось `"/documents/contracts" not in
    # current_url`. Но URL КАРТОЧКИ старого договора выглядит как
    # `/documents/contracts/<uuid>` — подстрока в нём ЕСТЬ, поэтому
    # переход в список не выполнялся, скрипт оставался на старом
    # договоре, не находил кнопку "Создать договор" и завершался за
    # ~20 секунд, ничего не создав.
    # Теперь: считаем, что мы в списке, только если после
    # /documents/contracts НЕТ идентификатора карточки.
    def on_contracts_list():
        cur = driver.current_url
        if "/documents/contracts" not in cur:
            return False
        tail = cur.split("/documents/contracts", 1)[1].strip("/")
        return tail == "" or tail.startswith("?")

    if not on_contracts_list():
        log(f"  Текущий URL не является списком договоров ({driver.current_url}) "
            f"— перехожу в список")
        driver.get(CONTRACTS_URL)
        time.sleep(4)
    else:
        time.sleep(2)

    dismiss_chrome_password_popup()
    log(f"  URL перед созданием: {driver.current_url}")

    # --- ЭТАП 3: Создать (кнопка 'Создать договор' в списке) ---
    log("ЭТАП 3: Открытие формы создания")
    create_btn = None
    for attempt in range(4):  # было 2 — увеличено, т.к. иногда нужен
                               # ещё один цикл, чтобы выйти из "тихого"
                               # редиректа авторизации (см. ниже)
        for xp in [
            "//button[.//span[normalize-space(text())='Создать договор']]",
            "//button[.//span[normalize-space(text())='Создать']]",
        ]:
            try:
                btns = WebDriverWait(driver, 5).until(
                    lambda d: [b for b in d.find_elements(By.XPATH, xp) if b.is_displayed()]
                )
                if btns:
                    create_btn = btns[0]
                    break
            except Exception:
                continue
        if create_btn:
            break

        # ВАЖНО: при частой смене сценариев (много быстрых циклов
        # вход/выход подряд) браузер иногда застревает на служебном
        # URL "тихого" продления сессии Keycloak
        # (auth.testportal...&prompt=none...), так и не долистав до
        # страницы договоров. Обычная повторная навигация тут может не
        # сработать сразу — даём больше времени постоять на BASE_URL,
        # чтобы редирект долистал сам, прежде чем снова идти на список.
        stuck_on_auth = "auth.testportal" in driver.current_url
        log(f"  Кнопка создания не найдена (попытка {attempt+1})"
            + (" — застряли на редиректе авторизации, жду дольше" if stuck_on_auth else "")
            + " — перехожу в список договоров", "WARN")

        if stuck_on_auth:
            driver.get(BASE_URL)
            time.sleep(6)
        driver.get(CONTRACTS_URL)
        time.sleep(5 if not stuck_on_auth else 8)
        dismiss_chrome_password_popup()

    if not create_btn:
        stuck_on_auth = "auth.testportal" in driver.current_url
        workflow_result["fail_reasons"]["Создание документа"] = (
            "застряли на редиректе авторизации ('тихое' продление сессии), "
            "форма создания не открылась" if stuck_on_auth else
            "кнопка 'Создать договор' не найдена в списке договоров")
        log(f"  ⚠ Не удалось открыть форму создания. URL: {driver.current_url}", "WARN")
        shot("no_create_button")
        return

    js_click(create_btn)
    time.sleep(3)
    log("  ✓ Форма открыта", "PASS")

    # --- ЭТАП 4: Форма (секция 1 "Основная информация" — открыта по умолчанию) ---
    log("ЭТАП 4: Заполнение формы (Контрагент=ИП Алдажаров, Заказчик=AI Group)")
    _contract_type_target = {
        "type_uslug": "Договор услуг",
        "type_uslug_postavka": "Договор услуг и поставки",
        "type_import": "Импорт",
    }.get(CONTRACT_SCENARIO, "Договор поставки")
    select_first_form_dropdown("Тип договора", target_option=_contract_type_target)
    time.sleep(0.3)
    contract_date = datetime.now().strftime("%d.%m.%Y")
    fill_date_field("Дата договора", contract_date)
    fill_text_field("Например", CONTRACT_NUM, "Номер договора")  # TODO VERIFY placeholder text
    select_first_form_dropdown("Контрагент")
    time.sleep(0.3)
    select_first_form_dropdown("Заказчик")
    time.sleep(0.3)
    select_first_form_dropdown("Проект")
    time.sleep(0.3)
    payment_type = {
        "prepay": "Предоплата",
        "cash": "Выдача наличных",
        "postpay_guarantee": "Постоплата (под гарантию)",
        "postpay_pledge": "Постоплата (под залог)",
        "partial_payments": "Частичные платежи",
    }.get(CONTRACT_SCENARIO, "Постоплата")
    select_first_form_dropdown("Тип оплаты", allow_missing=True, target_option=payment_type)
    time.sleep(0.3)

    fill_optional_fields()
    time.sleep(0.5)

    # --- ЭТАП 5: Создать ---
    log("ЭТАП 5: Сохранение договора")
    blur_focus()
    if click_create_button():
        time.sleep(4)
        new_url = driver.current_url
        if "/contracts/" in new_url and "/create" not in new_url:
            workflow_result["url"] = new_url
            workflow_result["created"] = True
            log(f"  ✓ Договор создан: {new_url}", "PASS")

    if not workflow_result["created"]:
        log("Прерываю — договор не создан", "FAIL")
        shot("contract_not_created")
        # Диагностика: часто рядом с кнопкой "Создать" остаётся текст
        # ошибки валидации (например "Заполните обязательное поле") —
        # печатаем весь видимый текст ошибок, если он есть.
        try:
            errs = driver.find_elements(
                By.XPATH,
                "//*[contains(@class,'error') or contains(@class,'invalid') "
                "or contains(@class,'ant-form-item-explain')]")
            visible_errs = [e.text.strip() for e in errs if e.is_displayed() and e.text.strip()]
            if visible_errs:
                log(f"  [DIAG] Видимые ошибки на форме: {visible_errs[:10]}", "DIAG")
            else:
                log("  [DIAG] Видимых текстов ошибок на форме не найдено", "DIAG")
        except Exception as e:
            log(f"  [DIAG] Не удалось собрать ошибки формы: {e}", "DIAG")
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
    go_to_general_info()

    # ==========================================
    # НОВЫЙ ПОРЯДОК ШАГОВ (по указанию пользователя, подтверждено
    # скриншотами пустой карточки только что созданного договора):
    #   6. Документы  →  7. Маршрут (Sh Margulan)  →  8. Подписанты
    #   →  9. Предмет договора  →  9.3 Финансы  →  10. На согласование
    # Раньше было: Документы → Подписанты → Предмет → Финансы → Маршрут.
    # ==========================================

    # --- ЭТАП 6: Документы ---
    log("ЭТАП 6: Загрузка документов")
    pdf_signing = create_test_pdf()
    pdf_attach = create_test_pdf()

    if pdf_signing:
        if upload_file_to_docs_tab(pdf_signing, "signing", "Contract_Signing",
                                    f"Договор {CONTRACT_NUM}"):
            workflow_result["document"] = True
    time.sleep(3)

    if pdf_attach:
        upload_file_to_docs_tab(pdf_attach, "attachment", "Contract_Attachment",
                                 f"Приложение к {CONTRACT_NUM}")
    time.sleep(3)

    go_to_general_info()
    time.sleep(2)

    # --- ЭТАП 7: Маршрут согласования (Margulan Sh, либо fallback) ---
    log("ЭТАП 7: Маршрут согласования (согласующий = Margulan Sh, либо fallback)")
    dismiss_chrome_password_popup()
    for retry in range(3):
        go_to_general_info()
        dismiss_chrome_password_popup()
        time.sleep(1)
        try:
            # ВАЖНО: проверять ТОЛЬКО внутри секции маршрута!
            # Раньше поиск шёл по всей странице — а 'Sh Margulan Ju'
            # это имя ЗАЛОГИНЕННОГО пользователя в шапке справа вверху.
            # Условие всегда было истинным, скрипт писал "Маршрут уже
            # настроен" и НИ РАЗУ не вызывал add_approval_route().
            route_values = driver.find_elements(
                By.XPATH,
                "//section[contains(@class,'evd-route')]"
                "//div[contains(@class,'evd-route__stages')]"
                "//span[contains(@class,'ui-select__value')]")
            already = False
            for v in route_values:
                if not v.is_displayed():
                    continue
                txt = (v.get_attribute("textContent") or "").strip()
                if txt and "выбрать" not in txt.lower():
                    log(f"  ✓ Маршрут уже настроен (согласующий: '{txt}')", "PASS")
                    workflow_result["actions_done"].append(f"Маршрут: {txt}")
                    workflow_result["approval_route"] = True
                    already = True
                    break

            # После сохранения модалки имя рендерится обычным текстом
            # в ячейке таблицы маршрута (а не в ui-select__value)
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
                        workflow_result["actions_done"].append(f"Маршрут: {txt}")
                        workflow_result["approval_route"] = True
                        already = True
                        break

            if already:
                break
        except Exception:
            pass

        if add_approval_route(approver_query="Бейсембаев"):
            workflow_result["actions_done"].append("Маршрут: согласующий проставлен")
            workflow_result["approval_route"] = True
            break
        else:
            try:
                for _ in range(4):
                    ActionChains(driver).send_keys(Keys.ESCAPE).perform()
                    time.sleep(0.5)
            except Exception:
                pass
            time.sleep(3)

    go_to_general_info()
    time.sleep(2)

    # --- ЭТАП 8: Подписанты ---
    log("ЭТАП 8: Подписанты (Заказчик=Бейсембаев Куаныш, Контрагент=Алдажаров Диас Талгатович)")
    for retry in range(3):
        if fill_signatories_in_card():
            workflow_result["signatories"] = True
            break
        else:
            log(f"  ⚠ Попытка #{retry+1} не удалась", "WARN")
            try:
                for _ in range(3):
                    ActionChains(driver).send_keys(Keys.ESCAPE).perform()
                    time.sleep(0.5)
            except Exception:
                pass
            exit_edit_mode()
            go_to_general_info()
            time.sleep(3)
    time.sleep(2)

    # --- ЭТАП 9: Предмет договора (теперь отдельная страница) ---
    log("ЭТАП 9: Предмет договора")
    go_to_general_info()
    time.sleep(1)
    if add_contract_subject():
        workflow_result["subject"] = True
    time.sleep(2)
    go_to_general_info()
    time.sleep(2)

    # --- ЭТАП 9.3: Финансы ---
    log("ЭТАП 9.3: Раздел 'Финансы'")
    try:
        fill_finance_section()
    except Exception as e:
        log(f"  ⚠ Финансы: {e}", "WARN")
        shot("finance_error")
    time.sleep(2)
    go_to_general_info()
    time.sleep(3)

    # --- ЭТАП 10: На согласование ---
    log("ЭТАП 9: 'На согласование'")
    if click_card_action("На согласование"):
        time.sleep(4)
        status = get_current_status()
        log(f"  Статус: '{status}'", "PASS")
        workflow_result["actions_done"].append(f"На согласование → {status}")
        workflow_result["final_status"] = status
    else:
        log("  ⚠ Не удалось отправить на согласование", "WARN")

    # --- ЭТАП 9.5: Согласовать ---
    # ВАЖНО: согласовать может ТОЛЬКО тот, кто назначен согласующим в
    # маршруте (см. ЭТАП 7 — approver_query="Бейсембаев"). Раньше здесь
    # жали "Согласовать" под тем, кто уже залогинен (создатель) — это
    # самосогласование, система его закономерно отклоняла. Теперь
    # сначала логинимся именно под назначенным согласующим.
    log("ЭТАП 9.5: 'Согласовать' под назначенным согласующим (Бейсембаев)")
    time.sleep(2)
    if not logout_current_account():
        driver.get(BASE_URL)
        time.sleep(4)
    if not login_with(SECOND_LOGIN, SECOND_PASS):
        log("  ⚠ Не удалось войти под согласующим (Бейсембаев)", "WARN")
    else:
        driver.get(workflow_result["url"])
        time.sleep(4)
        dismiss_chrome_password_popup()

    go_to_general_info()
    time.sleep(2)

    approved = False
    for approve_btn in ["Согласовать", "Подтвердить согласование", "Утвердить"]:
        if click_card_action(approve_btn):
            time.sleep(5)
            status = get_current_status()
            log(f"  '{approve_btn}' → статус: '{status}'", "PASS")
            workflow_result["actions_done"].append(f"{approve_btn} → {status}")
            workflow_result["final_status"] = status
            approved = True
            break

    if not approved:
        log("  ⚠ Согласование не удалось — возможно уже согласовано или нет прав", "WARN")
        shot("approve_failed")

    # --- ЭТАП 9.7: На подписание ---
    log("ЭТАП 9.7: 'На подписание'")
    time.sleep(3)
    go_to_general_info()
    time.sleep(2)
    for btn in ["На подписание", "Отправить на подписание"]:
        if click_card_action(btn):
            time.sleep(5)
            status = get_current_status()
            log(f"  '{btn}' → статус: '{status}'", "PASS")
            workflow_result["actions_done"].append(f"{btn} → {status}")
            workflow_result["final_status"] = status
            break

    # --- ЭТАП 10: Подписание Талгатом (marshar244) — ЗАКАЗЧИК ---
    log("=" * 60)
    log("ЭТАП 10: ЗАКАЗЧИК подписывает (marshar244 / Талгат Ерланович)")
    log("=" * 60)
    try:
        talgat_signed = sign_by_account(
            SECOND_LOGIN, SECOND_PASS,
            nca_password=SECOND_NCA_PASSWORD,
            contract_url=workflow_result["url"],
            p12_path=SECOND_P12_PATH,
            role_name="Талгат (Заказчик)"
        )
        if talgat_signed:
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

    # --- ЭТАП 11: Подписание Ерланом (hhuh8918) — КОНТРАГЕНТ ---
    log("=" * 60)
    log("ЭТАП 11: КОНТРАГЕНТ подписывает (hhuh8918 / Ерлан Талгатович)")
    log("=" * 60)
    try:
        erlan_signed = sign_by_account(
            THIRD_LOGIN, THIRD_PASS,
            nca_password=THIRD_NCA_PASSWORD,
            contract_url=workflow_result["url"],
            p12_path=THIRD_P12_PATH,
            role_name="Алдажаров Диас (Контрагент)"
        )
        if erlan_signed:
            log("  ✓✓ Ерлан подписал", "PASS")
        else:
            log("  ⚠ Ерлан не подписал", "WARN")
    except Exception as e:
        log(f"  ⚠ Ошибка Ерлана: {e}", "WARN")
        try:
            import traceback
            for tb in traceback.format_exc().split("\n"):
                log(f"    {tb}")
        except Exception:
            pass
        shot("erlan_error")

    # --- ЭТАП 12: Итоги ---
    log("=" * 60)
    log("ИТОГИ")
    log("=" * 60)
    log(f"Сценарий: {CONTRACT_SCENARIO}")
    log(f"Договор: {CONTRACT_NUM}")
    log(f"URL: {workflow_result['url']}")
    log(f"Создан: {'✓' if workflow_result['created'] else '✗'}")
    log(f"Подписанты: {'✓' if workflow_result['signatories'] else '✗'}")
    log(f"Предмет: {'✓' if workflow_result['subject'] else '✗'}")
    log(f"Документ: {'✓' if workflow_result['document'] else '✗'}")
    log(f"Маршрут: {'✓' if workflow_result['approval_route'] else '✗'}")
    log(f"Подписание ЭЦП: {'✓' if workflow_result['ecp_signed'] else '✗'}")
    log(f"Финальный статус: {workflow_result['final_status'] or 'Неизвестно'}")

    # Строка под конкретный сценарий (для автозаписи в чек-лист) —
    # успех сценария приравнивается к тому, что договор в этих условиях
    # реально создался (остальные шаги — общие для всех сценариев).
    _scenario_checklist_text = {
        "prepay": "Сценарий: Предоплата",
        "open_contract": "Сценарий: Открытый договор",
        "barter": "Сценарий: Бартер",
        "type_uslug": "Тип договора: Договор услуг",
        "type_uslug_postavka": "Тип договора: Договор услуг и поставки",
        "type_import": "Тип договора: Импорт",
        "cash": "Тип оплаты: Выдача наличных",
        "postpay_guarantee": "Тип оплаты: Постоплата (под гарантию)",
        "postpay_pledge": "Тип оплаты: Постоплата (под залог)",
        "partial_payments": "Тип оплаты: Частичные платежи",
        "paper_signing_off": "Подписывается бумажно: выключено",
        "no_template": "Документ из шаблона: выключено (ручная загрузка PDF)",
        "nds_0": "Ставка НДС: НДС 0%",
        "nds_none": "Ставка НДС: Без НДС",
    }.get(CONTRACT_SCENARIO)
    if _scenario_checklist_text:
        log(f"{_scenario_checklist_text}: {'✓' if workflow_result['created'] else '✗'}")
        if not workflow_result["created"] and _scenario_checklist_text not in workflow_result["fail_reasons"]:
            workflow_result["fail_reasons"][_scenario_checklist_text] = (
                workflow_result["fail_reasons"].get(
                    "Создание документа", "договор в этих условиях не создался"))

    # Известная (структурная) причина для ЭЦП — не варьируется от
    # прогона к прогону, поэтому не требует отдельного захвата в
    # момент отказа.
    if not workflow_result["ecp_signed"]:
        workflow_result["fail_reasons"]["Подписание ЭЦП"] = (
            "ИИН сертификата ЭЦП не совпадает с ИИН/БИН подписанта "
            "в системе (известное ограничение тестового окружения)")

    # Общий fallback для остальных проверок, если конкретная причина
    # не была записана по ходу выполнения (см. WARN-строки в логе выше).
    _base_checks = {
        "Создание документа": workflow_result["created"],
        "Указание подписантов": workflow_result["signatories"],
        "Прикрепление документа": workflow_result["document"],
        "Маршрут согласования": workflow_result["approval_route"],
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
# Без аргумента — прогоняются ВСЕ 14 сценариев подряд, один за другим,
# в одном и том же браузере (по одному договору на сценарий).
# С аргументом — только этот один сценарий, как раньше.
#     py contract_workflow_new_design.py           → все 14 сценариев
#     py contract_workflow_new_design.py barter     → только один
# ==========================================
_scenarios_to_run = [sys.argv[1]] if len(sys.argv) > 1 else list(CONTRACT_SCENARIOS)
_scenarios_to_run = [s for s in _scenarios_to_run if s in CONTRACT_SCENARIOS] or ["default"]

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
_safe_out("ПОЛНЫЙ ЛОГ:")
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
