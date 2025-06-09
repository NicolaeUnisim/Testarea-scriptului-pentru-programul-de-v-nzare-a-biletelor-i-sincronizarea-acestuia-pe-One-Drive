#Почему именно Python 3.12 https://www.python.org/downloads/windows/
# https://www.python.org/ftp/python/3.12.9/python-3.12.9-amd64.exe
#	На май 2025 г. официальных сборок pywin32 для Python 3.13 ещё нет.
#pip install qrcode fpdf Pillow oracledb pycryptodome pycryptodomex
#pip install pywin32
#
#$pythonPath = "$env:LOCALAPPDATA\Programs\Python\Python313"
#[Environment]::SetEnvironmentVariable("Path", $env:Path + ";$pythonPath;$pythonPath\Scripts", "User")
#https://download.oracle.com/otn_software/odac/Oracle-Client-for-Microsoft-Tools-64-bit.exe
#https://download.oracle.com/otn_software/odac/OracleClientForMicrosoftTools_x64_19.exe
#./DejaVuSans.ttf

#% !! tbl_reprints должен отправвялться в oracle также как и tbl_tickets 


# dino_ticket_gui.py
# ──────────────────
# Полноценная система продажи/печати билетов.
#   · show_gui()            – обычный режим (как было раньше);
#   · show_gui_embedded()   – режим для встраивания в Delphi.

import os, sys
import csv
import sqlite3
import random
import datetime
import hashlib
import platform
import qrcode
from fpdf import FPDF
from tkinter import *
from tkinter import ttk, messagebox, filedialog
# Встроенный фоновый процесс для отправки в Oracle
import threading
import time
import oracledb
import traceback
# ── Oracle Thick Mode Auto-init (по sqlplus без candidates) ──────────────
import shutil
import getpass
import uuid, webbrowser


ORACLE_DISABLED = False
ORACLE_AVAILABLE = False

CUT_COMMAND = b'\x1d\x56\x01\x00\x0a\x0a\x00'
DEFAULT_LOG_DIR = "LOG_prints"
PRINT_IMAGE= b'\x1B\x40\x1B\x61\x01\x1D\x54\x1C\x70\x01\x30\x1B\x40\x00'
SSS= b'\x0A\x0A\x0A\x0A\x0A\x0A\x00'
OnPrintLogTickets=False
os.makedirs(DEFAULT_LOG_DIR, exist_ok=True)
ERROR_LOG = os.path.join(DEFAULT_LOG_DIR, "errors.log")

# ── settings_ini_sanity.py ───────────────────────────────────────────
from configparser import ConfigParser
from pathlib import Path

CFG_PATH = Path(DEFAULT_LOG_DIR) / "settings.ini"

# ► базовые данные – правьте здесь, если нужно
DEFAULT_PRICE   = {"kids":"2300","regular":"2500","adult":"2700","family":"2000","invite":"0"}
DEFAULT_DEFAULT = {"serie":"KZ25","attraction":"Dino Festival KZ","currency":"KZT",
                   "language":"ru"}
DEFAULT_REASONS = [
    "инкасация","возврат денег за билет","кассиру на нужды",
    "отдал в долг инспектору","передал сумму следующему кассиру по смене",
    "проиграл в казино","прочее"
]
# ── в начале файла, рядом с DEFAULT_LABELS ──────────────
DEFAULT_CATEGORY_TITLES = {
    "ru": {
        "kids":    "Детский",
        "regular": "Общий",
        "adult":   "Взрослый",
        "family":  "Семейный",
        "invite":  "Пригласительный",
    },
    "en": {
        "kids":    "Kid",
        "regular": "Standard",
        "adult":   "Adult",
        "family":  "Family",
        "invite":  "Invitation",
    },
    "kz": {
        "kids":    "Балалар",
        "regular": "Жалпы",
        "adult":   "Ересек",
        "family":  "Отбасылық",
        "invite":  "Шақыру",
    },
    "ro": {
        "kids":    "Copil",
        "regular": "Standard",
        "adult":   "Adult",
        "family":  "Familie",
        "invite":  "Invitație",
    },
    "it": {
        "kids":    "Bambino",
        "regular": "Standard",
        "adult":   "Adulto",
        "family":  "Famiglia",
        "invite":  "Invito",
    },
}
DEFAULT_LABELS = {
    "ru": {"ticket":"БИЛЕТ","date":"ДАТА","attraction":"АТТРАКЦИОН","price":"ЦЕНА",
           "category":"КАТЕГОРИЯ","total":"СТОИМОСТЬ","number":"НОМЕР",
           "x_header":"X/Z-ОТЧЁТ","x_since":"С момента последнего Z:",
           "x_by_category":"--- ПО КАТЕГОРИЯМ ---","x_total":"--- ИТОГО ---",
           "x_count":"ВСЕГО БИЛЕТОВ","x_sum":"ОБОРОТ"},
    "en": {"ticket":"TICKET","date":"DATE","attraction":"ATTRACTION","price":"PRICE",
           "category":"CATEGORY","total":"TOTAL","number":"NUMBER",
           "x_header":"X/Z REPORT","x_since":"Since last Z:",
           "x_by_category":"--- BY CATEGORY ---","x_total":"--- TOTAL ---",
           "x_count":"TOTAL TICKETS","x_sum":"TURNOVER"},
    "kz": {"ticket":"БИЛЕТ","date":"КҮН","attraction":"АТТРАКЦИОН","price":"БАҒА",
           "category":"САНАТ","total":"ҚҰНЫ","number":"НОМЕР",
           "x_header":"X/Z ЕСЕП","x_since":"Соңғы Z-ден бері:",
           "x_by_category":"--- САНАТ БОЙЫНША ---","x_total":"--- БАРЛЫҒЫ ---",
           "x_count":"БИЛЕТ САНЫ","x_sum":"АУДАРЫЛЫМ"},
    "ro": {"ticket":"BILET","date":"DATA","attraction":"ATRACȚIE","price":"PREȚ",
           "category":"CATEGORIE","total":"TOTAL","number":"NUMĂR",
           "x_header":"RAPORT X/Z","x_since":"De la ultimul Z:",
           "x_by_category":"--- PE CATEGORII ---","x_total":"--- TOTAL ---",
           "x_count":"BILETE ÎN TOTAL","x_sum":"ÎNCASĂRI"},
    "it": {"ticket":"BIGLIETTO","date":"DATA","attraction":"ATTRAZIONE","price":"PREZZO",
           "category":"CATEGORIA","total":"TOTALE","number":"NUMERO",
           "x_header":"RAPPORTO X/Z","x_since":"Dall’ultimo Z:",
           "x_by_category":"--- PER CATEGORIA ---","x_total":"--- TOTALE ---",
           "x_count":"BIGLIETTI","x_sum":"FATTURATO"},
}

def ensure_settings_ini():
    cfg = ConfigParser()
    if CFG_PATH.exists():
        cfg.read(CFG_PATH, encoding="utf-8")

    # 1️⃣  цены
    if "prices" not in cfg:
        cfg["prices"] = DEFAULT_PRICE

    # 2️⃣  defaults
    if "defaults" not in cfg:
        cfg["defaults"] = DEFAULT_DEFAULT
    else:                                  # обеспечим наличие всех ключей
        for k,v in DEFAULT_DEFAULT.items():
            cfg["defaults"].setdefault(k, v)

    # 3️⃣  reasons  (в отдельной секции, чтобы легко расширять)
    if "reasons" not in cfg:
        cfg["reasons"] = {str(i):txt for i,txt in enumerate(DEFAULT_REASONS,1)}

    # 4️⃣  переводы
    for lang, labels in DEFAULT_LABELS.items():
        sec = f"labels_{lang}"
        if sec not in cfg:
            cfg[sec] = labels
        else:                              # если секция есть – дописываем недостающие ключи
            for k,v in labels.items():
                cfg[sec].setdefault(k, v)
    # 5️⃣  названия категорий
    for lang, names in DEFAULT_CATEGORY_TITLES.items():
        sec = f"categories_{lang}"
        if sec not in cfg:
            cfg[sec] = names
        else:
            for k, v in names.items():
                cfg[sec].setdefault(k, v)

    # сохраним, если что-то добавили
    with CFG_PATH.open("w", encoding="utf-8") as f:
        cfg.write(f)

    return cfg

# вызываем ОДИН раз в самом верху главного файла, вместо старых load_settings
CFG = ensure_settings_ini()
# ── сразу после CFG = ensure_settings_ini() ──────────────
# Человеческие названия категорий (можно тоже вынести в INI, если понадобится i18n)
CATEGORY_TITLES_old = {
    "kids":   "Детский",
    "regular":"Общий",
    "adult":  "Взрослый",
    "family": "Семейный",
    "invite": "Пригласительный",   # ← НОВОЕ
}
def load_category_titles(cfg: ConfigParser, lang: str):
    sec = f"categories_{lang}"
    if sec not in cfg:
        sec = f"categories_{cfg['defaults']['language']}"
    # если ключа нет — берём «capitalized» вариант ids → titles
    return {k: cfg[sec].get(k, k.capitalize()) for k in cfg["prices"]}
    
                
reasons = [CFG["reasons"][k] for k in sorted(CFG["reasons"], key=int)]
LANG = CFG["defaults"].get("language", "ru").lower()

def get_available_languages(cfg: ConfigParser):
    return [s.replace("labels_","") for s in cfg.sections() if s.startswith("labels_")]

def load_ticket_texts(cfg: ConfigParser, lang: str):
    sec = f"labels_{lang}"
    if sec not in cfg:
        # неизвестный язык → используем язык по умолчанию
        sec = f"labels_{cfg['defaults']['language']}"
    return dict(cfg[sec])
    
ticket_texts = load_ticket_texts(CFG,LANG)
CATEGORY_TITLES = load_category_titles(CFG, LANG)       # НОВОЕ!

# Динамический словарь для GUI/печати
TICKET_TYPES = {CATEGORY_TITLES[k]: int(v)
                for k, v in CFG["prices"].items()}


# словарь цен, пригодный для TICKET_TYPES
#TICKET_TYPES1 = {k.capitalize(): int(v) for k, v in CFG["prices"].items()}
print(TICKET_TYPES)


ticket_texts_old = {
    "ticket": "БИЛЕТ",
    "date": "ДАТА",
    "attraction": "АТТРАКЦИОН",
    "price": "ЦЕНА",
    "category": "КАТЕГОРИЯ",
    "total": "СТОИМОСТЬ",
    "number": "НОМЕР",
    "x_header": "X/Z-ОТЧЁТ",
    "x_since": "С момента последнего Z:",
    "x_by_category": "--- ПО КАТЕГОРИЯМ ---",
    "x_total": "--- ИТОГО ---",
    "x_count": "ВСЕГО БИЛЕТОВ",
    "x_sum": "ОБОРОТ",
}

reasons_old = [
        "инкасация",
        "возврат денег за билет",
        "кассиру на нужды",
        "отдал в долг инспектору",
        "передал сумму следующему кассиру по смене",
        "проиграл в казино",
        "прочее"
    ]

# Путь к логам и базе
DB_PATH = os.path.join(DEFAULT_LOG_DIR, "print_log.db")

# Получение имени пользователя и MAC-адреса
USERNAME = getpass.getuser()
MAC = ':'.join(f'{(uuid.getnode() >> ele) & 0xff:02x}' for ele in range(40, -1, -8))
HOSTNAME = platform.node()


def create_ticket_text(serie, product_name, price, currency, attraction, index):
    now = datetime.datetime.now()
    time_str = now.strftime("%H:%M %d.%m.%y")
    ticket_code = generate_ticket_code(serie)
    serial_number = f"{serie}-{index + 1} @ {time_str}"

    text = f"""
БИЛЕТ: "{ticket_code}"
ДАТА: "{time_str}"
АТТРАКЦИОН: "{attraction}"
ЦЕНА: "{price} {currency}"

КАТЕГОРИЯ: {product_name}
СТОИМОСТЬ: {price:.2f}

НОМЕР: {serial_number}
-------------------------
"""
    return text, ticket_code


