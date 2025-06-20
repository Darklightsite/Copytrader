# FÁJL: modules/telegram_bot.py (Teljes, javított kód)

import logging
import json
import io
import asyncio
import warnings
from pathlib import Path
from datetime import datetime, timedelta, timezone

# A Telegram és Matplotlib könyvtárak importját áthelyeztük a run_bot_process függvénybe
TELEGRAM_LIBS_AVAILABLE = False
MATPLOTLIB_AVAILABLE = False
class Update: pass
class ContextTypes:
    class DEFAULT_TYPE: pass
class ConversationHandler:
    END = -1

logger = logging.getLogger()

def _linspace(start, stop, num):
    if num < 2: return [start] if num == 1 else []
    step = (stop - start) / (num - 1)
    return [start + step * i for i in range(num)]

class TelegramBotManager:
    def __init__(self, token, config, data_dir: Path, telegram_classes):
        self.token, self.config, self.data_dir = token, config, data_dir
        
        self.Update = telegram_classes['Update']
        self.InlineKeyboardButton = telegram_classes['InlineKeyboardButton']
        self.InlineKeyboardMarkup = telegram_classes['InlineKeyboardMarkup']
        self.Application = telegram_classes['Application']
        self.CommandHandler = telegram_classes['CommandHandler']
        self.ContextTypes = telegram_classes['ContextTypes']
        self.ConversationHandler = telegram_classes['ConversationHandler']
        self.CallbackQueryHandler = telegram_classes['CallbackQueryHandler']
        self.BadRequest = telegram_classes['BadRequest']

        self.app = self.Application.builder().token(self.token).build()
        self.SELECT_PERIOD, self.SELECT_ACCOUNT = range(2)
        self._register_handlers()

    def _register_handlers(self):
        conv_handler = self.ConversationHandler(
            entry_points=[self.CommandHandler('chart', self.chart_start)],
            states={
                self.SELECT_PERIOD: [self.CallbackQueryHandler(self.select_period, pattern='^period_')],
                self.SELECT_ACCOUNT: [self.CallbackQueryHandler(self.select_account_and_generate, pattern='^account_'), self.CallbackQueryHandler(self.back_to_period, pattern='^back_to_period$')]
            },
            fallbacks=[self.CallbackQueryHandler(self.cancel, pattern='^cancel$'), self.CommandHandler('chart', self.chart_start)],
            per_message=False,
            conversation_timeout=300
        )
        self.app.add_handler(conv_handler)
        self.app.add_handler(self.CommandHandler(["start", "help"], self.start_command))
        self.app.add_handler(self.CommandHandler("status", self.status_command))
        self.app.add_handler(self.CommandHandler("pnl", self.pnl_command))
        # --- ÚJ PARANCS HOZZÁADÁSA ---
        self.app.add_handler(self.CommandHandler("pnlchart", self.pnl_chart_command))

    def run(self):
        logger.info("Telegram bot processz indul...")
        try:
            self.app.run_polling(timeout=60, allowed_updates=self.Update.ALL_TYPES)
        except Exception as e:
            logger.critical("Hiba a Telegram bot futása közben: %s", e, exc_info=True)
        logger.info("Telegram bot processz leállt.")

    def _load_json_file(self, file_path, default_data=None):
        if default_data is None: default_data = {}
        if not file_path.exists(): return default_data
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError): return default_data
    
    async def _delete_command_message(self, update: Update):
        try:
            await update.message.delete()
        except self.BadRequest as e:
            if "message to delete not found" not in str(e).lower():
                logger.warning(f"Nem sikerült törölni a parancsüzenetet (valószínűleg nincs admin jog): {e}")
        except Exception as e:
            logger.error(f"Hiba a parancsüzenet törlésekor: {e}", exc_info=True)

    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        # --- SÚGÓ SZÖVEG FRISSÍTÉSE ---
        help_text = ("👋 *Szia! Elérhető parancsok:*\n\n"
                     "`/status` - Részletes állapotjelentés\n"
                     "`/pnl` - Összesített PnL riport (szöveges)\n"
                     "`/pnlchart` - Összesített PnL riport (grafikon)\n"
                     "`/chart` - Interaktív egyenleggörbe")
        await update.message.reply_markdown(help_text)
        await self._delete_command_message(update)

    async def status_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        logger.info("/status parancs fogadva.")
        try:
            status = self._load_json_file(self.data_dir / "status.json")
            pnl_report = self._load_json_file(self.data_dir / "pnl_report.json")
            daily_stats = self._load_json_file(self.data_dir / "daily_stats.json")
            activity = self._load_json_file(self.data_dir / "activity.json")
            
            await self._delete_command_message(update)

            if not status:
                await context.bot.send_message(chat_id=update.effective_chat.id, text="Hiba: `status.json` nem található.", parse_mode='Markdown')
                return
            
            live_daily_pnl = pnl_report.get("Élő", {}).get("periods", {}).get("Mai", {}).get("pnl", 0.0)
            demo_daily_pnl = pnl_report.get("Demó", {}).get("periods", {}).get("Mai", {}).get("pnl", 0.0)

            reply = (
                f"✅ *Másoló v{status.get('version', 'N/A')}*\n"
                f"Utolsó szinkronizáció: `{status.get('timestamp', 'N/A')}`\n"
                f"Utolsó másolás: `{activity.get('last_copy_activity', 'N/A')}`\n\n"
                f"🏦 *Egyenleg (Élő):* `${status.get('live_balance', 0.0):,.2f}`\n"
                f"📈 *Nyitott PnL (Élő):* `${status.get('live_pnl', 0.0):,.2f}`\n"
                f"💰 *Mai Zárt PnL (Élő):* `${live_daily_pnl:,.2f}`\n\n"
                f"🏦 *Egyenleg (Demó):* `${status.get('demo_balance', 0.0):,.2f}`\n"
                f"📉 *Nyitott PnL (Demó):* `${status.get('demo_pnl', 0.0):,.2f}`\n"
                f"💰 *Mai Zárt PnL (Demó):* `${demo_daily_pnl:,.2f}`"
            )

            demo_stats = daily_stats.get('demo')
            if demo_stats:
                start_equity = demo_stats.get('day_start_equity', 0)
                peak_equity = demo_stats.get('day_peak_equity', 0)
                current_equity = status.get('demo_balance', 0)
                
                if start_equity > 0:
                    drawdown_limit_amount = start_equity * 0.05
                    current_drawdown = max(0, peak_equity - current_equity)
                    remaining_drawdown = drawdown_limit_amount - current_drawdown
                    reply += "\n\n"
                    reply += (f"🛡️ *Napi Drawdown (Demó):*\n"
                              f"  - Limit: `${drawdown_limit_amount:,.2f}`\n"
                              f"  - Jelenlegi: `${current_drawdown:,.2f}`\n"
                              f"  - Fennmaradó: `${remaining_drawdown:,.2f}`")
            
            await context.bot.send_message(chat_id=update.effective_chat.id, text=reply, parse_mode='Markdown', disable_notification=True)
        except Exception as e:
            logger.error(f"Hiba a /status parancs feldolgozása közben: {e}", exc_info=True)
            await context.bot.send_message(chat_id=update.effective_chat.id, text="Hiba a /status parancs végrehajtása során.")

    async def pnl_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        logger.info("/pnl parancs fogadva.")
        pnl_data = self._load_json_file(self.data_dir / "pnl_report.json")
        await self._delete_command_message(update)
        
        if not pnl_data:
            await context.bot.send_message(chat_id=update.effective_chat.id, text="Nincsenek elérhető PnL adatok.")
            return

        message = "📊 *Realizált PnL Jelentés* 📊\n\n"
        period_order = ["Mai", "Heti", "Havi", "Teljes"]
        
        for account in ["Élő", "Demó"]:
            if account_data := pnl_data.get(account):
                start_date_info = account_data.get('start_date', 'N/A')
                message += f"⦿ *{account} Számla* (Kezdet: {start_date_info})\n"
                for period in period_order:
                    if pnl_info := account_data.get('periods', {}).get(period):
                        pnl_value, trade_count = pnl_info.get('pnl', 0.0), pnl_info.get('trade_count', 0)
                        pnl_emoji = "📈" if pnl_value > 0 else "📉" if pnl_value < 0 else "➖"
                        message += f"  - `{period}`: {pnl_emoji} `${pnl_value:,.2f}` ({trade_count} trade)\n"
                message += "\n"
        await context.bot.send_message(chat_id=update.effective_chat.id, text=message, parse_mode='Markdown', disable_notification=True)

    # --- ÚJ FUNKCIÓ: PNL OSZLOPDIAGRAM ---
    async def pnl_chart_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        logger.info("/pnlchart parancs fogadva.")
        await self._delete_command_message(update)

        if not MATPLOTLIB_AVAILABLE:
            await context.bot.send_message(chat_id=update.effective_chat.id, text="Grafikon funkció nem elérhető: 'matplotlib' csomag hiányzik.")
            return

        pnl_data = self._load_json_file(self.data_dir / "pnl_report.json")
        if not pnl_data:
            await context.bot.send_message(chat_id=update.effective_chat.id, text="Nincsenek elérhető PnL adatok a grafikonhoz.")
            return

        # Üzenet küldése a várakozásról
        wait_message = await context.bot.send_message(chat_id=update.effective_chat.id, text="⏳ Készítem a PnL grafikont...")

        try:
            loop = asyncio.get_running_loop()
            # A grafikon generálása külön szálon fut, hogy ne blokkolja a botot
            image_buffer, caption_text = await loop.run_in_executor(None, self._generate_pnl_barchart, pnl_data)
            
            # A várakozási üzenet törlése
            await wait_message.delete()
            
            if image_buffer:
                await context.bot.send_photo(chat_id=update.effective_chat.id, photo=image_buffer, caption=caption_text, parse_mode='Markdown')
            else:
                await context.bot.send_message(chat_id=update.effective_chat.id, text=caption_text)

        except Exception as e:
            logger.error(f"Hiba a PnL grafikon generálásakor: {e}", exc_info=True)
            # A várakozási üzenet szerkesztése hiba esetén
            await wait_message.edit_text(text="❌ Hiba történt a PnL grafikon készítésekor.")

    def _generate_pnl_barchart(self, pnl_data):
        """A háttérben legenerálja a PnL oszlopdiagramot a matplotlib segítségével."""
        import matplotlib.pyplot as plt
        import numpy as np

        try:
            plt.style.use('dark_background')
            fig, ax = plt.subplots(figsize=(10, 7))

            accounts = list(pnl_data.keys())
            periods = ["Mai", "Heti", "Havi", "Teljes"]
            
            pnl_values = {acc: [pnl_data.get(acc, {}).get('periods', {}).get(p, {}).get('pnl', 0.0) for p in periods] for acc in accounts}

            x = np.arange(len(periods))
            width = 0.35 if len(accounts) > 1 else 0.5
            
            colors = {'Élő': '#00aaff', 'Demó': '#ffaa00'}

            rect_groups = []
            for i, acc in enumerate(accounts):
                offset = (width / -2) + (i * width) if len(accounts) > 1 else 0
                rects = ax.bar(x + offset, pnl_values[acc], width, label=acc, color=colors.get(acc, 'gray'))
                rect_groups.append(rects)

            ax.set_ylabel('Realizált PnL (USDT)', color='white', fontsize=12)
            ax.set_title('Időszakos Realizált PnL Összesítés', fontsize=16, color='white', pad=20)
            ax.set_xticks(x)
            ax.set_xticklabels(periods, fontsize=11, color='lightgray')
            ax.tick_params(axis='y', colors='white')
            ax.legend(fontsize=12)
            ax.grid(True, which='both', linestyle='--', linewidth=0.4, color='gray', axis='y')
            ax.axhline(0, color='gray', linewidth=0.8) # Nulla vonal
            plt.setp(ax.spines.values(), color='gray')
            ax.set_facecolor('#1e1e1e')
            fig.set_facecolor('#101010')

            # Címkék hozzáadása az oszlopok tetejére
            for rects in rect_groups:
                for rect in rects:
                    height = rect.get_height()
                    ax.annotate(f'${height:,.2f}',
                                xy=(rect.get_x() + rect.get_width() / 2, height),
                                xytext=(0, 5 if height >= 0 else -18),
                                textcoords="offset points",
                                ha='center', va='bottom' if height >= 0 else 'top',
                                color='white', fontsize=9, weight='bold')

            fig.tight_layout(pad=2)
            
            buf = io.BytesIO()
            plt.savefig(buf, format='png', dpi=110, bbox_inches='tight')
            buf.seek(0)
            plt.close(fig)

            caption_text = "📊 *Realizált PnL Oszlopdiagram*\nA grafikon a különböző időszakok alatt realizált profitot és veszteséget mutatja."
            
            return buf, caption_text
        except Exception as e:
            logger.error(f"Hiba a PnL oszlopdiagram generálása közben: {e}", exc_info=True)
            return None, "Belső hiba történt a PnL grafikon generálásakor."

    async def chart_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self._delete_command_message(update)
        if not MATPLOTLIB_AVAILABLE:
            await context.bot.send_message(chat_id=update.effective_chat.id, text="Grafikon funkció nem elérhető: 'matplotlib' csomag hiányzik.")
            return self.ConversationHandler.END
        
        keyboard = [
            [self.InlineKeyboardButton("Napi", callback_data='period_daily'), self.InlineKeyboardButton("Heti", callback_data='period_weekly')],
            [self.InlineKeyboardButton("Havi", callback_data='period_monthly'), self.InlineKeyboardButton("Összes", callback_data='period_all')],
            [self.InlineKeyboardButton("Mégse", callback_data='cancel')]
        ]
        await context.bot.send_message(chat_id=update.effective_chat.id, text='Milyen időszakról szeretnél grafikont?', reply_markup=self.InlineKeyboardMarkup(keyboard))
        return self.SELECT_PERIOD

    async def select_period(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        context.user_data['period'] = query.data.split('_')[1]
        keyboard = [
            [self.InlineKeyboardButton("Élő", callback_data='account_Élő'), self.InlineKeyboardButton("Demó", callback_data='account_Demó')],
            [self.InlineKeyboardButton("Vissza", callback_data='back_to_period'), self.InlineKeyboardButton("Mégse", callback_data='cancel')]
        ]
        await query.edit_message_text("Melyik számláról?", reply_markup=self.InlineKeyboardMarkup(keyboard))
        return self.SELECT_ACCOUNT

    async def select_account_and_generate(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        account_display_name = query.data.split('_')[1]
        await query.edit_message_text("⏳ Készítem a grafikont...")
        
        try:
            period = context.user_data.get('period')
            account_filename_key = 'live' if account_display_name == 'Élő' else 'demo'
            data_file = self.data_dir / f"{account_filename_key}_chart_data.json"
            data_for_chart = self._load_json_file(data_file, [])
            
            loop = asyncio.get_running_loop()
            image_buffer, caption_text = await loop.run_in_executor(None, self._generate_chart_in_memory, data_for_chart, period, account_display_name)
            
            await query.delete_message()
            if image_buffer:
                await context.bot.send_photo(chat_id=query.message.chat_id, photo=image_buffer, caption=caption_text, parse_mode='Markdown')
            else:
                await context.bot.send_message(chat_id=query.message.chat_id, text=caption_text)
        except Exception as e:
            logger.error(f"Hiba a grafikon generálásakor: {e}", exc_info=True)
            await context.bot.send_message(chat_id=query.message.chat_id, text="❌ Hiba történt a grafikon készítésekor.")
        finally:
            context.user_data.clear()
        return self.ConversationHandler.END

    def _generate_chart_in_memory(self, data, period, account_display_name):
        import matplotlib.pyplot as plt

        try:
            days_map = {'daily': 1, 'weekly': 7, 'monthly': 30}
            days = days_map.get(period)
            
            if days:
                start_ts = int((datetime.now(timezone.utc) - timedelta(days=days)).timestamp())
                filtered = [d for d in data if d and d.get('time', 0) >= start_ts]
            else:
                filtered = [d for d in data if d]

            if len(filtered) < 2: return None, f"Túl kevés adat a '{period}' időszakban a(z) '{account_display_name}' fiókhoz."
            
            all_equity_values = [float(p['value']) for p in filtered]
            min_equity, max_equity = min(all_equity_values), max(all_equity_values)
            if min_equity == max_equity: return None, f"Az egyenleg nem változott a '{period}' időszakban."

            plt.style.use('dark_background'); fig, ax = plt.subplots(figsize=(12, 6))
            x_indices = list(range(len(all_equity_values)))
            ax.plot(x_indices, all_equity_values, color='#00aaff', linewidth=2)
            ax.fill_between(x_indices, all_equity_values, color='#00aaff', alpha=0.1)
            
            target_tz = timezone(timedelta(hours=2))
            
            num_ticks = min(len(x_indices), 8); tick_indices = [int(i) for i in _linspace(0, len(x_indices) - 1, num_ticks)]
            tick_labels = [datetime.fromtimestamp(filtered[i]['time'], tz=timezone.utc).astimezone(target_tz).strftime('%m-%d\n%H:%M') for i in tick_indices]
            ax.set_xticks(tick_indices); ax.set_xticklabels(tick_labels, rotation=0)

            y_range = max_equity - min_equity; buffer = y_range * 0.1 or 1.0
            ax.set_ylim(min_equity - buffer, max_equity + buffer)
            
            title_period_map = {'daily': 'Utolsó 24 óra', 'weekly': 'Utolsó 7 nap', 'monthly': 'Utolsó 30 nap'}
            title_period = title_period_map.get(period, 'Teljes időszak')
            
            ax.set_title(f'{account_display_name} Számla Egyenleggörbe - {title_period}', fontsize=16, color='white', pad=20)
            ax.set_ylabel('Tőke (USDT)', color='white'); ax.grid(True, which='both', linestyle='--', linewidth=0.5, color='gray')
            ax.tick_params(axis='y', colors='white'); plt.setp(ax.spines.values(), color='gray')
            ax.set_facecolor('#1c1c1c'); fig.set_facecolor('#101010'); fig.tight_layout()
            
            buf = io.BytesIO(); plt.savefig(buf, format='png', dpi=100); buf.seek(0); plt.close(fig)
            
            change_val = all_equity_values[-1] - all_equity_values[0]
            change_percent = ((all_equity_values[-1]/all_equity_values[0]-1)*100) if all_equity_values[0] != 0 else 0
            caption_text = (f"📈 *Statisztika - {account_display_name} ({title_period})*\n"
                          f"Változás: `${change_val:,.2f}` ({change_percent:+.2f}%)")
            return buf, caption_text
        except Exception as e: 
            logger.error(f"Hiba a chart kép generálása közben: {e}", exc_info=True)
            return None, "Belső hiba történt a grafikon generálásakor."

    async def back_to_period(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        keyboard = [
            [self.InlineKeyboardButton("Napi", callback_data='period_daily'), self.InlineKeyboardButton("Heti", callback_data='period_weekly')],
            [self.InlineKeyboardButton("Havi", callback_data='period_monthly'), self.InlineKeyboardButton("Összes", callback_data='period_all')],
            [self.InlineKeyboardButton("Mégse", callback_data='cancel')]
        ]
        await query.edit_message_text('Milyen időszakról szeretnél grafikont?', reply_markup=self.InlineKeyboardMarkup(keyboard))
        return self.SELECT_PERIOD

    async def cancel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        await query.edit_message_text("Művelet megszakítva.")
        context.user_data.clear()
        return self.ConversationHandler.END
        
def run_bot_process(token: str, config: dict, data_dir: Path):
    from .logger_setup import setup_logging
    setup_logging(config, log_dir=(data_dir / "logs"))
    
    global TELEGRAM_LIBS_AVAILABLE, MATPLOTLIB_AVAILABLE, Update, ContextTypes, ConversationHandler
    
    try:
        from telegram import Update as TelegramUpdate
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        from telegram.ext import Application, CommandHandler, ContextTypes as TelegramContextTypes, ConversationHandler as TelegramConversationHandler, CallbackQueryHandler
        from telegram.error import BadRequest
        from telegram.warnings import PTBUserWarning

        warnings.filterwarnings("ignore", category=PTBUserWarning, message="If 'per_message=False'")

        Update = TelegramUpdate
        ContextTypes = TelegramContextTypes
        ConversationHandler = TelegramConversationHandler
        
        telegram_classes = {
            'Update': TelegramUpdate,
            'InlineKeyboardButton': InlineKeyboardButton,
            'InlineKeyboardMarkup': InlineKeyboardMarkup,
            'Application': Application,
            'CommandHandler': CommandHandler,
            'ContextTypes': TelegramContextTypes,
            'ConversationHandler': TelegramConversationHandler,
            'CallbackQueryHandler': CallbackQueryHandler,
            'BadRequest': BadRequest,
        }
        TELEGRAM_LIBS_AVAILABLE = True
    except ImportError:
        logger.warning("A 'python-telegram-bot' csomag nincs telepítve, a bot nem indul el.")
        return

    try:
        import matplotlib
        matplotlib.use('Agg')
        MATPLOTLIB_AVAILABLE = True
    except ImportError:
        logger.warning("A 'matplotlib' csomag nincs telepítve, a chart funkció nem lesz elérhető.")

    try:
        if not TELEGRAM_LIBS_AVAILABLE:
            raise ImportError("A 'python-telegram-bot' csomag nincs telepítve.")
        
        bot_manager = TelegramBotManager(token=token, config=config, data_dir=data_dir, telegram_classes=telegram_classes)
        bot_manager.run()
    except ImportError as e:
        logger.warning(f"A Telegram bot nem indul el: {e}")
    except Exception as e:
        logger.critical(f"A Telegram bot processz hiba miatt leállt: {e}", exc_info=True)