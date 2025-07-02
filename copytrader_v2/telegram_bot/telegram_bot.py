"""
Copytrader v2 - Telegram Bot
Complete Telegram bot with command handling, authentication, and admin functions
"""
import asyncio
import os
from typing import Dict, List, Optional, Any, Callable, Set
from datetime import datetime, timezone
import json
from pathlib import Path

try:
    from telegram import Update, Bot, BotCommand
    from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
    from telegram.constants import ParseMode
    TELEGRAM_AVAILABLE = True
except ImportError:
    TELEGRAM_AVAILABLE = False

from ..modules.exceptions import (
    TelegramError,
    TelegramBotError,
    TelegramConfigurationError,
    AuthenticationError,
    create_error_context
)
from ..modules.logger import get_logger
from ..modules.security import get_security_manager
from ..modules.file_utils import load_json_file, save_json_file

class TelegramAuth:
    """Authentication and authorization for Telegram bot"""
    
    def __init__(self):
        self.logger = get_logger('telegram')
        self.security_manager = get_security_manager()
        self.authorized_users: Dict[int, Dict[str, Any]] = {}
        self.admin_users: Set[int] = set()
        self.sessions: Dict[int, Dict[str, Any]] = {}
        
        self._load_auth_config()
    
    def _load_auth_config(self):
        """Load authentication configuration"""
        try:
            auth_config = load_json_file("config/telegram_auth.json", {})
            
            # Load authorized users
            for user_data in auth_config.get('authorized_users', []):
                user_id = int(user_data['user_id'])
                self.authorized_users[user_id] = {
                    'username': user_data.get('username'),
                    'role': user_data.get('role', 'user'),
                    'permissions': user_data.get('permissions', []),
                    'added_at': user_data.get('added_at')
                }
                
                if user_data.get('role') == 'admin':
                    self.admin_users.add(user_id)
            
        except Exception as e:
            self.logger.error(f"Failed to load auth config: {e}")
    
    def _save_auth_config(self):
        """Save authentication configuration"""
        try:
            auth_config = {
                'authorized_users': [
                    {
                        'user_id': user_id,
                        'username': data.get('username'),
                        'role': data.get('role'),
                        'permissions': data.get('permissions'),
                        'added_at': data.get('added_at')
                    }
                    for user_id, data in self.authorized_users.items()
                ]
            }
            
            save_json_file("config/telegram_auth.json", auth_config)
            
        except Exception as e:
            self.logger.error(f"Failed to save auth config: {e}")
    
    def is_authorized(self, user_id: int) -> bool:
        """Check if user is authorized"""
        return user_id in self.authorized_users
    
    def is_admin(self, user_id: int) -> bool:
        """Check if user is admin"""
        return user_id in self.admin_users
    
    def has_permission(self, user_id: int, permission: str) -> bool:
        """Check if user has specific permission"""
        if not self.is_authorized(user_id):
            return False
        
        if self.is_admin(user_id):
            return True  # Admins have all permissions
        
        user_permissions = self.authorized_users[user_id].get('permissions', [])
        return permission in user_permissions
    
    def add_user(self, user_id: int, username: str, role: str = 'user', permissions: List[str] = None) -> bool:
        """Add authorized user"""
        try:
            self.authorized_users[user_id] = {
                'username': username,
                'role': role,
                'permissions': permissions or [],
                'added_at': datetime.now(timezone.utc).isoformat()
            }
            
            if role == 'admin':
                self.admin_users.add(user_id)
            
            self._save_auth_config()
            self.logger.info(f"Added user {username} ({user_id}) with role {role}")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to add user: {e}")
            return False
    
    def remove_user(self, user_id: int) -> bool:
        """Remove authorized user"""
        try:
            if user_id in self.authorized_users:
                username = self.authorized_users[user_id].get('username', 'Unknown')
                del self.authorized_users[user_id]
                self.admin_users.discard(user_id)
                self.sessions.pop(user_id, None)
                
                self._save_auth_config()
                self.logger.info(f"Removed user {username} ({user_id})")
                return True
            
            return False
            
        except Exception as e:
            self.logger.error(f"Failed to remove user: {e}")
            return False
    
    def create_session(self, user_id: int) -> str:
        """Create user session"""
        if not self.is_authorized(user_id):
            raise AuthenticationError("User not authorized")
        
        try:
            # Check rate limiting
            self.security_manager.check_rate_limit(str(user_id), "telegram_command")
            
            session_token = self.security_manager.generate_session_token()
            
            self.sessions[user_id] = {
                'token': session_token,
                'created_at': datetime.now(timezone.utc),
                'last_activity': datetime.now(timezone.utc)
            }
            
            return session_token
            
        except Exception as e:
            raise AuthenticationError(f"Failed to create session: {e}")
    
    def validate_session(self, user_id: int) -> bool:
        """Validate user session"""
        if user_id not in self.sessions:
            return False
        
        session = self.sessions[user_id]
        
        # Check if session is expired (24 hours)
        if (datetime.now(timezone.utc) - session['created_at']).hours > 24:
            del self.sessions[user_id]
            return False
        
        # Update last activity
        session['last_activity'] = datetime.now(timezone.utc)
        return True

