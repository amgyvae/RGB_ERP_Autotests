
from artifact_paths import SCREENS_DIR, LOGS_DIR, screen_path, log_path
from env_config import env, env_list, is_headless  # секреты — из .env / GitHub Secrets
# -*- coding: utf-8 -*-
# ==========================================
# ПОЛНЫЙ АВТОТЕСТ ГПР  (узел Python в студии, сценарий gprFullEdition)
# Цепочка в студии: Start -> OPEN BROWSER -> OPEN URL -> этот скрипт
#
# Процесс:
#   Пользователь 1 (loginERP)  — проверяет список, создаёт ГПР, заполняет график,
#                                настраивает маршрут, отправляет на согласование
#   Пользователь 2 (SECOND)    — согласующий: согласовывает + ЭЦП (NCALayer)
#   Пользователь 3 (THIRD)     — утверждающий: подписывает + ЭЦП (NCALayer)
# ==========================================

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
# Ожидания выполняются явно; быстрые проверки отсутствия не блокируются.
driver.implicitly_wait(0)
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

# ---- доп. настройки (можно не трогать) ----
BASE_URL = "https://testportal.rgbgroup.kz/schedules/gpr"
KC_LOGOUT_URL = "https://auth.testportal.rgbgroup.kz/realms/rgb/protocol/openid-connect/logout"
PROJECT_NAME = "Grand Republic"   # проект, в котором создаём ГПР
WORK_TYPE = "1.1.1 Налоги ТОО"     # «Вид работ» — конечный пункт дерева (точный текст)
WORK_TYPE_SEARCH = "Налоги ТОО"    # что вводить в «Поиск» внутри списка «Вид работ»
PARENT_ROW = "Налоги и сборы"      # «Родительская строка» (пусто = оставить «Корневая строка»)
SECOND_FIO = "Бейсембаев Куаныш Едилович"        # согласующий — ищем строго по ФИО (поиск по email не работает: "Нет данных")
THIRD_FIO = 'Алдaжаров Диасс Андреевичч'  # точное ФИО из списка ERP
SCREEN_DIR = str(SCREENS_DIR)
TIMEOUT = 15
NCA_WAIT = 40     # сколько секунд ждать окно NCALayer
HOLD_OPEN_SECONDS = 0   # держим процесс (и браузер) живым после завершения, чтобы студия его не закрыла
                          # сразу; 0 = отключить и закрываться как раньше

login_val = str(login_val).strip().strip('"')
pass_val = str(pass_val).strip().strip('"')

# ==========================================
import os
import time
import traceback
from datetime import datetime, timedelta

from selenium.common.exceptions import (ElementClickInterceptedException,
                                        StaleElementReferenceException, TimeoutException)
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

RUN_ID = datetime.now().strftime("%d%m_%H%M%S")


def safe_middle_date(base_dt, month_offset=0):
    """Дата «с запасом» — строго в середине месяца (день 10-19).
    В календаре портала видны и серые дни соседних месяцев (напр. «31» слева, «1,2,3,4»
    справа от текущего месяца) — их цифры совпадают с днями текущего месяца по краям сетки.
    Если целиться в день 1-9 или 28-31, можно случайно кликнуть по чужому, серому дню.
    День 10-19 в сетке ровно один — перепутать нечего."""
    year, month = base_dt.year, base_dt.month + month_offset
    while month > 12:
        month -= 12
        year += 1
    while month < 1:
        month += 12
        year -= 1
    day = 10 + (base_dt.day % 10)   # всегда 10..19
    return datetime(year, month, day)


# ---- безопасный вывод: консоль студии в cp1252 и не понимает кириллицу ----
import sys
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

_TR = dict(zip("абвгдеёжзийклмнопрстуфхцчшщъыьэюяАБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ",
               ["a","b","v","g","d","e","e","zh","z","i","y","k","l","m","n","o","p","r","s","t","u","f","h","ts","ch","sh","sch","","y","","e","yu","ya",
                "A","B","V","G","D","E","E","Zh","Z","I","Y","K","L","M","N","O","P","R","S","T","U","F","H","Ts","Ch","Sh","Sch","","Y","","E","Yu","Ya"]))


def to_ascii(msg):
    safe = "".join(_TR.get(ch, ch) for ch in str(msg)).replace("«", '"').replace("»", '"').replace("—", "-")
    return safe.encode("ascii", "replace").decode("ascii")


def log(msg=""):
    msg = str(msg)
    try:
        print(msg)
    except UnicodeEncodeError:
        print(to_ascii(msg))
GPR_TITLE = f"Autotest GPR {RUN_ID}"


class StepFailed(Exception):
    pass


class PersonNotFound(StepFailed):
    pass


