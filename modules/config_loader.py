# FÁJL: modules/config_loader.py (Teljes, javított kód)

import configparser
import logging
import os

logger = logging.getLogger()

def load_configuration(nickname, path=None):
    """
    Beolvassa és validálja a konfigurációt a megadott felhasználóhoz (data/users/<nickname>/config.ini), részletes naplózással.
    Ha path meg van adva, azt használja, különben a felhasználói mappát.
    """
    if path is None:
        config_path = os.path.abspath(os.path.join('data', 'users', nickname, 'config.ini'))
    else:
        config_path = os.path.abspath(path)
    logger.info(f"Konfigurációs fájl beolvasásának megkezdése: {config_path}")

    if not os.path.exists(config_path):
        logger.critical(f"A konfigurációs fájl NEM LÉTEZIK a megadott helyen: {config_path}")
        return None

    parser = configparser.ConfigParser()
    try:
        read_files = parser.read(config_path, encoding='utf-8')
        if not read_files:
            logger.critical(f"A konfigurációs fájl ({config_path}) üres vagy nem sikerült beolvasni.")
            return None
    except Exception as e:
        logger.critical(f"Hiba a konfigurációs fájl olvasása közben: {e}", exc_info=True)
        return None

    if not parser.has_section('settings'):
        logger.critical(f"A beolvasott konfigurációs fájlból HIÁNYZIK a [settings] szekció!")
        return None
    
    if not parser.has_option('settings', 'copy_multiplier'):
         logger.warning(f"A [settings] szekcióból hiányzik a 'copy_multiplier' opció. Az alapértelmezett 10.0 lesz használva.")

    config = {}
    try:
        # API Szekció
        config['api'] = {
            'api_key': parser.get('api', 'api_key'),
            'api_secret': parser.get('api', 'api_secret'),
            'url': parser.get('api', 'url', fallback='https://api.bybit.com'),
            'is_demo': parser.getboolean('api', 'is_demo', fallback=False)
        }

        # Telegram Szekció (opcionális, lehet központi is)
        config['telegram'] = {
            'bot_token': parser.get('telegram', 'bot_token', fallback=None),
            'chat_id': parser.get('telegram', 'chat_id', fallback=None)
        }
        
        # Account Modes Szekció
        config['account_modes'] = {
            'mode': parser.get('account_modes', 'mode', fallback='Hedge')
        }

        # Settings Szekció
        sl_tiers_str = parser.get('settings', 'sl_loss_tiers_usd', fallback='10, 20, 30')
        symbols_raw = parser.get('settings', 'symbolstocopy', fallback='')
        if symbols_raw.strip() == '[]':
            symbols_list = []
        else:
            symbols_list = [s.strip() for s in symbols_raw.split(',') if s.strip()]
            
        config['settings'] = {
            'start_date': parser.get('settings', 'startdate', fallback=None),
            'log_rotation_backup_count': parser.getint('settings', 'logrotationbackupcount', fallback=14),
            'loop_interval': parser.getint('settings', 'loopintervalseconds', fallback=120),
            'symbols_to_copy': symbols_list,
            'loglevel_main': parser.get('settings', 'loglevel_main', fallback='INFO'),
            'loglevel_bot': parser.get('settings', 'loglevel_bot', fallback='WARNING'),
            'clear_log_on_startup': parser.getboolean('settings', 'clearlogonstartup', fallback=True),
            'copy_multiplier': parser.getfloat('settings', 'copy_multiplier', fallback=10.0),
            'qty_precision': parser.getint('settings', 'qty_precision', fallback=4),
            'sl_loss_tiers_usd': sorted([float(x.strip()) for x in sl_tiers_str.split(',')], reverse=True)
        }
        
    except (configparser.NoSectionError, configparser.NoOptionError, ValueError) as e:
        logger.critical(f"Konfigurációs hiba a(z) {config_path} fájlban. Hiba: {e}", exc_info=True)
        return None

    logger.info("Konfiguráció sikeresen betöltve.")
    return config