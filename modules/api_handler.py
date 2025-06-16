import time
import hmac
import hashlib
import requests
import json
import logging
from urllib.parse import urlencode

instrument_info_cache = {}

def make_api_request(api, endpoint, method="GET", params=None):
    """Általános API kérés küldő függvény, javított hibakezeléssel."""
    logger = logging.getLogger()
    params = params or {}
    timestamp = str(int(time.time() * 1000))
    # JAVÍTÁS: Az időkeret növelése a timestamp hibák elkerülésére
    recv_window = "30000" 
    headers = {'X-BAPI-API-KEY': api['key'], 'X-BAPI-TIMESTAMP': timestamp, 'X-BAPI-RECV-WINDOW': recv_window, 'Content-Type': 'application/json'}
    
    log_params = params.copy()
    if 'orderLinkId' in log_params: log_params['orderLinkId'] = '...'
    if 'cursor' in log_params and log_params['cursor'] not in [None, ""]:
        logger.debug(f"API Kérés: Method={method}, Endpoint={endpoint}, Params={log_params}")
    elif 'cursor' not in log_params:
        logger.debug(f"API Kérés: Method={method}, Endpoint={endpoint}, Params={log_params}")

    if method == "GET":
        query_string = urlencode(sorted(params.items()))
        to_sign = timestamp + api['key'] + recv_window + query_string
        url = f"{api['url']}{endpoint}?{query_string}" if query_string else f"{api['url']}{endpoint}"
        body_for_request = None
    else: # POST
        body_for_request = json.dumps(params)
        to_sign = timestamp + api['key'] + recv_window + body_for_request
        url = f"{api['url']}{endpoint}"
    
    headers['X-BAPI-SIGN'] = hmac.new(api['secret'].encode('utf-8'), to_sign.encode('utf-8'), hashlib.sha256).hexdigest()
    
    try:
        response = requests.request(method, url, headers=headers, data=body_for_request, timeout=20)
        logger.debug(f"API Válasz státuszkód: {response.status_code}, Válasz: {response.text[:200]}...")
        response.raise_for_status()
        response_data = response.json()
        
        # JAVÍTÁS: Mindig adjuk vissza a választ, hogy a hívó fél kezelhesse a hibakódokat
        if response_data.get('retCode') != 0:
            logger.warning(f"API Hiba ({method} {endpoint}): Code={response_data.get('retCode')}, Msg='{response_data.get('retMsg')}'")
        
        return response_data

    except requests.exceptions.RequestException as e:
        logger.error(f"Hálózati hiba az API kérés közben ({url}): {e}", exc_info=True)
        return None
    except Exception as e:
        logger.error(f"Általános hiba az API kérés közben ({url}): {e}", exc_info=True)
        return None

def get_data(api, endpoint, params=None):
    """Segédfüggvény a 'result' kinyeréséhez a GET kérésekből."""
    response = make_api_request(api, endpoint, "GET", params)
    return response.get('result', {}) if response and response.get('retCode') == 0 else {}

def get_instrument_info(live_api_config, symbol):
    """Lekéri és cache-eli az instrumentum információkat."""
    logger = logging.getLogger()
    if symbol in instrument_info_cache:
        return instrument_info_cache[symbol]
    
    params = {"category": "linear", "symbol": symbol}
    data = make_api_request(live_api_config, "/v5/market/instruments-info", "GET", params)
    
    if data and data.get("retCode") == 0 and data["result"].get("list"):
        info = data["result"]["list"][0]
        instrument_info_cache[symbol] = info
        return info
    
    logger.error(f"Nem sikerült lekérni az instrumentum információkat: {symbol}")
    return None

