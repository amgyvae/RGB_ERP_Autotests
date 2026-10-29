import re
import time
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys


_IGNORED_CELL_WORDS = {
    "—", "-", "", "ожидание", "черновик", "согласовано", "согласован",
    "на согласовании", "отклонено", "утверждено", "параллельное",
    "последовательное", "согласующий", "статус", "дата и время", "дата",
    "действия", "добавить", "+ добавить", "+ этап", "добавить этап",
    "сменить маршрут", "сохранить", "отмена", "удалить", "редактировать",
}

_DATE_OR_NUM_RE = re.compile(r"^[\d\s.,:/\-№#]+$")


def is_margulan_name(text: str) -> bool:
    low = (text or "").strip().lower()
    return ("margulan" in low or "маргулан" in low) and "aisinov" not in low


def _has_other_person_text(text: str) -> bool:
    t = " ".join((text or "").split()).strip()
    if not t:
        return False
    low = t.lower()
    if is_margulan_name(low):
        return False
    if low in _IGNORED_CELL_WORDS:
        return False
    if "выбрать" in low or "выберите" in low or "не назнач" in low or "не настроен" in low:
        return False
    if "этап" in low and len(low) < 35:
        return False
    if _DATE_OR_NUM_RE.match(low):
        return False
    return len(t) > 2 and any(ch.isalpha() for ch in t)


def _js_click(driver, el):
    driver.execute_script("arguments[0].click();", el)


def _hard_click(driver, el):
    return bool(driver.execute_script("""
        var el = arguments[0];
        var r = el.getBoundingClientRect();
        if (r.width <= 0 || r.height <= 0) return false;
        var opts = {bubbles: true, cancelable: true, view: window,
                    clientX: r.left + r.width / 2, clientY: r.top + r.height / 2};
        el.dispatchEvent(new PointerEvent('pointerdown', opts));
        el.dispatchEvent(new MouseEvent('mousedown', opts));
        el.dispatchEvent(new PointerEvent('pointerup', opts));
        el.dispatchEvent(new MouseEvent('mouseup', opts));
        el.dispatchEvent(new MouseEvent('click', opts));
        return true;
    """, el))


def _click(driver, el) -> bool:
    if el is None:
        return False
    try:
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
        time.sleep(0.15)
    except Exception:
        pass
    for m in ("selenium", "js", "hard"):
        try:
            if m == "selenium":
                el.click()
            elif m == "js":
                _js_click(driver, el)
            else:
                if not _hard_click(driver, el):
                    continue
            return True
        except Exception:
            continue
    return False


def _type_search(driver, inp, value: str):
    try:
        inp.click()
    except Exception:
        try:
            _js_click(driver, inp)
        except Exception:
            pass
    time.sleep(0.15)
    try:
        inp.send_keys(Keys.CONTROL, "a")
        inp.send_keys(Keys.BACKSPACE)
    except Exception:
        pass
    if value:
        try:
            inp.send_keys(value)
            return
        except Exception:
            pass
    try:
        driver.execute_script("""
            var el = arguments[0], val = arguments[1];
            Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set.call(el, val);
            el.dispatchEvent(new Event('input', {bubbles: true}));
            el.dispatchEvent(new Event('change', {bubbles: true}));
        """, inp, value)
    except Exception:
        pass


def find_route_section(driver):
    for xp in [
        "//section[contains(@class,'evd-route')]",
        "//*[normalize-space(text())='Маршрут согласования']/ancestor::section[1]",
        "//*[normalize-space(text())='Маршрут согласования']/ancestor::div[.//table or .//button][1]",
    ]:
        try:
            els = [e for e in driver.find_elements(By.XPATH, xp) if e.is_displayed()]
            if els:
                return els[0]
        except Exception:
            continue
    return None


def find_approvers_modal(driver):
    for xp in [
        "//div[@role='dialog'][.//h2[contains(normalize-space(.),'Согласующ')]]",
        "//div[contains(@class,'action-modal__shell')][contains(normalize-space(.),'Согласующ')]",
        "//*[@role='dialog' or @aria-modal='true'][contains(normalize-space(.),'Согласующ')]",
    ]:
        try:
            els = [e for e in driver.find_elements(By.XPATH, xp) if e.is_displayed()]
            if els:
                return els[-1]
        except Exception:
            continue
    return None


