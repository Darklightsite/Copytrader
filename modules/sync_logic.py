# FÁJL: modules/sync_logic.py (Teljes, javított kód)

import time
import logging
from decimal import Decimal

from .api_handler import get_data
from .order_handler import place_order_on_demo, set_leverage_on_demo, _determine_position_idx

logger = logging.getLogger()

def perform_initial_sync(config_data, state_manager, reporting_manager, cycle_events):
    """
    A program indulásakor végzi el a kezdeti szinkronizációt.
    Beállítja a tőkeáttételt, szinkronizálja a pozíciókat és gyűjti az eseményeket.
    """
    logger.info("=" * 60)
    logger.info("KEZDETI SZINKRONIZÁCIÓ INDUL...")
    
    activity_detected = False
    live_api = config_data['live_api']
    multiplier = Decimal(str(config_data['settings']['copy_multiplier']))
    qty_precision = config_data['settings']['qty_precision']
    
    params = {'category': 'linear', 'settleCoin': 'USDT'}
    live_positions_resp = get_data(live_api, "/v5/position/list", params)
    demo_positions_resp = get_data(config_data['demo_api'], "/v5/position/list", params)

    if live_positions_resp is None or demo_positions_resp is None:
        logger.error("Kezdeti szinkron sikertelen: pozíciók lekérése sikertelen.")
        return False

    live_positions = {f"{p['symbol']}-{p['side']}": p for p in live_positions_resp.get('list', []) if float(p.get('size', '0')) > 0}
    demo_positions = {f"{p['symbol']}-{p['side']}": p for p in demo_positions_resp.get('list', []) if float(p.get('size', '0')) > 0}
    
    logger.info(f"Élő pozíciók: {len(live_positions)} db, Demó pozíciók: {len(demo_positions)} db.")

    # Extra pozíciók zárása a demón
    for pos_id, demo_pos in demo_positions.items():
        if pos_id not in live_positions:
            activity_detected = True
            pos_idx = _determine_position_idx(config_data, demo_pos['side'])
            close_params = {'category': 'linear', 'symbol': demo_pos['symbol'], 'side': 'Sell' if demo_pos['side'] == 'Buy' else 'Buy', 'qty': demo_pos['size'], 'reduceOnly': True, 'positionIdx': pos_idx, 'orderType': 'Market'}
            if place_order_on_demo(config_data, close_params):
                cycle_events.append({'type': 'close', 'data': {'symbol': demo_pos['symbol'], 'side': demo_pos['side'], 'qty': demo_pos['size'], 'pnl': None, 'daily_pnl': None}})
            time.sleep(0.5)

    # Hiányzó vagy méreteltéréses pozíciók korrekciója
    for pos_id, live_pos in live_positions.items():
        expected_qty = (Decimal(live_pos['size']) * multiplier).quantize(Decimal('1e-' + str(qty_precision)))
        pos_idx = _determine_position_idx(config_data, live_pos['side'])
        
        leverage = live_pos.get('leverage', '10')
        set_leverage_on_demo(config_data, live_pos['symbol'], leverage)
        time.sleep(0.5)

        open_params = {'category': 'linear', 'symbol': live_pos['symbol'], 'side': live_pos['side'], 'qty': str(expected_qty), 'reduceOnly': False, 'positionIdx': pos_idx, 'orderType': 'Market'}
        
        if pos_id in demo_positions:
            actual_qty = Decimal(demo_positions[pos_id]['size'])
            if abs(actual_qty - expected_qty) > Decimal('1e-' + str(qty_precision)):
                activity_detected = True
                close_params = {'category': 'linear', 'symbol': live_pos['symbol'], 'side': 'Sell' if live_pos['side'] == 'Buy' else 'Buy', 'qty': str(actual_qty), 'reduceOnly': True, 'positionIdx': pos_idx, 'orderType': 'Market'}
                place_order_on_demo(config_data, close_params)
                time.sleep(1)
                if place_order_on_demo(config_data, open_params):
                    cycle_events.append({'type': 'open', 'data': {'symbol': live_pos['symbol'], 'side': live_pos['side'], 'qty': str(expected_qty), 'is_increase': True}})
        else:
            activity_detected = True
            if place_order_on_demo(config_data, open_params):
                cycle_events.append({'type': 'open', 'data': {'symbol': live_pos['symbol'], 'side': live_pos['side'], 'qty': str(expected_qty), 'is_increase': False}})

        state_manager.map_position(live_pos['symbol'], live_pos['side'])
        time.sleep(1)

    try:
        recent_executions = get_data(live_api, "/v5/execution/list", {'category': 'linear', 'limit': 1})
        if recent_executions and recent_executions.get('list'):
            state_manager.set_last_id(recent_executions['list'][0]['execId'])
    except Exception as e:
        logger.error(f"Hiba a legfrissebb esemény ID lekérdezése közben: {e}", exc_info=True)
        state_manager.set_last_id("initial_sync_error")

    logger.info("KEZDETI SZINKRONIZÁCIÓ BEFEJEZVE!")
    return activity_detected

