
import logging
import multiprocessing
import os
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

def setup_logging(cfg, log_dir: Path):
    """
    Beállítja a naplózást. A fő processznek és a bot processznek külön logfájlt hoz létre.
    """
    log_level_str = cfg['settings'].get('log_level', 'INFO')
    clear_on_startup = cfg['settings'].get('clear_log_on_startup', False)
    backup_count = cfg['settings'].get('log_rotation_backup_count', 14)

    log_dir.mkdir(parents=True, exist_ok=True)
    log_formatter = logging.Formatter('%(asctime)s - %(process)d - %(levelname)s - [%(funcName)s] - %(message)s')

    process_name = multiprocessing.current_process().name
    if process_name == 'MainProcess':
        log_file_name = "trade_copier_main.txt"
    else:
        log_file_name = f"trade_copier_bot_telegramm.txt"

    log_file_path = log_dir / log_file_name

    if process_name == 'MainProcess' and clear_on_startup and (log_dir / "trade_copier_main.txt").exists():
        try:
            (log_dir / "trade_copier_main.txt").unlink()
            print("Info: Előző fő naplófájl törölve a beállítások alapján.")
        except Exception as e:
            print(f"Warning: Nem sikerült törölni az előző fő naplófájlt: {e}")

    file_handler = TimedRotatingFileHandler(
        log_file_path,
        when="midnight",
        interval=1,
        backupCount=backup_count,
        encoding='utf-8'
    )
    file_handler.setFormatter(log_formatter)
    
    logger = logging.getLogger()
    
    # Elkerüljük a handler-ek duplikálódását
    if not logger.handlers:
        logger.setLevel(log_level_str.upper())
        logger.addHandler(file_handler)

        # --- JAVÍTÁS: A konzolra csak a fő processz írjon ---
        if process_name == 'MainProcess':
            console_handler = logging.StreamHandler()
            console_handler.setFormatter(log_formatter)
            console_handler.setLevel(logging.INFO) # A konzolra csak az INFO szintű üzenetek mennek
            logger.addHandler(console_handler)
    else:
        for handler in logger.handlers[:]:
            if isinstance(handler, TimedRotatingFileHandler):
                logger.removeHandler(handler)
        logger.addHandler(file_handler)

    # Külső könyvtárak naplózásának halkítása
    logging.getLogger("requests").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("telegram").setLevel(logging.WARNING)
    logging.getLogger("apscheduler").setLevel(logging.WARNING)

    logger.info(f"Naplózás beállítva a(z) '{process_name}' processz számára. Fájl: {log_file_path}")
