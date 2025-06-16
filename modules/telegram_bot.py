import logging
import json
import io
import asyncio
from pathlib import Path
from datetime import datetime, timedelta, timezone

# A python-telegram-bot könyvtár szükséges elemei
try:
    from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
    from telegram.ext import Application, CommandHandler, ContextTypes, ConversationHandler, CallbackQueryHandler
    TELEGRAM_LIBS_AVAILABLE = True
except ImportError:
    TELEGRAM_LIBS_AVAILABLE = False
    # Ha a libek nem elérhetőek, létrehozunk dummy osztályokat, hogy a kód ne szálljon el hibával
    class Update: pass
    class ContextTypes:
        class DEFAULT_TYPE: pass

# A matplotlib könyvtár szükséges a grafikonok rajzolásához
try:
    import matplotlib
    matplotlib.use('Agg') # Nem interaktív backend, ami szerver oldalon fut
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    MATPLOTLIB_AVAILABLE = True
except ImportError:
    MATPLOTLIB_AVAILABLE = False

from modules.logger_setup import setup_logging

# --- Konstansok a fájlok eléréséhez ---
DATA_DIR = Path(__file__).resolve().parent.parent / "data"
STATUS_FILE_PATH = DATA_DIR / "status.json"
PNL_REPORT_FILE_PATH = DATA_DIR / "pnl_report.json"
ACTIVITY_FILE_PATH = DATA_DIR / "activity.json"
LIVE_CHART_FILE_PATH = DATA_DIR / "live_chart_data.json"
DEMO_CHART_FILE_PATH = DATA_DIR / "demo_chart_data.json"

def _linspace(start, stop, num):
    """Lineárisan elosztott pontokat generál két érték között."""
    if num < 2:
        return [start] if num == 1 else []
    step = (stop - start) / (num - 1)
    return [start + step * i for i in range(num)]

