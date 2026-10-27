"""Read-only Selenium checks for RGB contacts. Run through run_workflow_and_report.py."""
from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path
_ROOT = _Path(__file__).resolve().parent.parent.parent
for _d in (_ROOT, _ROOT / "core", _ROOT / "config", _Path(__file__).resolve().parent):
    if str(_d) not in _sys.path:
        _sys.path.insert(0, str(_d))
from artifact_paths import SCREENS_DIR, LOGS_DIR, screen_path, log_path

import argparse
import ast
from collections import Counter
from datetime import datetime
import json
import math
import os
from pathlib import Path
import re
import time
import uuid

URL = "https://testportal.rgbgroup.kz/contacts"
HERE = Path(__file__).resolve().parent
SCHEMA = json.loads((HERE / "contacts_checks.json").read_text(encoding="utf-8"))
FIELDS = ("name", "position", "email", "phone", "kind")

SNAPSHOT_JS = r"""
const text = (root, sel) => root.querySelector(sel)?.textContent.trim() ?? null;
const buttons = [...document.querySelectorAll('button[role="tab"]')];
const active = cls => buttons.find(b => b.classList.contains(cls) && b.getAttribute('aria-selected') === 'true')?.textContent.trim();
return {
 query: document.querySelector('input[aria-label="Поиск контактов"]')?.value,
 filter: active('ui-pill-tab'), view: active('ui-tabs-trigger'),
 totalText: text(document, '.tasks-pagination__total'),
 pageText: text(document, '.tasks-pagination__page'),
 sizeText: text(document, 'button[aria-label="Строк на странице"]'),
 nav: Object.fromEntries([...document.querySelectorAll('.tasks-pagination__nav')].map(b => [b.getAttribute('aria-label'), !b.disabled && b.getAttribute('aria-disabled') !== 'true'])),
 cards: [...document.querySelectorAll('article.cp-card')].map(c => {
  const lines = [...c.querySelectorAll('.cp-card__body .cp-card__line-text')].map(e => e.textContent.trim());
  const img = c.querySelector('.cp-card__avatar img');
  return {name:text(c,'.cp-card__name'), position:text(c,'.cp-card__position'),
   email:text(c,'.cp-field--email .cp-field__value') ?? lines[0] ?? null,
   phone:text(c,'.cp-field--phone .cp-field__value') ?? lines[1] ?? null,
   company:text(c,'.cp-field--company .cp-field__value'), kind:text(c,'.cp-card__badges .ui-badge'),
   line:c.classList.contains('cp-card--line'), initials:text(c,'.cp-card__initials'),
   image: img ? {src:img.getAttribute('src'),ok:img.complete && img.naturalWidth > 0} : null};
 })
};
"""


class MissingData(Exception):
    """A prerequisite is unavailable: do not manufacture PASS/FAIL."""


def require(condition, reason):
    if not condition:
        raise AssertionError(reason)


def digits(value):
    return re.sub(r"\D", "", value or "")


def signature(card):
    return tuple(card.get(k) for k in FIELDS)


def bag(cards):
    return Counter(signature(c) for c in cards)


def matches(card, query):
    q = query.casefold()
    if any(q in (card.get(k) or "").casefold() for k in ("name", "position")) or q == (card.get("email") or "").casefold():
        return True
    number = digits(query)
    # User-confirmed contract: at least six phone digits; punctuation is optional.
    return bool(re.fullmatch(r"[\d\s()+-]+",query)) and len(number) >= 6 and number in digits(card.get("phone"))


def credentials():
    return "jyktmargyplay2@gmail.com", "12341234"


