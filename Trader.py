import time
import hmac
import hashlib
import requests
import logging
import configparser
import json
import os
from urllib.parse import urlencode
from decimal import Decimal, ROUND_DOWN, InvalidOperation

# --- Naplózás és Állapotfájl Beállítása ---
LOG_FILENAME = "trade_copier.log"
STATE_FILENAME = "copied_trades.json"

# A naplózás beállítása, hogy a konzolon és fájlban is megjelenjen minden.
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILENAME, mode='w'),
        logging.StreamHandler()
    ]
)

def log_and_print(msg):
    # Mostantól a basicConfig miatt a logging.info() mindenhova ír.
    logging.info(msg)

# --- Config betöltése ---
config = configparser.ConfigParser()
try:
    config.read("test.ini")
    AUTO_CONFIRM = config.getboolean("settings", "AUTO_CONFIRM", fallback=False)
    SL_LOSS_TIERS_USD = [float(x.strip()) for x in config.get("settings", "SL_LOSS_TIERS_USD", fallback="250,200,150,125,100,50,25").split(',')]
    LOOP_INTERVAL_SECONDS = config.getint("settings", "LOOP_INTERVAL_SECONDS", fallback=60)
    API_KEY_LIVE = config.get("live", "API_KEY")
    API_SECRET_LIVE = config.get("live", "API_SECRET")
    API_KEY_DEMO = config.get("demo", "API_KEY")
    API_SECRET_DEMO = config.get("demo", "API_SECRET")
    QTY_PRECISION = config.getint("settings", "QTY_PRECISION", fallback=8)
    PRICE_PRECISION = config.getint("settings", "PRICE_PRECISION", fallback=2)
    COPY_MULTIPLIER = config.getfloat("settings", "COPY_MULTIPLIER", fallback=1.0)
    LEVERAGE = config.getint("settings", "LEVERAGE", fallback=20)
except Exception as e:
    log_and_print(f"HIBA: Config betöltési hiba: {e}")
    exit(1)

BASE_URL_LIVE = "https://api.bybit.com"
BASE_URL_DEMO = "https://api-demo.bybit.com"
MIN_QTY_THRESHOLD = Decimal('1e-' + str(QTY_PRECISION))

# --- Állapotkezelő Függvények ---
def load_trade_state():
    if not os.path.exists(STATE_FILENAME): return {}
    try:
        with open(STATE_FILENAME, 'r') as f:
            state = json.load(f)
            for key in state:
                if 'live_qty' in state[key]:
                    state[key]['live_qty'] = Decimal(state[key]['live_qty'])
            return state
    except (json.JSONDecodeError, IOError):
        return {}

def save_trade_state(state_data):
    try:
        state_to_save = {}
        for key, value in state_data.items():
            state_to_save[key] = value.copy()
            if 'live_qty' in state_to_save[key]:
                state_to_save[key]['live_qty'] = str(state_to_save[key]['live_qty'])
        with open(STATE_FILENAME, 'w') as f:
            json.dump(state_to_save, f, indent=4)
    except IOError as e:
        log_and_print(f"HIBA: Állapotfájl mentése sikertelen ({STATE_FILENAME}): {e}")

# --- API és Segédfüggvények (Részletesebb naplózással) ---
def make_request(method, url, api_key, api_secret, params=None):
    params = params if params is not None else {}
    timestamp = str(int(time.time() * 1000))
    headers = {"X-BAPI-API-KEY": api_key, "X-BAPI-TIMESTAMP": timestamp, "X-BAPI-RECV-WINDOW": "5000"}
    
    sign_payload = timestamp + api_key + "5000"
    if method == "POST":
        headers["Content-Type"] = "application/json"
        body_str = json.dumps(params)
        sign_payload += body_str
    else: # GET
        query_string = urlencode(sorted(params.items()))
        sign_payload += query_string

    headers["X-BAPI-SIGN"] = hmac.new(api_secret.encode("utf-8"), sign_payload.encode("utf-8"), hashlib.sha256).hexdigest()

    try:
        if method == "POST":
            response = requests.post(url, headers=headers, data=body_str, timeout=15)
        else:
            response = requests.get(url, headers=headers, params=params, timeout=10)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        log_and_print(f"HIBA: API kérés hálózati hiba ({url}): {e}")
    except Exception as e:
        log_and_print(f"HIBA: API kérés általános hiba ({url}): {e}")
    return None

