# FÁJL: stabi.py (Végleges, javított verzió)
import logging
import configparser
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, JobQueue
import pytz # Szükséges az időzónához

# Naplózás beállítása
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

ADMIN_CHAT_ID = None

# Biztonsági funkció
def authorized_only(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        if not ADMIN_CHAT_ID or update.effective_user.id != ADMIN_CHAT_ID:
            logger.warning(f"Illetéktelen hozzáférési kísérlet: {update.effective_user.id}")
            return
        return await func(update, context, *args, **kwargs)
    return wrapper

@authorized_only
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Szia! A stabil bot sikeresen fut és csak neked válaszol.")

# A fő programrész
def main() -> None:
    global ADMIN_CHAT_ID
    config = configparser.ConfigParser()
    try:
        config.read('config.ini')
        token = config['telegram']['bot_token']
        ADMIN_CHAT_ID = int(config['telegram']['chat_id'])
    except (KeyError, ValueError) as e:
        logger.critical(f"HIBA a config.ini fájlban! Hiba: {e}")
        return

    logger.info(f"Bot indítása. Admin chat ID: {ADMIN_CHAT_ID}")

    # --- JAVÍTÁS KEZDETE: Időzóna kézi beállítása ---
    # Létrehozzuk a bot feladatütemezőjét (JobQueue).
    job_queue = JobQueue()
    # Kézzel beállítjuk az időzónáját a stabil UTC-re a hiba elkerülése érdekében.
    job_queue.scheduler.timezone = pytz.utc

    # Az Application-t már a kézileg beállított job_queue-val hozzuk létre.
    application = (
        Application.builder()
        .token(token)
        .job_queue(job_queue)
        .build()
    )
    # --- JAVÍTÁS VÉGE ---

    application.add_handler(CommandHandler("start", start_command))
    application.run_polling()

if __name__ == '__main__':
    main()