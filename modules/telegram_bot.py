# FÁJL: modules/telegram_bot.py
# VERZIÓ: Teljes, javított kód (parancsok törlésével)

import logging
import json
import io
import asyncio
from pathlib import Path
from datetime import datetime, timedelta, timezone

try:
    from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
    from telegram.ext import Application, CommandHandler, ContextTypes, ConversationHandler, CallbackQueryHandler
    from telegram.error import BadRequest
    TELEGRAM_LIBS_AVAILABLE = True
except ImportError:
    TELEGRAM_LIBS_AVAILABLE = False
    class Update: pass
    class ContextTypes:
        class DEFAULT_TYPE: pass
    class ConversationHandler:
        END = -1

try:
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    MATPLOTLIB_AVAILABLE = True
except ImportError:
    MATPLOTLIB_AVAILABLE = False

from .sync_checker import handle_sync_action

logger = logging.getLogger()

def _linspace(start, stop, num):
    if num < 2: return [start] if num == 1 else []
    step = (stop - start) / (num - 1)
    return [start + step * i for i in range(num)]

class TelegramBotManager:
    def __init__(self, token, config, data_dir: Path):
        if not TELEGRAM_LIBS_AVAILABLE:
            raise ImportError("A 'python-telegram-bot' csomag nincs telepítve.")
        self.token, self.config, self.data_dir = token, config, data_dir
        self.app = Application.builder().token(self.token).build()
        self.SELECT_PERIOD, self.SELECT_ACCOUNT = range(2)
        self._register_handlers()

    def _register_handlers(self):
        conv_handler = ConversationHandler(
            entry_points=[CommandHandler('chart', self.chart_start)],
            states={
                self.SELECT_PERIOD: [CallbackQueryHandler(self.select_period, pattern='^period_')],
                self.SELECT_ACCOUNT: [CallbackQueryHandler(self.select_account_and_generate, pattern='^account_'), CallbackQueryHandler(self.back_to_period, pattern='^back_to_period$')]
            },
            fallbacks=[CallbackQueryHandler(self.cancel, pattern='^cancel$'), CommandHandler('chart', self.chart_start)],
            per_message=False,
            conversation_timeout=300
        )
        self.app.add_handler(conv_handler)
        self.app.add_handler(CommandHandler(["start", "help"], self.start_command))
        self.app.add_handler(CommandHandler("status", self.status_command))
        self.app.add_handler(CommandHandler("pnl", self.pnl_command))
        self.app.add_handler(CallbackQueryHandler(self.button_callback_handler))

    def run(self):
        logger.info("Telegram bot processz indul...")
        try:
            self.app.run_polling(timeout=60, allowed_updates=Update.ALL_TYPES)
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
        """Segédfunkció a parancsot tartalmazó üzenet törlésére."""
        try:
            await update.message.delete()
        except BadRequest as e:
            # Akkor hagyjuk figyelmen kívül, ha az üzenet már nem létezik.
            if "message to delete not found" not in str(e).lower():
                logger.warning(f"Nem sikerült törölni a parancsüzenetet (valószínűleg nincs admin jog): {e}")
        except Exception as e:
            logger.error(f"Hiba a parancsüzenet törlésekor: {e}", exc_info=True)

    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        help_text = ("👋 *Szia! Elérhető parancsok:*\n\n"
                     "`/status` - Részletes állapotjelentés\n"
                     "`/pnl` - Összesített PnL riport\n"
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
    
    async def chart_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self._delete_command_message(update)
        if not MATPLOTLIB_AVAILABLE:
            await context.bot.send_message(chat_id=update.effective_chat.id, text="Grafikon funkció nem elérhető: 'matplotlib' csomag hiányzik.")
            return ConversationHandler.END
        
        keyboard = [
            [InlineKeyboardButton("Napi", callback_data='period_daily'), InlineKeyboardButton("Heti", callback_data='period_weekly')],
            [InlineKeyboardButton("Havi", callback_data='period_monthly'), InlineKeyboardButton("Összes", callback_data='period_all')],
            [InlineKeyboardButton("Mégse", callback_data='cancel')]
        ]
        await context.bot.send_message(chat_id=update.effective_chat.id, text='Milyen időszakról szeretnél grafikont?', reply_markup=InlineKeyboardMarkup(keyboard))
        return self.SELECT_PERIOD

    async def select_period(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        context.user_data['period'] = query.data.split('_')[1]
        keyboard = [
            [InlineKeyboardButton("Élő", callback_data='account_Élő'), InlineKeyboardButton("Demó", callback_data='account_Demó')],
            [InlineKeyboardButton("Vissza", callback_data='back_to_period'), InlineKeyboardButton("Mégse", callback_data='cancel')]
        ]
        await query.edit_message_text("Melyik számláról?", reply_markup=InlineKeyboardMarkup(keyboard))
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
        return ConversationHandler.END

    def _generate_chart_in_memory(self, data, period, account_display_name):
        try:
            days_map = {'daily': 1, 'weekly': 7, 'monthly': 30}
            days = days_map.get(period)
            
            if days:
                start_ts = int((datetime.now(timezone.utc) - timedelta(days=days)).timestamp())
                filtered = [d for d in data if d and d.get('time', 0) >= start_ts]
            else:
                filtered = [d for d in data if d]

            if len(filtered) < 2: return None, f"Túl kevés adat a '{period}' időszakban."
            
            all_equity_values = [float(p['value']) for p in filtered]
            min_equity, max_equity = min(all_equity_values), max(all_equity_values)
            if min_equity == max_equity: return None, "Az egyenleg nem változott."

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
            [InlineKeyboardButton("Napi", callback_data='period_daily'), InlineKeyboardButton("Heti", callback_data='period_weekly')],
            [InlineKeyboardButton("Havi", callback_data='period_monthly'), InlineKeyboardButton("Összes", callback_data='period_all')],
            [InlineKeyboardButton("Mégse", callback_data='cancel')]
        ]
        await query.edit_message_text('Milyen időszakról szeretnél grafikont?', reply_markup=InlineKeyboardMarkup(keyboard))
        return self.SELECT_PERIOD

    async def cancel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        await query.edit_message_text("Művelet megszakítva.")
        context.user_data.clear()
        return ConversationHandler.END
        
    async def button_callback_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        if not (query.data and query.data.startswith("sync_action:")): return

        await query.answer()
        action = query.data.split(":")[1]
        try:
            if query.message.caption:
                await query.edit_message_caption(caption=f"Parancs fogadva: {action}.")
            else:
                await query.edit_message_text(text=f"Parancs fogadva: {action}.")
        except BadRequest as e:
            if "message is not modified" not in str(e).lower(): 
                logger.error(f"Telegram BadRequest hiba: {e}")
        handle_sync_action(action, self.config, self.data_dir)

def run_bot_process(token: str, config: dict, data_dir: Path):
    from .logger_setup import setup_logging
    setup_logging(config, log_dir=(data_dir / "logs"))
    try:
        bot_manager = TelegramBotManager(token=token, config=config, data_dir=data_dir)
        bot_manager.run()
    except ImportError as e:
        logger.warning(f"A Telegram bot nem indul el: {e}")
    except Exception as e:
        logger.critical(f"A Telegram bot processz hiba: {e}", exc_info=True)