def get_positions_from_account(api_key, api_secret, base_url, account_name="Ismeretlen"):
    endpoint = "/v5/position/list"
    params = {"category": "linear", "settleCoin": "USDT"}
    data = make_request("GET", base_url + endpoint, api_key, api_secret, params)
    if data and data.get("retCode") == 0:
        return [pos for pos in data["result"]["list"] if quantize_value(pos.get("size", "0"), QTY_PRECISION) > Decimal(0)]
    log_and_print(f"Nem sikerült lekérni a pozíciókat ({account_name} számla): {data}")
    return []

def get_market_price(symbol, base_url, api_key, api_secret):
    log_and_print(f"Piaci ár lekérése: {symbol}...")
    endpoint = "/v5/market/tickers"
    params = {"category": "linear", "symbol": symbol}
    data = make_request("GET", base_url + endpoint, api_key, api_secret, params)
    if data and data.get("retCode") == 0 and data["result"]["list"]:
        price = quantize_value(data["result"]["list"][0]["markPrice"], PRICE_PRECISION)
        log_and_print(f"Sikeres ár lekérés: {symbol} @ {price}")
        return price
    log_and_print(f"HIBA: Piaci ár lekérése sikertelen ({symbol}): {data}")
    return None

def calculate_sl_price(entry_price, quantity, side, loss_usd_tiers, price_precision):
    log_and_print(f"SL számítás... Belépő: {entry_price}, Mennyiség: {quantity}, Oldal: {side}")
    if not all([quantity, entry_price]) or quantity <= 0 or entry_price <= 0: return None
    price_precision_str = '1e-' + str(price_precision)
    for loss_usd in loss_usd_tiers:
        try:
            price_change = (Decimal(str(loss_usd)) / quantity)
            sl_price = entry_price - price_change if side == "Buy" else entry_price + price_change
            if sl_price > 0: 
                final_sl = sl_price.quantize(Decimal(price_precision_str), rounding=ROUND_DOWN)
                log_and_print(f"SL számítás sikeres {loss_usd} USD veszteséggel. SL ár: {final_sl}")
                return final_sl
        except Exception: continue
    log_and_print("Figyelem: Nem sikerült érvényes, pozitív SL árat számolni a megadott szintekkel.")
    return None

def quantize_value(value_str, precision_digits):
    try:
        if value_str is None or value_str == "": return Decimal(0)
        return Decimal(value_str).quantize(Decimal('1e-' + str(precision_digits)), rounding=ROUND_DOWN)
    except (InvalidOperation, Exception): return Decimal(0)

def format_decimal_for_api(decimal_value, precision_digits):
    return f"{decimal_value:.{precision_digits}f}"

def place_order(api_key, api_secret, base_url, symbol, side, qty_str, order_type, position_idx, stop_loss_str=None):
    endpoint = "/v5/order/create"
    params = {
        "category": "linear", "symbol": symbol, "side": side, "orderType": order_type,
        "qty": qty_str, "positionIdx": position_idx
    }
    if order_type == "Market": params["timeInForce"] = "ImmediateOrCancel"

    if stop_loss_str and quantize_value(stop_loss_str, PRICE_PRECISION) > 0:
        params["stopLoss"] = stop_loss_str
        params["tpslMode"] = "Full"

    sl_info = f", SL: {stop_loss_str}" if stop_loss_str else ", SL: N/A"
    log_and_print(f"Rendelés küldése: {symbol} {side} {qty_str}{sl_info}")
    data = make_request("POST", base_url + endpoint, api_key, api_secret, params)
    if data and data.get("retCode") == 0:
        order_id = data.get('result', {}).get('orderId', 'N/A')
        log_and_print(f">>> Sikeres rendelés. Demo Order ID: {order_id}")
        return order_id
    log_and_print(f"HIBA rendeléskor: {data}")
    return None