def _confirm_delete_dialog_if_any(driver):
    time.sleep(0.35)
    for xp in [
        "//div[@role='dialog' or @aria-modal='true']//button[normalize-space(.)='Удалить' or normalize-space(.)='Да' or normalize-space(.)='Подтвердить']",
        "//div[contains(@class,'modal')]//button[normalize-space(.)='Удалить' or normalize-space(.)='Да' or normalize-space(.)='Подтвердить']",
    ]:
        try:
            btns = [b for b in driver.find_elements(By.XPATH, xp) if b.is_displayed() and b.is_enabled()]
            if btns and not find_approvers_modal(driver):
                _click(driver, btns[-1])
                time.sleep(0.5)
                return True
        except Exception:
            continue
    return False


def clear_approvers_modal_templates(driver, modal=None, log=None) -> int:
    """Удаляет всех шаблонных согласующих (кроме Sh Margulan Ju) внутри открытой модалки «Согласующие»."""
    removed = 0
    for _ in range(12):
        m = modal or find_approvers_modal(driver)
        if m is None:
            break
        acted = False
        try:
            items = m.find_elements(
                By.XPATH,
                ".//*[contains(@class,'evd-approvers-modal__item') or contains(@class,'approver') or self::li or self::tr]"
            )
        except Exception:
            items = []
        for item in items:
            try:
                if not item.is_displayed():
                    continue
                txt = " ".join((item.get_attribute("innerText") or "").split()).strip()
                if not txt or is_margulan_name(txt) or not _has_other_person_text(txt):
                    continue
                btns = [
                    b for b in item.find_elements(By.XPATH, ".//button")
                    if b.is_displayed() and b.is_enabled()
                    and "ui-select__trigger" not in (b.get_attribute("class") or "")
                    and (b.get_attribute("textContent") or "").strip() not in ("Сохранить", "Отмена", "Добавить")
                ]
                if btns:
                    if log:
                        log(f"  • Удаляю шаблонного согласующего в окне: {txt[:60]}")
                    _click(driver, btns[-1])
                    time.sleep(0.45)
                    removed += 1
                    acted = True
                    break
            except Exception:
                continue
        if not acted:
            break
    return removed


