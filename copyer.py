# FÁJL: copyer.py (Teljes, javított és véglegesített fájl)

import time
import logging
import multiprocessing
import configparser
import requests
from pathlib import Path
from datetime import datetime, timezone, timedelta  # JAVÍTVA: timedelta importálva
from modules.order_aggregator import OrderAggregator
from modules.order_handler import place_order_on_demo, set_leverage_on_demo
from decimal import Decimal
# Modul importok (a többi változatlan)
from modules.config_loader import load_configuration
from modules.logger_setup import setup_logging
from modules.state_manager import StateManager
from modules.reporting import ReportingManager
from modules.sync_logic import perform_initial_sync, main_event_loop
from modules.order_handler import check_and_set_sl, close_all_demo_positions
from modules.api_handler import get_data
from modules.telegram_sender import send_telegram_message
from modules.sync_checker import execute_pending_sync_actions, check_positions_sync
from modules.telegram_formatter import format_cycle_summary

__version__ = "14.2.0 (Stabil Indítás)"

DATA_DIR = Path(__file__).resolve().parent / "data"
def process_aggregated_orders(orders, config, state_manager, reporting_manager, cycle_events):
    """Végrehajtja az aggregált megbízásokat."""
    from modules.order_handler import _determine_position_idx # Késleltetett import a körkörös hivatkozás elkerülésére

    logger.info(f"{len(orders)} db aggregált megbízás feldolgozása...")
    for order in orders:
        symbol = order['symbol']
        side = order['side']
        action = order['action']
        qty = order['qty']

        if qty <= 0: continue

        qty_str = f"{qty:.{config['settings']['qty_precision']}f}"

        if action == "OPEN":
            is_increase = order['is_increase']
            if not is_increase:
                live_pos_resp = get_data(config['live_api'], "/v5/position/list", {'category': 'linear', 'symbol': symbol})
                if live_pos_resp and live_pos_resp.get('list'):
                    live_pos = live_pos_resp['list'][0]
                    leverage = live_pos.get('leverage', '10')
                    set_leverage_on_demo(config, symbol, leverage)
                    time.sleep(0.5)

            pos_idx = _determine_position_idx(config, side)
            params = {'category': 'linear', 'symbol': symbol, 'side': side, 'qty': qty_str, 'reduceOnly': False, 'orderType': 'Market', 'positionIdx': pos_idx}
            if place_order_on_demo(config, params):
                state_manager.map_position(symbol, side)
                reporting_manager.update_activity_log("copy")
                cycle_events.append({'type': 'open', 'data': {'symbol': symbol, 'side': side, 'qty': qty_str, 'is_increase': is_increase}})

        elif action == "CLOSE":
            position_side = order['position_side_for_close']
            pos_idx = _determine_position_idx(config, position_side)
            params = {'category': 'linear', 'symbol': symbol, 'side': side, 'qty': qty_str, 'reduceOnly': True, 'orderType': 'Market', 'positionIdx': pos_idx}
            if place_order_on_demo(config, params):
                state_manager.remove_mapping(symbol, position_side)
                time.sleep(1.5)
                closed_pnl, daily_pnl = reporting_manager.get_pnl_update_after_close(config['demo_api'], symbol)
                cycle_events.append({'type': 'close', 'data': {'symbol': symbol, 'side': position_side, 'qty': qty_str, 'pnl': closed_pnl, 'daily_pnl': daily_pnl}})

        time.sleep(0.5)
def update_config_value(section, option, value):
    """Frissíti a config.ini fájl egy adott értékét."""
    try:
        config = configparser.ConfigParser()
        config.read('config.ini')
        if not config.has_section(section):
            config.add_section(section)
        config.set(section, option, str(value))
        with open('config.ini', 'w') as configfile:
            config.write(configfile)
        print(f"A config.ini sikeresen frissítve: {section}.{option} = {value}")
    except Exception as e:
        print(f"Hiba a config.ini frissítésekor: {e}")

def perform_interactive_setup(config_data):
    """Minden indításkor lefutó interaktív folyamatot kezel."""
    print("="*60 + "\nINTERAKTÍV INDÍTÁSI MENÜ\n" + "="*60)
    while True:
        choice = input("Szeretnél tiszta lappal indulni? [i/n]: ").lower()
        if choice in ['i', 'n']: break
        print("Érvénytelen válasz.")

    if choice == 'i':
        print("\n--- TISZTA LAP FOLYAMAT ELINDULT ---")
        close_all_demo_positions(config_data)
        
        print("Adatfájlok törlése...")
        files_to_keep = ["live_chart_data.json"]
        for item in DATA_DIR.glob('**/*'):
            if item.is_file() and item.name not in files_to_keep:
                try: 
                    item.unlink()
                    print(f"  - Törölve: {item}")
                except OSError as e: 
                    print(f"  - Hiba a(z) {item} törlésekor: {e}")
        
        input("\nA nullázás kész. Nyomj Entert a folytatáshoz és a DemoStartDate beállításához...")
        
        print("\nBybit szerveridő lekérdezése...")
        try:
            response = requests.get("https://api.bybit.com/v5/market/time", timeout=10)
            response.raise_for_status()
            server_time_data = response.json()
            if server_time_data.get('retCode') == 0 and 'timeNano' in server_time_data.get('result', {}):
                server_time_ms = int(server_time_data['result']['timeNano']) // 1_000_000
                new_start_datetime = datetime.fromtimestamp(server_time_ms / 1000, tz=timezone.utc)
                new_start_date_str = new_start_datetime.strftime('%Y-%m-%d %H:%M:%S')
                print(f"Szerveridő sikeresen lekérve. Új DemoStartDate: {new_start_date_str}")
            else:
                raise ValueError("API válasz nem volt sikeres vagy nem tartalmazta a szükséges adatokat.")
        except Exception as e:
            print(f"Hiba: Szerveridő lekérdezése sikertelen ({e}). Helyi időt használunk.")
            new_start_date_str = (datetime.now(timezone.utc) + timedelta(seconds=5)).strftime('%Y-%m-%d %H:%M:%S')
        
        update_config_value('settings', 'DemoStartDate', new_start_date_str)
        config_data['settings']['demo_start_date'] = new_start_date_str
        
        print("--- KONFIGURÁCIÓ FRISSÍTVE ---\n")
    else:
        print("\nA program a meglévő adatokkal folytatja.\n")
