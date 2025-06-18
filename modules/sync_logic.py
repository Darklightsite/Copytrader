# FÁJL: modules/sync_logic.py

import time
import logging
from decimal import Decimal

from .api_handler import get_data
from .order_handler import place_order_on_demo, set_leverage_on_demo, _determine_position_idx

logger = logging.getLogger()

def perform_initial_sync(config_data, state_manager, reporting_manager, cycle_events):
    # ... (a függvény többi része változatlan) ...
    pass

def main_event_loop(config_data, state_manager, reporting_manager, cycle_events):
    # ... (a függvény többi része változatlan) ...
    pass

# A teljes, helyes kódot az előző válaszomban megtalálod, a lényeg a fenti
# "from .order_handler import..." sor, ami most már a _determine_position_idx-et is tartalmazza.
# A biztonság kedvéért itt van újra a teljes, helyes tartalom:

def perform_initial_sync(config_data, state_manager, reporting_manager, cycle_events):
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
        return False

    live_positions = {f"{p['symbol']}-{p['side']}": p for p in live_positions_resp.get('list', []) if float(p.get('size', '0')) > 0}
    demo_positions = {f"{p['symbol']}-{p['side']}": p for p in demo_positions_resp.get('list', []) if float(p.get('size', '0')) > 0}
    
    logger.info(f"Élő pozíciók: {len(live_positions)} db, Demó pozíciók: {len(demo_positions)} db.")

    for pos_id, demo_pos in demo_positions.items():
        if pos_id not in live_positions:
            activity_detected = True
            pos_idx = _determine_position_idx(config_data, demo_pos['side'])
            close_params = {'category': 'linear', 'symbol': demo_pos['symbol'], 'side': 'Sell' if demo_pos['side'] == 'Buy' else 'Buy', 'qty': demo_pos['size'], 'reduceOnly': True, 'positionIdx': pos_idx, 'orderType': 'Market'}
            place_order_on_demo(config_data, close_params)
            time.sleep(0.5)

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

def main_event_loop(config_data, state_manager, reporting_manager, cycle_events):
    activity_detected = False
    last_known_id = state_manager.get_last_id()
    if not last_known_id:
        return activity_detected

    recent_fills_data = get_data(config_data['live_api'], "/v5/execution/list", {"category": "linear", "limit": 100})
    if not recent_fills_data or not recent_fills_data.get('list'):
        return activity_detected

    recent_fills = recent_fills_data['list']
    new_fills_to_process = []
    for fill in recent_fills:
        if fill['execId'] == last_known_id: break
        new_fills_to_process.append(fill)

    if not new_fills_to_process:
        logger.info("Nincs új esemény az utolsó feldolgozás óta.")
        return activity_detected
        
    activity_detected = True
    multiplier = Decimal(str(config_data['settings']['copy_multiplier']))
    qty_precision = config_data['settings']['qty_precision']

    for fill in reversed(new_fills_to_process):
        symbol, side, exec_qty_str, closed_size_str = fill['symbol'], fill['side'], fill['execQty'], fill['closedSize']
        
        if config_data['settings'].get('symbols_to_copy') and symbol not in config_data['settings']['symbols_to_copy']:
            continue

        if float(closed_size_str) > 0:
            position_side = "Sell" if side == "Buy" else "Buy"
            if state_manager.is_position_mapped(symbol, position_side):
                demo_qty = (Decimal(closed_size_str) * multiplier).quantize(Decimal('1e-' + str(qty_precision)))
                pos_idx = _determine_position_idx(config_data, position_side)
                params = {'category': 'linear', 'symbol': symbol, 'side': side, 'qty': str(demo_qty), 'reduceOnly': True, 'orderType': 'Market', 'positionIdx': pos_idx}
                if place_order_on_demo(config_data, params):
                    state_manager.remove_mapping(symbol, position_side)
                    time.sleep(1.5)
                    closed_pnl, daily_pnl = reporting_manager.get_pnl_update_after_close(config_data['demo_api'], symbol)
                    cycle_events.append({'type': 'close', 'data': {'symbol': symbol, 'side': position_side, 'qty': str(demo_qty), 'pnl': closed_pnl, 'daily_pnl': daily_pnl}})
        else:
            is_increase = state_manager.is_position_mapped(symbol, side)
            if not is_increase:
                live_positions_resp = get_data(config_data['live_api'], "/v5/position/list", {'category': 'linear', 'symbol': symbol})
                if live_positions_resp and live_positions_resp.get('list'):
                    live_pos = live_positions_resp['list'][0]
                    leverage = live_pos.get('leverage', '10')
                    set_leverage_on_demo(config_data, symbol, leverage)
                    time.sleep(0.5)

            demo_qty = (Decimal(exec_qty_str) * multiplier).quantize(Decimal('1e-' + str(qty_precision)))
            if demo_qty <= 0: continue
            
            pos_idx = _determine_position_idx(config_data, side)
            params = {'category': 'linear', 'symbol': symbol, 'side': side, 'qty': str(demo_qty), 'reduceOnly': False, 'orderType': 'Market', 'positionIdx': pos_idx}
            if place_order_on_demo(config_data, params):
                state_manager.map_position(symbol, side)
                reporting_manager.update_activity_log("copy")
                cycle_events.append({'type': 'open', 'data': {'symbol': symbol, 'side': side, 'qty': str(demo_qty), 'is_increase': is_increase}})

    state_manager.set_last_id(recent_fills[0]['execId'])
    return activity_detected