def log_action(action: str, comment: str = ""):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
    CREATE TABLE IF NOT EXISTS xlog_actions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        action TEXT,
        timestamp TEXT DEFAULT CURRENT_TIMESTAMP,
        user TEXT,
        comment TEXT
    )
    """);    
    c.execute("""
        INSERT INTO xlog_actions (action, user, comment)
        VALUES (?, ?, ?)
    """, (action, USERNAME, comment))
    conn.commit()
    conn.close()

log_action("login", comment="Открытие GUI")
summary_refs = {}

def generate_ticket_code(serie):
    suffix = ''.join(random.choices("0123456789ABCDEF", k=6))
    return f"{serie}{datetime.datetime.now().strftime('%y%m%d')}{suffix}"


def log_ticket_text(text, price):
  if OnPrintLogTickets:
    now = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    folder = f"{DEFAULT_LOG_DIR}/printtickets_{now}_{price}"
    os.makedirs(folder, exist_ok=True)
    filename = os.path.join(folder, f"ticket_{now}.txt")
    with open(filename, "w", encoding="utf-8") as f:
        f.write(text)

try:
    import oracledb
    ORACLE_AVAILABLE = True
except ImportError:
    oracledb = None
    ORACLE_AVAILABLE = False

import uuid
from Cryptodome.Cipher import AES
from Cryptodome.Random import get_random_bytes
from Cryptodome.Protocol.KDF import PBKDF2
import base64

def get_mac_based_secret_old1(): 
    mac = uuid.getnode()
    mac_str = f"{mac:012X}"  # MAC в виде строки, например 'D4BED9AABBCC'
    sha256_hash = hashlib.sha256(mac_str.encode('utf-8')).hexdigest()
    # Форматируем как UUID-подобную строку длиной 36 символов
    formatted_uuid = f"{sha256_hash[:8]}-{sha256_hash[8:12]}-{sha256_hash[12:16]}-{sha256_hash[16:20]}-{sha256_hash[20:32]}"
    return formatted_uuid

# ВЕРСИЯ: переход от MAC к имени ПК + пользователя для шифра

def get_name_based_secret():
    """Формирует ключ на основе имени компьютера и пользователя."""
    base = f"{platform.node()}_{getpass.getuser()}"
    sha256_hash = hashlib.sha256(base.encode('utf-8')).hexdigest()
    return f"{sha256_hash[:8]}-{sha256_hash[8:12]}-{sha256_hash[12:16]}-{sha256_hash[16:20]}-{sha256_hash[20:32]}"


# заменяем старую функцию get_mac_based_secret на новую в коде
# и используем её вместо MAC в:
# - get_oracle_password
# - save_oracle_password

# ... ОРИГИНАЛ ФАЙЛ БЕЗ ИЗМЕНЕНИЙ ...
# --- Ниже только изменения по новым секретам ---
def get_mac_based_secret():
   return get_name_based_secret()
# ЗАМЕНИ В ФУНКЦИЯХ:

# БЫЛО:
# secret_phrase = get_mac_based_secret()
# СТАЛО:
secret_phrase = get_name_based_secret()

# в двух местах: get_oracle_password и save_oracle_password


def aes_cbc_encrypt(password, secret_phrase):
    iv = get_random_bytes(16)
    key = PBKDF2(secret_phrase, iv, dkLen=32, count=10000)
    pad = lambda s: s + (16 - len(s) % 16) * chr(16 - len(s) % 16)
    password = pad(password)
    cipher = AES.new(key, AES.MODE_CBC, iv)
    encrypted = cipher.encrypt(password.encode('utf-8'))
    return base64.b64encode(iv + encrypted).decode('utf-8')

def aes_cbc_decrypt(encrypted_data, secret_phrase):
    encrypted_data = base64.b64decode(encrypted_data)
    iv = encrypted_data[:16]
    encrypted_data = encrypted_data[16:]
    key = PBKDF2(secret_phrase, iv, dkLen=32, count=10000)
    cipher = AES.new(key, AES.MODE_CBC, iv)
    decrypted = cipher.decrypt(encrypted_data)
    padding_size = decrypted[-1]
    decrypted = decrypted[:-padding_size]
    return decrypted.decode('utf-8')

def get_oracle_password(db_path):
    secret_phrase = get_mac_based_secret()
    os.makedirs(os.path.dirname(db_path), exist_ok=True) if os.path.dirname(db_path) else None
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS ini_settings (
            id INTEGER PRIMARY KEY,
            name TEXT UNIQUE,
            value TEXT,
            iscoded INTEGER
        )
    ''')
    c.execute("SELECT value FROM ini_settings WHERE name = 'oracle_password'")
    row = c.fetchone()
    conn.close()

    if row:
        try:
            return aes_cbc_decrypt(row[0], secret_phrase)
        except Exception:
            return None
    else:
        return None

def save_oracle_password(password, db_path=DB_PATH):
    secret_phrase = get_mac_based_secret()
    encrypted = aes_cbc_encrypt(password, secret_phrase)
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO ini_settings (name, value, iscoded) VALUES (?, ?, ?)", ("oracle_password", encrypted, 1))
    conn.commit()
    conn.close()
    
import os
import platform
import urllib.request
import subprocess
import time

ORACLE_CLIENT_DIR = r"C:\Program Files\Oracle Client for Microsoft Tools"
ORACLE_OCI_DLL = os.path.join(ORACLE_CLIENT_DIR, "oci.dll")
ORACLE_INSTALLER_URL = "https://download.oracle.com/otn_software/odac/Oracle-Client-for-Microsoft-Tools-64-bit.exe"
ORACLE_INSTALLER_PATH = os.path.join(os.environ.get("TEMP", "."), "oracle_client_installer.exe")


def ensure_oracle_client_installed():
    if platform.system() != "Windows":
        return  # Только для Windows

    if os.path.isfile(ORACLE_OCI_DLL):
        print("[✓] Oracle Client уже установлен.")
        return

    print("[!] Oracle Client не найден, начинаю загрузку...")

    # Скачать установщик
    try:
        urllib.request.urlretrieve(ORACLE_INSTALLER_URL, ORACLE_INSTALLER_PATH)
        print(f"[→] Загружен установщик: {ORACLE_INSTALLER_PATH}")
    except Exception as e:
        print(f"[✘] Ошибка при загрузке установщика: {e}")
        return

    # Запуск установщика
    try:
        print("[→] Запуск установщика, ожидаем завершения...")
        proc = subprocess.Popen([ORACLE_INSTALLER_PATH], shell=True)
        proc.wait()
    except Exception as e:
        print(f"[✘] Ошибка запуска установщика: {e}")
        return

    # Повторная проверка
    for _ in range(10):
        if os.path.isfile(ORACLE_OCI_DLL):
            print("[✓] Oracle Client установлен успешно.")
            return
        print("[…] Ожидание установки Oracle Client...")
        time.sleep(3)

    print("[✘] Oracle Client не был найден даже после установки.")

# Использование перед init_oracle_client
ensure_oracle_client_installed()

def find_instant_client_dir():
    """Находит путь к Oracle Instant Client по расположению sqlplus."""
    filename = {
        "Darwin": "libclntsh.dylib",
        "Windows": "oci.dll",
        "Linux": "libclntsh.so"
    }.get(platform.system())

    if platform.system() != "Windows":
       sqlplus_path = shutil.which("sqlplus")
    else:  
       sqlplus_path = "C:/Program Files/Oracle Client for Microsoft Tools/" #
    if not sqlplus_path:
        return None

    inst_dir = os.path.dirname(sqlplus_path)
    if os.path.isfile(os.path.join(inst_dir, filename)):
        return inst_dir
    return None

# Инициализация Oracle клиента (если возможно)
if ORACLE_AVAILABLE and hasattr(oracledb, "init_oracle_client"):
    client_path = find_instant_client_dir()
    if client_path:
        try:
            oracledb.init_oracle_client(lib_dir=client_path)
        except Exception as e:
            print(f"[!] Oracle Thick mode init failed: {e}")
    else:
        print("[!] Instant Client not found ‒ Oracle disabled")
         
def init_oracle_client_safe():
    global ORACLE_DISABLED
    if ORACLE_DISABLED:
        return

    client_dir = find_instant_client_dir()
    if client_dir:
        try:
            oracledb.init_oracle_client(lib_dir=client_dir)
            print(f"[i] Oracle thick mode OK ({client_dir})")
        except Exception as e:
            print(f"[!] Thick mode init failed: {e}")
            ORACLE_DISABLED = True          # больше не пробуем
    else:
        print("[!] Instant Client not found ‒ Oracle disabled")
        ORACLE_DISABLED = True              # больше не пробуем

init_oracle_client_safe()
 
from tkinter import simpledialog

password=get_oracle_password(DB_PATH)
#print(f"orapassw={password}")
if not password and not ORACLE_DISABLED:
    password = simpledialog.askstring("Пароль Oracle", "Введите пароль:", show='*')
    if password:
        save_oracle_password(password)
    else:
        messagebox.showerror("Ошибка", "Пароль Oracle не задан — завершение.")
        sys.exit(1)
 
    
# Параметры подключения
ORACLE_DSN = f"test/{password}@orange.una.md:4024/clouddev.world"
  
# Константы
IS_WINDOWS = platform.system() == "Windows"
if IS_WINDOWS:
    import win32print
else:
    import subprocess

TICKET_TYPES_old = {"Детский": 2300, "Общий": 2500, "Взрослый": 2700, "Семейный": 2000}


# ── 1. ЛОГ-ФАЙЛ и функция log_error ───────────────────────────────────────────

def log_error(msg, exc=None, show_trace=True):
    """Логирует ошибку в файл и сразу выводит в терминал."""
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] ❌ {msg}", file=sys.stderr)
    if exc and show_trace:
        print(traceback.format_exc(), file=sys.stderr)
    with open(ERROR_LOG, "a", encoding="utf-8") as f:
        f.write(f"[{ts}] {msg}\n")
        if exc and show_trace:
            f.write(traceback.format_exc() + "\n")
                       
# ──────────────────────────────────────────────────────────────────
# блок вспомогательных функций (без изменений) ↓↓↓
def generate_ticket_code(serie):
    suffix = ''.join(random.choices("0123456789ABCDEF", k=6))
    return f"{serie}{datetime.datetime.now().strftime('%y%m%d')}{suffix}"

def generate_deal_hash(timestamp, accepted, total_sum):
    data = f"{timestamp}|{accepted}|{total_sum}|{os.urandom(8).hex()}"
    return hashlib.sha256(data.encode()).hexdigest()

def save_deal(total_sum, accepted, change):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    deal_hash = generate_deal_hash(timestamp, accepted, total_sum)
    hostname = platform.node()
    c.execute('''INSERT INTO tbl_deals (hash_deal, ts_deal, amt_total, amt_accepted, amt_change, name_host, ts_sync_due, user_name, mac)
                 VALUES (?, ?, ?, ?, ?, ?, NULL, ?, ?)''',
              (deal_hash, timestamp, total_sum, accepted, change, hostname, USERNAME, MAC))
    deal_id = c.lastrowid
    conn.commit()
    conn.close()
    return deal_id, deal_hash

def save_ticket(ticket_code, serie, index, product, attraction, price, currency, deal_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    full_host = HOSTNAME #get_full_host()
    c.execute('''INSERT INTO tbl_tickets (code_ticket, code_serie, ticket_no, ts_ticket, name_product, name_attraction, amt_price, name_currency, id_deal_ref)
                 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
              (ticket_code, serie, index + 1, timestamp, product, attraction, price, currency, deal_id))
    conn.commit()
    conn.close()

def generate_order_pdf(tickets, attraction, serie, accepted, change, filename):
    pdf = FPDF()
    #font_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    #if not os.path.isfile(font_path):
    font_path = "./DejaVuSans.ttf"
    try:
        pdf.add_font("DejaVu", "", font_path, uni=True)
        pdf.set_font("DejaVu", "", 14)
    except RuntimeError:
        pdf.set_font("Arial", size=14)
    
    

    for i, ticket in enumerate(tickets):
        ticket_code, product, price, currency = ticket
        pdf.add_page()
        timestamp = datetime.datetime.now().strftime("%d.%m.%Y %H:%M")
        pdf.cell(0, 10, f"БИЛЕТ: {ticket_code}", ln=True)
        pdf.cell(0, 10, f"ДАТА: {timestamp}", ln=True)
        pdf.cell(0, 10, f"АТТРАКЦИОН: {attraction}", ln=True)
        pdf.cell(0, 10, f"КАТЕГОРИЯ: {product}", ln=True)
        pdf.cell(0, 10, f"ЦЕНА: {price} {currency}", ln=True)
        pdf.cell(0, 10, f"СЕРИЯ: {serie}-{i + 1}", ln=True)
        pdf.cell(0, 10, f"ПРИНЯТО: {accepted}", ln=True)
        pdf.cell(0, 10, f"СДАЧА: {change}", ln=True)
        qr_path = os.path.join(DEFAULT_LOG_DIR, f"{ticket_code}.png")
        qrcode.make(f"{ticket_code} | {product} | {price} {currency} | {attraction}").save(qr_path)
        pdf.image(qr_path, x=80, y=100, w=50)
        os.remove(qr_path)

    pdf.output(os.path.join(DEFAULT_LOG_DIR, filename))

def print_to_printer_winHQPRST(printer_name, data):
    try:
        hprinter = win32print.OpenPrinter(printer_name)
        hjob = win32print.StartDocPrinter(hprinter, 1, ("Печать билета", None, "RAW"))
        win32print.StartPagePrinter(hprinter)
        win32print.WritePrinter(hprinter, PRINT_IMAGE)
        cleaned_data = data.encode("cp866", errors="ignore").decode("cp866")
        win32print.WritePrinter(hprinter, cleaned_data.encode("cp866"))
        win32print.WritePrinter(hprinter, SSS)
        win32print.WritePrinter(hprinter, CUT_COMMAND)
        win32print.EndPagePrinter(hprinter)
        win32print.EndDocPrinter(hprinter)
        win32print.ClosePrinter(hprinter)
    except Exception as e:
        print(f"Ошибка печати: {e}")

def print_to_printer(printer_name, data):
    if IS_WINDOWS:
        print_to_printer_winHQPRST(printer_name, data)
    else:
        subprocess.run(["lp", "-d", printer_name], input=data.encode("utf-8"))

def print_multiple_tickets(serie, count, price, currency, product_name, attraction, printer_name):
    for i in range(count):
        text, ticket_code = create_ticket_text(serie, product_name, price, currency, attraction, i)
        print(f"Печатаем билет {i + 1}...\n{text}")
        log_ticket_text(text, price)
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        #log_ticket_csv_sqlite(ticket_code, serie, i, now_str, product_name, attraction, price, currency)
        print_to_printer(printer_name, text)

def beep_success():
   if IS_WINDOWS:
    try:
        import winsound
        winsound.MessageBeep(winsound.MB_OK)
    except:
        print('[!] Beep failed (success)')

def beep_error():
   if IS_WINDOWS:
    try:
        import winsound
        winsound.MessageBeep(winsound.MB_ICONHAND)
    except:
        print('[!] Beep failed (error)')
        
# ──────────────────────────────────────────────────────────────────
#                    ↓↓↓  общее построение GUI  ↓↓↓
# Расширенная миграция структуры БД (deals + sync/версии)
def initialize_tmdb_docs_cash_database():
    from datetime import datetime

    return;
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # Включаем поддержку внешних ключей
    c.execute("PRAGMA foreign_keys = ON")

    # Проверка, есть ли уже документы
    c.execute("SELECT COUNT(*) FROM TMDB_DOCS")
    if c.fetchone()[0] == 0:
        now = datetime.now().isoformat(timespec="seconds")
        for i in range(1, 4):
            cod = 1000 + i
            c.execute('''INSERT INTO TMDB_DOCS (
                COD, TIP, SYSFID, USERID, AT1, AT2, AT3,
                TIPDOC, DATAMANUAL, NRMANUAL, VALUTA, NRSET,
                ISGFC, DOCCOLOR, CODF, TIPOPER, F, M, DIV, STATUS
            ) VALUES (?, 'T', 1, 1, 0, 0, 0, 1, ?, ?, 'MDL', 1, 0, 'R', 100, 200, 'Y', 'N', 1, 0)''',
                (cod, now, f'DOC-{cod}'))

            # Z отчёт
            c.execute("INSERT INTO TMDB_DOCS_Z (DOC_COD, TIMESTAMP, TOTAL, TICKETS, CASH_REMOVED) VALUES (?, ?, ?, ?, ?)",
                      (cod, now, 100.0 * i, 10 * i, 5.0 * i))

            # Касса старт
            c.execute("INSERT INTO TMDB_DOCS_CASH_START (DOC_COD, TS_START, AMOUNT, USER_NAME, MAC) VALUES (?, ?, ?, ?, ?)",
                      (cod, now, 50.0 * i, "demo_user", "00:11:22:33:44:55"))

            # Движения по кассе
            for j in range(2):
                c.execute('''INSERT INTO TMDB_DOCS_CASH_OPS (
                    DOC_COD, TS_OP, AMOUNT, OP_TYPE, REASON, USER_NAME, MAC
                ) VALUES (?, ?, ?, ?, ?, ?, ?)''',
                    (cod, now, 20.0 * (j + 1), "sale", f"reason-{j}", "demo_user", "00:11:22:33:44:55"))
        print(f"[✓] База данных '{DB_PATH}' инициализирована успешно.")

    conn.commit()
    conn.close()

    
def migrate_schema():
    import socket
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    cursor = c

    commands = [
    '''
    PRAGMA foreign_keys = ON;
    ''',
    '''
    CREATE TABLE IF NOT EXISTS TMDB_DOCS (
        COD INTEGER PRIMARY KEY,
        TIP TEXT,
        SYSFID INTEGER,
        USERID INTEGER,
        AT1 INTEGER,
        AT2 INTEGER,
        AT3 INTEGER,
        TIPDOC INTEGER,
        DATAMANUAL TEXT NOT NULL,
        NRMANUAL TEXT,
        VALUTA TEXT,
        NRSET INTEGER NOT NULL,
        ISGFC INTEGER DEFAULT 0 NOT NULL,
        DOCCOLOR TEXT,
        CODF INTEGER,
        TIPOPER INTEGER,
        F TEXT,
        M TEXT,
        DIV INTEGER,
        STATUS INTEGER
    );
    ''',
    '''
    CREATE TABLE IF NOT EXISTS TMDB_DOCS_Z (
        ID_Z INTEGER PRIMARY KEY AUTOINCREMENT,
        DOC_COD INTEGER,
        TIMESTAMP TEXT,
        TOTAL REAL,
        TICKETS INTEGER,
        CASH_REMOVED REAL,
        FOREIGN KEY (DOC_COD) REFERENCES TMDB_DOCS(COD) ON DELETE CASCADE
    );
    ''',
    '''
    CREATE TABLE IF NOT EXISTS TMDB_DOCS_CASH_START (
        ID INTEGER PRIMARY KEY AUTOINCREMENT,
        DOC_COD INTEGER,
        TS_START TEXT,
        AMOUNT REAL,
        USER_NAME TEXT,
        MAC TEXT,
        FOREIGN KEY (DOC_COD) REFERENCES TMDB_DOCS(COD) ON DELETE CASCADE
    );
    ''',
    '''
    CREATE TABLE IF NOT EXISTS TMDB_DOCS_CASH_OPS (
        ID INTEGER PRIMARY KEY AUTOINCREMENT,
        DOC_COD INTEGER,
        TS_OP TEXT,
        AMOUNT REAL,
        OP_TYPE TEXT,
        REASON TEXT,
        USER_NAME TEXT,
        MAC TEXT,
        FOREIGN KEY (DOC_COD) REFERENCES TMDB_DOCS(COD) ON DELETE CASCADE
    );
    ''',
    '''
    CREATE TABLE IF NOT EXISTS tbl_deals (
        id_deal INTEGER PRIMARY KEY AUTOINCREMENT,
        hash_deal TEXT UNIQUE,
        ts_deal TEXT,
        amt_total REAL,
        amt_accepted REAL,
        amt_change REAL,
        name_host TEXT,
        ts_sync_due TEXT,
        user_name TEXT,
        mac TEXT
    );
    ''',
    '''
    CREATE TABLE IF NOT EXISTS tbl_tickets (
        id_ticket INTEGER PRIMARY KEY AUTOINCREMENT,
        code_ticket TEXT,
        code_serie TEXT,
        ticket_no INTEGER,
        ts_ticket TEXT,
        name_product TEXT,
        name_attraction TEXT,
        amt_price REAL,
        name_currency TEXT,
        id_deal_ref INTEGER REFERENCES tbl_deals(id_deal)
    );
    ''',
    '''
    CREATE TABLE IF NOT EXISTS tbl_z_state (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        last_z_time TEXT
    );
    ''',
    '''
    CREATE TABLE IF NOT EXISTS tbl_z_reports (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT,
        total REAL,
        tickets INTEGER,
        cash_removed REAL DEFAULT 0.0
    );
    ''',
    '''
    CREATE TABLE IF NOT EXISTS tbl_sync_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name_table TEXT,
        id_record INTEGER,
        status TEXT,
        message TEXT,
        ts_synced TEXT DEFAULT CURRENT_TIMESTAMP
    );
    ''',
    '''
    CREATE TABLE IF NOT EXISTS ini_settings (
        id INTEGER PRIMARY KEY,
        name TEXT UNIQUE,
        value TEXT,
        iscoded INTEGER
    );
    ''',
    '''
    CREATE TABLE IF NOT EXISTS reprints (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ticket_code TEXT,
        timestamp TEXT
    );
    ''',
    '''
    CREATE TABLE IF NOT EXISTS xlog_actions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        action TEXT,
        timestamp TEXT DEFAULT CURRENT_TIMESTAMP,
        user TEXT,
        comment TEXT
    );
    ''',
    '''
    CREATE TABLE IF NOT EXISTS tbl_cash_withdrawals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts_withdraw TEXT,
        amount REAL,
        reason_id INTEGER,
        reason TEXT,
        user TEXT,
        ts_sync_due TEXT,
        name_host TEXT,
        mac TEXT
    );
    ''',
    '''
    CREATE TABLE IF NOT EXISTS tbl_cash_start (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts_start TEXT NOT NULL,
        amount REAL,
        user TEXT,
        name_host TEXT,
        mac TEXT,
        day_only TEXT GENERATED ALWAYS AS (substr(ts_start, 1, 10)) VIRTUAL,
        UNIQUE(day_only)
    );
    ''',
    '''
    CREATE TABLE IF NOT EXISTS tbl_reprints (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        code_ticket TEXT,
        ts_reprint TEXT
    );
    ''',
    '''
    CREATE TABLE IF NOT EXISTS tbl_schema_versions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        version TEXT,
        ts_applied TEXT DEFAULT CURRENT_TIMESTAMP
    );
    ''',
    '''
    CREATE VIEW IF NOT EXISTS vw_z_summary AS
    SELECT d.COD, d.NRMANUAL, z.TOTAL, z.TICKETS, z.TIMESTAMP
    FROM TMDB_DOCS d
    JOIN TMDB_DOCS_Z z ON d.COD = z.DOC_COD;
    ''',
    '''
    CREATE VIEW IF NOT EXISTS vw_cash_summary AS
    SELECT d.COD, d.NRMANUAL,
           COALESCE(cs.AMOUNT, 0) AS start_cash,
           COALESCE(SUM(co.AMOUNT), 0) AS cash_ops
    FROM TMDB_DOCS d
    LEFT JOIN TMDB_DOCS_CASH_START cs ON d.COD = cs.DOC_COD
    LEFT JOIN TMDB_DOCS_CASH_OPS co ON d.COD = co.DOC_COD
    GROUP BY d.COD, d.NRMANUAL, cs.AMOUNT;
    ''',
    '''
    CREATE INDEX IF NOT EXISTS idx_z_doc_cod ON TMDB_DOCS_Z(DOC_COD);
    ''',
    '''
    CREATE INDEX IF NOT EXISTS idx_cash_start_doc_cod ON TMDB_DOCS_CASH_START(DOC_COD);
    ''',
    '''
    CREATE INDEX IF NOT EXISTS idx_cash_ops_doc_cod ON TMDB_DOCS_CASH_OPS(DOC_COD);
    ''',
    '''
    CREATE INDEX IF NOT EXISTS idx_tickets_id_deal_ref ON tbl_tickets(id_deal_ref);
    ''',
    '''
    CREATE INDEX IF NOT EXISTS idx_deals_hash ON tbl_deals(hash_deal);
    ''',
    '''
    CREATE INDEX IF NOT EXISTS idx_sync_log_record ON tbl_sync_log(name_table, id_record);
    ''',
    '''
    CREATE INDEX IF NOT EXISTS idx_cash_withdrawals_ts ON tbl_cash_withdrawals(ts_withdraw);
    ''',
    '''
    CREATE INDEX IF NOT EXISTS idx_tickets_ts_ticket ON tbl_tickets(ts_ticket);
    ''',
    '''
    CREATE INDEX IF NOT EXISTS idx_deals_ts_deal ON tbl_deals(ts_deal);
    ''',
    '''
    CREATE INDEX IF NOT EXISTS idx_withdrawals_ts ON tbl_cash_withdrawals(ts_withdraw);
    ''',
    '''
    CREATE INDEX IF NOT EXISTS idx_cash_start_ts ON tbl_cash_start(ts_start);
    ''',
    '''
    CREATE INDEX IF NOT EXISTS idx_sync_log_ts ON tbl_sync_log(ts_synced);
    '''    
    ]

    # Выполнение всех команд
    for cmd in commands:
        cursor.execute(cmd)

    # Проверка новых колонок 
    c.execute("PRAGMA table_info(tbl_deals)")
    deal_cols = [row[1] for row in c.fetchall()]
    if "name_host" not in deal_cols:
        c.execute("ALTER TABLE tbl_deals ADD COLUMN name_host TEXT")

    # Фиксируем миграцию
    c.execute("SELECT version FROM tbl_schema_versions ORDER BY id DESC LIMIT 1")
    last = c.fetchone()
    vers = "v6-11 puncts-en"
    if not last or last[0] != vers:
        c.execute("INSERT INTO tbl_schema_versions (version) VALUES (?)", (vers,))

    initialize_tmdb_docs_cash_database()


    conn.commit()
    conn.close()


def ensure_oracle_tables():
    global ORACLE_DISABLED
    if ORACLE_DISABLED:
        return
    try:
        conn = oracledb.connect(ORACLE_DSN)
        cur = conn.cursor()

        cur.execute("""
        BEGIN
          -- 1. tbl_deals
          BEGIN
            EXECUTE IMMEDIATE '
              CREATE TABLE tbl_deals (
                id_deal      NUMBER,
                hash_deal    VARCHAR2(64) UNIQUE,
                ts_deal      DATE,
                amt_total    NUMBER(12,2),
                amt_accepted NUMBER(12,2),
                amt_change   NUMBER(12,2),
                name_host    VARCHAR2(128),
                ts_sync_due  DATE,
                CONSTRAINT FK_DEAL_TBL PRIMARY KEY (id_deal, name_host)
              )';
          EXCEPTION WHEN OTHERS THEN
            IF SQLCODE != -955 THEN RAISE; END IF;
          END;

          -- 2. tbl_tickets
          BEGIN
            EXECUTE IMMEDIATE '
              CREATE TABLE tbl_tickets (
                id_ticket      NUMBER,
                name_host      VARCHAR2(128),
                code_ticket    VARCHAR2(64),
                code_serie     VARCHAR2(16),
                ticket_no      NUMBER,
                ts_ticket      DATE,
                name_product   VARCHAR2(64),
                name_attraction VARCHAR2(128),
                amt_price      NUMBER(12,2),
                name_currency  VARCHAR2(8),
                id_deal_ref    NUMBER
              )';
          EXCEPTION WHEN OTHERS THEN
            IF SQLCODE != -955 THEN RAISE; END IF;
          END;

          -- 3. FK
          DECLARE
            cnt INTEGER;
          BEGIN
            SELECT COUNT(*) INTO cnt
            FROM user_constraints
            WHERE constraint_name = 'FK_TICKETS_DEALS'
              AND table_name = 'TBL_TICKETS';

            IF cnt = 0 THEN
              EXECUTE IMMEDIATE '
                ALTER TABLE tbl_tickets
                ADD CONSTRAINT FK_TICKETS_DEALS
                FOREIGN KEY (id_deal_ref, name_host)
                REFERENCES tbl_deals(id_deal, name_host)';
            END IF;
          EXCEPTION WHEN OTHERS THEN
            IF SQLCODE NOT IN (-2261, -2260) THEN RAISE; END IF;
          END;
        END;
        """)

        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        ORACLE_DISABLED = True
        log_error("Oracle disabled ‒ connection failed", e)

def log_withdrawal(amount, reason_id, reason_text, comment=""):
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        INSERT INTO tbl_cash_withdrawals (
            ts_withdraw, amount, reason_id, reason, user, ts_sync_due, name_host, mac
        ) VALUES (?, ?, ?, ?, ?, NULL, ?, ?)
    ''', (now, amount, reason_id, reason_text, USERNAME, HOSTNAME, MAC))
    conn.commit()
    conn.close()
    update_summary()
    messagebox.showinfo("Готово", f"Изъятие {amount:.2f} записано")
 
def open_withdrawal_form():
    win = Toplevel()
    win.title("Изъятие денег")
    win.geometry("400x250")

    Label(win, text="Сумма:").pack(pady=(10, 0))
    amount_var = StringVar()
    Entry(win, textvariable=amount_var).pack()

    Label(win, text="Причина:").pack(pady=(10, 0))
    reason_var = StringVar(value=reasons[0])
    OptionMenu(win, reason_var, *reasons).pack()

    Label(win, text="Комментарий:").pack(pady=(10, 0))
    comment_var = StringVar()
    Entry(win, textvariable=comment_var).pack()

    def submit():
        try:
            amount = float(amount_var.get())
            reason = reason_var.get()
            reason_id = reasons.index(reason) + 1
            comment = comment_var.get()
            log_withdrawal(amount, reason_id, reason, comment)
            win.destroy()
        except Exception as e:
            messagebox.showerror("Ошибка", f"Неверная сумма: {e}")

    Button(win, text="Записать", command=submit).pack(pady=15)
    

def get_last_z_time():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT last_z_time FROM tbl_z_state WHERE id = 1")
    row = c.fetchone()
    conn.close()
    if row and row[0]:
        return datetime.datetime.strptime(row[0].split('.')[0].replace('T', ' '), "%Y-%m-%d %H:%M:%S")
    return None
        
def check_z_timer_and_color_old1(z_btn):
    last = get_last_z_time()
    if not last or (datetime.datetime.now() - last).total_seconds() > 86400:
        z_btn.config(bg="red", fg="white")

def check_z_timer_and_color(z_btn):
    last = get_last_z_time()
    if not last or (datetime.datetime.now() - last).total_seconds() > 14400:
        z_btn.config(bg="red", fg="white")
    else:
        z_btn.config(bg="SystemButtonFace", fg="black")

       
# ──────────────────────────────────────────────────────────────────
def _build_gui(root):
    """Вся разметка и логика (была внутри старого show_gui)."""
    root.protocol("WM_DELETE_WINDOW", lambda: (log_action("logout", comment="Закрытие GUI"), root.destroy()))

    migrate_schema()

    root.title("Dino Festival KZ - Билеты")
    root.geometry("1200x700")

    # ---------- левые/правые панели ----------
    left_frame = Frame(root)
    left_frame.pack(side=LEFT, fill=BOTH, expand=True, padx=10, pady=10)

    right_frame = Frame(root)
    right_frame.pack(side=RIGHT, fill=Y, padx=10, pady=10)
    payment_type_var = StringVar(value="наличные")  # по умолчанию

    # ---------- таблица сделок ----------
    Label(right_frame, text="История сделок",
          font=("Arial", 14, "bold")).pack()
    columns = ("hash", "timestamp", "total", "accepted", "change")
    deal_tree = ttk.Treeview(right_frame, columns=columns,
                             show="headings", height=20)
    for col in columns:
        deal_tree.heading(col, text=col.upper())
        deal_tree.column(col, width=150)
    deal_tree.pack(fill=Y, expand=True)

    def load_deals():
        deal_tree.delete(*deal_tree.get_children())
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT hash_deal, ts_deal, amt_total, amt_accepted, amt_change FROM tbl_deals ORDER BY id_deal DESC")
        rows = c.fetchall()
        conn.close()
        if not rows:
            messagebox.showinfo("Информация", "Сделки не найдены. Сначала создайте хотя бы одну через печать.")
            return
        for row in rows:
            deal_tree.insert("", "end", values=row)



    #  второй Treeview для билетов выбранной сделки

    #  грид билетов — все поля таблицы tickets
    Label(right_frame, text="Билеты сделки", font=("Arial", 12, "bold")).pack(pady=(10, 0))
    ticket_columns = ["id_ticket", "code_ticket", "code_serie", "ticket_no", "ts_ticket", "name_product", "name_attraction", "amt_price", "name_currency"]
    ticket_tree = ttk.Treeview(right_frame, columns=ticket_columns, show="headings", height=5)
    for col in ticket_columns:
        ticket_tree.heading(col, text=col.upper())
        ticket_tree.column(col, width=110)
    ticket_tree.pack(fill=Y, expand=True)

    def load_tickets_for(deal_id):
        ticket_tree.delete(*ticket_tree.get_children())
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM tbl_tickets WHERE id_deal_ref = ?", (deal_id,))
        count = c.fetchone()[0]
        if count == 0:
            conn.close()
            messagebox.showinfo("Нет билетов", f"Для сделки #{deal_id} билеты не найдены.")
            return
        c.execute(f"SELECT {', '.join(ticket_columns)} FROM tbl_tickets WHERE id_deal_ref = ?", (deal_id,))
        for row in c.fetchall():
            ticket_tree.insert("", "end", values=row)
        conn.close()


    def on_deal_select(event):
        selected = deal_tree.selection()
        if selected:
            item = deal_tree.item(selected[0])
            deal_hash = item['values'][0]
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            c.execute("SELECT id_deal FROM tbl_deals WHERE hash_deal = ?", (deal_hash,))
            result = c.fetchone()
            conn.close()
            if result:
                load_tickets_for(result[0])

    deal_tree.bind("<<TreeviewSelect>>", on_deal_select)

    from PIL import Image, ImageTk


    def show_ticket_details(ticket_data):
        detail_win = Toplevel(root)
        detail_win.title(f"Билет: {ticket_data['code_ticket']}")
        Label(detail_win, text=f"КАТЕГОРИЯ: {ticket_data['name_product']}", font=("Arial", 12)).pack()
        Label(detail_win, text=f"ЦЕНА: {ticket_data['amt_price']} {ticket_data['name_currency']}").pack()
        Label(detail_win, text=f"АТТРАКЦИОН: {ticket_data['name_attraction']}").pack()
        Label(detail_win, text=f"СЕРИЯ: {ticket_data['code_serie']}  №{ticket_data['ticket_no']}").pack()

        qr_content = (
            f"{ticket_data['code_ticket']} | {ticket_data['name_product']} | "
            f"{ticket_data['amt_price']} {ticket_data['name_currency']} | {ticket_data['name_attraction']}"
        )
        qr_img = qrcode.make(qr_content)
        qr_img_path = os.path.join(DEFAULT_LOG_DIR, f"{ticket_data['code_ticket']}_preview.png")
        qr_img.save(qr_img_path)

        from PIL import Image, ImageTk
        img = Image.open(qr_img_path)
        img = img.resize((200, 200))
        img_tk = ImageTk.PhotoImage(img)
        qr_label = Label(detail_win, image=img_tk)
        qr_label.image = img_tk
        qr_label.pack()


        def reprint():
            printer_name = win32print.GetDefaultPrinter() if IS_WINDOWS else "default"
            price = float(ticket_data['amt_price'])  
            print_multiple_tickets(
                serie=ticket_data['code_serie'],
                count=1,
                price=price,
                currency=ticket_data['name_currency'],
                product_name=ticket_data['name_product'],
                attraction=ticket_data['name_attraction'],
                printer_name=printer_name
            )
            _log_reprint(ticket_data['code_ticket'])
            beep_success()
            messagebox.showinfo("Печать", "Билет успешно напечатан.")
    
        Button(detail_win, text="Повторная печать", command=reprint, bg="lightblue").pack(pady=10)
        detail_win.protocol("WM_DELETE_WINDOW", lambda: (os.remove(qr_img_path), detail_win.destroy()))
    
    

    def reprint_ticket_old():
        text = (
                f"БИЛЕТ: {ticket_data['code_ticket']}\n"
                f"КАТЕГОРИЯ: {ticket_data['name_product']}\n"
                f"ЦЕНА: {ticket_data['amt_price']} {ticket_data['name_currency']}\n"
                f"АТТРАКЦИОН: {ticket_data['name_attraction']}\n"
                f"СЕРИЯ: {ticket_data['code_serie']} №{ticket_data['ticket_no']}\n"
        )
        print_to_printer(win32print.GetDefaultPrinter() if IS_WINDOWS else "default", text)
        _log_reprint(ticket_data['code_ticket'])
        beep_success()
        
        Button(detail_win, text="Печать повторно", command=reprint_ticket).pack(pady=10)
        detail_win.protocol("WM_DELETE_WINDOW", lambda: (os.remove(qr_img_path), detail_win.destroy()))

    def on_ticket_double_click(event):
        selected = ticket_tree.selection()
        if selected:
            values = ticket_tree.item(selected[0])['values']
            keys = ticket_tree['columns']
            ticket_data = dict(zip(keys, values))
            show_ticket_details(ticket_data)

    ticket_tree.bind("<Double-1>", on_ticket_double_click)

    # ... (всё остальное без изменений)

    def _log_reprint(ticket_code):
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS tbl_reprints (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        ticket_code TEXT,
                        timestamp TEXT
                    )''')
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        c.execute("INSERT INTO reprints (ticket_code, timestamp) VALUES (?, ?)", (ticket_code, now))
        conn.commit()
        conn.close()
    def reprint_ticket_old():
        text = (
            f"БИЛЕТ: {ticket_data['code_ticket']}\n"
            f"КАТЕГОРИЯ: {ticket_data['name_product']}\n"
            f"ЦЕНА: {ticket_data['amt_price']} {ticket_data['name_currency']}\n"
            f"АТТРАКЦИОН: {ticket_data['name_attraction']}\n"
            f"СЕРИЯ: {ticket_data['code_serie']} №{ticket_data['ticket_no']}\n"
        )
        print_to_printer(win32print.GetDefaultPrinter() if IS_WINDOWS else "default", text)
        _log_reprint(ticket_data['code_ticket'])
        beep_success()

    # ... (всё остальное без изменений)

    def show_reprint_log():
        log_win = Toplevel(root)
        log_win.title("Лог повторных печатей")

        filter_frame = Frame(log_win)
        filter_frame.pack(pady=5)
        Label(filter_frame, text="Фильтр по коду билета:").pack(side=LEFT)
        filter_var = StringVar()
        Entry(filter_frame, textvariable=filter_var, width=30).pack(side=LEFT, padx=5)

        # ... (всё остальное без изменений)

        tree = ttk.Treeview(log_win, columns=("ticket_code", "timestamp", "count"), show="headings")
        tree.heading("ticket_code", text="Код билета")
        tree.heading("timestamp", text="Дата/время")
        tree.heading("count", text="Всего повторов")
        tree.column("ticket_code", width=180)
        tree.column("timestamp", width=160)
        tree.column("count", width=120)
        tree.pack(fill=BOTH, expand=True)

        def load_reprints():
            tree.delete(*tree.get_children())
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            query = '''
                SELECT r1.ticket_code, r1.timestamp,
                       (SELECT COUNT(*) FROM tbl_reprints r2 WHERE r2.ticket_code = r1.ticket_code)
                FROM reprints r1
            '''
            params = []
            if filter_var.get():
                query += " WHERE r1.ticket_code LIKE ?"
                params.append(f"%{filter_var.get()}%")
            query += " ORDER BY r1.id DESC"
            c.execute(query, params)
            for row in c.fetchall():
                tree.insert("", "end", values=row)
            conn.close()

        def export_reprints_csv():
            path = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV files", "*.csv")])
            if not path:
                return
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            query = '''
                SELECT r1.ticket_code, r1.timestamp,
                       (SELECT COUNT(*) FROM reprints r2 WHERE r2.ticket_code = r1.ticket_code)
                FROM reprints r1
            '''
            params = []
            if filter_var.get():
                query += " WHERE r1.ticket_code LIKE ?"
                params.append(f"%{filter_var.get()}%")
            query += " ORDER BY r1.id DESC"
            c.execute(query, params)
            rows = c.fetchall()
            conn.close()

            with open(path, "w", newline='', encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(["ticket_code", "timestamp", "total_reprints"])
                writer.writerows(rows)
            messagebox.showinfo("Экспорт", f"Файл сохранён: {path}")



        Button(filter_frame, text="Экспорт CSV", command=export_reprints_csv).pack(side=LEFT, padx=5)



    # Модифицируем экспорт: весь или текущий
    def export_deals_csv():
        path = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV files", "*.csv")])
        if not path:
            return

        filter_id = None
        selected = deal_tree.selection()
        if selected:
            deal_hash = deal_tree.item(selected[0])['values'][0]
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            c.execute("SELECT deal_id FROM tbl_deals WHERE deal_hash = ?", (deal_hash,))
            r = c.fetchone()
            if r:
                filter_id = r[0]
            conn.close()

        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()

        # Получим имена всех колонок из обеих таблиц
        c.execute("PRAGMA table_info(tbl_deals)")
        deals_cols = [f"d.{row[1]}" for row in c.fetchall()]
        c.execute("PRAGMA table_info(tbl_tickets)")
        ticket_cols = [f"t.{row[1]}" for row in c.fetchall()]

        all_cols = deals_cols + ticket_cols
        all_cols_str = ", ".join(all_cols)

        if filter_id:
            c.execute(f'''
                SELECT {all_cols_str}
                FROM tbl_deals d
                JOIN tbl_tickets t ON d.id_deal = t.id_deal_ref
                WHERE d.id_deal = ?
            ''', (filter_id,))
        else:
            c.execute(f'''
                SELECT {all_cols_str}
                FROM tbl_deals d
                JOIN tbl_tickets t ON d.id_deal = t.id_deal_ref
            ''')
        rows = c.fetchall()

        # Заголовки без "d." и "t."
        headers = [col.split(".")[1] for col in all_cols]
        conn.close()

        with open(path, "w", newline='', encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(headers)
            writer.writerows(rows)
            
        messagebox.showinfo("Готово", f"CSV экспортирован: {path}")

    Button(right_frame, text="Экспорт deals CSV",
           command=export_deals_csv).pack(pady=5)

    def export_today_to_excel():
        today = datetime.datetime.now().strftime("%Y-%m-%d")
        path = f"{DEFAULT_LOG_DIR}/deals_{today}.csv"
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("PRAGMA table_info(tbl_deals)")
        deals_cols = [f"d.{row[1]}" for row in c.fetchall()]
        c.execute("PRAGMA table_info(tbl_tickets)")
        ticket_cols = [f"t.{row[1]}" for row in c.fetchall()]
        all_cols = deals_cols + ticket_cols
        all_cols_str = ", ".join(all_cols)
        c.execute(f'''
            SELECT {all_cols_str}
            FROM tbl_deals d
            JOIN tbl_tickets t ON d.id_deal = t.id_deal_ref
            WHERE d.ts_deal LIKE ?
        ''', (f"{today}%",))
        rows = c.fetchall()
        headers = [col.split(".")[1] for col in all_cols]
        conn.close()
        with open(path, "w", newline='', encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(headers)
            writer.writerows(rows)
        log_action("excel_export", comment=f"Экспорт {path} за {today}")    
        messagebox.showinfo("Готово", f"Экспорт за сегодня: {path}")

    def export_today_csv_xlsx():
        import pandas as pd
    
        today = datetime.datetime.now().strftime("%Y-%m-%d")
        path_csv = os.path.join(DEFAULT_LOG_DIR, f"deals_{today}.csv")
        path_xlsx = os.path.join(DEFAULT_LOG_DIR, f"deals_{today}.xlsx")
    
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
    
        query = '''
            SELECT d.*, t.*
            FROM tbl_deals d
            JOIN tbl_tickets t ON d.id_deal = t.id_deal_ref
            WHERE d.ts_deal >= ?
        '''
        c.execute(query, (f"{today} 00:00:00",))
        rows = c.fetchall()
    
        # Заголовки
        c.execute("PRAGMA table_info(tbl_deals)")
        deal_cols = [f"d.{row[1]}" for row in c.fetchall()]
        c.execute("PRAGMA table_info(tbl_tickets)")
        ticket_cols = [f"t.{row[1]}" for row in c.fetchall()]
        headers = [col.split(".")[1] for col in deal_cols + ticket_cols]
    
        conn.close()
    
        # CSV
        with open(path_csv, "w", newline='', encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(headers)
            writer.writerows(rows)
    
        # Excel
        df = pd.DataFrame(rows, columns=headers)
        df.to_excel(path_xlsx, index=False)
    
        log_action("excel_export", comment=f"Экспорт {path_csv} + {path_xlsx} за {today}")    
        messagebox.showinfo("Экспорт", f"Сохранено:\n{path_csv}\n{path_xlsx}")
    

    Button(right_frame, text="Экспорт за сегодня", command=export_today_csv_xlsx).pack(pady=5)

    # ---------- переменные интерфейса ----------
    serie_var = StringVar(value="KZ25")
    attraction_var = StringVar(value="Dino Festival KZ")
    currency_var = StringVar(value="KZT")
    accepted_var = StringVar(value="0")
    change_var = StringVar(value="0.00")
    total_sum_var = IntVar(value=0)
    qr_var = BooleanVar(value=True)
    pdf_var = BooleanVar(value=False)
    ticket_vars = {k: IntVar(value=0) for k in TICKET_TYPES}

    def on_focus_intvar(entry_widget, var):
        def handler(event):
            try:
                if entry_widget.get().strip() == "":
                    var.set(0)
                entry_widget.select_range(0, END)
                entry_widget.icursor(END)
            except:
                var.set(0)
        return handler
        
    # ---------- разметка слева ----------
    row = 0
    Label(left_frame, text="Серия билета:").grid(row=row, column=0, sticky="e")
    Entry(left_frame, textvariable=serie_var).grid(row=row, column=1)
 #   row += 1
    Label(left_frame, text="Аттракцион:").grid(row=row, column=2, sticky="e")
    Entry(left_frame, textvariable=attraction_var).grid(row=row, column=3)
    row += 1


    for name, var in ticket_vars.items():
        Label(left_frame, text=f"{name} ({TICKET_TYPES[name]}):").grid(
            row=row, column=0, sticky="e")

        Button(left_frame, text="-",
               command=lambda v=var: v.set(max(0, v.get() - 1)),
               width=4, height=2).grid(row=row, column=1)

        entry = Entry(left_frame, textvariable=var, width=6, justify='center')
        entry.grid(row=row, column=2)
        entry.bind("<FocusIn>", on_focus_intvar(entry, var))

        Button(left_frame, text="+",
               command=lambda v=var: v.set(v.get() + 1),
               width=4, height=2).grid(row=row, column=3)

        # Очистка и валидация
        def on_focus_out(event, v=var):
            try:
                val = int(event.widget.get())
                if val < 0:
                    val = 0
                v.set(val)
            except:
                v.set(0)

        entry.bind("<FocusOut>", on_focus_out)
        row += 1
    

    Label(left_frame, text="Сумма к оплате:").grid(
        row=row, column=0, sticky="e")
    Label(left_frame, textvariable=total_sum_var).grid(row=row, column=1)
    row += 1
    # === Добавим выбор типа оплаты и кнопку терминала ===
    Label(left_frame, text="Тип оплаты:").grid(row=row, column=0, sticky="e")
    payment_options = ["наличные", "банк. карта", "перечисление банком", "оплата MIA"]
    payment_menu = OptionMenu(left_frame, payment_type_var, *payment_options)
    payment_menu.grid(row=row, column=1, sticky="w")

    Button(left_frame, text="Оплатить через терминал", command=lambda: handle_terminal_payment()).grid(row=row, column=2, columnspan=2, sticky="w")
    row += 1

 
    Button(left_frame, text="Без сдачи", command=lambda: accepted_var.set(str(total_sum_var.get())), bg="lightgreen").grid(row=row, column=0, sticky="w")
    Label(left_frame, text="Принято:").grid(row=row, column=1, sticky="e")
    entry_accepted = Entry(left_frame, textvariable=accepted_var)
    entry_accepted.grid(row=row, column=2)
    row += 1
    
    Label(left_frame, text="Сдача:").grid(row=row, column=0, sticky="e")
    Label(left_frame, textvariable=change_var).grid(row=row, column=1)
    row += 1

    #row += 1

    Checkbutton(left_frame, text="Добавить QR",
                variable=qr_var).grid(row=row, column=0)
    Checkbutton(left_frame, text="Сохранять в PDF",
                variable=pdf_var).grid(row=row, column=1)
    row += 1

    # ---------- пересчёт итогов ----------
    def update_total(*_):
        total = sum(ticket_vars[k].get() * TICKET_TYPES[k]
                    for k in ticket_vars)
        total_sum_var.set(total)
        try:
            acc = float(accepted_var.get())
            change = acc - total
            change_var.set(f"{change:.2f}")
        except ValueError:
            change_var.set("0.00")

    for var in ticket_vars.values():
        var.trace_add("write", update_total)
    accepted_var.trace_add("write", update_total)

    # ---------- логика заказа ----------
    def reset_order(event=None):
        for var in ticket_vars.values():
            var.set(0)
        accepted_var.set("0")
        change_var.set("0.00")
        entry_accepted.focus_set()
        payment_type_var.set("наличные")  # ← вот эта строка нужна

    def show_x_report():
        text = generate_report_text()
        win = Toplevel(root)
        win.title("X-ОТЧЁТ")
    
        textbox = Text(win, wrap="word", height=15, width=60)
        textbox.insert("1.0", text)
        textbox.config(state="disabled")
        textbox.pack(padx=10, pady=10)
    
        def copy_text():
            root.clipboard_clear()
            root.clipboard_append(text)
            messagebox.showinfo("Скопировано", "Текст X-отчёта скопирован в буфер.")
    
        def print_text():
            print_to_printer(win32print.GetDefaultPrinter() if IS_WINDOWS else "default", text)
    
        def save_pdf():
            from fpdf import FPDF
            filename = f"x_report_{datetime.datetime.now().strftime('%Y%m%d_%H%M')}.pdf"
            pdf = FPDF()
            pdf.add_page()
            #pdf.set_font("Arial", size=12)
            #pdf.set_font("Helvetica", size=14)

            font_path = "./DejaVuSans.ttf"
            try:
                pdf.add_font("DejaVu", "", font_path, uni=True)
                pdf.set_font("DejaVu", "", 12)
            except:
                pdf.set_font("Arial", size=12)

            for line in text.split("\n"):
                pdf.cell(200, 10, txt=line, ln=True)
            pdfFilePath=os.path.join(DEFAULT_LOG_DIR, filename)
            pdf.output(pdfFilePath)
            messagebox.showinfo("PDF сохранён", f"Файл: {pdfFilePath}")
            webbrowser.open_new(pdfFilePath)
    
        btns = Frame(win)
        btns.pack(pady=5)
        Button(btns, text="Копировать", command=copy_text).pack(side=LEFT, padx=5)
        Button(btns, text="Печать", command=print_text).pack(side=LEFT, padx=5)
        Button(btns, text="PDF", command=save_pdf).pack(side=LEFT, padx=5)
        
    def make_z_report():
        show_x_report()
        now = datetime.datetime.now()
        since = get_last_z_time() or datetime.datetime.min
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
    
        c.execute("SELECT COUNT(*), SUM(amt_price) FROM tbl_tickets WHERE ts_ticket > ?", (since.strftime("%Y-%m-%d %H:%M:%S"),))
        count, total = c.fetchone()
        #if total==None:
        #  return;   
        # Логируем Z
        c.execute("INSERT INTO tbl_z_reports (timestamp, total, tickets) VALUES (?, ?, ?)",
                  (now.strftime("%Y-%m-%d %H:%M:%S"), total or 0, count))
    
        # Обновляем Z-время
        c.execute("INSERT OR REPLACE INTO tbl_z_state (id, last_z_time) VALUES (1, ?)", (now.strftime("%Y-%m-%d %H:%M:%S"),))
        conn.commit()
        conn.close()
        
        messagebox.showinfo("Z-ОТЧЁТ", f"Z-отчёт снят. {count} билетов, сумма: {total or 0:.2f}")
        try:
           check_z_timer_and_color(z_button)  # сбросить цвет
        except:
            print("Z-отчёт снят")
        update_summary()
        

    def ask_cash_start():
#        last_z = get_last_z_time()
#        now = datetime.datetime.now()
#        if (now - last_z > datetime.timedelta(hours=24)) or (now.date() != last_z.date()):
        now    = datetime.datetime.now()
        last_z = get_last_z_time()          # может быть None

        # Если Z-отчётов ещё не было — считаем, что все ОК и пропускаем проверку
        if last_z and ( (now - last_z > datetime.timedelta(hours=24))
                        or (now.date() != last_z.date()) ):
            if messagebox.askyesno("Внимание", "С момента последнего Z-отчета прошло более 24ч или наступил следующий день. Сформировать Z-отчет сейчас?"):
                make_z_report()
            else:
                show_x_report()
                messagebox.showerror("Выход", "Z-отчет не был снят. Программа завершит работу.")
                root.destroy()
                return
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        today_str = now.strftime('%Y-%m-%d')
        c.execute("SELECT amount FROM tbl_cash_start WHERE DATE(ts_start) = ?", (today_str,))  
        print(today_str)
        row = c.fetchone()
        if row is None:
            start_amt = simpledialog.askfloat("Начало дня", "Сколько денег в кассе на начало дня?")
            if start_amt is not None:
                ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                c.execute("INSERT INTO tbl_cash_start ( ts_start, amount, user, name_host, mac) VALUES ( ?, ?, ?, ?, ?)",
                          (ts, start_amt, USERNAME, HOSTNAME, MAC))
                conn.commit()
                update_summary()
        conn.close()
    
    ask_cash_start()
    
    def do_print(event=None):
        # 0️⃣  НИ ОДНОГО БИЛЕТА ─ сразу стоп
        total_qty = sum(var.get() for var in ticket_vars.values())
        if total_qty == 0:
            beep_error()
            messagebox.showerror("Ошибка", "Выберите хотя бы один билет")
            return

        last_z = get_last_z_time()
        now = datetime.datetime.now()
        time_left = (datetime.datetime.combine(now.date(), datetime.time(23, 59, 59)) - now).total_seconds()
        if last_z:
         if (now - last_z > datetime.timedelta(hours=24)) or (now.date() != last_z.date()):
            beep_error()
            messagebox.showerror("Ошибка", "Продажа заблокирована — Z-отчет не снят более 24ч или наступил новый день.")
            return
        elif time_left <= 10 * 60:
            messagebox.showwarning("Внимание", "‼ Менее 10 минут до конца дня — требуется снять Z-отчет после продажи.")
        elif time_left <= 20 * 60:
            messagebox.showinfo("Предупреждение", "⚠ Менее 20 минут до конца дня.")
        
            
    
        #if accepted_var.get().strip() == "" or float(accepted_var.get()) <= 0:
        #    beep_error()
        ##    messagebox.showerror("Ошибка", "Введите сумму оплаты (Принято)")
        #    return

        # ▸ если сумма к оплате 0 (пригласительные) – считаем, что оплата не нужна
        if total_sum_var.get() == 0:
            accepted_var.set("0")
            change_var.set("0.00")
        else:
            try:
                acc_test = float(accepted_var.get())
                if acc_test <= 0:
                    raise ValueError
            except ValueError:
                beep_error()
                messagebox.showerror("Ошибка", "Введите сумму оплаты (Принято)")
                return

        total = total_sum_var.get()
        try:
            acc = float(accepted_var.get())
            chg = float(change_var.get())
        except:
            beep_error()
            messagebox.showerror("Ошибка", "Неверная сумма")
            return
    
        deal_id, deal_hash = save_deal(total, acc, chg)
        tickets = []
        for cat, var in ticket_vars.items():
            cnt = var.get()
            for i in range(cnt):
                code = generate_ticket_code(serie_var.get())
                save_ticket(code, serie_var.get(), i, cat, attraction_var.get(),
                            TICKET_TYPES[cat], currency_var.get(), deal_id)
                tickets.append((code, cat, TICKET_TYPES[cat], currency_var.get()))
    	        
    
        if pdf_var.get():
            filename = f"Dino_KZ_{datetime.datetime.now().strftime('%Y%m%d_%H%M')}.pdf"
            generate_order_pdf(tickets, attraction_var.get(), serie_var.get(), acc, chg, filename)
        else:
            #text = "\n".join([f"{t[0]} - {t[1]} - {t[2]} {t[3]}" for t in tickets])
            #print_to_printer(win32print.GetDefaultPrinter() if IS_WINDOWS else "default", text)
            # Печатаем билеты через print_multiple_tickets по каждой категории
            printer_name = win32print.GetDefaultPrinter() if IS_WINDOWS else "default"
            for product_name in TICKET_TYPES:
                count = ticket_vars[product_name].get()
                if count > 0:
                    print_multiple_tickets(
                        serie=serie_var.get(),
                        count=count,
                        price=TICKET_TYPES[product_name],
                        currency=currency_var.get(),
                        product_name=product_name,
                        attraction=attraction_var.get(),
                        printer_name=printer_name
                    )
                    
        messagebox.showinfo("Успех", f"Сделка сохранена: {deal_hash[:10]}")
        beep_success()
        load_deals()
        #update_total()
        update_summary()
        reset_order()
        if time_left <= 10 * 60: #автоматическое предложение снять Z после завершения сделки Внимание", "‼ Менее 10 минут до конца дня — требуется снять Z-отчет после продажи.
            z_button.invoke()  # автоматически нажимает кнопку Z-отчета
        
    Button(left_frame, text="Печать заказа", height=2, width=20,
           command=do_print).grid(row=row, column=0, columnspan=2, pady=10)
    Button(left_frame, text="Отмена", height=2, width=20,
           command=reset_order).grid(row=row, column=2, columnspan=2, pady=10)
    row += 1
    
    Button(left_frame, text="Изъятие денег", height=2, width=15, command=open_withdrawal_form).grid(row=row, column=0, columnspan=1, pady=5)
    #row += 1
 
    Button(left_frame, text="Журнал синхронизации",
           height=2, width=15,
           command=show_sync_log).grid(row=row, column=0, columnspan=3, pady=5)
    #row += 1
    
    Button(left_frame, text="Лог повторных печатей",
           height=2, width=15,
           command=show_reprint_log).grid(row=row, column=2, columnspan=1, padx=1, pady=5)
    row += 1
    
    Button(left_frame, text="Повторная печать билета",
           height=2, width=42,
           command=lambda: on_ticket_double_click(None)).grid(row=row, column=0, columnspan=4, pady=7)
    
    row += 1
    Button(left_frame, text="Синхронизировать сейчас", height=2, width=15,
           command=lambda: manual_sync_trigger.set()).grid(row=row, column=0, columnspan=1, pady=(10, 0))
    
    row += 1
    # Убедимся, что row свободен
    Button(left_frame, text="Сформировать X-отчёт", width=15, height=2, command=show_x_report)\
        .grid(row=row, column=0, columnspan=1, padx=1, pady=5)

    z_button = Button(left_frame, text="Сформировать Z-отчёт", width=15, height=2, command=make_z_report)
    z_button.grid(row=row, column=1, columnspan=1, padx=1, pady=5)
    check_z_timer_and_color(z_button)

    Button(left_frame, text="Пересчитать обороты", width=15, height=2, command=update_summary)\
        .grid(row=row, column=2, columnspan=1, padx=1, pady=5)

    #row += 1  
    root.bind("<Return>", do_print)
    root.bind("<Escape>", reset_order)
    
    # ---------- стартовое состояние ----------
    load_deals()
    #update_total()  # пересчёт на старте
    entry_accepted.focus_set()
    return root
      
      
# ──────────────────────────────────────────────────────────────────
#                     ПУБЛИЧНЫЕ ФУНКЦИИ
# ──────────────────────────────────────────────────────────────────

# Фоновая синхронизация с обновлением статуса
# В show_gui() и start_sync_thread() используется sync_status_var
# Добавим кнопку ручной синхронизации в show_gui()

# Весь обновлённый show_gui и использование sync_status_var ↓↓↓

manual_sync_trigger = threading.Event()

# Кнопка и окно просмотра sync_log

def show_sync_log(_=None):
    win = Toplevel()
    win.title("Журнал синхронизаций")
    win.geometry("700x400")

    Label(win, text="Лог синхронизации с Oracle", font=("Arial", 14, "bold")).pack(pady=5)

    tree = ttk.Treeview(win, columns=("table", "record", "status", "message", "time"), show="headings")
    for col in tree["columns"]:
        tree.heading(col, text=col.upper())
        tree.column(col, width=130 if col != "message" else 280)
    tree.pack(fill=BOTH, expand=True, padx=10, pady=5)

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT table_name, record_id, status, message, synced_at FROM sync_log ORDER BY id DESC LIMIT 200")
    for row in c.fetchall():
        tree.insert("", "end", values=row)
    conn.close()

# show_gui с инициализацией переменной
# ── 2. ПРОВЕРКИ СОСТОЯНИЯ ─────────────────────────────────────────────────────
IS_WINDOWS = platform.system() == "Windows"

def check_printer():
    try:
        if IS_WINDOWS:
            import win32print
            name = win32print.GetDefaultPrinter()
            return f"🖨️ Принтер: {name}", True
        else:
            res = subprocess.run(["lpstat", "-p"], capture_output=True, text=True)
            if res.returncode == 0 and res.stdout.strip():
                return f"🖨️ Принтер: OK", True
        return "🖨️ Принтер: ❌ не найден", False
    except Exception as e:
        log_error("Проверка принтера", e)
        return "🖨️ Принтер: ❌ ошибка", False


def check_sqlite():
    try:
        sqlite3.connect(DB_PATH).close()
        return "🗄️ SQLite: OK", True
    except Exception as e:
        log_error("SQLite недоступен", e)
        return "🗄️ SQLite: ❌", False


def check_oracle():
    try:
        oracledb.connect(ORACLE_DSN).close()
        return "🔗 Oracle: OK", True
    except Exception as e:
        # Логируем, но не считаем критичным — синхронизация всё-равно будет пытаться
        log_error("Oracle недоступен при старте", e)
        return "🔗 Oracle: ❌", False
  
def update_summary():
    #try:
        lbl = summary_refs.get("lbl")
        var = summary_refs.get("var")
        if not lbl or not var:
            return

        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()

        # дата последнего Z
        c.execute("SELECT last_z_time FROM tbl_z_state WHERE id = 1")
        row = c.fetchone()
        if row and row[0]:
            since = datetime.datetime.strptime(row[0].split('.')[0].replace('T', ' '), "%Y-%m-%d %H:%M:%S")
        else:
            since = datetime.datetime.min

        # стартовая сумма
        today_str = datetime.datetime.now().strftime('%Y-%m-%d')
        c.execute("SELECT amount FROM tbl_cash_start WHERE DATE(ts_start) = ?", (today_str,))
        start = c.fetchone()
        N = start[0] if start else 0

        # оборот после Z
        c.execute("SELECT SUM(amt_price) FROM tbl_tickets WHERE ts_ticket > ?", (since.strftime("%Y-%m-%d %H:%M:%S"),))
        P = c.fetchone()[0] or 0

        # изъятия после Z
        c.execute("SELECT SUM(amount) FROM tbl_cash_withdrawals WHERE ts_withdraw > ?", (since.strftime("%Y-%m-%d %H:%M:%S"),))
        R = c.fetchone()[0] or 0

        K = N + P - R
        txt = f"[N:{N:.0f}] [P:{P:.0f}] [R:{R:.0f}] [K:{K:.0f}]"
        var.set(txt)
        lbl.config(fg="red" if K < 0 else "black")
        conn.close()
    #except:
     #   if "var" in summary_refs:
      #      summary_refs["var"].set("[N:?] [P:?] [R:?] [K:?]")
                        
# ── 3. STATUSBAR ──────────────────────────────────────────────────────────────
def build_status_bar(root):
    """Создаёт строку статуса и возвращает (sync_var, oracle_var)"""
    bar = Frame(root, bd=1, relief=SUNKEN)
    bar.pack(side=BOTTOM, fill=X)

    # Статические проверки принтера/SQLite прямо при запуске
    printer_text, _ = check_printer()
    sqlite_text, _ = check_sqlite()

    Label(bar, text=printer_text, anchor="w").pack(side=LEFT, padx=8)
    Label(bar, text=sqlite_text, anchor="w").pack(side=LEFT, padx=8)

    # Динамические: Oracle-подключение и цикл синхронизации
    oracle_var = StringVar(value="🔗 Oracle: ⏳")
    sync_var   = StringVar(value="🔄 Синхронизация: ⏳ ожидание…")

    Label(bar, textvariable=oracle_var, anchor="w").pack(side=LEFT, padx=8)
    Label(bar, textvariable=sync_var,   anchor="w").pack(side=LEFT, padx=8)

    # Показ [N:..][P:..][R:..][K:..]
    summary_var = StringVar()
    lbl_summary = Label(bar, textvariable=summary_var, anchor="w")
    lbl_summary.pack(side=RIGHT, padx=8)

    # сохраняем в глобальный словарь
    summary_refs["lbl"] = lbl_summary
    summary_refs["var"] = summary_var

    update_summary()
    #root.after(30000, update_summary)  # каждые 30 сек

    return sync_var, oracle_var


def start_sync_thread1(sync_var, oracle_var, root):
    if ORACLE_DISABLED:
        #sync_var.set("🔄 Синхронизация: ❌ отключена")
        #oracle_var.set("🔗 Oracle: ❌")
        root.after(0, lambda: oracle_var.set("🔗 Oracle: ❌"))
        root.after(0, lambda: sync_var.set("🔄 Синхронизация: ❌ отключена"))        
        return
    print("🔄 Синхронизация:  включена ")

    def sync_loop():
        while True:
            manual_sync_trigger.wait(timeout=30)
            manual_sync_trigger.clear()
            #sync_var.set("🔄 Синхронизация: 🟡 выполняется…")
            # Внутри sync_loop, вместо sync_var.set(...):
            #if root.winfo_exists():
            try:
                root.after(0, lambda: sync_var.set("🔄 Синхронизация: 🟡 выполняется..."))
                #print(sync_var.get())  # вместо print(sync_var)
            except RuntimeError:
                pass               
            try:
                try:
                    ora_conn = oracledb.connect(ORACLE_DSN)
                    ora_cur = ora_conn.cursor()
                    root.after(0, lambda: oracle_var.set("🔗 Oracle: ✅"))
                except Exception as ora_e:
                    #oracle_var.set("🔗 Oracle: ❌")
                    root.after(0, lambda: oracle_var.set("🔄 Синхронизация: 🔴 ошибка Oracle"))
                    log_error("Oracle connect", ora_e)
                    continue

                sql_conn = sqlite3.connect(DB_PATH)
                sql_cur = sql_conn.cursor()

                sql_cur.execute("""
                    SELECT id_deal, hash_deal, ts_deal, amt_total, amt_accepted, amt_change, name_host
                    FROM tbl_deals
                    WHERE ts_sync_due IS NULL
                """)
                deals = sql_cur.fetchall()

                for d in deals:
                    id_deal = d[0]
                    try:
                        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        #ora_cur.execute("""
                        #    INSERT INTO tbl_deals
                        #    (id_deal, hash_deal, ts_deal, amt_total, amt_accepted, amt_change, name_host, ts_sync_due, user_name, mac)
                        #    VALUES (:1, :2, TO_DATE(:3, 'YYYY-MM-DD HH24:MI:SS'), :4, :5, :6, :7, TO_DATE(:8, 'YYYY-MM-DD HH24:MI:SS'), :9, :10)
                        #""", (*d, now, USERNAME, MAC))

                        try:
                            ora_cur.execute("""
                                INSERT INTO tbl_deals
                                (id_deal, hash_deal, ts_deal, amt_total, amt_accepted, amt_change,
                                 name_host, ts_sync_due, user_name, mac)
                                VALUES (:1, :2, TO_DATE(:3, 'YYYY-MM-DD HH24:MI:SS'), :4, :5, :6,
                                        :7, TO_DATE(:8, 'YYYY-MM-DD HH24:MI:SS'), :9, :10)
                            """, (*d, now, USERNAME, MAC))
                            ora_conn.commit()
                            #sql_cur.execute("INSERT INTO tbl_sync_log (name_table, id_record, status) VALUES ('tbl_deals', ?, 'ok')", (d[0],))
                        except Exception as e:
                            if "ORA-00001" in str(e):  # дубликат — считаем успешным
                                print(f"[~] Сделка уже в Oracle (id_deal={id_deal})")
                            else:
                                msg = f"❌ Ошибка вставки tbl_deals (id_deal={id_deal}): {e}"
                                print(f"[!] {msg}")
                                log_error(msg, e)
                                sql_cur.execute("INSERT INTO tbl_sync_log (name_table, id_record, status, message) VALUES ('tbl_deals', ?, 'fail', ?)", (id_deal, str(e)))
                                continue  # пропускаем билеты
 
                        sql_cur.execute("SELECT * FROM tbl_tickets WHERE id_deal_ref = ?", (id_deal,))
                        tickets_raw = sql_cur.fetchall()
                        tickets = [t + (d[6],) for t in tickets_raw]  # d[6] = name_host
                        for t in tickets:
                            try:
                                ora_cur.execute("""
                                    INSERT INTO tbl_tickets
                                    (id_ticket, code_ticket, code_serie, ticket_no, ts_ticket, name_product,
                                     name_attraction, amt_price, name_currency, id_deal_ref, name_host)
                                    VALUES (:1, :2, :3, :4, TO_DATE(:5, 'YYYY-MM-DD HH24:MI:SS'), :6, :7, :8, :9, :10, :11)
                                """, t)
                                ora_conn.commit()
                                #sql_cur.execute("INSERT INTO tbl_sync_log (name_table, id_record, status) VALUES ('tbl_tickets', ?, 'ok')", (t[0],))
                            except Exception as e:
                                msg = f"Ошибка при вставке в tbl_tickets (id_ticket={t[0]}): {e}"
                                print(f"[!] {msg}")
                                log_error(msg, e)
                                sql_cur.execute("INSERT INTO tbl_sync_log (name_table, id_record, status, message) VALUES ('tbl_tickets', ?, 'fail', ?)", (t[0], str(e)))
                                                        
                        sql_cur.execute("UPDATE tbl_deals SET ts_sync_due = ? WHERE id_deal = ?", (now, id_deal))
                        #sql_cur.execute("INSERT INTO tbl_sync_log (name_table, id_record, status) VALUES ('tbl_deals', ?, 'ok')", (id_deal,))
                    except Exception as de:
                        sql_cur.execute("INSERT INTO tbl_sync_log (name_table, id_record, status, message) VALUES ('tbl_deals', ?, 'fail', ?)", (id_deal, str(de)))
                        log_error("sync deal + tickets", de)

                sql_conn.commit()
                root.after(0, lambda: sync_var.set("🔄 Синхронизация: ✅ завершена"))
            except Exception as e:
                #sync_var.set("🔄 Синхронизация: 🔴 ошибка цикла")
                log_error("main sync loop", e)
            finally:
                try:
                    ora_cur.close(); ora_conn.close()
                except: pass
                try:
                    sql_cur.close(); sql_conn.close()
                except: pass

    threading.Thread(target=sync_loop, daemon=True).start()

