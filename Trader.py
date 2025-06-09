import time
import hmac
import hashlib
import requests
import logging
import configparser
from urllib.parse import urlencode
from decimal import Decimal, ROUND_DOWN, InvalidOperation

# --- Naplózás beállítása ---
LOG_FILENAME = "trade_copier.log"
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    filename=LOG_FILENAME,
    filemode='w'
)

def log_and_print(msg):
    print(msg)
    logging.info(msg)

# --- Config betöltése ---
config = configparser.ConfigParser()
try:
    config.read("test.ini")
    AUTO_CONFIRM = config.getboolean("settings", "AUTO_CONFIRM", fallback=False)
    DEFAULT_SL_LOSS_USD = config.getfloat("settings", "DEFAULT_SL_LOSS_USD", fallback=100.0)
    LOOP_INTERVAL_SECONDS = config.getint("settings", "LOOP_INTERVAL_SECONDS", fallback=60)
    API_KEY_LIVE = config.get("live", "API_KEY")
    API_SECRET_LIVE = config.get("live", "API_SECRET")
    API_KEY_DEMO = config.get("demo", "API_KEY")
    API_SECRET_DEMO = config.get("demo", "API_SECRET")
    QTY_PRECISION = config.getint("settings", "QTY_PRECISION", fallback=8)
    PRICE_PRECISION = config.getint("settings", "PRICE_PRECISION", fallback=2)
    COPY_MULTIPLIER = config.getfloat("settings", "COPY_MULTIPLIER", fallback=1.0)

except Exception as e:
    log_and_print(f"HIBA: Config betöltési hiba: {e}")
    exit(1)

BASE_URL_LIVE = "https://api.bybit.com"
BASE_URL_DEMO = "https://api-demo.bybit.com"

MIN_QTY_THRESHOLD = Decimal('1e-' + str(QTY_PRECISION))

def calculate_sl_price(entry_price, quantity, side, loss_usd, price_precision):
    """
    Kiszámolja a stop loss árat a megadott PNL veszteséghez.
    """
    if quantity is None or quantity <= Decimal(0) or entry_price <= Decimal(0):
        log_and_print("Figyelem: Az SL számításhoz érvénytelen mennyiség vagy belépési ár.")
        return None
    try:
        loss_decimal = Decimal(str(loss_usd))
        price_precision_str = '1e-' + str(price_precision)
        
        price_change = (loss_decimal / quantity).quantize(Decimal(price_precision_str), rounding=ROUND_DOWN)
        
        if side == "Buy":
            sl_price = entry_price - price_change
        elif side == "Sell":
            sl_price = entry_price + price_change
        else:
            return None

        if sl_price <= Decimal(0):
            log_and_print(f"Figyelem: A számított SL ({sl_price}) nulla vagy negatív lenne, ezért kihagyva.")
            return None
            
        return sl_price.quantize(Decimal(price_precision_str), rounding=ROUND_DOWN)
        
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

