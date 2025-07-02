"""
Enhanced main entry point for Copytrader with improved process management.
"""
import os
import sys
import signal
import time
import logging
from typing import List, Dict, Any, Optional
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed
import multiprocessing
from multiprocessing import Process, Event, Queue, Manager

from modules.config_loader import get_all_users, load_configuration, is_master, is_user
from modules.logger_setup import setup_logging, send_admin_alert
from modules.exceptions import (
    ConfigurationError, 
    handle_exception_with_context, 
    create_error_context
)

DATA_DIR = Path(__file__).resolve().parent / "data"

# Global shutdown event
shutdown_event = multiprocessing.Event()
process_status = multiprocessing.Manager().dict()

class ProcessManager:
    """Enhanced process manager with recovery and monitoring"""
    
    def __init__(self):
        self.processes: Dict[str, Process] = {}
        self.process_info: Dict[str, Dict[str, Any]] = {}
        self.shutdown_requested = False
        self.max_restart_attempts = 3
        self.restart_delay = 5  # seconds
        
    def start_user_process(self, nickname: str) -> bool:
        """Start a process for a specific user with error handling"""
        try:
            config = load_configuration(nickname)
            if not config:
                error_msg = f"Failed to load configuration for user: {nickname}"
                logging.error(error_msg)
                send_admin_alert(error_msg, user=nickname)
                return False
                
            # Create process with proper error handling
            process = Process(
                target=safe_run_for_user,
                args=(nickname, shutdown_event),
                name=f"CopyTrader-{nickname}",
                daemon=False  # Changed from daemon=True for proper cleanup
            )
            
            process.start()
            
            self.processes[nickname] = process
            self.process_info[nickname] = {
                'start_time': time.time(),
                'restart_count': 0,
                'status': 'running',
                'pid': process.pid
            }
            
            process_status[nickname] = 'started'
            logging.info(f"Process started for user {nickname} (PID: {process.pid})")
            return True
            
        except Exception as e:
            context = create_error_context(
                operation='start_user_process',
                nickname=nickname
            )
            handled_error = handle_exception_with_context(e, context, logging.getLogger())
            logging.error(f"Failed to start process for {nickname}: {handled_error}")
            send_admin_alert(f"Failed to start process for {nickname}: {str(e)}", user=nickname)
            return False
    
    def monitor_processes(self) -> None:
        """Monitor running processes and restart if needed"""
        while not self.shutdown_requested:
            try:
                for nickname, process in list(self.processes.items()):
                    if not process.is_alive():
                        exit_code = process.exitcode
                        info = self.process_info[nickname]
                        
                        logging.warning(f"Process for {nickname} died with exit code {exit_code}")
                        
                        # Check if we should restart
                        if (info['restart_count'] < self.max_restart_attempts and 
                            not self.shutdown_requested):
                            
                            logging.info(f"Restarting process for {nickname} "
                                       f"(attempt {info['restart_count'] + 1}/{self.max_restart_attempts})")
                            
                            # Wait before restart
                            time.sleep(self.restart_delay)
                            
                            # Remove dead process
                            del self.processes[nickname]
                            
                            # Restart
                            if self.start_user_process(nickname):
                                self.process_info[nickname]['restart_count'] += 1
                            else:
                                logging.error(f"Failed to restart process for {nickname}")
                                send_admin_alert(f"Failed to restart process for {nickname}", user=nickname)
                        else:
                            logging.error(f"Max restart attempts reached for {nickname}")
                            send_admin_alert(f"Max restart attempts reached for {nickname}", user=nickname)
                            del self.processes[nickname]
                            process_status[nickname] = 'failed'
                
                time.sleep(10)  # Check every 10 seconds
                
            except Exception as e:
                logging.error(f"Error in process monitor: {e}", exc_info=True)
                time.sleep(5)
    
    def graceful_shutdown(self, timeout: int = 30) -> None:
        """Gracefully shutdown all processes"""
        logging.info("Initiating graceful shutdown...")
        self.shutdown_requested = True
        shutdown_event.set()
        
        # Send shutdown signal to all processes
        for nickname, process in self.processes.items():
            try:
                if process.is_alive():
                    logging.info(f"Sending shutdown signal to {nickname} (PID: {process.pid})")
                    process.terminate()
            except Exception as e:
                logging.error(f"Error terminating process {nickname}: {e}")
        
        # Wait for processes to finish gracefully
        start_time = time.time()
        while time.time() - start_time < timeout:
            alive_processes = [p for p in self.processes.values() if p.is_alive()]
            if not alive_processes:
                break
            time.sleep(1)
        
        # Force kill any remaining processes
        for nickname, process in self.processes.items():
            try:
                if process.is_alive():
                    logging.warning(f"Force killing process {nickname}")
                    process.kill()
                    process.join(timeout=5)
            except Exception as e:
                logging.error(f"Error force killing process {nickname}: {e}")
        
        logging.info("Shutdown complete")