def start_sync_thread(sync_var, oracle_var, root):
    if ORACLE_DISABLED:
        root.after(0, lambda: oracle_var.set("🔗 Oracle: ❌"))
        root.after(0, lambda: sync_var.set("🔄 Синхронизация: ❌ отключена"))        
        return
    print("🔄 Синхронизация:  включена ")

    def sync_loop():
        while True:
            manual_sync_trigger.wait(timeout=30)
            manual_sync_trigger.clear()
            try:
                root.after(0, lambda: sync_var.set("🔄 Синхронизация: 🟡 выполняется..."))
            except RuntimeError:
                pass
            try:
                try:
                    ora_conn = oracledb.connect(ORACLE_DSN)
                    ora_cur = ora_conn.cursor()
                    root.after(0, lambda: oracle_var.set("🔗 Oracle: ✅"))
                except Exception as ora_e:
                    root.after(0, lambda: oracle_var.set("🔄 Синхронизация: 🔴 ошибка Oracle"))
                    log_error("Oracle connect", ora_e)
                    continue

                sql_conn = sqlite3.connect(DB_PATH)
                sql_cur = sql_conn.cursor()

                sql_cur.execute("""
                    SELECT id_deal, hash_deal, ts_deal, amt_total, amt_accepted, amt_change, name_host
                    FROM tbl_deals
                    WHERE ts_sync_due IS NULL
                """)
                deals = sql_cur.fetchall()

                for d in deals:
                    id_deal = d[0]
                    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    deal_uploaded = False

                    try:
                        ora_cur.execute("""
                            INSERT INTO tbl_deals
                            (id_deal, hash_deal, ts_deal, amt_total, amt_accepted, amt_change,
                             name_host, ts_sync_due, user_name, mac)
                            VALUES (:1, :2, TO_DATE(:3, 'YYYY-MM-DD HH24:MI:SS'), :4, :5, :6,
                                    :7, TO_DATE(:8, 'YYYY-MM-DD HH24:MI:SS'), :9, :10)
                        """, (*d, now, USERNAME, MAC))
                        ora_conn.commit()
                        deal_uploaded = True
                    except Exception as e:
                        if "ORA-00001" in str(e):
                            print(f"[~] Сделка уже в Oracle (id_deal={id_deal})")
                            deal_uploaded = True
                        else:
                            msg = f"❌ Ошибка вставки tbl_deals (id_deal={id_deal}): {e}"
                            print(f"[!] {msg}")
                            log_error(msg, e)
                            sql_cur.execute("INSERT INTO tbl_sync_log (name_table, id_record, status, message) VALUES ('tbl_deals', ?, 'fail', ?)", (id_deal, str(e)))

                    if deal_uploaded:
                        sql_cur.execute("SELECT * FROM tbl_tickets WHERE id_deal_ref = ?", (id_deal,))
                        tickets_raw = sql_cur.fetchall()
                        tickets = [t + (d[6],) for t in tickets_raw]

                        for t in tickets:
                            try:
                                ora_cur.execute("""
                                    INSERT INTO tbl_tickets
                                    (id_ticket, code_ticket, code_serie, ticket_no, ts_ticket, name_product,
                                     name_attraction, amt_price, name_currency, id_deal_ref, name_host)
                                    VALUES (:1, :2, :3, :4, TO_DATE(:5, 'YYYY-MM-DD HH24:MI:SS'), :6, :7, :8, :9, :10, :11)
                                """, t)
                                ora_conn.commit()
                                sql_cur.execute("INSERT INTO tbl_sync_log (name_table, id_record, status) VALUES ('tbl_tickets', ?, 'ok')", (t[0],))
                            except Exception as e:
                                if "ORA-00001" in str(e):
                                    print(f"[~] Билет уже в Oracle (id_ticket={t[0]})")
                                    sql_cur.execute("INSERT INTO tbl_sync_log (name_table, id_record, status) VALUES ('tbl_tickets', ?, 'ok')", (t[0],))
                                else:
                                    msg = f"❌ Ошибка вставки tbl_tickets (id_ticket={t[0]}): {e}"
                                    print(f"[!] {msg}")
                                    log_error(msg, e)
                                    sql_cur.execute("INSERT INTO tbl_sync_log (name_table, id_record, status, message) VALUES ('tbl_tickets', ?, 'fail', ?)", (t[0], str(e)))

                        sql_cur.execute("UPDATE tbl_deals SET ts_sync_due = ? WHERE id_deal = ?", (now, id_deal))

                sql_conn.commit()
                root.after(0, lambda: sync_var.set("🔄 Синхронизация: ✅ завершена"))
            except Exception as e:
                log_error("main sync loop", e)
            finally:
                try:
                    ora_cur.close(); ora_conn.close()
                except: pass
                try:
                    sql_cur.close(); sql_conn.close()
                except: pass

    threading.Thread(target=sync_loop, daemon=True).start()

            
