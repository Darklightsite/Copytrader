import time
import logging
from decimal import Decimal

from modules.api_handler import get_data
from modules.order_handler import place_order_on_demo, determine_position_idx
# JAVÍTÁS: Importálás az új, dedikált telegram_sender modulból
from modules.telegram_sender import send_telegram_message

MIN_ORDER_VALUE_USDT = 5.0

def perform_initial_sync(cfg, state_manager, reporting_manager):
    """Elvégzi a kezdeti szinkronizációt az élő és demó számlák között."""
    logger = logging.getLogger()
    logger.info("=" * 60)
    logger.info("KEZDETI SZINKRONIZÁCIÓ INDUL...")
    
    pos_params = {'category': 'linear', 'settleCoin': 'USDT'}
    live_positions = get_data(cfg['live_api'], "/v5/position/list", pos_params).get('list', [])
    demo_positions = get_data(cfg['demo_api'], "/v5/position/list", pos_params).get('list', [])
    
    live_pos_dict = {f"{p['symbol']}-{p['side']}": p for p in live_positions if float(p.get('size', '0')) > 0}
    demo_pos_dict = {f"{p['symbol']}-{p['side']}": p for p in demo_positions if float(p.get('size', '0')) > 0}
    
    logger.info(f"Élő pozíciók: {len(live_pos_dict)} db, Demó pozíciók: {len(demo_pos_dict)} db.")
    
    activity_in_sync = False
    for key, demo_pos in demo_pos_dict.items():
        if key not in live_pos_dict:
            activity_in_sync = True
            logger.info(f"[SYNC] Árva demó pozíció észlelve: {key}. Zárás...")
            close_params = {
                "category": "linear", "symbol": demo_pos['symbol'], 
                "side": "Sell" if demo_pos['side'] == "Buy" else "Buy", 
                "orderType": "Market", "qty": demo_pos['size'], 
                "positionIdx": determine_position_idx(cfg, demo_pos['side']), "reduceOnly": True
            }
            if place_order_on_demo(cfg, close_params, reporting_manager):
                time.sleep(3)
                closed_pnl, new_daily_pnl = reporting_manager.get_pnl_update_after_close(cfg['demo_api'], demo_pos['symbol'])
                pnl_msg = f"*PnL: ${closed_pnl:.2f}*" if closed_pnl is not None else "PnL nem elérhető"
                daily_pnl_msg = f"Napi PnL: ${new_daily_pnl:.2f}" if new_daily_pnl is not None else ""
                msg = f"🧹 *POZÍCIÓ ZÁRÁSA (Árva):*\n{demo_pos['symbol']} | {demo_pos['side']} | {demo_pos['size']}\n{pnl_msg}\n{daily_pnl_msg}"
                send_telegram_message(cfg, msg)

    for key, live_pos in live_pos_dict.items():
        min_qty_threshold = Decimal('1e-' + str(cfg['settings']['qty_precision']))
        expected_qty = (Decimal(live_pos['size']) * cfg['settings']['copy_multiplier']).quantize(min_qty_threshold)
        if expected_qty <= 0: continue

        demo_pos = demo_pos_dict.get(key)
        open_params = {"category": "linear", "symbol": live_pos['symbol'], "side": live_pos['side'], "orderType": "Market", "qty": str(expected_qty), "positionIdx": determine_position_idx(cfg, live_pos['side'])}
        
        if not demo_pos:
            activity_in_sync = True
            logger.info(f"  -> Hiányzik a demóról. Nyitás {expected_qty} mérettel...")
            if place_order_on_demo(cfg, open_params, reporting_manager): state_manager.map_position(live_pos['symbol'], live_pos['side'])
        elif Decimal(demo_pos['size']) != expected_qty:
            activity_in_sync = True
            logger.info(f"  -> Méreteltérés. Élő (szorozva): {expected_qty}, Demó: {demo_pos['size']}. Korrekció...")
            close_params = {"category": "linear", "symbol": demo_pos['symbol'], "side": "Sell" if demo_pos['side'] == "Buy" else "Buy", "orderType": "Market", "qty": demo_pos['size'], "positionIdx": determine_position_idx(cfg, demo_pos['side']), "reduceOnly": True}
            if place_order_on_demo(cfg, close_params, reporting_manager):
                time.sleep(1.5)
                if place_order_on_demo(cfg, open_params, reporting_manager): state_manager.map_position(live_pos['symbol'], live_pos['side'])
        else:
            logger.info(f"  -> Pozíció rendben, leképezés rögzítve.")
            state_manager.map_position(live_pos['symbol'], live_pos['side'])

    latest_exec = get_data(cfg['live_api'], "/v5/execution/list", {"category": "linear", "limit": 1}).get('list', [])
    if latest_exec: state_manager.set_last_id(latest_exec[0]['execId'])
    logger.info(f"Kezdő eseményazonosító beállítva: {state_manager.get_last_id()}"); logging.info("KEZDETI SZINKRONIZÁCIÓ BEFEJEZVE!"); logging.info("=" * 60)
    return activity_in_sync

