# FÁJL: modules/sync_checker.py

import logging
import json
import time
from decimal import Decimal
from pathlib import Path
from datetime import datetime
# JAVÍTÁS: multiprocessing.Event importálása a típus-ellenőrzéshez
from multiprocessing import Event

from .api_handler import get_data
from .telegram_sender import send_telegram_document, send_telegram_message
from .order_handler import place_order_on_demo, _determine_position_idx

logger = logging.getLogger()

def _load_sync_state(sync_state_path):
    if not sync_state_path.exists(): 
        return {"waiting_for_reply": False, "discrepancies": [], "pending_action": None}
    try:
        with open(sync_state_path, 'r', encoding='utf-8') as f: 
            return json.load(f)
    except (json.JSONDecodeError, IOError): 
        return {"waiting_for_reply": False, "discrepancies": [], "pending_action": None}

def _save_sync_state(state, sync_state_path):
    try:
        with open(sync_state_path, 'w', encoding='utf-8') as f: 
            json.dump(state, f, indent=4)
    except IOError as e: 
        logger.error(f"Hiba a {sync_state_path} írása közben: {e}")

# JAVÍTÁS: A függvény most már megkapja a sync_trigger eseményt is
def check_positions_sync(config_data, data_dir, sync_trigger: Event):
    sync_state_path = data_dir / "sync_state.json"
    state = _load_sync_state(sync_state_path)
    if state.get("waiting_for_reply"):
        logger.info("Szinkronizációs ellenőrzés kihagyva, felhasználói válaszra vár...")
        return
        
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
        logger.warning(f"Szinkronizációs eltérés észlelve! Eltérések száma: {len(discrepancies)}")
        send_sync_issue_report(config_data, discrepancies, data_dir)
        state["waiting_for_reply"], state["discrepancies"] = True, discrepancies
        _save_sync_state(state, sync_state_path)
    else:
        logger.info("A fiókok tökéletes szinkronban vannak.")

def send_sync_issue_report(config_data, discrepancies, data_dir):
    report_path = data_dir / "sync_discrepancy_report.txt"
    report_content = f"Szinkronizációs Eltérés Jelentés - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n" + "=" * 40 + "\n\n"
    for d in discrepancies:
        report_content += f"Hiba: {d['type']} | Szimbólum: {d['symbol']} ({d['side']})\n"
        if 'expected_demo_qty' in d: report_content += f"  - Elvárt demó méret: {d['expected_demo_qty']}\n"
        if 'actual_demo_qty' in d: report_content += f"  - Jelenlegi demó méret: {d['actual_demo_qty']}\n"
        report_content += "\n"
    try:
        with open(report_path, 'w', encoding='utf-8') as f: f.write(report_content)
    except IOError as e: 
        logger.error(f"Nem sikerült írni a riportfájlt: {e}"); return
        
    caption = "‼️ *Szinkronizációs Hiba Észlelve* ‼️\n\nRészletek a csatolt fájlban. Mit tegyek?"
    buttons = [
        [{"text": "✅ Teljes Szinkronizálás", "callback_data": "sync_action:FULL_SYNC"}], 
        [{"text": "❌ Figyelmen Kívül Hagyás", "callback_data": "sync_action:IGNORE"}]
    ]
    send_telegram_document(config_data, report_path, caption, buttons)

# JAVÍTÁS: A függvény most már megkapja a sync_trigger eseményt
def handle_sync_action(action: str, config_data: dict, data_dir: Path, sync_trigger: Event):
    sync_state_path = data_dir / "sync_state.json"
    logger.info(f"Felhasználói szinkronizációs parancs érkezett: {action}")
    state = _load_sync_state(sync_state_path)
    
    if action == "IGNORE":
        message = "👌 Rendben, az eltérések figyelmen kívül hagyva a következő ellenőrzésig."
        state = {"waiting_for_reply": False, "discrepancies": [], "pending_action": None}
    elif action == "FULL_SYNC":
        message = "⚙️ Rendben, a teljes szinkronizálás a következő ciklus elején elindul."
        state["waiting_for_reply"] = False
        state["pending_action"] = "FULL_SYNC"
        
    _save_sync_state(state, sync_state_path)
    send_telegram_message(config_data, message)

    # JAVÍTÁS: Jelzés a fő ciklusnak, hogy azonnal induljon
    if sync_trigger:
        logger.info("Azonnali ciklusindítás jelzése a fő processznek...")
        sync_trigger.set()

def execute_pending_sync_actions(config_data, state_manager, reporting_manager, data_dir):
    sync_state_path = data_dir / "sync_state.json"
    state = _load_sync_state(sync_state_path)
    if not state.get("pending_action"): return False

    action = state.get("pending_action")
    discrepancies = state.get("discrepancies", [])
    logger.info(f"Függőben lévő szinkronizációs művelet végrehajtása: {action}")
    
    if action == "FULL_SYNC":
        send_telegram_message(config_data, "⏳ Megkezdtem a fiókok teljes szinkronizálását...")
        
        for d in discrepancies:
            symbol, side = d['symbol'], d['side']
            position_idx = _determine_position_idx(config_data, side)
            qty_precision = config_data['settings']['qty_precision']

            try:
                if d['type'] == 'extra_on_demo':
                    params = {'category': 'linear', 'symbol': symbol, 'side': 'Sell' if side == 'Buy' else 'Buy', 'qty': d['actual_demo_qty'], 'reduceOnly': True, 'positionIdx': position_idx, 'orderType': 'Market'}
                    place_order_on_demo(config_data, params)

                elif d['type'] == 'missing_on_demo':
                    params = {'category': 'linear', 'symbol': symbol, 'side': side, 'qty': d['expected_demo_qty'], 'reduceOnly': False, 'positionIdx': position_idx, 'orderType': 'Market'}
                    place_order_on_demo(config_data, params)
                
                elif d['type'] == 'size_mismatch':
                    expected_qty = Decimal(d['expected_demo_qty'])
                    actual_qty = Decimal(d['actual_demo_qty'])
                    delta = expected_qty - actual_qty
                    
                    if abs(delta) < Decimal('1e-' + str(qty_precision)):
                        continue

                    trade_side = side if delta > 0 else ('Sell' if side == 'Buy' else 'Buy')
                    trade_qty = abs(delta)
                    reduce_only = delta < 0

                    params = {'category': 'linear', 'symbol': symbol, 'side': trade_side, 'qty': f"{trade_qty:.{qty_precision}f}", 'reduceOnly': reduce_only, 'positionIdx': position_idx, 'orderType': 'Market'}
                    place_order_on_demo(config_data, params)

                time.sleep(1.5)

            except Exception as e:
                logger.error(f"Hiba a {symbol}-{side} szinkronizálása közben: {e}", exc_info=True)
                send_telegram_message(config_data, f"❌ Hiba a(z) {symbol}-{side} szinkronizálása közben: {e}")

    _save_sync_state({"waiting_for_reply": False, "discrepancies": [], "pending_action": None}, sync_state_path)
    logger.info("Függőben lévő szinkronizációs művelet befejezve.")
    send_telegram_message(config_data, "✅ A fiókok közötti szinkronizálás befejeződött.")
    return True