def generate_report_text_old():
    since = get_last_z_time() or datetime.datetime.min
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # Группировка по категориям
    c.execute('''
        SELECT name_product, COUNT(*), SUM(amt_price)
        FROM tbl_tickets
        WHERE ts_ticket > ?
        GROUP BY name_product
    ''', (since.strftime("%Y-%m-%d %H:%M:%S"),))
    rows = c.fetchall()

    # Общие итоги
    c.execute('''
        SELECT COUNT(*), SUM(amt_price)
        FROM tbl_tickets
        WHERE ts_ticket > ?
    ''', (since.strftime("%Y-%m-%d %H:%M:%S"),))
    count_total, sum_total = c.fetchone()
    conn.close()

    report = []
    report.append(f"X/Z-ОТЧЁТ {now.strftime('%Y-%m-%d %H:%M:%S')}")
    report.append(f"С момента последнего Z: {since.strftime('%Y-%m-%d %H:%M:%S') if since else 'никогда'}")
    report.append("\n--- ПО КАТЕГОРИЯМ ---")

    for category, qty, total in rows:
        report.append(f"{category:<12} | {qty:>3} бил. | {total:>8.2f}")

    report.append("\n--- ИТОГО ---")
    report.append(f"ВСЕГО БИЛЕТОВ: {count_total}")
    #report.append(f"ОБОРОТ:        {sum_total:.2f}")
    if sum_total is not None:
        report.append(f"ОБОРОТ:        {sum_total:.2f}")
    else:
        report.append("ОБОРОТ:        0.00")
    return "\n".join(report)
    