def clear_route_templates(driver, log=None) -> int:
    """Удаляет шаблонных пользователей и лишние пустые этапы в блоке «Маршрут согласования»."""
    removed = 0
    m = find_approvers_modal(driver)
    if m is not None:
        removed += clear_approvers_modal_templates(driver, m, log=log)

    for _ in range(15):
        sec = find_route_section(driver)
        if sec is None:
            break
        acted = False
        try:
            rows = [r for r in sec.find_elements(By.XPATH, ".//tbody//tr") if r.is_displayed()]
        except Exception:
            rows = []

        for r in rows:
            try:
                name_cells = r.find_elements(By.CSS_SELECTOR, ".evd-route__td--name")
                if name_cells:
                    who_txt = " ".join((name_cells[0].get_attribute("textContent") or "").split()).strip()
                else:
                    tds = [td for td in r.find_elements(By.TAG_NAME, "td") if td.is_displayed()]
                    who_txt = " ".join(
                        (td.get_attribute("textContent") or "").strip()
                        for td in tds
                        if _has_other_person_text(td.get_attribute("textContent") or "")
                        or is_margulan_name(td.get_attribute("textContent") or "")
                    ).strip()
                if not who_txt or is_margulan_name(who_txt) or not _has_other_person_text(who_txt):
                    continue

                row_btns = [
                    b for b in r.find_elements(By.XPATH, ".//button")
                    if b.is_displayed() and b.is_enabled()
                    and "ui-select__trigger" not in (b.get_attribute("class") or "")
                ]
                if not row_btns:
                    continue

                direct_del = None
                for b in row_btns:
                    meta = " ".join([
                        b.get_attribute("aria-label") or "",
                        b.get_attribute("title") or "",
                        b.get_attribute("class") or "",
                        b.get_attribute("textContent") or "",
                    ]).lower()
                    if any(k in meta for k in ("удал", "убрать", "delete", "remove", "trash")):
                        direct_del = b
                        break

                if direct_del is not None:
                    if log:
                        log(f"  • Удаляю шаблонного согласующего из маршрута: {who_txt[:60]}")
                    _click(driver, direct_del)
                    _confirm_delete_dialog_if_any(driver)
                    time.sleep(0.6)
                    removed += 1
                    acted = True
                    break

                # Иначе кликаем кнопку меню «⋯» в конце строки
                menu_btn = row_btns[-1]
                _click(driver, menu_btn)
                time.sleep(0.5)

                del_opt = None
                edit_opt = None
                for xp in [
                    "//*[@role='menuitem' or @role='option' or self::button or self::li]"
                    "[contains(translate(normalize-space(.),'УДАЛИТЬБР','удалитьбр'),'удал') "
                    "or contains(translate(normalize-space(.),'УДАЛИТЬБР','удалитьбр'),'убрать')]",
                ]:
                    vis = [
                        x for x in driver.find_elements(By.XPATH, xp)
                        if x.is_displayed()
                        and len((x.get_attribute("textContent") or "").strip()) < 40
                        and "паспорт" not in (x.get_attribute("textContent") or "").lower()
                        and "заявк" not in (x.get_attribute("textContent") or "").lower()
                        and "заказ" not in (x.get_attribute("textContent") or "").lower()
                        and "документ" not in (x.get_attribute("textContent") or "").lower()
                        and "смет" not in (x.get_attribute("textContent") or "").lower()
                    ]
                    if vis:
                        del_opt = vis[-1]
                        break

                if del_opt is not None:
                    if log:
                        log(f"  • Удаляю шаблонного согласующего через меню: {who_txt[:60]}")
                    _click(driver, del_opt)
                    _confirm_delete_dialog_if_any(driver)
                    time.sleep(0.6)
                    removed += 1
                    acted = True
                    break

                # Если меню открыло «Редактировать» или модалку «Согласующие»
                modal_now = find_approvers_modal(driver)
                if modal_now is None:
                    for xp in [
                        "//*[@role='menuitem' or self::button or self::li]"
                        "[normalize-space(.)='Редактировать' or normalize-space(.)='Изменить']",
                    ]:
                        vis = [x for x in driver.find_elements(By.XPATH, xp) if x.is_displayed()]
                        if vis:
                            edit_opt = vis[-1]
                            break
                    if edit_opt is not None:
                        _click(driver, edit_opt)
                        time.sleep(0.7)
                        modal_now = find_approvers_modal(driver)

                if modal_now is not None:
                    c = clear_approvers_modal_templates(driver, modal_now, log=log)
                    if c > 0:
                        removed += c
                        # Сохраняем модалку или оставляем для выбора Margulan
                        save_btns = [
                            b for b in modal_now.find_elements(
                                By.XPATH, ".//button[normalize-space(.)='Сохранить' or normalize-space(.)='Применить']"
                            )
                            if b.is_displayed() and b.is_enabled()
                        ]
                        if save_btns:
                            _click(driver, save_btns[-1])
                            time.sleep(0.8)
                        acted = True
                        break
                else:
                    try:
                        ActionChains(driver).send_keys(Keys.ESCAPE).perform()
                    except Exception:
                        pass
            except Exception:
                continue

        if not acted:
            break

    # Удаляем лишние пустые этапы (2 этап, 3 этап...), если у них есть кнопка удаления этапа
    for _ in range(6):
        sec = find_route_section(driver)
        if sec is None:
            break
        try:
            stages = [s for s in sec.find_elements(By.CSS_SELECTOR, ".evd-route__stage") if s.is_displayed()]
        except Exception:
            stages = []
        if len(stages) <= 1:
            break
        deleted_stage = False
        for stg in reversed(stages[1:]):
            try:
                st_txt = (stg.get_attribute("innerText") or "")
                if is_margulan_name(st_txt):
                    continue
                s_btns = [
                    b for b in stg.find_elements(By.XPATH, ".//button")
                    if b.is_displayed() and b.is_enabled()
                    and "ui-select__trigger" not in (b.get_attribute("class") or "")
                    and "добавить" not in (b.get_attribute("textContent") or "").strip().lower()
                ]
                for sb in s_btns:
                    meta = " ".join([
                        sb.get_attribute("aria-label") or "",
                        sb.get_attribute("title") or "",
                        sb.get_attribute("class") or "",
                        sb.get_attribute("textContent") or "",
                    ]).lower()
                    if any(k in meta for k in ("удал", "delete", "remove", "trash")):
                        _click(driver, sb)
                        _confirm_delete_dialog_if_any(driver)
                        time.sleep(0.6)
                        deleted_stage = True
                        break
                if deleted_stage:
                    break
            except Exception:
                continue
        if not deleted_stage:
            break

    return removed


