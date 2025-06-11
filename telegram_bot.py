import configparser, json, logging, os
from pathlib import Path
from datetime import datetime, timedelta
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# --- Konfiguráció ---
SCRIPT_DIR = Path(__file__).resolve().parent
CONFIG_FILE = SCRIPT_DIR / "config.ini"
config = configparser.ConfigParser()
try:
    config.read(CONFIG_FILE, encoding='utf-8')
    TOKEN = config.get("telegram", "bot_token")
    STATUS_FILE = SCRIPT_DIR / config.get("files", "STATUS_FILE")
    # JAVÍTVA: A helyes fájlnév használata
    TRANSACTION_HISTORY_FILE = SCRIPT_DIR / config.get("files", "TRANSACTION_HISTORY_FILE")
except Exception as e:
    print(f"Hiba a config.ini beolvasásakor: {e}")
    exit()

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# --- PnL Számító Logika ---
def calculate_pnl_for_period(days):
    try:
        with open(TRANSACTION_HISTORY_FILE, 'r', encoding='utf-8') as f:
            history = json.load(f)
    except FileNotFoundError:
        return "Hiba: A `transaction_history.json` fájl még nem létezik. Várj egy ciklust, amíg a másoló létrehozza."
    except Exception as e:
        return f"Hiba az előzmények olvasásakor: {e}"

    now = datetime.now()
    if days > 0:
        start_date = now - timedelta(days=days)
    else: # A mai nap (naptári nap)
        start_date = now.replace(hour=0, minute=0, second=0, microsecond=0)

    total_pnl = 0.0
    pnl_types = ["TRADE", "SETTLEMENT", "FUNDING"]

    for trans in history:
        # A V5 Transaction Log a 'transactionTime' mezőt használja
        trans_time = datetime.fromtimestamp(int(trans.get('transactionTime', 0)) / 1000)
        if trans_time >= start_date and trans.get('type') in pnl_types:
            total_pnl += float(trans.get('change', 0))
            
    return f"${total_pnl:,.2f}"

# --- Parancsok ---
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "👋 Szia! Elérhető parancsok:\n\n"
        "`/status` - Működés és aktuális állapot\n"
        "`/pnl_daily` - Mai realizált PnL\n"
        "`/pnl_weekly` - Elmúlt 7 nap PnL\n"
        "`/pnl_monthly` - Elmúlt 30 nap PnL\n"
        "`/pnl_90d` - Elmúlt 90 nap PnL"
    )
    await update.message.reply_markdown(help_text)

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        with open(STATUS_FILE, 'r', encoding='utf-8') as f: status = json.load(f)
        reply = (
            f"✅ *A másoló program állapota:*\n\n"
            f"Frissítve: `{status.get('timestamp', 'N/A')}`\n"
            f"Élő egyenleg: *${status.get('live_balance', 0):,.2f}*\n"
            f"Demó egyenleg: *${status.get('demo_balance', 0):,.2f}*\n\n"
            f"Élő pozíciók: *{status.get('live_pos_count', 0)} db*\n"
            f"Demó megbízások (SL): *{status.get('sl_order_count', 0)} db* | Demó pozíciók: *{status.get('demo_pos_count', 0)} db*\n\n"
            f"📈 Élő PnL: *${float(status.get('live_pnl', 0)):,.2f}*\n"
            f"📉 Demó PnL: *${float(status.get('demo_pnl', 0)):,.2f}*"
        )
        await update.message.reply_markdown(reply)
    except FileNotFoundError:
        await update.message.reply_text("Hiba: A `status.json` fájl még nem jött létre.")
    except Exception as e:
        await update.message.reply_text(f"Hiba az állapot beolvasásakor: {e}")

async def pnl_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    command = update.message.text.strip()
    reply = "Ismeretlen parancs."
    
    if command == '/pnl_daily':
        pnl = calculate_pnl_for_period(days=0)
        reply = f"📅 *Mai realizált PnL (Élő):* {pnl}"
    elif command == '/pnl_weekly':
        pnl = calculate_pnl_for_period(days=7)
        reply = f"🗓️ *Heti realizált PnL (Élő):* {pnl}"
    elif command == '/pnl_monthly':
        pnl = calculate_pnl_for_period(days=30)
        reply = f"🈷️ *Havi realizált PnL (Élő):* {pnl}"
    elif command == '/pnl_90d':
        pnl = calculate_pnl_for_period(days=90)
        reply = f"📊 *90 Napos realizált PnL (Élő):* {pnl}"

    await update.message.reply_markdown(reply)

# --- Bot Indítása ---
def main():
    print("Telegram bot indítása...")
    application = Application.builder().token(TOKEN).build()
    application.add_handler(CommandHandler(["start", "help"], start_command))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(CommandHandler("pnl_daily", pnl_command))
    application.add_handler(CommandHandler("pnl_weekly", pnl_command))
    application.add_handler(CommandHandler("pnl_monthly", pnl_command))
    application.add_handler(CommandHandler("pnl_90d", pnl_command))
    print("A bot figyel... (A leállításhoz nyomj Ctrl+C-t)")
    application.run_polling()

if __name__ == '__main__':
    main()
