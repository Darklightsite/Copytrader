# FÁJL: modules/order_handler.py

import logging
import time
from decimal import Decimal
from .api_handler import get_data, make_api_request, get_instrument_info
# A hibát okozó "from .sync_logic import..." sor innen törölve

logger = logging.getLogger()

def _determine_position_idx(config_data, side):
    """Meghatározza a pozíciós indexet a config.ini beállításai alapján."""
    demo_mode = config_data.get('account_modes', {}).get('demo_mode', 'Oneway')
    if demo_mode.strip().capitalize() == 'Hedge':
        return 1 if side == 'Buy' else 2
    return 0

def set_leverage_on_demo(config_data, symbol: str, leverage: str):
    """Beállítja a tőkeáttételt a demó fiókon egy adott szimbólumra."""
    logger.info(f"Tőkeáttétel beállítása: {symbol} -> {leverage}x")
    params = {"category": "linear","symbol": symbol,"buyLeverage": leverage,"sellLeverage": leverage}
    response = make_api_request(config_data['demo_api'], "/v5/position/set-leverage", "POST", params)
    if response and response.get("retCode") == 0:
        logger.info(f"✅ Tőkeáttétel sikeresen beállítva: {symbol} -> {leverage}x")
        return True
    else:
        ret_msg = response.get('retMsg', 'Ismeretlen hiba') if response else "Nincs válasz"
        logger.error(f"❌ Tőkeáttétel beállítása sikertelen: {symbol}. Hiba: {ret_msg}")
        return False

def close_all_demo_positions(config_data):
    """Lekérdezi és lezárja az összes nyitott pozíciót a demó fiókon."""
    logger.info("Összes nyitott demó pozíció zárása...")
    params = {'category': 'linear', 'settleCoin': 'USDT'}
    positions_resp = get_data(config_data['demo_api'], "/v5/position/list", params)
    if not positions_resp or not positions_resp.get('list'):
        logger.info("Nem találhatóak nyitott demó pozíciók.")
        return
    for pos in positions_resp['list']:
        if float(pos.get('size', '0')) > 0:
            symbol, side, size = pos['symbol'], pos['side'], pos['size']
            pos_idx = _determine_position_idx(config_data, side)
            close_params = {'category': 'linear', 'symbol': symbol, 'orderType': 'Market', 'side': 'Sell' if side == 'Buy' else 'Buy', 'qty': size, 'reduceOnly': True, 'positionIdx': pos_idx}
            place_order_on_demo(config_data, close_params)
            time.sleep(0.5)

def place_order_on_demo(config_data, params):
    symbol = params.get('symbol', 'N/A')
    side = params.get('side', 'N/A')
    qty = params.get('qty', 'N/A')
    logger.info(f"MEGBÍZÁS KÜLDÉSE: {symbol} | {side} | {qty}")
    response = make_api_request(config_data['demo_api'], "/v5/order/create", "POST", params)
    if response and response.get("retCode") == 0:
        return True
    ret_msg = response.get('retMsg', "Ismeretlen hiba") if response else "Nincs válasz"
    logger.error(f"❌ MEGBÍZÁS SIKERTELEN! Hiba: {ret_msg}")
    return False

def check_and_set_sl(position, config_data):
    try:
        symbol, side, pos_idx = position['symbol'], position['side'], int(position.get('positionIdx', 0))
        size, entry_price = Decimal(position['size']), Decimal(position['avgPrice'])
        current_sl_price_str = position.get('stopLoss', '')
        sl_loss_tiers = config_data['settings']['sl_loss_tiers_usd']
        if size <= 0 or not sl_loss_tiers: return None

        if current_sl_price_str and float(current_sl_price_str) > 0:
            current_sl_price = Decimal(current_sl_price_str)
            current_loss_dist = abs(entry_price - current_sl_price)
            widest_pnl_target = Decimal(str(sl_loss_tiers[0]))
            if size > 0:
                widest_price_change = abs(widest_pnl_target) / size
                if current_loss_dist <= (widest_price_change * Decimal('1.1')):
                    return None

        instrument_info = get_instrument_info(config_data['demo_api'], symbol)
        if not instrument_info: return None
        tick_size = Decimal(instrument_info['priceFilter']['tickSize'])

        for target_pnl_loss_usd in sl_loss_tiers:
            target_pnl_loss = -abs(Decimal(str(target_pnl_loss_usd)))
            price_change_per_unit = abs(target_pnl_loss) / size
            ideal_sl_price = entry_price - price_change_per_unit if side == "Buy" else entry_price + price_change_per_unit
            rounding_mode = "ROUND_DOWN" if side == "Buy" else "ROUND_UP"
            new_sl_price_quantized = (ideal_sl_price / tick_size).quantize(Decimal('1'), rounding=rounding_mode) * tick_size
            if new_sl_price_quantized <= 0: continue
            sl_price_str = f"{new_sl_price_quantized:.{abs(tick_size.as_tuple().exponent)}f}"
            if current_sl_price_str == sl_price_str: continue

            body = {"category": "linear", "symbol": symbol, "positionIdx": pos_idx, "tpslMode": "Full", "stopLoss": sl_price_str, "slTriggerBy": "MarkPrice"}
            response = make_api_request(config_data['demo_api'], "/v5/position/trading-stop", "POST", body)
            
            if response and response.get("retCode") == 0:
                logger.info(f"✅ SL SIKERESEN BEÁLLÍTVA ({symbol}) -> {sl_price_str}")
                return {"symbol": symbol, "side": side, "pnl_value": target_pnl_loss_usd}
            elif response:
                ret_code, ret_msg = response.get("retCode"), response.get("retMsg", "").lower()
                if ret_code == 34040 or "not modified" in ret_msg: return None
                elif ret_code in [110043, 10001] or "too close" in ret_msg or "10_pcnt" in ret_msg:
                    time.sleep(0.5)
                    continue
                else:
                    logger.error(f"❌ SIKERTELEN SL MÓDOSÍTÁS ({symbol}): {ret_msg} (Kód: {ret_code}).")
                    return None
            else:
                 logger.error(f"❌ SIKERTELEN SL MÓDOSÍTÁS ({symbol}): Nincs válasz az API-tól.")
                 return None
        return None
    except Exception as e:
        logger.error(f"Hiba történt a(z) {position.get('symbol', 'Ismeretlen')} pozíció SL beállítása közben: {e}", exc_info=True)
        return None