class TelegramBotManager:
    """
    Osztály, amely a Telegram bot összes interaktív logikáját, parancsait és
    beszélgetéseit kezeli. Külön processzben fut.
    """
    
    def __init__(self, token):
        if not TELEGRAM_LIBS_AVAILABLE:
            raise ImportError("A 'python-telegram-bot' csomag nincs telepítve.")
        self.token = token
        self.app = Application.builder().token(self.token).build()
        self.SELECT_PERIOD, self.SELECT_ACCOUNT = range(2)
        self._register_handlers()

    def _register_handlers(self):
        """Regisztrálja a parancs- és üzenetkezelőket a bothoz."""
        conv_handler = ConversationHandler(
            entry_points=[CommandHandler('chart', self.chart_start)],
            states={
                self.SELECT_PERIOD: [CallbackQueryHandler(self.select_period, pattern='^period_')],
                self.SELECT_ACCOUNT: [CallbackQueryHandler(self.select_account_and_generate, pattern='^account_'), CallbackQueryHandler(self.back_to_period, pattern='^back_to_period$')]
            },
            fallbacks=[CallbackQueryHandler(self.cancel, pattern='^cancel$'), CommandHandler('chart', self.chart_start)],
            per_message=False
        )
        self.app.add_handler(conv_handler)
        self.app.add_handler(CommandHandler(["start", "help"], self.start_command))
        self.app.add_handler(CommandHandler("status", self.status_command))
        self.app.add_handler(CommandHandler("pnl", self.pnl_command))
        self.app.add_handler(CommandHandler("livepnl", self.live_pnl_command))
        self.app.add_handler(CommandHandler("demopnl", self.demo_pnl_command))

    def run(self):
        """A bot futtatása (polling módban)."""
        logger = logging.getLogger()
        logger.info("Telegram bot processz indul...")
        try:
            self.app.run_polling()
        except Exception as e:
            logger.critical("KRITIKUS HIBA a Telegram bot processzben: %s", e, exc_info=True)
        logger.info("Telegram bot processz leállt.")

    def _load_json_file(self, file_path, default_data):
        """Biztonságos JSON fájl betöltő, hibakezeléssel."""
        logger = logging.getLogger()
        logger.debug(f"JSON fájl betöltése: {file_path}")
        if not file_path.exists():
            logger.warning(f"A(z) {file_path} fájl nem található."); return default_data
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            logger.error(f"Hiba a {file_path} olvasásakor: {e}", exc_info=True)
            return default_data

    def _format_pnl_report(self, report_data, status_data, account_filter=None):
        """Megformázza a PnL riportot a Telegram üzenet számára."""
        if not report_data: return "Nincsenek elérhető PnL adatok."
        timestamp = status_data.get('timestamp', 'Ismeretlen');
        header = f"📊 *PnL Jelentés (Realizált)* 📊\n_Adatok frissessége: {timestamp}_\n\n"
        table = ""

        def create_account_section(account_name, pnl_data, status_data):
            balance_key = "live_balance" if account_name == "Élő" else "demo_balance"
            balance = status_data.get(balance_key, 0.0)
            section = f"⦿ *{account_name} Számla* (Egyenleg: `${balance:,.2f}`)\n"
            start_date = pnl_data.get('start_date')
            section += f"_Számítás kezdete: {start_date}_\n" if start_date != "Nincs rögzített kereskedés" else "_Számítás kezdete: Nincs rögzített kereskedés_\n"
            periods = pnl_data.get('periods', {})
            period_order = ["Napi", "Heti", "Havi", "90 Napos", "Teljes"]
            for period_name in period_order:
                if period_name in periods:
                    data = periods[period_name]
                    pnl, count = data.get('pnl', 0.0), data.get('trade_count', 0)
                    section += f"  - {period_name}: `${pnl:,.2f}` ({count} trade)\n"
            return section + "\n"

        if account_filter == "Élő" or account_filter is None:
            if live_data := report_data.get("Élő"):
                table += create_account_section("Élő", live_data, status_data)
        if account_filter == "Demó" or account_filter is None:
            if demo_data := report_data.get("Demó"):
                table += create_account_section("Demó", demo_data, status_data)
        
        if not table:
            return header + (f"Nincsenek PnL adatok a(z) '{account_filter}' számlához." if account_filter else "Nincsenek PnL adatok egyik számlához sem.")
        return header + table

    async def _handle_error(self, update: Update, context: ContextTypes.DEFAULT_TYPE, command_name: str):
        """Általános hibakezelő a parancsokhoz."""
        logger = logging.getLogger()
        logger.error("Hiba a(z) /%s parancs feldolgozása közben: %s", command_name, context.error, exc_info=True)
        if update and update.message:
            await update.message.reply_text("Hoppá! Hiba történt a parancs végrehajtása közben. A részletekért nézd meg a log fájlt.")

    async def _delete_command_message(self, update: Update):
        """Törli a parancsot tartalmazó üzenetet a chat tisztán tartása érdekében."""
        try:
            if update.message: await update.message.delete()
        except Exception:
            logging.getLogger().debug("A parancsüzenet törlése nem sikerült.")

    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        command_name = "start"; logging.info(f"/{command_name} parancs fogadva.")
        try:
            help_text = "👋 Szia! Elérhető parancsok:\n\n`/status` - Részletes állapotjelentés\n`/pnl` - Teljes PnL riport\n`/livepnl` - Élő PnL riport\n`/demopnl` - Demó PnL riport\n`/chart` - Interaktív egyenleggörbe"
            await update.message.reply_markdown(help_text)
        except Exception as e:
            context.error = e; await self._handle_error(update, context, command_name)
        finally:
            await self._delete_command_message(update)

    async def status_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        command_name = "status"; logging.info(f"/{command_name} parancs fogadva.")
        try:
            status = self._load_json_file(STATUS_FILE_PATH, {})
            pnl_report = self._load_json_file(PNL_REPORT_FILE_PATH, {})
            activity_data = self._load_json_file(ACTIVITY_FILE_PATH, {})
            if not status:
                await update.message.reply_markdown("Hiba: `status.json` nem található vagy üres."); return
            
            live_daily_pnl = pnl_report.get("Élő", {}).get("periods", {}).get("Napi", {}).get("pnl", 0.0)
            demo_daily_pnl = pnl_report.get("Demó", {}).get("periods", {}).get("Napi", {}).get("pnl", 0.0)
            
            reply = (f"✅ *Másoló program állapota (v{status.get('version', 'N/A')})*\n"
                     f"Utolsó frissítés: `{status.get('timestamp', 'N/A')}`\n"
                     f"Utolsó másolás: `{activity_data.get('last_copy_activity', 'Még nem történt')}`\n\n"
                     f"🏦 *Egyenleg (Élő):* `${status.get('live_balance', 0.0):,.2f}`\n"
                     f"🏦 *Egyenleg (Demó):* `${status.get('demo_balance', 0.0):,.2f}`\n\n"
                     f"📈 *Nyitott PnL (Élő):* `${status.get('live_pnl', 0.0):,.2f}`\n"
                     f"📉 *Nyitott PnL (Demó):* `${status.get('demo_pnl', 0.0):,.2f}`\n\n"
                     f"💰 *Napi Zárt PnL (Élő):* `${live_daily_pnl:,.2f}`\n"
                     f"💰 *Napi Zárt PnL (Demó):* `${demo_daily_pnl:,.2f}`\n\n"
                     f"Live pozíciók: *{status.get('live_pos_count', 0)} db*\n"
                     f"Demó pozíciók: *{status.get('demo_pos_count', 0)} db*")
            await update.message.reply_markdown(reply)
        except Exception as e:
            context.error = e; await self._handle_error(update, context, command_name)
        finally:
            await self._delete_command_message(update)

    async def pnl_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        command_name = "pnl"; logging.info(f"/{command_name} parancs fogadva.")
        try:
            status, report = self._load_json_file(STATUS_FILE_PATH, {}), self._load_json_file(PNL_REPORT_FILE_PATH, {})
            await update.message.reply_markdown(self._format_pnl_report(report, status))
        except Exception as e:
            context.error = e; await self._handle_error(update, context, command_name)
        finally:
            await self._delete_command_message(update)

    async def live_pnl_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        command_name = "livepnl"; logging.info(f"/{command_name} parancs fogadva.")
        try:
            status, report = self._load_json_file(STATUS_FILE_PATH, {}), self._load_json_file(PNL_REPORT_FILE_PATH, {})
            await update.message.reply_markdown(self._format_pnl_report(report, status, "Élő"))
        except Exception as e:
            context.error = e; await self._handle_error(update, context, command_name)
        finally:
            await self._delete_command_message(update)

    async def demo_pnl_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        command_name = "demopnl"; logging.info(f"/{command_name} parancs fogadva.")
        try:
            status, report = self._load_json_file(STATUS_FILE_PATH, {}), self._load_json_file(PNL_REPORT_FILE_PATH, {})
            await update.message.reply_markdown(self._format_pnl_report(report, status, "Demó"))
        except Exception as e:
            context.error = e; await self._handle_error(update, context, command_name)
        finally:
            await self._delete_command_message(update)

    async def chart_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not MATPLOTLIB_AVAILABLE:
            await update.message.reply_text("A grafikon funkció nem elérhető, mert a 'matplotlib' csomag hiányzik.")
            return ConversationHandler.END

        logging.info(f"/chart parancs fogadva.")
        keyboard = [
            [InlineKeyboardButton("Napi", callback_data='period_daily'), InlineKeyboardButton("Heti", callback_data='period_weekly')],
            [InlineKeyboardButton("Havi", callback_data='period_monthly'), InlineKeyboardButton("90 Napos", callback_data='period_90days')],
            [InlineKeyboardButton("Mégse", callback_data='cancel')]
        ]
        await update.message.reply_text('Milyen időszakról szeretnél grafikont?', reply_markup=InlineKeyboardMarkup(keyboard))
        await self._delete_command_message(update)
        return self.SELECT_PERIOD

    async def select_period(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query; await query.answer();
        context.user_data['period'] = query.data.split('_')[1]
        logging.info(f"Chart: Időszak kiválasztva: {context.user_data['period']}")
        keyboard = [
            [InlineKeyboardButton("Élő", callback_data='account_Élő'), InlineKeyboardButton("Demó", callback_data='account_Demó')],
            [InlineKeyboardButton("Vissza", callback_data='back_to_period'), InlineKeyboardButton("Mégse", callback_data='cancel')]
        ]
        await query.edit_message_text("Rendben. Melyik számláról?", reply_markup=InlineKeyboardMarkup(keyboard))
        return self.SELECT_ACCOUNT

    async def select_account_and_generate(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query; await query.answer()
        account = query.data.split('_')[1]
        context.user_data['account'] = account
        logging.info(f"Chart: Számla kiválasztva: {account}. Grafikon generálása...")
        await query.edit_message_text("⏳ Türelem, készítem a grafikont...")
        
        try:
            period = context.user_data['period']
            data_file = LIVE_CHART_FILE_PATH if account == "Élő" else DEMO_CHART_FILE_PATH
            data_for_chart = self._load_json_file(data_file, [])
            
            loop = asyncio.get_running_loop()
            image_buffer, caption_text = await loop.run_in_executor(None, self._generate_chart_in_memory, data_for_chart, period, account)
            
            logging.info("Grafikon sikeresen legenerálva.")
            await query.delete_message()
            if image_buffer:
                await context.bot.send_photo(chat_id=query.message.chat_id, photo=image_buffer, caption=caption_text, parse_mode='Markdown')
            else:
                await context.bot.send_message(chat_id=query.message.chat_id, text=caption_text)
        except Exception as e:
            logging.error(f"Váratlan hiba a grafikon generálásakor: {e}", exc_info=True)
            await query.edit_message_text(f"❌ Hiba történt a grafikon készítésekor. Részletek a logban.")
        finally:
            context.user_data.clear()
        return ConversationHandler.END

    def _generate_chart_in_memory(self, data: list, period: str, account: str):
        """Legenerálja a grafikont és visszaadja egy byte bufferben a képet és a hozzá tartozó szöveget."""
        try:
            days = {'daily': 1, 'weekly': 7, 'monthly': 30, '90days': 90}.get(period, 1)
            start_ts = int((datetime.now(timezone.utc) - timedelta(days=days)).timestamp())
            filtered = [d for d in data if d.get('time', 0) >= start_ts]

            if len(filtered) < 2:
                return None, f"Túl kevés adat ({len(filtered)} db) van a grafikonhoz a kiválasztott időszakban."

            all_equity_values = [float(p['value']) for p in filtered]
            min_equity, max_equity = min(all_equity_values), max(all_equity_values)

            if min_equity == max_equity:
                return None, f"Az egyenleg nem változott a kiválasztott időszakban (érték: ${min_equity:,.2f})."

            plt.style.use('dark_background'); fig, ax = plt.subplots(figsize=(12, 6))
            all_timestamps = [datetime.fromtimestamp(p['time'], tz=timezone.utc) for p in filtered]; x_indices = list(range(len(all_equity_values)))
            ax.plot(x_indices, all_equity_values, color='#00aaff', linewidth=2); ax.fill_between(x_indices, all_equity_values, color='#00aaff', alpha=0.1)
            num_points = len(x_indices); num_ticks = min(num_points, 8); tick_indices = [int(i) for i in _linspace(0, num_points - 1, num_ticks)]
            tick_labels = [all_timestamps[i].strftime('%m-%d\n%H:%M') for i in tick_indices]
            ax.set_xticks(tick_indices); ax.set_xticklabels(tick_labels, rotation=0); y_range = max_equity - min_equity; buffer = y_range * 0.1 or 1.0; ax.set_ylim(min_equity - buffer, max_equity + buffer)
            title_period = {'daily': 'Utolsó 24 óra', 'weekly': 'Utolsó 7 nap', 'monthly': 'Utolsó 30 nap', '90days': 'Utolsó 90 nap'}.get(period, '')
            ax.set_title(f'{account} Számla Egyenleggörbe - {title_period}', fontsize=16, color='white', pad=20)
            ax.set_ylabel('Tőke (USDT)', color='white'); ax.grid(True, which='both', linestyle='--', linewidth=0.5, color='gray')
            ax.tick_params(axis='y', colors='white'); plt.setp(ax.spines.values(), color='gray'); ax.set_facecolor('#1c1c1c'); fig.set_facecolor('#101010'); fig.tight_layout()
            buf = io.BytesIO(); plt.savefig(buf, format='png', dpi=100); buf.seek(0); plt.close(fig)
            
            change_val = all_equity_values[-1] - all_equity_values[0]
            change_percent = ((all_equity_values[-1]/all_equity_values[0]-1)*100) if all_equity_values[0] != 0 else 0
            
            caption_text = (f"📈 *Statisztika - {account} ({title_period})*\n\n"
                          f"Legalacsonyabb: `${min_equity:,.2f}`\n"
                          f"Legmagasabb: `${max_equity:,.2f}`\n"
                          f"Változás: `${change_val:,.2f}` ({change_percent:+.2f}%)\n"
                          f"Kilengés: `${max_equity - min_equity:,.2f}`")
            return buf, caption_text
        except Exception as e:
            logging.error(f"Hiba a chart kép generálása közben: {e}", exc_info=True); return None, f"Belső hiba történt a grafikon generálásakor: {e}"

    async def back_to_period(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query; await query.answer(); logging.info("Chart: Visszalépés az időszak választáshoz.")
        keyboard = [[InlineKeyboardButton("Napi", callback_data='period_daily'), InlineKeyboardButton("Heti", callback_data='period_weekly')], [InlineKeyboardButton("Havi", callback_data='period_monthly'), InlineKeyboardButton("90 Napos", callback_data='period_90days')], [InlineKeyboardButton("Mégse", callback_data='cancel')]]
        await query.edit_message_text('Milyen időszakról szeretnél grafikont?', reply_markup=InlineKeyboardMarkup(keyboard)); return self.SELECT_PERIOD

    async def cancel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query; await query.answer(); logging.info("Chart: Művelet megszakítva.")
        await query.edit_message_text("Művelet megszakítva."); context.user_data.clear(); return ConversationHandler.END

def run_bot_process(token: str, config: dict):
    """
    Ez a függvény a célpontja a multiprocessing.Process-nak.
    Elindítja a botot egy teljesen külön processzben, saját naplózással.
    """
    setup_logging(config)
    try:
        bot_manager = TelegramBotManager(token=token)
        bot_manager.run()
    except ImportError as e:
        logging.getLogger().warning(f"A Telegram bot nem indul el, mert hiányoznak a szükséges csomagok: {e}")
    except Exception as e:
        logging.getLogger().critical(f"A Telegram bot processz elindítása sikertelen: {e}", exc_info=True)