def get_limit_orders_from_account(api_key, api_secret, base_url, account_name="Ismeretlen"):
    endpoint = "/v5/order/realtime"
    url = base_url + endpoint
    timestamp = str(int(time.time() * 1000))
    params = {"category": "linear", "settleCoin": "USDT", "orderFilter": "Order"}
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
            return [
                order for order in data["result"]["list"]
                if order.get("orderType") == "Limit" and order.get("orderStatus") in ["New", "PartiallyFilled"]
            ]
        else:
            log_and_print(f"Nem sikerült lekérni a nyitott megbízásokat ({account_name} számla): {data}")
            return []
    except requests.exceptions.RequestException as e:
        log_and_print(f"HIBA: Nyitott megbízások lekérése ({account_name} számla) hálózati hiba: {e}")
        return []
    except Exception as e:
        log_and_print(f"HIBA: Nyitott megbízások lekérése nem sikerült ({account_name} számla): {e}")
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
                price_str=None, order_type="Limit", position_idx=0,
                take_profit_str=None, stop_loss_str=None,
                tp_trigger_by_str=None, sl_trigger_by_str=None,
                tpsl_mode_str=None):
    endpoint = "/v5/order/create"
    url = base_url + endpoint
    timestamp = str(int(time.time() * 1000))

    body = {
        "category": "linear", "symbol": symbol, "side": side, "orderType": order_type,
        "qty": qty_str, "timeInForce": "GTC", "positionIdx": position_idx
    }

    if order_type == "Limit":
        if price_str is None:
            log_and_print(f"HIBA: Limit order ({symbol}) leadásához kötelező ár megadása!")
            return None
        body["price"] = price_str
    elif order_type != "Market":
        log_and_print(f"HIBA: Ismeretlen order_type ({order_type}) a rendelés leadásakor: {symbol}")
        return None

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
        price_info_log = f"@ {price_str}" if order_type == "Limit" else "(Marketár)"
        tpsl_info_log = ""
        if "takeProfit" in body: tpsl_info_log += f", TP: {body['takeProfit']}"
        if "stopLoss" in body: tpsl_info_log += f", SL: {body['stopLoss']}"

        if data.get("retCode") == 0:
            order_id_info = data.get('result', {}).get('orderId', 'N/A')
            log_and_print(f"Sikeres {order_type} rendelés: {symbol} {side} {qty_str} {price_info_log}{tpsl_info_log}. Demo Order ID: {order_id_info}")
            return order_id_info
        else:
            log_and_print(f"HIBA {order_type} rendeléskor ({symbol} {side} {qty_str} {price_info_log}{tpsl_info_log}): {data}")
            return None
    except requests.exceptions.RequestException as e:
        log_and_print(f"HIBA {order_type} rendelés küldésénél ({symbol}) hálózati hiba: {e}")
        return None
    except Exception as e:
        log_and_print(f"HIBA {order_type} rendelés küldésénél ({symbol}): {e}")
        return None

def amend_order_on_demo(api_key, api_secret, base_url, symbol, order_id,
                        new_qty_str=None, take_profit_str=None, stop_loss_str=None,
                        tp_trigger_by_str=None, sl_trigger_by_str=None):
    endpoint = "/v5/order/amend"
    url = base_url + endpoint
    timestamp = str(int(time.time() * 1000))
    body = {"category": "linear", "symbol": symbol, "orderId": order_id}

    if new_qty_str: body["qty"] = new_qty_str
    
    body["takeProfit"] = take_profit_str if take_profit_str and quantize_value(take_profit_str, PRICE_PRECISION) > Decimal(0) else "0"
    body["stopLoss"] = stop_loss_str if stop_loss_str and quantize_value(stop_loss_str, PRICE_PRECISION) > Decimal(0) else "0"

    if tp_trigger_by_str and body["takeProfit"] != "0": body["tpTriggerBy"] = tp_trigger_by_str
    if sl_trigger_by_str and body["stopLoss"] != "0": body["slTriggerBy"] = sl_trigger_by_str
    
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
        if data.get("retCode") == 0:
            log_and_print(f"Sikeres order módosítás: {symbol}, ID: {order_id}, Qty: {body.get('qty', 'n/a')}, TP: {body.get('takeProfit')}, SL: {body.get('stopLoss')}")
            return data.get("result", {}).get("orderId")
        else:
            if data.get("retCode") == 110044 and "qty" not in body :
                 pass
            elif data.get("retCode") == 110007:
                 log_and_print(f"Order módosítás nem lehetséges, order nem található/teljesült ({symbol}, ID: {order_id}): {data}")
                 return "FILLED_OR_NOT_FOUND"
            else:
                 log_and_print(f"HIBA order módosításakor ({symbol}, ID: {order_id}): {data}")
            return None
    except requests.exceptions.RequestException as e:
        log_and_print(f"HIBA order módosítás API hívásnál ({symbol}, ID: {order_id}) hálózati hiba: {e}")
        return None
    except Exception as e:
        log_and_print(f"HIBA order módosítás API hívásnál ({symbol}, ID: {order_id}): {e}")
        return None

