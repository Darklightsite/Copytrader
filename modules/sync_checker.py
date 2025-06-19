# FÁJL: modules/sync_checker.py (Teljes, ellenőrzött kód)

import logging
import time
from decimal import Decimal
from pathlib import Path
from .api_handler import get_data
from .telegram_sender import send_telegram_message
from .order_handler import place_order_on_demo, _determine_position_idx

logger = logging.getLogger()

def _fix_discrepancies(config_data, discrepancies):
    """Végrehajtja a pozíciók közötti eltérések javítását."""
    logger.info(f"Azonnali szinkronizáció végrehajtása {len(discrepancies)} db eltérésre...")
    send_telegram_message(config_data, f"⏳ Megkezdtem a fiókok azonnali szinkronizálását ({len(discrepancies)} db eltérés)...")
    
    time.sleep(2) 
    
    for d in discrepancies:
        symbol = d['symbol']
        side = d.get('side') 
        qty_precision = config_data['settings']['qty_precision']

        try:
            if d['type'] == 'extra_on_demo':
                if not side: continue
                pos_idx = _determine_position_idx(config_data, side)
                params = {'category': 'linear', 'symbol': symbol, 'side': 'Sell' if side == 'Buy' else 'Buy', 'qty': d['actual_demo_qty'], 'reduceOnly': True, 'positionIdx': pos_idx, 'orderType': 'Market'}
                place_order_on_demo(config_data, params)

            elif d['type'] == 'missing_on_demo':
                if not side: continue
                pos_idx = _determine_position_idx(config_data, side)
                params = {'category': 'linear', 'symbol': symbol, 'side': side, 'qty': d['expected_demo_qty'], 'reduceOnly': False, 'positionIdx': pos_idx, 'orderType': 'Market'}
                place_order_on_demo(config_data, params)
            
            elif d['type'] == 'size_mismatch':
                if not side: continue
                expected_qty = Decimal(d['expected_demo_qty'])
                actual_qty = Decimal(d['actual_demo_qty'])
                delta = expected_qty - actual_qty
                
                if abs(delta) < Decimal('1e-' + str(qty_precision)):
                    continue

                trade_side = side if delta > 0 else ('Sell' if side == 'Buy' else 'Buy')
                trade_qty = abs(delta)
                reduce_only = delta < 0
                
                pos_idx = _determine_position_idx(config_data, side)
                params = {'category': 'linear', 'symbol': symbol, 'side': trade_side, 'qty': f"{trade_qty:.{qty_precision}f}", 'reduceOnly': reduce_only, 'positionIdx': pos_idx, 'orderType': 'Market'}
                place_order_on_demo(config_data, params)

            time.sleep(1.5)

        except Exception as e:
            logger.error(f"Hiba a {symbol}-{side} szinkronizálása közben: {e}", exc_info=True)
            send_telegram_message(config_data, f"❌ Hiba a(z) {symbol}-{side} szinkronizálása közben: {e}")
    
    logger.info("Azonnali szinkronizációs művelet befejezve.")
    send_telegram_message(config_data, "✅ A fiókok közötti szinkronizálás befejeződött.")


def check_positions_sync(config_data, data_dir, state_manager, reporting_manager):
    """
    Ellenőrzi a fiókok szinkronját, és ha eltérést talál, azonnal elindítja a javítást.
    """
    logger.info("Fiókok szinkronjának ellenőrzése...")
    live_api, demo_api = config_data['live_api'], config_data['demo_api']
    multiplier = Decimal(str(config_data['settings']['copy_multiplier']))
    qty_precision = config_data['settings']['qty_precision']
    
    live_pos_resp = get_data(live_api, "/v5/position/list", {'category': 'linear', 'settleCoin': 'USDT'})
    demo_pos_resp = get_data(demo_api, "/v5/position/list", {'category': 'linear', 'settleCoin': 'USDT'})
    
    if live_pos_resp is None or demo_pos_resp is None:
        logger.error("A szinkron ellenőrzése sikertelen: nem sikerült lekérni a pozíciókat.")
        return

    live_positions = {f"{p['symbol']}-{p['side']}": p for p in live_pos_resp.get('list', []) if float(p.get('size', 0)) > 0}
    demo_positions = {f"{p['symbol']}-{p['side']}": p for p in demo_pos_resp.get('list', []) if float(p.get('size', 0)) > 0}
    
    discrepancies = []
    for pos_id, live_pos in live_positions.items():
        expected_demo_qty = (Decimal(live_pos['size']) * multiplier).quantize(Decimal('1e-' + str(qty_precision)))
        
        if pos_id in demo_positions:
            demo_qty = Decimal(demo_positions[pos_id]['size'])
            if abs(demo_qty - expected_demo_qty) > Decimal('1e-' + str(qty_precision)):
                discrepancies.append({"type": "size_mismatch", "symbol": live_pos['symbol'], "side": live_pos['side'], "expected_demo_qty": f"{expected_demo_qty:.{qty_precision}f}", "actual_demo_qty": f"{demo_qty:.{qty_precision}f}"})
        else:
            discrepancies.append({"type": "missing_on_demo", "symbol": live_pos['symbol'], "side": live_pos['side'], "expected_demo_qty": f"{expected_demo_qty:.{qty_precision}f}"})
    
    for pos_id, demo_pos in demo_positions.items():
        if pos_id not in live_positions:
            discrepancies.append({"type": "extra_on_demo", "symbol": demo_pos['symbol'], "side": demo_pos['side'], "actual_demo_qty": demo_pos['size']})
    
    if discrepancies:
        _fix_discrepancies(config_data, discrepancies)
    else:
        logger.info("A fiókok tökéletes szinkronban vannak.")