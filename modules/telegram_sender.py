
import logging
import requests
import json
from pathlib import Path

logger = logging.getLogger()

def _get_telegram_config(config_data):
    """Belső segédfüggvény a Telegram konfiguráció kinyeréséhez."""
    token = config_data.get('telegram', {}).get('bot_token')
    chat_id = config_data.get('telegram', {}).get('chat_id')
    
    if not token or not chat_id:
        logger.debug("Telegram bot_token vagy chat_id hiányzik. Üzenetküldés kihagyva.") # 
        return None, None
    return token, chat_id

def send_telegram_message(config_data, message):
    """Egyszerű szöveges üzenetet küld a Telegramra."""
    token, chat_id = _get_telegram_config(config_data)
    if not token: return

    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {'chat_id': chat_id, 'text': message, 'parse_mode': 'Markdown'}
        response = requests.post(url, json=payload, timeout=10)
        response.raise_for_status()
    except Exception as e:
        logger.error(f"Telegram üzenet küldése sikertelen: {e}")

def send_telegram_document(config_data, document_path: Path, caption: str, buttons=None):
    """Fájlt (dokumentumot) küld a Telegramra, képaláírással és opcionális gombokkal."""
    token, chat_id = _get_telegram_config(config_data)
    if not token: return

    try:
        url = f"https://api.telegram.org/bot{token}/sendDocument"
        payload = {'chat_id': chat_id, 'caption': caption, 'parse_mode': 'Markdown'}

        if buttons: # 
            inline_keyboard = {"inline_keyboard": buttons}
            payload['reply_markup'] = json.dumps(inline_keyboard)

        with open(document_path, 'rb') as doc:
            files = {'document': (document_path.name, doc)}
            response = requests.post(url, data=payload, files=files, timeout=20)
        
        response.raise_for_status()
        logger.info(f"Dokumentum sikeresen elküldve a Telegramra: {document_path.name}") # 

    except FileNotFoundError:
        logger.error(f"A küldendő dokumentumfájl nem található: {document_path}")
    except Exception as e:
        logger.error(f"Hiba a Telegram dokumentum küldése közben: {e}", exc_info=True)