def safe_run_for_user(nickname: str, shutdown_event: Event) -> None:
    """
    Safely run user process with proper error handling and shutdown support.
    """
    logger = None
    try:
        # Load configuration
        config = load_configuration(nickname)
        if not config:
            raise ConfigurationError(f"Failed to load configuration for {nickname}")
        
        # Setup logging for this process
        log_dir = DATA_DIR / "users" / nickname / "logs"
        setup_logging(config, log_dir=log_dir)
        logger = logging.getLogger()
        
        logger.info(f"Starting process for user: {nickname}")
        process_status[nickname] = 'initializing'
        
        # Main process loop
        while not shutdown_event.is_set():
            try:
                if is_master({'account_type': config['settings'].get('account_type', '')}):
                    logger.debug("Running master account logic")
                    # Master account logic here
                    
                elif is_user({'account_type': config['settings'].get('account_type', '')}):
                    logger.debug("Running user account logic")
                    # User account logic here
                    
                else:
                    raise ConfigurationError(f"Unknown account type for {nickname}")
                
                process_status[nickname] = 'running'
                
                # Check for shutdown every second
                if shutdown_event.wait(timeout=1):
                    break
                    
            except KeyboardInterrupt:
                logger.info("Keyboard interrupt received")
                break
            except Exception as e:
                context = create_error_context(
                    operation='user_process_loop',
                    nickname=nickname
                )
                handled_error = handle_exception_with_context(e, context, logger)
                logger.error(f"Error in user process loop: {handled_error}")
                
                # Wait before continuing to avoid tight error loops
                if not shutdown_event.wait(timeout=5):
                    continue
                else:
                    break
        
        logger.info(f"Process for {nickname} shutting down gracefully")
        process_status[nickname] = 'stopped'
        
    except Exception as e:
        error_msg = f"Critical error in process for {nickname}: {e}"
        if logger:
            logger.critical(error_msg, exc_info=True)
        else:
            print(error_msg)  # Fallback if logging not setup
        
        send_admin_alert(error_msg, user=nickname)
        process_status[nickname] = 'error'
        raise

def setup_signal_handlers(process_manager: ProcessManager) -> None:
    """Setup signal handlers for graceful shutdown"""
    def signal_handler(signum, frame):
        try:
            signal_name = signal.Signals(signum).name
        except (ValueError, AttributeError):
            signal_name = f"Signal-{signum}"
        logging.info(f"Received signal {signal_name}, initiating shutdown...")
        process_manager.graceful_shutdown()
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Windows doesn't have SIGHUP
    if hasattr(signal, 'SIGHUP'):
        signal.signal(signal.SIGHUP, signal_handler)

def main() -> None:
    """Enhanced main function with proper process management"""
    # Setup basic logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(DATA_DIR / "logs" / "main.log")
        ]
    )
    
    logger = logging.getLogger(__name__)
    logger.info("=== Copytrader v2 Starting ===")
    
    try:
        # Get all users
        users = get_all_users()
        if not users:
            error_msg = "No users found in users.json!"
            logger.error(error_msg)
            send_admin_alert(error_msg, user=None, account=None)
            return
        
        logger.info(f"Found {len(users)} users to process")
        
        # Create process manager
        process_manager = ProcessManager()
        
        # Setup signal handlers
        setup_signal_handlers(process_manager)
        
        # Start processes for all users
        started_processes = 0
        for user in users:
            nickname = user.get('nickname')
            if not nickname:
                logger.warning("User without nickname found, skipping")
                continue
                
            if process_manager.start_user_process(nickname):
                started_processes += 1
            else:
                logger.error(f"Failed to start process for {nickname}")
        
        if started_processes == 0:
            logger.error("No processes started successfully")
            return
        
        logger.info(f"Started {started_processes} processes successfully")
        
        # Start monitoring
        monitor_process = Process(
            target=process_manager.monitor_processes,
            name="ProcessMonitor"
        )
        monitor_process.start()
        
        try:
            # Wait for all processes to complete or shutdown signal
            for nickname, process in process_manager.processes.items():
                process.join()
            
            monitor_process.terminate()
            monitor_process.join(timeout=5)
            
        except KeyboardInterrupt:
            logger.info("Keyboard interrupt in main, shutting down...")
            process_manager.graceful_shutdown()
            
    except Exception as e:
        context = create_error_context(operation='main')
        handled_error = handle_exception_with_context(e, context, logger)
        logger.critical(f"Critical error in main: {handled_error}")
        send_admin_alert(f"Critical error in main: {str(e)}", user=None, account=None)
        sys.exit(1)
    
    logger.info("=== Copytrader v2 Shutdown Complete ===")

if __name__ == "__main__":
    # Ensure proper multiprocessing setup
    multiprocessing.freeze_support()
    main() 