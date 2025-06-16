import time
import logging
from decimal import Decimal, ROUND_DOWN, ROUND_UP

from modules.api_handler import make_api_request, get_instrument_info
# JAVÍTÁS: Importálás az új, dedikált telegram_sender modulból
from modules.telegram_sender import send_telegram_message

MIN_ORDER_VALUE_USDT = 5.0

def place_order_on_demo(cfg, params, reporting_manager):
    """Demó megbízás küldése és aktivitás naplózása."""
    logger = logging.getLogger()
    logger.info(f"MEGBÍZÁS KÜLDÉSE: {params}")
    response = make_api_request(cfg['demo_api'], "/v5/order/create", "POST", params)
    
    if response and response.get("retCode") == 0:
        msg = f"✅ MEGBÍZÁS SIKERES: {params.get('symbol')} {params.get('side')} {params.get('qty')}"
        logger.info(msg)
        if reporting_manager:
            reporting_manager.update_activity_log("copy")
        return True
    else:
        msg = response.get('retMsg', 'Ismeretlen hiba') if response else 'Nincs válasz'
        logger.error(f"❌ MEGBÍZÁS SIKERTELEN! Hiba: {msg}")
        return False

def determine_position_idx(cfg, side):
    """Meghatározza a pozíciós indexet a fiók módja alapján."""
    demo_mode = cfg.get('account_modes', {}).get('demo_mode', 'Oneway')
    if demo_mode == 'Hedge':
        return 1 if side == 'Buy' else 2
    return 0

def check_and_set_sl(position, cfg):
    """Ellenőrzi és beállítja a Stop-Losst egy adott pozíción."""
    logger = logging.getLogger()
    try:
        symbol, side, pos_idx = position['symbol'], position['side'], int(position.get('positionIdx', 0))
        size, entry_price = Decimal(position['size']), Decimal(position['avgPrice'])
        current_sl_price_str = position.get('stopLoss', '')
        current_sl_price = Decimal(current_sl_price_str) if current_sl_price_str and current_sl_price_str != "0" else None
        sl_loss_tiers = cfg['settings']['sl_loss_tiers_usd']
        
        if size <= 0 or not sl_loss_tiers: return

        instrument_info = get_instrument_info(cfg['live_api'], symbol)
        if not instrument_info: return
        tick_size = Decimal(instrument_info['priceFilter']['tickSize'])

        if current_sl_price is not None:
            widest_target_loss_usd = Decimal(str(sl_loss_tiers[0]))
            widest_price_change = abs(widest_target_loss_usd) / size
            widest_target_sl = entry_price - widest_price_change if side == 'Buy' else entry_price + widest_price_change
            
            current_loss_distance = abs(entry_price - current_sl_price)
            widest_target_distance = abs(entry_price - widest_target_sl)

            if current_loss_distance <= (widest_target_distance * Decimal('1.1')):
                logger.debug(f"SL ({symbol}): A manuális SL ({current_sl_price_str}) a 10%-os tűrésen belül van. Nincs teendő.")
                return

        for target_pnl_loss_usd in sl_loss_tiers:
            target_pnl_loss = -abs(Decimal(str(target_pnl_loss_usd)))
            price_change_per_unit = abs(target_pnl_loss) / size
            ideal_sl_price = entry_price - price_change_per_unit if side == "Buy" else entry_price + price_change_per_unit
            rounding_mode = ROUND_DOWN if side == "Buy" else ROUND_UP
            new_sl_price_quantized = (ideal_sl_price / tick_size).quantize(Decimal('1'), rounding=rounding_mode) * tick_size
            
            if new_sl_price_quantized <= 0:
                logger.debug(f"SL diagnosztika ({symbol}): Célveszteség=${target_pnl_loss_usd:.2f}, Számított SL érvénytelen (<=0). Kihagyva.")
                continue
            
            sl_price_str = f"{new_sl_price_quantized:.{abs(tick_size.as_tuple().exponent)}f}"
            
            if current_sl_price_str == sl_price_str:
                logger.debug(f"SL ({symbol}) már be van állítva a helyes {sl_price_str} értékre.")
                return

            logger.info(f"SL BEÁLLÍTÁS KÍSÉRLET: {symbol} | Célveszteség: ${target_pnl_loss_usd:.2f} | Cél SL ár: {sl_price_str}")
            body = {"category": "linear", "symbol": symbol, "positionIdx": pos_idx, "tpslMode": "Full", "stopLoss": sl_price_str, "slTriggerBy": "MarkPrice"}
            response = make_api_request(cfg['demo_api'], "/v5/position/trading-stop", "POST", body)
            
            if response and response.get("retCode") == 0:
                msg = f"✅ *SL SIKERESEN BEÁLLÍTVA ({symbol})*\nPozíció: {side}\nÚj SL ár: *{sl_price_str}*\n(Célveszteség: ~${target_pnl_loss_usd:.2f})"
                send_telegram_message(cfg, msg)
                return
            elif response:
                ret_code = response.get("retCode")
                ret_msg = response.get("retMsg", "").lower()
                if ret_code in [110043, 10001] or "too close" in ret_msg or "10_pcnt" in ret_msg:
                    logger.info(f"SL KÍSÉRLET ELUTASÍTVA ({symbol} - {sl_price_str}): {ret_msg}. Következő szint kipróbálása...")
                    time.sleep(0.5)
                    continue
                if "not modified" in ret_msg:
                    logger.debug(f"SL DIAGNOSZTIKA ({symbol}): A cél SL ({sl_price_str}) a(z) ${target_pnl_loss_usd:.2f} szinten már aktív.")
                    return
                logger.error(f"❌ SIKERTELEN SL MÓDOSÍTÁS ({symbol}): {ret_msg} (Kód: {ret_code}). További próbálkozás leállítva ennél a pozíciónál.")
                return
            else:
                 logger.error(f"❌ SIKERTELEN SL MÓDOSÍTÁS ({symbol}): Nincs válasz az API-tól.")
                 return
        
        logger.warning(f"{symbol}: Egyik SL szint sem volt sikeresen beállítható a Bybit API-n keresztül.")
    except Exception as e:
        logger.error(f"Hiba történt a(z) {position.get('symbol', 'Ismeretlen')} pozíció SL beállítása közben: {e}", exc_info=True)
