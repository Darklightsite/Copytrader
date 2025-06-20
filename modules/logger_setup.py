# FÁJL: modules/logger_setup.py (Teljes, javított kód)

import logging
import multiprocessing
import os
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

class CustomColorFormatter(logging.Formatter):
    """
    Egyedi log formatter, amely színezi a kimenetet a log szintje,
    és bizonyos üzenetek tartalma alapján a konzolon.
    """
    # ANSI escape kódok a színekhez
    GREY = "\x1b[38;20m"
    YELLOW = "\x1b[33;20m"
    RED = "\x1b[31;20m"
    BOLD_RED = "\x1b[31;1m"
    BLUE = "\x1b[34;20m" # Kék szín hozzáadva
    RESET = "\x1b[0m"

    # Az alap formátum, ami mindenhol használva lesz
    BASE_FORMAT = "%(asctime)s - %(process)d - %(levelname)s - [%(funcName)s] - "

    def __init__(self):
        super().__init__()
        self.FORMATS = {
            logging.DEBUG: self.GREY + self.BASE_FORMAT + self.RESET + self.GREY + "%(message)s" + self.RESET,
            logging.INFO: self.GREY + self.BASE_FORMAT + self.RESET + "%(message)s", # Alapértelmezett INFO
            logging.WARNING: self.YELLOW + self.BASE_FORMAT + self.RESET + self.YELLOW + "%(message)s" + self.RESET,
            logging.ERROR: self.RED + self.BASE_FORMAT + self.RESET + self.RED + "%(message)s" + self.RESET,
            logging.CRITICAL: self.BOLD_RED + self.BASE_FORMAT + self.RESET + self.BOLD_RED + "%(message)s" + self.RESET,
        }

    def format(self, record):
        # Speciális eset a ciklus vége üzenetnek
        if "--- Ciklus vége" in record.getMessage():
            # JAVÍTÁS: Pirosról kékre cserélve
            log_fmt = self.GREY + self.BASE_FORMAT + self.RESET + self.BLUE + "%(message)s" + self.RESET
        else:
            log_fmt = self.FORMATS.get(record.levelno, self.FORMATS[logging.INFO])
        
        formatter = logging.Formatter(log_fmt)
        return formatter.format(record)


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

    logger.info(f"Naplózás beállítva a(z) '{process_name}' processz számára. Szint: {log_level_str.upper()}. Fájl: {log_file_path}")