def set_position_tpsl(api_key, api_secret, base_url, symbol, position_idx, stop_loss_str):
    endpoint = "/v5/position/set-tpsl"
    params = {"category": "linear", "symbol": symbol, "positionIdx": position_idx, "tpslMode": "Full", "stopLoss": stop_loss_str}
    log_and_print(f"SL beállítása meglévő pozícióra ({symbol}): {stop_loss_str}")
    data = make_request("POST", base_url + endpoint, api_key, api_secret, params)
    if data and data.get("retCode") == 0:
        log_and_print(f">>> Sikeres SL beállítás a(z) {symbol} pozícióra.")
        return True
    log_and_print(f"HIBA SL beállításakor ({symbol}): {data}")
    return False

# --- Fő Szinkronizációs Logika ---
def sync_all_trades(live_api_key, live_api_secret, live_base_url, 
                    demo_api_key, demo_api_secret, demo_base_url, 
                    trade_state):
    
    log_and_print("-" * 50)
    live_positions = get_positions_from_account(live_api_key, live_api_secret, live_base_url, "Élő")
    demo_positions = get_positions_from_account(demo_api_key, demo_api_secret, demo_base_url, "Demó")

    live_pos_map = {f"{p['symbol']}-{p['side']}-{p.get('positionIdx', 0)}": p for p in live_positions}
    demo_pos_map = {f"{p['symbol']}-{p['side']}-{p.get('positionIdx', 0)}": p for p in demo_positions}
    new_state = trade_state.copy()

    # 1. LÉPÉS: Lezárt kereskedések kezelése
    closed_trade_keys = [key for key in new_state if key not in live_pos_map]
    if closed_trade_keys:
        log_and_print("\n--- Lezárt kereskedések kezelése ---")
        for key in closed_trade_keys:
            if key in demo_pos_map:
                demo_pos_to_close = demo_pos_map[key]
                log_and_print(f"'{key}' zárása a demó fiókon, mert az élőn már nem létezik.")
                place_order(demo_api_key, demo_api_secret, demo_base_url, demo_pos_to_close['symbol'], "Buy" if demo_pos_to_close['side'] == "Sell" else "Sell", demo_pos_to_close['size'], "Market", demo_pos_to_close.get('positionIdx', 0))
            del new_state[key]
            log_and_print(f"'{key}' eltávolítva az állapotból.")

    # 2. LÉPÉS: Új és aktív kereskedések szinkronizálása
    log_and_print("\n--- Új és aktív kereskedések ellenőrzése ---")
    for key, live_pos in live_pos_map.items():
        live_symbol = live_pos['symbol']
        live_side = live_pos['side']
        live_pos_idx = live_pos.get('positionIdx', 0)
        live_qty_decimal = quantize_value(live_pos.get("size", "0"), QTY_PRECISION)
        target_demo_qty_decimal = (live_qty_decimal * Decimal(str(COPY_MULTIPLIER))).quantize(MIN_QTY_THRESHOLD)
        if target_demo_qty_decimal < MIN_QTY_THRESHOLD: continue
        current_demo_qty_decimal = quantize_value(demo_pos_map.get(key, {}).get('size', '0'), QTY_PRECISION)
        last_copied_data = new_state.get(key, {})
        last_copied_live_qty = last_copied_data.get('live_qty', Decimal(0))
        
        # Eset: Új kereskedés
        if key not in new_state:
            log_and_print(f"\n>>> ÚJ KERESKEDÉS: {key}")
            target_demo_qty_str = format_decimal_for_api(target_demo_qty_decimal, QTY_PRECISION)
            
            sl_str = None
            market_price = get_market_price(live_symbol, demo_base_url, demo_api_key, demo_api_secret)
            if market_price:
                sl_price = calculate_sl_price(market_price, target_demo_qty_decimal, live_side, SL_LOSS_TIERS_USD, PRICE_PRECISION)
                if sl_price: sl_str = format_decimal_for_api(sl_price, PRICE_PRECISION)
            
            order_id = place_order(demo_api_key, demo_api_secret, demo_base_url, live_symbol, live_side, target_demo_qty_str, "Market", live_pos_idx, stop_loss_str=sl_str)
            if order_id: new_state[key] = {'live_qty': live_qty_decimal}

        # Eset: Meglévő kereskedés
        else:
            live_qty_diff = live_qty_decimal - last_copied_live_qty
            if live_qty_diff > 0:
                log_and_print(f"\n>>> POZÍCIÓ NÖVELÉSE: {key}")
                qty_to_add_demo = target_demo_qty_decimal - current_demo_qty_decimal
                if qty_to_add_demo >= MIN_QTY_THRESHOLD:
                    log_and_print(f"Kiegészítés mértéke: {qty_to_add_demo}")
                    qty_to_add_str = format_decimal_for_api(qty_to_add_demo, QTY_PRECISION)
                    order_id = place_order(demo_api_key, demo_api_secret, demo_base_url, live_symbol, live_side, qty_to_add_str, "Market", live_pos_idx)
                    if order_id:
                        log_and_print("Sikeres kiegészítés, SL újraszámítása a teljes pozícióra...")
                        time.sleep(2)
                        sl_str = None
                        market_price = get_market_price(live_symbol, demo_base_url, demo_api_key, demo_api_secret)
                        if market_price:
                            sl_price = calculate_sl_price(market_price, target_demo_qty_decimal, live_side, SL_LOSS_TIERS_USD, PRICE_PRECISION)
                            if sl_price:
                                sl_str = format_decimal_for_api(sl_price, PRICE_PRECISION)
                                set_position_tpsl(demo_api_key, demo_api_secret, demo_base_url, live_symbol, live_pos_idx, sl_str)
                        new_state[key] = {'live_qty': live_qty_decimal}
                else: log_and_print(f"Növekedés észlelve, de a demó méret már helyes. Nincs teendő. Kulcs: {key}")
            
            elif live_qty_diff < 0:
                log_and_print(f"\n>>> POZÍCIÓ CSÖKKENTÉSE: {key}")
                qty_to_close_demo = current_demo_qty_decimal - target_demo_qty_decimal
                if qty_to_close_demo >= MIN_QTY_THRESHOLD:
                    log_and_print(f"Zárandó mennyiség: {qty_to_close_demo}")
                    qty_to_close_str = format_decimal_for_api(qty_to_close_demo, QTY_PRECISION)
                    closing_side = "Buy" if live_side == "Sell" else "Sell"
                    order_id = place_order(demo_api_key, demo_api_secret, demo_base_url, live_symbol, closing_side, qty_to_close_str, "Market", live_pos_idx)
                    if order_id: new_state[key] = {'live_qty': live_qty_decimal}
                else: log_and_print(f"Csökkenés észlelve, de a demó méret már helyes. Nincs teendő. Kulcs: {key}")
    return new_state

