import configparser
import time
import requests
from decimal import Decimal, ROUND_DOWN, InvalidOperation
import hmac
from urllib.parse import urlencode

LOG_FILENAME = "copytrader.log"

# --- Config betöltése ---
config = configparser.ConfigParser()
config.read("config.ini")
try:
    API_KEY_LIVE = config.get("live", "API_KEY")
    API_SECRET_LIVE = config.get("live", "API_SECRET")
    API_KEY_DEMO = config.get("demo", "API_KEY")
    API_SECRET_DEMO = config.get("demo", "API_SECRET")
    QTY_PRECISION = config.getint("settings", "QTY_PRECISION", fallback=8)
    PRICE_PRECISION = config.getint("settings", "PRICE_PRECISION", fallback=2)
    COPY_MULTIPLIER = config.getfloat("settings", "COPY_MULTIPLIER", fallback=1.0)
    DEFAULT_SL_LOSS_USD = config.getfloat("settings", "DEFAULT_SL_LOSS_USD", fallback=10)
    LOOP_INTERVAL_SECONDS = config.getint("settings", "LOOP_INTERVAL_SECONDS", fallback=30)
    AUTO_CONFIRM = config.getboolean("settings", "AUTO_CONFIRM", fallback=False)
except Exception as e:
    print(f"HIBA: Config betöltési hiba: {e}")
    exit(1)

BASE_URL_LIVE = "https://api.bybit.com"
BASE_URL_DEMO = "https://api-demo.bybit.com"

MIN_QTY_THRESHOLD = Decimal('1e-' + str(QTY_PRECISION))

def log_and_print(msg):
    print(msg)
    try:
        with open(LOG_FILENAME, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}\n")
    except Exception:
        pass

def calculate_sl_price(entry_price, quantity, side, loss_usd, price_precision):
def calculate_sl_price(entry_price, quantity, side, loss_usd, price_precision):
    """
    Kiszámolja a stop loss árat a megadott PNL veszteséghez.
    Ha az SL szint nulla vagy negatív lenne, próbálja a loss_usd-t lépésenként 25-tel csökkenteni,
    amíg az SL pozitív nem lesz, vagy el nem éri a 0-át.
    """
    if quantity is None or quantity <= Decimal(0) or entry_price <= Decimal(0):
        log_and_print("Figyelem: Az SL számításhoz érvénytelen mennyiség vagy belépési ár.")
        return None
    try:
        min_loss_usd = 0
        loss_decimal = Decimal(str(loss_usd))
        price_precision_str = '1e-' + str(price_precision)
        while loss_decimal > Decimal(min_loss_usd):
            price_change = (loss_decimal / quantity).quantize(Decimal(price_precision_str), rounding=ROUND_DOWN)
            if side == "Buy":
                sl_price = entry_price - price_change
            elif side == "Sell":
                sl_price = entry_price + price_change
            else:
                return None
            if sl_price > Decimal(0):
                return sl_price.quantize(Decimal(price_precision_str), rounding=ROUND_DOWN)
            # Ha az SL nem megfelelő, csökkentsük a loss_usd-t 25-tel és próbáljuk újra
            loss_decimal -= Decimal('25')
        log_and_print(f"Figyelem: A számított SL többszöri próbálkozás után is nulla vagy negatív lenne, ezért kihagyva.")
        return None
    except Exception as e:
        log_and_print(f"HIBA: SL ár számítása során hiba történt: {e}")
        return None

def quantize_value(value_str, precision_digits):
    """Egy stringként kapott számot Decimal-ként kvantál a megadott pontosságra."""
    try:
        if value_str is None or value_str == "":
            return Decimal(0)
        precision_str = '1e-' + str(precision_digits)
        return Decimal(value_str).quantize(Decimal(precision_str), rounding=ROUND_DOWN)
    except InvalidOperation:
        log_and_print(f"HIBA: Érvénytelen érték kvantáláshoz: '{value_str}', pontosság: {precision_digits}. 0-val tér vissza.")
        return Decimal(0)
    except Exception as e:
        log_and_print(f"HIBA: Érték kvantálása nem sikerült: '{value_str}', pontosság: {precision_digits}, hiba: {e}")
        try:
            return Decimal(str(float(value_str))).quantize(Decimal('1e-' + str(precision_digits)), rounding=ROUND_DOWN)
        except Exception:
            log_and_print(f"HIBA: Végső fallback kvantálás is sikertelen: '{value_str}'. 0-val tér vissza.")
            return Decimal(0)