# ── dino_ticket_gui.py  ─────────────────────────────────────────
def generate_report_text() -> str:
    """
    Формирует X/Z-отчёт, используя переводы из ticket_texts
    и динамические названия категорий.
    """
    now   = datetime.datetime.now()                     # ← 1. вот он!
    since = get_last_z_time() or datetime.datetime.min
    texts = ticket_texts                                # labels_ru / en / kz / …

    conn = sqlite3.connect(DB_PATH)
    c    = conn.cursor()

    # ▸ обороты по категориям
    c.execute("""
        SELECT name_product, COUNT(*), SUM(amt_price)
        FROM tbl_tickets
        WHERE ts_ticket > ?
        GROUP BY name_product
    """, (since.strftime("%Y-%m-%d %H:%M:%S"),))
    rows = c.fetchall()

    # ▸ общий итог
    c.execute("""
        SELECT COUNT(*), SUM(amt_price)
        FROM tbl_tickets
        WHERE ts_ticket > ?
    """, (since.strftime("%Y-%m-%d %H:%M:%S"),))
    count_total, sum_total = c.fetchone()
    conn.close()

    report = []
    report.append(f"{texts['x_header']} {now.strftime('%Y-%m-%d %H:%M:%S')}")
    since_str = since.strftime('%Y-%m-%d %H:%M:%S') if since != datetime.datetime.min else "—"
    report.append(f"{texts['x_since']} {since_str}")

    report.append(f"\n{texts['x_by_category']}")
    for cat, qty, total in rows:
        report.append(f"{cat:<16} | {qty:>3} | {total:>10.2f}")

    report.append(f"\n{texts['x_total']}")
    report.append(f"{texts['x_count']}: {count_total or 0}")
    report.append(f"{texts['x_sum']}:  {(sum_total or 0):.2f}")

    return "\n".join(report)
