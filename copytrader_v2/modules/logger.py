"""
Copytrader v2 - Advanced Logging System
Comprehensive logging with structured output, file rotation, and error tracking
"""
import logging
import logging.handlers
import os
import sys
from pathlib import Path
from typing import Dict, Optional, Any
import json
from datetime import datetime, timezone
import traceback

from .exceptions import FileOperationError, create_error_context

class StructuredFormatter(logging.Formatter):
    """Custom formatter for structured JSON logging"""
    
    def format(self, record: logging.LogRecord) -> str:
        # Create base log entry
        log_entry = {
            'timestamp': datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            'level': record.levelname,
            'logger': record.name,
            'message': record.getMessage(),
            'module': record.module,
            'function': record.funcName,
            'line': record.lineno
        }
        
        # Add exception info if present
        if record.exc_info:
            log_entry['exception'] = {
                'type': record.exc_info[0].__name__ if record.exc_info[0] else None,
                'message': str(record.exc_info[1]) if record.exc_info[1] else None,
                'traceback': traceback.format_exception(*record.exc_info)
            }
        
        # Add extra fields if present
        if hasattr(record, 'extra_fields'):
            log_entry.update(record.extra_fields)
        
        return json.dumps(log_entry, ensure_ascii=False)

class CopytraderLogger:
    """Enhanced logger with context and structured output"""
    
    def __init__(self, name: str):
        self.logger = logging.getLogger(name)
        self.name = name
        self.context = {}
    
    def set_context(self, **kwargs):
        """Set persistent context for this logger"""
        self.context.update(kwargs)
    
    def clear_context(self):
        """Clear persistent context"""
        self.context.clear()
    
    def _log_with_context(self, level: int, message: str, extra: Optional[Dict[str, Any]] = None, **kwargs):
        """Log with context and extra fields"""
        combined_extra = dict(self.context)
        if extra:
            combined_extra.update(extra)
        combined_extra.update(kwargs)
        
        # Create a LogRecord with extra fields
        record = self.logger.makeRecord(
            self.logger.name, level, "", 0, message, (), None
        )
        record.extra_fields = combined_extra
        
        self.logger.handle(record)
    
    def debug(self, message: str, extra: Optional[Dict[str, Any]] = None, **kwargs):
        """Log debug message with context"""
        self._log_with_context(logging.DEBUG, message, extra, **kwargs)
    
    def info(self, message: str, extra: Optional[Dict[str, Any]] = None, **kwargs):
        """Log info message with context"""
        self._log_with_context(logging.INFO, message, extra, **kwargs)
    
    def warning(self, message: str, extra: Optional[Dict[str, Any]] = None, **kwargs):
        """Log warning message with context"""
        self._log_with_context(logging.WARNING, message, extra, **kwargs)
    
    def error(self, message: str, extra: Optional[Dict[str, Any]] = None, exc_info: bool = False, **kwargs):
        """Log error message with context"""
        if exc_info:
            kwargs['exception_info'] = traceback.format_exc()
        self._log_with_context(logging.ERROR, message, extra, **kwargs)
    
    def critical(self, message: str, extra: Optional[Dict[str, Any]] = None, exc_info: bool = False, **kwargs):
        """Log critical message with context"""
        if exc_info:
            kwargs['exception_info'] = traceback.format_exc()
        self._log_with_context(logging.CRITICAL, message, extra, **kwargs)