def main_event_loop(config_data, state_manager, order_aggregator):
    """
    A fő eseményfigyelő ciklus. Az új kötéseket keresi, és átadja őket
    az order_aggregator-nak. Visszaadja, hogy történt-e aktivitás, és
    az utolsó esemény ID-ját, amit a ciklus végén kell menteni.
    """
    logger.info("Új kereskedési események keresése...")
    last_known_id = state_manager.get_last_id()
    if not last_known_id:
        logger.warning("Nincs utolsó esemény ID, a ciklus kihagyva. Kezdeti szinkronra lehet szükség.")
        return False, None

    recent_fills_data = get_data(config_data['live_api'], "/v5/execution/list", {"category": "linear", "limit": 100})
    if not recent_fills_data or not recent_fills_data.get('list'):
        return False, None

    recent_fills = recent_fills_data['list']
    new_fills_to_process = []
    for fill in recent_fills:
        if fill['execId'] == last_known_id:
            break
        new_fills_to_process.append(fill)

    # JAVÍTÁS: Módosított visszatérési értékek a robusztus állapotkezeléshez
    if not new_fills_to_process:
        logger.info("Nincs új esemény az utolsó feldolgozás óta.")
        return False, None
        
    activity_detected = True
    # A legfrissebb esemény ID-ja, amit a hívó majd elment, ha a ciklus sikeres volt
    last_id_to_save = recent_fills[0]['execId']
    logger.info(f"{len(new_fills_to_process)} új esemény észlelve, átadva az aggregátornak. Új last_id jelölt: {last_id_to_save}")

    for fill in reversed(new_fills_to_process):
        symbol, side, exec_qty_str = fill['symbol'], fill['side'], fill['execQty']
        closed_size_str = fill.get('closedSize', '0')
        exec_type = fill.get('execType')

        if exec_type != 'Trade':
            logger.info(f"Esemény kihagyva: {symbol} ({exec_type}), nem Trade típusú.")
            continue
        
        # Szűrés a configban megadott szimbólumokra (ha van ilyen)
        if config_data['settings'].get('symbols_to_copy') and symbol not in config_data['settings']['symbols_to_copy']:
            continue

        # ZÁRÁS ESEMÉNY
        if float(closed_size_str) > 0:
            position_side = "Sell" if side == "Buy" else "Buy"
            if state_manager.is_position_mapped(symbol, position_side):
                fill_data = {
                    'symbol': symbol,
                    'side': side,  # A záró megbízás iránya (pl. Buy-al zárunk egy Sell pozíciót)
                    'qty': closed_size_str,
                    'action': 'CLOSE',
                    'position_side_for_close': position_side  # Az eredeti pozíció iránya
                }
                order_aggregator.add_fill(fill_data)
        # NYITÁS VAGY NÖVELÉS ESEMÉNY
        else:
            is_increase = state_manager.is_position_mapped(symbol, side)
            fill_data = {
                'symbol': symbol,
                'side': side,
                'qty': exec_qty_str,
                'action': 'OPEN',
                'is_increase': is_increase
            }
            order_aggregator.add_fill(fill_data)
    
    # JAVÍTÁS: Az ID mentését a fő ciklusra bízzuk, itt csak visszaadjuk
    return activity_detected, last_id_to_save