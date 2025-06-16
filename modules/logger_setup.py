import logging
from logging.handlers import TimedRotatingFileHandler
import multiprocessing
import os
from pathlib import Path

LOG_DIR = Path(__file__).resolve().parent.parent / "data" / "logs"

def setup_logging(cfg):
    """Beállítja a naplózást a fő- és alprocesszek számára."""
    try:
        log_level_str = cfg['settings']['log_level']
        clear_on_startup = cfg['settings']['clearlogonstartup']
        
        log_formatter = logging.Formatter('%(asctime)s - %(levelname)s - [%(funcName)s] - %(message)s')
        LOG_DIR.mkdir(parents=True, exist_ok=True)

        log_file_name = "trade_copier.txt"
        # Ha a bot processz futtatja, más nevet adunk a lognak
        if multiprocessing.current_process().name != 'MainProcess':
            log_file_name = f"trade_copier_bot_{os.getpid()}.txt"
        
        log_file = LOG_DIR / log_file_name

        # Csak a fő processz törölje a fő logot indításkor
        if multiprocessing.current_process().name == 'MainProcess' and clear_on_startup and (LOG_DIR / "trade_copier.txt").exists():
            try:
                (LOG_DIR / "trade_copier.txt").unlink()
                print(f"Info: Előző naplófájl (trade_copier.txt) törölve a `ClearLogOnStartup=True` beállítás alapján.")
            except Exception as e:
                print(f"Warning: Nem sikerült törölni az előző naplófájlt: {e}")

        file_handler = TimedRotatingFileHandler(log_file, when="D", interval=1, backupCount=14, encoding='utf-8')
        file_handler.setFormatter(log_formatter)
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(log_formatter)
        
        logger = logging.getLogger()
        
        # Elkerüljük a handler-ek duplikálását
        if not logger.handlers:
            logger.setLevel(log_level_str.upper())
            logger.addHandler(file_handler)
            logger.addHandler(console_handler)

        # Csendesítjük a library-k saját loggereit
        logging.getLogger("httpx").setLevel(logging.WARNING)
        logging.getLogger("telegram").setLevel(logging.WARNING)
        logging.getLogger("apscheduler").setLevel(logging.WARNING)
    except Exception as e:
        print(f"Hiba a naplózás beállítása során: {e}")
