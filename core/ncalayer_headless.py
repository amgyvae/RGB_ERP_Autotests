# -*- coding: utf-8 -*-
"""
Headless NCALayer Server & Signing Helper (wss://127.0.0.1:13579)
=================================================================
Allows all 5 EDS (ЭЦП) autotests (ГПР, Договоры, Накладные, Счета на оплату, Акты)
to sign documents headlessly on macOS, Linux (GitHub Actions ubuntu-latest), and Windows
without requiring a GUI desktop or manual file/password dialogs.
"""

from __future__ import annotations

import glob
import json
import os
import shutil
import socket
import subprocess
import time
from pathlib import Path
from typing import Callable, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
BUNDLES_DIR = REPO_ROOT / "core" / "ncalayer_bundles"
CERTS_DIR = REPO_ROOT / "certs"

CONTROL_FILE = Path(os.environ.get("NCA_CONTROL_FILE", "/tmp/ncalayer_active_key.json"))
RESULT_FILE = Path(os.environ.get("NCA_RESULT_FILE", "/tmp/ncalayer_last_result.json"))
LOG_FILE = Path(os.environ.get("NCA_LOG_FILE", "/tmp/ncalayer_headless.log"))
NCA_PORT = int(os.environ.get("NCA_PORT", "13579"))

_SERVER_PROC: Optional[subprocess.Popen] = None


def _load_dotenv_Simple() -> dict[str, str]:
    env_map: dict[str, str] = {}
    env_path = REPO_ROOT / ".env"
    if env_path.exists():
        try:
            for line in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k = k.strip()
                v = v.strip().strip("'").strip('"')
                env_map[k] = v
        except Exception:
            pass
    return env_map


def find_java_binary() -> str:
    """Finds a usable Java executable across macOS, Linux (GitHub Actions), and Windows."""
    env_java = os.environ.get("NCA_JAVA_BIN", "").strip()
    if env_java and os.path.isfile(env_java):
        return env_java

    # 1. Bundled NCALayer JRE on macOS (if present)
    mac_nca_java = "/Applications/NCALayer.app/Contents/Resources/bin/java"
    if os.path.isfile(mac_nca_java):
        return mac_nca_java

    # 2. Installed JDKs on macOS
    for candidate in sorted(glob.glob("/Library/Java/JavaVirtualMachines/*/Contents/Home/bin/java"), reverse=True):
        if os.path.isfile(candidate):
            return candidate

    # 3. Standard PATH java (works on Ubuntu GitHub Actions & Linux/Windows)
    which_java = shutil.which("java")
    if which_java:
        # On macOS, /usr/bin/java is a stub that fails if no JDK is in /Library/Java;
        # we already checked /Library/Java above, so on Linux/Windows which_java is real.
        return which_java

    raise RuntimeError("Java runtime not found for Headless NCALayer.")


def resolve_p12_path(raw_path: Optional[str] = None, key_index: int = 1) -> str:
    """
    Resolves any Windows/macOS/old .p12 path (e.g. C:\\Program Files\\NCALayer\\GOST2015_...p12
    or old GOST512_b2c200...p12) to the actual .p12 file inside <repo>/certs/.
    """
    env_map = _load_dotenv_Simple()
    if not raw_path:
        env_key = f"NCA_KEY{key_index}_PATH"
        raw_path = os.environ.get(env_key) or env_map.get(env_key) or ""

    raw_str = str(raw_path or "").strip()

    # 1. Direct path exists
    if raw_str and os.path.isfile(raw_str):
        return str(Path(raw_str).resolve())

    # Extract basename (handles both Windows '\' and POSIX '/')
    basename = raw_str.replace("\\", "/").split("/")[-1] if raw_str else ""
    if basename:
        cand = CERTS_DIR / basename
        if cand.is_file():
            return str(cand.resolve())

    # 2. Match by prefix (GOST2015 vs GOST512) inside certs/
    all_p12 = sorted(CERTS_DIR.glob("*.p12"))
    if not all_p12:
        raise FileNotFoundError(f"No .p12 certificates found in {CERTS_DIR}")

    upper_base = basename.upper()
    if "GOST2015" in upper_base or key_index == 1 and "GOST512" not in upper_base:
        for p in all_p12:
            if "GOST2015" in p.name.upper():
                return str(p.resolve())
    if "GOST512" in upper_base or key_index == 2:
        for p in all_p12:
            if "GOST512" in p.name.upper():
                return str(p.resolve())

    return str(all_p12[0].resolve())


def resolve_default_p12_path(key_index: int = 1, raw_path: Optional[str] = None) -> str:
    return resolve_p12_path(raw_path=raw_path, key_index=key_index)