# --- Fő Futási Logika ---
def main():
    log_and_print("="*60)
    log_and_print("Trade másoló indítása (Verzió: 8 - Részletes Naplózás)")
    log_and_print(f"Állapot fájl: {STATE_FILENAME}")
    
    trade_state = load_trade_state()

    try:
        while True:
            log_and_print("\n" + "="*60)
            log_and_print(f"Szinkronizációs ciklus indítása - {time.strftime('%Y-%m-%d %H:%M:%S')}")
            
            updated_state = sync_all_trades(
                API_KEY_LIVE, API_SECRET_LIVE, BASE_URL_LIVE,
                API_KEY_DEMO, API_SECRET_DEMO, BASE_URL_DEMO,
                trade_state
            )
            
            if updated_state != trade_state:
                log_and_print("\nÁllapot megváltozott, mentés...")
                save_trade_state(updated_state)
                trade_state = updated_state
            
            log_and_print(f"\nCiklus befejezve. Várakozás {LOOP_INTERVAL_SECONDS} másodpercet...")
            time.sleep(LOOP_INTERVAL_SECONDS)

    except KeyboardInterrupt:
        log_and_print("\nSzkript leállítva. Viszlát!")
    except Exception as e:
        log_and_print(f"\nKRITIKUS HIBA A FŐ CIKLUSBAN: {e}")
        logging.exception("Kritikus hiba:")

if __name__ == "__main__":
    main()