def cancel_order_on_demo(api_key, api_secret, base_url, symbol, order_id):
    endpoint = "/v5/order/cancel"
    url = base_url + endpoint
    timestamp = str(int(time.time() * 1000))
    body = {"category": "linear", "symbol": symbol, "orderId": order_id}
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
        if data.get("retCode") == 0:
            log_and_print(f"Sikeres order törlés: {symbol}, Order ID: {order_id}")
            return True
        else:
            if data.get("retCode") == 110007:
                log_and_print(f"Order törlés nem szükséges/lehetséges (nem található/már törölt/teljesült): {symbol}, ID: {order_id}")
                return True
            log_and_print(f"HIBA order törlésekor ({symbol}, ID: {order_id}): {data}")
            return False
    except requests.exceptions.RequestException as e:
        log_and_print(f"HIBA order törlés API hívásnál ({symbol}, ID: {order_id}) hálózati hiba: {e}")
        return False
    except Exception as e:
        log_and_print(f"HIBA order törlés API hívásnál ({symbol}, ID: {order_id}): {e}")
        return False

# --- Szinkronizációs függvények ---

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

            calculated_sl_str = None
            if qty_to_change_decimal > 0:
                log_and_print(f"Friss piaci ár lekérése {live_symbol} számára az SL számításhoz...")
                current_market_price = get_market_price(live_symbol, demo_base_url)

                if current_market_price and current_market_price > Decimal(0):
                    log_and_print(f"A jelenlegi piaci ár: {current_market_price}")
                    sl_price_decimal = calculate_sl_price(
                        entry_price=current_market_price,
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
                    log_and_print(f"HIBA: Nem sikerült lekérni a friss piaci árat {live_symbol}-hoz, SL beállítása kihagyva.")

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
        #else:
            #log_and_print(f"Demó pozíció mérete megegyezik: {live_symbol} ({live_side}).")

def sync_limit_orders(live_api_key, live_api_secret, live_base_url, demo_api_key, demo_api_secret, demo_base_url):
    log_and_print("Limit megbízások szinkronizálása...")
    live_orders = get_limit_orders_from_account(live_api_key, live_api_secret, live_base_url, "Élő")
    demo_orders = get_limit_orders_from_account(demo_api_key, demo_api_secret, demo_base_url, "Demó")
    demo_order_map = {}
    for do in demo_orders:
        key = (do["symbol"], do["side"], quantize_value(do.get("price","0"), PRICE_PRECISION), do.get("positionIdx", 0))
        demo_order_map[key] = do
    
    for live_order in live_orders:
        live_symbol = live_order["symbol"]
        live_side = live_order["side"]
        live_pos_idx = live_order.get("positionIdx", 0)
        live_qty_decimal = quantize_value(live_order.get("qty","0"), QTY_PRECISION)
        live_price_decimal = quantize_value(live_order.get("price","0"), PRICE_PRECISION)
        
        target_demo_qty_decimal = (live_qty_decimal * Decimal(str(COPY_MULTIPLIER))).quantize(MIN_QTY_THRESHOLD)

        live_tp_str = live_order.get("takeProfit")
        live_tp_trigger = live_order.get("tpTriggerBy")
        live_sl_trigger = live_order.get("slTriggerBy")
        
        if target_demo_qty_decimal < MIN_QTY_THRESHOLD:
            log_and_print(f"Cél demó mennyiség limit orderhez ({live_symbol}) nulla vagy túl kicsi. Cleanup kezeli.")
            continue

        calculated_sl_str = None
        if target_demo_qty_decimal > 0 and live_price_decimal > 0:
            sl_price_decimal = calculate_sl_price(
                entry_price=live_price_decimal,
                quantity=target_demo_qty_decimal,
                side=live_side,
                loss_usd=DEFAULT_SL_LOSS_USD,
                price_precision=PRICE_PRECISION
            )
            if sl_price_decimal:
                calculated_sl_str = format_decimal_for_api(sl_price_decimal, PRICE_PRECISION)

        current_demo_order_obj = demo_order_map.get((live_symbol, live_side, live_price_decimal, live_pos_idx))
        
        if current_demo_order_obj:
            demo_order_id = current_demo_order_obj["orderId"]
            current_demo_qty_decimal = quantize_value(current_demo_order_obj.get("qty","0"), QTY_PRECISION)
            demo_tp_str = current_demo_order_obj.get("takeProfit", "0")
            demo_sl_str = current_demo_order_obj.get("stopLoss", "0")

            live_tp_dec = quantize_value(live_tp_str if live_tp_str else "0", PRICE_PRECISION)
            demo_tp_dec = quantize_value(demo_tp_str if demo_tp_str else "0", PRICE_PRECISION)
            calculated_sl_dec = quantize_value(calculated_sl_str if calculated_sl_str else "0", PRICE_PRECISION)
            demo_sl_dec = quantize_value(demo_sl_str if demo_sl_str else "0", PRICE_PRECISION)

            needs_amend = False
            if current_demo_qty_decimal != target_demo_qty_decimal: needs_amend = True
            if live_tp_dec != demo_tp_dec or calculated_sl_dec != demo_sl_dec: needs_amend = True
            
            if needs_amend:
                log_and_print(f"\nLimit order módosítás: {live_symbol} ({live_side}) @ {live_price_decimal}, ID: {demo_order_id}")
                log_and_print(f"CélQty:{target_demo_qty_decimal}, JelenlegiQty:{current_demo_qty_decimal}")
                log_and_print(f"CélTP:{live_tp_str}, CélSL(számított):{calculated_sl_str}")

                if not AUTO_CONFIRM:
                    confirm = input(f"Biztosan módosítod a limit ordert ({live_symbol})? (igen/nem): ")
                    if confirm.lower() != "igen":
                        log_and_print("Order módosítás kihagyva.")
                        continue
                
                target_demo_qty_str = format_decimal_for_api(target_demo_qty_decimal, QTY_PRECISION)
                amend_result = amend_order_on_demo(
                    demo_api_key, demo_api_secret, demo_base_url, live_symbol, demo_order_id,
                    new_qty_str=target_demo_qty_str, 
                    take_profit_str=live_tp_str, 
                    stop_loss_str=calculated_sl_str,
                    tp_trigger_by_str=live_tp_trigger, 
                    sl_trigger_by_str=live_sl_trigger
                )
                if amend_result == "FILLED_OR_NOT_FOUND":
                    log_and_print(f"Order ({demo_order_id}) módosítása nem sikerült, mert teljesült/törlődött.")
            else:
                log_and_print(f"Limit order rendben: {live_symbol} ({live_side}) @ {live_price_decimal}")
        else: 
            log_and_print(f"\nÚj limit order: {live_symbol} ({live_side}) @ {live_price_decimal}, CélQty: {target_demo_qty_decimal}, TP: {live_tp_str}, SL(számított): {calculated_sl_str or 'N/A'}")

            if not AUTO_CONFIRM:
                confirm = input(f"Új limit order ({live_symbol}) létrehozása demón? (igen/nem): ")
                if confirm.lower() != "igen":
                    log_and_print("Új order létrehozása kihagyva.")
                    continue
            
            target_demo_qty_str = format_decimal_for_api(target_demo_qty_decimal, QTY_PRECISION)
            live_price_str_formatted = format_decimal_for_api(live_price_decimal, PRICE_PRECISION)
            place_order(
                demo_api_key, demo_api_secret, demo_base_url,
                live_symbol, live_side, target_demo_qty_str, live_price_str_formatted,
                order_type="Limit", position_idx=live_pos_idx,
                take_profit_str=live_tp_str, 
                stop_loss_str=calculated_sl_str,
                tp_trigger_by_str=live_tp_trigger, 
                sl_trigger_by_str=live_sl_trigger
            )

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

def cleanup_demo_limit_orders(live_api_key, live_api_secret, live_base_url, demo_api_key, demo_api_secret, demo_base_url):
    log_and_print("Demó limit megbízások tisztítása...")
    live_orders = get_limit_orders_from_account(live_api_key, live_api_secret, live_base_url, "Élő")
    demo_orders = get_limit_orders_from_account(demo_api_key, demo_api_secret, demo_base_url, "Demó")
    
    live_order_map = {}
    for lo in live_orders:
        key = (lo["symbol"], lo["side"], quantize_value(lo.get("price","0"), PRICE_PRECISION), lo.get("positionIdx", 0))
        live_order_map[key] = (quantize_value(lo.get("qty","0"), QTY_PRECISION) * Decimal(str(COPY_MULTIPLIER))).quantize(MIN_QTY_THRESHOLD)

    for demo_order in demo_orders:
        demo_symbol = demo_order["symbol"]
        demo_side = demo_order["side"]
        demo_pos_idx = demo_order.get("positionIdx", 0)
        demo_price_decimal = quantize_value(demo_order.get("price","0"), PRICE_PRECISION)
        demo_key = (demo_symbol, demo_side, demo_price_decimal, demo_pos_idx)
        
        target_live_based_qty = live_order_map.get(demo_key, Decimal(0))
        current_demo_qty_decimal = quantize_value(demo_order.get("qty","0"), QTY_PRECISION)

        if current_demo_qty_decimal > target_live_based_qty:
            qty_diff = current_demo_qty_decimal - target_live_based_qty
            if qty_diff >= MIN_QTY_THRESHOLD:
                if target_live_based_qty == Decimal(0):
                    log_and_print(f"\nDemó limit order törlése: {demo_symbol} ({demo_side}) @ {demo_price_decimal}, ID: {demo_order['orderId']}.")
                    if not AUTO_CONFIRM:
                        confirm = input(f"Biztosan törlöd a demó limit ordert ({demo_symbol})? (igen/nem): ")
                        if confirm.lower() != "igen":
                            log_and_print("Order törlés kihagyva.")
                            continue
                    cancel_order_on_demo(demo_api_key, demo_api_secret, demo_base_url, demo_symbol, demo_order["orderId"])
                else:
                    log_and_print(f"\nDemó limit order mennyiség csökkentése: {demo_symbol} ({demo_side}) @ {demo_price_decimal}.")
                    if not AUTO_CONFIRM:
                        confirm = input(f"Biztosan módosítod a demó limit ordert ({demo_symbol})? (igen/nem): ")
                        if confirm.lower() != "igen":
                            log_and_print("Order módosítás kihagyva.")
                            continue
                    new_qty_str = format_decimal_for_api(target_live_based_qty, QTY_PRECISION)
                    amend_order_on_demo(demo_api_key, demo_api_secret, demo_base_url, demo_symbol, demo_order["orderId"], new_qty_str=new_qty_str)

# --- Fő futás logika ---
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

    try:
        while True:
            log_and_print("\n" + "="*50)
            log_and_print(f"Szinkronizációs ciklus indítása - {time.strftime('%Y-%m-%d %H:%M:%S')}")
            log_and_print("="*50)
            
            sync_open_positions(API_KEY_LIVE, API_SECRET_LIVE, BASE_URL_LIVE, API_KEY_DEMO, API_SECRET_DEMO, BASE_URL_DEMO)
            sync_limit_orders(API_KEY_LIVE, API_SECRET_LIVE, BASE_URL_LIVE, API_KEY_DEMO, API_SECRET_DEMO, BASE_URL_DEMO)
            cleanup_demo_positions(API_KEY_LIVE, API_SECRET_LIVE, BASE_URL_LIVE, API_KEY_DEMO, API_SECRET_DEMO, BASE_URL_DEMO)
            cleanup_demo_limit_orders(API_KEY_LIVE, API_SECRET_LIVE, BASE_URL_LIVE, API_KEY_DEMO, API_SECRET_DEMO, BASE_URL_DEMO)
            
            log_and_print("\nSzinkronizációs ciklus befejezve.")
            log_and_print(f"Várakozás {LOOP_INTERVAL_SECONDS} másodpercet a következő ciklusig...")
            time.sleep(LOOP_INTERVAL_SECONDS)

    except KeyboardInterrupt:
        log_and_print("\nSzkript leállítva (KeyboardInterrupt). Viszlát!")
    except Exception as e:
        log_and_print(f"\nKRITIKUS HIBA A FŐ CIKLUSBAN: {e}")
        logging.exception("Kritikus hiba a fő ciklusban:")

if __name__ == "__main__":
    main()