def resolve_p12_password(raw_password: Optional[str] = None, p12_path: Optional[str] = None) -> str:
    """Resolves the password for the given .p12 certificate."""
    env_map = _load_dotenv_Simple()
    p12_resolved = ""
    try:
        p12_resolved = resolve_p12_path(p12_path)
    except Exception:
        p12_resolved = str(p12_path or "")

    # If the caller passed an explicit password, check if it matches key1/key2 or use it directly
    if raw_password and str(raw_password).strip():
        return str(raw_password).strip()

    if "GOST512" in os.path.basename(p12_resolved).upper():
        pwd2 = os.environ.get("NCA_KEY2_PASSWORD") or env_map.get("NCA_KEY2_PASSWORD")
        return (pwd2 or "Aa1979").strip()

    pwd1 = os.environ.get("NCA_KEY1_PASSWORD") or env_map.get("NCA_KEY1_PASSWORD")
    return (pwd1 or "Aa200616.").strip()


def is_port_listening(port: int = NCA_PORT, host: str = "127.0.0.1", timeout: float = 0.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _write_control_file(p12_path: str, password: str, req_id: Optional[int] = None) -> int:
    if req_id is None:
        req_id = int(time.time() * 1000)
    payload = {
        "req_id": req_id,
        "p12_path": p12_path,
        "password": password,
        "updated_at": time.time(),
    }
    tmp_path = Path(f"{CONTROL_FILE}.tmp.{os.getpid()}")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    tmp_path.replace(CONTROL_FILE)
    return req_id


def ensure_headless_ncalayer_running(log: Callable[[str], None] = print) -> bool:
    """
    Ensures the Headless NCALayer WebSocket server is listening on wss://127.0.0.1:13579.
    If a GUI NCALayer is running on macOS/Windows and occupying 13579, stops it first
    so that headless signing works deterministically without OS file dialogs.
    """
    global _SERVER_PROC

    # Seed default Key 1 into control file if not present
    try:
        default_p12 = resolve_p12_path(key_index=1)
        default_pwd = resolve_p12_password(p12_path=default_p12)
        if not CONTROL_FILE.exists():
            _write_control_file(default_p12, default_pwd, req_id=1)
    except Exception:
        default_p12 = ""
        default_pwd = ""

    deps_jar = BUNDLES_DIR / "ncalayer_deps.jar"
    version_file = Path("/tmp/ncalayer_server_version.txt")
    expected_ver = str(int(deps_jar.stat().st_mtime)) if deps_jar.exists() else "1"

    if is_port_listening(NCA_PORT):
        # Check if it's already our HeadlessNcaServer process with current JAR version
        cur_ver = version_file.read_text(encoding="utf-8").strip() if version_file.exists() else ""
        if cur_ver != expected_ver:
            try:
                subprocess.run(["pkill", "-f", "HeadlessNcaServer"], check=False)
                time.sleep(1.0)
            except Exception:
                pass
        elif _SERVER_PROC is not None and _SERVER_PROC.poll() is None:
            return True
        else:
            # Check process list for HeadlessNcaServer vs GUI NCALayer
            try:
                ps_out = subprocess.check_output(["ps", "-ef"], text=True, stderr=subprocess.DEVNULL)
                if "kz.gov.pki.headless.HeadlessNcaServer" in ps_out:
                    return True
                if "NCALayer.jar" in ps_out:
                    log("ℹ️ Останавливаем GUI NCALayer, чтобы запустить Headless NCALayer...")
                    subprocess.run(["pkill", "-f", "NCALayer.jar"], check=False)
                    time.sleep(1.0)
            except Exception:
                pass

    if is_port_listening(NCA_PORT):
        return True

    java_bin = find_java_binary()
    cp_glob = f"{BUNDLES_DIR}/*"
    cmd = [
        java_bin,
        "-Djava.awt.headless=true",
        f"-Dnca.port={NCA_PORT}",
        f"-Dnca.control.file={CONTROL_FILE}",
        f"-Dnca.result.file={RESULT_FILE}",
    ]
    if default_p12 and default_pwd:
        cmd.extend([
            f"-Dnca.p12.path={default_p12}",
            f"-Dnca.p12.password={default_pwd}",
        ])
    cmd.extend([
        "-cp", cp_glob,
        "kz.gov.pki.headless.HeadlessNcaServer",
    ])

    log_fp = open(LOG_FILE, "a", encoding="utf-8")
    _SERVER_PROC = subprocess.Popen(
        cmd,
        stdout=log_fp,
        stderr=log_fp,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
    )

    deadline = time.time() + 12.0
    while time.time() < deadline:
        if is_port_listening(NCA_PORT):
            try:
                version_file.write_text(expected_ver, encoding="utf-8")
            except Exception:
                pass
            log(f"✓ Headless NCALayer запущен на wss://127.0.0.1:{NCA_PORT} (PID {_SERVER_PROC.pid})")
            return True
        if _SERVER_PROC.poll() is not None:
            break
        time.sleep(0.25)

    try:
        tail = LOG_FILE.read_text(encoding="utf-8", errors="ignore")[-800:]
    except Exception:
        tail = ""
    log(f"⚠️ Не удалось запустить Headless NCALayer на порту {NCA_PORT}. Лог:\n{tail}")
    return False


def _try_click_ncalayer_method_in_browser(driver, log: Callable[[str], None]) -> bool:
    if driver is None:
        return False
    try:
        from selenium.webdriver.common.by import By
        dialogs = driver.find_elements(
            By.XPATH,
            "//*[@role='dialog' or contains(@class,'action-modal__shell')]"
            "[.//*[contains(normalize-space(.),'Способ подписания') or contains(normalize-space(.),'NCALayer')]]",
        )
        for dlg in dialogs:
            if not dlg.is_displayed():
                continue
            btns = dlg.find_elements(
                By.XPATH,
                ".//*[self::button or @role='button'][contains(normalize-space(.),'NCALayer')]",
            )
            for b in btns:
                if b.is_displayed() and b.is_enabled():
                    try:
                        b.click()
                    except Exception:
                        driver.execute_script("arguments[0].click();", b)
                    log("  • В окне 'Способ подписания' выбрана кнопка 'NCALayer'")
                    return True
    except Exception:
        pass
    return False


def sign_with_ncalayer(
    password: Optional[str] = None,
    p12_path: Optional[str] = None,
    log: Callable[[str], None] = print,
    timeout: float = 25.0,
    driver=None,
) -> bool:
    """
    Universal replacement for GUI-based sign_with_ncalayer / nca_sign.
    1. Ensures Headless NCALayer is running on wss://127.0.0.1:13579.
    2. Resolves p12_path (mapping Windows paths to <repo>/certs/*.p12) and password.
    3. Publishes credentials to CONTROL_FILE so the pending or incoming WebSocket signing
       request from Chrome immediately signs using this exact certificate & password.
    4. Waits up to `timeout` seconds for the WebSocket server to confirm signature completion.
    """
    # Support calling as sign_with_ncalayer(driver, password=..., p12_path=...)
    if password is not None and not isinstance(password, str) and hasattr(password, "find_elements"):
        driver = password
        password = None

    ensure_headless_ncalayer_running(log=log)

    resolved_p12 = resolve_p12_path(p12_path)
    resolved_pwd = resolve_p12_password(password, resolved_p12)

    # Record previous result timestamp before publishing new credentials
    prev_ts = 0
    if RESULT_FILE.exists():
        try:
            prev_data = json.loads(RESULT_FILE.read_text(encoding="utf-8"))
            prev_ts = int(prev_data.get("timestamp", 0))
        except Exception:
            prev_ts = 0

    req_id = _write_control_file(resolved_p12, resolved_pwd)
    cert_name = os.path.basename(resolved_p12)
    log(f"  🔐 [Headless NCALayer] Подписание ключом: {cert_name}")

    clicked_method = False
    last_error: Optional[str] = None
    deadline = time.time() + float(timeout)
    while time.time() < deadline:
        if not clicked_method and driver is not None:
            if _try_click_ncalayer_method_in_browser(driver, log):
                clicked_method = True
        if RESULT_FILE.exists():
            try:
                res = json.loads(RESULT_FILE.read_text(encoding="utf-8"))
                res_ts = int(res.get("timestamp", 0))
                res_req_id = int(res.get("req_id", 0))
                same_cert = res.get("p12_path") == resolved_p12
                # Either matched our req_id or completed very recently (within last 10s with same cert)
                if (
                    res_ts > prev_ts
                    and (
                        res_req_id == req_id
                        or res_ts >= (req_id - 2500)
                        or (same_cert and res_ts >= (req_id - 10000))
                    )
                ):
                    if res.get("ok", False):
                        log(
                            f"  ✅ [Headless NCALayer] ЭЦП сформирована "
                            f"({res.get('module')}.{res.get('method')}, {res.get('response_len')} байт)"
                        )
                        time.sleep(1.0)
                        return True
                    else:
                        # Frontend often sends a probe call first (e.g. without extKeyUsageOids)
                        # followed milliseconds later by the real signing call. Keep waiting!
                        last_error = res.get("error_preview", "unknown error")
                        prev_ts = res_ts
            except Exception:
                pass
        time.sleep(0.25)

    if last_error:
        log(f"  ❌ [Headless NCALayer] Ошибка формирования ЭЦП: {last_error}")
    else:
        log(f"  ⚠️ [Headless NCALayer] Запрос на подписание от браузера не поступил за {float(timeout):.0f} сек")
    return False
