"""
Copytrader v2 - Custom Exception Hierarchy
Complete exception system for precise error handling and recovery
"""
from typing import Optional, Dict, Any, Union
import traceback

class CopytraderError(Exception):
    """Base exception for all Copytrader-related errors"""
    
    def __init__(self, message: str, error_code: Optional[str] = None, context: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.message = message
        self.error_code = error_code
        self.context = context or {}
        self.timestamp = self._get_timestamp()
    
    def _get_timestamp(self) -> str:
        """Get current timestamp"""
        from datetime import datetime
        return datetime.utcnow().isoformat()
    
    def __str__(self) -> str:
        parts = [self.message]
        if self.error_code:
            parts.append(f"Code: {self.error_code}")
        if self.context:
            parts.append(f"Context: {self.context}")
        return " | ".join(parts)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert exception to dictionary for logging/reporting"""
        return {
            'type': self.__class__.__name__,
            'message': self.message,
            'error_code': self.error_code,
            'context': self.context,
            'timestamp': self.timestamp,
            'traceback': traceback.format_exc()
        }

# Configuration related exceptions
class ConfigurationError(CopytraderError):
    """Raised when there are configuration-related issues"""
    pass

class MissingConfigurationError(ConfigurationError):
    """Raised when required configuration is missing"""
    pass

class InvalidConfigurationError(ConfigurationError):
    """Raised when configuration values are invalid"""
    pass

# API related exceptions  
class APIError(CopytraderError):
    """Base class for API-related errors"""
    pass

class APIConnectionError(APIError):
    """Raised when API connection fails"""
    pass

class APIAuthenticationError(APIError):
    """Raised when API authentication fails"""
    pass

class APIRateLimitError(APIError):
    """Raised when API rate limits are exceeded"""
    pass

class APINetworkError(APIError):
    """Raised when network-related API errors occur"""
    pass

class APIResponseError(APIError):
    """Raised when API returns unexpected response format"""
    pass

class APITimeoutError(APIError):
    """Raised when API requests timeout"""
    pass

# Trading related exceptions
class TradingError(CopytraderError):
    """Base class for trading-related errors"""
    pass

class OrderExecutionError(TradingError):
    """Raised when order execution fails"""
    pass

class InsufficientBalanceError(TradingError):
    """Raised when account has insufficient balance"""
    pass

class InvalidPositionError(TradingError):
    """Raised when position operations are invalid"""
    pass

class RiskManagementError(TradingError):
    """Raised when risk management rules are violated"""
    pass

class PositionNotFoundError(TradingError):
    """Raised when expected position is not found"""
    pass

class OrderNotFoundError(TradingError):
    """Raised when expected order is not found"""
    pass

# Synchronization related exceptions
class SynchronizationError(CopytraderError):
    """Base class for synchronization-related errors"""
    pass

class PositionSyncError(SynchronizationError):
    """Raised when position synchronization fails"""
    pass

class OrderSyncError(SynchronizationError):
    """Raised when order synchronization fails"""
    pass

class DataSyncError(SynchronizationError):
    """Raised when data synchronization fails"""
    pass

class SyncTimeoutError(SynchronizationError):
    """Raised when synchronization operations timeout"""
    pass

# Authentication related exceptions
class AuthenticationError(CopytraderError):
    """Base class for authentication-related errors"""
    pass

class UnauthorizedAccessError(AuthenticationError):
    """Raised when unauthorized access is attempted"""
    pass

class SessionExpiredError(AuthenticationError):
    """Raised when user session has expired"""
    pass

class RateLimitExceededError(AuthenticationError):
    """Raised when rate limits are exceeded"""
    pass

# Telegram related exceptions
class TelegramError(CopytraderError):
    """Base class for Telegram-related errors"""
    pass

class TelegramBotError(TelegramError):
    """Raised when Telegram bot operations fail"""
    pass

class TelegramMessageError(TelegramError):
    """Raised when Telegram message operations fail"""
    pass

class TelegramConfigurationError(TelegramError):
    """Raised when Telegram configuration is invalid"""
    pass

# Data related exceptions
class DataError(CopytraderError):
    """Base class for data-related errors"""
    pass

class DataValidationError(DataError):
    """Raised when data validation fails"""
    pass

class DataSerializationError(DataError):
    """Raised when data serialization/deserialization fails"""
    pass

class FileOperationError(DataError):
    """Raised when file operations fail"""
    pass

class DatabaseError(DataError):
    """Raised when database operations fail"""
    pass

# Recovery strategies
class RecoveryError(CopytraderError):
    """Raised when error recovery fails"""
    pass

class MaxRetriesExceededError(CopytraderError):
    """Raised when maximum retry attempts are exceeded"""
    pass

# Reporting and monitoring exceptions
class ReportingError(CopytraderError):
    """Base class for reporting-related errors"""
    pass

class ChartGenerationError(ReportingError):
    """Raised when chart generation fails"""
    pass

class ReportGenerationError(ReportingError):
    """Raised when report generation fails"""
    pass

# Security related exceptions
class SecurityError(CopytraderError):
    """Base class for security-related errors"""
    pass

class EncryptionError(SecurityError):
    """Raised when encryption/decryption fails"""
    pass

class ValidationError(SecurityError):
    """Raised when input validation fails"""
    pass

def handle_exception_with_context(
    exception: Exception, 
    context: Dict[str, Any], 
    logger=None
) -> CopytraderError:
    """
    Convert a generic exception to a Copytrader-specific exception with context.
    
    Args:
        exception: The original exception
        context: Additional context information
        logger: Optional logger instance
        
    Returns:
        CopytraderError with context
    """
    error_message = str(exception)
    error_type = type(exception).__name__
    
    # Map common exceptions to specific Copytrader exceptions
    exception_mapping = {
        'ConnectionError': APIConnectionError,
        'TimeoutError': APITimeoutError,
        'ValueError': DataValidationError,
        'KeyError': ConfigurationError,
        'FileNotFoundError': FileOperationError,
        'PermissionError': FileOperationError,
        'JSONDecodeError': DataSerializationError,
        'HTTPError': APIError,
        'RequestException': APINetworkError,
    }
    
    exception_class = exception_mapping.get(error_type, CopytraderError)
    
    # Create new exception with context
    new_exception = exception_class(
        message=f"{error_type}: {error_message}",
        error_code=error_type,
        context=context
    )
    
    if logger:
        logger.error(f"Exception converted: {new_exception.to_dict()}")
    
    return new_exception

def create_error_context(
    operation: str,
    user_id: Optional[Union[str, int]] = None,
    symbol: Optional[str] = None,
    account: Optional[str] = None,
    **kwargs
) -> Dict[str, Any]:
    """
    Create standardized error context dictionary.
    
    Args:
        operation: The operation being performed
        user_id: Optional user ID
        symbol: Optional trading symbol
        account: Optional account identifier
        **kwargs: Additional context fields
        
    Returns:
        Context dictionary
    """
    from datetime import datetime
    
    context = {
        'operation': operation,
        'timestamp': datetime.utcnow().isoformat()
    }
    
    if user_id is not None:
        context['user_id'] = str(user_id)
    if symbol is not None:
        context['symbol'] = symbol
    if account is not None:
        context['account'] = account
        
    context.update(kwargs)
    return context

class ErrorRecoveryManager:
    """Manages error recovery strategies"""
    
    def __init__(self, max_retries: int = 3, base_delay: float = 1.0):
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.retry_counts = {}
    
    def should_retry(self, operation: str, exception: Exception) -> bool:
        """Determine if an operation should be retried"""
        retry_count = self.retry_counts.get(operation, 0)
        
        if retry_count >= self.max_retries:
            return False
        
        # Don't retry certain types of errors
        non_retryable = (
            AuthenticationError,
            ConfigurationError,
            ValidationError,
            InvalidConfigurationError
        )
        
        if isinstance(exception, non_retryable):
            return False
        
        return True
    
    def get_retry_delay(self, operation: str) -> float:
        """Get delay before retry (exponential backoff)"""
        retry_count = self.retry_counts.get(operation, 0)
        return self.base_delay * (2 ** retry_count)
    
    def record_retry(self, operation: str):
        """Record a retry attempt"""
        self.retry_counts[operation] = self.retry_counts.get(operation, 0) + 1
    
    def reset_retries(self, operation: str):
        """Reset retry count for successful operation"""
        self.retry_counts.pop(operation, None)