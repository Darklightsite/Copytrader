# FÁJL: modules/telegram_bot.py (Teljes, javított kód)

import logging
import json
import io
import asyncio
import warnings
from pathlib import Path
from datetime import datetime, timedelta, timezone
from collections import defaultdict

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
        # Új állapotok a beszélgetéshez
        self.SELECT_ACCOUNT, self.SELECT_CHART_TYPE, self.SELECT_PERIOD = range(3)
        self._register_handlers()

    def _register_handlers(self):
        # Többlépcsős ConversationHandler a /chart parancshoz
        conv_handler = self.ConversationHandler(
            entry_points=[self.CommandHandler('chart', self.chart_start)],
            states={
                self.SELECT_ACCOUNT: [
                    self.CallbackQueryHandler(self.select_account, pattern='^account_')
                ],
                self.SELECT_CHART_TYPE: [
                    self.CallbackQueryHandler(self.select_chart_type, pattern='^chart_type_'),
                    self.CallbackQueryHandler(self.chart_start, pattern='^back_to_account$') # Vissza gomb
                ],
                self.SELECT_PERIOD: [
                    self.CallbackQueryHandler(self.select_period_and_generate, pattern='^period_'),
                    self.CallbackQueryHandler(self.select_account, pattern='^back_to_chart_type$') # Vissza gomb
                ],
            },
            fallbacks=[self.CallbackQueryHandler(self.cancel, pattern='^cancel$'), self.CommandHandler('chart', self.chart_start)],
            per_message=False,
            conversation_timeout=300
        )
        self.app.add_handler(conv_handler)
        self.app.add_handler(self.CommandHandler(["start", "help"], self.start_command))
        self.app.add_handler(self.CommandHandler("status", self.status_command))
        self.app.add_handler(self.CommandHandler("pnl", self.pnl_command))

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
        if not update.message: return
        try:
            await update.message.delete()
        except self.BadRequest as e:
            if "message to delete not found" not in str(e).lower():
                logger.warning(f"Nem sikerült törölni a parancsüzenetet (valószínűleg nincs admin jog): {e}")
        except Exception as e:
            logger.error(f"Hiba a parancsüzenet törlésekor: {e}", exc_info=True)

    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        help_text = ("👋 *Szia! Elérhető parancsok:*\n\n"
                     "`/status` - Részletes állapotjelentés\n"
                     "`/pnl` - Összesített PnL riport\n"
                     "`/chart` - Interaktív grafikon menü")
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
            
            live_daily_pnl = pnl_report.get("Élő", {}).get("summary", {}).get("periods", {}).get("Mai", {}).get("pnl", 0.0)
            demo_daily_pnl = pnl_report.get("Demó", {}).get("summary", {}).get("periods", {}).get("Mai", {}).get("pnl", 0.0)

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
                if summary_data := account_data.get('summary'):
                    start_date_info = summary_data.get('start_date', 'N/A')
                    message += f"⦿ *{account} Számla* (Kezdet: {start_date_info})\n"
                    for period in period_order:
                        if pnl_info := summary_data.get('periods', {}).get(period):
                            pnl_value, trade_count = pnl_info.get('pnl', 0.0), pnl_info.get('trade_count', 0)
                            pnl_emoji = "📈" if pnl_value > 0 else "📉" if pnl_value < 0 else "➖"
                            message += f"  - `{period}`: {pnl_emoji} `${pnl_value:,.2f}` ({trade_count} trade)\n"
                    message += "\n"
        await context.bot.send_message(chat_id=update.effective_chat.id, text=message, parse_mode='Markdown', disable_notification=True)
    
    # --- GRAFIKON FUNKCIÓK ---

    async def chart_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """A /chart beszélgetés indítása vagy újraindítása (Fiókválasztás)."""
        await self._delete_command_message(update)
        
        if not MATPLOTLIB_AVAILABLE:
            message_text = "Grafikon funkció nem elérhető: 'matplotlib' csomag hiányzik."
            if update.callback_query: await update.callback_query.edit_message_text(message_text)
            else: await context.bot.send_message(chat_id=update.effective_chat.id, text=message_text)
            return self.ConversationHandler.END

        context.user_data.clear()
        keyboard = [
            [self.InlineKeyboardButton("Élő", callback_data='account_live'), self.InlineKeyboardButton("Demó", callback_data='account_demo')],
            [self.InlineKeyboardButton("Mégse", callback_data='cancel')]
        ]
        message_text = "Melyik fiókról szeretnél grafikont?"
        
        if update.callback_query:
            await update.callback_query.answer()
            await update.callback_query.edit_message_text(message_text, reply_markup=self.InlineKeyboardMarkup(keyboard))
        else:
            await context.bot.send_message(chat_id=update.effective_chat.id, text=message_text, reply_markup=self.InlineKeyboardMarkup(keyboard))
        
        return self.SELECT_ACCOUNT

    async def select_account(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Fiók kiválasztása után a diagramtípus bekérése."""
        query = update.callback_query
        await query.answer()

        # Ha a "back_to_chart_type" gombról jövünk, a fiók már be van állítva, nem írjuk felül.
        if 'account' not in context.user_data:
             context.user_data['account'] = query.data.split('_')[1]

        keyboard = [
            [self.InlineKeyboardButton("Egyenleggörbe", callback_data='chart_type_balance')],
            [self.InlineKeyboardButton("Napi PnL Oszlopdiagram", callback_data='chart_type_pnl')],
            [self.InlineKeyboardButton("« Vissza (Fiók)", callback_data='back_to_account')],
            [self.InlineKeyboardButton("Mégse", callback_data='cancel')]
        ]
        await query.edit_message_text("Milyen típusú diagramot szeretnél?", reply_markup=self.InlineKeyboardMarkup(keyboard))
        return self.SELECT_CHART_TYPE

    async def select_chart_type(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Diagramtípus kiválasztása után a periódus bekérése."""
        query = update.callback_query
        await query.answer()
        
        # JAVÍTÁS: A callback 'chart_type_pnl' -> ['chart', 'type', 'pnl']. A helyes index a 2.
        context.user_data['chart_type'] = query.data.split('_')[2]
        
        chart_type = context.user_data['chart_type']
        
        if chart_type == 'balance':
            keyboard = [
                [self.InlineKeyboardButton("Napi", callback_data='period_daily'), self.InlineKeyboardButton("Heti", callback_data='period_weekly')],
                [self.InlineKeyboardButton("Havi", callback_data='period_monthly'), self.InlineKeyboardButton("Összes", callback_data='period_all')]
            ]
        elif chart_type == 'pnl':
             keyboard = [
                [self.InlineKeyboardButton("Heti", callback_data='period_weekly'), self.InlineKeyboardButton("Havi", callback_data='period_monthly')],
                [self.InlineKeyboardButton("Összes", callback_data='period_all')]
            ]
        else:
            await query.edit_message_text("Hiba: Ismeretlen diagramtípus került kiválasztásra.")
            return self.ConversationHandler.END

        keyboard.append([self.InlineKeyboardButton("« Vissza (Típus)", callback_data='back_to_chart_type')])
        keyboard.append([self.InlineKeyboardButton("Mégse", callback_data='cancel')])
        
        await query.edit_message_text("Válassz időszakot:", reply_markup=self.InlineKeyboardMarkup(keyboard))
        return self.SELECT_PERIOD

    async def select_period_and_generate(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Periódus kiválasztása után a megfelelő grafikon generálása és küldése."""
        query = update.callback_query
        await query.answer()
        context.user_data['period'] = query.data.split('_')[1]

        await query.edit_message_text("⏳ Készítem a grafikont, egy pillanat...")
        
        try:
            account_key = context.user_data.get('account')
            chart_type = context.user_data.get('chart_type')
            period = context.user_data.get('period')
            account_display_name = "Élő" if account_key == 'live' else "Demó"
            
            loop = asyncio.get_running_loop()
            
            if chart_type == 'balance':
                data_file = self.data_dir / f"{account_key}_chart_data.json"
                data_for_chart = self._load_json_file(data_file, [])
                image_buffer, caption_text = await loop.run_in_executor(None, self._generate_balance_chart, data_for_chart, period, account_display_name)
            elif chart_type == 'pnl':
                pnl_report = self._load_json_file(self.data_dir / "pnl_report.json", {})
                image_buffer, caption_text = await loop.run_in_executor(None, self._generate_daily_pnl_barchart, pnl_report, account_display_name, period)
            else:
                image_buffer, caption_text = None, "Ismeretlen diagramtípus."

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

    def _generate_balance_chart(self, data, period, account_display_name):
        """Legenerálja az egyenleggörbe grafikont."""
        import matplotlib.pyplot as plt
        
        try:
            days_map = {'daily': 1, 'weekly': 7, 'monthly': 30}
            title_period_map = {'daily': 'Utolsó 24 óra', 'weekly': 'Utolsó 7 nap', 'monthly': 'Utolsó 30 nap'}
            title_period = title_period_map.get(period, 'Teljes időszak')
            
            days = days_map.get(period)
            if days:
                start_ts = int((datetime.now(timezone.utc) - timedelta(days=days)).timestamp())
                filtered = [d for d in data if d and d.get('time', 0) >= start_ts]
            else: # 'all'
                filtered = [d for d in data if d]

            if len(filtered) < 2: return None, f"Túl kevés adat a(z) '{account_display_name} / {title_period}' időszakban."
            
            all_equity_values = [float(p['value']) for p in filtered]
            if min(all_equity_values) == max(all_equity_values): return None, f"Az egyenleg nem változott a '{title_period}' időszakban."

            plt.style.use('dark_background'); fig, ax = plt.subplots(figsize=(12, 6))
            x_indices = list(range(len(all_equity_values)))
            ax.plot(x_indices, all_equity_values, color='#00aaff', linewidth=2)
            ax.fill_between(x_indices, all_equity_values, color='#00aaff', alpha=0.1)
            
            target_tz = timezone(timedelta(hours=2))
            
            num_ticks = min(len(x_indices), 8); tick_indices = [int(i) for i in _linspace(0, len(x_indices) - 1, num_ticks)]
            tick_labels = [datetime.fromtimestamp(filtered[i]['time'], tz=timezone.utc).astimezone(target_tz).strftime('%m-%d\n%H:%M') for i in tick_indices]
            ax.set_xticks(tick_indices); ax.set_xticklabels(tick_labels, rotation=0, color='lightgray')

            min_equity, max_equity = min(all_equity_values), max(all_equity_values)
            y_range = max_equity - min_equity; buffer = y_range * 0.1 or 1.0
            ax.set_ylim(min_equity - buffer, max_equity + buffer)
            
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

    def _generate_daily_pnl_barchart(self, pnl_data, account_display_name, period):
        """Legenerálja a napokra bontott PNL oszlopdiagramot."""
        import matplotlib.pyplot as plt
        
        try:
            raw_history = pnl_data.get(account_display_name, {}).get('raw_history', [])
            if not raw_history:
                return None, f"Nincsenek elérhető előzmény adatok a(z) '{account_display_name}' fiókhoz."

            daily_pnl = defaultdict(float)
            for trade in raw_history:
                day_str = datetime.fromtimestamp(int(trade['createdTime']) / 1000, tz=timezone.utc).strftime('%Y-%m-%d')
                daily_pnl[day_str] += float(trade.get('closedPnl', 0))

            days_map = {'weekly': 7, 'monthly': 30}
            title_map = {'weekly': 'Utolsó 7 nap', 'monthly': 'Utolsó 30 nap', 'all': 'Teljes időszak'}
            title_period = title_map.get(period)
            
            today = datetime.now(timezone.utc).date()
            if period in days_map:
                start_date = today - timedelta(days=days_map[period] -1)
                all_days = [start_date + timedelta(days=i) for i in range(days_map[period])]
            else: # 'all'
                sorted_dates_str = sorted(daily_pnl.keys())
                if not sorted_dates_str: return None, f"Nincs PnL adat a(z) '{account_display_name}' fiókhoz."
                start_date = datetime.strptime(sorted_dates_str[0], '%Y-%m-%d').date()
                all_days = [start_date + timedelta(days=i) for i in range((today - start_date).days + 1)]

            labels = [day.strftime('%m-%d') for day in all_days]
            values = [daily_pnl.get(day.strftime('%Y-%m-%d'), 0) for day in all_days]

            if not any(v != 0 for v in values):
                return None, f"Nincs realizált PnL a(z) '{account_display_name} / {title_period}' időszakban."
            
            plt.style.use('dark_background'); fig, ax = plt.subplots(figsize=(12, 7))
            colors = ['#2ca02c' if v >= 0 else '#d62728' for v in values]
            bars = ax.bar(labels, values, color=colors)
            
            ax.set_title(f'Napi Realizált PnL - {account_display_name} ({title_period})', fontsize=16, color='white', pad=20)
            ax.set_ylabel('PnL (USDT)', color='white')
            ax.grid(True, axis='y', linestyle='--', linewidth=0.4, color='gray')
            ax.axhline(0, color='gray', linewidth=0.8)
            plt.setp(ax.spines.values(), color='gray')
            ax.set_facecolor('#1e1e1e'); fig.set_facecolor('#101010')
            ax.tick_params(axis='x', labelrotation=45, colors='lightgray')
            ax.tick_params(axis='y', colors='white')
            
            fig.tight_layout()
            buf = io.BytesIO(); plt.savefig(buf, format='png', dpi=100); buf.seek(0); plt.close(fig)

            total_pnl = sum(values)
            caption = (f"🗓️ *Napi PnL Riport - {account_display_name} ({title_period})*\n"
                       f"Összesített PnL: `${total_pnl:,.2f}`")
            return buf, caption

        except Exception as e:
            logger.error(f"Hiba a napi PnL oszlopdiagram generálása közben: {e}", exc_info=True)
            return None, "Belső hiba történt a grafikon generálásakor."

    async def cancel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Megszakítja a beszélgetést."""
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
        from telegram import Update as TelegramUpdate, InlineKeyboardButton, InlineKeyboardMarkup
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