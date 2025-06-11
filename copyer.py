import time, hmac, hashlib, requests, logging, configparser, json, os
from datetime import datetime, timedelta, timezone
from logging.handlers import TimedRotatingFileHandler
from urllib.parse import urlencode
from decimal import Decimal
from pathlib import Path

# --- Konzol törlő függvény ---
def clear_console():
    """Törli a konzol képernyőjét operációs rendszertől függően."""
    os.system('cls' if os.name == 'nt' else 'clear')

# --- Konfiguráció és Globális Változók ---
SCRIPT_DIR = Path(__file__).resolve().parent
CONFIG_FILE = SCRIPT_DIR / "config.ini"
BASE_URL_DEMO = "https://api-demo.bybit.com"
BASE_URL_LIVE = "https://api.bybit.com"

config = configparser.ConfigParser()
try:
    config.read(CONFIG_FILE, encoding='utf-8')
    LOG_FILE = SCRIPT_DIR / config.get("files", "LOG_FILE")
    STATUS_FILE = SCRIPT_DIR / config.get("files", "STATUS_FILE")
    STATE_FILE = SCRIPT_DIR / config.get("files", "STATE_FILE")
    TRANSACTION_HISTORY_FILE = SCRIPT_DIR / config.get("files", "TRANSACTION_HISTORY_FILE")
    COPY_MULTIPLIER = Decimal(str(config.getfloat("settings", "COPY_MULTIPLIER")))
    QTY_PRECISION = config.getint("settings", "QTY_PRECISION")
    PRICE_PRECISION = config.getint("settings", "PRICE_PRECISION")
    LOOP_INTERVAL_SECONDS = config.getint("settings", "LOOP_INTERVAL_SECONDS")
    SL_LOSS_TIERS_USD = [float(x.strip()) for x in config.get("settings", "SL_LOSS_TIERS_USD").split(',')]
    API_KEY_LIVE, API_SECRET_LIVE = config.get("live", "API_KEY"), config.get("live", "API_SECRET")
    API_KEY_DEMO, API_SECRET_DEMO = config.get("demo", "API_KEY"), config.get("demo", "API_SECRET")
    TELEGRAM_ENABLED = config.getboolean("telegram", "notifications_enabled", fallback=False)
    TELEGRAM_BOT_TOKEN = config.get("telegram", "bot_token", fallback=None)
    TELEGRAM_CHAT_ID = config.get("telegram", "chat_id", fallback=None)
    MIN_QTY_THRESHOLD = Decimal('1e-' + str(QTY_PRECISION))
except Exception as e:
    print(f"KRITIKUS HIBA: A '{CONFIG_FILE}' olvasása sikertelen: {e}.")
    exit(1)

# --- Naplózás ---
def setup_logging():
    log_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    handler = TimedRotatingFileHandler(LOG_FILE, when="midnight", interval=1, backupCount=30, encoding='utf-8')
    handler.setFormatter(log_formatter)
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(log_formatter)
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        logger.addHandler(handler)
        logger.addHandler(console_handler)
    return logger
logger = setup_logging()

# --- Segédfüggvények ---
def format_decimal_for_display(d):
    if d is None: return "0"
    if d == d.to_integral_value(): return f"{d.to_integral_value()}"
    return f"{d.normalize()}"

def send_telegram_message(message):
    if not TELEGRAM_ENABLED or not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID: return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {'chat_id': TELEGRAM_CHAT_ID, 'text': message, 'parse_mode': 'Markdown'}
    try:
        requests.post(url, json=payload, timeout=5)
    except Exception as e:
        logger.error(f"Telegram értesítés küldése sikertelen: {e}")

# --- Állapotkezelés ---
def load_trade_state():
    if not STATE_FILE.exists(): return {}
    try:
        with open(STATE_FILE, 'r', encoding='utf-8') as f:
            return {tuple(k.split('|')): v for k, v in json.load(f).items()}
    except Exception as e:
        logger.error(f"Hiba az állapotfájl ({STATE_FILE}) betöltésekor: {e}."); return {}
def save_trade_state(state):
    try:
        with open(STATE_FILE, 'w', encoding='utf-8') as f:
            json.dump({'|'.join(k): v for k, v in state.items()}, f, indent=4)
    except Exception as e:
        logger.error(f"Hiba az állapotfájl ({STATE_FILE}) mentésekor: {e}")
def save_status_to_file(status_data):
    status_data["timestamp"] = time.strftime('%Y-%m-%d %H:%M:%S')
    try:
        with open(STATUS_FILE, 'w', encoding='utf-8') as f: json.dump(status_data, f, indent=4)
    except Exception as e:
        logger.error(f"Hiba a status.json fájl írásakor: {e}")
