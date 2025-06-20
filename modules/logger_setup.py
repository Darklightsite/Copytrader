# FÁJL: modules/logger_setup.py (Teljes, javított kód)

import logging
import multiprocessing
import os
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

def setup_logging(cfg, log_dir: Path):
    """
    Beállítja a naplózást. A fő processznek és a bot processznek külön logfájlt és külön naplózási szintet használ.
    """
    process_name = multiprocessing.current_process().name
    
    # Naplózási szint és fájlnév meghatározása a processz neve alapján
    if process_name == 'MainProcess':
        log_level_str = cfg['settings'].get('loglevel_main', 'INFO')
        log_file_name = "main_process.log"
    else: # Feltételezzük, hogy minden más processz a Telegram bothoz tartozik
        log_level_str = cfg['settings'].get('loglevel_bot', 'WARNING')
        log_file_name = "telegram_bot_process.log"

    clear_on_startup = cfg['settings'].get('clear_log_on_startup', False)
    backup_count = cfg['settings'].get('log_rotation_backup_count', 14)

    log_dir.mkdir(parents=True, exist_ok=True)
    log_formatter = logging.Formatter('%(asctime)s - %(process)d - %(levelname)s - [%(funcName)s] - %(message)s')
    
    log_file_path = log_dir / log_file_name

    # Fő processz indításakor töröljük a régi naplót, ha a beállítás úgy kívánja
    if process_name == 'MainProcess' and clear_on_startup and log_file_path.exists():
        try:
            log_file_path.unlink()
            print(f"Info: A(z) {log_file_name} naplófájl törölve a beállítások alapján.")
        except Exception as e:
            print(f"Warning: Nem sikerült törölni a(z) {log_file_name} naplófájlt: {e}")

    file_handler = TimedRotatingFileHandler(
        log_file_path,
        when="midnight",
        interval=1,
        backupCount=backup_count,
        encoding='utf-8'
    )
    file_handler.setFormatter(log_formatter)
    
    logger = logging.getLogger()
    
    # A gyökér naplózó szintjét mindig a legbőbeszédűbbre (DEBUG) állítjuk,
    # hogy a handlerek tudják a szűrést végezni.
    logger.setLevel(logging.DEBUG)
    
    # Eltávolítjuk a régi handlereket a duplikáció elkerülése végett
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
        
    # Hozzáadjuk az új, szint-specifikus file handlert
    file_handler.setLevel(log_level_str.upper())
    logger.addHandler(file_handler)

    # A konzolra csak a fő processz írjon, és csak INFO szinten
    if process_name == 'MainProcess':
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(log_formatter)
        console_handler.setLevel(logging.INFO)
        logger.addHandler(console_handler)

    # Külső könyvtárak naplózásának halkítása a "szemét" elkerülése érdekében
    # Ezek a beállítások minden processzre érvényesek lesznek
    third_party_loggers = ["requests", "urllib3", "httpx", "telegram", "apscheduler", "httpcore"]
    for lib_name in third_party_loggers:
        logging.getLogger(lib_name).setLevel(logging.WARNING)

    logger.info(f"Naplózás beállítva a(z) '{process_name}' processz számára. Szint: {log_level_str.upper()}. Fájl: {log_file_path}")