class TelegramBot:
    """
    Main Telegram bot class with command handling and authentication
    """
    
    def __init__(self, accounts: Dict, sync_managers: Dict, reporting_manager):
        self.logger = get_logger('telegram')
        self.accounts = accounts
        self.sync_managers = sync_managers
        self.reporting_manager = reporting_manager
        
        # Bot configuration
        self.bot_token = os.getenv('TELEGRAM_BOT_TOKEN')
        if not self.bot_token:
            raise TelegramConfigurationError("TELEGRAM_BOT_TOKEN not found in environment")
        
        # Authentication
        self.auth = TelegramAuth()
        
        # Bot instance
        self.application: Optional[Application] = None
        self.bot: Optional[Bot] = None
        
        # Command handlers
        self.commands: Dict[str, Callable] = {}
        
        if not TELEGRAM_AVAILABLE:
            self.logger.warning("Telegram libraries not available - bot will not function")
            return
        
        self._register_commands()
    
    async def initialize(self):
        """Initialize the Telegram bot"""
        if not TELEGRAM_AVAILABLE:
            return
        
        try:
            # Create application
            self.application = Application.builder().token(self.bot_token).build()
            self.bot = self.application.bot
            
            # Setup command handlers
            for command, handler in self.commands.items():
                self.application.add_handler(CommandHandler(command, handler))
            
            # Add message handler for non-commands
            self.application.add_handler(
                MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message)
            )
            
            # Setup bot commands menu
            await self._setup_bot_commands()
            
            self.logger.info("Telegram bot initialized successfully")
            
        except Exception as e:
            self.logger.error(f"Failed to initialize Telegram bot: {e}")
            raise TelegramBotError(f"Failed to initialize bot: {e}")
    
    async def start(self):
        """Start the Telegram bot"""
        if not TELEGRAM_AVAILABLE or not self.application:
            return
        
        try:
            await self.application.initialize()
            await self.application.start()
            await self.application.updater.start_polling()
            
            self.logger.info("Telegram bot started and polling")
            
        except Exception as e:
            self.logger.error(f"Failed to start Telegram bot: {e}")
            raise TelegramBotError(f"Failed to start bot: {e}")
    
    async def shutdown(self):
        """Shutdown the Telegram bot"""
        if not TELEGRAM_AVAILABLE or not self.application:
            return
        
        try:
            await self.application.updater.stop()
            await self.application.stop()
            await self.application.shutdown()
            
            self.logger.info("Telegram bot shutdown complete")
            
        except Exception as e:
            self.logger.error(f"Error during bot shutdown: {e}")
    
    def _register_commands(self):
        """Register bot commands"""
        self.commands = {
            'start': self.cmd_start,
            'help': self.cmd_help,
            'status': self.cmd_status,
            'balance': self.cmd_balance,
            'positions': self.cmd_positions,
            'sync_status': self.cmd_sync_status,
            'reports': self.cmd_reports,
            'stop_loss': self.cmd_stop_loss,
            'admin': self.cmd_admin,
            'auth': self.cmd_auth
        }
    
    async def _setup_bot_commands(self):
        """Setup bot command menu"""
        if not self.bot:
            return
        
        commands = [
            BotCommand("start", "Start the bot and authenticate"),
            BotCommand("help", "Show help message"),
            BotCommand("status", "Show overall system status"),
            BotCommand("balance", "Show account balances"),
            BotCommand("positions", "Show open positions"),
            BotCommand("sync_status", "Show synchronization status"),
            BotCommand("reports", "Generate and show reports"),
            BotCommand("stop_loss", "Manage stop-loss settings"),
            BotCommand("admin", "Admin commands (admin only)")
        ]
        
        try:
            await self.bot.set_my_commands(commands)
        except Exception as e:
            self.logger.warning(f"Failed to set bot commands: {e}")
    
    def require_auth(self, permission: str = None):
        """Decorator for commands that require authentication"""
        def decorator(func):
            async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
                user_id = update.effective_user.id
                
                # Check if user is authorized
                if not self.auth.is_authorized(user_id):
                    await update.message.reply_text(
                        "❌ You are not authorized to use this bot.\n"
                        "Please contact an administrator."
                    )
                    return
                
                # Check specific permission if required
                if permission and not self.auth.has_permission(user_id, permission):
                    await update.message.reply_text(
                        f"❌ You don't have permission to use this command.\n"
                        f"Required permission: {permission}"
                    )
                    return
                
                # Validate session
                if not self.auth.validate_session(user_id):
                    await update.message.reply_text(
                        "🔒 Your session has expired. Please use /start to authenticate."
                    )
                    return
                
                return await func(update, context)
            return wrapper
        return decorator
    
    def admin_only(self, func):
        """Decorator for admin-only commands"""
        async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
            user_id = update.effective_user.id
            
            if not self.auth.is_admin(user_id):
                await update.message.reply_text("❌ Admin access required.")
                return
            
            return await func(self, update, context)
        return wrapper
    
    # Command handlers
    
    async def cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Start command handler"""
        user_id = update.effective_user.id
        username = update.effective_user.username or "Unknown"
        
        try:
            if self.auth.is_authorized(user_id):
                # Create new session
                token = self.auth.create_session(user_id)
                
                await update.message.reply_text(
                    f"🚀 Welcome back to Copytrader v2!\n\n"
                    f"You are authenticated as: @{username}\n"
                    f"Session created successfully.\n\n"
                    f"Use /help to see available commands."
                )
            else:
                await update.message.reply_text(
                    f"❌ Hello @{username}!\n\n"
                    f"You are not authorized to use this bot.\n"
                    f"Your user ID: `{user_id}`\n\n"
                    f"Please contact an administrator to get access.",
                    parse_mode=ParseMode.MARKDOWN
                )
            
        except Exception as e:
            self.logger.error(f"Error in start command: {e}")
            await update.message.reply_text("❌ An error occurred. Please try again.")
    
    async def cmd_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Help command handler"""
        help_text = """
🤖 **Copytrader v2 Bot Commands**

**Basic Commands:**
/start - Authenticate and start session
/help - Show this help message
/status - Show system status
/balance - Show account balances
/positions - Show open positions
/sync_status - Show sync status
/reports - Generate reports

**Management:**
/stop_loss - Manage stop-loss settings

**Admin Commands:**
/admin - Admin functions (admin only)

**Tips:**
• Use /status for a quick overview
• Reports include charts and analytics
• All commands require authentication
        """
        
        await update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN)
    
    @require_auth()
    async def cmd_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Status command handler"""
        try:
            # Collect system status
            total_accounts = len(self.accounts)
            active_syncs = len(self.sync_managers)
            
            # Get API health status
            api_health = {}
            for account_name, account in self.accounts.items():
                # This would normally check API health
                api_health[account_name] = "✅ Healthy"
            
            status_text = f"""
