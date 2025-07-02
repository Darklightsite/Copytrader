"""
Copytrader v2 - Main Application Entry Point
Production-ready cryptocurrency copy trading bot for Bybit
"""
import asyncio
import signal
import sys
import logging
from pathlib import Path
from typing import Dict, List, Optional
import multiprocessing
from concurrent.futures import ProcessPoolExecutor
import time

from modules.logger import setup_logging, get_logger
from modules.file_utils import ensure_directory_structure, load_account_configs
from modules.api_handler import BybitAPIHandler
from modules.sync_logic import SyncManager
from modules.reporting_manager import ReportingManager
from modules.security import SecurityManager
from modules.exceptions import CopytraderError, ConfigurationError
from telegram_bot.telegram_bot import TelegramBot

# Global shutdown event
shutdown_event = multiprocessing.Event()

class CopytraderApplication:
    """Main application orchestrator"""
    
    def __init__(self):
        self.logger = None
        self.accounts = {}
        self.sync_managers = {}
        self.telegram_bot = None
        self.reporting_manager = None
        self.running = False
        
    async def initialize(self):
        """Initialize the application"""
        try:
            # Setup directory structure
            ensure_directory_structure()
            
            # Setup logging
            setup_logging()
            self.logger = get_logger('main')
            self.logger.info("🚀 Copytrader v2 starting up...")
            
            # Load account configurations
            self.accounts = load_account_configs()
            if not self.accounts:
                raise ConfigurationError("No accounts found in data/accounts/")
            
            self.logger.info(f"Loaded {len(self.accounts)} accounts")
            
            # Initialize security manager
            SecurityManager.initialize()
            
            # Initialize reporting manager
            self.reporting_manager = ReportingManager()
            await self.reporting_manager.initialize()
            
            # Initialize sync managers for each account pair
            await self._initialize_sync_managers()
            
            # Initialize Telegram bot
            await self._initialize_telegram_bot()
            
            self.logger.info("✅ Copytrader v2 initialized successfully")
            
        except Exception as e:
            if self.logger:
                self.logger.critical(f"Failed to initialize application: {e}", exc_info=True)
            else:
                print(f"CRITICAL: Failed to initialize application: {e}")
            raise
    
    async def _initialize_sync_managers(self):
        """Initialize synchronization managers"""
        master_accounts = [acc for acc in self.accounts.values() if acc.get('role') == 'master']
        slave_accounts = [acc for acc in self.accounts.values() if acc.get('role') == 'slave']
        
        if not master_accounts:
            raise ConfigurationError("No master account found")
        if not slave_accounts:
            raise ConfigurationError("No slave accounts found")
            
        for master in master_accounts:
            for slave in slave_accounts:
                sync_key = f"{master['nickname']}->{slave['nickname']}"
                sync_manager = SyncManager(master, slave)
                await sync_manager.initialize()
                self.sync_managers[sync_key] = sync_manager
                
        self.logger.info(f"Initialized {len(self.sync_managers)} sync pairs")
    
    async def _initialize_telegram_bot(self):
        """Initialize Telegram bot"""
        try:
            self.telegram_bot = TelegramBot(
                accounts=self.accounts,
                sync_managers=self.sync_managers,
                reporting_manager=self.reporting_manager
            )
            await self.telegram_bot.initialize()
            self.logger.info("📱 Telegram bot initialized")
        except Exception as e:
            self.logger.error(f"Failed to initialize Telegram bot: {e}")
            # Continue without Telegram bot if it fails
    
    async def run(self):
        """Main application loop"""
        self.running = True
        self.logger.info("🔄 Starting main application loop")
        
        try:
            # Start Telegram bot in background
            if self.telegram_bot:
                asyncio.create_task(self.telegram_bot.start())
            
            # Main sync loop
            while self.running and not shutdown_event.is_set():
                try:
                    # Run sync cycles for all pairs
                    for sync_key, sync_manager in self.sync_managers.items():
                        if shutdown_event.is_set():
                            break
                            
                        try:
                            await sync_manager.run_sync_cycle()
                        except Exception as e:
                            self.logger.error(f"Sync error for {sync_key}: {e}")
                    
                    # Update reports
                    try:
                        await self.reporting_manager.update_all_reports()
                    except Exception as e:
                        self.logger.error(f"Reporting error: {e}")
                    
                    # Sleep before next cycle
                    await asyncio.sleep(10)  # 10 second cycle
                    
                except Exception as e:
                    self.logger.error(f"Error in main loop: {e}", exc_info=True)
                    await asyncio.sleep(30)  # Longer wait on error
                    
        except KeyboardInterrupt:
            self.logger.info("Keyboard interrupt received")
        except Exception as e:
            self.logger.critical(f"Critical error in main loop: {e}", exc_info=True)
        finally:
            await self.shutdown()
    
    async def shutdown(self):
        """Graceful shutdown"""
        self.logger.info("🛑 Shutting down Copytrader v2...")
        self.running = False
        shutdown_event.set()
        
        # Shutdown sync managers
        for sync_manager in self.sync_managers.values():
            try:
                await sync_manager.shutdown()
            except Exception as e:
                self.logger.error(f"Error shutting down sync manager: {e}")
        
        # Shutdown Telegram bot
        if self.telegram_bot:
            try:
                await self.telegram_bot.shutdown()
            except Exception as e:
                self.logger.error(f"Error shutting down Telegram bot: {e}")
        
        # Shutdown reporting
        if self.reporting_manager:
            try:
                await self.reporting_manager.shutdown()
            except Exception as e:
                self.logger.error(f"Error shutting down reporting: {e}")
        
        self.logger.info("✅ Copytrader v2 shutdown complete")

def setup_signal_handlers(app: CopytraderApplication):
    """Setup signal handlers for graceful shutdown"""
    def signal_handler(signum, frame):
        print(f"\nReceived signal {signum}, initiating shutdown...")
        shutdown_event.set()
        
        # Run shutdown in event loop
        loop = asyncio.get_event_loop()
        if loop.is_running():
            loop.create_task(app.shutdown())
        else:
            asyncio.run(app.shutdown())
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Windows doesn't have SIGHUP
    if hasattr(signal, 'SIGHUP'):
        signal.signal(signal.SIGHUP, signal_handler)

async def main():
    """Main entry point"""
    app = CopytraderApplication()
    
    try:
        # Setup signal handlers
        setup_signal_handlers(app)
        
        # Initialize and run
        await app.initialize()
        await app.run()
        
    except KeyboardInterrupt:
        print("\nKeyboard interrupt received")
    except Exception as e:
        print(f"FATAL ERROR: {e}")
        sys.exit(1)

if __name__ == "__main__":
    # Ensure proper multiprocessing setup
    multiprocessing.freeze_support()
    
    # Run the application
    asyncio.run(main())