class LoggingManager:
    """Manages all logging configuration and file handlers"""
    
    def __init__(self, log_dir: Path):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        
        self.handlers: Dict[str, logging.Handler] = {}
        self.loggers: Dict[str, CopytraderLogger] = {}
        
        # Configure root logger
        self._setup_root_logger()
        
        # Setup module-specific loggers
        self._setup_module_loggers()
    
    def _setup_root_logger(self):
        """Setup root logger configuration"""
        root_logger = logging.getLogger()
        root_logger.setLevel(logging.DEBUG)
        
        # Remove default handlers
        for handler in root_logger.handlers[:]:
            root_logger.removeHandler(handler)
        
        # Console handler for immediate feedback
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.INFO)
        console_formatter = logging.Formatter(
            '%(asctime)s | %(name)-12s | %(levelname)-8s | %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        console_handler.setFormatter(console_formatter)
        
        root_logger.addHandler(console_handler)
    
    def _setup_module_loggers(self):
        """Setup loggers for specific modules"""
        log_configs = {
            'main': {'level': logging.INFO, 'structured': True},
            'api': {'level': logging.DEBUG, 'structured': True},
            'sync': {'level': logging.INFO, 'structured': True},
            'telegram': {'level': logging.INFO, 'structured': False},
            'error': {'level': logging.ERROR, 'structured': True},
            'trading': {'level': logging.INFO, 'structured': True},
            'reporting': {'level': logging.INFO, 'structured': True},
            'security': {'level': logging.WARNING, 'structured': True}
        }
        
        for log_name, config in log_configs.items():
            self._create_file_logger(log_name, config['level'], config['structured'])
    
    def _create_file_logger(self, name: str, level: int, structured: bool = True):
        """Create a file logger with rotation"""
        log_file = self.log_dir / f"{name}.log"
        
        # Rotating file handler (10MB max, 5 backups)
        handler = logging.handlers.RotatingFileHandler(
            log_file,
            maxBytes=10*1024*1024,  # 10MB
            backupCount=5,
            encoding='utf-8'
        )
        handler.setLevel(level)
        
        # Set formatter
        if structured:
            handler.setFormatter(StructuredFormatter())
        else:
            handler.setFormatter(logging.Formatter(
                '%(asctime)s | %(name)-12s | %(levelname)-8s | %(message)s',
                datefmt='%Y-%m-%d %H:%M:%S'
            ))
        
        # Create logger
        logger = logging.getLogger(name)
        logger.setLevel(level)
        logger.addHandler(handler)
        
        # Prevent propagation to avoid duplicate logs
        logger.propagate = False
        
        self.handlers[name] = handler
    
    def get_logger(self, name: str) -> CopytraderLogger:
        """Get or create a CopytraderLogger instance"""
        if name not in self.loggers:
            self.loggers[name] = CopytraderLogger(name)
        return self.loggers[name]
    
    def get_log_files(self) -> Dict[str, str]:
        """Get paths to all log files"""
        log_files = {}
        for name in self.handlers.keys():
            log_file = self.log_dir / f"{name}.log"
            if log_file.exists():
                log_files[name] = str(log_file)
        return log_files
    
    def get_log_content(self, log_name: str, max_lines: int = 100) -> Optional[str]:
        """Get recent content from a log file"""
        log_file = self.log_dir / f"{log_name}.log"
        
        if not log_file.exists():
            return None
        
        try:
            with open(log_file, 'r', encoding='utf-8') as f:
                lines = f.readlines()
                # Return last N lines
                return ''.join(lines[-max_lines:])
        except Exception as e:
            self.get_logger('error').error(f"Failed to read log file {log_name}: {e}")
            return None
    
    def clear_log(self, log_name: str) -> bool:
        """Clear a specific log file"""
        log_file = self.log_dir / f"{log_name}.log"
        
        try:
            if log_file.exists():
                log_file.write_text('', encoding='utf-8')
                return True
            return False
        except Exception as e:
            self.get_logger('error').error(f"Failed to clear log file {log_name}: {e}")
            return False
    
    def archive_logs(self) -> bool:
        """Archive old log files"""
        try:
            from datetime import datetime
            import shutil
            
            archive_dir = self.log_dir / "archive" / datetime.now().strftime("%Y%m%d_%H%M%S")
            archive_dir.mkdir(parents=True, exist_ok=True)
            
            for log_file in self.log_dir.glob("*.log"):
                if log_file.stat().st_size > 0:  # Only archive non-empty files
                    shutil.copy2(log_file, archive_dir / log_file.name)
                    log_file.write_text('', encoding='utf-8')  # Clear original
            
            return True
        except Exception as e:
            self.get_logger('error').error(f"Failed to archive logs: {e}")
            return False

# Global logging manager instance
_logging_manager: Optional[LoggingManager] = None

def setup_logging(log_dir: Optional[Path] = None):
    """Setup global logging configuration"""
    global _logging_manager
    
    if log_dir is None:
        log_dir = Path("data/logs")
    
    try:
        _logging_manager = LoggingManager(log_dir)
        
        # Log startup message
        logger = get_logger('main')
        logger.info("Logging system initialized", log_dir=str(log_dir))
        
    except Exception as e:
        print(f"CRITICAL: Failed to setup logging: {e}")
        raise FileOperationError(f"Failed to setup logging: {e}")

def get_logger(name: str) -> CopytraderLogger:
    """Get a logger instance"""
    global _logging_manager
    
    if _logging_manager is None:
        setup_logging()
    
    return _logging_manager.get_logger(name)

def get_log_content(log_name: str, max_lines: int = 100) -> Optional[str]:
    """Get content from a log file"""
    global _logging_manager
    
    if _logging_manager is None:
        return None
    
    return _logging_manager.get_log_content(log_name, max_lines)

def get_error_logs(max_lines: int = 50) -> Optional[str]:
    """Get recent error logs for admin alerts"""
    return get_log_content('error', max_lines)

def clear_log(log_name: str) -> bool:
    """Clear a specific log file"""
    global _logging_manager
    
    if _logging_manager is None:
        return False
    
    return _logging_manager.clear_log(log_name)

def archive_logs() -> bool:
    """Archive all log files"""
    global _logging_manager
    
    if _logging_manager is None:
        return False
    
    return _logging_manager.archive_logs()

# Utility functions for common logging patterns
def log_api_call(logger: CopytraderLogger, endpoint: str, method: str, status_code: Optional[int] = None, **kwargs):
    """Log API call with standard format"""
    logger.info(
        f"API {method} {endpoint}",
        endpoint=endpoint,
        method=method,
        status_code=status_code,
        **kwargs
    )

def log_trading_action(logger: CopytraderLogger, action: str, symbol: str, side: str, quantity: float, **kwargs):
    """Log trading action with standard format"""
    logger.info(
        f"Trading {action}: {side} {quantity} {symbol}",
        action=action,
        symbol=symbol,
        side=side,
        quantity=quantity,
        **kwargs
    )

def log_sync_event(logger: CopytraderLogger, event_type: str, master_account: str, slave_account: str, **kwargs):
    """Log synchronization event with standard format"""
    logger.info(
        f"Sync {event_type}: {master_account} -> {slave_account}",
        event_type=event_type,
        master_account=master_account,
        slave_account=slave_account,
        **kwargs
    )