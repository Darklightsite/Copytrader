
import configparser
import logging
import json

logger = logging.getLogger()

def load_configuration(path='config.ini'):
    """Beolvassa és validálja a konfigurációt a megadott .ini fájlból."""
    parser = configparser.ConfigParser()
    if not parser.read(path, encoding='utf-8'):
        logger.critical(f"A konfigurációs fájl ({path}) nem található vagy üres!")
        return None

    config = {}
    try:
        # API Szekció
        config['live_api'] = {
            'api_key': parser.get('api', 'api_key_live'),
            'api_secret': parser.get('api', 'api_secret_live'),
            'url': 'https://api.bybit.com',  # Helyes élő URL 
            'is_demo': False
        }
        config['demo_api'] = {
            'api_key': parser.get('api', 'api_key_demo'),
            'api_secret': parser.get('api', 'api_secret_demo'),
            'url': 'https://api-demo.bybit.com',  # Helyes demó URL 
            'is_demo': True
        }

        # Telegram Szekció
        config['telegram'] = {
            'bot_token': parser.get('telegram', 'bot_token', fallback=None),
            'chat_id': parser.get('telegram', 'chat_id', fallback=None)
        }
        
        # Account Modes Szekció
        config['account_modes'] = {
            'demo_mode': parser.get('account_modes', 'demo_mode', fallback='Hedge')
        }

        # Settings Szekció
        sl_tiers_str = parser.get('settings', 'SL_LOSS_TIERS_USD', fallback='10, 20, 30')
        config['settings'] = {
            'live_start_date': parser.get('settings', 'LiveStartDate', fallback=None),
            'demo_start_date': parser.get('settings', 'DemoStartDate', fallback=None),
                      'log_rotation_backup_count': parser.getint('settings', 'LogRotationBackupCount', fallback=14),
            'loop_interval': parser.getint('settings', 'LoopIntervalSeconds', fallback=120),
            'symbols_to_copy': json.loads(parser.get('settings', 'SymbolsToCopy', fallback='[]')),
            'log_level': parser.get('settings', 'LogLevel', fallback='INFO'),
            'clear_log_on_startup': parser.getboolean('settings', 'ClearLogOnStartup', fallback=True),
            'copy_multiplier': parser.getfloat('settings', 'COPY_MULTIPLIER', fallback=1.0), # 
            'qty_precision': parser.getint('settings', 'QTY_PRECISION', fallback=4),
            'sl_loss_tiers_usd': sorted([float(x.strip()) for x in sl_tiers_str.split(',')], reverse=True)
        }
        
    except (configparser.NoSectionError, configparser.NoOptionError, ValueError, json.JSONDecodeError) as e:
        logger.critical(f"Konfigurációs hiba a(z) {path} fájlban. Hiba: {e}", exc_info=True) # 
        return None

    logger.info("Konfiguráció sikeresen betöltve.")
    return config