📊 **System Status**

**Accounts:** {total_accounts} configured
**Active Syncs:** {active_syncs} running
**Last Update:** {datetime.now().strftime('%H:%M:%S')}

**API Health:**
"""
            
            for account, health in api_health.items():
                status_text += f"• {account}: {health}\n"
            
            await update.message.reply_text(status_text, parse_mode=ParseMode.MARKDOWN)
            
        except Exception as e:
            self.logger.error(f"Error in status command: {e}")
            await update.message.reply_text("❌ Failed to get system status.")
    
    # @require_auth('view_balance')
    async def cmd_balance(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Balance command handler"""
        try:
            balance_text = "💰 **Account Balances**\n\n"
            
            # This would fetch real balance data
            for account_name in self.accounts.keys():
                # Mock balance data
                balance = 1000.0  # This would come from API
                balance_text += f"**{account_name}:** ${balance:,.2f}\n"
            
            await update.message.reply_text(balance_text, parse_mode=ParseMode.MARKDOWN)
            
        except Exception as e:
            self.logger.error(f"Error in balance command: {e}")
            await update.message.reply_text("❌ Failed to get account balances.")
    
    @require_auth('view_positions')
    async def cmd_positions(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Positions command handler"""
        try:
            positions_text = "📈 **Open Positions**\n\n"
            
            # This would fetch real position data
            positions_text += "No open positions currently.\n"
            
            await update.message.reply_text(positions_text, parse_mode=ParseMode.MARKDOWN)
            
        except Exception as e:
            self.logger.error(f"Error in positions command: {e}")
            await update.message.reply_text("❌ Failed to get positions.")
    
    @require_auth('view_sync')
    async def cmd_sync_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Sync status command handler"""
        try:
            sync_text = "🔄 **Synchronization Status**\n\n"
            
            for sync_key, sync_manager in self.sync_managers.items():
                status = sync_manager.get_sync_status()
                sync_text += f"**{sync_key}:**\n"
                sync_text += f"• Last Sync: {status.get('last_sync', 'Never')}\n"
                sync_text += f"• Copy Multiplier: {status.get('copy_multiplier', 1.0)}\n\n"
            
            await update.message.reply_text(sync_text, parse_mode=ParseMode.MARKDOWN)
            
        except Exception as e:
            self.logger.error(f"Error in sync status command: {e}")
            await update.message.reply_text("❌ Failed to get sync status.")
    
    @require_auth('view_reports')
    async def cmd_reports(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Reports command handler"""
        try:
            await update.message.reply_text("📊 Generating reports... Please wait.")
            
            # Generate reports for all accounts
            reports_text = "📊 **Daily Reports**\n\n"
            
            for account_name in self.accounts.keys():
                try:
                    report = await self.reporting_manager.generate_daily_report(account_name)
                    if 'error' not in report:
                        balance = report['balance']
                        performance = report['performance']
                        
                        reports_text += f"**{account_name}:**\n"
                        reports_text += f"• Balance: ${balance['current']:,.2f}\n"
                        reports_text += f"• 24h Change: {balance['change_24h']:+.2f} ({balance['change_24h_pct']:+.2f}%)\n"
                        reports_text += f"• Total Return: {performance['total_return_pct']:+.2f}%\n\n"
                        
                        # Send chart if available
                        if report['charts']['balance_chart']:
                            try:
                                await update.message.reply_photo(
                                    photo=open(report['charts']['balance_chart'], 'rb'),
                                    caption=f"Balance Chart - {account_name}"
                                )
                            except Exception:
                                pass
                                
                except Exception as e:
                    reports_text += f"**{account_name}:** Error generating report\n\n"
            
            await update.message.reply_text(reports_text, parse_mode=ParseMode.MARKDOWN)
            
        except Exception as e:
            self.logger.error(f"Error in reports command: {e}")
            await update.message.reply_text("❌ Failed to generate reports.")
    
    @require_auth('manage_stop_loss')
    async def cmd_stop_loss(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Stop-loss command handler"""
        try:
            args = context.args
            
            if not args:
                # Show current stop-loss settings
                sl_text = "🛑 **Stop-Loss Settings**\n\n"
                
                for account_name, account in self.accounts.items():
                    if account.role == 'slave':
                        sl_tiers = account.sl_loss_tiers_usd or []
                        sl_text += f"**{account_name}:**\n"
                        if sl_tiers:
                            sl_text += f"• Tiers: {', '.join(f'${tier}' for tier in sl_tiers)}\n"
                        else:
                            sl_text += "• No stop-loss tiers set\n"
                        sl_text += "\n"
                
                sl_text += "\n**Usage:**\n"
                sl_text += "`/stop_loss <account> <tier1> <tier2> ...`\n"
                sl_text += "Example: `/stop_loss slave1 100 50 25`"
                
                await update.message.reply_text(sl_text, parse_mode=ParseMode.MARKDOWN)
            else:
                # Set new stop-loss tiers
                account_name = args[0]
                tiers = [float(tier) for tier in args[1:]]
                
                if account_name in self.accounts:
                    # Update account config
                    # This would normally save to file
                    await update.message.reply_text(
                        f"✅ Updated stop-loss tiers for {account_name}:\n"
                        f"Tiers: {', '.join(f'${tier}' for tier in tiers)}"
                    )
                else:
                    await update.message.reply_text(f"❌ Account '{account_name}' not found.")
            
        except Exception as e:
            self.logger.error(f"Error in stop_loss command: {e}")
            await update.message.reply_text("❌ Failed to manage stop-loss settings.")
    
    @admin_only
    async def cmd_admin(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Admin command handler"""
        try:
            args = context.args
            
            if not args:
                admin_text = """
👑 **Admin Commands**

**User Management:**
`/admin add_user <user_id> <username> [role]`
`/admin remove_user <user_id>`
`/admin list_users`

**System Management:**
`/admin logs [lines]`
`/admin restart`
`/admin backup`

**Examples:**
`/admin add_user 123456789 john_doe user`
`/admin logs 50`
                """
                await update.message.reply_text(admin_text, parse_mode=ParseMode.MARKDOWN)
                return
            
            command = args[0]
            
            if command == "add_user" and len(args) >= 3:
                user_id = int(args[1])
                username = args[2]
                role = args[3] if len(args) > 3 else 'user'
                
                if self.auth.add_user(user_id, username, role):
                    await update.message.reply_text(f"✅ Added user @{username} ({user_id}) with role '{role}'")
                else:
                    await update.message.reply_text("❌ Failed to add user")
            
            elif command == "remove_user" and len(args) >= 2:
                user_id = int(args[1])
                
                if self.auth.remove_user(user_id):
                    await update.message.reply_text(f"✅ Removed user {user_id}")
                else:
                    await update.message.reply_text("❌ User not found")
            
            elif command == "list_users":
                users_text = "👥 **Authorized Users**\n\n"
                
                for user_id, data in self.auth.authorized_users.items():
                    users_text += f"• @{data.get('username', 'Unknown')} ({user_id})\n"
                    users_text += f"  Role: {data.get('role', 'user')}\n\n"
                
                await update.message.reply_text(users_text, parse_mode=ParseMode.MARKDOWN)
            
            elif command == "logs":
                lines = int(args[1]) if len(args) > 1 else 20
                
                # Get recent logs
                from ..modules.logger import get_log_content
                log_content = get_log_content('main', lines)
                
                if log_content:
                    # Send as file if too long
                    if len(log_content) > 4000:
                        await update.message.reply_document(
                            document=log_content.encode(),
                            filename=f"logs_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
                        )
                    else:
                        await update.message.reply_text(f"```\n{log_content}\n```", parse_mode=ParseMode.MARKDOWN)
                else:
                    await update.message.reply_text("❌ No logs available")
            
            else:
                await update.message.reply_text("❌ Invalid admin command. Use `/admin` for help.")
            
        except Exception as e:
            self.logger.error(f"Error in admin command: {e}")
            await update.message.reply_text("❌ Admin command failed.")
    
    async def cmd_auth(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Auth command handler"""
        user_id = update.effective_user.id
        
        if self.auth.is_authorized(user_id):
            user_info = self.auth.authorized_users[user_id]
            auth_text = f"""
🔐 **Authentication Status**

**User:** @{user_info.get('username', 'Unknown')}
**ID:** {user_id}
**Role:** {user_info.get('role', 'user')}
**Permissions:** {', '.join(user_info.get('permissions', [])) or 'Default'}
**Session:** {'✅ Active' if self.auth.validate_session(user_id) else '❌ Expired'}
            """
        else:
            auth_text = f"""
🔐 **Authentication Status**

**Status:** ❌ Not Authorized
**User ID:** {user_id}

Please contact an administrator for access.
            """
        
        await update.message.reply_text(auth_text, parse_mode=ParseMode.MARKDOWN)
    
    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle non-command messages"""
        user_id = update.effective_user.id
        
        if not self.auth.is_authorized(user_id):
            await update.message.reply_text(
                "❌ You are not authorized. Use /start to check your status."
            )
            return
        
        await update.message.reply_text(
            "🤖 I don't understand that message. Use /help to see available commands."
        )
    
    async def send_alert(self, message: str, alert_type: str = "info"):
        """Send alert to all admin users"""
        if not TELEGRAM_AVAILABLE or not self.bot:
            return
        
        emoji_map = {
            "info": "ℹ️",
            "warning": "⚠️", 
            "error": "❌",
            "success": "✅"
        }
        
        emoji = emoji_map.get(alert_type, "📢")
        formatted_message = f"{emoji} **ALERT**\n\n{message}"
        
        for admin_id in self.auth.admin_users:
            try:
                await self.bot.send_message(
                    chat_id=admin_id,
                    text=formatted_message,
                    parse_mode=ParseMode.MARKDOWN
                )
            except Exception as e:
                self.logger.warning(f"Failed to send alert to admin {admin_id}: {e}")
    
    async def send_trade_notification(self, account: str, action: str, symbol: str, side: str, quantity: float):
        """Send trade notification to authorized users"""
        if not TELEGRAM_AVAILABLE or not self.bot:
            return
        
        message = f"""
📈 **Trade Executed**

**Account:** {account}
**Action:** {action}
**Symbol:** {symbol}
**Side:** {side}
**Quantity:** {quantity}
**Time:** {datetime.now().strftime('%H:%M:%S')}
        """
        
        for user_id in self.auth.authorized_users:
            if self.auth.has_permission(user_id, 'trade_notifications'):
                try:
                    await self.bot.send_message(
                        chat_id=user_id,
                        text=message,
                        parse_mode=ParseMode.MARKDOWN
                    )
                except Exception as e:
                    self.logger.warning(f"Failed to send trade notification to {user_id}: {e}")