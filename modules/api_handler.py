
import time
import hmac
import hashlib
import json
import logging
import requests

logger = logging.getLogger()

def make_api_request(api_config, endpoint, method="POST", params=None):
    """Általános API kérést készít és küld a Bybit V5 API-hoz."""
    if params is None:
        params = {}
    
    timestamp = str(int(time.time() * 1000))
    recv_window = "20000"

    # A paramétereket ABC sorrendbe rendezzük a GET kéréseknél
    if method == "GET":
        query_string = "&".join([f"{k}={v}" for k, v in sorted(params.items())])
        data_to_sign = timestamp + api_config['api_key'] + recv_window + query_string # 
    else: # POST
        query_string = json.dumps(params)
        data_to_sign = timestamp + api_config['api_key'] + recv_window + query_string

    signature = hmac.new(
        bytes(api_config['api_secret'], "utf-8"),
        bytes(data_to_sign, "utf-8"),
        hashlib.sha256
    ).hexdigest()

    headers = {
        'X-BAPI-API-KEY': api_config['api_key'],
        'X-BAPI-TIMESTAMP': timestamp, # 
        'X-BAPI-RECV-WINDOW': recv_window,
        'X-BAPI-SIGN': signature,
        'Content-Type': 'application/json'
    }
    
    # Az URL-t dinamikusan, az api_config-ból vesszük.
    base_url = api_config.get('url', "https://api.bybit.com") # Alapértelmezett az élő 
    url = f"{base_url}{endpoint}"
    
    if method == "GET" and query_string:
        url += "?" + query_string # 

    try:
        if method == "GET":
            response = requests.get(url, headers=headers, timeout=10)
        else: # POST
            response = requests.post(url, headers=headers, data=query_string, timeout=10)
        
        response.raise_for_status()
        response_json = response.json()

        # Hibakód ellenőrzése a Bybit válaszában
        if response_json.get('retCode') != 0:
            logger.error(f"API hiba a(z) {endpoint} végponton ({base_url}): {response_json.get('retMsg')} (Kód: {response_json.get('retCode')})") # 
            # Visszaadjuk a teljes választ, hogy a hívó fél is kezelhesse a hibát
            return response_json
            
        return response_json

    except requests.exceptions.RequestException as e:
        logger.error(f"Hálózati hiba a(z) {endpoint} hívása közben ({url}): {e}")
        return None
    except json.JSONDecodeError:
        logger.error(f"JSON dekódolási hiba a(z) {endpoint} válaszában. Válasz: {response.text}") # 
        return None

def get_data(api_config, endpoint, params=None):
    """Egyszerűsített wrapper a GET kérésekhez, ami a 'result' részt adja vissza."""
    response = make_api_request(api_config, endpoint, method="GET", params=params)
    if response and response.get('retCode') == 0:
        return response.get('result', {})
    return None

def get_instrument_info(api_config, symbol):
    """Lekérdezi egy adott instrumentum (trading pair) adatait."""
    logger.debug(f"Instrumentum információk lekérdezése: {symbol}")
    params = {
        'category': 'linear',
        'symbol': symbol
    }
    instrument_data = get_data(api_config, "/v5/market/instruments-info", params=params)

    if instrument_data and instrument_data.get('list'):
        return instrument_data['list'][0]
    else:
        logger.error(f"Nem sikerült lekérni az instrumentum információkat ehhez: {symbol}")
        return None
        