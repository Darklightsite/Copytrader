# FÁJL: modules/logger_setup.py (Teljes, javított kód)

import logging
import multiprocessing
import os
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from modules.config_loader import get_all_users, is_admin
from modules.telegram_sender import send_telegram_message

class CustomColorFormatter(logging.Formatter):
    """
    Egyedi log formatter, amely a teljes sort színezi a kimeneten a log szintje,
    és bizonyos üzenetek tartalma alapján a konzolon.
    """
    # ANSI escape kódok a színekhez
    GREY = "\x1b[38;20m"
    YELLOW = "\x1b[33;20m"
    RED = "\x1b[31;20m"
    BOLD_RED = "\x1b[31;1m"
    LIGHT_BLUE = "\x1b[94m" # Világoskék szín hozzáadva
    RESET = "\x1b[0m"

    # Az alap formátum, ami mindenhol használva lesz
    BASE_FORMAT = "%(asctime)s - %(process)d - %(levelname)s - [%(funcName)s] - %(message)s"

    def __init__(self):
        super().__init__()
        # JAVÍTÁS: A formátumok mostantól a teljes sort színezik
        self.FORMATS = {
            logging.DEBUG: self.GREY + self.BASE_FORMAT + self.RESET,
            logging.INFO: self.GREY + self.BASE_FORMAT + self.RESET,
            logging.WARNING: self.YELLOW + self.BASE_FORMAT + self.RESET,
            logging.ERROR: self.RED + self.BASE_FORMAT + self.RESET,
            logging.CRITICAL: self.BOLD_RED + self.BASE_FORMAT + self.RESET,
        }

    def format(self, record):
        # Speciális eset a ciklus vége üzenetnek
        if "--- Ciklus vége" in record.getMessage():
            log_fmt = self.LIGHT_BLUE + self.BASE_FORMAT + self.RESET
        else:
            log_fmt = self.FORMATS.get(record.levelno, self.FORMATS[logging.INFO])
        
        formatter = logging.Formatter(log_fmt)
        return formatter.format(record)

class AdminNotificationHandler(logging.Handler):
    """
    Egyedi log handler, amely minden ERROR/CRITICAL logot elküld az admin(ok) Telegramjára.
    """
    def __init__(self, bot_token, users_json_path='data/users.json'):
        super().__init__(level=logging.ERROR)
        self.bot_token = bot_token
        self.admin_ids = [user['telegram_id'] for user in get_all_users(users_json_path) if is_admin(user)]

    def emit(self, record):
        if record.levelno >= logging.ERROR:
            msg = self.format(record)
            for admin_id in self.admin_ids:
                try:
                    send_telegram_message(self.bot_token, admin_id, f"[HIBA] {msg}")
                except Exception as e:
                    print(f"Nem sikerült adminnak hibát küldeni Telegramon: {e}")

def setup_logging(cfg, log_dir: Path):
    """
    Beállítja a naplózást. A fő processznek és a bot processznek külön logfájlt és külön naplózási szintet használ.
    A fő processz konzol kimenete színes.
    """
    process_name = multiprocessing.current_process().name
    
    if process_name == 'MainProcess':
        log_level_str = cfg['settings'].get('loglevel_main', 'INFO')
        log_file_name = "main_process.txt"
    else:
        log_level_str = cfg['settings'].get('loglevel_bot', 'WARNING')
        log_file_name = "telegram_bot_process.txt"

    clear_on_startup = cfg['settings'].get('clear_log_on_startup', False)
    backup_count = cfg['settings'].get('log_rotation_backup_count', 14)

    log_dir.mkdir(parents=True, exist_ok=True)
    # Egyszerű, színkód nélküli formatter a fájlokhoz
    plain_formatter = logging.Formatter('%(asctime)s - %(process)d - %(levelname)s - [%(funcName)s] - %(message)s')
    
    log_file_path = log_dir / log_file_name

    if process_name == 'MainProcess' and clear_on_startup and log_file_path.exists():
        try:
            log_file_path.unlink()
            print(f"Info: A(z) {log_file_name} naplófájl törölve a beállítások alapján.")
        except Exception as e:
            print(f"Warning: Nem sikerült törölni a(z) {log_file_name} naplófájlt: {e}")

    # Fájl handler a sima formatterrel
    file_handler = TimedRotatingFileHandler(
        log_file_path, when="midnight", interval=1, backupCount=backup_count, encoding='utf-8'
    )
    file_handler.setFormatter(plain_formatter)
    
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)
    
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
        
    file_handler.setLevel(log_level_str.upper())
    logger.addHandler(file_handler)

    # A konzolra csak a fő processz írjon, és a színes formattert használja
    if process_name == 'MainProcess':
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(CustomColorFormatter()) # Itt használjuk a színes formattert
        console_handler.setLevel(logging.INFO)
        logger.addHandler(console_handler)

    # Külső könyvtárak naplózásának halkítása
    third_party_loggers = [
        "requests", "urllib3", "httpx", 
        "telegram", "apscheduler", "httpcore",
        "matplotlib"
    ]
    for lib_name in third_party_loggers:
        logging.getLogger(lib_name).setLevel(logging.WARNING)

    # A végén admin értesítő handler hozzáadása
    bot_token = cfg.get('telegram', {}).get('bot_token')
    if bot_token:
        admin_handler = AdminNotificationHandler(bot_token)
        admin_handler.setLevel(logging.ERROR)
        admin_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
        logger.addHandler(admin_handler)

    logger.info(f"Naplózás beállítva a(z) '{process_name}' processz számára. Szint: {log_level_str.upper()}. Fájl: {log_file_path}")