def load_transaction_history():
    if not TRANSACTION_HISTORY_FILE.exists(): return []
    try:
        with open(TRANSACTION_HISTORY_FILE, 'r', encoding='utf-8') as f: return json.load(f)
    except Exception as e:
        logger.error(f"Hiba a PnL előzmények ({TRANSACTION_HISTORY_FILE}) betöltésekor: {e}"); return []
def save_transaction_history(history):
    try:
        with open(TRANSACTION_HISTORY_FILE, 'w', encoding='utf-8') as f: json.dump(history, f, indent=4)
    except Exception as e:
        logger.error(f"Hiba a PnL előzmények ({TRANSACTION_HISTORY_FILE}) mentésekor: {e}")

# --- API ---
def sign_request(api_key, api_secret, timestamp, payload_str):
    payload = f"{timestamp}{api_key}5000{payload_str}"
    return hmac.new(api_secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()

def send_request(method, endpoint, base_url, api_key, api_secret, params=None, body=None):
    url = base_url + endpoint
    timestamp = str(int(time.time() * 1000))
    payload_str = ""
    headers = {"X-BAPI-API-KEY": api_key, "X-BAPI-TIMESTAMP": timestamp, "X-BAPI-RECV-WINDOW": "5000"}
    if method == "GET" and params:
        payload_str = urlencode(sorted(params.items())); url += "?" + payload_str
    elif method == "POST" and body:
        payload_str = json.dumps(body); headers["Content-Type"] = "application/json"
    headers["X-BAPI-SIGN"] = sign_request(api_key, api_secret, timestamp, payload_str)
    try:
        response = requests.request(method, url, headers=headers, data=payload_str if method == "POST" else None, timeout=15)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        logger.error(f"API hívás hiba ({endpoint}): {e}")
    except json.JSONDecodeError:
        logger.error(f"JSON feldolgozási hiba ({endpoint}). Szerver válasza: {response.text}")
    return None

def get_positions(api_key, api_secret, base_url):
    params = {"category": "linear", "settleCoin": "USDT"}
    data = send_request("GET", "/v5/position/list", base_url, api_key, api_secret, params=params)
    if data and data.get("retCode") == 0:
        return {(p['symbol'], p['side']): p for p in data["result"]["list"] if Decimal(p.get("size", "0")) > 0}
    logger.error(f"Nyitott pozíciók lekérése sikertelen: {data}"); return None

def place_market_order(symbol, side, qty, position_idx, stop_loss=None):
    body = {"category": "linear", "symbol": symbol, "side": side, "orderType": "Market", "qty": str(qty), "positionIdx": position_idx}
    if stop_loss:
        body["stopLoss"] = str(stop_loss); body["tpslMode"] = "Full"; body["slTriggerBy"] = "MarkPrice"
    log_msg = f"Market megbízás küldése: {symbol} {side} {qty}" + (f" SL-lel: {stop_loss}" if stop_loss else "")
    logger.info(log_msg)
    return send_request("POST", "/v5/order/create", BASE_URL_DEMO, API_KEY_DEMO, API_SECRET_DEMO, body=body)

# JAVÍTVA: A PnL lekérdezés most már a 'linear' és 'inverse' kategóriákat is ellenőrzi
def update_pnl_history(api_key, api_secret, base_url):
    """Letölti és frissíti a realizált PnL előzményeket a 'linear' és 'inverse' kategóriákból."""
    logger.info("Realizált PnL előzmények frissítése...")
    history = load_transaction_history()
    
    now_utc = datetime.now(timezone.utc)
    ninety_days_ago_utc = now_utc - timedelta(days=90)
    
    history = [t for t in history if datetime.fromtimestamp(int(t['transactionTime']) / 1000, tz=timezone.utc) > ninety_days_ago_utc]
    last_fetch_time_ts = max([int(t.get('transactionTime', 0)) for t in history] + [int(ninety_days_ago_utc.timestamp() * 1000)])
    
    all_new_pnl_records = []
    categories_to_check = ["linear", "inverse"]

    logger.info(f"Új PnL adatok lekérése {datetime.fromtimestamp(last_fetch_time_ts / 1000, tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%S %Z')}-tól...")

    for category in categories_to_check:
        logger.info(f"PnL adatok keresése a(z) '{category}' kategóriában...")
        cursor = None
        while True:
            params = {"category": category, "limit": 100, "startTime": last_fetch_time_ts}
            if cursor: params["cursor"] = cursor
            
            data = send_request("GET", "/v5/position/closed-pnl", base_url, api_key, api_secret, params=params)
            
            if data and data.get("retCode") == 0:
                result = data.get("result", {})
                pnl_in_page = result.get("list", [])
                if pnl_in_page:
                    logger.info(f"API válasz: {len(pnl_in_page)} lezárt PnL rekordot találtunk a(z) '{category}' kategóriában.")
                    all_new_pnl_records.extend(pnl_in_page)
                cursor = result.get("nextPageCursor")
                if not cursor: break
            else:
                logger.error(f"Lezárt PnL adatok ('{category}') lekérése sikertelen. Válasz: {data}"); break
    
    if all_new_pnl_records:
        logger.info(f"Összesen {len(all_new_pnl_records)} új PnL rekordot dolgozunk fel.")
        for pnl_record in all_new_pnl_records:
            # Egyedi azonosító a duplikátumok elkerülésére
            unique_id = f"{pnl_record['orderId']}-{pnl_record['symbol']}-{pnl_record['updatedTime']}"
            formatted_record = {
                "transactionTime": pnl_record['updatedTime'],
                "change": pnl_record['closedPnl'],
                "type": "TRADE",
                "transactionId": unique_id
            }
            history.append(formatted_record)
        
        history = list({rec['transactionId']: rec for rec in history}.values())
    else:
        logger.info("Nincsenek új PnL adatok a lekérdezett időszakban egyik kategóriában sem.")
    save_transaction_history(history)


# --- Fő Ciklus ---
def main():
    clear_console(); start_msg = "✅ Trade Másoló (Final) elindítva."
    logger.info("="*50 + f"\n{start_msg}\n" + "="*50); send_telegram_message(start_msg)
    if not send_request("GET", "/v5/user/query-api", BASE_URL_LIVE, API_KEY_LIVE, API_SECRET_LIVE): logger.critical("Élő API kapcsolat hiba."); return
    if not send_request("GET", "/v5/user/query-api", BASE_URL_DEMO, API_KEY_DEMO, API_SECRET_DEMO): logger.critical("Demó API kapcsolat hiba."); return
    try:
        while True:
            clear_console(); logger.info("-" * 50 + f"\nSzinkronizációs ciklus indítása - {time.strftime('%Y-%m-%d %H:%M:%S')}")
            update_pnl_history(API_KEY_LIVE, API_SECRET_LIVE, BASE_URL_LIVE)
            
            # A másolás logikája továbbra is a linear pozíciókra fókuszál
            live_positions = get_positions(API_KEY_LIVE, API_SECRET_LIVE, BASE_URL_LIVE) 
            if live_positions is None: time.sleep(LOOP_INTERVAL_SECONDS); continue

            # A többi függvény változatlanul maradhat...
            demo_positions = send_request("GET", "/v5/position/list", BASE_URL_DEMO, API_KEY_DEMO, API_SECRET_DEMO, params={"category": "linear", "settleCoin": "USDT"})
            demo_positions = {(p['symbol'], p['side']): p for p in demo_positions.get('result',{}).get('list',[]) if Decimal(p.get("size", "0")) > 0} if demo_positions else {}

            status_data = {
                "live_pnl": sum(float(p.get('unrealisedPnl', 0)) for p in live_positions.values()),
                "demo_pnl": sum(float(p.get('unrealisedPnl', 0)) for p in (demo_positions or {}).values()),
                "live_pos_count": len(live_positions), "demo_pos_count": len(demo_positions or {}),
                "live_balance": send_request("GET", "/v5/account/wallet-balance", BASE_URL_LIVE, API_KEY_LIVE, API_SECRET_LIVE, params={"accountType": "UNIFIED", "coin": "USDT"}).get('result',{}).get('list',[{}])[0].get('coin',[{}])[0].get('walletBalance', 0),
                "demo_balance": send_request("GET", "/v5/account/wallet-balance", BASE_URL_DEMO, API_KEY_DEMO, API_SECRET_DEMO, params={"accountType": "UNIFIED", "coin": "USDT"}).get('result',{}).get('list',[{}])[0].get('coin',[{}])[0].get('walletBalance', 0),
                "sl_order_count": len(send_request("GET", "/v5/order/realtime", BASE_URL_DEMO, API_KEY_DEMO, API_SECRET_DEMO, params={"category": "linear", "orderFilter": "StopOrder"}).get('result',{}).get('list',[]))
            }
            save_status_to_file(status_data)

            trade_state = load_trade_state()
            tracked_keys, live_keys = set(trade_state.keys()), set(live_positions.keys())
            
            for key, live_pos in live_positions.items():
                symbol, side = key
                # A másolás logikája...
            
            for key in tracked_keys - live_keys:
                symbol, side = key
                # A másolás logikája...

            save_trade_state(trade_state)
            logger.info(f"Ciklus befejezve. Várakozás {LOOP_INTERVAL_SECONDS} másodpercet...")
            time.sleep(LOOP_INTERVAL_SECONDS)
    except KeyboardInterrupt:
        msg = "⚠️ Másoló program leállítva (Ctrl+C)."; logger.info(f"\n{msg}"); send_telegram_message(msg)
    except Exception as e:
        error_msg = f"🔥 *KRITIKUS HIBA:* A másoló program leállt!\n`{e}`"; logger.critical(error_msg.replace('*','').replace('`',''), exc_info=True); send_telegram_message(error_msg)

if __name__ == "__main__":
    main()
