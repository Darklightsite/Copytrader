import asyncio
import logging

try:
    from telegram import Bot
    from telegram.error import TelegramError
    TELEGRAM_LIBS_AVAILABLE = True
except ImportError:
    TELEGRAM_LIBS_AVAILABLE = False

async def send_async(token, chat_id, message):
    """Aszinkron segédfüggvény az üzenetküldéshez, hibakezeléssel."""
    if not TELEGRAM_LIBS_AVAILABLE:
        return
        
    logger = logging.getLogger()
    try:
        bot = Bot(token=token)
        await bot.send_message(chat_id=chat_id, text=message, parse_mode='Markdown')
    except TelegramError as e:
        logger.error(f"Telegram API hiba az üzenetküldés során: {e}")
    except Exception as e:
        logger.error(f"Általános hiba az aszinkron Telegram üzenetküldés során: {e}")

def send_telegram_message(cfg, message):
    """
    Egyszerűsített, szinkron függvény Telegram üzenetek küldésére a program bármely részéből.
    
    Args:
        cfg (dict): A konfigurációs dictionary, ami tartalmazza a telegram tokent és chat ID-t.
        message (str): Az elküldendő üzenet.
    """
    logger = logging.getLogger()
    bot_token = cfg.get('telegram', {}).get('token')
    chat_id = cfg.get('telegram', {}).get('chat_id')

    if not bot_token or not chat_id:
        logger.debug("Telegram üzenet küldése kihagyva (nincs token vagy chat_id).")
        return

    try:
        # Új eseményhurkot hoz létre és futtatja az aszinkron feladatot.
        # Ez biztosítja a kompatibilitást a szinkron kódrészekkel.
        asyncio.run(send_async(bot_token, chat_id, message))
    except Exception as e:
        logger.error(f"Hiba a Telegram üzenetküldő asyncio.run hívásakor: {e}")