def route_only_margulan(driver) -> bool:
    """Проверяет, что в маршруте согласования назначен Sh Margulan Ju, нет других шаблонных
    пользователей и нет пустых незаполненных селектов «Выбрать согласующего»."""
    sec = find_route_section(driver)
    if sec is None:
        return False
    try:
        sec_txt = (sec.get_attribute("innerText") or "")
    except Exception:
        return False
    if not is_margulan_name(sec_txt):
        return False
    low = sec_txt.lower()
    if "выбрать согласующего" in low or "этапы согласования не настроены" in low:
        return False
    try:
        rows = [r for r in sec.find_elements(By.XPATH, ".//tbody//tr") if r.is_displayed()]
        for r in rows:
            name_cells = r.find_elements(By.CSS_SELECTOR, ".evd-route__td--name")
            if name_cells:
                who = (name_cells[0].get_attribute("textContent") or "").strip()
                if who and not is_margulan_name(who) and _has_other_person_text(who):
                    return False
        stages = [s for s in sec.find_elements(By.CSS_SELECTOR, ".evd-route__stage") if s.is_displayed()]
        for s in stages:
            if not is_margulan_name(s.get_attribute("innerText") or ""):
                return False
    except Exception:
        pass
    return True


def _pick_margulan_in_open_panel(driver, panel, log=None):
    def get_opts():
        out = []
        for xp in [".//button[@role='option']", ".//*[@role='option']"]:
            try:
                for b in panel.find_elements(By.XPATH, xp):
                    if not b.is_displayed():
                        continue
                    txt = " ".join((b.get_attribute("textContent") or "").split()).strip()
                    if txt:
                        out.append((b, txt))
            except Exception:
                continue
            if out:
                break
        return out

    search_inp = None
    for xp in [".//input[contains(@class,'ui-select__search-input')]", ".//input"]:
        try:
            inps = [i for i in panel.find_elements(By.XPATH, xp) if i.is_displayed()]
            if inps:
                search_inp = inps[0]
                break
        except Exception:
            continue

    for query in ("Margulan", "Sh Margulan", ""):
        if search_inp is not None:
            _type_search(driver, search_inp, query)
            time.sleep(1.1)
        opts = get_opts()
        for el, txt in opts:
            if is_margulan_name(txt):
                _click(driver, el)
                time.sleep(0.6)
                return txt
    return None


def _select_margulan_for_trigger(driver, trigger, log=None) -> bool:
    panel = None
    for m in ("hard", "js", "selenium"):
        try:
            if m == "hard":
                _hard_click(driver, trigger)
            elif m == "js":
                _js_click(driver, trigger)
            else:
                trigger.click()
        except Exception:
            continue
        for _ in range(8):
            vis = [
                p for p in driver.find_elements(By.XPATH, "//div[contains(@class,'ui-select__panel') or @role='listbox']")
                if p.is_displayed()
            ]
            if vis:
                panel = vis[-1]
                break
            time.sleep(0.25)
        if panel is not None:
            break

    if panel is None:
        if log:
            log("  ⚠ Список согласующих не открылся", "WARN")
        return False

    picked = _pick_margulan_in_open_panel(driver, panel, log=log)
    if not picked:
        if log:
            log("  ⚠ Пользователь Sh Margulan Ju не найден в списке согласующих", "WARN")
        return False

    if log:
        log(f"  ✓ Выбран согласующий: {picked}", "PASS")

    # Если открыта модалка «Согласующие», НЕ жмём Escape (он закроет модалку без сохранения!)
    modal = find_approvers_modal(driver)
    if modal is not None:
        try:
            headings = [h for h in modal.find_elements(By.XPATH, ".//h2 | .//h3") if h.is_displayed()]
            if headings:
                _click(driver, headings[0])
                time.sleep(0.3)
        except Exception:
            pass
        clear_approvers_modal_templates(driver, modal, log=log)
        save_btns = [
            b for b in modal.find_elements(
                By.XPATH,
                ".//footer//button[normalize-space(.)='Сохранить' or normalize-space(.)='Добавить' or normalize-space(.)='Применить'] | "
                ".//button[normalize-space(.)='Сохранить' or normalize-space(.)='Применить']"
            )
            if b.is_displayed() and b.is_enabled()
        ]
        if save_btns:
            _click(driver, save_btns[-1])
            for _ in range(16):
                if find_approvers_modal(driver) is None:
                    break
                time.sleep(0.4)
    else:
        # Закрываем выпадающую панель, если она мультиселект и осталась открыта
        try:
            for bd in driver.find_elements(By.XPATH, "//div[contains(@class,'ui-select__backdrop')]"):
                if bd.is_displayed():
                    _hard_click(driver, bd)
                    time.sleep(0.3)
        except Exception:
            pass

    return True


