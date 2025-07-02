import os
import sys
import multiprocessing
from modules.config_loader import get_all_users, load_configuration, is_master, is_user
from modules.logger_setup import setup_logging
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent / "data"


def run_for_user(nickname):
    config = load_configuration(nickname)
    if not config:
        print(f"[HIBA] Nem sikerült betölteni a konfigurációt: {nickname}")
        return
    log_dir = DATA_DIR / "users" / nickname / "logs"
    setup_logging(config, log_dir=log_dir)
    # Itt lehet folytatni a userhez tartozó fő logikát (pl. kereskedés, adatgyűjtés, stb.)
    import logging
    logger = logging.getLogger()
    logger.info(f"Fiók indítása: {nickname}")
    if is_master({'account_type': config['settings'].get('account_type', '')}):
        logger.info("Ez a master account, csak adatforrásként működik.")
        # Master account logika (pl. csak adatgyűjtés)
    elif is_user({'account_type': config['settings'].get('account_type', '')}):
        logger.info("Ez egy user account, kereskedési logika indul.")
        # User account logika (pl. kereskedés, szinkron, stb.)
    else:
        logger.warning("Ismeretlen account típus!")


def main():
    users = get_all_users()
    if not users:
        print("[HIBA] Nincs egyetlen felhasználó sem a users.json-ban!")
        return
    processes = []
    for user in users:
        nickname = user.get('nickname')
        if not nickname:
            continue
        p = multiprocessing.Process(target=run_for_user, args=(nickname,), daemon=True)
        p.start()
        processes.append(p)
    for p in processes:
        p.join()

if __name__ == "__main__":
    multiprocessing.freeze_support()
    main() 