def main_event_loop(cfg, state_manager, reporting_manager):
    """A fő eseményfigyelő ciklus, ami az új kötéseket keresi."""
    logger = logging.getLogger()
    activity_this_cycle = False
    last_known_id = state_manager.get_last_id()
    if not last_known_id: 
        logger.error("Nincs kezdő eseményazonosító, a ciklus nem tud elindulni.")
        return activity_this_cycle
    
    logger.info(f"Új kereskedési események keresése (utolsó ismert ID: {last_known_id})...")
    all_recent_fills = get_data(cfg['live_api'], "/v5/execution/list", {"category": "linear", "limit": 100}).get('list', [])
    if not all_recent_fills: 
        logger.info("Nem sikerült lekérni a kötéslistát, vagy a lista üres.")
        return activity_this_cycle

    new_fills_to_process = []
    for fill in all_recent_fills:
        if fill['execId'] == last_known_id: break
        new_fills_to_process.append(fill)
    
    if not new_fills_to_process: 
        logger.info("Nincs új esemény az utolsó feldolgozás óta.")
        return activity_this_cycle
    
    activity_this_cycle = True
    logger.info(f"{len(new_fills_to_process)} új esemény található. Feldolgozás...")
    min_qty_threshold = Decimal('1e-' + str(cfg['settings']['qty_precision']))

    for fill in reversed(new_fills_to_process):
        symbol, side, qty, closed_size, price = fill['symbol'], fill['side'], fill['execQty'], fill['closedSize'], float(fill['execPrice'])
        if cfg['settings']['symbols_to_copy'] and symbol not in cfg['settings']['symbols_to_copy']:
            logger.debug(f"Kötés kihagyva: {symbol} nem szerepel a listán.")
            continue
        
        logger.info(f"ESEMÉNY: {symbol} | Oldal: {side} | Mennyiség: {qty} | Zárt méret: {closed_size}")
        
        if float(closed_size) > 0:
            position_side = "Sell" if side == "Buy" else "Buy"
            if state_manager.is_position_mapped(symbol, position_side):
                demo_qty = (Decimal(closed_size) * cfg['settings']['copy_multiplier']).quantize(min_qty_threshold)
                logger.info(f"  -> Záró esemény. Demó zárása {demo_qty} mérettel...")
                params = { "category": "linear", "symbol": symbol, "side": side, "orderType": "Market", "qty": str(demo_qty), "positionIdx": determine_position_idx(cfg, position_side), "reduceOnly": True }
                if place_order_on_demo(cfg, params, reporting_manager): state_manager.remove_mapping(symbol, position_side)
            else: 
                logger.warning(f"Záró esemény egy NEM követett pozícióra ({symbol}-{position_side}). Kihagyva.")
        else:
            is_new_pos = not state_manager.is_position_mapped(symbol, side)
            demo_qty = (Decimal(qty) * cfg['settings']['copy_multiplier']).quantize(min_qty_threshold)
            if demo_qty == 0: 
                logger.warning(f"A szorzó és kerekítés után a másolandó mennyiség 0 lenne. Kihagyva.")
                continue
            
            if is_new_pos: 
                logger.info(f"  -> Új pozíció. Demó nyitása {demo_qty} mérettel...")
                state_manager.map_position(symbol, side)
            else: 
                logger.info(f"  -> Pozíció növelése. Demó növelése {demo_qty} mérettel...")
            
            params = { "category": "linear", "symbol": symbol, "side": side, "orderType": "Market", "qty": str(demo_qty), "positionIdx": determine_position_idx(cfg, side), "reduceOnly": False }
            if (float(demo_qty) * price) < MIN_ORDER_VALUE_USDT: 
                logger.warning(f"MEGBÍZÁS KIHAGYVA: Értéke ({float(demo_qty) * price:.2f} USDT) alacsonyabb mint {MIN_ORDER_VALUE_USDT} USDT.")
                continue
            
            place_order_on_demo(cfg, params, reporting_manager)
            
    state_manager.set_last_id(all_recent_fills[0]['execId'])
    logger.info(f"Állapot frissítve. Új utolsó esemény ID: {state_manager.get_last_id()}")
    return activity_this_cycle