class GprTest:
    def __init__(self, drv):
        self.d = drv
        self.results = []
        self.gpr_number = None
        self.gpr_url = None
        self.second_fio = SECOND_FIO
        self.third_fio = THIRD_FIO
        os.makedirs(SCREEN_DIR, exist_ok=True)

    # ===================================================== helpers (Selenium)
    @staticmethod
    def _t(text):
        if '"' not in text:
            return f'"{text}"'
        if "'" not in text:
            return f"'{text}'"
        return "concat(" + ", '\"', ".join(f'"{p}"' for p in text.split('"')) + ")"

    def xp_text(self, text, exact=True, tag="*"):
        t = self._t(text)
        return f"//{tag}[normalize-space(.)={t}]" if exact else f"//{tag}[contains(normalize-space(.), {t})]"

    def visible(self, xpath, timeout=TIMEOUT):
        # Проверяем все совпадения: скрытый первый элемент не блокирует видимый.
        def first_visible(driver):
            for element in driver.find_elements(By.XPATH, xpath):
                try:
                    if element.is_displayed():
                        return element
                except StaleElementReferenceException:
                    continue
            return False
        return WebDriverWait(self.d, timeout, poll_frequency=0.2).until(first_visible)

    def exists(self, xpath, timeout=3):
        try:
            self.visible(xpath, timeout)
            return True
        except TimeoutException:
            return False

    def click(self, xpath, timeout=TIMEOUT):
        end = time.time() + timeout
        while time.time() < end:
            try:
                els = [e for e in self.d.find_elements(By.XPATH, xpath) if e.is_displayed()]
                if els:
                    el = els[-1]
                    self.d.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
                    try:
                        el.click()
                    except ElementClickInterceptedException:
                        self.d.execute_script("arguments[0].click();", el)
                    return el
            except StaleElementReferenceException:
                pass
            time.sleep(0.3)
        raise StepFailed(f"Не найден кликабельный элемент: {xpath}")

    def click_text(self, text, exact=True, tag="*", timeout=TIMEOUT):
        for tg in ("button", "a", "span", "div", tag):
            xp = self.xp_text(text, exact, tg)
            if [e for e in self.d.find_elements(By.XPATH, xp) if e.is_displayed()]:
                return self.click(xp, timeout)
        return self.click(self.xp_text(text, exact, tag), timeout)

    def click_any(self, texts, timeout=TIMEOUT, scope=""):
        end = time.time() + timeout
        while time.time() < end:
            for txt in texts:
                xp = f"{scope}//button[contains(normalize-space(.), {self._t(txt)})]"
                if [e for e in self.d.find_elements(By.XPATH, xp) if e.is_displayed()]:
                    self.click(xp, 3)
                    return txt
            time.sleep(0.5)
        raise StepFailed(f"Ни одна из кнопок не найдена: {texts}")

    def type_into(self, xpath, value, clear=True, timeout=TIMEOUT):
        el = self.visible(xpath, timeout)
        self.d.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
        el.click()
        if clear:
            el.send_keys(Keys.CONTROL, "a")
            el.send_keys(Keys.DELETE)
        el.send_keys(value)
        return el

    def _label_xp(self, label):
        """XPath подписи поля. Если открыта модалка и подпись есть в ней — берём ТОЛЬКО её.
        Иначе «Начало план.» находилась в заголовке таблицы за модалкой, и «первое поле после
        подписи» оказывалось полем «Количество» — туда и печатались все даты."""
        lab = self._t(label)
        in_modal = f"{self.modal()}//*[normalize-space(text())={lab}]"
        if [e for e in self.d.find_elements(By.XPATH, in_modal) if e.is_displayed()]:
            return f"({in_modal})[last()]"
        return f"(//*[normalize-space(text())={lab}])[last()]"

    def input_after_label(self, label):
        return (f"({self._label_xp(label)}/following::*[self::input or self::textarea]"
                f"[not(@type='checkbox') and not(@type='hidden')])[1]")

    def select_after_label(self, label):
        return (f"({self._label_xp(label)}/following::*"
                f"[contains(@class,'select') or @role='combobox' or contains(@class,'dropdown')])[1]")

    def choose_in_dropdown(self, label, search=None, option_text=None, first=False):
        self.click(self.select_after_label(label))
        time.sleep(0.5)
        if search:
            srch = "//input[(contains(@placeholder,'Поиск') or @type='search')]"
            boxes = [e for e in self.d.find_elements(By.XPATH, srch) if e.is_displayed()]
            if boxes:
                boxes[-1].send_keys(search)
                time.sleep(1)
        if first:
            opt = ("//*[(@role='option' or contains(@class,'option') or contains(@class,'item'))"
                   " and string-length(normalize-space(.))>0]")
            self.click(f"({opt})[1]")
        else:
            self.click_text(option_text or search, exact=False)
        time.sleep(0.5)

    def close_popups_in_modal(self, title):
        """Закрыть выпадашку/календарь кликом по заголовку модалки (Escape закрыл бы саму модалку)."""
        try:
            hdr = [e for e in self.d.find_elements(By.XPATH, self.xp_text(title, True)) if e.is_displayed()]
            if hdr:
                self.d.execute_script("arguments[0].click();", hdr[-1])
        except Exception:
            pass
        time.sleep(0.3)

    def fill_date(self, label, dt, modal_title="Добавить строку"):
        """Заполняет дату. Простой ввод текста часто НЕ фиксируется компонентом-календарём
        (поле визуально показывает текст, но внутреннее состояние формы остаётся пустым —
        именно так терялись «плановое начало/конец»). Поэтому после ввода текста ещё и
        кликаем по дню в открывшемся календаре, если он появился — это и есть «настоящее»
        подтверждение выбора для большинства таких виджетов."""
        el = self.visible(self.input_after_label(label))
        self.d.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
        target_day = str(dt.day)
        for fmt in ("%d.%m.%Y", "%Y-%m-%d", "%d/%m/%Y"):
            el.click()
            el.send_keys(Keys.CONTROL, "a")
            el.send_keys(Keys.DELETE)
            el.send_keys(dt.strftime(fmt))
            time.sleep(0.5)

            day_xp = ("//*[(@role='gridcell' or @role='button' or contains(@class,'day') "
                      "or contains(@class,'cell')) and normalize-space(text())="
                      f"'{target_day}' and not(contains(@class,'disabled')) "
                      "and not(contains(@class,'outside')) and not(contains(@class,'other'))]")
            day_cells = [e for e in self.d.find_elements(By.XPATH, day_xp) if e.is_displayed()]
            if day_cells:
                picked = next((c for c in day_cells
                               if "selected" in (c.get_attribute("class") or "")
                               or c.get_attribute("aria-selected") == "true"), day_cells[0])
                self.d.execute_script("arguments[0].scrollIntoView({block:'center'});", picked)
                self.d.execute_script("arguments[0].click();", picked)
                time.sleep(0.4)
            else:
                el.send_keys(Keys.TAB)
                time.sleep(0.4)

            self.close_popups_in_modal(modal_title)
            val = (el.get_attribute("value") or "").strip()
            if dt.strftime("%Y") in val:      # в поле реально дата, а не «18,1» в чужом поле
                log(f"  [i] {label}: {val}")
                return
        ph = el.get_attribute("placeholder") or ""
        raise StepFailed(f"Дата не проставилась в поле «{label}» (найдено поле с placeholder "
                         f"«{ph}», значение «{el.get_attribute('value')}»)")

    def table_cell_is_filled(self, row_marker, column_label):
        """Проверяет по самой таблице (не по модалке), что в колонке column_label для строки,
        содержащей row_marker, стоит не «-» — т.е. значение реально сохранилось на сервере."""
        js = """
        const [rowMarker, colLabel] = arguments;
        const table = document.querySelector('table.evd-lines__table');
        if (!table) return null;
        const ths = [...table.querySelectorAll('thead th')];
        const idx = ths.findIndex(th => th.textContent.trim() === colLabel);
        if (idx < 0) return null;
        const rows = [...table.querySelectorAll('tbody tr')];
        const row = rows.find(r => r.textContent.includes(rowMarker));
        if (!row) return null;
        const cell = row.children[idx];
        if (!cell) return null;
        return cell.textContent.trim();
        """
        val = self.d.execute_script(js, row_marker, column_label)
        return val is not None and val not in ("", "-")

    def get_cell_element(self, row_marker, column_label):
        """Находит WebElement карандаша (✏️) для правки прямо в ячейке таблицы (видно на
        портале рядом с «-» в пустых датах), а если его нет — саму ячейку. Помечает элемент
        временным data-атрибутом, чтобы забрать настоящим WebElement, а не координатами."""
        js = """
        const [rowMarker, colLabel] = arguments;
        const table = document.querySelector('table.evd-lines__table');
        if (!table) return null;
        const ths = [...table.querySelectorAll('thead th')];
        const idx = ths.findIndex(th => th.textContent.trim() === colLabel);
        if (idx < 0) return false;
        const rows = [...table.querySelectorAll('tbody tr')];
        const row = rows.find(r => r.textContent.includes(rowMarker));
        if (!row) return false;
        const cell = row.children[idx];
        if (!cell) return false;
        const pencil = cell.querySelector('svg, button, [class*="edit"], [class*="pencil"]');
        (pencil || cell).setAttribute('data-autotest-cell', '1');
        return true;
        """
        ok = self.d.execute_script(js, row_marker, column_label)
        if not ok:
            return None
        try:
            return self.d.find_element(By.CSS_SELECTOR, "[data-autotest-cell='1']")
        except Exception:
            return None

    def repair_table_date(self, row_marker, column_label, dt):
        """Пытается проставить дату прямо в ячейке таблицы (не в модалке «Добавить строку»),
        когда значение туда не сохранилось. Кликает по ячейке, ищет появившийся инпут/календарь
        и, если получилось — кликает по дню в календаре (это и есть «настоящее» подтверждение)."""
        cell = self.get_cell_element(row_marker, column_label)
        if cell is None:
            return False
        self.d.execute_script("arguments[0].removeAttribute('data-autotest-cell');", cell)
        self.d.execute_script("arguments[0].scrollIntoView({block:'center'});", cell)
        try:
            cell.click()
        except Exception:
            self.d.execute_script("arguments[0].click();", cell)
        time.sleep(0.8)

        target_day = str(dt.day)
        inputs = [e for e in self.d.find_elements(By.XPATH, "//input[@type='text' or not(@type)]")
                  if e.is_displayed()]
        target = inputs[-1] if inputs else None
        if target is not None:
            target.click()
            target.send_keys(Keys.CONTROL, "a")
            target.send_keys(Keys.DELETE)
            target.send_keys(dt.strftime("%d.%m.%Y"))
            time.sleep(0.5)

        day_xp = ("//*[(@role='gridcell' or @role='button' or contains(@class,'day') "
                  "or contains(@class,'cell')) and normalize-space(text())="
                  f"'{target_day}' and not(contains(@class,'disabled')) "
                  "and not(contains(@class,'outside')) and not(contains(@class,'other'))]")
        day_cells = [e for e in self.d.find_elements(By.XPATH, day_xp) if e.is_displayed()]
        if day_cells:
            picked = next((c for c in day_cells
                           if "selected" in (c.get_attribute("class") or "")
                           or c.get_attribute("aria-selected") == "true"), day_cells[0])
            self.d.execute_script("arguments[0].click();", picked)
            time.sleep(0.5)
        elif target is not None:
            target.send_keys(Keys.TAB)
            time.sleep(0.5)
        else:
            return False  # ни инпута, ни календаря не появилось — нечего заполнять

        try:
            self.d.find_element(By.TAG_NAME, "body").click()
        except Exception:
            pass
        time.sleep(1)
        return self.table_cell_is_filled(row_marker, column_label)

    def assert_text(self, text, exact=False, timeout=TIMEOUT, msg=None):
        if not self.exists(self.xp_text(text, exact), timeout):
            raise StepFailed(msg or f"На странице нет текста: «{text}»")

    def modal(self):
        return "//*[@role='dialog' or contains(@class,'modal') or contains(@class,'Modal')]"

    def modal_open(self, title, timeout=5):
        return (self.exists(f"{self.modal()}{self.xp_text(title, False)}", timeout)
                or self.exists(self.xp_text(title, True), 1))

    def screenshot(self, name):
        path = os.path.join(SCREEN_DIR, f"{RUN_ID}_{name}.png")
        try:
            self.d.save_screenshot(path)
        except Exception:
            pass
        return path

    def step(self, name, func, critical=True):
        log(f"\n[STEP] {name}")
        started = time.perf_counter()
        try:
            func()
            self.results.append((name, "OK", "", critical))
            log("  [OK] OK")
        except Exception as e:
            shot = self.screenshot(name.replace(" ", "_")[:40])
            self.results.append((name, "FAIL", f"{e} | скрин: {shot}", critical))
            log(f"  [FAIL] FAIL: {e}\n{traceback.format_exc()}")
            if critical:
                raise
        finally:
            log(f"  [TIME] {name}: {time.perf_counter() - started:.1f} s")

    # ===================================================== авторизация
    def is_login_page(self, timeout=3):
        return self.exists("//input[@type='password']", timeout)

    def login(self, email, password):
        """Вход через страницу Keycloak (auth.testportal.rgbgroup.kz)."""
        self.d.get(BASE_URL)
        time.sleep(2)
        if not self.is_login_page(8):
            self.logout()
        user_xp = ("(//input[@id='username' or @name='username' or @type='email' or @name='email' "
                   "or @name='login' or (@type='text' and not(@readonly))])[1]")
        pass_xp = "(//input[@id='password' or @name='password' or @type='password'])[1]"
        self.type_into(user_xp, email)
        pwd = self.type_into(pass_xp, password)
        # кнопка «Войти» в Keycloak бывает <input type=submit> — жмём Enter, затем кнопку как запасной вариант
        pwd.send_keys(Keys.ENTER)
        time.sleep(2)
        if self.is_login_page(1):
            btn = ("//*[@id='kc-login'] | //input[@type='submit'] | "
                   "//button[@type='submit' or contains(normalize-space(.),'Войти')]")
            try:
                self.click(btn, 5)
            except StepFailed:
                pass
        try:
            WebDriverWait(self.d, 30).until(
                lambda d: not [e for e in d.find_elements(By.XPATH, "//input[@type='password']") if e.is_displayed()])
        except TimeoutException:
            err = ""
            for xp in ["//*[@id='input-error']", "//*[contains(@class,'alert')]", "//*[contains(@class,'error')]"]:
                els = [e.text for e in self.d.find_elements(By.XPATH, xp) if e.is_displayed() and e.text.strip()]
                if els:
                    err = els[0]
                    break
            raise StepFailed(f"Не удалось войти как {email}. {err}")
        time.sleep(2)
        if "/schedules/gpr" not in self.d.current_url:
            self.d.get(BASE_URL)
            time.sleep(3)
        log(f"  [i] вошли как {email} ({self.current_user_name()})")

    def logout(self):
        if self.is_login_page(1):
            return
        self.d.execute_script("window.scrollTo(0,0)")
        try:
            self.click_text("Выйти", exact=False, timeout=5)
        except StepFailed:
            pass
        time.sleep(2)
        # Keycloak может показать страницу подтверждения выхода
        for _ in range(2):
            if self.is_login_page(3):
                break
            try:
                self.click("//*[@id='kc-logout'] | //input[@type='submit'] | "
                           "//button[contains(normalize-space(.),'Выйти') or contains(normalize-space(.),'Logout') "
                           "or contains(normalize-space(.),'Log out') or normalize-space(.)='Да']", 3)
                time.sleep(2)
            except StepFailed:
                pass
            self.d.get(BASE_URL)
            time.sleep(2)
        if not self.is_login_page(5):
            # запасной вариант: прямой выход из Keycloak
            self.d.get(KC_LOGOUT_URL)
            time.sleep(2)
            try:
                self.click("//*[@id='kc-logout'] | //input[@type='submit'] | //button", 3)
            except StepFailed:
                pass
            self.d.delete_all_cookies()
            self.d.get(BASE_URL)
            if not self.is_login_page(10):
                raise StepFailed("Не удалось выйти из учётной записи")

    def current_user_name(self):
        """ФИО из шапки (строка перед «Выйти»)."""
        js = r"""
        const out=[...document.querySelectorAll('body *')].find(e=>e.children.length===0&&e.textContent.trim()==='Выйти');
        if(!out) return '';
        let p=out.parentElement;
        while(p && !p.innerText.includes('Уведомления')) p=p.parentElement;
        if(!p) return '';
        const lines=p.innerText.split('\n').map(s=>s.trim()).filter(Boolean);
        const i=lines.lastIndexOf('Выйти');
        for(let k=i-1;k>=0;k--){const s=lines[k]; if(s.length>2 && s!=='|' && !/^\d+\+?$/.test(s) && s!=='Уведомления') return s;}
        return '';
        """
        try:
            return (self.d.execute_script(js) or "").strip()
        except Exception:
            return ""

    # ===================================================== ЭЦП / NCALayer
    def nca_sign(self, p12_path, nca_password):
        """Выбор .p12 и ввод пароля в окне NCALayer (через pyautogui, окно Java)."""
        import pyautogui
        import pyperclip
        pyautogui.FAILSAFE = False

        def paste(text):
            pyperclip.copy(text)
            time.sleep(0.2)
            pyautogui.hotkey("ctrl", "v")
            time.sleep(0.4)

        keys = ["NCALayer", "Открыть", "Open", "Выбор", "Выберите", "Пароль", "Password"]

        def nca_windows():
            try:
                return [t for t in pyautogui.getAllTitles() if t and any(k.lower() in t.lower() for k in keys)]
            except Exception:
                return []

        end = time.time() + NCA_WAIT
        wins = []
        while time.time() < end and not wins:
            wins = nca_windows()
            time.sleep(1)
        if not wins:
            log("  [!] окно NCALayer не появилось — подпись ЭЦП не запрашивалась")
            return False
        log(f"  [i] окно NCALayer: {wins}")
        try:
            w = pyautogui.getWindowsWithTitle(wins[0])[0]
            w.activate()
        except Exception:
            pass
        time.sleep(1.5)
        # 1) выбор файла ключа
        paste(p12_path)
        pyautogui.press("enter")
        time.sleep(2.5)
        # 2) пароль к ключу
        paste(nca_password)
        pyautogui.press("enter")
        time.sleep(3)
        # 3) подтверждение выбора сертификата / «Подписать» (если окно ещё открыто)
        for _ in range(3):
            if not nca_windows():
                break
            pyautogui.press("enter")
            time.sleep(2.5)
        if nca_windows():
            raise StepFailed("Окно NCALayer не закрылось — проверьте путь к ключу и пароль")
        return True

    def sign_action(self, main_buttons, p12, pwd, comment):
        self.d.get(self.gpr_url)
        time.sleep(3)
        clicked = self.click_any(main_buttons, timeout=20)
        log(f"  [i] нажато «{clicked}»")
        time.sleep(1.5)
        # модалка портала: комментарий + кнопка подтверждения / подписи ЭЦП
        try:
            self.type_into(f"{self.modal()}//textarea", comment, timeout=2)
        except Exception:
            pass
        try:
            c = self.click_any(["Подписать ЭЦП", "ЭЦП", "Выбрать ключ", "Подписать", "Согласовать",
                                "Утвердить", "Подтвердить", "Да"], timeout=4, scope=self.modal())
            log(f"  [i] в окне подтверждения нажато «{c}»")
        except StepFailed:
            pass
        self.nca_sign(p12, pwd)
        time.sleep(3)
        self.d.refresh()
        time.sleep(3)

    # ===================================================== шаги
    def s01_login_first(self):
        self.login(login_val, pass_val)
        self.assert_text("ГПР", exact=True)
        self.assert_text("Выберите проект, чтобы посмотреть его графики")

    def s02_list_page_elements(self):
        for t in ["Создать ГПР", "Все этапы", "Строительство", "Проектирование", "Завершенные", "Сетка", "Лист"]:
            self.assert_text(t)
        self.visible("//input[contains(@placeholder,'Поиск')]")
        self.assert_text("Класс жилья")

    def s03_stage_filters(self):
        badges = {"Строительство": "Строительство", "Проектирование": "Проектирование", "Завершенные": "Завершенный"}
        for f in ["Строительство", "Проектирование", "Завершенные", "Все этапы"]:
            self.click_text(f, exact=False)
            time.sleep(1)
            if f in badges and not self.exists(self.xp_text(badges[f], exact=True), 3):
                raise StepFailed(f"Фильтр «{f}» не показал карточки с бейджем «{badges[f]}»")
        self.assert_text(PROJECT_NAME)

    def s04_view_toggle(self):
        self.click_text("Сетка", exact=False)
        self.assert_text(PROJECT_NAME)
        self.click_text("Лист", exact=False)
        self.assert_text(PROJECT_NAME)

    def s05_search(self):
        box = "//input[contains(@placeholder,'Поиск') and not(ancestor::*[@role='dialog'])]"
        self.type_into(box, "Flagman"); time.sleep(1.5)
        self.assert_text("Flagman")
        self.type_into(box, "zzz_nothing_" + RUN_ID); time.sleep(1.5)
        if self.exists(self.xp_text("Flagman", False), 1):
            raise StepFailed("Поиск по несуществующему значению всё ещё показывает проекты")
        el = self.visible(box); el.send_keys(Keys.CONTROL, "a"); el.send_keys(Keys.DELETE)
        time.sleep(1.5)
        self.assert_text(PROJECT_NAME)

    def s06_create_modal_close_cancel(self):
        self.click_text("Создать ГПР", tag="button")
        if not self.modal_open("Создать ГПР"):
            raise StepFailed("Модалка «Создать ГПР» не открылась")
        for t in ["Проект", "Название", "На основании сметы", "Отмена", "Создать"]:
            self.assert_text(t)
        self.click(f"({self.modal()}//button[.//*[name()='svg'] and string-length(normalize-space(.))=0])[1]")
        time.sleep(1)
        if self.exists(self.xp_text("На основании сметы", True), 2):
            raise StepFailed("Модалка не закрылась по крестику")
        self.click_text("Создать ГПР", tag="button")
        self.click_text("Отмена", tag="button")
        time.sleep(1)
        if self.exists(self.xp_text("На основании сметы", True), 2):
            raise StepFailed("Модалка не закрылась по «Отмена»")

    def s07_create_validation(self):
        self.click_text("Создать ГПР", tag="button")
        self.click(f"{self.modal()}//button[normalize-space(.)='Создать']")
        time.sleep(1.5)
        if self.exists(self.xp_text("ГПР успешно создан", False), 1):
            raise StepFailed("Пустой ГПР создан — нет валидации")
        if not self.exists(self.xp_text("На основании сметы", True), 2):
            raise StepFailed("Пустая форма закрылась без валидации")

    def s08_create_gpr(self):
        if not self.exists(self.xp_text("На основании сметы", True), 1):
            self.click_text("Создать ГПР", tag="button")
        self.choose_in_dropdown("Проект", search=PROJECT_NAME, option_text=PROJECT_NAME)
        self.assert_text(PROJECT_NAME)
        self.type_into(self.input_after_label("Название"), GPR_TITLE)
        self.choose_in_dropdown("На основании сметы", first=True)
        self.click(f"{self.modal()}//button[normalize-space(.)='Создать']")
        self.assert_text("ГПР успешно создан", timeout=20)
        num = self.visible("//*[starts-with(normalize-space(text()),'ГПР-')]", 20)
        self.gpr_number = num.text.strip()
        self.gpr_url = self.d.current_url
        log(f"  [i] создан {self.gpr_number}: {self.gpr_url}")

    def s09_check_card(self):
        self.assert_text("Черновик", exact=True)
        for t in ["Основная информация", "Наименование графика", "Проект", "Автор", "Версия",
                  "Причина изменения версии", "Период графика", "Начало план.", "Конец план.",
                  "Маршрут согласования", "Удалить", "Редактировать", "Отправить на согласование",
                  "Открыть график", "Обсуждение", "История", "Уникальный номер", "Дата создания"]:
            self.assert_text(t)
        self.assert_text(GPR_TITLE, exact=True)
        self.assert_text(PROJECT_NAME)
        self.assert_text("v1", exact=True)

    def is_discussion_field(self, el):
        """Поле «Введите сообщение» справа — не путать с полем причины версии слева."""
        try:
            cls = (el.get_attribute("class") or "")
            ph = (el.get_attribute("placeholder") or "")
            if "mentions" in cls or "сообщение" in ph.lower():
                return True
            # блок «Обсуждение»/«История» — правая колонка; карточка ГПР — левая
            x = self.d.execute_script("return arguments[0].getBoundingClientRect().x;", el)
            card_x = self.d.execute_script(
                "var n=[...document.querySelectorAll('*')].find(e=>e.textContent.trim()==='Основная информация'"
                "&&e.children.length<3); return n? n.getBoundingClientRect().x : 0;")
            return x is not None and card_x is not None and x > card_x + 500
        except Exception:
            return False

    def s10_version_reason(self):
        label = "//*[normalize-space(text())='Причина изменения версии']"
        pencil = f"({label}/following::*[name()='svg'])[1]/.."
        el = self.visible(pencil)
        self.d.execute_script("arguments[0].scrollIntoView({block:'center'}); arguments[0].click();", el)
        # Центрированная форма не относится к обсуждению, даже если её x > 500.
        field_xpath = ("//input[@placeholder='Укажите причину изменения'] | "
                       "//textarea[@placeholder='Укажите причину изменения']")
        text = "Первичная версия (автотест)"
        self.type_into(field_xpath, text)
        save_xpath = ("//*[.//input[@placeholder='Укажите причину изменения'] or "
                      ".//textarea[@placeholder='Укажите причину изменения']]"
                      "//button[normalize-space(.)='Сохранить']")
        self.click(save_xpath)
        WebDriverWait(self.d, TIMEOUT, poll_frequency=0.2).until(
            EC.invisibility_of_element_located((By.XPATH, field_xpath)))
        self.assert_text(text, exact=True, timeout=TIMEOUT,
                         msg="Причина версии не отобразилась после сохранения")

    def refresh_schedule(self):
        """В текущем интерфейсе нет кнопки обновления: заново читаем страницу."""
        self.d.refresh()
        table_xpath = "//table[contains(concat(' ', normalize-space(@class), ' '), ' evd-lines__table ')]"
        open_xpath = "//button[contains(normalize-space(.), 'Открыть график')]"

        def loaded_view(driver):
            for xpath, view in ((table_xpath, "table"), (open_xpath, "card")):
                for element in driver.find_elements(By.XPATH, xpath):
                    try:
                        if element.is_displayed():
                            return view
                    except StaleElementReferenceException:
                        continue
            return False

        view = WebDriverWait(self.d, TIMEOUT, poll_frequency=0.2).until(loaded_view)
        if view == "card":
            self.click(open_xpath)
        self.visible(table_xpath)
        # Дождаться строк или явного пустого состояния, а не только оболочки.
        self.visible(table_xpath + "//tbody/tr")

    def s11_open_schedule(self):
        self.click_text("Открыть график", exact=False, tag="button")
        self.assert_text("Позиции графика")
        for t in ["Таблица", "Диаграмма", "Добавить строку", "История графика", "Наименование", "Статус"]:
            self.assert_text(t)
        self.click_text("Диаграмма", exact=True); time.sleep(1.5)
        self.click_text("Таблица", exact=True); time.sleep(1)
        self.refresh_schedule()

    def field_click(self, label, current_text=None):
        """Клик по выпадающему полю под подписью (по его текущему тексту, напр. «Выберите значение»)."""
        if current_text:
            xp = f"({self._label_xp(label)}/following::*[normalize-space(text())={self._t(current_text)}])[1]"
            if self.exists(xp, 2):
                return self.click(xp)
        return self.click(self.select_after_label(label))

    def s12_add_row(self):
        M = "Добавить строку"
        self.click_text(M, exact=False, tag="button")
        if not self.modal_open(M):
            raise StepFailed("Модалка «Добавить строку» не открылась")
        self.assert_text("Работа")

        # --- Вид работ: дерево с поиском
        self.field_click("Вид работ", "Выберите значение")
        time.sleep(0.8)
        leaf = f"//*[normalize-space(text())={self._t(WORK_TYPE)}]"
        boxes = [e for e in self.d.find_elements(By.XPATH, "//input[contains(@placeholder,'Поиск')]")
                 if e.is_displayed()]
        if boxes:
            boxes[-1].send_keys(WORK_TYPE_SEARCH)
            time.sleep(1.5)
        if not self.exists(leaf, 5):
            raise StepFailed(f"В дереве «Вид работ» нет пункта «{WORK_TYPE}»")
        self.click(leaf)
        time.sleep(1)
        self.assert_text(WORK_TYPE, msg=f"«Вид работ» не выбран ({WORK_TYPE})")
        self.close_popups_in_modal(M)

        # --- Ед. измерения подставляется автоматически из вида работ и недоступна для правки — не трогаем
        try:
            unit = ("(//*[normalize-space(text())='Ед. измерения']/following::*"
                    "[string-length(normalize-space(text()))>0])[1]")
            log(f"  [i] Ед. измерения (автоподстановка): {self.visible(unit, 3).text.strip()}")
        except TimeoutException:
            pass

        # --- Родительская строка: поле показывается, только если в графике уже есть строки-кандидаты
        #     (для первой строки в пустом графике выбирать не из чего, поле просто отсутствует)
        if PARENT_ROW and self.exists(self.xp_text("Родительская строка", True), 2):
            self.field_click("Родительская строка", "Корневая строка")
            time.sleep(0.8)
            opt = f"//*[normalize-space(text())={self._t(PARENT_ROW)} and not(ancestor::table)]"
            if self.exists(opt, 4):
                self.click(opt)
            else:
                log(f"  [!] в «Родительская строка» нет «{PARENT_ROW}», оставляем корневую")
            time.sleep(0.8)
            self.close_popups_in_modal(M)
        else:
            log("  [i] поле «Родительская строка» отсутствует (в графике ещё нет строк) — оставляем как есть")

        # --- числа, даты, примечание
        self.type_into(self.input_after_label("Количество"), "100")
        today = datetime.now()
        # даты «с запасом» — см. safe_middle_date: день 10-19, без риска попасть в серый
        # (чужого месяца) день на краю календарной сетки
        # все даты в ТЕКУЩЕМ месяце: календарь открывается на нём, и клик по «18» попадал
        # в сентябрь даже при введённом «18.10» — поэтому следующий месяц не используем
        d_start_plan = today.replace(day=10)
        d_end_plan = today.replace(day=19)
        d_start_fact = today.replace(day=11)
        d_end_fact = today.replace(day=18)
        self.fill_date("Начало план.", d_start_plan)
        self.fill_date("Конец план.", d_end_plan)
        self.fill_date("Начало факт.", d_start_fact)
        self.fill_date("Конец факт.", d_end_fact)
        self.type_into(self.input_after_label("% выполнения"), "15")
        self.type_into(self.input_after_label("Примечание"), f"Автотест {RUN_ID}")
        qty = (self.visible(self.input_after_label("Количество")).get_attribute("value") or "")
        if not qty.replace(" ", "").startswith("100"):
            raise StepFailed(f"В «Количество» стоит «{qty}» вместо 100 — поле было перезаписано")

        self.click(f"{self.modal()}//button[normalize-space(.)='Добавить']")
        time.sleep(2.5)
        if self.exists(f"{self.modal()}{self.xp_text(M, True)}", 1):
            errs = [e.text for e in self.d.find_elements(By.XPATH,
                    f"{self.modal()}//*[contains(@class,'error') or contains(@class,'invalid')]")
                    if e.is_displayed() and e.text.strip()]
            raise StepFailed(f"Модалка не закрылась после «Добавить»: {'; '.join(errs) or 'ошибка валидации'}")

        # --- проверка: строка появилась (при необходимости раскрываем родителя)
        short = WORK_TYPE.split(" ", 1)[-1]          # «Налоги ТОО»
        row_xp = f"//*[contains(normalize-space(text()), {self._t(short)})]"
        if not self.exists(row_xp, 4) and PARENT_ROW:
            parent = (f"//tr[.//*[contains(normalize-space(text()), {self._t(PARENT_ROW)})]]"
                      f"//*[name()='svg' or self::button][1]")
            try:
                self.click(parent, 4)
                time.sleep(1.5)
            except StepFailed:
                pass
        if not self.exists(row_xp, 6):
            raise StepFailed(f"Строка «{short}» не появилась в таблице графика")

        # --- модалка иногда «принимает» ввод даты визуально, но не сохраняет её на сервере —
        #     проверяем по самой таблице и, если пусто, пытаемся исправить прямо в ячейке
        self.refresh_schedule()
        for col, dt_val in (("Начало план.", d_start_plan), ("Конец план.", d_end_plan),
                            ("Начало факт.", d_start_fact), ("Конец факт.", d_end_fact)):
            if self.table_cell_is_filled(short, col):
                continue
            log(f"  [!] «{col}» не сохранилось для строки «{short}» — пробую исправить прямо в таблице")
            if not self.repair_table_date(short, col, dt_val):
                raise StepFailed(f"«{col}» не сохраняется ни в модалке «Добавить строку», ни при правке "
                                 f"прямо в таблице для строки «{short}». Похоже, поле требует именно клика "
                                 f"по дню в календаре в другом месте формы — нужно посмотреть на портале вручную.")

    def s13_history_and_back(self):
        self.click_text("История графика", exact=True, tag="button")
        time.sleep(1.5)
        self.d.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
        time.sleep(0.5)
        self.click_text("Вернуться к основной информации", exact=False)
        self.assert_text("Основная информация")

    def _visible_options(self):
        """Варианты в открытом списке выбора сотрудника (без полей ввода и заголовка «Внутренние»)."""
        xp = ("//*[(@role='option' or contains(@class,'option') or contains(@class,'item')) "
              "and string-length(normalize-space(.))>0 and not(.//input)]")
        return [e for e in self.d.find_elements(By.XPATH, xp)
                if e.is_displayed() and e.text.strip() and e.text.strip() not in ("Внутренние", "Внешние")]

    def _find_search_box(self, timeout=6):
        """Явно находит открывшееся поле поиска внутри выпадающего списка сотрудников.
        НЕ полагается на document.activeElement: если фокус не попал в инпут, активным
        элементом оказывается <body>, и Ctrl+A/Delete превращаются в «выделить всю страницу»
        и попытку удалить это выделение — то, что вы видели на скриншоте."""
        xp = ("//input[contains(@placeholder,'Поиск') or @type='search' "
              "or contains(@class,'search')]")
        end = time.time() + timeout
        while time.time() < end:
            boxes = [e for e in self.d.find_elements(By.XPATH, xp) if e.is_displayed()]
            if boxes:
                return boxes[-1]
            time.sleep(0.3)
        # запасной вариант: активный элемент, но только если это реально поле ввода
        act = self.d.switch_to.active_element
        if act.tag_name in ("input", "textarea"):
            return act
        raise StepFailed("Список сотрудников не открылся: поле поиска не появилось")

    @staticmethod
    def _person_name_matches(label, fio):
        """Сравниваем строку имени отдельно от email/должности.

        Допускается отсутствие отчества, но не другое отчество.
        """
        expected = fio.casefold().replace("a", "а").split()
        for line in label.splitlines():
            actual = line.casefold().replace("a", "а").split()
            if sorted(actual) == sorted(expected):
                return True
            if len(expected) == 3 and len(actual) == 2 and sorted(actual) == sorted(expected[:2]):
                return True
        return False

    def _pick_person(self, placeholder, fio, open_dropdown=True):
        """Выбирает кнопку option в панели, связанной с конкретным полем."""
        trigger_xpath = ("//button[@aria-haspopup='listbox' and "
                         f".//span[normalize-space(.)={self._t(placeholder)}]]")
        trigger = self.visible(trigger_xpath)
        if open_dropdown and trigger.get_attribute("aria-expanded") != "true":
            trigger.click()
        panel_id = trigger.get_attribute("aria-controls")
        if not panel_id:
            raise StepFailed(f"У поля «{placeholder}» отсутствует aria-controls")
        panel_xpath = f"//*[@role='listbox' and @id={self._t(panel_id)}]"
        self.visible(panel_xpath)
        self.type_into(panel_xpath + "//input[contains(@class,'ui-select__search-input')]",
                       "Алд" if fio == THIRD_FIO else fio.split()[0])
        option_xpath = panel_xpath + "//button[@role='option']"

        def matching_option(driver):
            matches = []
            for option in driver.find_elements(By.XPATH, option_xpath):
                try:
                    if option.is_displayed() and option.is_enabled() and self._person_name_matches(option.text.strip(), fio):
                        matches.append(option)
                except StaleElementReferenceException:
                    continue
            if len(matches) > 1:
                raise StepFailed(f"Несколько сотрудников совпадают с ФИО «{fio}»")
            return matches[0] if matches else False

        try:
            option = WebDriverWait(self.d, TIMEOUT, poll_frequency=0.2).until(matching_option)
        except TimeoutException:
            found = [o.text.strip() for o in self.d.find_elements(By.XPATH, option_xpath) if o.is_displayed()]
            raise PersonNotFound(f"В списке «{placeholder}» не найдено «{fio}». Варианты: {found}")
        name = option.text.strip()
        self.d.execute_script("arguments[0].scrollIntoView({block:'nearest'});", option)
        option.click()

        def selection_applied(driver):
            # В маршруте select заменяется сохранённой строкой сотрудника.
            if placeholder == "Выбрать согласующего":
                cells = driver.find_elements(By.XPATH,
                    "//td[contains(concat(' ', normalize-space(@class), ' '), ' evd-route__td--name ')]")
                for cell in cells:
                    try:
                        if cell.is_displayed() and self._person_name_matches(cell.text.strip(), fio):
                            return True
                    except StaleElementReferenceException:
                        continue
            triggers = driver.find_elements(By.XPATH,
                f"//button[@aria-haspopup='listbox' and @aria-controls={self._t(panel_id)}]")
            for current in triggers:
                try:
                    if (current.is_displayed() and current.get_attribute("aria-expanded") == "false"
                            and self._person_name_matches(current.text.strip(), fio)):
                        return True
                except StaleElementReferenceException:
                    continue
            return False

        WebDriverWait(self.d, TIMEOUT, poll_frequency=0.2).until(selection_applied,
            message=f"После клика сотрудник «{fio}» не появился в поле «{placeholder}»")
        return name

    def _pick_owned_person(self, placeholder, role):
        accounts = [
            (THIRD_FIO, (THIRD_LOGIN, THIRD_PASS, THIRD_P12_PATH, THIRD_NCA_PASSWORD)),
        ]
        for index, (fio, account) in enumerate(accounts):
            try:
                name = self._pick_person(placeholder, fio, open_dropdown=index == 0)
            except PersonNotFound:
                continue
            setattr(self, role + "_account", account)
            log(f"  [i] {role}: {fio} ({account[0]})")
            return name
        raise StepFailed(f"В списке «{placeholder}» не найден аккаунт Алдажарова (поиск по «Алд»)")

    def s14_route(self):
        self.click("//button[contains(normalize-space(.),'Этап') and not(contains(.,'Добавить'))]")
        self.assert_text("1 этап", timeout=10)
        name = self._pick_owned_person("Выбрать согласующего", "reviewer")
        log(f"  [i] согласующий: {name}")
        self.assert_text(name.split("\n")[0])

    def s15_approver(self):
        self.click("(//*[contains(normalize-space(text()),'Утвержда')]/following::button"
                   "[contains(normalize-space(.),'Добавить')])[1]")
        name = self._pick_owned_person("Выберите утверждающего", "approver")
        log(f"  [i] утверждающий: {name}")
        section = "//section[.//h2[normalize-space(.)='Утверждающий']]"
        save = section + "//button[normalize-space(.)='Сохранить']"
        self.click(save)
        WebDriverWait(self.d, TIMEOUT, poll_frequency=0.2).until(
            EC.invisibility_of_element_located((By.XPATH, save)))
        self.visible(section + "//*[normalize-space(.)=" + self._t(name) + "]")
        if self.exists(self.xp_text("Утверждающий не назначен", False), 2):
            raise StepFailed("Утверждающий не назначился")

    def s16_discussion(self):
        self.click_text("Обсуждение", exact=True)
        msg = f"Автотест: комментарий {RUN_ID}"
        self.type_into("//textarea[contains(@placeholder,'Введите сообщение')] | "
                       "//input[contains(@placeholder,'Введите сообщение')]", msg)
        self.click_text("Отправить", exact=True, tag="button")
        self.assert_text(msg, timeout=10)
        self.click_text("История", exact=True); time.sleep(1.5)
        self.click_text("Обсуждение", exact=True)

    def s17_edit_open_cancel(self):
        self.d.execute_script("window.scrollTo(0,0)")
        self.click_text("Редактировать", exact=True, tag="button")
        time.sleep(1.5)
        if self.exists(self.xp_text("Отмена", True, "button"), 3):
            self.click_text("Отмена", exact=True, tag="button")
        else:
            self.d.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
        time.sleep(1)
        self.assert_text(GPR_TITLE)

    def s18_send_to_approval(self):
        self.d.execute_script("window.scrollTo(0,0)")
        self.click_text("Отправить на согласование", exact=True, tag="button")
        time.sleep(2)

        # подтверждение может быть модалкой, тостом или без него вовсе — пробуем везде, не только в modal()
        for xp in [f"{self.modal()}//button[contains(normalize-space(.), {self._t(t)})]"
                   for t in ("Подтвердить", "Да", "Отправить", "ОК", "OK", "Продолжить")] + \
                  [f"//button[contains(normalize-space(.), {self._t(t)})]"
                   for t in ("Подтвердить", "Да, отправить", "Продолжить")]:
            els = [e for e in self.d.find_elements(By.XPATH, xp) if e.is_displayed()]
            if els:
                self.click(xp, 3)
                log(f"  [i] подтвердил отправку кнопкой по xpath: {xp}")
                time.sleep(1.5)
                break

        # если появилась ошибка валидации — покажем её текст сразу, не дожидаясь конца шага
        err_xp = ("//*[contains(@class,'error') or contains(@class,'toast') or contains(@class,'alert') "
                  "or contains(@class,'notification')]")
        errs = [e.text.strip() for e in self.d.find_elements(By.XPATH, err_xp) if e.is_displayed() and e.text.strip()]
        if errs:
            log(f"  [i] сообщения на странице после клика: {errs}")

        time.sleep(2)
        self.d.refresh(); time.sleep(3)
        if self.exists(self.xp_text("Черновик", True), 2):
            shot = self.screenshot("18_status_still_chernovik")
            errs2 = [e.text.strip() for e in self.d.find_elements(By.XPATH, err_xp) if e.is_displayed() and e.text.strip()]
            raise StepFailed("Статус остался «Черновик» после отправки на согласование. "
                             f"Сообщения на странице: {errs + errs2 or 'нет видимых ошибок'}. Скрин: {shot}")

    def s19_approve_first(self):
        """Согласование под аккаунтом, выбранным на шаге маршрута."""
        if self.reviewer_account[0] != login_val:
            self.logout()
            self.login(*self.reviewer_account[:2])
        self.d.get(self.gpr_url)
        status_xpath = "//*[contains(concat(' ', normalize-space(@class), ' '), ' detail-hero__status ')]"
        self.visible(status_xpath + "[normalize-space(.)='На согласовании']", timeout=15)
        header = "//*[contains(concat(' ', normalize-space(@class), ' '), ' detail-header__actions ')]"
        # В текущем UI согласование тоже называется «Утвердить».
        self.click(header + "//button[normalize-space(.)='Согласовать' or normalize-space(.)='Утвердить']", 15)
        time.sleep(1.5)
        try:
            self.type_into(f"{self.modal()}//textarea", "Согласовано автотестом", timeout=2)
        except TimeoutException:
            pass
        try:
            self.click_any(["Согласовать", "Утвердить", "Подтвердить", "Да", "ОК"], timeout=3, scope=self.modal())
        except StepFailed:
            pass
        expected_status = status_xpath + "[normalize-space(.)='На утверждении']"
        if not self.exists(expected_status, 15):
            self.d.refresh()
            if not self.exists(expected_status, 10):
                actual = [e.text.strip() for e in self.d.find_elements(By.XPATH, status_xpath) if e.is_displayed()]
                raise StepFailed(f"После согласования ожидался статус «На утверждении», получено: {actual}")

    def s20_sign_approver(self):
        """Вход и подпись только аккаунтом назначенного утверждающего."""
        login_, password, p12, nca_password = self.approver_account
        if login_ != self.reviewer_account[0]:
            self.logout()
            self.login(login_, password)
        self.d.get(self.gpr_url)
        self.assert_text("На утверждении", timeout=15)
        self.sign_action(["Утвердить", "Подписать ЭЦП", "Подписать"],
                         p12, nca_password, "Утверждено автотестом")
        final = ["Утвержден", "Утверждён", "Подписан", "Подписано"]
        if not self.exists(" | ".join(self.xp_text(st, False) for st in final), 12):
            raise StepFailed("После подписи итоговый статус не найден")

    def s21_verify_in_list(self):
        self.d.get(BASE_URL); time.sleep(2)
        self.click_text(PROJECT_NAME, exact=False)
        self.assert_text(GPR_TITLE, timeout=15, msg="Созданный ГПР не найден в списке графиков проекта")

    # ===================================================== запуск
    def run(self):
        steps = [
            ("01 Вход пользователем 1", self.s01_login_first, True),
            ("02 Элементы страницы списка ГПР", self.s02_list_page_elements, False),
            ("03 Фильтры этапов", self.s03_stage_filters, False),
            ("04 Переключение Сетка/Лист", self.s04_view_toggle, False),
            ("05 Поиск по проектам", self.s05_search, False),
            ("06 Модалка: крестик и Отмена", self.s06_create_modal_close_cancel, False),
            ("07 Модалка: валидация пустой формы", self.s07_create_validation, False),
            ("08 Создание ГПР", self.s08_create_gpr, True),
            ("09 Проверка карточки ГПР", self.s09_check_card, False),
            ("10 Причина изменения версии", self.s10_version_reason, False),
            ("11 Открыть график, вкладки", self.s11_open_schedule, True),
            ("12 Добавление строки графика", self.s12_add_row, True),
            ("13 История графика и возврат", self.s13_history_and_back, True),
            ("14 Маршрут: этап и согласующий", self.s14_route, True),
            ("15 Назначение утверждающего", self.s15_approver, True),
            ("16 Обсуждение и История", self.s16_discussion, False),
            ("17 Редактировать (открыть/отменить)", self.s17_edit_open_cancel, False),
            ("18 Отправка на согласование", self.s18_send_to_approval, True),
            ("19 Согласование назначенным аккаунтом", self.s19_approve_first, True),
            ("20 Утверждение + ЭЦП назначенным аккаунтом", self.s20_sign_approver, True),
            ("21 ГПР виден в списке проекта", self.s21_verify_in_list, False),
        ]
        try:
            for name, fn, critical in steps:
                self.step(name, fn, critical)
        except Exception:
            log("\n[STOP] Критический шаг упал, тест остановлен")
        finally:
            self.report()
            self.hold_browser_open()
        failed_all = [n for n, s, _, _ in self.results if s != "OK"]
        failed_critical = [n for n, s, _, crit in self.results if s != "OK" and crit]
        if failed_critical or len(self.results) != len(steps):
            nums = [n.split()[0] for n in (failed_critical or failed_all)]
            first = next(((n, c) for n, st, c, crit in self.results if st != "OK" and (crit or not failed_critical)),
                        ("", ""))
            raise Exception(to_ascii(f"GPR autotest FAILED, steps: {nums}. "
                                     f"First error [{first[0]}]: {first[1]}. Report: {SCREEN_DIR}"))
        elif failed_all:
            log(f"\n[WARN] Некритичные шаги не прошли: {failed_all}. Основной сценарий выполнен полностью.")

    def hold_browser_open(self):
        """Скрипт не закрывает браузер сам (нет driver.quit()) — его закрывает студия, когда
        скрипт-нода завершится. Чтобы можно было посмотреть на результат, держим процесс живым."""
        if HOLD_OPEN_SECONDS <= 0:
            return
        mins = HOLD_OPEN_SECONDS // 60
        log(f"\n[i] Держу браузер открытым ~{mins} мин., чтобы можно было посмотреть результат.")
        log("[i] Чтобы закрыть раньше — нажмите квадратную кнопку Stop в студии.")
        end = time.time() + HOLD_OPEN_SECONDS
        while time.time() < end:
            time.sleep(5)
            try:
                _ = self.d.current_url  # если браузер закрыли вручную — выходим сразу, не ждём до конца
            except Exception:
                log("[i] Браузер закрыт вручную — завершаю ожидание.")
                break

    def report(self):
        ok = sum(1 for _, s, _, _ in self.results if s == "OK")
        lines = [f"ОТЧЁТ АВТОТЕСТА ГПР  {datetime.now():%d.%m.%Y %H:%M:%S}",
                 f"ГПР: {self.gpr_number or '-'}  ({GPR_TITLE})  {self.gpr_url or ''}",
                 f"Итого: {ok}/{len(self.results)} шагов успешно", "-" * 70]
        lines += [f"[{s:4}]{'(некрит.)' if not crit and s != 'OK' else ''} {n}" +
                  (f"\n        {c}" if c else "") for n, s, c, crit in self.results]
        text = "\n".join(lines)
        log("\n" + text)
        with open(log_path(f"gpr_report_{RUN_ID}.txt"), "w", encoding="utf-8") as f:
            f.write(text)


GprTest(driver).run()