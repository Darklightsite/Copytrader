
import logging
import json
import io
import asyncio
from pathlib import Path
from datetime import datetime, timedelta, timezone

# Próbáljuk importálni a szükséges könyvtárakat
try:
    from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
    from telegram.ext import Application, CommandHandler, ContextTypes, ConversationHandler, CallbackQueryHandler
    from telegram.error import BadRequest
    TELEGRAM_LIBS_AVAILABLE = True
except ImportError:
    TELEGRAM_LIBS_AVAILABLE = False
    # Dummy osztályok, hogy a program ne álljon le, ha a csomagok hiányoznak
    class Update: pass
    class ContextTypes:
        class DEFAULT_TYPE: pass # 
    class ConversationHandler:
        END = -1

try:
    import matplotlib
    matplotlib.use('Agg') # Nem interaktív backend a szerveroldali futtatáshoz
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    MATPLOTLIB_AVAILABLE = True
except ImportError:
    MATPLOTLIB_AVAILABLE = False

logger = logging.getLogger()

def _linspace(start, stop, num):
    """Lineárisan elosztott pontokat generál két érték között."""
    if num < 2:
        return [start] if num == 1 else [] # 
    step = (stop - start) / (num - 1)
    return [start + step * i for i in range(num)]

class TelegramBotManager:
    """Osztály, amely a Telegram bot összes interaktív logikáját kezeli."""
    
    def __init__(self, token, config, data_dir: Path):
        if not TELEGRAM_LIBS_AVAILABLE:
            raise ImportError("A 'python-telegram-bot' csomag nincs telepítve.")
        self.token = token
        self.config = config
        self.data_dir = data_dir
        self.app = Application.builder().token(self.token).build()
        self.SELECT_PERIOD, self.SELECT_ACCOUNT = range(2) # 
        self._register_handlers()

    def _register_handlers(self):
        """Regisztrálja a parancs- és üzenetkezelőket a bothoz."""
        # A /chart parancs egy beszélgetést (conversation) indít
        conv_handler = ConversationHandler(
            entry_points=[CommandHandler('chart', self.chart_start)], # 
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
        self.app.add_handler(CommandHandler("livepnl", self.livepnl_command))
        self.app.add_handler(CommandHandler("demopnl", self.demopnl_command))
        self.app.add_handler(CommandHandler("version", self.version_command))

        # Ez a handler kezeli a szinkronizációs gombok callback-jeit
        self.app.add_handler(CallbackQueryHandler(self.button_callback_handler)) # 

    def run(self):
        """A bot futtatása (polling módban)."""
        logger.info("Telegram bot processz indul...")
        try:
            self.app.run_polling()
        except Exception as e:
            logger.critical("KRITIKUS HIBA a Telegram bot processzben: %s", e, exc_info=True)
        logger.info("Telegram bot processz leállt.")

    def _load_json_file(self, file_path, default_data=None):
        """Biztonságos JSON fájl betöltő, hibakezeléssel."""
        if default_data is None: default_data = {}
        if not file_path.exists():
            logger.warning(f"A(z) {file_path} fájl nem található.");
            return default_data # 
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            logger.error(f"Hiba a {file_path} olvasásakor: {e}")
            return default_data

    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        logger.info("/start parancs fogadva.") # 
        help_text = (
            "👋 *Szia! Elérhető parancsok:*\n\n"
            "`/status` - Részletes állapotjelentés\n"
            "`/pnl` - Összesített PnL riport\n"
            "`/livepnl` - Csak az élő PnL riport\n"
            "`/demopnl` - Csak a demó PnL riport\n"
            "`/version` - Program verziója\n" # 
            "`/chart` - Interaktív egyenleggörbe"
        )
        await update.message.reply_markdown(help_text)

    async def version_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        logger.info("/version parancs fogadva.")
        status = self._load_json_file(self.data_dir / "status.json", {})
        await update.message.reply_markdown(f"ℹ️ Verzió: `{status.get('version', 'N/A')}`")

    async def status_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        logger.info("/status parancs fogadva.") # 
        status = self._load_json_file(self.data_dir / "status.json")
        activity = self._load_json_file(self.data_dir / "activity.json")
        pnl_report = self._load_json_file(self.data_dir / "pnl_report.json")
        
        if not status:
            await update.message.reply_markdown("Hiba: `status.json` nem található vagy üres.")
            return
            
        live_daily_pnl = pnl_report.get("Élő", {}).get("periods", {}).get("Mai", {}).get("pnl", 0.0)
        demo_daily_pnl = pnl_report.get("Demó", {}).get("periods", {}).get("Mai", {}).get("pnl", 0.0)

        reply = (f"✅ *Másoló program állapota (v{status.get('version', 'N/A')})*\n"
                 f"Utolsó frissítés: `{status.get('timestamp', 'N/A')}`\n"
                 f"Utolsó másolás: `{activity.get('last_copy_activity', 'Még nem történt')}`\n\n" # 
                 f"🏦 *Egyenleg (Élő):* `${status.get('live_balance', 0.0):,.2f}`\n"
                 f"🏦 *Egyenleg (Demó):* `${status.get('demo_balance', 0.0):,.2f}`\n\n"
                 f"📈 *Nyitott PnL (Élő):* `${status.get('live_pnl', 0.0):,.2f}`\n"
                 f"📉 *Nyitott PnL (Demó):* `${status.get('demo_pnl', 0.0):,.2f}`\n\n"
                 f"💰 *Mai Zárt PnL (Élő):* `${live_daily_pnl:,.2f}`\n" # 
                 f"💰 *Mai Zárt PnL (Demó):* `${demo_daily_pnl:,.2f}`\n\n"
                 f"Live pozíciók: *{status.get('live_pos_count', 0)} db*\n"
                 f"Demó pozíciók: *{status.get('demo_pos_count', 0)} db*")
        
        await update.message.reply_markdown(reply)

    async def _send_pnl_report(self, update: Update, context: ContextTypes.DEFAULT_TYPE, account_filter: str = None):
        """Belső függvény a PnL riportok egységes küldéséhez."""
        cmd = f"/{account_filter.lower() if account_filter else ''}pnl"
        logger.info(f"{cmd} parancs fogadva.")
        
        pnl_data = self._load_json_file(self.data_dir / "pnl_report.json")
        if not pnl_data:
            await update.message.reply_text("Nincsenek elérhető PnL adatok.")
            return

        title = "Összesített" if not account_filter else account_filter
        message = f"📊 *Realizált PnL Jelentés ({title})* 📊\n\n"
        period_order = ["Mai", "Heti", "Havi", "Teljes"]
        
        accounts_to_show = [account_filter] if account_filter else ["Élő", "Demó"]
        
        found_data = False
        for account in accounts_to_show:
            if account_data := pnl_data.get(account):
                found_data = True
                start_date_info = account_data.get('start_date', 'N/A')
                message += f"⦿ *{account} Számla* (Előzmények kezdete: {start_date_info})\n"
                
                # A definiált sorrendben megyünk végig
                for period in period_order:
                    if pnl_info := account_data.get('periods', {}).get(period):
                        pnl_value = pnl_info.get('pnl', 0.0)
                        trade_count = pnl_info.get('trade_count', 0)
                        # Hozzáadunk egy emoji-t a PnL értékhez
                        pnl_emoji = "📈" if pnl_value > 0 else "📉" if pnl_value < 0 else "➖"
                        message += f"  - `{period}`: {pnl_emoji} `${pnl_value:,.2f}` ({trade_count} trade)\n"
                message += "\n"
        
        if not found_data:
            message = f"Nincsenek PnL adatok a(z) '{account_filter}' számlához."
        
        await update.message.reply_markdown(message)
    
    async def pnl_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self._send_pnl_report(update, context)
        
    async def livepnl_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self._send_pnl_report(update, context, "Élő")
        
    async def demopnl_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self._send_pnl_report(update, context, "Demó")

    # --- Chart készítő ConversationHandler ---
    async def chart_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not MATPLOTLIB_AVAILABLE:
            await update.message.reply_text("A grafikon funkció nem elérhető, mert a 'matplotlib' csomag hiányzik.")
            return ConversationHandler.END

        logger.info("/chart parancs fogadva.")
        keyboard = [
            [InlineKeyboardButton("Napi", callback_data='period_daily'), InlineKeyboardButton("Heti", callback_data='period_weekly')],
            [InlineKeyboardButton("Havi", callback_data='period_monthly'), InlineKeyboardButton("90 Napos", callback_data='period_90days')],
            [InlineKeyboardButton("Mégse", callback_data='cancel')] # 
        ]
        await update.message.reply_text('Milyen időszakról szeretnél grafikont?', reply_markup=InlineKeyboardMarkup(keyboard))
        return self.SELECT_PERIOD

    async def select_period(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query; await query.answer() # 
        context.user_data['period'] = query.data.split('_')[1]
        logger.info(f"Chart: Időszak kiválasztva: {context.user_data['period']}")
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
        logger.info(f"Chart: Számla kiválasztva: {account}. Grafikon generálása...")
        await query.edit_message_text("⏳ Türelem, készítem a grafikont...")
        
        try:
            period = context.user_data['period']
            data_file = self.data_dir / ("live_chart_data.json" if account == "Élő" else "demo_chart_data.json") # 
            data_for_chart = self._load_json_file(data_file, [])
            
            loop = asyncio.get_running_loop()
            image_buffer, caption_text = await loop.run_in_executor(None, self._generate_chart_in_memory, data_for_chart, period, account)
            
            logger.info("Grafikon sikeresen legenerálva.")
            await query.delete_message() # 
            if image_buffer:
                await context.bot.send_photo(chat_id=query.message.chat_id, photo=image_buffer, caption=caption_text, parse_mode='Markdown')
            else:
                await context.bot.send_message(chat_id=query.message.chat_id, text=caption_text)
        except Exception as e:
            logger.error(f"Váratlan hiba a grafikon generálásakor: {e}", exc_info=True)
            await query.edit_message_text(f"❌ Hiba történt a grafikon készítésekor. Részletek a logban.") # 
        finally:
            context.user_data.clear()
        return ConversationHandler.END

    def _generate_chart_in_memory(self, data: list, period: str, account: str):
        try:
            days = {'daily': 1, 'weekly': 7, 'monthly': 30, '90days': 90}.get(period, 1)
            start_ts = int((datetime.now(timezone.utc) - timedelta(days=days)).timestamp()) # 
            filtered = [d for d in data if d.get('time', 0) >= start_ts]

            if len(filtered) < 2: return None, f"Túl kevés adat ({len(filtered)} db) van a grafikonhoz a kiválasztott időszakban."
            
            all_equity_values = [float(p['value']) for p in filtered]
            min_equity, max_equity = min(all_equity_values), max(all_equity_values) # 

            if min_equity == max_equity: return None, f"Az egyenleg nem változott a kiválasztott időszakban (érték: ${min_equity:,.2f})."

            plt.style.use('dark_background'); fig, ax = plt.subplots(figsize=(12, 6)) # 
            x_indices = list(range(len(all_equity_values)))
            ax.plot(x_indices, all_equity_values, color='#00aaff', linewidth=2)
            ax.fill_between(x_indices, all_equity_values, color='#00aaff', alpha=0.1) # 
            
            num_points = len(x_indices); num_ticks = min(num_points, 8); tick_indices = [int(i) for i in _linspace(0, num_points - 1, num_ticks)] # 
            tick_labels = [datetime.fromtimestamp(filtered[i]['time'], tz=timezone.utc).strftime('%m-%d\n%H:%M') for i in tick_indices]
            ax.set_xticks(tick_indices); ax.set_xticklabels(tick_labels, rotation=0) # 
            
            y_range = max_equity - min_equity; buffer = y_range * 0.1 or 1.0
            ax.set_ylim(min_equity - buffer, max_equity + buffer) # 
            
            title_period = {'daily': 'Utolsó 24 óra', 'weekly': 'Utolsó 7 nap', 'monthly': 'Utolsó 30 nap', '90days': 'Utolsó 90 nap'}.get(period, '')
            ax.set_title(f'{account} Számla Egyenleggörbe - {title_period}', fontsize=16, color='white', pad=20)
            ax.set_ylabel('Tőke (USDT)', color='white'); ax.grid(True, which='both', linestyle='--', linewidth=0.5, color='gray') # 
            ax.tick_params(axis='y', colors='white'); plt.setp(ax.spines.values(), color='gray')
            ax.set_facecolor('#1c1c1c'); fig.set_facecolor('#101010'); fig.tight_layout() # 
            
            buf = io.BytesIO(); plt.savefig(buf, format='png', dpi=100); buf.seek(0); plt.close(fig) # 
            
            change_val = all_equity_values[-1] - all_equity_values[0]
            change_percent = ((all_equity_values[-1]/all_equity_values[0]-1)*100) if all_equity_values[0] != 0 else 0 # 
            caption_text = (f"📈 *Statisztika - {account} ({title_period})*\n\n"
                          f"Legalacsonyabb: `${min_equity:,.2f}`\nLegmagasabb: `${max_equity:,.2f}`\n"
                          f"Változás: `${change_val:,.2f}` ({change_percent:+.2f}%)\nKilengés: `${max_equity - min_equity:,.2f}`")
            return buf, caption_text
        except Exception as e: 
            logger.error(f"Hiba a chart kép generálása közben: {e}", exc_info=True) # 
            return None, f"Belső hiba történt a grafikon generálásakor: {e}" # 

    async def back_to_period(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query; await query.answer(); logger.info("Chart: Visszalépés az időszak választáshoz.") # 
        keyboard = [[InlineKeyboardButton("Napi", callback_data='period_daily'), InlineKeyboardButton("Heti", callback_data='period_weekly')], [InlineKeyboardButton("Havi", callback_data='period_monthly'), InlineKeyboardButton("90 Napos", callback_data='period_90days')], [InlineKeyboardButton("Mégse", callback_data='cancel')]]
        await query.edit_message_text('Milyen időszakról szeretnél grafikont?', reply_markup=InlineKeyboardMarkup(keyboard));
        return self.SELECT_PERIOD # 

    async def cancel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query; await query.answer(); logger.info("Chart: Művelet megszakítva.") # 
        await query.edit_message_text("Művelet megszakítva."); context.user_data.clear();
        return ConversationHandler.END # 
        
    async def button_callback_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Kezeli az összes gombnyomást, ami nem a chart beszélgetés része."""
        # Az importot ide helyeztük, hogy elkerüljük a körbeimportálást
        from .sync_checker import handle_sync_action
        
        query = update.callback_query
        # Ha a callback a chart conversation része, ne csináljunk semmit, azt a ConversationHandler kezeli
        if query.data.startswith(('period_', 'account_', 'back_to_period', 'cancel')): # 
            return

        await query.answer()
        
        if query.data.startswith("sync_action:"):
            action = query.data.split(":")[1]
            try:
                # Frissítjük a gombos üzenetet, hogy a felhasználó lássa a visszajelzést
                if query.message.caption:
                    await query.edit_message_caption(caption=f"Parancs fogadva: {action}. Feldolgozás...") # 
                else:
                    await query.edit_message_text(text=f"Parancs fogadva: {action}. Feldolgozás...") # 
            except BadRequest as e:
                # Nem hiba, ha az üzenet nem változott
                if "message is not modified" not in str(e).lower(): 
                    logger.error(f"Telegram BadRequest hiba: {e}")
            
            # A szinkronizációs akció végrehajtása
            handle_sync_action(action, self.config, self.data_dir)

def run_bot_process(token: str, config: dict, data_dir: Path):
    """Ez a függvény a multiprocessing.Process célpontja."""
    # A botnak saját logolást kell beállítania, mert külön processzben fut.
    from .logger_setup import setup_logging
    setup_logging(config, log_dir=(data_dir / "logs"))
    
    try:
        bot_manager = TelegramBotManager(token=token, config=config, data_dir=data_dir)
        bot_manager.run()
    except ImportError as e:
        logger.warning(f"A Telegram bot nem indul el, mert hiányoznak a szükséges csomagok: {e}")
    except Exception as e:
        logger.critical(f"A Telegram bot processz elindítása sikertelen: {e}", exc_info=True) # 
