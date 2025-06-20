# FÁJL: modules/sync_checker.py (Teljes, javított kód)

import logging
import time
from decimal import Decimal
from .api_handler import get_data
from .telegram_sender import send_telegram_message
from .order_handler import place_order_on_demo, _determine_position_idx

logger = logging.getLogger()

def _fix_discrepancies(config_data, discrepancies, pending_actions):
    """Végrehajtja a pozíciók közötti eltérések javítását, figyelembe véve a függőben lévő műveleteket."""
    if not discrepancies:
        return

    logger.info(f"Azonnali szinkronizáció végrehajtása {len(discrepancies)} db eltérésre...")
    send_telegram_message(config_data, f"⏳ Megkezdtem a fiókok azonnali szinkronizálását ({len(discrepancies)} db eltérés)...")
    
    time.sleep(2) 
    
    for d in discrepancies:
        symbol = d['symbol']
        side = d.get('side') 
        qty_precision = config_data['settings']['qty_precision']

        action_type_map = {
            'missing_on_demo': 'OPEN',
            'extra_on_demo': 'CLOSE',
        }
        required_action = action_type_map.get(d['type'])
        
        is_pending = False
        if required_action:
            is_pending = any(
                p['symbol'] == symbol and p['side'] == side and p['action'] == required_action
                for p in pending_actions
            )
        
        if is_pending:
            logger.info(f"Szinkronizációs javítás ({symbol}-{side} {required_action}) kihagyva, mert egy függőben lévő esemény kezeli.")
            continue

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


def check_positions_sync(config_data, state_manager, pending_actions=None):
    """
    Ellenőrzi a fiókok szinkronját, és ha eltérést talál, elindítja a javítást.
    Figyelembe veszi a függőben lévő, még nem végrehajtott műveleteket.
    """
    if pending_actions is None:
        pending_actions = []

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
    all_symbols = set(live_positions.keys()) | set(demo_positions.keys())

    for pos_id in all_symbols:
        live_pos = live_positions.get(pos_id)
        demo_pos = demo_positions.get(pos_id)
        symbol, side = pos_id.split('-')

        is_pending_open = any(p['symbol'] == symbol and p['side'] == side and p['action'] == 'OPEN' for p in pending_actions)
        is_pending_close = any(p['symbol'] == symbol and p['side'] == side and p['action'] == 'CLOSE' for p in pending_actions)

        if live_pos and not demo_pos:
            if is_pending_open:
                logger.info(f"Hiányzó demó pozíció ({pos_id}) észlelve, de a javítás kihagyva, mert egy függőben lévő OPEN esemény kezeli.")
                continue
            expected_demo_qty = (Decimal(live_pos['size']) * multiplier).quantize(Decimal('1e-' + str(qty_precision)))
            if expected_demo_qty > 0:
                discrepancies.append({"type": "missing_on_demo", "symbol": symbol, "side": side, "expected_demo_qty": f"{expected_demo_qty:.{qty_precision}f}"})
        
        elif not live_pos and demo_pos:
            if is_pending_close:
                logger.info(f"Extra demó pozíció ({pos_id}) észlelve, de a javítás kihagyva, mert egy függőben lévő CLOSE esemény kezeli.")
                continue
            discrepancies.append({"type": "extra_on_demo", "symbol": symbol, "side": side, "actual_demo_qty": demo_pos['size']})

        elif live_pos and demo_pos:
            # --- MÓDOSÍTÁS KEZDETE ---
            # Ha egyidejűleg van függőben lévő zárás és nyitás, az egy teljes pozíció-újraindítás.
            # Ilyenkor a sync checkernek nem szabad beavatkoznia a méreteltérésbe.
            is_pending_full_reset = is_pending_open and is_pending_close
            if is_pending_full_reset:
                logger.info(f"Méreteltérés ({pos_id}) észlelve, de a javítás kihagyva, mert egy teljes pozíció-újraindítás van folyamatban.")
                continue
            # --- MÓDOSÍTÁS VÉGE ---
            
            expected_demo_qty = (Decimal(live_pos['size']) * multiplier).quantize(Decimal('1e-' + str(qty_precision)))
            demo_qty = Decimal(demo_pos['size'])
            if abs(demo_qty - expected_demo_qty) > Decimal('1e-' + str(qty_precision)):
                 if is_pending_open or is_pending_close:
                     logger.info(f"Méreteltérés ({pos_id}) észlelve, de a javítás kihagyva, mert egy függőben lévő esemény kezeli.")
                     continue
                 discrepancies.append({"type": "size_mismatch", "symbol": symbol, "side": side, "expected_demo_qty": f"{expected_demo_qty:.{qty_precision}f}", "actual_demo_qty": f"{demo_qty:.{qty_precision}f}"})
    
    if discrepancies:
        _fix_discrepancies(config_data, discrepancies, pending_actions)
    else:
        logger.info("A fiókok tökéletes szinkronban vannak.")