def _click_add_stage_button(driver, log=None) -> bool:
    sec = find_route_section(driver)
    if sec is not None:
        try:
            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", sec)
            time.sleep(0.3)
        except Exception:
            pass
    for xp in [
        "//button[contains(@class,'evd-empty-stub__action')]",
        "//section[contains(@class,'evd-route')]//button[contains(normalize-space(.),'Добавить этап')]",
        "//*[self::button or self::a][normalize-space(.)='Добавить этап']",
        "//section[contains(@class,'evd-route')]//button[contains(@class,'evd-route__add-badge')]",
        "//section[contains(@class,'evd-route')]//button[contains(normalize-space(.),'Этап')]",
        "//*[contains(normalize-space(text()),'Маршрут согласования')]/following::button[contains(normalize-space(.),'Этап')][1]",
    ]:
        try:
            btns = [b for b in driver.find_elements(By.XPATH, xp) if b.is_displayed() and b.is_enabled()]
            if btns:
                if _click(driver, btns[0]):
                    if log:
                        log("  • Нажата кнопка добавления этапа")
                    time.sleep(1.2)
                    return True
        except Exception:
            continue
    return False


def _find_unset_route_trigger(driver, scope=None):
    modal = find_approvers_modal(driver)
    if modal is not None:
        try:
            trgs = [
                t for t in modal.find_elements(By.XPATH, ".//button[contains(@class,'ui-select__trigger')]")
                if t.is_displayed() and t.is_enabled()
            ]
            if trgs:
                return trgs[0]
        except Exception:
            pass

    root = scope or find_route_section(driver) or driver
    prefix = ".//" if scope or root is not driver else "//"
    for xp in [
        f"{prefix}button[contains(@class,'ui-select__trigger')][contains(normalize-space(.),'Выбрать согласующего') or contains(normalize-space(.),'согласующ')]",
        f"{prefix}div[contains(@class,'evd-route__stages')]//button[contains(@class,'ui-select__trigger')]",
        f"{prefix}table[contains(@class,'evd-route__table')]//button[contains(@class,'ui-select__trigger')]",
    ]:
        try:
            trgs = [
                t for t in root.find_elements(By.XPATH, xp)
                if t.is_displayed() and t.is_enabled()
                and not is_margulan_name(t.get_attribute("textContent") or "")
            ]
            if trgs:
                return trgs[0]
        except Exception:
            continue
    return None