# ────────────────────────────────────────────────────────────────
  
    
        
# ── 5.  show_gui() ─────────────────────────────────────────────────
def show_gui():
    migrate_schema()
    if not ORACLE_DISABLED:
        ensure_oracle_tables()         # пробуем только один раз
    root = Tk()
    if platform.system() == "Windows":
        root.state('zoomed')  # Windows only
    else:
        # macOS, Linux
        screen_width = root.winfo_screenwidth()
        screen_height = root.winfo_screenheight()
        root.geometry(f"{screen_width}x{screen_height}+0+0")

    root.title("Dino Festival KZ – Билеты")
    root.geometry("1200x700")
    #ask_cash_start()
	
    # 5.1  Статус-бар
    sync_var, oracle_var = build_status_bar(root)

 

    # 5.4  Ваша основная верстка интерфейса
    _build_gui(root)

    # 5.2  Поток синхронизации
    start_sync_thread(sync_var, oracle_var, root)

    root.mainloop()
    
def show_gui_old1():
    migrate_schema()
    root = Tk()
    sync_status_var = StringVar(value="Синхронизация: ⏳ ожидание...")  # теперь после root = Tk()
    start_sync_thread(sync_status_var)
    _build_gui(root)
    

    # Нижняя панель
    bottom = Frame(root)
    bottom.pack(side=BOTTOM, fill=X)
    Label(bottom, textvariable=sync_status_var, anchor="w").pack(side=LEFT, padx=10)
    Button(bottom, text="Синхронизировать сейчас", command=lambda: manual_sync_trigger.set()).pack(side=RIGHT, padx=10, pady=3)
    Button(bottom, text="Журнал синхронизации", command=lambda: show_sync_log(sync_status_var)).pack(side=RIGHT, padx=10)

    root.mainloop()



# ──────────────────────────────────────────────────────────────────
def show_gui_embedded(hwnd_parent: int):
    """
    Специальный режим: создаём окно, прицепляем к чужому HWND
    (вызывается из embed_tk_frame.py).
    """
    if not IS_WINDOWS:
        raise RuntimeError("Embedding доступен только в Windows")

    import win32gui
    import win32con
    import ctypes

    root = Tk()
    root.overrideredirect(True)          # убираем рамку
    root.geometry("1200x700")            # желаемый размер

    hwnd_tk = root.winfo_id()
    win32gui.SetParent(hwnd_tk, hwnd_parent)

    GWL_STYLE = -16
    style = win32gui.GetWindowLong(hwnd_tk, GWL_STYLE)
    style = (style & ~win32con.WS_POPUP) | win32con.WS_CHILD | win32con.WS_VISIBLE
    win32gui.SetWindowLong(hwnd_tk, GWL_STYLE, style)
    win32gui.MoveWindow(hwnd_tk, 0, 0, 1200, 700, True)

    _build_gui(root)        # строим всё то же самое
    return root             # цикл mainloop() запустит «первый» скрипт

# ──────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    # по-старому: python dino_ticket_gui.py
    show_gui()