def format_decimal_for_api(decimal_value, precision_digits):
    """Decimal értéket stringgé formáz az API számára megfelelő pontossággal."""
    return f"{decimal_value:.{precision_digits}f}"

def sign_request(api_key, api_secret, timestamp, method, endpoint, query_string=""):
    payload_data = query_string if query_string else ""
    payload = f"{timestamp}{api_key}5000{payload_data}"
    signature = hmac.new(api_secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    return signature

def check_api_connection(api_key, api_secret, base_url):
    log_and_print(f"API kapcsolat ellenőrzése: {base_url}...")
    endpoint = "/v5/user/query-api"
    url = base_url + endpoint
    timestamp = str(int(time.time() * 1000))
    sign = sign_request(api_key, api_secret, timestamp, "GET", endpoint)
    headers = {
        "X-BAPI-API-KEY": api_key, "X-BAPI-SIGN": sign,
        "X-BAPI-TIMESTAMP": timestamp, "X-BAPI-RECV-WINDOW": "5000"
    }
    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        data = response.json()
        if data.get("retCode") == 0:
            log_and_print(f"API kapcsolat sikeres: {base_url}")
            return True
        else:
            log_and_print(f"API kapcsolat hiba ({base_url}): {data}")
            return False
    except requests.exceptions.RequestException as e:
        log_and_print(f"HIBA: API kapcsolat ellenőrzés ({base_url}) hálózati hiba: {e}")
        return False
    except Exception as e:
        log_and_print(f"HIBA: API kapcsolat ellenőrzés ({base_url}) általános hiba: {e}")
        return False

def get_positions_from_account(api_key, api_secret, base_url, account_name="Ismeretlen"):
    endpoint = "/v5/position/list"
    url = base_url + endpoint
    timestamp = str(int(time.time() * 1000))
    params = {"category": "linear", "settleCoin": "USDT"}
    query_string = urlencode(params)
    sign = sign_request(api_key, api_secret, timestamp, "GET", endpoint, query_string)
    headers = {
        "X-BAPI-API-KEY": api_key, "X-BAPI-SIGN": sign,
        "X-BAPI-TIMESTAMP": timestamp, "X-BAPI-RECV-WINDOW": "5000"
    }
    try:
        response = requests.get(url, headers=headers, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        if data.get("retCode") == 0 and "result" in data and "list" in data["result"]:
            return [pos for pos in data["result"]["list"] if quantize_value(pos.get("size", "0"), QTY_PRECISION) > Decimal(0)]
        else:
            log_and_print(f"Nem sikerült lekérni a pozíciókat ({account_name} számla): {data}")
            return []
    except requests.exceptions.RequestException as e:
        log_and_print(f"HIBA: Pozíciók lekérése ({account_name} számla) hálózati hiba: {e}")
        return []
    except Exception as e:
        log_and_print(f"HIBA: Pozíciók lekérése nem sikerült ({account_name} számla): {e}")
        return []

def get_market_price(symbol, base_url):
    url = f"{base_url}/v5/market/tickers?category=linear&symbol={symbol}"
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
        if data.get("retCode") == 0 and "result" in data and "list" in data["result"] and data["result"]["list"]:
            return quantize_value(data["result"]["list"][0]["markPrice"], PRICE_PRECISION)
        else:
            log_and_print(f"HIBA: Nem sikerült lekérni az árfolyamot {symbol}-hoz (válasz nem megfelelő): {data}")
            return None
    except requests.exceptions.RequestException as e:
        log_and_print(f"HIBA: Hálózati hiba az árfolyam lekérésekor {symbol}-hoz: {e}")
    except Exception as e:
        log_and_print(f"HIBA: Általános hiba az árfolyam lekérésekor {symbol}-hoz: {e}")
    return None

def place_order(api_key, api_secret, base_url, symbol, side, qty_str,
                price_str=None, order_type="Market", position_idx=0,
                take_profit_str=None, stop_loss_str=None,
                tp_trigger_by_str=None, sl_trigger_by_str=None,
                tpsl_mode_str=None):
    # Csak piaci megbízás engedélyezett
    if order_type != "Market":
        log_and_print(f"Csak piaci megbízások engedélyezettek. ({symbol})")
        return None

    endpoint = "/v5/order/create"
    url = base_url + endpoint
    timestamp = str(int(time.time() * 1000))

    body = {
        "category": "linear", "symbol": symbol, "side": side, "orderType": "Market",
        "qty": qty_str, "timeInForce": "GTC", "positionIdx": position_idx
    }

    if take_profit_str and quantize_value(take_profit_str, PRICE_PRECISION) > Decimal(0):
        body["takeProfit"] = take_profit_str
        if tp_trigger_by_str: body["tpTriggerBy"] = tp_trigger_by_str
        if tpsl_mode_str: body["tpslMode"] = tpsl_mode_str
    
    if stop_loss_str and quantize_value(stop_loss_str, PRICE_PRECISION) > Decimal(0):
        body["stopLoss"] = stop_loss_str
        if sl_trigger_by_str: body["slTriggerBy"] = sl_trigger_by_str
        if tpsl_mode_str and "tpslMode" not in body: body["tpslMode"] = tpsl_mode_str

    encoded_body = urlencode(body)
    sign = sign_request(api_key, api_secret, timestamp, "POST", endpoint, encoded_body)
    headers = {
        "X-BAPI-API-KEY": api_key, "X-BAPI-SIGN": sign, "X-BAPI-TIMESTAMP": timestamp,
        "X-BAPI-RECV-WINDOW": "5000", "Content-Type": "application/x-www-form-urlencoded"
    }
    try:
        response = requests.post(url, headers=headers, data=encoded_body, timeout=15)
        response.raise_for_status()
        data = response.json()
        price_info_log = "(Marketár)"
        tpsl_info_log = ""
        if "takeProfit" in body: tpsl_info_log += f", TP: {body['takeProfit']}"
        if "stopLoss" in body: tpsl_info_log += f", SL: {body['stopLoss']}"

        if data.get("retCode") == 0:
            order_id_info = data.get('result', {}).get('orderId', 'N/A')
            log_and_print(f"Sikeres Market rendelés: {symbol} {side} {qty_str} {price_info_log}{tpsl_info_log}. Demo Order ID: {order_id_info}")
            return order_id_info
        else:
            log_and_print(f"HIBA Market rendeléskor ({symbol} {side} {qty_str} {price_info_log}{tpsl_info_log}): {data}")
            return None
    except requests.exceptions.RequestException as e:
        log_and_print(f"HIBA Market rendelés küldésénél ({symbol}) hálózati hiba: {e}")
        return None
    except Exception as e:
        log_and_print(f"HIBA Market rendelés küldésénél ({symbol}): {e}")
        return None

def sync_open_positions(live_api_key, live_api_secret, live_base_url, demo_api_key, demo_api_secret, demo_base_url):
    log_and_print("Nyitott pozíciók szinkronizálása...")
    live_positions = get_positions_from_account(live_api_key, live_api_secret, live_base_url, "Élő")
    demo_positions = get_positions_from_account(demo_api_key, demo_api_secret, demo_base_url, "Demó")
    demo_pos_map = {(p["symbol"], p["side"], p.get("positionIdx", 0)): p for p in demo_positions}

    for live_pos in live_positions:
        live_symbol = live_pos["symbol"]
        live_side = live_pos["side"]
        live_pos_idx = live_pos.get("positionIdx", 0)
        
        live_qty_decimal = quantize_value(live_pos.get("size","0"), QTY_PRECISION)
        target_demo_qty_decimal = (live_qty_decimal * Decimal(str(COPY_MULTIPLIER))).quantize(MIN_QTY_THRESHOLD)

        live_tp_str = live_pos.get("takeProfit")
        live_tpsl_mode = live_pos.get("tpslMode", "Full")
        live_tp_trigger = live_pos.get("tpTriggerBy")
        live_sl_trigger = live_pos.get("slTriggerBy")

        current_demo_pos_obj = demo_pos_map.get((live_symbol, live_side, live_pos_idx))
        current_demo_qty_decimal = Decimal(0)
        if current_demo_pos_obj:
            current_demo_qty_decimal = quantize_value(current_demo_pos_obj.get("size","0"), QTY_PRECISION)

        qty_to_change_decimal = target_demo_qty_decimal - current_demo_qty_decimal
        
        if target_demo_qty_decimal < MIN_QTY_THRESHOLD:
            log_and_print(f"Cél demó mennyiség {live_symbol} ({live_side}) számára nulla vagy túl kicsi. Cleanup kezeli.")
            continue

        if abs(qty_to_change_decimal) >= MIN_QTY_THRESHOLD:
            log_and_print(f"\nPozíció igazítás: {live_symbol} ({live_side}) CélDemoQty: {target_demo_qty_decimal}, JelenlegiDemoQty: {current_demo_qty_decimal}, Változás: {qty_to_change_decimal}")
            
            action = "nyitása/növelése" if qty_to_change_decimal > 0 else "csökkentése"
            if not AUTO_CONFIRM:
                confirm = input(f"Biztosan {action} a pozíciót ({live_symbol} {live_side}) {abs(qty_to_change_decimal)} mérettel? (igen/nem): ")
                if confirm.lower() != "igen":
                    log_and_print("Pozíció igazítás kihagyva.")
                    continue
            
            qty_to_change_str = format_decimal_for_api(abs(qty_to_change_decimal), QTY_PRECISION)
            order_side_for_change = live_side if qty_to_change_decimal > 0 else ("Buy" if live_side == "Sell" else "Sell")

            # SL újraszámolás az átlagos nyitóárhoz képest!
            avg_entry_price = quantize_value(live_pos.get("entryPrice", "0"), PRICE_PRECISION)
            log_and_print(f"Átlagos nyitóár: {avg_entry_price} - ehhez képest számoljuk az SL-t.")

            calculated_sl_str = None
            if avg_entry_price > Decimal(0):
                sl_price_decimal = calculate_sl_price(
                    entry_price=avg_entry_price,
                    quantity=target_demo_qty_decimal,
                    side=order_side_for_change,
                    loss_usd=DEFAULT_SL_LOSS_USD,
                    price_precision=PRICE_PRECISION
                )
                if sl_price_decimal:
                    calculated_sl_str = format_decimal_for_api(sl_price_decimal, PRICE_PRECISION)
                    log_and_print(f"Számított SL ({live_symbol} {order_side_for_change}): ${calculated_sl_str}")
                else:
                    log_and_print(f"Figyelem: Nem sikerült SL-t számolni a {live_symbol} pozícióhoz.")
            else:
                log_and_print(f"HIBA: Nincs átlagos nyitóár {live_symbol}-hoz, SL beállítása kihagyva.")

            order_id = place_order(
                demo_api_key, demo_api_secret, demo_base_url,
                live_symbol, order_side_for_change, qty_to_change_str,
                order_type="Market",
                position_idx=live_pos_idx,
                take_profit_str=live_tp_str,
                stop_loss_str=calculated_sl_str,
                tp_trigger_by_str=live_tp_trigger,
                sl_trigger_by_str=live_sl_trigger,
                tpsl_mode_str=live_tpsl_mode
            )
            if order_id:
                log_and_print(f"Méret igazítva (Market orderrel). Demo Order ID: {order_id}")

def cleanup_demo_positions(live_api_key, live_api_secret, live_base_url, demo_api_key, demo_api_secret, demo_base_url):
    log_and_print("Demó pozíciók tisztítása...")
    live_positions = get_positions_from_account(live_api_key, live_api_secret, live_base_url, "Élő")
    demo_positions = get_positions_from_account(demo_api_key, demo_api_secret, demo_base_url, "Demó")
    live_pos_map = {} 
    for lp in live_positions:
        key = (lp["symbol"], lp["side"], lp.get("positionIdx", 0))
        live_qty = quantize_value(lp.get("size","0"), QTY_PRECISION)
        live_pos_map[key] = (live_qty * Decimal(str(COPY_MULTIPLIER))).quantize(MIN_QTY_THRESHOLD)

    for demo_pos in demo_positions:
        demo_symbol = demo_pos["symbol"]
        demo_side = demo_pos["side"]
        demo_pos_idx = demo_pos.get("positionIdx", 0)
        demo_key = (demo_symbol, demo_side, demo_pos_idx)
        
        current_demo_qty_decimal = quantize_value(demo_pos.get("size","0"), QTY_PRECISION)
        target_live_based_qty = live_pos_map.get(demo_key, Decimal(0))

        if current_demo_qty_decimal > target_live_based_qty:
            qty_to_close_decimal = current_demo_qty_decimal - target_live_based_qty
            if qty_to_close_decimal >= MIN_QTY_THRESHOLD:
                log_and_print(f"\nDemó pozíció csökkentése/zárása: {demo_symbol} ({demo_side}). Jelenlegi: {current_demo_qty_decimal}, Cél: {target_live_based_qty}, Zárandó: {qty_to_close_decimal}")
                if not AUTO_CONFIRM:
                    confirm = input(f"Demó pozíciót ({demo_symbol}) {qty_to_close_decimal} mérettel csökkenteni/zárni? (igen/nem): ")
                    if confirm.lower() != "igen":
                        log_and_print("Demó pozíció zárása/csökkentése kihagyva.")
                        continue
                qty_to_close_str = format_decimal_for_api(qty_to_close_decimal, QTY_PRECISION)
                closing_side = "Buy" if demo_side == "Sell" else "Sell"
                place_order(
                    demo_api_key, demo_api_secret, demo_base_url,
                    demo_symbol, closing_side, qty_to_close_str,
                    order_type="Market", position_idx=demo_pos_idx
                )

def main():
    log_and_print("Trade másoló indítása...")
    log_and_print(f"Log fájl: {LOG_FILENAME}")
    log_and_print(f"Másolási szorzó: {COPY_MULTIPLIER}")
    log_and_print(f"Automatikus Stop Loss: ${DEFAULT_SL_LOSS_USD} PNL")
    log_and_print(f"Szinkronizálási ciklus: {LOOP_INTERVAL_SECONDS} másodperc")
    log_and_print(f"Használt mennyiség pontosság: {QTY_PRECISION} tizedesjegy")
    log_and_print(f"Használt ár pontosság: {PRICE_PRECISION} tizedesjegy")

    if not check_api_connection(API_KEY_LIVE, API_SECRET_LIVE, BASE_URL_LIVE):
        log_and_print("HIBA: Élő API kapcsolat sikertelen.")
        return
    if not check_api_connection(API_KEY_DEMO, API_SECRET_DEMO, BASE_URL_DEMO):
        log_and_print("HIBA: Demó API kapcsolat sikertelen.")
        return

    while True:
        sync_open_positions(API_KEY_LIVE, API_SECRET_LIVE, BASE_URL_LIVE, API_KEY_DEMO, API_SECRET_DEMO, BASE_URL_DEMO)
        cleanup_demo_positions(API_KEY_LIVE, API_SECRET_LIVE, BASE_URL_LIVE, API_KEY_DEMO, API_SECRET_DEMO, BASE_URL_DEMO)
        log_and_print(f"Várakozás {LOOP_INTERVAL_SECONDS} másodpercet a következő ciklusig...")
        time.sleep(LOOP_INTERVAL_SECONDS)

if __name__ == "__main__":
    main()