def setup_margulan_route(driver, log=None) -> bool:
    """Гарантирует, что в «Маршруте согласования»:
    1) удалены любые шаблонные согласующие (до и после нажатия «Добавить этап»),
    2) добавлен этап и выбран пользователь Sh Margulan Ju."""
    sec = find_route_section(driver)
    if sec is not None:
        try:
            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", sec)
            time.sleep(0.3)
        except Exception:
            pass

    # 1. Если маршрут уже шаблонно предзаполнен другими пользователями — очищаем
    clear_route_templates(driver, log=log)
    if route_only_margulan(driver):
        if log:
            log("  ✓ Маршрут согласования уже настроен на Sh Margulan Ju", "PASS")
        return True

    # 2. Если этапа ещё нет — нажимаем «Добавить этап» / «+ Этап»
    sec = find_route_section(driver)
    has_stages = False
    if sec is not None:
        try:
            has_stages = bool([s for s in sec.find_elements(By.CSS_SELECTOR, ".evd-route__stage") if s.is_displayed()])
        except Exception:
            has_stages = False

    if not has_stages and _find_unset_route_trigger(driver) is None and find_approvers_modal(driver) is None:
        _click_add_stage_button(driver, log=log)
        # Если нажатие «Добавить этап» подставило шаблон — сразу очищаем всех шаблонных пользователей!
        clear_route_templates(driver, log=log)
        if route_only_margulan(driver):
            if log:
                log("  ✓ Маршрут согласования настроен на Sh Margulan Ju", "PASS")
            return True

    # 3. Если после удаления шаблонных этапов не осталось ни одного этапа — создаём чистый этап
    sec = find_route_section(driver)
    if sec is not None:
        try:
            stages_now = [s for s in sec.find_elements(By.CSS_SELECTOR, ".evd-route__stage") if s.is_displayed()]
        except Exception:
            stages_now = []
        if not stages_now and _find_unset_route_trigger(driver) is None and find_approvers_modal(driver) is None:
            _click_add_stage_button(driver, log=log)
            clear_route_templates(driver, log=log)

    # 4. Заполняем Sh Margulan Ju во всех незаполненных этапах (обычно 1 этап)
    for _ in range(4):
        if route_only_margulan(driver):
            break
        trg = _find_unset_route_trigger(driver)
        if trg is None:
            # Нажимаем «+ Добавить» / «Добавить» внутри этапа, у которого ещё нет Sh Margulan Ju
            sec = find_route_section(driver)
            clicked_add_person = False
            if sec is not None:
                stages = [s for s in sec.find_elements(By.CSS_SELECTOR, ".evd-route__stage") if s.is_displayed()]
                target_scopes = [s for s in stages if not is_margulan_name(s.get_attribute("innerText") or "")] or [sec]
                for sc in target_scopes:
                    btns = [
                        b for b in sc.find_elements(
                            By.XPATH,
                            ".//button[normalize-space(.)='Добавить' or contains(normalize-space(.),'Добавить')]"
                        )
                        if b.is_displayed() and b.is_enabled()
                        and "этап" not in (b.get_attribute("textContent") or "").lower()
                    ]
                    if btns and _click(driver, btns[0]):
                        clicked_add_person = True
                        time.sleep(1.0)
                        break
            if not clicked_add_person:
                for xp in [
                    "//*[contains(normalize-space(text()),' этап')]/following::button[contains(normalize-space(.),'Добавить')][1]",
                ]:
                    btns = [b for b in driver.find_elements(By.XPATH, xp) if b.is_displayed() and b.is_enabled()]
                    if btns and _click(driver, btns[0]):
                        clicked_add_person = True
                        time.sleep(1.0)
                        break

            # Если открылась модалка «Согласующие» с предзаполненным шаблоном — очищаем её
            modal = find_approvers_modal(driver)
            if modal is not None:
                clear_approvers_modal_templates(driver, modal, log=log)
            trg = _find_unset_route_trigger(driver)

        if trg is None:
            break

        if not _select_margulan_for_trigger(driver, trg, log=log):
            break
        time.sleep(0.8)

    # 5. Нажимаем встроенную кнопку «Сохранить» в секции маршрута, если она есть
    sec = find_route_section(driver)
    if sec is not None:
        try:
            save_btns = [
                b for b in sec.find_elements(By.XPATH, ".//button[normalize-space(.)='Сохранить']")
                if b.is_displayed() and b.is_enabled()
            ]
            if save_btns:
                _click(driver, save_btns[0])
                time.sleep(1.2)
        except Exception:
            pass

    for _ in range(8):
        sec = find_route_section(driver)
        if route_only_margulan(driver) or (sec is not None and is_margulan_name(sec.get_attribute("innerText") or "")):
            if log:
                log("  ✓ Маршрут согласования настроен (Sh Margulan Ju)", "PASS")
            return True
        time.sleep(0.8)

    if log:
        log("  ⚠ Sh Margulan Ju не подтверждён в маршруте согласования", "WARN")
    return False