# FÁJL: copyer.py - A teljes, javított main() funkció

def main():
    config_data = load_configuration()
    if not config_data:
        exit(1)
        
    perform_interactive_setup(config_data)

    setup_logging(config_data, log_dir=(DATA_DIR / "logs"))
    logger = logging.getLogger()
    
    try: 
        logger.info(f"TRADE MÁSOLÓ INDUL - Verzió: {__version__}")
        
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        sync_state_path = DATA_DIR / "sync_state.json"
        if sync_state_path.exists():
            try:
                sync_state_path.unlink()
                logger.info("Régi 'sync_state.json' fájl törölve az induláskor.")
            except OSError as e:
                logger.warning(f"Nem sikerült törölni a 'sync_state.json' fájlt: {e}")
        
        send_telegram_message(config_data, f"🚀 *Trade Másoló Indul*\nVerzió: `{__version__}`")
        
        bot_process = None
        if config_data.get('telegram', {}).get('bot_token'):
            from modules.telegram_bot import run_bot_process
            bot_process = multiprocessing.Process(target=run_bot_process, args=(config_data['telegram']['bot_token'], config_data, DATA_DIR), daemon=True)
            bot_process.start()
            logger.info(f"Bot processz elindítva (PID: {bot_process.pid}).")

        state_manager = StateManager(DATA_DIR)
        reporting_manager = ReportingManager(
            live_api=config_data['live_api'], demo_api=config_data['demo_api'],
            data_dir=DATA_DIR, version=__version__, config=config_data
        )
        
        order_aggregator = OrderAggregator()
        activity_since_last_pnl_update = True
        
        if state_manager.is_new_state():
            initial_events = []
            activity_since_last_pnl_update = perform_initial_sync(config_data, state_manager, reporting_manager, initial_events)
            if initial_events:
                summary_message = format_cycle_summary(initial_events, __version__)
                if summary_message:
                    send_telegram_message(config_data, summary_message)

        while True:
            cycle_events = []
            
            if bot_process and not bot_process.is_alive():
                logger.warning("A Telegram bot processz váratlanul leállt.")
                bot_process = None

            if execute_pending_sync_actions(config_data, state_manager, reporting_manager, DATA_DIR):
                activity_since_last_pnl_update = True

            logger.info("-" * 60)
            
            # Új események gyűjtése
            if main_event_loop(config_data, state_manager, cycle_events, order_aggregator):
                 activity_since_last_pnl_update = True

            # Aggregált megbízások feldolgozása
            ready_orders = order_aggregator.get_ready_orders()
            if ready_orders:
                process_aggregated_orders(ready_orders, config_data, state_manager, reporting_manager, cycle_events)
                activity_since_last_pnl_update = True

            # Riportok frissítése
            reporting_manager.update_reports(pnl_update_needed=activity_since_last_pnl_update)
            if activity_since_last_pnl_update:
                activity_since_last_pnl_update = False

            # SL beállítása
            demo_positions_response = get_data(config_data['demo_api'], "/v5/position/list", {'category': 'linear', 'settleCoin': 'USDT'})
            if demo_positions_response and demo_positions_response.get('list'):
                for pos in demo_positions_response['list']:
                    if float(pos.get('size', '0')) > 0:
                        sl_event = check_and_set_sl(pos, config_data)
                        if sl_event:
                            cycle_events.append({'type': 'sl', 'data': sl_event})
                        time.sleep(0.3)

            # Szinkron ellenőrzés
            check_positions_sync(config_data, DATA_DIR)

            # Ciklus végi összefoglaló küldése
            if cycle_events:
                summary_message = format_cycle_summary(cycle_events, __version__)
                if summary_message:
                    send_telegram_message(config_data, summary_message)

            interval = config_data['settings']['loop_interval']
            logger.info(f"--- Ciklus vége, várakozás {interval} másodpercet... ---")
            time.sleep(interval)
            
    except KeyboardInterrupt:
        logger.info("Program leállítva (Ctrl+C).")
        if 'config_data' in locals():
            send_telegram_message(config_data, "💤 *Trade Másoló Leállítva*")
    except Exception as e:
        logger.critical(f"Váratlan, végzetes hiba történt: {e}", exc_info=True)
        if 'config_data' in locals():
            send_telegram_message(config_data, f"💥 *KRITIKUS HIBA* 💥\n\nA program váratlan hiba miatt leállt:\n`{e}`")
    finally:
        if 'bot_process' in locals() and bot_process and bot_process.is_alive():
            logger.info("Bot processz leállítása a finally blokkban...")
            bot_process.terminate()
            bot_process.join()
        logger.info("Fő program leállt.")
if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()