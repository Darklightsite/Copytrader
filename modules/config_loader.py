import configparser
import json
from decimal import Decimal
from pathlib import Path

# A fő könyvtárban lévő config.ini-re hivatkozunk
CONFIG_FILE = Path(__file__).resolve().parent.parent / "config.ini"

def load_configuration():
    """Beolvassa és feldolgozza a konfigurációs fájlt."""
    if not CONFIG_FILE.exists():
        # A naplózás még nem él, ezért printet használunk
        print(f"KRITIKUS HIBA: A konfigurációs fájl nem található: {CONFIG_FILE}")
        return None
    try:
        config = configparser.ConfigParser(interpolation=None)
        config.read(CONFIG_FILE, encoding='utf-8')
        sl_tiers_str = config.get('settings', 'SL_LOSS_TIERS_USD', fallback='10, 20, 30')
        
        return {
            "live_api": {'key': config['api']['api_key_live'], 'secret': config['api']['api_secret_live'], 'url': "https://api.bybit.com"},
            "demo_api": {'key': config['api']['api_key_demo'], 'secret': config['api']['api_secret_demo'], 'url': "https://api-demo.bybit.com"},
            "telegram": {'token': config.get('telegram', 'bot_token', fallback=None), 'chat_id': config.get('telegram', 'chat_id', fallback=None)},
            "settings": {
                'loop_interval': config.getint('settings', 'LoopIntervalSeconds', fallback=15),
                'symbols_to_copy': json.loads(config.get('settings', 'SymbolsToCopy', fallback='[]')),
                'log_level': config.get('settings', 'LogLevel', fallback='INFO'),
                'clearlogonstartup': config.getboolean('settings', 'ClearLogOnStartup', fallback=False),
                'copy_multiplier': Decimal(str(config.getfloat('settings', 'COPY_MULTIPLIER', fallback=1.0))),
                'qty_precision': config.getint('settings', 'QTY_PRECISION', fallback=3),
                'sl_loss_tiers_usd': sorted([float(x.strip()) for x in sl_tiers_str.split(',')], reverse=True)
            },
            "account_modes": {'demo_mode': config.get('account_modes', 'DemoAccountPositionMode', fallback='Hedge').strip().capitalize()}
        }
    except Exception as e:
        print(f"KRITIKUS HIBA a konfiguráció feldolgozásakor: {e}")
        return None
