import time
import logging
import multiprocessing

# --- Modulok importálása a 'modules' mappából ---
from modules.config_loader import load_configuration
from modules.logger_setup import setup_logging
from modules.state_manager import StateManager
from modules.reporting import ReportingManager
from modules.sync_logic import perform_initial_sync, main_event_loop
from modules.order_handler import check_and_set_sl
from modules.api_handler import get_data
from modules.telegram_bot import run_bot_process, TELEGRAM_LIBS_AVAILABLE
from modules.telegram_sender import send_telegram_message

__version__ = "12.4.0 (Telegram Fix)"

def main():
    """A fő program belépési pontja."""
    
    config_data = load_configuration()
    if not config_data:
        exit(1)
    setup_logging(config_data)
    
    logger = logging.getLogger()
    logger.info(f"TRADE MÁSOLÓ INDUL - Verzió: {__version__}")
    send_telegram_message(config_data, f"🚀 *Trade Másoló Indul*\nVerzió: `{__version__}`")
    
    bot_process = None
    bot_token = config_data.get('telegram', {}).get('token')
    if TELEGRAM_LIBS_AVAILABLE and bot_token:
        bot_process = multiprocessing.Process(target=run_bot_process, args=(bot_token, config_data), daemon=True)
        bot_process.start()
        logger.info(f"Bot processz elindítva (PID: {bot_process.pid}).")
    else:
        logger.warning("A Telegram bot nem indul el (nincs token vagy hiányoznak a csomagok).")

    state_manager = StateManager()
    # Ez a hívás már a helyes, 4 argumentumot váró __init__-et célozza.
    reporting_manager = ReportingManager(config_data['live_api'], config_data['demo_api'], __version__)
    reporting_manager.update_activity_log("startup")
    
    activity_since_last_pnl_update = True 
    if state_manager.get_last_id() is None:
        activity_since_last_pnl_update = perform_initial_sync(config_data, state_manager, reporting_manager) or activity_since_last_pnl_update
        
    try:
        while True:
            if bot_process and not bot_process.is_alive():
                logger.error("A bot processz váratlanul leállt! A fő program tovább fut, de a bot nem fog válaszolni.")
                break 
            
            logger.info("-" * 60)
            
            cycle_activity = main_event_loop(config_data, state_manager, reporting_manager)
            activity_since_last_pnl_update = activity_since_last_pnl_update or cycle_activity

            reporting_manager.update_reports(pnl_update_needed=activity_since_last_pnl_update)
            if activity_since_last_pnl_update:
                activity_since_last_pnl_update = False

            demo_positions_response = get_data(config_data['demo_api'], "/v5/position/list", {'category': 'linear', 'settleCoin': 'USDT'})
            demo_positions_for_sl = demo_positions_response.get('list', []) if demo_positions_response else []

            if demo_positions_for_sl:
                logger.debug("SL beállítása a demó pozíciókon...")
                for pos in demo_positions_for_sl:
                    if float(pos.get('size', '0')) > 0:
                        check_and_set_sl(pos, config_data)
                        time.sleep(0.3)
            
            interval = config_data['settings']['loop_interval']
            logger.info(f"--- Ciklus vége, várakozás {interval} másodpercet... ---")
            time.sleep(interval)
            
    except KeyboardInterrupt:
        logger.info("Program leállítva (Ctrl+C).")
        send_telegram_message(config_data, "💤 Trade másoló program leállítva.")
    except Exception as e:
        logger.critical(f"Váratlan hiba a fő ciklusban: {e}", exc_info=True)
        send_telegram_message(config_data, f"💥 KRITIKUS HIBA!\nA program váratlan hiba miatt leállt.\nHiba: {e}")
    finally:
        if bot_process and bot_process.is_alive():
            logger.info("Bot processz leállítása...")
            bot_process.terminate()
            bot_process.join()
        logger.info("Fő program leállt.")

if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
