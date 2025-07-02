import os
import sys
import multiprocessing
from modules.config_loader import get_all_users, load_configuration, is_master, is_user
from modules.logger_setup import setup_logging, send_admin_alert
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent / "data"


def run_for_user(nickname):
    config = load_configuration(nickname)
    if not config:
        print(f"[HIBA] Nem sikerült betölteni a konfigurációt: {nickname}")
        send_admin_alert(f"Nem sikerült betölteni a konfigurációt: {nickname}", user=nickname)
        return
    log_dir = DATA_DIR / "users" / nickname / "logs"
    setup_logging(config, log_dir=log_dir)
    # Itt lehet folytatni a userhez tartozó fő logikát (pl. kereskedés, adatgyűjtés, stb.)
    import logging
    logger = logging.getLogger()
    logger.info(f"Fiók indítása: {nickname}")
    try:
        if is_master({'account_type': config['settings'].get('account_type', '')}):
            logger.info("Ez a master account, csak adatforrásként működik.")
            # Master account logika (pl. csak adatgyűjtés)
        elif is_user({'account_type': config['settings'].get('account_type', '')}):
            logger.info("Ez egy user account, kereskedési logika indul.")
            # User account logika (pl. kereskedés, szinkron, stb.)
        else:
            logger.warning("Ismeretlen account típus!")
            send_admin_alert(f"Ismeretlen account típus: {nickname}", user=nickname, account=config['settings'].get('account_type'))
    except Exception as e:
        logger.error(f"Váratlan hiba a fiók indításakor: {e}", exc_info=True)
        send_admin_alert(f"❌ Váratlan hiba a fiók indításakor ({nickname}): {e}", user=nickname, account=config['settings'].get('account_type'))


def main():
    users = get_all_users()
    if not users:
        print("[HIBA] Nincs egyetlen felhasználó sem a users.json-ban!")
        send_admin_alert("Nincs egyetlen felhasználó sem a users.json-ban!", user=None, account=None)
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