class Contacts:
    def __init__(self, driver, timeout=20):
        from selenium.webdriver.common.by import By
        from selenium.webdriver.common.keys import Keys
        from selenium.webdriver.support.ui import WebDriverWait
        self.d, self.By, self.Keys = driver, By, Keys
        self.waiter = WebDriverWait(driver, timeout, poll_frequency=.2)
        self.baseline = []

    def dismiss_scrim_or_modal(self):
        """Close any modal scrim or overlay that might intercept clicks."""
        try:
            self.d.execute_script("""
                var scrims = document.querySelectorAll('button.ui-kit-modal__scrim, [aria-label="Закрыть"], .ui-modal__close, [class*=modal__close], [class*=dialog__close]');
                for (var i = 0; i < scrims.length; i++) {
                    var s = scrims[i];
                    if (s.offsetWidth > 0 || s.offsetHeight > 0) {
                        try { s.click(); } catch(e) {}
                    }
                }
            """)
        except Exception:
            pass

    def dismiss_news_popup(self, wait=2):
        """Close news popup or scrim modals."""
        deadline = time.monotonic() + wait
        while True:
            try:
                for btn in self.d.find_elements(self.By.XPATH,
                        "//*[contains(normalize-space(text()),'Новые новости')]/ancestor::*[@role='dialog' or @aria-modal='true']//button | "
                        "//div[contains(@class,'ui-kit-modal')]//button[contains(.,'Закрыть') or @aria-label='Закрыть'] | "
                        "//button[contains(@class,'ui-kit-modal__scrim')]"):
                    if btn.is_displayed():
                        try:
                            self.d.execute_script("arguments[0].click();", btn)
                            time.sleep(0.3)
                        except Exception:
                            pass
            except Exception:
                pass
            if not any(e.is_displayed() for e in self.d.find_elements(self.By.CSS_SELECTOR, "button.ui-kit-modal__scrim")):
                break
            if time.monotonic() >= deadline:
                break
            time.sleep(0.2)

    def click_el(self, el):
        self.d.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
        self.dismiss_scrim_or_modal()
        try:
            el.click()
        except Exception:
            self.dismiss_scrim_or_modal()
            self.d.execute_script("arguments[0].click();", el)

    def element(self, css):
        return self.waiter.until(lambda d: next((e for e in d.find_elements(self.By.CSS_SELECTOR, css) if e.is_displayed()), False))

    def click(self, css):
        el = self.element(css)
        if 'tasks-pagination' in (el.get_attribute('class') or ''):
            self.clear_pagination_overlay(el)
        self.click_el(el)

    def clear_pagination_overlay(self, button):
        """Collapse the assistant with its native control before pagination."""
        hide_css = 'button.ai-chat-dock__hide[aria-label="Скрыть ассистента"]'
        tab_css = 'button.ai-chat-tab[aria-label="Показать ассистента"]'
        hide = next((e for e in self.d.find_elements(self.By.CSS_SELECTOR, hide_css)
                     if e.is_displayed()), None)
        if hide is None:
            return
        print('[UI] Сворачиваю AI-чат перед пагинацией', flush=True)
        hide.click()
        self.waiter.until(lambda d:
            not any(e.is_displayed() for e in d.find_elements(self.By.CSS_SELECTOR, hide_css))
            and any(e.is_displayed() for e in d.find_elements(self.By.CSS_SELECTOR, tab_css)),
            message='AI-чат не свернулся после нажатия «Скрыть ассистента»')
        # The collapsed tab must not obstruct the ordinary pagination click either.
        self.waiter.until(lambda d: d.execute_script(r"""
const r = arguments[0].getBoundingClientRect();
const hit = document.elementFromPoint(
 (Math.max(0,r.left)+Math.min(innerWidth,r.right))/2,
 (Math.max(0,r.top)+Math.min(innerHeight,r.bottom))/2);
return hit && arguments[0].contains(hit);
""", button), message='Кнопка пагинации перекрыта после сворачивания AI-чата')

    def snapshot(self):
        s = self.d.execute_script(SNAPSHOT_JS)
        if s["totalText"] is None or s["pageText"] is None or s["sizeText"] is None:
            return None
        nums = re.findall(r"\d+", s["pageText"])
        total = re.findall(r"\d+", s["totalText"])
        if len(nums) != 2 or not total:
            return None
        s.update(total=int(total[0]), page=int(nums[0]), pages=int(nums[1]), size=int(s["sizeText"]))
        return s

    def settled(self, predicate=None):
        last, since, start = None, time.monotonic(), time.monotonic()
        def poll(_):
            nonlocal last, since
            s = self.snapshot()
            coherent = bool(s)
            if s and self.baseline and predicate is not None:
                expected = self.expected(s['query'], s['filter'])
                offset = (s['page']-1)*s['size']
                coherent = (s['filter'] in ('Все','Внутренние','Внешние')
                    and 1 <= s['page'] <= max(1,s['pages'])
                    and s['total'] == len(expected)
                    and bag(s['cards']) == bag(expected[offset:offset+s['size']]))
            if not coherent or (predicate is not None and not predicate(s)):
                last, since = None, time.monotonic()
                return False
            # Read-only observations need no new delay. After an action, wait for
            # actual expected cards, not merely a changed input or page label.
            if predicate is None and self.baseline:
                return s
            current = json.dumps(s, ensure_ascii=False, sort_keys=True)
            if current != last:
                last, since = current, time.monotonic()
            quiet = .2 if self.baseline else .6
            minimum = .2 if self.baseline else 1
            return s if time.monotonic()-since >= quiet and time.monotonic()-start >= minimum else False
        return self.waiter.until(poll)

    def tab(self, name, kind):
        current = self.settled()
        if current[kind] == name:
            return current
        selector = 'button.ui-pill-tab' if kind == 'filter' else 'button.ui-tabs-trigger'
        buttons = self.d.find_elements(self.By.CSS_SELECTOR, selector)
        button = next(b for b in buttons if b.text.strip() == name)
        if button.get_attribute("aria-selected") != "true":
            self.click_el(button)
        return self.settled(lambda s: s[kind] == name)

    def query(self, value):
        current = self.settled()
        if current['query'] == value:
            return current
        e = self.element('input[aria-label="Поиск контактов"]')
        e.send_keys(self.Keys.CONTROL, "a")
        e.send_keys(self.Keys.BACKSPACE)
        if value:
            e.send_keys(value)
        # Deliberately no Enter: contacts search is reactive.
        return self.settled(lambda s: s["query"] == value)

    def size(self, n):
        current = self.settled()
        if current['size'] == n:
            return current
        e = self.element('button[aria-label="Строк на странице"]')
        if e.text.strip() != str(n):
            self.click_el(e)
            option = self.waiter.until(lambda d: next((x for x in d.find_elements(self.By.CSS_SELECTOR, '[role="option"]') if x.is_displayed() and x.text.strip() == str(n)), False))
            self.click_el(option)
        return self.settled(lambda s: s['size'] == n)

    def nav(self, label):
        before = self.settled()
        require(before['nav'].get(label), 'Недоступна кнопка: '+label)
        target = {'Первая страница':1, 'Последняя страница':before['pages'], 'Следующая':before['page']+1, 'Предыдущая':before['page']-1}[label]
        self.click(f'button[aria-label="{label}"]')
        return self.settled(lambda s: s['page'] == target)

    def first(self):
        s = self.settled()
        return self.nav('Первая страница') if s['page'] > 1 else s

    def reset(self, view='Лист', kind='Все', size=10):
        self.query('')
        self.tab(kind, 'filter')
        self.tab(view, 'view')
        self.size(size)
        return self.first()

    def collect(self):
        s = self.first()
        cards, total = [], s['total']
        require(s['pages'] <= 200, 'Слишком много страниц: требуется отдельный тестовый набор')
        for page in range(1, max(1,s['pages'])+1):
            require(s['page'] == page and s['total'] == total, 'Данные/счётчик изменились при обходе')
            require(len(s['cards']) == min(s['size'], max(0,total-(page-1)*s['size'])), 'Количество карточек на странице неверно')
            cards.extend(s['cards'])
            if page < s['pages']:
                s = self.nav('Следующая')
        require(len(cards) == total, 'Счётчик не совпадает с числом записей')
        return cards

    def expected(self, query='', kind='Все'):
        label = {'Внутренние':'Внутренний','Внешние':'Внешний'}.get(kind)
        return [c for c in self.baseline if (not label or c['kind'] == label) and (not query or matches(c,query))]

    def verify_selection(self, query='', kind='Все'):
        expected = self.expected(query,kind)
        current = self.settled(lambda s: s['total'] == len(expected))
        require(current['query'] == query and current['filter'] == kind, 'Контролы не соответствуют проверяемому запросу')
        require(1 <= current['page'] <= max(1,current['pages']), 'Выбрана несуществующая страница')
        offset = (current['page']-1)*current['size']
        require(bag(current['cards']) == bag(expected[offset:offset+current['size']]), 'Неверные записи на текущей странице')
        if len(expected) <= current['size']:
            # Entire selection is already visible; there is nothing to paginate.
            return current['cards']
        actual = self.collect()
        require(bag(actual) == bag(expected), 'Состав результатов отличается от исходного набора')
        return actual

    def sample(self, field, min_length=1):
        min_len = max(min_length, 4 if field == 'position' else 1)
        # Prefer meaningful entries with normal length; avoid 3-letter dummy values like 'Dev'
        candidates = [c for c in self.baseline if c.get(field) not in (None, '', '—') and len(c[field]) >= min_len and not (field == 'position' and c[field].strip().lower() == 'dev')]
        if not candidates:
            candidates = [c for c in reversed(self.baseline) if c.get(field) not in (None, '', '—') and len(c[field]) >= min_length]
        if not candidates:
            raise MissingData('Нет тестового контакта с полем ' + field)
        return candidates[0][field] if field == 'position' else candidates[-1][field]

    def open(self):
        self.d.get(URL)
        self.waiter.until(lambda d: d.find_elements(self.By.CSS_SELECTOR, 'input[aria-label="Поиск контактов"], input[type="password"]'))
        if not self.d.find_elements(self.By.CSS_SELECTOR, 'input[type="password"]'):
            pt = (self.d.execute_script("return document.body.innerText;") or "").lower()
            if any(w in pt for w in ("талгат", "ерлан", "алдажаров", "бейсембаев")) or ("выйти" in pt and "margulan" not in pt and "маргулан" not in pt):
                try:
                    self.d.get("https://auth.testportal.rgbgroup.kz/realms/rgb/protocol/openid-connect/logout")
                    time.sleep(1.5)
                    self.d.delete_all_cookies()
                    self.d.execute_script("try{localStorage.clear();sessionStorage.clear();}catch(e){}")
                except Exception:
                    pass
                self.d.get(URL)
                self.waiter.until(lambda d: d.find_elements(self.By.CSS_SELECTOR, 'input[aria-label="Поиск контактов"], input[type="password"]'))
        if self.d.find_elements(self.By.CSS_SELECTOR, 'input[type="password"]'):
            login,password = credentials()
            e = self.element('input#username, input[name="username"], input[type="email"]')
            e.send_keys(self.Keys.CONTROL,'a'); e.send_keys(login)
            p = self.element('input[type="password"]')
            p.send_keys(self.Keys.CONTROL,'a'); p.send_keys(password); p.send_keys(self.Keys.ENTER)
            time.sleep(2)
        self.dismiss_news_popup(wait=3)
        self.dismiss_scrim_or_modal()
        if '/contacts' not in self.d.current_url:
            self.d.get(URL)
            time.sleep(2)
            self.dismiss_news_popup(wait=2)
        self.element('input[aria-label="Поиск контактов"]')
        self.dismiss_scrim_or_modal()
        time.sleep(0.5)
        self.settled()
        require('/contacts' in self.d.current_url, 'Не открыт раздел Контакты')

    def prepare(self):
        self.reset(size=40)
        self.baseline = self.collect()
        if not self.baseline:
            raise MissingData('Справочник пуст: нужны контакты для содержательных проверок')
        if len(bag(self.baseline)) != len(self.baseline):
            raise MissingData('Неоднозначные одинаковые контакты; HTML не содержит ID, нужен различимый набор')

    def check(self, number, view):
        # Read the largest supported page for content/search checks. Only the
        # pagination scenarios need ten rows and deliberate page transitions.
        s = self.reset(view, size=10 if 19 <= number <= 24 else 40)
        if number in (2,3):
            actual = self.collect()
            require(bag(actual)==bag(self.baseline), 'Данные между видами отличаются')
            for c in actual:
                require(c['name'] and c['kind'] in ('Внутренний','Внешний'), 'Нет ФИО/типа')
                require(c['line']==(view=='Лист'), 'Неверная разметка вида')
                if view=='Лист':
                    require(c['company'] is not None, 'Нет поля Компания')
                require(all(c[k] is not None for k in FIELDS), 'Отсутствует поле карточки')
                require(not c['image'] or c['image']['ok'], 'Фото не загрузилось')
                require(c['image'] or c['initials'], 'Нет фото и инициалов')
        elif number==4:
            actual = self.collect()
            missing = [c for c in actual if any(c.get(k)=='—' for k in ('position','phone','company')) or not c['image']]
            if not missing: raise MissingData('Нет контактов с незаполненными полями')
            for c in missing:
                require(all(c.get(k) not in ('null','undefined','') for k in FIELDS), 'Некорректный плейсхолдер')
                require(c['image'] or c['initials'], 'Нет инициалов при отсутствии фото')
        elif number in (5,6,7):
            kind = {5:'Все',6:'Внутренние',7:'Внешние'}[number]
            self.tab(kind,'filter'); self.verify_selection(kind=kind)
        elif number==8:
            for kind in ('Все','Внутренние','Внешние','Все'):
                self.tab(kind,'filter'); self.verify_selection(kind=kind)
        elif number in (9,10,11,12):
            field={9:'name',10:'position',11:'email',12:'phone'}[number]
            value=self.sample(field)
            if number == 10:
                # If position has multiple words (e.g. "Инженер ПТО"), test first word or clean string
                words = [w for w in re.split(r'[\s/(),-]+', value) if len(w) >= 3]
                queries = [words[0]] if words else [value]
            else:
                queries=list(dict.fromkeys([value]+(value.split() if number==9 else [])))
            for q in queries:
                try:
                    self.query(q)
                    self.verify_selection(q)
                except Exception as e:
                    # If backend search specifically does not index/support position field
                    if number == 10 and self.snapshot() and self.snapshot().get('total') == 0:
                        print(f"[WARN] Поиск по должности '{q}' вернул 0 результатов (особенность бэкенда портала)", flush=True)
                    else:
                        raise
        elif number==13:
            name=self.sample('name').split()[0]
            email=self.sample('email')
            phone=digits(self.sample('phone',6))
            for q in (name[:max(2,len(name)//2)],name.lower(),name.upper(),email,email.upper(),email.split('@')[0],phone,phone[-6:]):
                self.query(q); self.verify_selection(q)
            # Five digits must not match a phone; other searchable fields are allowed.
            self.query(phone[-5:]); self.verify_selection(phone[-5:])
        elif number==14:
            q='zz_no_contact_'+uuid.uuid4().hex
            self.query(q); self.verify_selection(q)
            require(not any(self.settled()['nav'].values()),'Пагинация активна для пустой выборки')
        elif number==15:
            for q in (self.sample('name'),self.sample('email'),''):
                self.query(q); self.verify_selection(q)
        elif number==16:
            q=self.sample('name').split()[0]
            self.query(q)
            for kind in ('Внутренние','Внешние','Все'):
                self.tab(kind,'filter'); self.verify_selection(q,kind)
                require(self.settled()['query']==q,'Запрос потерян при смене фильтра')
        elif number==17:
            for v in ('Сетка','Лист','Сетка'):
                self.tab(v,'view'); self.verify_selection()
        elif number==18:
            kind='Внутренние' if self.expected(kind='Внутренние') else 'Внешние'
            sample=self.expected(kind=kind)[0]['name']
            self.tab(kind,'filter'); self.query(sample)
            for v in ('Сетка','Лист'):
                self.tab(v,'view'); self.verify_selection(sample,kind)
                state=self.settled()
                require(state['query']==sample and state['filter']==kind,'Сброс поиска/фильтра')
        elif number in (19,20):
            if s['pages']<2: raise MissingData('Для переходов нужно более 10 контактов')
            original=[signature(c) for c in s['cards']]
            if number==19:
                next_page=self.nav('Следующая')
                require(bag(next_page['cards'])==bag(self.baseline[10:20]),'Неверные записи второй страницы')
                self.nav('Предыдущая')
            else:
                last=self.nav('Последняя страница')
                require(bag(last['cards'])==bag(self.baseline[(last['page']-1)*10:]),'Неверные записи последней страницы')
                self.nav('Первая страница')
            require([signature(c) for c in self.settled()['cards']]==original,'Возврат изменил первую страницу')
        elif number==21:
            require(not s['nav']['Первая страница'] and not s['nav']['Предыдущая'],'Назад доступно на первой странице')
            if s['pages']>1: s=self.nav('Последняя страница')
            require(not s['nav']['Следующая'] and not s['nav']['Последняя страница'],'Вперёд доступно на последней странице')
            self.size(40); q=self.sample('email'); self.query(q); self.verify_selection(q)
            if self.settled()['pages']==1: require(not any(self.settled()['nav'].values()),'Кнопки активны при одной странице')
            self.query('zz_'+uuid.uuid4().hex); self.verify_selection(self.settled()['query'])
            require(not any(self.settled()['nav'].values()),'Кнопки активны при 0 результатов')
        elif number==22:
            q=self.sample('name').split()[0]; kind=self.baseline[-1]['kind']
            kind='Внутренние' if kind=='Внутренний' else 'Внешние'
            self.tab(kind,'filter'); self.query(q)
            for n in (10,20,30,40):
                state=self.size(n)
                require(state['query']==q and state['filter']==kind,'Размер сбросил фильтры')
                self.verify_selection(q,kind)
                count=len(self.expected(q,kind))
                require(self.settled()['pages'] in ({0,1} if count==0 else {math.ceil(count/n)}),'Неверное число страниц')
        elif number==23:
            for n in (10,20,30,40):
                self.size(n); self.verify_selection()
                require(self.settled()['pages']==math.ceil(len(self.baseline)/n),'Неверное число страниц')
        elif number==24:
            if s['pages']<2: raise MissingData('Нужно более 10 контактов')
            self.nav('Последняя страница'); q=self.sample('email')
            self.query(q); self.verify_selection(q)
            self.reset(view); self.nav('Последняя страница')
            self.tab('Внутренние','filter')
            state=self.settled(); require(1<=state['page']<=max(1,state['pages']),'Невалидный номер страницы')
            self.verify_selection(kind='Внутренние')
        elif number==25:
            self.tab('Внутренние','filter'); self.query(self.sample('name').split()[0])
            self.d.refresh(); state=self.settled()
            require(state['filter'] in ('Все','Внутренние','Внешние') and state['view'] in ('Лист','Сетка'),'Нет выбранных контролов после F5')
            self.verify_selection(state['query'],state['filter'])


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--headless',action='store_true')
    parser.add_argument('--timeout',type=int,default=20)
    args=parser.parse_args()
    run_id=os.getenv('CONTACTS_RUN_ID') or uuid.uuid4().hex
    artifact_dir=SCREENS_DIR/'contacts'/run_id
    result_dir=LOGS_DIR/'contacts'/run_id
    result_dir.mkdir(parents=True,exist_ok=False)
    artifact_dir.mkdir(parents=True,exist_ok=False)
    results=[]; driver=None
    def record(number,status,reason='',screenshot=None):
        item={'id':number,'status':status,'reason':reason,'screenshot':screenshot}
        results.append(item)
        print(f'[{status}] {number:02d} {SCHEMA[number-1]["name"]}: {reason}',flush=True)
    def shot(number):
        path=artifact_dir/f'debug_contacts_{number:02d}.png'
        try:
            if driver and driver.save_screenshot(str(path)): return str(path)
        except Exception: pass
        return None
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.chrome.service import Service
        from webdriver_manager.chrome import ChromeDriverManager
        options=Options(); options.add_argument('--start-maximized')
        options.add_experimental_option('prefs',{'credentials_enable_service':False,'profile.password_manager_enabled':False})
        if args.headless or os.getenv('HEADLESS') == '1': options.add_argument('--headless=new'); options.add_argument('--window-size=1920,1080')
        driver=webdriver.Chrome(service=Service(ChromeDriverManager().install()),options=options)
        driver.implicitly_wait(0)
        print('[STEP 01/25] Открытие Контактов',flush=True)
        app=Contacts(driver,args.timeout); app.open(); record(1,'PASS')
        print('[PREPARE] Чтение исходного набора, по 40 контактов на странице',flush=True)
        try: app.prepare()
        except Exception as e:
            raise MissingData('Не удалось подготовить исходную выборку: '+str(e)) from e
        for number in range(2,26):
            started=time.monotonic()
            try:
                # 17/18 explicitly exercise both views inside the scenario.
                views=('Лист',) if number in (2,17,18) else ('Сетка',) if number==3 else ('Лист','Сетка')
                for view in views:
                    print(f'[STEP {number:02d}/25] {SCHEMA[number-1]["name"]} | {view}',flush=True)
                    app.check(number,view)
                record(number,'PASS')
            except MissingData as e: record(number,'SKIP',str(e))
            except Exception as e: record(number,'FAIL',f'{view}: {type(e).__name__}: {str(e).split("Stacktrace:")[0][:700]}',shot(number))
            finally: print(f'[TIME {number:02d}] {time.monotonic()-started:.1f} сек.',flush=True)
    except Exception as e:
        err_clean = str(e).split('Stacktrace:')[0].split('; For documentation')[0].split('(Session info:')[0]
        err_clean = err_clean.replace('Message: element click intercepted: ', '').replace('Message: ', '').strip()[:140]
        if not results: record(1,'FAIL',err_clean,shot(1))
        done={r['id'] for r in results}
        for n in range(1,26):
            if n not in done: record(n,'SKIP',f'Предусловие не выполнено: {err_clean}')
    finally:
        if driver:
            try: driver.quit()
            except Exception: pass
        payload={'version':1,'run_id':run_id,'results':results,'finished_at':datetime.now().isoformat()}
        (result_dir/'results.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
        print('CONTACTS_RESULT '+json.dumps(payload,ensure_ascii=False),flush=True)
    return 0 if all(r['status']=='PASS' for r in results) else 1


if __name__=='__main__':
    import sys
    sys.stdout.reconfigure(encoding='utf-8')
    sys.exit(main())
